"""OECM Favourability Tool — Streamlit entry point."""
import streamlit as st
import logging
import tempfile

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

# ===================================================================
# Page configuration
# ===================================================================
st.set_page_config(
    page_title="OECM Favourability Tool",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Large, bold tab labels — close to title font size
st.markdown(
    """
    <style>
    .stTabs [data-baseweb="tab-list"] { gap: 12px; }
    .stTabs [data-baseweb="tab"] {
        font-size: 1.05rem;
        font-weight: 700;
        padding: 12px 28px;
    }
    .stTabs [aria-selected="true"] {
        border-bottom: 3px solid #2E7D32;
        color: #2E7D32;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ===================================================================
# Import UI components
# ===================================================================
from ui.sidebar import render_sidebar
from ui import tab_data_upload
from ui.tab_module1 import render_tab_module1
from ui.tab_module2 import render_tab_module2

# ===================================================================
# Main title and description
# ===================================================================
st.title("OECM Territorial Favourability Analysis Tool")

st.markdown(
    """
    Decision-support tool for identifying territories candidate for
    **Other Effective Area-based Conservation Measures (OECMs)**
    as defined by CBD COP14 decision 14/8.

    **Dual functionality:**
    - **Module 1:** Diagnostic of existing protection network (WDPA) with gap analysis
    - **Module 2:** Multi-criteria evaluation of OECM favourability
    """
)

st.markdown("---")

# ===================================================================
# Global CSS — larger, bolder tab labels
# ===================================================================
st.markdown(
    """
    <style>
    /* Tab labels — close to h1/title size */
    .stTabs [data-baseweb="tab"] {
        font-size: 2.0rem;
        font-weight: 700;
        padding: 0.8rem 2.2rem;
        letter-spacing: 0.01em;
    }
    .stTabs [data-baseweb="tab"] p {
        font-size: 2.0rem !important;
        font-weight: 700 !important;
    }
    /* Active tab underline accent */
    .stTabs [aria-selected="true"] {
        border-bottom: 4px solid #2e7d32;
        color: #2e7d32;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ===================================================================
# Sidebar: render parameter panel and store in session state
# ===================================================================
with st.sidebar:
    parameters = render_sidebar()

# Store parameters in session state for access across tabs
st.session_state['parameters'] = parameters

# Store study area geometry separately for Module 1 compatibility
if 'study_area_geometry' in parameters:
    st.session_state['territory_geom'] = parameters['study_area_geometry']

# Log current parameters (DEBUG level)
logger.debug(f"Current parameters: {parameters}")

# ===================================================================
# Tabs: Data Upload, Module 1, and Module 2
# ===================================================================
tab1, tab2, tab3 = st.tabs([
    "① Data Upload",
    "② Protection Network Diagnostic",
    "③ OECM Favourability Analysis"
])

with tab1:
    # Render data upload tab
    tab_data_upload.render()

with tab2:
    # Retrieve PA data from session state if available
    pa_gdf = st.session_state.get('pa_gdf', None)
    territory_geom = st.session_state.get('territory_geom', None)
    ecosystem_layer = st.session_state.get('ecosystem_layer', None)

    # Render Module 1 tab
    render_tab_module1(
        pa_gdf=pa_gdf,
        territory_geom=territory_geom,
        ecosystem_layer=ecosystem_layer
    )

with tab3:
    st.header("Module 2 — OECM Favourability Analysis")

    # Check if data has been uploaded
    data_ready_module2 = st.session_state.get('data_ready_module2', False)
    score_array = st.session_state.get('score_array', None)

    if not data_ready_module2:
        st.info(
            "Upload all 6 criterion rasters in the **① Data Upload** tab first."
        )
    else:
        # Retrieve raster paths from session state
        raster_paths = st.session_state.get('criterion_raster_paths', {})

        # Check if weights sum to 1.0
        weight_sum = parameters.get('W_A', 0) + parameters.get('W_B', 0) + parameters.get('W_C', 0)
        weights_valid = abs(weight_sum - 1.0) < 0.001

        st.markdown("---")

        # Run analysis button
        run_col1, run_col2, run_col3 = st.columns([1, 2, 1])

        with run_col2:
            run_button_disabled = not weights_valid

            if not weights_valid:
                st.error(f"Inter-group weights must sum to 1.0 (current sum: {weight_sum:.3f})")

            run_button = st.button(
                "Run MCE Analysis",
                type="primary",
                disabled=run_button_disabled,
                use_container_width=True
            )

        if run_button:
            with st.spinner("Loading and aligning raster layers (cached after first run)..."):
                try:
                    # Import required modules
                    from modules.module2_favourability import raster_preprocessing
                    from modules.module2_favourability import mce_engine
                    import yaml
                    from pathlib import Path

                    # Load settings for resolution and CRS
                    settings_path = Path(__file__).parent / "config" / "settings.yaml"
                    with open(settings_path, 'r') as f:
                        settings = yaml.safe_load(f)

                    target_resolution = settings.get('resolution_m', 100.0)
                    target_crs = settings.get('crs', 'EPSG:3035')
                    study_area_geom = parameters.get('study_area_geometry')

                    # -------------------------------------------------------
                    # Cached load + align: only re-runs when files or study
                    # area change. Changing weights/method/threshold does NOT
                    # trigger re-alignment (major speed-up on every re-run).
                    # -------------------------------------------------------
                    @st.cache_data(show_spinner=False)
                    def _load_and_align(paths_frozen, study_area_wkt, resolution, crs):
                        """Load and align all rasters. Cache key = paths + study area."""
                        from shapely.wkt import loads as _wkt_loads
                        from modules.module2_favourability import raster_preprocessing as _rp
                        sa_geom = _wkt_loads(study_area_wkt) if study_area_wkt else None
                        raster_dict = {}
                        for name, path in paths_frozen:
                            arr, prof = _rp.load_raster(path)
                            raster_dict[name] = (arr, prof)
                        return _rp.align_rasters(
                            raster_dict,
                            study_area_geom=sa_geom,
                            resolution=resolution,
                            crs=crs
                        )

                    # Build hashable cache key
                    layer_order = [
                        'ecosystem_condition', 'regulating_es',
                        'anthropogenic_pressure', 'cultural_es',
                        'provisioning_es', 'landuse'
                    ]
                    paths_frozen = tuple((k, raster_paths[k]) for k in layer_order)
                    study_area_wkt = study_area_geom.wkt if study_area_geom else ''

                    aligned = _load_and_align(
                        paths_frozen, study_area_wkt, target_resolution, target_crs
                    )

                    # Extract aligned arrays
                    eco_aligned       = aligned['ecosystem_condition'][0]
                    reg_aligned       = aligned['regulating_es'][0]
                    pressure_aligned  = aligned['anthropogenic_pressure'][0]
                    cult_aligned      = aligned['cultural_es'][0]
                    prov_aligned      = aligned['provisioning_es'][0]
                    landuse_aligned   = aligned['landuse'][0]
                    reference_profile = aligned['ecosystem_condition'][1]

                    st.success("Rasters loaded and aligned!")

                except Exception as e:
                    st.error(f"Raster loading/alignment failed: {str(e)}")
                    logger.exception("Raster loading/alignment error:")
                    st.stop()

            with st.spinner("Computing favourability scores..."):
                try:
                    # Prepare weight structure
                    weights = {
                        'inter_group_weights': {
                            'W_A': parameters['W_A'],
                            'W_B': parameters['W_B'],
                            'W_C': parameters['W_C']
                        },
                        'group_a_weights': {
                            'ecosystem_condition': parameters['w_condition'],
                            'regulating_es': parameters['w_regulating_es'],
                            'low_pressure': parameters['w_pressure']
                        },
                        'group_b_weights': {
                            'cultural_es': parameters['w_cultural_es']
                        },
                        'group_c_weights': {
                            'provisioning_es': parameters['w_provisioning_es'],
                            'compatible_landuse': parameters['w_landuse_compatible']
                        }
                    }

                    # Build gap mask from Module 1 gap layers (if available)
                    gap_mask = None
                    gap_bonus_val = parameters.get('gap_bonus', 0.0)
                    if gap_bonus_val > 0.0 and 'gap_layers' in st.session_state:
                        try:
                            import numpy as np
                            from rasterio.features import rasterize as _rasterize

                            gap_layers = st.session_state['gap_layers']
                            target_crs_obj = reference_profile['crs']
                            target_shape = (reference_profile['height'],
                                            reference_profile['width'])
                            target_transform = reference_profile['transform']

                            # Combine strict_gaps + qualitative_gaps into one mask
                            all_geoms = []
                            for key in ('strict_gaps', 'qualitative_gaps'):
                                gdf = gap_layers.get(key)
                                if gdf is not None and len(gdf) > 0:
                                    reprojected = gdf.to_crs(target_crs_obj)
                                    valid = reprojected[
                                        ~reprojected.geometry.is_empty
                                        & reprojected.geometry.notnull()
                                    ]
                                    all_geoms.extend(
                                        (geom, 1) for geom in valid.geometry
                                    )

                            if all_geoms:
                                gap_raster = _rasterize(
                                    shapes=all_geoms,
                                    out_shape=target_shape,
                                    transform=target_transform,
                                    fill=0,
                                    dtype='uint8'
                                )
                                gap_mask = gap_raster.astype(bool)
                                logger.info(
                                    f"Gap mask built: {np.sum(gap_mask)} gap pixels "
                                    f"out of {gap_mask.size}"
                                )
                            else:
                                logger.info("No gap geometries found, skipping gap bonus")
                        except Exception as e:
                            logger.warning(f"Failed to build gap mask: {e}")
                            gap_mask = None

                    # Run MCE
                    results = mce_engine.compute_favourability(
                        ecosystem_condition=eco_aligned,
                        regulating_es=reg_aligned,
                        cultural_es=cult_aligned,
                        provisioning_es=prov_aligned,
                        anthropogenic_pressure=pressure_aligned,
                        landuse=landuse_aligned,
                        weights=weights,
                        method=parameters['method'],
                        alpha=parameters['alpha'],
                        threshold_pressure=parameters.get('threshold_pressure', 150.0),
                        gap_bonus=gap_bonus_val,
                        gap_mask=gap_mask
                    )

                    # Store results in session state
                    st.session_state['score_array'] = results['score']
                    st.session_state['oecm_mask'] = results['oecm_mask']
                    st.session_state['classical_pa_mask'] = results['classical_pa_mask']
                    st.session_state['eliminatory_mask'] = results['eliminatory_mask']
                    st.session_state['raster_profile'] = reference_profile

                    st.success("MCE analysis complete!")

                except Exception as e:
                    st.error(f"MCE computation failed: {str(e)}")
                    logger.exception("MCE computation error:")
                    st.stop()

    # Show results when analysis has been run
    if data_ready_module2 and score_array is None:
        st.info(
            "Configure weights in the sidebar and click **Run MCE Analysis** above "
            "to compute favourability scores."
        )
    elif score_array is not None:
        oecm_mask = st.session_state.get('oecm_mask', None)
        classical_pa_mask = st.session_state.get('classical_pa_mask', None)
        eliminatory_mask = st.session_state.get('eliminatory_mask', None)
        raster_profile = st.session_state.get('raster_profile', None)

        render_tab_module2(
            score_array=score_array,
            oecm_mask=oecm_mask,
            classical_pa_mask=classical_pa_mask,
            eliminatory_mask=eliminatory_mask,
            profile=raster_profile,
            params=parameters
        )

# ===================================================================
# Footer
# ===================================================================
st.markdown("---")
st.caption(
    "OECM Favourability Tool v0.1 | "
    "Developed with Claude Code | "
    "Full specifications: .claude/agents/SPECIFICATIONS.md"
)
