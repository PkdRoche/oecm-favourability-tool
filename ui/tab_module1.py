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
            status = st.empty()
            status.info("Loading and classifying protected areas…")
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
            finally:
                status.empty()
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

    # Pre-compute area in ha from EPSG:3035 (metric, accurate) and attach to 4326 copy
    pa_display = pa_gdf_4326.copy()
    pa_display['area_ha'] = (pa_gdf.geometry.area / 10000).round(2).values

    # Filter invalid/empty geometries (folium expects GeoJSON geometries with coordinates)
    if 'geometry' in pa_display.columns:
        pa_display = pa_display[pa_display.geometry.notna()].copy()
        pa_display = pa_display[~pa_display.geometry.is_empty].copy()
        try:
            pa_display = pa_display[pa_display.is_valid].copy()
        except Exception:
            pass

        # Folium's bounds computation assumes geometries expose a GeoJSON 'coordinates' key;
        # GeometryCollection uses 'geometries' instead and can trigger KeyError('coordinates').
        # Keep only Polygon/MultiPolygon for display.
        try:
            geom_types = pa_display.geometry.geom_type
            allowed = geom_types.isin(['Polygon', 'MultiPolygon'])
            dropped = int((~allowed).sum())
            if dropped:
                logger.warning(
                    f"Dropping {dropped} feature(s) with unsupported geometry types for folium: "
                    f"{geom_types[~allowed].value_counts().to_dict()}"
                )
            pa_display = pa_display[allowed].copy()
        except Exception:
            pass

    # Deduplicate column names — folium/__geo_interface__ raises ValueError otherwise
    # (WDPA files sometimes have duplicate columns e.g. two 'NAME' columns)
    seen = {}
    new_cols = []
    for col in pa_display.columns:
        if col in seen:
            seen[col] += 1
            new_cols.append(f"{col}_{seen[col]}")
        else:
            seen[col] = 0
            new_cols.append(col)
    pa_display.columns = new_cols

    # Build colour lookup once
    _colour_map = {
        cn: iucn_classes.get(cn, {}).get('colour', '#B4B2A9')
        for cn in pa_display['protection_class'].unique()
    } if 'protection_class' in pa_display.columns else {}

    # Single GeoJson layer (replaces one folium object per PA — massive speed-up)
    iucn_col = 'IUCN_MAX' if 'IUCN_MAX' in pa_display.columns else 'IUCN_CAT'
    tooltip_fields   = [c for c in ['WDPA_NAME', 'protection_class', iucn_col, 'area_ha']
                        if c in pa_display.columns]
    tooltip_aliases  = [a for c, a in [('WDPA_NAME', 'Name'), ('protection_class', 'Class'),
                                        (iucn_col, 'IUCN Cat.'), ('area_ha', 'Area (ha)')]
                        if c in pa_display.columns]

    if len(pa_display) > 0:
        folium.GeoJson(
            pa_display,
            style_function=lambda feature: {
                'fillColor': _colour_map.get(
                    feature['properties'].get('protection_class', 'unassigned'), '#B4B2A9'
                ),
                'color': _colour_map.get(
                    feature['properties'].get('protection_class', 'unassigned'), '#B4B2A9'
                ),
                'weight': 1,
                'fillOpacity': 0.5
            },
            tooltip=folium.GeoJsonTooltip(fields=tooltip_fields, aliases=tooltip_aliases)
        ).add_to(m)
    else:
        st.warning("No valid protected-area geometries to display on the map.")

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
        iucn_col_stats = 'IUCN_MAX' if 'IUCN_MAX' in pa_gdf.columns else 'IUCN_CAT'
        if iucn_col_stats in pa_gdf.columns:
            # Compute total union once — reused for TOTAL row (avoids 3× union_all)
            total_pa_area_ha = pa_gdf.geometry.union_all().area / 10000.0
            iucn_rows = []
            for cat, grp in pa_gdf.groupby(iucn_col_stats):
                net_area = grp.geometry.union_all().area / 10000.0
                iucn_rows.append({
                    'IUCN Category': cat,
                    'Area (ha)': f"{net_area:,.0f}",
                    '% Territory': f"{net_area / territory_area_ha * 100:.2f}%",
                    'Sites': len(grp)
                })
            iucn_rows.append({
                'IUCN Category': 'TOTAL',
                'Area (ha)': f"{total_pa_area_ha:,.0f}",
                '% Territory': f"{total_pa_area_ha / territory_area_ha * 100:.2f}%",
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
        status = st.empty()
        status.info("Computing gap layers...")
        try:
            # Compute gap layers
            strict_gaps_gdf = strict_gaps(pa_gdf, territory_geom)
            qual_gaps_gdf = qualitative_gaps(pa_gdf, territory_geom)
            corridors_gdf = potential_corridors(pa_gdf, territory_geom, max_gap_m=5000.0)

            # Store layers in session state
            st.session_state['gap_layers'] = {
                'strict_gaps': strict_gaps_gdf,
                'qualitative_gaps': qual_gaps_gdf,
                'corridors': corridors_gdf
            }

            # Store raw areas only — % computed dynamically from current
            # territory_area_ha at render time (so they stay correct if
            # the user switches territory without re-running the analysis)
            st.session_state['gap_stats'] = {
                'strict_area':   strict_gaps_gdf.geometry.area.sum() / 10000.0 if len(strict_gaps_gdf) > 0 else 0.0,
                'qual_area':     qual_gaps_gdf.geometry.area.sum()   / 10000.0 if len(qual_gaps_gdf)   > 0 else 0.0,
                'corridor_area': corridors_gdf.geometry.area.sum()   / 10000.0 if len(corridors_gdf)   > 0 else 0.0,
            }

        except Exception as e:
            st.error(f"Gap analysis failed: {str(e)}")
        finally:
            status.empty()

    # Display statistics + map whenever results are available in session state
    # (rendered OUTSIDE the button block so they survive Streamlit re-runs)
    if 'gap_layers' in st.session_state:

        # --- Summary metrics (persist across re-runs via session_state) ---
        if 'gap_stats' in st.session_state:
            gs = st.session_state['gap_stats']
            st.success("Gap analysis complete!")

            # % computed fresh from current territory_area_ha so they are
            # always consistent with the selected region denominator
            def _pct(area_ha):
                return area_ha / territory_area_ha * 100.0 if territory_area_ha > 0 else 0.0

            st.caption(
                f"Reference territory: **{territory_area_ha:,.0f} ha** "
                f"({territory_area_ha / 100:.0f} km²) — "
                "percentages below are relative to this total area."
            )

            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric(
                    "Strict Gaps",
                    f"{gs['strict_area']:,.0f} ha",
                    f"{_pct(gs['strict_area']):.1f}% of territory",
                    delta_color="off",
                    help="Areas with NO PA coverage of any kind. "
                         "strict_gap% + total_PA_coverage% ≈ 100%."
                )
            with col2:
                st.metric(
                    "Qualitative Gaps",
                    f"{gs['qual_area']:,.0f} ha",
                    f"{_pct(gs['qual_area']):.1f}% of territory",
                    delta_color="off",
                    help="Areas covered ONLY by weak protection classes "
                         "(contractual / unassigned). Superset of strict gaps."
                )
            with col3:
                st.metric(
                    "Potential Corridors",
                    f"{gs['corridor_area']:,.0f} ha",
                    f"{_pct(gs['corridor_area']):.1f}% of territory",
                    delta_color="off",
                    help="Unprotected areas within 5 km of two or more PA patches "
                         "(potential ecological corridors). Independent of gap metrics."
                )

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
                status = st.empty()
                status.info("Computing zonal statistics for all criteria...")
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
                            f"across {len(zonal_df['iucn_cat'].unique())} IUCN categories"
                        )

                except Exception as e:
                    st.error(f"Failed to compute zonal statistics: {str(e)}")
                    logger.exception("Zonal statistics computation error:")
                finally:
                    status.empty()

            # Display results if available
            if 'zonal_stats' in st.session_state and st.session_state['zonal_stats'] is not None:
                zonal_df = st.session_state['zonal_stats']

                # Row 1: Grouped bar chart
                st.markdown("#### Mean Criterion Scores by IUCN Category")
                st.caption(
                    "All criteria normalised to [0–1] for display. "
                    "Anthropogenic pressure is inverted (lower raw value = higher score). "
                    "Land use (CLC categorical codes) is excluded — see breakdown below."
                )

                try:
                    import plotly.express as px

                    chart_data = zonal_df[zonal_df['criterion'] != 'landuse'][['criterion', 'iucn_cat', 'mean']].copy()
                    for crit in chart_data['criterion'].unique():
                        mask = chart_data['criterion'] == crit
                        vals = chart_data.loc[mask, 'mean']
                        vmin, vmax = vals.min(), vals.max()
                        if vmax > vmin:
                            chart_data.loc[mask, 'mean'] = (vals - vmin) / (vmax - vmin)
                        if crit == 'anthropogenic_pressure':
                            chart_data.loc[mask, 'mean'] = 1.0 - chart_data.loc[mask, 'mean']

                    cat_order = sorted([c for c in chart_data['iucn_cat'].unique() if c != 'outside'])
                    if 'outside' in chart_data['iucn_cat'].unique():
                        cat_order.append('outside')

                    fig = px.bar(
                        chart_data,
                        x='criterion',
                        y='mean',
                        color='iucn_cat',
                        barmode='group',
                        category_orders={'iucn_cat': cat_order},
                        labels={
                            'criterion': 'Criterion',
                            'mean': 'Normalised Score [0–1]',
                            'iucn_cat': 'IUCN Category'
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
                    st.warning("Plotly not available. Install plotly for interactive charts.")
                    st.bar_chart(
                        zonal_df[zonal_df['criterion'] != 'landuse'].pivot(
                            index='criterion', columns='iucn_cat', values='mean'
                        )
                    )

                # Row 2: Summary pivot table (continuous criteria only)
                st.markdown("#### Summary: Mean Scores by IUCN Category")

                try:
                    summary_df = criterion_coverage_summary(
                        zonal_df[zonal_df['criterion'] != 'landuse']
                    )

                    display_summary = summary_df.copy()
                    for col in display_summary.columns:
                        display_summary[col] = display_summary[col].apply(lambda x: f"{x:.3f}" if pd.notna(x) else "—")

                    st.dataframe(display_summary, width='stretch')

                except Exception as e:
                    st.error(f"Failed to generate summary table: {str(e)}")

                # Row 3: Expandable detailed statistics
                with st.expander("Detailed Statistics (min/median/max/std)"):
                    st.markdown("**Per-criterion statistics by IUCN category (continuous criteria only):**")

                    detailed_stats = []

                    for criterion in zonal_df['criterion'].unique():
                        if criterion == 'landuse':
                            continue
                        criterion_data = zonal_df[zonal_df['criterion'] == criterion]

                        for iucn_cat in criterion_data['iucn_cat'].unique():
                            class_data = criterion_data[criterion_data['iucn_cat'] == iucn_cat]

                            if len(class_data) > 0:
                                row = class_data.iloc[0]
                                detailed_stats.append({
                                    'Criterion': criterion,
                                    'IUCN Category': iucn_cat,
                                    'Min': f"{row['min']:.3f}",
                                    'Median': f"{row['median']:.3f}",
                                    'Max': f"{row['max']:.3f}",
                                    'Std': f"{row['std']:.3f}",
                                    'Pixel Count': f"{row['pixel_count']:,}"
                                })

                    detailed_df = pd.DataFrame(detailed_stats)
                    st.dataframe(detailed_df, hide_index=True, width='stretch')

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

    # ── Report generation ────────────────────────────────────────────────
    st.markdown("#### Diagnostic Report")
    st.caption(
        "Generate a fully documented report (DOCX) containing all maps, "
        "charts and tables computed above.  Requires **python-docx** "
        "(`pip install python-docx`)."
    )

    report_col1, report_col2, _ = st.columns([1, 1, 2])
    with report_col1:
        if st.button("Generate DOCX Report", type="primary", use_container_width=True):
            with st.spinner("Building report…"):
                try:
                    from modules.module1_protected_areas.report_generator import (
                        generate_docx_report
                    )
                    from modules.module1_protected_areas.coverage_stats import (
                        coverage_by_class, kmgbf_indicator
                    )

                    # Re-compute tables needed for the report
                    _cov_df   = coverage_by_class(pa_gdf, territory_area_ha)
                    _kmgbf    = kmgbf_indicator(pa_gdf, territory_area_ha)
                    _net_area = compute_net_area(pa_gdf, territory_geom)

                    # IUCN category coverage table
                    iucn_col_r = 'IUCN_MAX' if 'IUCN_MAX' in pa_gdf.columns else 'IUCN_CAT'
                    _iucn_rows = []
                    if iucn_col_r in pa_gdf.columns:
                        for cat, grp in pa_gdf.groupby(iucn_col_r):
                            net = grp.geometry.union_all().area / 10000.0
                            _iucn_rows.append({
                                'IUCN Category': cat,
                                'Area (ha)': f'{net:,.0f}',
                                '% Territory': f'{net / territory_area_ha * 100:.2f}%',
                                'Sites': len(grp),
                            })
                    _iucn_df = pd.DataFrame(_iucn_rows) if _iucn_rows else None

                    docx_bytes = generate_docx_report(
                        territory_name=st.session_state.get('parameters', {}).get(
                            'study_area_name', 'Unknown territory'),
                        territory_area_ha=territory_area_ha,
                        pa_gdf=pa_gdf,
                        territory_geom=territory_geom,
                        iucn_classes=iucn_classes,
                        coverage_df=_cov_df,
                        iucn_coverage_df=_iucn_df,
                        gap_layers=st.session_state.get('gap_layers'),
                        gap_stats=st.session_state.get('gap_stats'),
                        ri_df=st.session_state.get('ri_df'),
                        zonal_df=st.session_state.get('zonal_stats'),
                        kmgbf_pct=_kmgbf,
                        net_area_ha=_net_area,
                    )
                    st.session_state['_module1_report_bytes'] = docx_bytes
                    st.success("Report ready — click Download below.")

                except ImportError as e:
                    st.error(str(e))
                except Exception as e:
                    st.error(f"Report generation failed: {e}")
                    logger.exception("Module 1 report generation error")

    with report_col2:
        report_bytes = st.session_state.get('_module1_report_bytes')
        territory_slug = (
            st.session_state.get('parameters', {})
            .get('study_area_name', 'territory')
            .replace(' ', '_')[:30]
        )
        st.download_button(
            label="Download DOCX",
            data=report_bytes or b'',
            file_name=f"module1_diagnostic_{territory_slug}.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            disabled=report_bytes is None,
            use_container_width=True,
        )

    st.markdown("---")

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
