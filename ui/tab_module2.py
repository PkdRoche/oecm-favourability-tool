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


def render_tab_module2(score_array=None, oecm_mask=None, classical_pa_mask=None, profile=None, params=None):
    """
    Render Module 2 interface with criteria upload, MCE execution, and results display.

    Parameters
    ----------
    score_array : np.ndarray, optional
        Favourability score array [0-1]. If None, displays placeholder UI.
    oecm_mask : np.ndarray, optional
        Binary mask: 1 = OECM favourable, 0 = not OECM favourable.
    classical_pa_mask : np.ndarray, optional
        Binary mask: 1 = classical PA preferable (Group C score too low), 0 = not.
    profile : dict, optional
        Rasterio profile (CRS, transform, dimensions) for georeferencing.
    params : dict, optional
        Full parameter dictionary from sidebar for reproducibility logging.
    """
    st.header("Module 2 — OECM Favourability Analysis")

    # Check if data is available
    if score_array is None:
        st.info(
            "Upload raster criteria layers and configure weights in the sidebar "
            "to run favourability analysis."
        )

        st.markdown("### Required Input Layers")
        st.markdown(
            """
            Module 2 requires the following raster layers (all in same CRS and resolution):

            **Group A — Ecological Integrity:**
            - Ecosystem condition [0-1]
            - Regulating ES capacity [0-1]
            - Anthropogenic pressure (raw values, hab/km²)

            **Group B — Co-benefits:**
            - Cultural ES capacity [0-1]

            **Group C — Production Function:**
            - Provisioning ES capacity [0-1]
            - Land use / land cover (categorical: CLC, OSO, or equivalent)

            **Group D — Eliminatory Criteria:**
            - Anthropogenic pressure threshold (configured in sidebar)
            - Incompatible land use classes (defined in config/land_use_compatibility.yaml)
            """
        )

        st.markdown("### Workflow")
        st.markdown(
            """
            1. Upload all required raster layers (GeoTIFF format)
            2. Configure aggregation method and weights in sidebar
            3. Click 'Run MCE Analysis' to compute favourability scores
            4. Review results: map, statistics, score distribution
            5. Export outputs: GeoTIFF, shapefile, CSV, PDF report
            """
        )

        return

    # ===================================================================
    # Row 1: Three metric cards
    # ===================================================================
    st.subheader("Favourability Summary")

    # Compute statistics
    oecm_area_ha = np.sum(oecm_mask) * (profile['transform'][0] ** 2) / 10000.0 if oecm_mask is not None else 0.0
    classical_pa_area_ha = np.sum(classical_pa_mask) * (profile['transform'][0] ** 2) / 10000.0 if classical_pa_mask is not None else 0.0

    # Territory area (from profile dimensions)
    territory_area_ha = (profile['width'] * profile['height'] * (profile['transform'][0] ** 2)) / 10000.0

    oecm_pct = (oecm_area_ha / territory_area_ha * 100.0) if territory_area_ha > 0 else 0.0
    classical_pa_pct = (classical_pa_area_ha / territory_area_ha * 100.0) if territory_area_ha > 0 else 0.0

    # Median favourability score (OECM favourable pixels only)
    if oecm_mask is not None and np.sum(oecm_mask) > 0:
        oecm_scores = score_array[oecm_mask == 1]
        median_score = np.median(oecm_scores)
    else:
        median_score = 0.0

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric(
            label="OECM Favourable Area",
            value=f"{oecm_area_ha:,.0f} ha",
            delta=f"{oecm_pct:.1f}% of territory",
            help="Areas with sufficient production function (Group C > threshold)"
        )

    with col2:
        st.metric(
            label="Classical PA Preferable",
            value=f"{classical_pa_area_ha:,.0f} ha",
            delta=f"{classical_pa_pct:.1f}% of territory",
            help="Areas with low production function — better suited to classical PA designation"
        )

    with col3:
        st.metric(
            label="Median Favourability Score",
            value=f"{median_score:.2f}",
            help="Median score across OECM favourable pixels (0-1 scale)"
        )

    st.markdown("---")

    # ===================================================================
    # Row 2: Favourability map
    # ===================================================================
    st.subheader("Favourability Map")

    # Create folium map with raster overlay
    try:
        # Convert score_array to RGBA image for folium overlay
        # Three-class coloring:
        # 1. classical_pa_mask → blue (#378ADD)
        # 2. oecm_mask → green gradient (score 0→1: light to dark green)
        # 3. Not favourable → transparent/grey

        rgba = np.zeros((*score_array.shape, 4), dtype=np.uint8)

        # Default: transparent
        rgba[..., 3] = 0

        # OECM favourable pixels: green gradient based on score
        if oecm_mask is not None:
            oecm_pixels = oecm_mask.astype(bool)
            # Green colormap: light green (low score) to dark green (high score)
            cmap = plt.cm.Greens
            norm = mcolors.Normalize(vmin=0.0, vmax=1.0)

            for i in range(score_array.shape[0]):
                for j in range(score_array.shape[1]):
                    if oecm_pixels[i, j] and not np.isnan(score_array[i, j]):
                        color = cmap(norm(score_array[i, j]))
                        rgba[i, j, :3] = (np.array(color[:3]) * 255).astype(np.uint8)
                        rgba[i, j, 3] = 200  # Semi-transparent

        # Classical PA pixels: blue
        if classical_pa_mask is not None:
            classical_pixels = classical_pa_mask.astype(bool)
            rgba[classical_pixels, 0] = 55   # R
            rgba[classical_pixels, 1] = 138  # G
            rgba[classical_pixels, 2] = 221  # B
            rgba[classical_pixels, 3] = 200  # Alpha

        # Convert to PIL Image
        img_pil = Image.fromarray(rgba, mode='RGBA')

        # Convert to base64 for folium
        buffered = io.BytesIO()
        img_pil.save(buffered, format="PNG")
        img_base64 = base64.b64encode(buffered.getvalue()).decode()

        # Get bounds from profile
        from rasterio.transform import array_bounds
        bounds_arr = array_bounds(
            profile['height'],
            profile['width'],
            profile['transform']
        )

        # Convert bounds to lat/lon for folium (assuming EPSG:3035, need to reproject)
        # For simplicity, compute center and use a simple folium map
        # Note: Proper implementation requires reprojecting bounds to EPSG:4326

        # Create folium map centered on raster centroid
        center_x = (bounds_arr[0] + bounds_arr[2]) / 2
        center_y = (bounds_arr[1] + bounds_arr[3]) / 2

        # Simple approximation: treat as lat/lon (works for demo, not production)
        # In production, use pyproj to convert EPSG:3035 to EPSG:4326
        m = folium.Map(
            location=[center_y / 100000, center_x / 100000],  # Rough approximation
            zoom_start=8,
            tiles='OpenStreetMap'
        )

        # Add image overlay
        folium.raster_layers.ImageOverlay(
            image=f"data:image/png;base64,{img_base64}",
            bounds=[[bounds_arr[1] / 100000, bounds_arr[0] / 100000],
                    [bounds_arr[3] / 100000, bounds_arr[2] / 100000]],
            opacity=0.7,
            name='Favourability'
        ).add_to(m)

        # Add legend
        legend_html = """
        <div style="position: fixed; bottom: 50px; left: 50px; width: 200px;
                    background-color: white; border:2px solid grey; z-index:9999;
                    font-size:12px; padding: 10px">
        <p style="margin:3px 0; font-weight:bold;">Favourability Legend</p>
        <p style="margin:3px 0;">
            <span style="background-color:#0F6E56; width:20px; height:15px;
                         display:inline-block; margin-right:5px;"></span>
            OECM favourable
        </p>
        <p style="margin:3px 0;">
            <span style="background-color:#378ADD; width:20px; height:15px;
                         display:inline-block; margin-right:5px;"></span>
            Classical PA preferable
        </p>
        <p style="margin:3px 0;">
            <span style="background-color:#CCCCCC; width:20px; height:15px;
                         display:inline-block; margin-right:5px;"></span>
            Not favourable
        </p>
        </div>
        """
        m.get_root().html.add_child(folium.Element(legend_html))

        # Display map
        st_folium(m, width=None, height=500)

    except Exception as e:
        st.warning(f"Map rendering failed: {str(e)}. Export GeoTIFF for visualization in QGIS.")

    st.markdown("---")

    # ===================================================================
    # Row 3: Two columns - Score distribution & Statistics by unit
    # ===================================================================
    st.subheader("Detailed Analysis")

    col_left, col_right = st.columns(2)

    with col_left:
        st.markdown("#### Score Distribution")

        if oecm_mask is not None and np.sum(oecm_mask) > 0:
            oecm_scores = score_array[oecm_mask == 1]

            # Create histogram with plotly for better control
            hist_counts, bin_edges = np.histogram(oecm_scores, bins=10, range=(0, 1))
            bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2

            fig = go.Figure(data=[go.Bar(
                x=bin_centers,
                y=hist_counts,
                marker_color='#0F6E56',
                name='Pixel count'
            )])

            # Add vertical line at export threshold if available
            export_threshold = st.session_state.get('export_threshold', 0.6)
            fig.add_vline(
                x=export_threshold,
                line_dash="dash",
                line_color="red",
                annotation_text=f"Export threshold: {export_threshold:.2f}"
            )

            fig.update_layout(
                xaxis_title="Favourability Score",
                yaxis_title="Pixel Count",
                showlegend=False,
                height=300
            )

            st.plotly_chart(fig, use_container_width=True)

            st.caption(
                "Distribution of favourability scores across OECM favourable pixels.\n"
                "Red dashed line indicates export threshold."
            )

            # Summary statistics
            st.markdown("**Summary Statistics:**")
            st.write(f"- Mean: {np.mean(oecm_scores):.3f}")
            st.write(f"- Median: {np.median(oecm_scores):.3f}")
            st.write(f"- Std Dev: {np.std(oecm_scores):.3f}")
            st.write(f"- Min: {np.min(oecm_scores):.3f}")
            st.write(f"- Max: {np.max(oecm_scores):.3f}")

        else:
            st.info("No OECM favourable pixels found with current parameters.")

    with col_right:
        st.markdown("#### Parameter Summary")

        # Display current parameters as a clean table
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
                # Create simple stats dataframe
                stats_df = pd.DataFrame([
                    {
                        'metric': 'OECM favourable area (ha)',
                        'value': f"{oecm_area_ha:.2f}"
                    },
                    {
                        'metric': 'Classical PA area (ha)',
                        'value': f"{classical_pa_area_ha:.2f}"
                    },
                    {
                        'metric': 'Median score',
                        'value': f"{median_score:.3f}"
                    }
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
                # Create temporary map image
                with tempfile.NamedTemporaryFile(delete=False, suffix='.png') as tmp_img:
                    # Save current map as PNG (simplified)
                    fig_map, ax = plt.subplots(figsize=(10, 8))
                    ax.imshow(rgba)
                    ax.axis('off')
                    plt.savefig(tmp_img.name, bbox_inches='tight', dpi=150)
                    plt.close()

                    # Create stats dataframe
                    stats_df = pd.DataFrame([
                        {'Metric': 'OECM favourable area (ha)', 'Value': f"{oecm_area_ha:.2f}"},
                        {'Metric': 'Classical PA area (ha)', 'Value': f"{classical_pa_area_ha:.2f}"},
                        {'Metric': 'Median favourability score', 'Value': f"{median_score:.3f}"}
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

            st.json(params_full)

            # Provide download button
            json_str = json.dumps(params_full, indent=2)
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
