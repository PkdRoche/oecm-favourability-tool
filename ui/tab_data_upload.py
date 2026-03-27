"""Streamlit UI for Data Upload Tab — centralized input layer management."""
import streamlit as st
import tempfile
import configparser
from pathlib import Path
import logging
import numpy as np
import rasterio
import subprocess
import sys

# Import validation function with graceful fallback
try:
    from modules.module2_favourability.raster_preprocessing import (
        validate_and_rescale_layer, load_raster
    )
    VALIDATION_AVAILABLE = True
except ImportError:
    VALIDATION_AVAILABLE = False

logger = logging.getLogger(__name__)


def _native_browse(filetypes: list[tuple]) -> str:
    """Open a native Windows file dialog in a subprocess and return the selected path (or '')."""
    script = (
        "import tkinter as tk; from tkinter import filedialog; "
        "root = tk.Tk(); root.withdraw(); root.wm_attributes('-topmost', True); "
        f"path = filedialog.askopenfilename(filetypes={filetypes!r}); "
        "root.destroy(); print(path)"
    )
    try:
        result = subprocess.run(
            [sys.executable, '-c', script],
            capture_output=True, text=True, timeout=120
        )
        return result.stdout.strip()
    except Exception as e:
        logger.warning(f"Native file dialog failed: {e}")
        return ''


def _validate_layer(criterion_key: str, file_path: str) -> None:
    """
    Validate and rescale a raster layer, storing results in session state.

    Parameters
    ----------
    criterion_key : str
        Criterion key (e.g., 'ecosystem_condition', 'anthropogenic_pressure').
    file_path : str
        Path to the uploaded raster file.

    Notes
    -----
    This function:
    - Calls validate_and_rescale_layer() if available
    - Stores the validation report in st.session_state['validation_reports']
    - If rescaling occurred, saves the rescaled array to a new temp file
      and updates st.session_state['criterion_raster_paths']
    - Uses a session state flag to avoid re-validation on every rerender
    """
    if not VALIDATION_AVAILABLE:
        logger.warning("Validation function not available — skipping validation")
        return

    # CLC land use values are categorical integer codes — no rescaling needed
    if criterion_key == 'landuse':
        logger.info("Skipping validation for CLC land use layer (categorical codes, no rescaling)")
        st.session_state['validation_reports'][criterion_key] = {
            'criterion': criterion_key,
            'original_min': None,
            'original_max': None,
            'expected_min': 111,
            'expected_max': 523,
            'rescaled': False,
            'method': 'none',
            'warning': None
        }
        st.session_state[f"{criterion_key}_validated_path"] = file_path
        return

    # Check if we've already validated this specific file path
    validation_key = f"{criterion_key}_validated_path"
    if st.session_state.get(validation_key) == file_path:
        # Already validated this exact file — skip
        return

    # Validate and rescale
    with st.spinner(f"Validating {criterion_key.replace('_', ' ')}..."):
        try:
            # Load the raster
            array, profile = load_raster(file_path)

            # Validate and rescale
            rescaled_array, _, report = validate_and_rescale_layer(
                array=array,
                criterion_key=criterion_key,
                profile=profile
            )

            # Store validation report
            st.session_state['validation_reports'][criterion_key] = report

            # If rescaling occurred, save to new temp file and update path
            if report['rescaled']:
                with tempfile.NamedTemporaryFile(delete=False, suffix='.tif') as tmp:
                    temp_path = tmp.name

                # Write rescaled array to the temp file
                with rasterio.open(temp_path, 'w', **profile) as dst:
                    dst.write(rescaled_array, 1)

                # Update path in session state
                st.session_state['criterion_raster_paths'][criterion_key] = temp_path
                logger.info(f"Rescaled {criterion_key} saved to {temp_path}")

            # Mark this path as validated
            st.session_state[validation_key] = file_path

            logger.info(f"Validation complete for {criterion_key}: {report}")

        except Exception as e:
            logger.error(f"Validation failed for {criterion_key}: {e}")
            # Store error report
            st.session_state['validation_reports'][criterion_key] = {
                'criterion': criterion_key,
                'error': str(e),
                'rescaled': False
            }


