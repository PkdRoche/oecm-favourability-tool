"""Streamlit UI for Data Upload Tab — centralized input layer management."""
import streamlit as st
import tempfile
from pathlib import Path
import logging
import numpy as np
import rasterio

# Import validation function with graceful fallback
try:
    from modules.module2_favourability.raster_preprocessing import (
        validate_and_rescale_layer, load_raster
    )
    VALIDATION_AVAILABLE = True
except ImportError:
    VALIDATION_AVAILABLE = False

logger = logging.getLogger(__name__)


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
        "**Recommended format: GeoPackage (.gpkg)** — single file, no missing components. "
        "Shapefile: upload as a ZIP archive containing .shp, .shx, .dbf and .prj."
    )

    wdpa_uploaded_file = st.file_uploader(
        "Upload WDPA protected areas layer",
        type=['gpkg', 'geojson', 'zip'],
        key='wdpa_upload',
        help=(
            "GeoPackage (.gpkg) or GeoJSON (.geojson) recommended. "
            "For Shapefiles, zip all components (.shp, .shx, .dbf, .prj) into a .zip archive. "
            "Required columns: IUCN_CAT, DESIG_TYPE."
        )
    )

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

    # Store WDPA file in session state
    if wdpa_uploaded_file is not None:
        import zipfile, os
        suffix = Path(wdpa_uploaded_file.name).suffix.lower()
        if suffix == '.zip':
            # Extract ZIP to a temp directory and find the .shp or .gpkg inside
            tmp_dir = tempfile.mkdtemp()
            zip_bytes = wdpa_uploaded_file.read()
            zip_path = os.path.join(tmp_dir, 'wdpa.zip')
            with open(zip_path, 'wb') as f:
                f.write(zip_bytes)
            with zipfile.ZipFile(zip_path, 'r') as zf:
                zf.extractall(tmp_dir)
            # Find the main vector file
            for ext in ['.gpkg', '.shp', '.geojson']:
                matches = [os.path.join(tmp_dir, fn)
                           for fn in os.listdir(tmp_dir) if fn.lower().endswith(ext)]
                if matches:
                    st.session_state['wdpa_file'] = matches[0]
                    st.caption(f"✅ Extracted: {Path(matches[0]).name}")
                    logger.info(f"WDPA extracted from ZIP: {matches[0]}")
                    break
            else:
                st.error("No .gpkg, .shp or .geojson found inside the ZIP archive.")
                st.session_state['wdpa_file'] = None
        else:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(wdpa_uploaded_file.read())
                tmp.flush()
                st.session_state['wdpa_file'] = tmp.name
                logger.info(f"WDPA file uploaded: {tmp.name}")
    else:
        st.session_state['wdpa_file'] = None

    st.markdown("---")

    # ===================================================================
    # Criterion rasters (for Module 2)
    # ===================================================================
    st.subheader("Multi-Criteria Evaluation Layers")
    st.markdown(
        """
        Upload the six criterion rasters (GeoTIFF, EPSG:3035).
        Files up to **2 GB** are supported — including Corine Land Cover.
        """
    )

    # Initialize session state dicts
    if 'criterion_raster_paths' not in st.session_state:
        st.session_state['criterion_raster_paths'] = {}
    if 'validation_reports' not in st.session_state:
        st.session_state['validation_reports'] = {}

    # Helper: render one file uploader and update session state
    def _layer_uploader(criterion_key, label, help_text):
        uploaded = st.file_uploader(
            label,
            type=['tif', 'tiff'],
            key=f'{criterion_key}_upload',
            help=help_text,
        )
        if uploaded is not None:
            # Skip re-writing if already stored for this upload (avoid temp file leak)
            existing_path = st.session_state['criterion_raster_paths'].get(criterion_key)
            validation_key = f'_validated_{criterion_key}'
            already_validated = st.session_state.get(validation_key) == uploaded.name
            if existing_path and already_validated and Path(existing_path).exists():
                return  # Already processed this file — skip

            # Clean up previous temp file for this criterion
            if existing_path and Path(existing_path).exists():
                try:
                    Path(existing_path).unlink()
                    logger.debug(f"Cleaned up old temp file: {existing_path}")
                except OSError:
                    pass

            with tempfile.NamedTemporaryFile(delete=False, suffix='.tif') as tmp:
                tmp.write(uploaded.read())
                tmp.flush()
                st.session_state['criterion_raster_paths'][criterion_key] = tmp.name
                logger.info(f"{criterion_key} uploaded: {tmp.name}")
                _validate_layer(criterion_key, tmp.name)
        else:
            # Clean up temp file when uploader is cleared
            existing_path = st.session_state['criterion_raster_paths'].get(criterion_key)
            if existing_path and Path(existing_path).exists():
                try:
                    Path(existing_path).unlink()
                    logger.debug(f"Cleaned up temp file on clear: {existing_path}")
                except OSError:
                    pass
            st.session_state['criterion_raster_paths'].pop(criterion_key, None)
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
