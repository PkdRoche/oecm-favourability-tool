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
    /* Tab labels */
    .stTabs [data-baseweb="tab"] {
        font-size: 1.6rem;
        font-weight: 700;
        padding: 0.7rem 1.8rem;
        letter-spacing: 0.01em;
    }
    /* Active tab underline accent */
    .stTabs [aria-selected="true"] {
        border-bottom: 3px solid #2e7d32;
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
    # Check if data has been uploaded
    data_ready_module2 = st.session_state.get('data_ready_module2', False)

    if not data_ready_module2:
        st.info(
            "Please upload your input data in the **① Data Upload** tab first."
        )
        st.markdown(
            """
            Module 2 requires all 6 criterion rasters to be uploaded.
            Navigate to the **① Data Upload** tab to upload the required layers.
            """
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
            with st.spinner("Loading and preprocessing raster layers..."):
                try:
                    # Import required modules
                    from modules.module2_favourability import raster_preprocessing
                    from modules.module2_favourability import mce_engine

                    # Load rasters from stored paths
                    @st.cache_data
                    def load_raster_from_path(raster_path):
                        """Load raster from file path."""
                        return raster_preprocessing.load_raster(raster_path)

                    # Load all layers
                    eco_array, eco_profile = load_raster_from_path(raster_paths['ecosystem_condition'])
                    reg_array, reg_profile = load_raster_from_path(raster_paths['regulating_es'])
                    pressure_array, pressure_profile = load_raster_from_path(raster_paths['anthropogenic_pressure'])
                    cult_array, cult_profile = load_raster_from_path(raster_paths['cultural_es'])
                    prov_array, prov_profile = load_raster_from_path(raster_paths['provisioning_es'])
                    landuse_array, landuse_profile = load_raster_from_path(raster_paths['landuse'])

                    st.success("All layers loaded successfully!")

                except Exception as e:
                    st.error(f"Raster loading failed: {str(e)}")
                    logger.exception("Raster loading error:")
                    st.stop()

            with st.spinner("Aligning rasters to common grid..."):
                try:
                    # Load settings for resolution and CRS
                    import yaml
                    from pathlib import Path
                    settings_path = Path(__file__).parent / "config" / "settings.yaml"
                    with open(settings_path, 'r') as f:
                        settings = yaml.safe_load(f)

                    target_resolution = settings.get('resolution_m', 100.0)
                    target_crs = settings.get('crs', 'EPSG:3035')

                    # Get study area geometry from parameters
                    study_area_geom = parameters.get('study_area_geometry')

                    # Align all rasters
                    raster_dict = {
                        'ecosystem_condition': (eco_array, eco_profile),
                        'regulating_es': (reg_array, reg_profile),
                        'anthropogenic_pressure': (pressure_array, pressure_profile),
                        'cultural_es': (cult_array, cult_profile),
                        'provisioning_es': (prov_array, prov_profile),
                        'landuse': (landuse_array, landuse_profile)
                    }

                    # Align using study area geometry as reference grid
                    aligned = raster_preprocessing.align_rasters(
                        raster_dict,
                        study_area_geom=study_area_geom,
                        resolution=target_resolution,
                        crs=target_crs
                    )

                    # Extract aligned arrays
                    eco_aligned = aligned['ecosystem_condition'][0]
                    reg_aligned = aligned['regulating_es'][0]
                    pressure_aligned = aligned['anthropogenic_pressure'][0]
                    cult_aligned = aligned['cultural_es'][0]
                    prov_aligned = aligned['provisioning_es'][0]
                    landuse_aligned = aligned['landuse'][0]

                    # Use first profile as reference
                    reference_profile = aligned['ecosystem_condition'][1]

                    st.success("Rasters aligned to common grid!")

                except Exception as e:
                    st.error(f"Raster alignment failed: {str(e)}")
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
                        alpha=parameters['alpha']
                    )

                    # Store results in session state
                    st.session_state['score_array'] = results['score']
                    st.session_state['oecm_mask'] = results['oecm_mask']
                    st.session_state['classical_pa_mask'] = results['classical_pa_mask']
                    st.session_state['raster_profile'] = reference_profile

                    st.success("MCE analysis complete!")

                except Exception as e:
                    st.error(f"MCE computation failed: {str(e)}")
                    logger.exception("MCE computation error:")
                    st.stop()

    # Retrieve Module 2 results from session state if available
    score_array = st.session_state.get('score_array', None)
    oecm_mask = st.session_state.get('oecm_mask', None)
    classical_pa_mask = st.session_state.get('classical_pa_mask', None)
    raster_profile = st.session_state.get('raster_profile', None)

    st.markdown("---")

    # Render Module 2 tab
    render_tab_module2(
        score_array=score_array,
        oecm_mask=oecm_mask,
        classical_pa_mask=classical_pa_mask,
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