def _save_project_ini(filepath: str) -> None:
    """Save current layer paths to a .ini project file.

    Parameters
    ----------
    filepath : str
        Output .ini file path.
    """
    config = configparser.ConfigParser()

    # WDPA section
    config['wdpa'] = {}
    wdpa_path = st.session_state.get('wdpa_file')
    # Prefer the original path over temp paths
    original_wdpa = st.session_state.get('_original_wdpa_path', wdpa_path)
    if original_wdpa:
        config['wdpa']['path'] = str(original_wdpa)

    # Criterion rasters section
    config['rasters'] = {}
    raster_paths = st.session_state.get('criterion_raster_paths', {})
    original_paths = st.session_state.get('_original_raster_paths', {})
    for key, path in raster_paths.items():
        # Prefer the original on-disk path over temp copies
        config['rasters'][key] = str(original_paths.get(key, path))

    # Settings section
    config['settings'] = {
        'exclude_marine_pa': str(st.session_state.get('exclude_marine_pa', True))
    }

    with open(filepath, 'w') as f:
        config.write(f)
    logger.info(f"Project saved to {filepath}")


def _load_project_ini(filepath: str) -> dict:
    """Load layer paths from a .ini project file.

    Parameters
    ----------
    filepath : str
        Input .ini file path.

    Returns
    -------
    dict
        Dictionary with keys: 'wdpa_path', 'raster_paths', 'settings'.
        Missing files are reported but non-fatal.
    """
    config = configparser.ConfigParser()
    config.read(filepath)

    result = {'wdpa_path': None, 'raster_paths': {}, 'settings': {}, 'errors': []}

    # WDPA
    wdpa_path = config.get('wdpa', 'path', fallback=None)
    if wdpa_path and Path(wdpa_path).exists():
        result['wdpa_path'] = wdpa_path
    elif wdpa_path:
        result['errors'].append(f"WDPA file not found: {wdpa_path}")

    # Rasters
    if config.has_section('rasters'):
        for key, path in config.items('rasters'):
            if Path(path).exists():
                result['raster_paths'][key] = path
            else:
                result['errors'].append(f"{key}: file not found — {path}")

    # Settings
    if config.has_section('settings'):
        for key, value in config.items('settings'):
            result['settings'][key] = value

    logger.info(f"Project loaded from {filepath}: {len(result['raster_paths'])} rasters")
    return result


