"""Streamlit UI for Module 1 — Protection Network Diagnostic."""
import streamlit as st
import numpy as np
import pandas as pd
import geopandas as gpd
import folium
from streamlit_folium import st_folium
from pathlib import Path
import yaml
import tempfile
import logging

logger = logging.getLogger(__name__)


def load_iucn_classification():
    """
    Load IUCN classification colour scheme from config.

    Returns
    -------
    dict
        Dictionary mapping protection classes to colour codes and labels.
    """
    config_path = Path(__file__).parent.parent / "config" / "iucn_classification.yaml"

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        return config.get('classes', {})
    except FileNotFoundError:
        st.warning(f"IUCN classification config not found: {config_path}")
        return {}


def render_tab_module1(pa_gdf=None, territory_geom=None, ecosystem_layer=None):
    """
    Render Module 1 interface with WDPA loading, coverage stats, and gap analysis.

    Parameters
    ----------
    pa_gdf : gpd.GeoDataFrame, optional
        Protected areas GeoDataFrame with 'protection_class' column.
        If None, displays placeholder UI.
    territory_geom : shapely.geometry, optional
        Territory boundary geometry for statistics.
    ecosystem_layer : gpd.GeoDataFrame, optional
        Ecosystem types layer for representativity analysis.
    """
    st.header("Module 1 — Protected Area Network Diagnostic")

    # ===================================================================
    # Load WDPA and run analysis if not already done
    # ===================================================================
    wdpa_file = st.session_state.get('wdpa_file')
    territory_geom = st.session_state.get('territory_geom')
    pa_gdf = st.session_state.get('pa_gdf')

    if territory_geom is None:
        st.info("Select your study region in the sidebar (Country → NUTS2 region) first.")
        return

    if wdpa_file is None:
        st.info("Upload your WDPA protected areas file in the **① Data Upload** tab first.")
        return

    if pa_gdf is None:
        st.info("WDPA file loaded. Click the button below to run the diagnostic.")
        if st.button("▶ Run Protection Network Diagnostic", type="primary", width='stretch'):
            with st.spinner("Loading and classifying protected areas…"):
                try:
                    from modules.module1_protected_areas.wdpa_loader import (
                        load_wdpa_local, filter_to_extent, classify_iucn
                    )
                    import yaml
                    config_path = Path(__file__).parent.parent / "config" / "iucn_classification.yaml"
                    with open(config_path, 'r', encoding='utf-8') as f:
                        classification_table = yaml.safe_load(f)
                    gdf = load_wdpa_local(wdpa_file)
                    if st.session_state.get('exclude_marine_pa', True):
                        if 'REALM' in gdf.columns:
                            n_marine = int((gdf['REALM'] == 'Marine').sum())
                            gdf = gdf[gdf['REALM'] != 'Marine'].copy()
                            if n_marine:
                                st.info(f"Excluded {n_marine} fully marine PA(s) (REALM = 'Marine').")
                        elif 'MARINE' in gdf.columns:
                            # Fallback for older WDPA exports using integer MARINE column
                            n_marine = int((gdf['MARINE'] == 2).sum())
                            gdf = gdf[gdf['MARINE'] != 2].copy()
                            if n_marine:
                                st.info(f"Excluded {n_marine} fully marine PA(s) (MARINE = 2).")
                        else:
                            st.caption("Neither REALM nor MARINE column found in WDPA file — marine filter not applied.")
                    gdf = filter_to_extent(gdf, territory_geom)
                    gdf = classify_iucn(gdf, classification_table)
                    st.session_state['pa_gdf'] = gdf
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to load WDPA data: {e}")
                    logger.exception("WDPA load failed")
        return

    pa_gdf = st.session_state['pa_gdf']

    # Button to re-run with fresh data
    if st.button("↺ Re-run Diagnostic", width='content'):
        st.session_state.pop('pa_gdf', None)
        st.rerun()

    # Import module functions (only when data is available)
    from modules.module1_protected_areas.coverage_stats import (
        compute_net_area,
        coverage_by_class,
        kmgbf_indicator
    )
    from modules.module1_protected_areas.representativity import (
        cross_with_ecosystem_types,
        representativity_index,
        propose_group_a_weights
    )
    from modules.module1_protected_areas.gap_analysis import (
        strict_gaps,
        qualitative_gaps,
        potential_corridors
    )

    # Ensure data is in EPSG:3035
    if pa_gdf.crs != 'EPSG:3035':
        pa_gdf = pa_gdf.to_crs('EPSG:3035')

    # Compute territory area
    territory_area_ha = territory_geom.area / 10000.0

    # ===================================================================
    # Row 1: Metric cards
    # ===================================================================
    st.subheader("Key Indicators")

    col1, col2, col3, col4 = st.columns(4)

    # Metric 1: Net protected area
    net_area = compute_net_area(pa_gdf, territory_geom)

    with col1:
        st.metric(
            label="Net Protected Area",
            value=f"{net_area:,.0f} ha",
            help="Deduplicated area via geometric union (excludes overlaps)"
        )

    # Metric 2: % territory (KMGBF indicator)
    kmgbf_pct = kmgbf_indicator(pa_gdf, territory_area_ha)
    target_30 = 30.0

    with col2:
        delta = kmgbf_pct - target_30
        st.metric(
            label="% Territory Protected",
            value=f"{kmgbf_pct:.1f}%",
            delta=f"{delta:.1f}% vs 30% target",
            help="KMGBF Target 3: 30% strict protection (IUCN I-II) by 2030"
        )

    # Metric 3: Number of PA sites
    n_sites = len(pa_gdf)

    with col3:
        st.metric(
            label="Number of PA Sites",
            value=f"{n_sites:,}",
            help="Total number of protected area polygons"
        )

    # Metric 4: Synthetic RI index (if ecosystem layer available)
    with col4:
        if ecosystem_layer is not None:
            # Compute representativity index
            try:
                # Load defaults from config
                config_path = Path(__file__).parent.parent / "config" / "criteria_defaults.yaml"
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f)
                target_threshold = config.get('representativity', {}).get('default_target', 0.30)

                # Compute ecosystem totals
                if ecosystem_layer.crs != 'EPSG:3035':
                    ecosystem_layer = ecosystem_layer.to_crs('EPSG:3035')

                ecosystem_layer['area_ha'] = ecosystem_layer.geometry.area / 10000.0
                territory_totals = ecosystem_layer.groupby('ecosystem_type')['area_ha'].sum().to_dict()

                # Cross analysis
                coverage_df = cross_with_ecosystem_types(pa_gdf, ecosystem_layer)
                ri_df = representativity_index(coverage_df, territory_totals, target_threshold)

                synthetic_ri = ri_df['RI'].mean()

                # Determine colour
                if synthetic_ri >= 0.7:
                    ri_colour = "#1D9E75"  # Green
                    ri_label = "Good"
                elif synthetic_ri >= 0.3:
                    ri_colour = "#F6A623"  # Amber
                    ri_label = "Fair"
                else:
                    ri_colour = "#D0021B"  # Red
                    ri_label = "Poor"

                st.metric(
                    label="Synthetic RI",
                    value=f"{synthetic_ri:.2f}",
                    help=(
                        f"Representativity Index: {ri_label}\n"
                        "1.0 = all ecosystem types reach 30% target\n"
                        "<1.0 = under-representation"
                    )
                )

                # Store RI results in session state for later use
                st.session_state['ri_df'] = ri_df

            except Exception as e:
                st.metric(
                    label="Synthetic RI",
                    value="N/A",
                    help=f"Error computing RI: {str(e)}"
                )
        else:
            st.metric(
                label="Synthetic RI",
                value="N/A",
                help="Upload ecosystem layer to compute representativity index"
            )

    st.markdown("---")

    # ===================================================================
    # Row 2: Interactive folium map
    # ===================================================================
    st.subheader("Protected Area Network Map")

    # Load colour scheme
    iucn_classes = load_iucn_classification()

    # Reproject to EPSG:4326 for folium (needs lat/lon)
    import geopandas as gpd
    from shapely.geometry import mapping
    pa_gdf_4326 = pa_gdf.to_crs('EPSG:4326')
    territory_gs = gpd.GeoSeries([territory_geom], crs='EPSG:3035').to_crs('EPSG:4326')
    centroid = territory_gs.iloc[0].centroid

    m = folium.Map(
        location=[centroid.y, centroid.x],
        zoom_start=8,
        tiles='OpenStreetMap'
    )

    # Add PA polygons coloured by protection class
    for _, row in pa_gdf_4326.iterrows():
        # Get colour for this class
        class_name = row.get('protection_class', 'unassigned')
        class_info = iucn_classes.get(class_name, {})
        colour = class_info.get('colour', '#B4B2A9')

        # Prepare popup content
        popup_html = f"""
        <b>Name:</b> {row.get('WDPA_NAME', row.get('name', 'Unnamed'))}<br>
        <b>Class:</b> {class_info.get('label', class_name)}<br>
        <b>Area:</b> {row.geometry.area / 10000:.2f} ha<br>
        <b>IUCN Category:</b> {row.get('IUCN_CAT', 'Not reported')}
        """

        # Add polygon to map
        folium.GeoJson(
            row.geometry,
            style_function=lambda x, colour=colour: {
                'fillColor': colour,
                'color': colour,
                'weight': 1,
                'fillOpacity': 0.5
            },
            popup=folium.Popup(popup_html, max_width=300)
        ).add_to(m)

    # Add legend
    legend_html = """
    <div style="position: fixed; bottom: 50px; left: 50px; width: 250px;
                background-color: white; border:2px solid grey; z-index:9999;
                font-size:14px; padding: 10px">
    <p style="margin-bottom:5px; font-weight:bold;">Protection Classes</p>
    """

    for class_name, class_info in iucn_classes.items():
        if class_name == 'oecm':  # Skip OECM for now (not in WDPA)
            continue
        colour = class_info.get('colour', '#B4B2A9')
        label = class_info.get('label', class_name)
        legend_html += f"""
        <p style="margin:3px 0;">
            <span style="background-color:{colour}; width:20px; height:15px;
                         display:inline-block; margin-right:5px;"></span>
            {label}
        </p>
        """

    legend_html += "</div>"
    m.get_root().html.add_child(folium.Element(legend_html))

    # Display map
    st_folium(m, width=None, height=500)

    st.markdown("---")

    # ===================================================================
    # Row 3: Two columns - Coverage stats & Representativity chart
    # ===================================================================
    st.subheader("Detailed Statistics")

    col_left, col_right = st.columns(2)

    with col_left:
        st.markdown("#### Coverage by Protection Class")

        # Compute coverage statistics
        coverage_df = coverage_by_class(pa_gdf, territory_area_ha)

        # Format for display
        display_df = coverage_df.copy()
        display_df['area_ha'] = display_df['area_ha'].apply(lambda x: f"{x:,.0f}")
        display_df['pct_territory'] = display_df['pct_territory'].apply(lambda x: f"{x:.2f}%")

        st.dataframe(
            display_df,
            hide_index=True,
            width='stretch',
            column_config={
                'protection_class': st.column_config.TextColumn('Class'),
                'area_ha': st.column_config.TextColumn('Area (ha)'),
                'pct_territory': st.column_config.TextColumn('% Territory'),
                'n_sites': st.column_config.NumberColumn('Sites', format="%d")
            }
        )

        # IUCN category breakdown
        st.markdown("#### Coverage by IUCN Category")
        if 'IUCN_CAT' in pa_gdf.columns:
            iucn_rows = []
            for cat, grp in pa_gdf.groupby('IUCN_CAT'):
                net_area = grp.geometry.union_all().area / 10000.0
                iucn_rows.append({
                    'IUCN Category': cat,
                    'Area (ha)': f"{net_area:,.0f}",
                    '% Territory': f"{net_area / territory_area_ha * 100:.2f}%",
                    'Sites': len(grp)
                })
            iucn_rows.append({
                'IUCN Category': 'TOTAL',
                'Area (ha)': f"{pa_gdf.geometry.union_all().area / 10000.0:,.0f}",
                '% Territory': f"{pa_gdf.geometry.union_all().area / 10000.0 / territory_area_ha * 100:.2f}%",
                'Sites': len(pa_gdf)
            })
            import pandas as pd
            st.dataframe(pd.DataFrame(iucn_rows), hide_index=True, width='stretch')

    with col_right:
        st.markdown("#### Ecosystem Representativity")

        if 'ri_df' in st.session_state and st.session_state['ri_df'] is not None:
            ri_df = st.session_state['ri_df']

            # Create horizontal bar chart
            chart_data = ri_df[['ecosystem_type', 'coverage_pct']].copy()
            chart_data = chart_data.sort_values('coverage_pct', ascending=True)

            # Define colour function
            def get_bar_colour(pct):
                return '#1D9E75' if pct >= 30.0 else '#F6A623'

            chart_data['colour'] = chart_data['coverage_pct'].apply(get_bar_colour)

            # Display chart using Streamlit bar_chart (simple approach)
            st.bar_chart(
                chart_data.set_index('ecosystem_type')['coverage_pct'],
                width='stretch'
            )

            st.caption(
                "Green bars: above 30% target | Amber bars: below 30% target\n\n"
                "Vertical dashed line indicates KMGBF 30% threshold."
            )

            # Alternative: display as table if chart is not informative
            st.markdown("**Coverage Details:**")
            display_ri = ri_df[['ecosystem_type', 'coverage_pct', 'RI', 'gap_ha']].copy()
            display_ri['coverage_pct'] = display_ri['coverage_pct'].apply(lambda x: f"{x:.1f}%")
            display_ri['RI'] = display_ri['RI'].apply(lambda x: f"{x:.2f}")
            display_ri['gap_ha'] = display_ri['gap_ha'].apply(lambda x: f"{x:,.0f}")

            st.dataframe(
                display_ri,
                hide_index=True,
                width='stretch',
                column_config={
                    'ecosystem_type': 'Ecosystem Type',
                    'coverage_pct': 'Coverage',
                    'RI': 'RI',
                    'gap_ha': 'Gap (ha)'
                }
            )

        else:
            st.info(
                "Upload ecosystem type layer to compute and display "
                "representativity statistics."
            )

    st.markdown("---")

    # ===================================================================
    # Row 4: Gap analysis
    # ===================================================================
    st.subheader("Gap Analysis")

    if st.button("Run Gap Analysis"):
        with st.spinner("Computing gap layers..."):
            try:
                # Compute gap layers
                strict_gaps_gdf = strict_gaps(pa_gdf, territory_geom)
                qual_gaps_gdf = qualitative_gaps(pa_gdf, territory_geom)
                corridors_gdf = potential_corridors(pa_gdf, territory_geom, max_gap_m=5000.0)

                # Store in session state
                st.session_state['gap_layers'] = {
                    'strict_gaps': strict_gaps_gdf,
                    'qualitative_gaps': qual_gaps_gdf,
                    'corridors': corridors_gdf
                }

                # Compute summary statistics
                strict_area = strict_gaps_gdf.geometry.area.sum() / 10000.0 if len(strict_gaps_gdf) > 0 else 0.0
                qual_area = qual_gaps_gdf.geometry.area.sum() / 10000.0 if len(qual_gaps_gdf) > 0 else 0.0
                corridor_area = corridors_gdf.geometry.area.sum() / 10000.0 if len(corridors_gdf) > 0 else 0.0

                strict_pct = (strict_area / territory_area_ha * 100.0) if territory_area_ha > 0 else 0.0
                qual_pct = (qual_area / territory_area_ha * 100.0) if territory_area_ha > 0 else 0.0
                corridor_pct = (corridor_area / territory_area_ha * 100.0) if territory_area_ha > 0 else 0.0

                st.success("Gap analysis complete!")

                col1, col2, col3 = st.columns(3)

                with col1:
                    st.metric(
                        "Strict Gaps",
                        f"{strict_area:,.0f} ha",
                        f"{strict_pct:.1f}% of territory",
                        help="Areas with no PA coverage"
                    )

                with col2:
                    st.metric(
                        "Qualitative Gaps",
                        f"{qual_area:,.0f} ha",
                        f"{qual_pct:.1f}% of territory",
                        help="Areas with only weak protection (contractual/unassigned)"
                    )

                with col3:
                    st.metric(
                        "Potential Corridors",
                        f"{corridor_area:,.0f} ha",
                        f"{corridor_pct:.1f}% of territory",
                        help="Unprotected areas connecting PA patches"
                    )

            except Exception as e:
                st.error(f"Gap analysis failed: {str(e)}")

    # Display gap map if available
    if 'gap_layers' in st.session_state:
        st.markdown("#### Gap Layers Map")

        gap_layers = st.session_state['gap_layers']

        # Create folium map (centroid already in EPSG:4326 from above)
        m_gaps = folium.Map(
            location=[centroid.y, centroid.x],
            zoom_start=8,
            tiles='OpenStreetMap'
        )

        # Helper: filter out empty/null geometries that crash folium
        def _clean_for_folium(gdf):
            """Remove empty/null/coordinate-less geometries and reproject to EPSG:4326.

            Folium's get_bounds() calls iter_coords() which expects a
            'coordinates' key in every GeoJSON feature geometry.  Geometry
            types like GeometryCollection use 'geometries' instead, causing
            a KeyError.  We convert GeometryCollections to their union and
            drop anything that still lacks coordinates.
            """
            from shapely.ops import unary_union
            from shapely.geometry import mapping as _shp_mapping, GeometryCollection

            clean = gdf[~gdf.geometry.is_empty & gdf.geometry.notnull()].copy()
            if len(clean) > 0:
                # Flatten GeometryCollections → their unary_union
                def _flatten(geom):
                    if isinstance(geom, GeometryCollection):
                        u = unary_union(geom.geoms) if geom.geoms else geom
                        return u
                    return geom
                clean = clean.copy()
                clean['geometry'] = clean.geometry.apply(_flatten)
                # Re-filter after flattening
                clean = clean[~clean.geometry.is_empty & clean.geometry.notnull()]

            if len(clean) > 0:
                # Final safety: drop any geometry whose GeoJSON lacks 'coordinates'
                def _has_coords(geom):
                    try:
                        m = _shp_mapping(geom)
                        return 'coordinates' in m
                    except Exception:
                        return False
                clean = clean[clean.geometry.apply(_has_coords)]

            if len(clean) > 0 and hasattr(clean, 'to_crs'):
                clean = clean.to_crs('EPSG:4326')
            return clean

        # Add gap layers as toggleable overlays (reproject to 4326)
        strict_4326 = _clean_for_folium(gap_layers['strict_gaps'])
        if len(strict_4326) > 0:
            folium.GeoJson(
                strict_4326,
                name='Strict Gaps',
                style_function=lambda x: {
                    'fillColor': '#D0021B',
                    'color': '#D0021B',
                    'weight': 1,
                    'fillOpacity': 0.4
                }
            ).add_to(m_gaps)

        qual_4326 = _clean_for_folium(gap_layers['qualitative_gaps'])
        if len(qual_4326) > 0:
            folium.GeoJson(
                qual_4326,
                name='Qualitative Gaps',
                style_function=lambda x: {
                    'fillColor': '#F6A623',
                    'color': '#F6A623',
                    'weight': 1,
                    'fillOpacity': 0.4
                }
            ).add_to(m_gaps)

        corr_4326 = _clean_for_folium(gap_layers['corridors'])
        if len(corr_4326) > 0:
            folium.GeoJson(
                corr_4326,
                name='Potential Corridors',
                style_function=lambda x: {
                    'fillColor': '#4A90E2',
                    'color': '#4A90E2',
                    'weight': 1,
                    'fillOpacity': 0.4
                }
            ).add_to(m_gaps)

        # Add layer control
        folium.LayerControl().add_to(m_gaps)

        st_folium(m_gaps, width='stretch', height=400)

    else:
        st.info("Click 'Run Gap Analysis' to compute and display gap layers.")

    st.markdown("---")

    # ===================================================================
    # Criterion profiles within existing protected areas
    # ===================================================================
    st.markdown("### Criterion profiles within existing protected areas")

    try:
        # Check if raster paths are available in session state
        raster_paths = st.session_state.get('criterion_raster_paths', None)

        if raster_paths is None or len(raster_paths) == 0:
            st.info(
                "Raster paths for MCE criteria not yet available. "
                "Run Module 2 analysis first to enable criterion profiling within PAs."
            )
        else:
            # Import zonal stats functions
            from modules.module1_protected_areas.zonal_stats import (
                zonal_stats_by_pa_class,
                criterion_coverage_summary
            )

            if st.button("Compute Criterion Profiles"):
                with st.spinner("Computing zonal statistics for all criteria..."):
                    try:
                        # Compute zonal statistics
                        zonal_df = zonal_stats_by_pa_class(pa_gdf, raster_paths)

                        if len(zonal_df) == 0:
                            st.warning("No zonal statistics computed (no valid overlaps)")
                        else:
                            # Store in session state
                            st.session_state['zonal_stats'] = zonal_df

                            st.success(
                                f"Computed statistics for {len(zonal_df['criterion'].unique())} criteria "
                                f"across {len(zonal_df['pa_class'].unique())} protection classes"
                            )

                    except Exception as e:
                        st.error(f"Failed to compute zonal statistics: {str(e)}")
                        logger.exception("Zonal statistics computation error:")

            # Display results if available
            if 'zonal_stats' in st.session_state and st.session_state['zonal_stats'] is not None:
                zonal_df = st.session_state['zonal_stats']

                # Row 1: Grouped bar chart
                st.markdown("#### Mean Criterion Scores by Protection Class")
                st.caption(
                    "All criteria normalised to [0–1] for display. "
                    "Anthropogenic pressure is inverted (lower raw value = higher score). "
                    "Land use (CLC categorical codes) is excluded — see breakdown below."
                )

                try:
                    import plotly.express as px

                    # Normalise each criterion to [0-1] for comparable display
                    # Exclude 'landuse' — CLC codes are categorical, mean is meaningless
                    chart_data = zonal_df[zonal_df['criterion'] != 'landuse'][['criterion', 'pa_class', 'mean']].copy()
                    for crit in chart_data['criterion'].unique():
                        mask = chart_data['criterion'] == crit
                        vals = chart_data.loc[mask, 'mean']
                        vmin, vmax = vals.min(), vals.max()
                        if vmax > vmin:
                            chart_data.loc[mask, 'mean'] = (vals - vmin) / (vmax - vmin)
                        # Invert anthropogenic pressure (high pressure = bad)
                        if crit == 'anthropogenic_pressure':
                            chart_data.loc[mask, 'mean'] = 1.0 - chart_data.loc[mask, 'mean']

                    # Sort PA classes: protection classes first, then 'outside'
                    pa_class_order = sorted([c for c in chart_data['pa_class'].unique() if c != 'outside'])
                    if 'outside' in chart_data['pa_class'].unique():
                        pa_class_order.append('outside')

                    # Create grouped bar chart
                    fig = px.bar(
                        chart_data,
                        x='criterion',
                        y='mean',
                        color='pa_class',
                        barmode='group',
                        category_orders={'pa_class': pa_class_order},
                        labels={
                            'criterion': 'Criterion',
                            'mean': 'Normalised Score [0–1]',
                            'pa_class': 'Protection Class'
                        },
                        title='',
                        color_discrete_sequence=px.colors.qualitative.Set2
                    )

                    fig.update_layout(
                        xaxis_tickangle=-45,
                        height=400,
                        legend=dict(
                            orientation="v",
                            yanchor="top",
                            y=1.0,
                            xanchor="left",
                            x=1.02
                        )
                    )

                    st.plotly_chart(fig, width='stretch')

                except ImportError:
                    # Fallback to simpler visualization if plotly not available
                    st.warning("Plotly not available. Install plotly for interactive charts.")
                    st.bar_chart(
                        zonal_df[zonal_df['criterion'] != 'landuse'].pivot(
                            index='criterion', columns='pa_class', values='mean'
                        )
                    )

                # Row 2: Summary pivot table (continuous criteria only)
                st.markdown("#### Summary: Mean Scores by PA Class")

                try:
                    summary_df = criterion_coverage_summary(
                        zonal_df[zonal_df['criterion'] != 'landuse']
                    )

                    # Format for display
                    display_summary = summary_df.copy()
                    for col in display_summary.columns:
                        display_summary[col] = display_summary[col].apply(lambda x: f"{x:.3f}" if pd.notna(x) else "—")

                    st.dataframe(
                        display_summary,
                        width='stretch'
                    )

                except Exception as e:
                    st.error(f"Failed to generate summary table: {str(e)}")

                # Row 3: Expandable detailed statistics
                with st.expander("Detailed Statistics (min/median/max/std)"):
                    st.markdown("**Per-criterion box-plot statistics (continuous criteria only):**")

                    # Create detailed table — exclude landuse (categorical)
                    detailed_stats = []

                    for criterion in zonal_df['criterion'].unique():
                        if criterion == 'landuse':
                            continue
                        criterion_data = zonal_df[zonal_df['criterion'] == criterion]

                        for pa_class in criterion_data['pa_class'].unique():
                            class_data = criterion_data[criterion_data['pa_class'] == pa_class]

                            if len(class_data) > 0:
                                row = class_data.iloc[0]
                                detailed_stats.append({
                                    'Criterion': criterion,
                                    'PA Class': pa_class,
                                    'Min': f"{row['min']:.3f}",
                                    'Median': f"{row['median']:.3f}",
                                    'Max': f"{row['max']:.3f}",
                                    'Std': f"{row['std']:.3f}",
                                    'Pixel Count': f"{row['pixel_count']:,}"
                                })

                    detailed_df = pd.DataFrame(detailed_stats)

                    st.dataframe(
                        detailed_df,
                        hide_index=True,
                        width='stretch'
                    )

                # Row 4: CLC land use class breakdown
                if 'landuse' in st.session_state.get('criterion_raster_paths', {}):
                    st.markdown("#### Land Use Composition (CLC Level 1)")
                    st.caption("Pixel counts per Corine Land Cover Level 1 category within the study area.")
                    try:
                        import rasterio as _rio

                        # CLC Level 1 labels (first digit of CLC code)
                        _CLC_LEVEL1_LABELS = {
                            1: "Urban",
                            2: "Agricultural",
                            3: "Shrublands / Mixed",
                            4: "Forest",
                            5: "Water",
                        }

                        lu_path = st.session_state['criterion_raster_paths']['landuse']

                        with _rio.open(lu_path) as src:
                            lu_array = src.read(1).astype(float)
                            lu_nodata = src.nodata
                        if lu_nodata is not None:
                            lu_array[lu_array == lu_nodata] = np.nan

                        # Aggregate to Level 1 using first digit of CLC code
                        valid_codes = lu_array[~np.isnan(lu_array)].astype(int)
                        level1_codes = valid_codes // 100  # 311 → 3, 112 → 1, etc.
                        unique_l1, counts_l1 = np.unique(level1_codes, return_counts=True)
                        total_valid = len(valid_codes)

                        clc_rows = []
                        for l1, cnt in sorted(zip(unique_l1, counts_l1), key=lambda x: -x[1]):
                            label = _CLC_LEVEL1_LABELS.get(int(l1), f"Unknown ({l1})")
                            clc_rows.append({
                                'Level 1': int(l1),
                                'Category': label,
                                'Pixel Count': int(cnt),
                                '% of area': f"{100.0 * cnt / total_valid:.1f}%"
                            })

                        clc_table = pd.DataFrame(clc_rows)
                        st.dataframe(clc_table, hide_index=True, use_container_width=True)

                    except Exception as e:
                        st.caption(f"CLC breakdown unavailable: {e}")

    except Exception as e:
        st.warning(
            f"Criterion profiling unavailable: {str(e)}\n\n"
            "This feature requires raster paths to be available in session state."
        )

    st.markdown("---")

    # ===================================================================
    # Footer: Export buttons
    # ===================================================================
    st.subheader("Export & Analysis Tools")

    col_exp1, col_exp2 = st.columns(2)

    with col_exp1:
        if st.button("Export PA Statistics (CSV)"):
            # Export coverage statistics
            coverage_df = coverage_by_class(pa_gdf, territory_area_ha)

            # Create temporary CSV file
            with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.csv') as tmp:
                coverage_df.to_csv(tmp.name, index=False)

                # Provide download button
                with open(tmp.name, 'r') as f:
                    csv_data = f.read()

                st.download_button(
                    label="Download CSV",
                    data=csv_data,
                    file_name="pa_coverage_statistics.csv",
                    mime="text/csv"
                )

    with col_exp2:
        if 'ri_df' in st.session_state and st.session_state['ri_df'] is not None:
            if st.button("Apply Weight Suggestions to Module 2 →"):
                # Propose Group A weights from representativity deficits
                try:
                    ri_df = st.session_state['ri_df']

                    # Load criterion-ecosystem mapping from config
                    config_path = Path(__file__).parent.parent / "config" / "criteria_defaults.yaml"
                    with open(config_path, 'r', encoding='utf-8') as f:
                        config = yaml.safe_load(f)

                    criterion_mapping = config.get('criterion_ecosystem_mapping', {})

                    # Propose weights
                    proposed_weights = propose_group_a_weights(ri_df, criterion_mapping)

                    # Validate handoff before storing
                    from modules.module1_protected_areas.handoff import (
                        validate_weight_handoff,
                        format_weights_for_mce
                    )

                    validate_weight_handoff(proposed_weights, str(config_path))
                    formatted_weights = format_weights_for_mce(proposed_weights)

                    # Store validated weights in session state
                    st.session_state['proposed_group_a_weights'] = formatted_weights

                    st.success(
                        "Weight suggestions validated and applied! "
                        "Go to sidebar Section 7 to apply them to Module 2."
                    )

                except ValueError as e:
                    st.error(f"Weight validation failed: {str(e)}")
                except Exception as e:
                    st.error(f"Failed to propose weights: {str(e)}")
        else:
            st.info("Run representativity analysis with ecosystem layer to enable weight suggestions.")
