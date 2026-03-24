"""Streamlit UI for Module 1 — Protection Network Diagnostic."""
import streamlit as st
import pandas as pd
import geopandas as gpd
import folium
from streamlit_folium import st_folium
from pathlib import Path
import yaml
import tempfile


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

    # Check if data is available
    if pa_gdf is None or territory_geom is None:
        st.info(
            "Load protected area data to begin analysis. "
            "Configure study area in the sidebar and upload PA vector layer."
        )
        st.markdown("### Quick Start")
        st.markdown(
            "1. Set ISO3 country code in sidebar (e.g., 'FRA' for France)\n"
            "2. Upload WDPA shapefile or GeoPackage\n"
            "3. Upload territory boundary polygon\n"
            "4. Optionally upload ecosystem type layer for representativity analysis"
        )
        return

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

    # Create folium map centered on territory
    centroid = territory_geom.centroid
    m = folium.Map(
        location=[centroid.y, centroid.x],
        zoom_start=8,
        tiles='OpenStreetMap'
    )

    # Add PA polygons coloured by protection class
    for _, row in pa_gdf.iterrows():
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
            use_container_width=True,
            column_config={
                'protection_class': st.column_config.TextColumn('Class'),
                'area_ha': st.column_config.TextColumn('Area (ha)'),
                'pct_territory': st.column_config.TextColumn('% Territory'),
                'n_sites': st.column_config.NumberColumn('Sites', format="%d")
            }
        )

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
                use_container_width=True
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
                use_container_width=True,
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

        # Create folium map
        m_gaps = folium.Map(
            location=[centroid.y, centroid.x],
            zoom_start=8,
            tiles='OpenStreetMap'
        )

        # Add gap layers as toggleable overlays
        if len(gap_layers['strict_gaps']) > 0:
            folium.GeoJson(
                gap_layers['strict_gaps'],
                name='Strict Gaps',
                style_function=lambda x: {
                    'fillColor': '#D0021B',
                    'color': '#D0021B',
                    'weight': 1,
                    'fillOpacity': 0.4
                }
            ).add_to(m_gaps)

        if len(gap_layers['qualitative_gaps']) > 0:
            folium.GeoJson(
                gap_layers['qualitative_gaps'],
                name='Qualitative Gaps',
                style_function=lambda x: {
                    'fillColor': '#F6A623',
                    'color': '#F6A623',
                    'weight': 1,
                    'fillOpacity': 0.4
                }
            ).add_to(m_gaps)

        if len(gap_layers['corridors']) > 0:
            folium.GeoJson(
                gap_layers['corridors'],
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

        st_folium(m_gaps, width=None, height=400)

    else:
        st.info("Click 'Run Gap Analysis' to compute and display gap layers.")

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

                    # Store in session state
                    st.session_state['proposed_group_a_weights'] = proposed_weights

                    st.success(
                        "Weight suggestions applied! "
                        "Go to sidebar Section 7 to apply them to Module 2."
                    )

                except Exception as e:
                    st.error(f"Failed to propose weights: {str(e)}")
        else:
            st.info("Run representativity analysis with ecosystem layer to enable weight suggestions.")
