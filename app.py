"""OECM Favourability Tool — Streamlit entry point."""
import streamlit as st
import logging
import tempfile
import yaml
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


@st.cache_resource
def _load_settings() -> dict:
    """Load settings.yaml once for the lifetime of the server process."""
    settings_path = Path(__file__).parent / "config" / "settings.yaml"
    with open(settings_path, 'r') as f:
        return yaml.safe_load(f)


_settings = _load_settings()

# ===================================================================
# Page configuration
# ===================================================================
st.set_page_config(
    page_title="OECM Favourability Tool",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Tab styling: bold labels, 2 rows of 2 (flex-wrap)
st.markdown(
    """
    <style>
    /* Wrap tabs onto 2 rows of 2 */
    .stTabs [data-baseweb="tab-list"] {
        flex-wrap: wrap;
        gap: 8px 12px;
    }
    .stTabs [data-baseweb="tab"] {
        flex: 0 0 calc(50% - 8px);
        box-sizing: border-box;
        font-size: 2.1rem;
        font-weight: 700;
        padding: 16px 24px;
        justify-content: flex-start;
    }
    .stTabs [data-baseweb="tab"] p {
        font-size: 2.1rem !important;
        font-weight: 700 !important;
    }
    .stTabs [aria-selected="true"] {
        border-bottom: 3px solid #2E7D32;
        color: #2E7D32;
    }
    /* Suppress grey overlay during recomputation */
    [data-testid="stAppViewBlockContainer"],
    .stApp > header + div,
    div[class*="stale"] { opacity: 1 !important; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ===================================================================
# Import UI components
# ===================================================================
from ui.sidebar import render_sidebar
from ui import tab_data_upload
from ui.tab_ahp import render_tab_ahp
from ui.tab_module1 import render_tab_module1
from ui.tab_module2 import render_tab_module2

# ===================================================================
# Main title and description
# ===================================================================
st.title("OECM Conservation Planning Tool")

st.markdown(
    """
    GIS decision-support tool for identifying and assessing candidate territories for
    **Other Effective Area-based Conservation Measures (OECMs)**,
    aligned with **KMGBF Target 3** (CBD COP15 decision 15/4) and the global **30×30** biodiversity commitment.

    | Step | Module | Description |
    |---|---|---|
    | ① | **Data Upload** | Load WDPA protected areas, NUTS study-area boundaries, and MCE criterion rasters |
    | ② | **Weight Calibration (AHP)** | Set criterion importance using Analytic Hierarchy Process pairwise comparisons |
    | ③ | **Protection Network Diagnostic** | WDPA coverage statistics, KMGBF indicator, ecosystem representativity, gap analysis |
    | ④ | **OECM Favourability Analysis** | Multi-criteria evaluation, candidate site delineation, sensitivity analysis, and GeoTIFF / DOCX export |
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

# Store study area geometry separately for Module 1 compatibility
if 'study_area_geometry' in parameters:
    st.session_state['territory_geom'] = parameters['study_area_geometry']

# Log current parameters (DEBUG level)
logger.debug(f"Current parameters: {parameters}")

# ===================================================================
# Tabs: Data Upload, Module 1, and Module 2
# ===================================================================
tab1, tab2, tab3, tab4 = st.tabs([
    "① Data Upload",
    "② Weight Calibration (AHP)",
    "③ Protection Network Diagnostic",
    "④ OECM Favourability Analysis"
])

with tab1:
    tab_data_upload.render()

with tab2:
    render_tab_ahp()

with tab3:
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

with tab4:
    st.header("Module 2 — OECM Favourability Analysis")

    # Check if data has been uploaded
    data_ready_module2 = st.session_state.get('data_ready_module2', False)

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

        # -------------------------------------------------------
        # Cached load + align: only re-runs when files or study
        # area change. Changing weights/method/threshold does NOT
        # trigger re-alignment (major speed-up on every re-run).
        # -------------------------------------------------------
        @st.cache_data(show_spinner=False)
        def _load_and_align(paths_frozen, study_area_wkt, resolution, crs):
            """Load and align all rasters. Cache key = paths + study area.

            When a study area is available, each raster is read via a windowed
            read limited to the study area bounding box before alignment.
            This avoids loading full EU-wide extents into memory.
            """
            from shapely.wkt import loads as _wkt_loads
            from modules.module2_favourability import raster_preprocessing as _rp
            sa_geom = _wkt_loads(study_area_wkt) if study_area_wkt else None
            raster_dict = {}
            for name, path in paths_frozen:
                if sa_geom is not None:
                    arr, prof = _rp.load_raster_windowed(
                        path, clip_geom=sa_geom, geom_crs=crs
                    )
                else:
                    arr, prof = _rp.load_raster(path)
                raster_dict[name] = (arr, prof)
            return _rp.align_rasters(
                raster_dict,
                study_area_geom=sa_geom,
                resolution=resolution,
                crs=crs
            )

        # Build hashable cache key from current raster paths + study area
        target_resolution = _settings.get('resolution_m', 100.0)
        target_crs = _settings.get('crs', 'EPSG:3035')
        study_area_geom = parameters.get('study_area_geometry')

        layer_order = [
            'ecosystem_condition', 'regulating_es',
            'anthropogenic_pressure', 'cultural_es',
            'provisioning_es', 'landuse'
        ]
        paths_frozen = tuple((k, raster_paths[k]) for k in layer_order)
        study_area_wkt = study_area_geom.wkt if study_area_geom else ''

        # Check whether aligned arrays are already in session state for the
        # current set of paths (so we know if Load & Align has been run)
        aligned_key = st.session_state.get('_aligned_key')
        current_key = (paths_frozen, study_area_wkt, target_resolution, target_crs)
        rasters_aligned = aligned_key == current_key

        # ------------------------------------------------------------------
        # Step 1 — Load & Align button (only needed when files/area change)
        # ------------------------------------------------------------------
        load_col1, load_col2, load_col3 = st.columns([1, 2, 1])
        with load_col2:
            load_button = st.button(
                "Load & Align Rasters",
                type="secondary" if rasters_aligned else "primary",
                use_container_width=True,
                help="Re-run only when you change raster files or the study area."
            )

        if load_button:
            with st.spinner("Loading and aligning raster layers (cached after first run)..."):
                try:
                    from modules.module2_favourability import mce_engine  # noqa: F401 — ensure importable
                    aligned = _load_and_align(
                        paths_frozen, study_area_wkt, target_resolution, target_crs
                    )
                    # Store aligned arrays and profile in session state
                    st.session_state['_aligned_arrays'] = {
                        k: aligned[k][0] for k in layer_order
                    }
                    st.session_state['_aligned_profile'] = aligned['ecosystem_condition'][1]
                    st.session_state['_aligned_key'] = current_key
                    # Clear previous MCE results so they are recomputed below
                    for _k in ('score_array', 'oecm_mask', 'classical_pa_mask',
                               'eliminatory_mask', 'raster_profile'):
                        st.session_state.pop(_k, None)
                    st.success("Rasters loaded and aligned!")
                    rasters_aligned = True
                except Exception as e:
                    st.error(f"Raster loading/alignment failed: {str(e)}")
                    logger.exception("Raster loading/alignment error:")

        # ------------------------------------------------------------------
        # Step 2 — MCE computation: auto-runs on every rerun when aligned
        # ------------------------------------------------------------------
        if rasters_aligned:
            if not weights_valid:
                st.error(
                    f"Inter-group weights must sum to 1.0 (current sum: {weight_sum:.3f})"
                )
            else:
                from modules.module2_favourability import mce_engine

                aligned_arrays  = st.session_state['_aligned_arrays']
                reference_profile = st.session_state['_aligned_profile']

                # Prepare weight structure — normalize inter-group weights to exactly
                # 1.0 to avoid floating-point drift triggering the engine's atol=1e-6 check.
                _wa, _wb, _wc = parameters['W_A'], parameters['W_B'], parameters['W_C']
                _wsum = _wa + _wb + _wc
                weights = {
                    'inter_group_weights': {
                        'W_A': _wa / _wsum,
                        'W_B': _wb / _wsum,
                        'W_C': _wc / _wsum,
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

                        all_geoms = []
                        for _gkey in ('strict_gaps', 'qualitative_gaps'):
                            gdf = gap_layers.get(_gkey)
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

                # ── PA proximity raster (distance transform from WDPA) ──────
                pa_proximity_raster = None
                if parameters.get('proximity_bonus', 0.0) > 0.0:
                    try:
                        import numpy as np
                        from scipy.ndimage import distance_transform_edt as _edt
                        from rasterio.features import rasterize as _rasterize2
                        pa_gdf_prox = st.session_state.get('pa_gdf')
                        if pa_gdf_prox is not None and len(pa_gdf_prox) > 0:
                            _pa_repr = pa_gdf_prox.to_crs(reference_profile['crs'])
                            _pa_bin  = _rasterize2(
                                shapes=[(g, 1) for g in _pa_repr.geometry
                                        if g and not g.is_empty],
                                out_shape=(reference_profile['height'],
                                           reference_profile['width']),
                                transform=reference_profile['transform'],
                                fill=0, dtype='uint8'
                            )
                            pixel_size_m = abs(reference_profile['transform'][0])
                            # distance_transform_edt returns distance in pixels
                            pa_proximity_raster = _edt(
                                1 - _pa_bin
                            ).astype(np.float32) * pixel_size_m
                            logger.info("PA proximity raster computed")
                    except Exception as _e:
                        logger.warning(f"PA proximity raster failed: {_e}")

                try:
                    with st.spinner("Computing favourability scores…"):
                        results = mce_engine.compute_favourability(
                            ecosystem_condition=aligned_arrays['ecosystem_condition'],
                            regulating_es=aligned_arrays['regulating_es'],
                            cultural_es=aligned_arrays['cultural_es'],
                            provisioning_es=aligned_arrays['provisioning_es'],
                            anthropogenic_pressure=aligned_arrays['anthropogenic_pressure'],
                            landuse=aligned_arrays['landuse'],
                            weights=weights,
                            method=parameters['method'],
                            alpha=parameters['alpha'],
                            threshold_pressure=parameters.get('threshold_pressure', 150.0),
                            gap_bonus=gap_bonus_val,
                            gap_mask=gap_mask,
                            percentile_norm=parameters.get('percentile_norm', False),
                            proximity_bonus=parameters.get('proximity_bonus', 0.0),
                            proximity_decay_km=parameters.get('proximity_decay_km', 10.0),
                            pa_proximity_raster=pa_proximity_raster,
                        )

                    score_out        = results['score'].copy()
                    oecm_mask_out    = results['oecm_mask'].copy()
                    classical_out    = results['classical_pa_mask'].copy()
                    elim_mask_out    = results['eliminatory_mask'].copy()

                    # ── Optional: mask out pixels inside existing PAs ────────
                    if parameters.get('exclude_pa_pixels') and 'pa_gdf' in st.session_state:
                        import numpy as np
                        from rasterio.features import rasterize as _rasterize_pa
                        _pa_gdf_ex  = st.session_state['pa_gdf']
                        _ex_classes = parameters.get('exclude_pa_classes', [])
                        if _ex_classes and 'protection_class' in _pa_gdf_ex.columns:
                            _pa_sel = _pa_gdf_ex[
                                _pa_gdf_ex['protection_class'].isin(_ex_classes)
                            ]
                        else:
                            _pa_sel = _pa_gdf_ex
                        if len(_pa_sel) > 0:
                            try:
                                _pa_repr = _pa_sel.to_crs(reference_profile['crs'])
                                _geoms   = [
                                    (g, 1) for g in _pa_repr.geometry
                                    if g is not None and not g.is_empty
                                ]
                                if _geoms:
                                    _pa_mask = _rasterize_pa(
                                        shapes=_geoms,
                                        out_shape=(reference_profile['height'],
                                                   reference_profile['width']),
                                        transform=reference_profile['transform'],
                                        fill=0, dtype='uint8'
                                    ).astype(bool)
                                    score_out[_pa_mask]     = np.nan
                                    oecm_mask_out[_pa_mask] = False
                                    classical_out[_pa_mask] = False
                                    elim_mask_out[_pa_mask] = False
                                    logger.info(
                                        "PA exclusion: masked %d pixels from %d %s",
                                        int(_pa_mask.sum()), len(_pa_sel),
                                        str(_ex_classes)
                                    )
                            except Exception as _e:
                                logger.warning("PA exclusion rasterization failed: %s", _e)

                    st.session_state['score_array']        = score_out
                    st.session_state['oecm_mask']          = oecm_mask_out
                    st.session_state['classical_pa_mask']  = classical_out
                    st.session_state['eliminatory_mask']   = elim_mask_out
                    st.session_state['raster_profile']     = reference_profile
                    st.session_state['normalised_arrays']  = results.get('normalised_arrays', {})
                    st.session_state['group_scores']       = results.get('group_scores', {})

                    render_tab_module2(
                        score_array=score_out,
                        oecm_mask=oecm_mask_out,
                        classical_pa_mask=classical_out,
                        eliminatory_mask=elim_mask_out,
                        profile=reference_profile,
                        params=parameters
                    )

                except Exception as e:
                    st.error(f"MCE computation failed: {str(e)}")
                    logger.exception("MCE computation error:")

        else:
            st.info(
                "Click **Load & Align Rasters** above to initialise the analysis. "
                "After that, scores update automatically when you adjust weights."
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
