"""Streamlit UI for Module 2 — OECM Favourability Analysis."""
import streamlit as st
import numpy as np
import pandas as pd
import folium
from streamlit_folium import st_folium
import tempfile
from pathlib import Path


def render_tab_module2(score_array=None, oecm_mask=None, classical_pa_mask=None, profile=None):
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

    st.info(
        "Map display under development. "
        "Raster-to-PNG overlay via folium requires additional processing. "
        "For now, export GeoTIFF and open in QGIS for visualisation."
    )

    # Placeholder for map
    # TODO: Convert raster to PNG overlay using rasterio + PIL
    # Display as folium map with existing PAs overlaid

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

            # Create histogram
            hist_data = pd.DataFrame({'score': oecm_scores})

            st.bar_chart(
                hist_data['score'].value_counts(bins=10).sort_index(),
                use_container_width=True
            )

            st.caption(
                "Distribution of favourability scores across OECM favourable pixels.\n"
                "X-axis: score bins [0-1] | Y-axis: pixel count"
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
        st.markdown("#### Statistics by Territorial Unit")

        st.info(
            "Upload territorial unit vector layer (municipalities, grid cells, etc.) "
            "to compute zonal statistics."
        )

        # Placeholder for zonal statistics table
        # TODO: Implement zonal stats from uploaded vector layer

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

    col_exp1, col_exp2, col_exp3 = st.columns(3)

    with col_exp1:
        if st.button("Export GeoTIFF"):
            st.info("GeoTIFF export functionality under development (modules/module2_favourability/export.py)")

    with col_exp2:
        if st.button("Export Shapefile (Favourable Zones)"):
            st.info(
                f"Shapefile export functionality under development. "
                f"Will vectorise pixels with score > {export_threshold:.2f}"
            )

    with col_exp3:
        if st.button("Generate PDF Report"):
            st.info("PDF report generation under development (modules/module2_favourability/export.py)")

    st.markdown("---")

    # ===================================================================
    # Footer: Reproducibility note
    # ===================================================================
    st.subheader("Reproducibility & Parameter Log")

    with st.expander("View Current Parameter Configuration (JSON)"):
        # Retrieve parameters from session state
        if 'parameters' in st.session_state:
            params = st.session_state['parameters']

            import json
            st.json(params)

            # Provide download button
            json_str = json.dumps(params, indent=2)
            st.download_button(
                label="Download Parameters (JSON)",
                data=json_str,
                file_name="mce_parameters.json",
                mime="application/json"
            )
        else:
            st.info("Run MCE analysis to generate parameter log.")

    st.caption(
        "All parameters used in MCE computation are logged for full reproducibility. "
        "Include this JSON file with exported outputs to document analysis settings."
    )
