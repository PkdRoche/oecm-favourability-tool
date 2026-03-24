"""OECM Favourability Tool — Streamlit entry point."""
import streamlit as st
import logging

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
# Sidebar: render parameter panel and store in session state
# ===================================================================
with st.sidebar:
    parameters = render_sidebar()

# Store parameters in session state for access across tabs
st.session_state['parameters'] = parameters

# Log current parameters (DEBUG level)
logger.debug(f"Current parameters: {parameters}")

# ===================================================================
# Tabs: Module 1 and Module 2
# ===================================================================
tab1, tab2 = st.tabs([
    "Module 1 — Protection Network Diagnostic",
    "Module 2 — OECM Favourability Analysis"
])

with tab1:
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

with tab2:
    # Retrieve Module 2 results from session state if available
    score_array = st.session_state.get('score_array', None)
    oecm_mask = st.session_state.get('oecm_mask', None)
    classical_pa_mask = st.session_state.get('classical_pa_mask', None)
    raster_profile = st.session_state.get('raster_profile', None)

    # Render Module 2 tab
    render_tab_module2(
        score_array=score_array,
        oecm_mask=oecm_mask,
        classical_pa_mask=classical_pa_mask,
        profile=raster_profile
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