def render():
    """
    Render data upload interface with validation summary.

    All uploaded files are stored in session state for consumption by
    Module 1 and Module 2 analysis tabs. No analytical code is executed here.

    Session state keys set:
    -----------------------
    wdpa_file : str or None
        Path to uploaded WDPA file (GeoPackage, Shapefile, or GeoJSON).
    criterion_raster_paths : dict
        Dictionary mapping criterion names to file paths:
        - 'ecosystem_condition': path to GeoTIFF
        - 'regulating_es': path to GeoTIFF
        - 'anthropogenic_pressure': path to GeoTIFF
        - 'cultural_es': path to GeoTIFF
        - 'provisioning_es': path to GeoTIFF
        - 'landuse': path to GeoTIFF
    data_ready : bool
        True if all required layers are uploaded, False otherwise.
    """
    st.header("Input Data Upload")
    st.markdown(
        """
        Upload all required layers before running the analysis.
        **All rasters must be in EPSG:3035** (LAEA Europe) with consistent resolution.
        """
    )

    # ===================================================================
    # Project Save / Load
    # ===================================================================
    st.subheader("Project Configuration")
    st.caption(
        "Save or load layer paths to avoid re-selecting files on each restart. "
        "The .ini file stores **file paths only** — no data is copied."
    )

    col_load, col_save = st.columns(2)

    with col_load:
        ini_file = st.file_uploader(
            "Load project (.ini)",
            type=['ini'],
            key='project_ini_upload',
            help="Load a previously saved .ini project file to restore all layer paths."
        )
        if ini_file is not None:
            # Write to temp so configparser can read it
            ini_content = ini_file.read().decode('utf-8')
            tmp_ini = Path(tempfile.gettempdir()) / 'oecm_project_load.ini'
            tmp_ini.write_text(ini_content)

            project = _load_project_ini(str(tmp_ini))

            # Apply loaded paths to session state
            if 'criterion_raster_paths' not in st.session_state:
                st.session_state['criterion_raster_paths'] = {}
            if 'validation_reports' not in st.session_state:
                st.session_state['validation_reports'] = {}
            if '_original_raster_paths' not in st.session_state:
                st.session_state['_original_raster_paths'] = {}

            # WDPA
            if project['wdpa_path']:
                st.session_state['wdpa_file'] = project['wdpa_path']
                st.session_state['_original_wdpa_path'] = project['wdpa_path']

            # Rasters — point directly to on-disk files (no temp copy needed)
            for key, path in project['raster_paths'].items():
                st.session_state['criterion_raster_paths'][key] = path
                st.session_state['_original_raster_paths'][key] = path
                _validate_layer(key, path)

            # Settings
            if project['settings'].get('exclude_marine_pa'):
                st.session_state['exclude_marine_pa'] = (
                    project['settings']['exclude_marine_pa'].lower() == 'true'
                )

            # Report
            n_loaded = len(project['raster_paths'])
            wdpa_ok = project['wdpa_path'] is not None
            st.success(
                f"Project loaded: {n_loaded} raster(s)"
                f"{', WDPA' if wdpa_ok else ''}"
            )
            if project['errors']:
                for err in project['errors']:
                    st.warning(f"Missing: {err}")

    with col_save:
        save_path = st.text_input(
            "Save project as (.ini)",
            value=str(Path.home() / 'oecm_project.ini'),
            help="Choose a path to save the current layer configuration."
        )
        if st.button("Save Project"):
            try:
                _save_project_ini(save_path)
                st.success(f"Project saved to `{save_path}`")
            except Exception as e:
                st.error(f"Failed to save project: {e}")

    # Define required layers (used throughout the render function)
    required_rasters = [
        ('ecosystem_condition', 'Ecosystem condition'),
        ('regulating_es', 'Regulating ES capacity'),
        ('anthropogenic_pressure', 'Anthropogenic pressure'),
        ('cultural_es', 'Cultural ES capacity'),
        ('provisioning_es', 'Provisioning ES capacity'),
        ('landuse', 'Land use / land cover')
    ]

    st.markdown("---")

    # ===================================================================
    # WDPA section (for Module 1)
    # ===================================================================
    st.subheader("Protected Areas Network (WDPA)")

    st.caption(
        "Supported formats: GeoPackage (.gpkg), GeoJSON (.geojson), Shapefile (.shp), ZIP archive (.zip). "
        "Click **Browse…** or paste a path directly. Use **✕ Clear** to remove and reload a different file."
    )

    col_wdpa_browse, col_wdpa_clear = st.columns([1, 1])
    with col_wdpa_browse:
        if st.button("Browse…", key='wdpa_browse'):
            chosen = _native_browse([
                ("Vector layers", "*.gpkg *.geojson *.shp *.zip"),
                ("All files", "*.*"),
            ])
            if chosen:
                st.session_state['wdpa_direct_path'] = chosen
                st.session_state.pop('pa_gdf', None)  # force reload
    with col_wdpa_clear:
        if st.button("✕ Clear", key='wdpa_clear'):
            st.session_state['wdpa_direct_path'] = ''
            st.session_state['wdpa_file'] = None
            st.session_state.pop('_original_wdpa_path', None)
            st.session_state.pop('pa_gdf', None)

    prev_wdpa = st.session_state.get('wdpa_file')
    wdpa_path_input = st.text_input(
        "WDPA file path",
        key='wdpa_direct_path',
        placeholder=r"C:\data\wdpa.gpkg",
        help="Full path to the WDPA GeoPackage (.gpkg), GeoJSON, Shapefile, or ZIP on disk.",
    )

    if wdpa_path_input:
        p = Path(wdpa_path_input)
        if p.exists():
            if prev_wdpa != str(p):
                st.session_state.pop('pa_gdf', None)  # path changed → force reload
            st.session_state['wdpa_file'] = str(p)
            st.session_state['_original_wdpa_path'] = str(p)
            st.caption(f"✅ {p.name}")
        else:
            st.warning(f"File not found: {wdpa_path_input}")
            st.session_state['wdpa_file'] = None
            st.session_state.pop('_original_wdpa_path', None)
    else:
        st.session_state['wdpa_file'] = None
        st.session_state.pop('_original_wdpa_path', None)

    def _clear_pa_gdf():
        """Reset cached PA GeoDataFrame when marine filter changes."""
        st.session_state.pop('pa_gdf', None)

    st.checkbox(
        "Exclude marine protected areas (REALM = 'Marine')",
        value=st.session_state.get('exclude_marine_pa', True),
        key='exclude_marine_pa',
        on_change=_clear_pa_gdf,
        help=(
            "Removes fully marine PAs (WDPA REALM column = 'Marine') from the analysis. "
            "Coastal and terrestrial PAs are kept. Change requires re-running the diagnostic."
        )
    )

    st.markdown("---")

    # ===================================================================
    # Criterion rasters (for Module 2)
    # ===================================================================
    st.subheader("Multi-Criteria Evaluation Layers")
    st.caption(
        "Click **Browse…** or paste a path for each GeoTIFF (EPSG:3035). "
        "Paths are saved as-is in the .ini project file — no temporary copies."
    )

    # Initialize session state dicts
    if 'criterion_raster_paths' not in st.session_state:
        st.session_state['criterion_raster_paths'] = {}
    if 'validation_reports' not in st.session_state:
        st.session_state['validation_reports'] = {}

    # Initialize original paths dict
    if '_original_raster_paths' not in st.session_state:
        st.session_state['_original_raster_paths'] = {}

    # Helper: Browse + Clear buttons with editable path input for each raster layer
    def _layer_uploader(criterion_key, label, help_text):
        widget_key = f'{criterion_key}_direct_path'

        col_browse, col_clear, col_name = st.columns([1, 1, 4])
        with col_browse:
            if st.button("Browse…", key=f'{criterion_key}_browse'):
                chosen = _native_browse([
                    ("GeoTIFF", "*.tif *.tiff"),
                    ("All files", "*.*"),
                ])
                if chosen:
                    st.session_state[widget_key] = chosen
        with col_clear:
            if st.button("✕ Clear", key=f'{criterion_key}_clear'):
                st.session_state[widget_key] = ''
                st.session_state['criterion_raster_paths'].pop(criterion_key, None)
                st.session_state['_original_raster_paths'].pop(criterion_key, None)
                st.session_state['validation_reports'].pop(criterion_key, None)
                st.session_state.pop(f"{criterion_key}_validated_path", None)

        with col_name:
            path_input = st.text_input(
                label,
                key=widget_key,
                placeholder=r"C:\data\file.tif",
                help=help_text,
            )

        if path_input:
            p = Path(path_input)
            if p.exists():
                prev = st.session_state['criterion_raster_paths'].get(criterion_key)
                st.session_state['criterion_raster_paths'][criterion_key] = str(p)
                st.session_state['_original_raster_paths'][criterion_key] = str(p)
                if prev != str(p):
                    _validate_layer(criterion_key, str(p))
                st.caption(f"✅ {p.name}")
            else:
                st.warning(f"File not found: {path_input}")
                st.session_state['criterion_raster_paths'].pop(criterion_key, None)
                st.session_state['_original_raster_paths'].pop(criterion_key, None)
                st.session_state['validation_reports'].pop(criterion_key, None)
        else:
            st.session_state['criterion_raster_paths'].pop(criterion_key, None)
            st.session_state['_original_raster_paths'].pop(criterion_key, None)
            st.session_state['validation_reports'].pop(criterion_key, None)

    col_left, col_right = st.columns(2)

    with col_left:
        st.markdown("#### Group A — Ecological Integrity")
        _layer_uploader(
            'ecosystem_condition', "Ecosystem condition [0–1]",
            "Normalised ecosystem condition index (0 = degraded, 1 = pristine)."
        )
        _layer_uploader(
            'regulating_es', "Regulating ES capacity [0–1]",
            "Regulating ecosystem services capacity (e.g. carbon storage, water regulation)."
        )
        _layer_uploader(
            'anthropogenic_pressure', "Anthropogenic pressure (hab/km²)",
            "Human population density or composite anthropogenic pressure index. Raw values accepted."
        )

    with col_right:
        st.markdown("#### Group B — Co-benefits")
        _layer_uploader(
            'cultural_es', "Cultural ES capacity [0–1]",
            "Cultural ecosystem services capacity (e.g. recreation, landscape aesthetics)."
        )
        st.markdown("#### Group C — Production Function")
        _layer_uploader(
            'provisioning_es', "Provisioning ES capacity [0–1]",
            "Provisioning ecosystem services capacity (e.g. food, timber, water supply)."
        )
        _layer_uploader(
            'landuse', "Land use / land cover — CLC 2018 (categorical)",
            "Corine Land Cover 2018 GeoTIFF (up to 2 GB supported). "
            "Download free from https://land.copernicus.eu/pan-european/corine-land-cover"
        )

    st.markdown("---")

    # ===================================================================
    # Layer Validation section
    # ===================================================================
    if VALIDATION_AVAILABLE:
        st.subheader("Layer Validation")

        validation_reports = st.session_state.get('validation_reports', {})
        uploaded_rasters = st.session_state.get('criterion_raster_paths', {})

        # Check if any layers have been uploaded
        if uploaded_rasters:
            # Display validation status for each layer in required_rasters
            for key, label in required_rasters:
                col_layer, col_status = st.columns([3, 1])

                with col_layer:
                    st.markdown(f"**{label}**")

                    if key in validation_reports:
                        report = validation_reports[key]

                        # Check for validation error
                        if 'error' in report:
                            st.error(f"Validation failed: {report['error']}")
                        else:
                            # Build display message
                            orig_min = report.get('original_min', 'N/A')
                            orig_max = report.get('original_max', 'N/A')
                            exp_min = report.get('expected_min', 'N/A')
                            exp_max = report.get('expected_max', 'N/A')

                            # Format ranges
                            if isinstance(orig_min, (int, float)) and isinstance(orig_max, (int, float)):
                                orig_range = f"[{orig_min:.3f}, {orig_max:.3f}]"
                            else:
                                orig_range = f"[{orig_min}, {orig_max}]"

                            if isinstance(exp_min, (int, float)) and isinstance(exp_max, (int, float)):
                                if exp_min == 0 and exp_max == 1:
                                    exp_range = "[0, 1]"
                                else:
                                    exp_range = f"[{exp_min:.3f}, {exp_max:.3f}]"
                            else:
                                exp_range = str(exp_max) if exp_max == exp_min else f"[{exp_min}, {exp_max}]"

                            st.caption(f"Original: {orig_range} → Expected: {exp_range}")

                            if report.get('warning'):
                                st.warning(f"⚠️ {report['warning']}")

                    elif key in uploaded_rasters:
                        st.caption("Uploaded — validation pending")
                    else:
                        st.caption("Not uploaded")

                with col_status:
                    if key in validation_reports:
                        report = validation_reports[key]

                        if 'error' in report:
                            st.error("⚪ Error")
                        elif report.get('rescaled'):
                            st.info("🔵 Auto-rescaled")
                        elif report.get('warning'):
                            st.warning("🟡 Warning")
                        else:
                            st.success("🟢 OK")
                    elif key in uploaded_rasters:
                        st.info("⏳ Pending")
                    else:
                        st.error("⚪ Not uploaded")

                st.markdown("---")

        else:
            st.info("Upload raster layers above to see validation results.")

    st.markdown("---")

    # ===================================================================
    # Validation summary
    # ===================================================================
    st.subheader("Upload Status")

    # Check upload status
    uploaded_rasters = st.session_state.get('criterion_raster_paths', {})
    wdpa_uploaded = st.session_state.get('wdpa_file') is not None

    col_status1, col_status2 = st.columns(2)

    with col_status1:
        st.markdown("**Protected Areas:**")
        if wdpa_uploaded:
            st.success("✓ WDPA layer uploaded")
        else:
            st.error("✗ WDPA layer missing")

    with col_status2:
        st.markdown("**MCE Criterion Rasters:**")
        missing_rasters = []
        for key, label in required_rasters:
            if key in uploaded_rasters:
                st.success(f"✓ {label}")
            else:
                st.error(f"✗ {label}")
                missing_rasters.append(label)

    # Overall validation status
    all_rasters_uploaded = len(missing_rasters) == 0
    data_ready_module1 = wdpa_uploaded
    data_ready_module2 = all_rasters_uploaded

    # Store validation flags in session state
    st.session_state['data_ready_module1'] = data_ready_module1
    st.session_state['data_ready_module2'] = data_ready_module2

    st.markdown("---")

    # ===================================================================
    # Validation button and status message
    # ===================================================================
    st.subheader("Ready to Proceed")

    col_ready1, col_ready2 = st.columns([2, 1])

    with col_ready1:
        if data_ready_module1 and data_ready_module2:
            st.success(
                "All required layers uploaded successfully! "
                "You may now proceed to Module 1 and Module 2 analysis tabs."
            )
            st.session_state['data_ready'] = True
        elif data_ready_module1 and not data_ready_module2:
            st.info(
                "WDPA layer uploaded — Module 1 (Protection Network Diagnostic) is ready. "
                f"Upload {len(missing_rasters)} remaining raster(s) to enable Module 2."
            )
            st.session_state['data_ready'] = False
        elif not data_ready_module1 and data_ready_module2:
            st.info(
                "All MCE rasters uploaded — Module 2 (OECM Favourability) is ready. "
                "Upload WDPA layer to enable Module 1."
            )
            st.session_state['data_ready'] = False
        else:
            st.warning(
                "Upload all required layers to proceed. "
                "At minimum, upload WDPA for Module 1 or all 6 rasters for Module 2."
            )
            st.session_state['data_ready'] = False

    # ===================================================================
    # Data validation notes
    # ===================================================================
    with st.expander("Data Requirements & Validation"):
        st.markdown(
            """
            ### Raster Requirements
            All criterion rasters must satisfy:
            - **CRS:** EPSG:3035 (Lambert Azimuthal Equal Area — Europe)
            - **Resolution:** Consistent across all layers (recommended: 100m)
            - **Extent:** Identical bounding box and dimensions
            - **Format:** GeoTIFF (.tif or .tiff)
            - **Value range:**
              - Normalized criteria [0-1]: ecosystem condition, regulating ES, cultural ES, provisioning ES
              - Anthropogenic pressure: raw values (hab/km²)
              - Land use: categorical integer codes (e.g., CLC 2018)

            ### Vector Requirements (WDPA)
            - **Formats:** GeoPackage (.gpkg), Shapefile (.shp), or GeoJSON (.geojson)
            - **Required columns:**
              - `IUCN_CAT`: IUCN category (Ia, Ib, II, III, IV, V, VI, Not Reported)
              - `DESIG_TYPE`: Designation type (National, Regional, International)
              - `WDPA_NAME` or `name`: Protected area name
            - **Geometry:** Polygon or MultiPolygon in any CRS (will be reprojected to EPSG:3035)

            ### Pre-processing Notes
            - Raster alignment is performed automatically during MCE execution
            - WDPA geometries are classified into 5 protection classes based on IUCN category
            - Missing or invalid geometries are automatically filtered
            """
        )

    # ===================================================================
    # Session state debug info (collapsible)
    # ===================================================================
    with st.expander("Debug: Session State"):
        st.json({
            'wdpa_file': st.session_state.get('wdpa_file', 'Not uploaded'),
            'criterion_raster_paths': list(st.session_state.get('criterion_raster_paths', {}).keys()),
            'data_ready': st.session_state.get('data_ready', False),
            'data_ready_module1': st.session_state.get('data_ready_module1', False),
            'data_ready_module2': st.session_state.get('data_ready_module2', False)
        })
