"""Streamlit UI for Module 2 — OECM Favourability Analysis."""
import streamlit as st
import numpy as np
import pandas as pd
import folium
from streamlit_folium import st_folium
import tempfile
from pathlib import Path
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
from PIL import Image
import io
import base64
import json
from datetime import datetime
import plotly.graph_objects as go


def render_tab_module2(score_array=None, oecm_mask=None, classical_pa_mask=None,
                       eliminatory_mask=None, profile=None, params=None):
    """
    Render Module 2 results. Called only when score_array is available.

    Parameters
    ----------
    score_array : np.ndarray
        Favourability score array [0-1], NaN where eliminated.
    oecm_mask : np.ndarray
        Boolean mask: True = OECM favourable (Group C >= threshold).
    classical_pa_mask : np.ndarray
        Boolean mask: True = classical PA preferable (Group C < threshold).
    eliminatory_mask : np.ndarray, optional
        Boolean mask: True = pixel passed Group D (not eliminated).
    profile : dict
        Rasterio profile (CRS, transform, dimensions).
    params : dict, optional
        Full parameter dictionary from sidebar for reproducibility logging.
    """
    # ===================================================================
    # Row 1: Summary metric cards
    # ===================================================================
    st.subheader("Favourability Summary")

    pixel_area_ha = (profile['transform'][0] ** 2) / 10000.0
    territory_area_ha = profile['width'] * profile['height'] * pixel_area_ha

    valid_mask = ~np.isnan(score_array)
    n_valid = int(np.sum(valid_mask))
    n_total = score_array.size
    n_eliminated = n_total - n_valid

    oecm_area_ha = float(np.sum(oecm_mask)) * pixel_area_ha if oecm_mask is not None else 0.0
    classical_pa_area_ha = float(np.sum(classical_pa_mask)) * pixel_area_ha if classical_pa_mask is not None else 0.0
    oecm_pct = (oecm_area_ha / territory_area_ha * 100.0) if territory_area_ha > 0 else 0.0
    classical_pa_pct = (classical_pa_area_ha / territory_area_ha * 100.0) if territory_area_ha > 0 else 0.0

    valid_scores = score_array[valid_mask]
    median_score = float(np.median(valid_scores)) if len(valid_scores) > 0 else 0.0

    col1, col2, col3, col4 = st.columns(4)

    eligible_area_ha = n_valid * pixel_area_ha
    eligible_pct = (eligible_area_ha / territory_area_ha * 100.0) if territory_area_ha > 0 else 0.0

    with col1:
        st.metric(
            label="Eligible Area (passed Group D)",
            value=f"{eligible_area_ha:,.0f} ha",
            delta=f"{eligible_pct:.1f}% of territory",
            help="Pixels not eliminated by pressure or incompatible land use"
        )

    with col2:
        st.metric(
            label="OECM Favourable",
            value=f"{oecm_area_ha:,.0f} ha",
            delta=f"{oecm_pct:.1f}% of territory",
            help="Eligible pixels with sufficient production function (Group C ≥ threshold)"
        )

    with col3:
        st.metric(
            label="Low use-function (MCE Group C < 0.10)",
            value=f"{classical_pa_area_ha:,.0f} ha",
            delta=f"{classical_pa_pct:.1f}% of territory",
            help=(
                "Eligible pixels where Group C score (provisioning ES + compatible land use) "
                "is below 0.10 — these areas lack sufficient production function for OECM "
                "and may be better candidates for classical PA designation. "
                "This is NOT the existing WDPA protected area network."
            )
        )

    with col4:
        st.metric(
            label="Median Score (eligible)",
            value=f"{median_score:.2f}",
            help="Median favourability score across all eligible pixels (0-1 scale)"
        )

    # Elimination diagnostic
    elim_pct = (n_eliminated / n_total * 100.0) if n_total > 0 else 0.0
    if n_eliminated > 0:
        st.caption(
            f"Group D eliminated {n_eliminated:,} pixels ({elim_pct:.1f}% of grid) — "
            "high anthropogenic pressure or incompatible land use. "
            "Adjust the pressure threshold in the sidebar to change this."
        )

    st.markdown("---")

    # ===================================================================
    # Sub-tabs: Map and Statistics
    # ===================================================================
    subtab1, subtab2 = st.tabs(["Map", "Statistics"])

    with subtab1:
        # =================================================================
        # MAP TAB: Threshold explorer then map
        # =================================================================
        st.subheader("Favourability Map")

        # Threshold slider FIRST so the map reflects the current value immediately
        threshold_col1, threshold_col2 = st.columns([2, 1])
        with threshold_col1:
            map_threshold = st.slider(
                "Display threshold — show areas ≥",
                min_value=0.0,
                max_value=1.0,
                value=st.session_state.get('export_threshold', 0.5),
                step=0.05,
                key='map_threshold_slider',
                help="Only pixels with favourability score ≥ this value are shown on the map"
            )
            st.session_state['export_threshold'] = map_threshold

        with threshold_col2:
            above_threshold = valid_mask & (score_array >= map_threshold)
            area_above_ha = np.sum(above_threshold) * pixel_area_ha
            pct_above = (area_above_ha / territory_area_ha * 100.0) if territory_area_ha > 0 else 0.0
            st.metric(
                label=f"Area ≥ {map_threshold:.2f}",
                value=f"{area_above_ha:,.0f} ha",
                delta=f"{pct_above:.1f}% of study area"
            )

        # Create folium map with raster overlay
        if n_valid == 0:
            st.warning(
                "All pixels were eliminated by Group D criteria (pressure threshold or "
                "incompatible land use). Increase the pressure threshold in the sidebar "
                "or verify your input layers cover the study area."
            )

        try:
            # Convert score_array to PNG using RdYlGn colormap
            import matplotlib.cm as mcm
            from rasterio.warp import transform_bounds

            cmap = mcm.get_cmap('RdYlGn')
            norm = mcolors.Normalize(vmin=0.0, vmax=1.0)

            # Show only pixels at or above the map threshold — others are transparent
            display_mask = valid_mask & (score_array >= map_threshold)
            rgba = np.zeros((*score_array.shape, 4), dtype=np.uint8)
            rgba[display_mask] = (cmap(norm(score_array[display_mask])) * 255).astype(np.uint8)
            # Pixels below threshold and eliminated pixels stay fully transparent (alpha=0)

            # Convert to PIL Image
            img_pil = Image.fromarray(rgba, mode='RGBA')

            # Convert to base64 for folium
            buffered = io.BytesIO()
            img_pil.save(buffered, format="PNG")
            img_base64 = base64.b64encode(buffered.getvalue()).decode()

            # Get bounds from profile and reproject to EPSG:4326
            from rasterio.transform import array_bounds

            bounds_3035 = array_bounds(
                profile['height'],
                profile['width'],
                profile['transform']
            )

            # Reproject bounds from EPSG:3035 to EPSG:4326
            bounds_4326 = transform_bounds(
                'EPSG:3035',
                'EPSG:4326',
                bounds_3035[0],  # left
                bounds_3035[1],  # bottom
                bounds_3035[2],  # right
                bounds_3035[3]   # top
            )

            # Create folium map centered on bounds
            center_lat = (bounds_4326[1] + bounds_4326[3]) / 2
            center_lon = (bounds_4326[0] + bounds_4326[2]) / 2

            m = folium.Map(
                location=[center_lat, center_lon],
                zoom_start=8,
                tiles='OpenStreetMap'
            )

            # Add raster overlay
            folium.raster_layers.ImageOverlay(
                image=f"data:image/png;base64,{img_base64}",
                bounds=[[bounds_4326[1], bounds_4326[0]],  # SW corner
                        [bounds_4326[3], bounds_4326[2]]],  # NE corner
                opacity=0.75,
                name='Favourability Score'
            ).add_to(m)

            # Add NUTS2 boundary if available
            study_area_geom = st.session_state.get('study_area_geometry')
            if study_area_geom is not None:
                import geopandas as gpd
                nuts_gdf = gpd.GeoDataFrame([{'geometry': study_area_geom}], crs='EPSG:3035')
                nuts_gdf_4326 = nuts_gdf.to_crs('EPSG:4326')

                folium.GeoJson(
                    nuts_gdf_4326,
                    name='Study Area',
                    style_function=lambda x: {
                        'fillColor': 'none',
                        'color': 'white',
                        'weight': 2,
                        'fillOpacity': 0
                    }
                ).add_to(m)

            # Add WDPA protected areas if available
            wdpa_gdf = st.session_state.get('pa_gdf')
            if wdpa_gdf is not None:
                wdpa_gdf_4326 = wdpa_gdf.to_crs('EPSG:4326')

                folium.GeoJson(
                    wdpa_gdf_4326,
                    name='Protected Areas (WDPA)',
                    style_function=lambda x: {
                        'fillColor': '#378ADD',
                        'color': '#378ADD',
                        'weight': 1,
                        'fillOpacity': 0.3
                    }
                ).add_to(m)

            # Add color legend (gradient bar with labels)
            legend_html = """
            <div style="position: fixed; bottom: 50px; left: 50px; width: 220px;
                        background-color: white; border:2px solid grey; z-index:9999;
                        font-size:12px; padding: 10px">
            <p style="margin:3px 0; font-weight:bold;">Favourability Score</p>
            <div style="background: linear-gradient(to right, #d7191c, #fdae61, #ffffbf, #a6d96a, #1a9641);
                        height: 20px; margin: 5px 0;"></div>
            <div style="display: flex; justify-content: space-between; font-size: 10px;">
                <span>0.0</span>
                <span>0.5</span>
                <span>1.0</span>
            </div>
            <p style="margin:5px 0; font-size:10px; color:#666;">
                Red = Low favourability<br>
                Green = High favourability
            </p>
            </div>
            """
            m.get_root().html.add_child(folium.Element(legend_html))

            # Add layer control
            folium.LayerControl().add_to(m)

            # Display map
            st_folium(m, width="100%", height=550)

        except Exception as e:
            st.error(f"Map rendering failed: {str(e)}")
            st.info("Export GeoTIFF for visualization in QGIS.")


    with subtab2:
        # =================================================================
        # STATISTICS TAB: Score distribution for all eligible pixels
        # =================================================================
        st.subheader("Score Distribution")

        if len(valid_scores) > 0:
            n_oecm = int(np.sum(oecm_mask)) if oecm_mask is not None else 0
            n_classical = int(np.sum(classical_pa_mask)) if classical_pa_mask is not None else 0

            # Histogram of ALL eligible pixel scores (not just OECM-favourable)
            hist_counts, bin_edges = np.histogram(valid_scores, bins=20, range=(0, 1))
            bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2

            bin_colors = []
            for bc in bin_centers:
                if bc < 0.33:
                    bin_colors.append('#d7191c')   # Red
                elif bc < 0.67:
                    bin_colors.append('#fdae61')   # Yellow
                else:
                    bin_colors.append('#1a9641')   # Green

            fig_hist = go.Figure(data=[go.Bar(
                x=bin_centers,
                y=hist_counts,
                marker_color=bin_colors,
                name='All eligible pixels'
            )])

            export_threshold = st.session_state.get('export_threshold', 0.5)
            fig_hist.add_vline(
                x=export_threshold,
                line_dash="dash",
                line_color="black",
                line_width=2,
                annotation_text=f"Export threshold: {export_threshold:.2f}",
                annotation_position="top"
            )

            fig_hist.update_layout(
                xaxis_title="Favourability Score",
                yaxis_title="Pixel Count (eligible pixels)",
                showlegend=False,
                height=350
            )

            st.plotly_chart(fig_hist, use_container_width=True)

            if n_oecm == 0:
                st.warning(
                    "No pixels classified as OECM-favourable — Group C score "
                    f"(provisioning ES + compatible land use) is below the minimum "
                    "threshold (0.10) for all eligible pixels. "
                    "Check that provisioning_es and land use layers have valid values."
                )

            # Summary statistics for all eligible pixels
            col_stat1, col_stat2, col_stat3, col_stat4 = st.columns(4)
            with col_stat1:
                st.metric("Mean (eligible)", f"{np.mean(valid_scores):.3f}")
            with col_stat2:
                st.metric("Median (eligible)", f"{np.median(valid_scores):.3f}")
            with col_stat3:
                st.metric("Std Dev", f"{np.std(valid_scores):.3f}")
            with col_stat4:
                above_05 = np.sum(valid_scores >= 0.5) / len(valid_scores) * 100
                st.metric("% eligible ≥ 0.5", f"{above_05:.1f}%")

            col_stat5, col_stat6 = st.columns(2)
            with col_stat5:
                above_07 = np.sum(valid_scores >= 0.7) / len(valid_scores) * 100
                st.metric("% eligible ≥ 0.7", f"{above_07:.1f}%")
            with col_stat6:
                area_above_07_ha = np.sum(valid_scores >= 0.7) * pixel_area_ha
                st.metric("Area ≥ 0.7 (ha)", f"{area_above_07_ha:,.0f}")

        else:
            st.warning(
                "No eligible pixels found — all pixels were eliminated by Group D criteria. "
                "Increase the pressure threshold in the sidebar or verify input layers."
            )

        st.markdown("---")

        # =================================================================
        # Per-criterion contribution chart
        # =================================================================
        st.markdown("#### Per-Criterion Contribution")

        try:
            # Retrieve criterion arrays from session state if available
            # This requires storing intermediate criterion scores during MCE
            # For now, display parameter weights instead

            if params is not None:
                # Extract weights
                weights_data = []

                # Group A criteria
                if 'w_condition' in params:
                    weights_data.append({
                        'Criterion': 'Ecosystem Condition',
                        'Group': 'A — Ecological',
                        'Weight': params['w_condition'] * params['W_A'],
                        'Group_Letter': 'A'
                    })

                if 'w_regulating_es' in params:
                    weights_data.append({
                        'Criterion': 'Regulating ES',
                        'Group': 'A — Ecological',
                        'Weight': params['w_regulating_es'] * params['W_A'],
                        'Group_Letter': 'A'
                    })

                if 'w_pressure' in params:
                    weights_data.append({
                        'Criterion': 'Low Pressure',
                        'Group': 'A — Ecological',
                        'Weight': params['w_pressure'] * params['W_A'],
                        'Group_Letter': 'A'
                    })

                # Group B criteria
                if 'w_cultural_es' in params:
                    weights_data.append({
                        'Criterion': 'Cultural ES',
                        'Group': 'B — Co-benefits',
                        'Weight': params['w_cultural_es'] * params['W_B'],
                        'Group_Letter': 'B'
                    })

                # Group C criteria
                if 'w_provisioning_es' in params:
                    weights_data.append({
                        'Criterion': 'Provisioning ES',
                        'Group': 'C — Production',
                        'Weight': params['w_provisioning_es'] * params['W_C'],
                        'Group_Letter': 'C'
                    })

                if 'w_landuse_compatible' in params:
                    weights_data.append({
                        'Criterion': 'Compatible Land Use',
                        'Group': 'C — Production',
                        'Weight': params['w_landuse_compatible'] * params['W_C'],
                        'Group_Letter': 'C'
                    })

                weights_df = pd.DataFrame(weights_data)

                # Create horizontal bar chart
                color_map = {
                    'A': '#1a9641',  # Green
                    'B': '#378ADD',  # Blue
                    'C': '#F6A623'   # Orange
                }

                fig_weights = go.Figure()

                for group_letter in ['A', 'B', 'C']:
                    group_data = weights_df[weights_df['Group_Letter'] == group_letter]

                    if len(group_data) > 0:
                        fig_weights.add_trace(go.Bar(
                            y=group_data['Criterion'],
                            x=group_data['Weight'],
                            name=group_data['Group'].iloc[0],
                            orientation='h',
                            marker_color=color_map[group_letter],
                            text=group_data['Weight'].apply(lambda x: f"{x:.3f}"),
                            textposition='auto'
                        ))

                fig_weights.update_layout(
                    xaxis_title="Effective Weight (intra × inter)",
                    yaxis_title="Criterion",
                    barmode='group',
                    height=350,
                    legend=dict(
                        orientation="h",
                        yanchor="bottom",
                        y=1.02,
                        xanchor="right",
                        x=1
                    )
                )

                st.plotly_chart(fig_weights, use_container_width=True)

                st.caption(
                    "Effective weight = intra-group weight × inter-group weight. "
                    "Bars show the relative contribution of each criterion to the final score."
                )

            else:
                st.info("Parameter information not available.")

        except Exception as e:
            st.warning(f"Could not display criterion contributions: {str(e)}")

        st.markdown("---")

        # =================================================================
        # Parameter summary table
        # =================================================================
        st.markdown("#### Current Parameter Configuration")

        if params is not None:
            param_display = pd.DataFrame([
                {'Parameter': 'Aggregation Method', 'Value': params.get('method', 'N/A')},
                {'Parameter': 'Alpha (OWA)', 'Value': f"{params.get('alpha', 0.0):.2f}" if params.get('method') == 'owa' else 'N/A'},
                {'Parameter': 'W_A (Ecological)', 'Value': f"{params.get('W_A', 0.0):.2f}"},
                {'Parameter': 'W_B (Co-benefits)', 'Value': f"{params.get('W_B', 0.0):.2f}"},
                {'Parameter': 'W_C (Production)', 'Value': f"{params.get('W_C', 0.0):.2f}"},
                {'Parameter': 'Max Pressure (hab/km²)', 'Value': f"{params.get('threshold_pressure', 0.0):.0f}"},
                {'Parameter': 'Gap Bonus', 'Value': f"{params.get('gap_bonus', 0.0):.2f}"},
            ])

            st.dataframe(
                param_display,
                hide_index=True,
                use_container_width=True
            )

            st.caption("Full parameter log available at bottom of page.")
        else:
            st.info("Parameter information not available.")

    st.markdown("---")

    # ===================================================================
    # Row 4: Export panel
    # ===================================================================
    st.subheader("Export & Reporting")

    # Threshold slider for polygon export
    export_threshold = st.slider(
        "Favourability threshold for polygon export",
        min_value=0.0,
        max_value=1.0,
        value=0.6,
        step=0.05,
        help="Pixels above this threshold will be vectorised and exported as shapefile"
    )

    # Store threshold in session state for histogram display
    st.session_state['export_threshold'] = export_threshold

    col_exp1, col_exp2, col_exp3, col_exp4 = st.columns(4)

    # Import export functions
    from modules.module2_favourability import export as export_module

    with col_exp1:
        if st.button("Export GeoTIFF"):
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix='.tif') as tmp:
                    export_module.export_geotiff(
                        array=score_array,
                        profile=profile,
                        output_path=tmp.name
                    )

                    # Read file for download
                    with open(tmp.name, 'rb') as f:
                        geotiff_bytes = f.read()

                    st.download_button(
                        label="Download GeoTIFF",
                        data=geotiff_bytes,
                        file_name="favourability_scores.tif",
                        mime="image/tiff"
                    )

                    st.success("GeoTIFF ready for download!")

            except Exception as e:
                st.error(f"GeoTIFF export failed: {str(e)}")

    with col_exp2:
        if st.button("Export Shapefile (ZIP)"):
            try:
                import zipfile

                # Create temporary directory for shapefile components
                with tempfile.TemporaryDirectory() as tmpdir:
                    shp_path = Path(tmpdir) / "favourable_zones.shp"

                    export_module.export_shapefile(
                        score_array=score_array,
                        profile=profile,
                        threshold=export_threshold,
                        output_path=str(shp_path)
                    )

                    # Zip all shapefile components
                    zip_path = Path(tmpdir) / "favourable_zones.zip"
                    with zipfile.ZipFile(zip_path, 'w') as zipf:
                        for ext in ['.shp', '.shx', '.dbf', '.prj', '.cpg']:
                            component = shp_path.with_suffix(ext)
                            if component.exists():
                                zipf.write(component, component.name)

                    # Read zip for download
                    with open(zip_path, 'rb') as f:
                        zip_bytes = f.read()

                    st.download_button(
                        label="Download Shapefile (ZIP)",
                        data=zip_bytes,
                        file_name="favourable_zones.zip",
                        mime="application/zip"
                    )

                    st.success(f"Shapefile ready (threshold: {export_threshold:.2f})!")

            except Exception as e:
                st.error(f"Shapefile export failed: {str(e)}")

    with col_exp3:
        if st.button("Export CSV Stats"):
            try:
                # Build comprehensive stats table
                pa_gdf = st.session_state.get('pa_gdf')
                wdpa_area_ha = 0.0
                n_pa_sites = 0
                if pa_gdf is not None:
                    try:
                        wdpa_area_ha = float(pa_gdf.geometry.union_all().area) / 10000.0
                        n_pa_sites = len(pa_gdf)
                    except Exception:
                        pass

                stats_df = pd.DataFrame([
                    {'metric': 'Territory grid area (ha)',
                     'value': f"{territory_area_ha:.0f}"},
                    {'metric': 'Eligible area — passed Group D (ha)',
                     'value': f"{eligible_area_ha:.0f}"},
                    {'metric': 'Eliminated — high pressure or incompatible LU (ha)',
                     'value': f"{n_eliminated * pixel_area_ha:.0f}"},
                    {'metric': 'OECM favourable area — MCE Group C ≥ 0.10 (ha)',
                     'value': f"{oecm_area_ha:.0f}"},
                    {'metric': 'Low use-function area — MCE Group C < 0.10 (ha)',
                     'value': f"{classical_pa_area_ha:.0f}"},
                    {'metric': 'Median favourability score (eligible pixels)',
                     'value': f"{median_score:.3f}"},
                    {'metric': 'Existing WDPA protected area — union (ha)',
                     'value': f"{wdpa_area_ha:.0f}" if wdpa_area_ha > 0 else 'Not loaded'},
                    {'metric': 'Existing WDPA sites (count)',
                     'value': str(n_pa_sites) if n_pa_sites > 0 else 'Not loaded'},
                ])

                with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.csv') as tmp:
                    export_module.export_csv_stats(
                        stats_df=stats_df,
                        output_path=tmp.name
                    )

                    # Read file for download
                    with open(tmp.name, 'r') as f:
                        csv_data = f.read()

                    st.download_button(
                        label="Download CSV",
                        data=csv_data,
                        file_name="favourability_statistics.csv",
                        mime="text/csv"
                    )

                    st.success("CSV ready for download!")

            except Exception as e:
                st.error(f"CSV export failed: {str(e)}")

    with col_exp4:
        if st.button("Generate PDF Report"):
            try:
                # Create temporary map image from score_array
                with tempfile.NamedTemporaryFile(delete=False, suffix='.png') as tmp_img:
                    import matplotlib.cm as mcm
                    _cmap = mcm.get_cmap('RdYlGn')
                    _norm = mcolors.Normalize(vmin=0.0, vmax=1.0)
                    _rgba = np.zeros((*score_array.shape, 4), dtype=np.uint8)
                    _vm = ~np.isnan(score_array)
                    _rgba[_vm] = (_cmap(_norm(score_array[_vm])) * 255).astype(np.uint8)
                    fig_map, ax = plt.subplots(figsize=(10, 8))
                    ax.imshow(_rgba)
                    ax.axis('off')
                    plt.savefig(tmp_img.name, bbox_inches='tight', dpi=150)
                    plt.close()

                    # Build comprehensive stats table for PDF
                    pa_gdf = st.session_state.get('pa_gdf')
                    wdpa_area_ha_pdf = 0.0
                    n_pa_sites_pdf = 0
                    if pa_gdf is not None:
                        try:
                            wdpa_area_ha_pdf = float(pa_gdf.geometry.union_all().area) / 10000.0
                            n_pa_sites_pdf = len(pa_gdf)
                        except Exception:
                            pass

                    stats_df = pd.DataFrame([
                        {'Metric': 'Territory grid area (ha)',
                         'Value': f"{territory_area_ha:.0f}"},
                        {'Metric': 'Eligible area — passed Group D (ha)',
                         'Value': f"{eligible_area_ha:.0f}"},
                        {'Metric': 'Eliminated — pressure / incompatible LU (ha)',
                         'Value': f"{n_eliminated * pixel_area_ha:.0f}"},
                        {'Metric': 'OECM favourable area — MCE Group C ≥ 0.10 (ha)',
                         'Value': f"{oecm_area_ha:.0f}"},
                        {'Metric': 'Low use-function — MCE Group C < 0.10 (ha)',
                         'Value': f"{classical_pa_area_ha:.0f}"},
                        {'Metric': 'Median favourability score (eligible pixels)',
                         'Value': f"{median_score:.3f}"},
                        {'Metric': 'Existing WDPA protected area — union (ha)',
                         'Value': f"{wdpa_area_ha_pdf:.0f}" if wdpa_area_ha_pdf > 0 else 'Not loaded'},
                        {'Metric': 'Existing WDPA sites (count)',
                         'Value': str(n_pa_sites_pdf) if n_pa_sites_pdf > 0 else 'Not loaded'},
                    ])

                    # Add timestamp and spec version to params
                    if params is not None:
                        params_full = params.copy()
                        params_full['timestamp'] = datetime.now().isoformat()
                        params_full['spec_version'] = 'v0.1'
                    else:
                        params_full = {
                            'timestamp': datetime.now().isoformat(),
                            'spec_version': 'v0.1'
                        }

                    # Generate PDF
                    with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_pdf:
                        export_module.generate_pdf_report(
                            map_image_path=tmp_img.name,
                            stats_df=stats_df,
                            parameters=params_full,
                            output_path=tmp_pdf.name
                        )

                        # Read PDF for download
                        with open(tmp_pdf.name, 'rb') as f:
                            pdf_bytes = f.read()

                        st.download_button(
                            label="Download PDF Report",
                            data=pdf_bytes,
                            file_name="favourability_report.pdf",
                            mime="application/pdf"
                        )

                        st.success("PDF report ready for download!")

            except ImportError:
                st.error("PDF generation requires reportlab. Install with: pip install reportlab")
            except Exception as e:
                st.error(f"PDF generation failed: {str(e)}")

    st.markdown("---")

    # ===================================================================
    # Footer: Reproducibility note
    # ===================================================================
    st.subheader("Reproducibility & Parameter Log")

    with st.expander("View Current Parameter Configuration (JSON)"):
        # Use params passed to function or retrieve from session state
        params_to_display = params if params is not None else st.session_state.get('parameters')

        if params_to_display:
            # Add timestamp and version info if not present
            params_full = params_to_display.copy()
            if 'timestamp' not in params_full:
                params_full['timestamp'] = datetime.now().isoformat()
            if 'spec_version' not in params_full:
                params_full['spec_version'] = 'v0.1'

            def _json_safe(obj):
                """Convert non-serializable objects to strings."""
                if hasattr(obj, 'wkt'):  # shapely geometry
                    return obj.wkt
                if hasattr(obj, 'isoformat'):  # datetime
                    return obj.isoformat()
                return str(obj)

            json_str = json.dumps(params_full, indent=2, default=_json_safe)
            st.json(json.loads(json_str))
            st.download_button(
                label="Download Parameters (JSON)",
                data=json_str,
                file_name="mce_parameters.json",
                mime="application/json"
            )
        else:
            st.info("Parameter configuration not available. Run analysis to generate parameter log.")

    st.caption(
        "All parameters used in MCE computation are logged for full reproducibility. "
        "Include this JSON file with exported outputs to document analysis settings."
    )
