"""Raster data preprocessing and harmonisation.

This module provides functions for loading, reprojecting, resampling, aligning,
and normalising raster data for the OECM Favourability Tool.
"""

import logging
import numpy as np
import rasterio
from rasterio.warp import calculate_default_transform, reproject, Resampling
from rasterio.transform import from_bounds
from rasterio.mask import mask as rasterio_mask
import yaml
from pathlib import Path
from typing import Optional
from shapely.geometry import mapping
import math

logger = logging.getLogger(__name__)


def _load_config():
    """Load configuration from settings.yaml."""
    config_path = Path(__file__).parent.parent.parent / "config" / "settings.yaml"
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def _load_transformation_config():
    """Load transformation function configuration."""
    config_path = Path(__file__).parent.parent.parent / "config" / "transformation_functions.yaml"
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def load_raster(path: str) -> tuple[np.ndarray, dict]:
    """Load a GeoTIFF raster file.

    Parameters
    ----------
    path : str
        Path to the GeoTIFF file.

    Returns
    -------
    tuple[np.ndarray, dict]
        A tuple containing:
        - array : np.ndarray
            2D numpy array of raster values (first band).
        - profile : dict
            Rasterio profile dictionary containing metadata (CRS, transform, etc.).

    Raises
    ------
    FileNotFoundError
        If the file does not exist.
    ValueError
        If the raster is empty or cannot be read.
    """
    logger.info(f"Loading raster from {path}")

    if not Path(path).exists():
        raise FileNotFoundError(f"Raster file not found: {path}")

    with rasterio.open(path) as src:
        array = src.read(1)
        profile = dict(src.profile)

    if array.size == 0:
        raise ValueError(f"Empty raster array loaded from {path}")

    logger.info(f"Loaded raster with shape {array.shape}, dtype {array.dtype}")
    return array, profile


def reproject_raster(
    array: np.ndarray,
    src_profile: dict,
    target_crs: str
) -> tuple[np.ndarray, dict]:
    """Reproject raster to target CRS using rasterio.warp.

    Parameters
    ----------
    array : np.ndarray
        Source raster array.
    src_profile : dict
        Source raster profile containing CRS and transform.
    target_crs : str
        Target coordinate reference system (e.g., 'EPSG:3035').

    Returns
    -------
    tuple[np.ndarray, dict]
        A tuple containing:
        - array : np.ndarray
            Reprojected raster array.
        - profile : dict
            Updated profile with new CRS and transform.

    Raises
    ------
    ValueError
        If target_crs is invalid or CRS information is missing.
    """
    logger.info(f"Reprojecting from {src_profile['crs']} to {target_crs}")

    if src_profile.get('crs') is None:
        raise ValueError("Source profile missing CRS information")

    if not target_crs:
        raise ValueError("Target CRS must be specified")

    # Check if already in target CRS
    if str(src_profile['crs']).upper() == target_crs.upper():
        logger.info("Raster already in target CRS, skipping reprojection")
        return array, src_profile.copy()

    # Calculate transform and dimensions for target CRS
    try:
        transform, width, height = calculate_default_transform(
            src_profile['crs'],
            target_crs,
            src_profile['width'],
            src_profile['height'],
            *rasterio.transform.array_bounds(
                src_profile['height'],
                src_profile['width'],
                src_profile['transform']
            )
        )
    except Exception as e:
        raise ValueError(f"Invalid target CRS '{target_crs}': {e}")

    # Create destination array
    dst_array = np.empty((height, width), dtype=array.dtype)

    # Reproject
    reproject(
        source=array,
        destination=dst_array,
        src_transform=src_profile['transform'],
        src_crs=src_profile['crs'],
        dst_transform=transform,
        dst_crs=target_crs,
        resampling=Resampling.bilinear
    )

    # Update profile
    dst_profile = src_profile.copy()
    dst_profile.update({
        'crs': target_crs,
        'transform': transform,
        'width': width,
        'height': height
    })

    logger.info(f"Reprojected to shape {dst_array.shape}")
    return dst_array, dst_profile


def resample_raster(
    array: np.ndarray,
    profile: dict,
    target_resolution: float,
    method: str = "bilinear"
) -> tuple[np.ndarray, dict]:
    """Resample raster to target resolution.

    Parameters
    ----------
    array : np.ndarray
        Input raster array.
    profile : dict
        Raster profile containing transform and bounds.
    target_resolution : float
        Target resolution in units of the CRS (typically meters).
    method : str, optional
        Resampling method: 'bilinear', 'nearest', or 'cubic'.
        Default is 'bilinear'.

    Returns
    -------
    tuple[np.ndarray, dict]
        A tuple containing:
        - array : np.ndarray
            Resampled raster array.
        - profile : dict
            Updated profile with new transform and dimensions.

    Raises
    ------
    ValueError
        If resampling method is invalid.
    """
    logger.info(f"Resampling to {target_resolution}m resolution using {method}")

    # Map method string to Resampling enum
    resampling_methods = {
        'bilinear': Resampling.bilinear,
        'nearest': Resampling.nearest,
        'cubic': Resampling.cubic
    }

    if method not in resampling_methods:
        raise ValueError(
            f"Invalid resampling method '{method}'. "
            f"Must be one of {list(resampling_methods.keys())}"
        )

    resampling_enum = resampling_methods[method]

    # Calculate current resolution
    transform = profile['transform']
    current_res_x = abs(transform[0])
    current_res_y = abs(transform[4])

    # Check if already at target resolution
    if np.isclose(current_res_x, target_resolution) and np.isclose(current_res_y, target_resolution):
        logger.info("Raster already at target resolution, skipping resampling")
        return array, profile.copy()

    # Calculate new dimensions
    scale_x = current_res_x / target_resolution
    scale_y = current_res_y / target_resolution

    new_width = int(np.round(profile['width'] * scale_x))
    new_height = int(np.round(profile['height'] * scale_y))

    # Get bounds
    bounds = rasterio.transform.array_bounds(
        profile['height'],
        profile['width'],
        transform
    )

    # Create new transform
    new_transform = from_bounds(
        bounds[0], bounds[1], bounds[2], bounds[3],
        new_width, new_height
    )

    # Create destination array
    dst_array = np.empty((new_height, new_width), dtype=array.dtype)

    # Resample
    reproject(
        source=array,
        destination=dst_array,
        src_transform=transform,
        src_crs=profile['crs'],
        dst_transform=new_transform,
        dst_crs=profile['crs'],
        resampling=resampling_enum
    )

    # Update profile
    dst_profile = profile.copy()
    dst_profile.update({
        'transform': new_transform,
        'width': new_width,
        'height': new_height
    })

    logger.info(f"Resampled from {array.shape} to {dst_array.shape}")
    return dst_array, dst_profile


def derive_grid_from_geometry(geom, resolution=100.0, crs="EPSG:3035") -> dict:
    """Derive a rasterio profile (transform, width, height, crs) from a shapely geometry.

    Parameters
    ----------
    geom : shapely.geometry
        Shapely geometry in the target CRS (typically NUTS2 boundary).
    resolution : float, optional
        Target grid resolution in units of the CRS (typically meters).
        Default is 100.0.
    crs : str, optional
        Target coordinate reference system. Default is 'EPSG:3035'.

    Returns
    -------
    dict
        Rasterio profile dictionary containing:
        - 'crs': Target CRS
        - 'transform': Affine transform for the grid
        - 'width': Grid width in pixels
        - 'height': Grid height in pixels
        - 'dtype': Data type (float64)
        - 'count': Number of bands (1)

    Notes
    -----
    Grid bounds are snapped to clean multiples of the resolution to ensure
    alignment with standard grid systems.
    """
    logger.info(f"Deriving grid from geometry: resolution={resolution}m, CRS={crs}")

    bounds = geom.bounds  # (minx, miny, maxx, maxy)

    # Snap bounds to clean grid multiples
    minx = math.floor(bounds[0] / resolution) * resolution
    miny = math.floor(bounds[1] / resolution) * resolution
    maxx = math.ceil(bounds[2] / resolution) * resolution
    maxy = math.ceil(bounds[3] / resolution) * resolution

    # Calculate dimensions
    width = int((maxx - minx) / resolution)
    height = int((maxy - miny) / resolution)

    # Create transform
    transform = from_bounds(minx, miny, maxx, maxy, width, height)

    profile = {
        'crs': crs,
        'transform': transform,
        'width': width,
        'height': height,
        'dtype': 'float64',
        'count': 1
    }

    logger.info(f"Derived grid: {width}x{height} pixels, bounds=({minx}, {miny}, {maxx}, {maxy})")
    return profile


def align_rasters(
    raster_dict: dict[str, tuple[np.ndarray, dict]],
    study_area_geom=None,
    resolution: float = 100.0,
    crs: str = "EPSG:3035"
) -> dict[str, tuple[np.ndarray, dict]]:
    """Align all rasters to a common grid (extent, resolution, CRS).

    When study_area_geom is provided, the reference grid is derived from the
    NUTS2 study area geometry bounds. All layers are clipped to the study area
    before alignment. This ensures all outputs are masked to the analysis extent.

    When study_area_geom is None (backward compatibility), the first layer after
    sorting by name is used as the reference grid.

    Parameters
    ----------
    raster_dict : dict[str, tuple[np.ndarray, dict]]
        Dictionary mapping layer names to (array, profile) tuples.
    study_area_geom : shapely.geometry, optional
        Study area geometry (typically NUTS2 boundary) in target CRS.
        If provided, this defines the reference grid extent. Default is None.
    resolution : float, optional
        Target resolution in units of the CRS (typically meters).
        Only used when study_area_geom is provided. Default is 100.0.
    crs : str, optional
        Target coordinate reference system. Only used when study_area_geom
        is provided. Default is 'EPSG:3035'.

    Returns
    -------
    dict[str, tuple[np.ndarray, dict]]
        Dictionary with aligned rasters, all sharing the same grid.

    Raises
    ------
    ValueError
        If raster_dict is empty or contains incompatible grids.

    Warnings
    --------
    Logs a warning if a layer covers less than 80% of the study area grid cells.

    Notes
    -----
    - When study_area_geom is provided:
      - Uses nearest-neighbor resampling for integer/categorical layers
      - Uses bilinear resampling for float layers
      - Fills NoData with np.nan for float output (not 0)
      - Clips each layer to study area before alignment
    - When study_area_geom is None:
      - Legacy behavior: uses first sorted layer as reference
      - Logs deprecation warning
    """
    logger.info(f"Aligning {len(raster_dict)} rasters to common grid")

    if not raster_dict:
        raise ValueError("Cannot align empty raster dictionary")

    # ===================================================================
    # Case 1: study_area_geom provided — derive grid from geometry
    # ===================================================================
    if study_area_geom is not None:
        logger.info("Using study area geometry to derive reference grid")

        # Derive reference grid from geometry
        ref_profile = derive_grid_from_geometry(geom=study_area_geom, resolution=resolution, crs=crs)

        aligned = {}

        for name, (src_array, src_profile) in raster_dict.items():
            logger.info(f"Clipping and aligning '{name}' to study area grid")

            # Determine resampling method based on dtype
            is_categorical = np.issubdtype(src_array.dtype, np.integer)
            resampling_method = Resampling.nearest if is_categorical else Resampling.bilinear

            logger.info(f"  dtype={src_array.dtype}, resampling={resampling_method.name}")

            # Create destination array
            # Use float64 for output to support np.nan
            dst_dtype = src_array.dtype if is_categorical else np.float64
            dst_array = np.full(
                (ref_profile['height'], ref_profile['width']),
                fill_value=np.nan if not is_categorical else 0,
                dtype=dst_dtype
            )

            # Reproject and resample to reference grid
            reproject(
                source=src_array,
                destination=dst_array,
                src_transform=src_profile['transform'],
                src_crs=src_profile['crs'],
                dst_transform=ref_profile['transform'],
                dst_crs=ref_profile['crs'],
                resampling=resampling_method,
                dst_nodata=np.nan if not is_categorical else 0
            )

            # Apply study area mask (clip to geometry)
            # Create a temporary in-memory dataset for masking
            with rasterio.io.MemoryFile() as memfile:
                with memfile.open(
                    driver='GTiff',
                    height=ref_profile['height'],
                    width=ref_profile['width'],
                    count=1,
                    dtype=dst_dtype,
                    crs=ref_profile['crs'],
                    transform=ref_profile['transform']
                ) as dataset:
                    dataset.write(dst_array, 1)

                    # Apply mask using geometry
                    try:
                        masked_array, masked_transform = rasterio_mask(
                            dataset,
                            [mapping(study_area_geom)],
                            crop=False,  # Don't crop, just mask
                            filled=True,
                            nodata=np.nan if not is_categorical else 0
                        )

                        dst_array = masked_array[0]  # Extract first band

                    except Exception as e:
                        logger.warning(f"Failed to mask '{name}' to study area: {e}. Using unmasked data.")

            # Check coverage (warn if < 80%)
            if not is_categorical:
                valid_count = np.sum(~np.isnan(dst_array))
            else:
                valid_count = np.sum(dst_array != 0)

            total_count = dst_array.size
            coverage = valid_count / total_count if total_count > 0 else 0

            if coverage < 0.80:
                logger.warning(
                    f"Layer '{name}' covers only {coverage*100:.1f}% of the study area grid. "
                    f"Expected coverage ≥80%. Check layer extent."
                )

            # Create aligned profile
            dst_profile = ref_profile.copy()
            dst_profile['dtype'] = str(dst_dtype)

            aligned[name] = (dst_array, dst_profile)
            logger.info(f"Aligned '{name}' to shape {dst_array.shape}, coverage={coverage*100:.1f}%")

        logger.info("All rasters aligned to study area grid")
        return aligned

    # ===================================================================
    # Case 2: No study_area_geom — legacy behavior (alphabetical reference)
    # ===================================================================
    else:
        logger.warning(
            "align_rasters() called without study_area_geom. "
            "Using legacy behavior (first sorted layer as reference). "
            "This is deprecated — please provide study_area_geom for correct grid alignment."
        )

        # Sort by name and use first as reference
        sorted_names = sorted(raster_dict.keys())
        reference_name = sorted_names[0]
        ref_array, ref_profile = raster_dict[reference_name]

        logger.info(f"Using '{reference_name}' as reference grid")
        logger.info(f"Reference: shape={ref_array.shape}, CRS={ref_profile['crs']}, "
                    f"transform={ref_profile['transform']}")

        aligned = {}
        aligned[reference_name] = (ref_array.copy(), ref_profile.copy())

        # Get reference bounds
        ref_bounds = rasterio.transform.array_bounds(
            ref_profile['height'],
            ref_profile['width'],
            ref_profile['transform']
        )

        # Align all other rasters to reference
        for name in sorted_names[1:]:
            src_array, src_profile = raster_dict[name]
            logger.info(f"Aligning '{name}' to reference grid")

            # Create destination array matching reference
            dst_array = np.empty(
                (ref_profile['height'], ref_profile['width']),
                dtype=src_array.dtype
            )

            # Reproject to match reference
            reproject(
                source=src_array,
                destination=dst_array,
                src_transform=src_profile['transform'],
                src_crs=src_profile['crs'],
                dst_transform=ref_profile['transform'],
                dst_crs=ref_profile['crs'],
                resampling=Resampling.bilinear
            )

            # Create aligned profile
            dst_profile = src_profile.copy()
            dst_profile.update({
                'crs': ref_profile['crs'],
                'transform': ref_profile['transform'],
                'width': ref_profile['width'],
                'height': ref_profile['height']
            })

            aligned[name] = (dst_array, dst_profile)
            logger.info(f"Aligned '{name}' to shape {dst_array.shape}")

        logger.info("All rasters aligned to common grid")
        return aligned


def apply_nodata_mask(
    array: np.ndarray,
    nodata_value: Optional[float]
) -> np.ndarray:
    """Replace nodata values with np.nan.

    Parameters
    ----------
    array : np.ndarray
        Input raster array.
    nodata_value : float or None
        Value representing missing data. If None, array is returned unchanged.

    Returns
    -------
    np.ndarray
        Array with nodata values replaced by np.nan. Returned as float dtype.

    Notes
    -----
    Handles None nodata_value gracefully by returning a copy of the array
    converted to float dtype.
    """
    # Ensure float dtype for np.nan
    array_float = array.astype(np.float64, copy=True)

    if nodata_value is None:
        logger.debug("No nodata value specified, returning array as-is")
        return array_float

    # Replace nodata with nan
    mask = array_float == nodata_value
    nodata_count = np.sum(mask)

    if nodata_count > 0:
        array_float[mask] = np.nan
        logger.info(f"Masked {nodata_count} nodata values to np.nan")

    return array_float


def normalize_linear(
    array: np.ndarray,
    vmin: float,
    vmax: float,
    invert: bool = False
) -> np.ndarray:
    """Linear normalisation to [0, 1].

    Parameters
    ----------
    array : np.ndarray
        Input array to normalize.
    vmin : float
        Minimum value for normalization range.
    vmax : float
        Maximum value for normalization range.
    invert : bool, optional
        If True, invert the normalized values (1 - normalized).
        Used for pressure layers. Default is False.

    Returns
    -------
    np.ndarray
        Normalized array with values in [0, 1]. NaN values are preserved.

    Notes
    -----
    Values below vmin are clipped to 0, values above vmax are clipped to 1.
    """
    logger.info(f"Applying linear normalization (vmin={vmin}, vmax={vmax}, invert={invert})")

    if vmax <= vmin:
        raise ValueError(f"vmax ({vmax}) must be greater than vmin ({vmin})")

    # Normalize to [0, 1]
    normalized = (array - vmin) / (vmax - vmin)

    # Clip to [0, 1]
    normalized = np.clip(normalized, 0, 1)

    # Invert if requested
    if invert:
        normalized = 1.0 - normalized

    logger.info(f"Linear normalization complete, range: [{np.nanmin(normalized):.3f}, {np.nanmax(normalized):.3f}]")
    return normalized


def normalize_sigmoid(
    array: np.ndarray,
    inflection: float,
    slope: float
) -> np.ndarray:
    """Sigmoid normalization to [0, 1].

    Parameters
    ----------
    array : np.ndarray
        Input array to normalize.
    inflection : float
        Inflection point of sigmoid curve (input value at which output = 0.5).
    slope : float
        Steepness of the sigmoid curve. Higher values create sharper transitions.

    Returns
    -------
    np.ndarray
        Normalized array with values in [0, 1]. NaN values are preserved.

    Notes
    -----
    Uses the logistic function: f(x) = 1 / (1 + exp(-slope * (x - inflection)))
    """
    logger.info(f"Applying sigmoid normalization (inflection={inflection}, slope={slope})")

    # Sigmoid transformation: 1 / (1 + exp(-slope * (x - inflection)))
    normalized = 1.0 / (1.0 + np.exp(-slope * (array - inflection)))

    logger.info(f"Sigmoid normalization complete, range: [{np.nanmin(normalized):.3f}, {np.nanmax(normalized):.3f}]")
    return normalized


def normalize_gaussian(
    array: np.ndarray,
    mean: float,
    std: float
) -> np.ndarray:
    """Gaussian normalization - non-monotone, optimum at mean.

    This function is used EXCLUSIVELY for provisioning ES capacity (Group C),
    where an optimal intermediate value is desired (e.g., moderate use is best).

    Parameters
    ----------
    array : np.ndarray
        Input array to normalize.
    mean : float
        Optimal value (peak of Gaussian curve).
    std : float
        Standard deviation controlling spread around optimum.

    Returns
    -------
    np.ndarray
        Normalized array with values in [0, 1], maximum at mean. NaN values are preserved.

    Notes
    -----
    Uses the Gaussian (normal distribution) formula:
    f(x) = exp(-((x - mean)^2) / (2 * std^2))

    WARNING: This is a non-monotone transformation. Do NOT apply to any layer
    other than provisioning ES without explicit instruction.
    """
    logger.info(f"Applying Gaussian normalization (mean={mean}, std={std})")
    logger.warning("Gaussian normalization is non-monotone - use only for provisioning ES")

    if std <= 0:
        raise ValueError(f"Standard deviation must be positive, got {std}")

    # Gaussian transformation: exp(-((x - mean)^2) / (2 * std^2))
    normalized = np.exp(-((array - mean) ** 2) / (2 * std ** 2))

    logger.info(f"Gaussian normalization complete, range: [{np.nanmin(normalized):.3f}, {np.nanmax(normalized):.3f}]")
    return normalized


def normalize_layer(
    array: np.ndarray,
    layer_name: str,
    params: dict
) -> np.ndarray:
    """Dispatcher: apply normalization based on configuration.

    Reads the transformation type from the params dictionary and applies
    the appropriate normalization function.

    Parameters
    ----------
    array : np.ndarray
        Input array to normalize.
    layer_name : str
        Name of the layer being normalized (for logging).
    params : dict
        Transformation parameters from configuration, must include 'type' key.
        Additional keys depend on the transformation type:
        - 'linear': vmin, vmax, invert (optional)
        - 'inverted_linear': vmin, vmax
        - 'sigmoid': inflection, slope
        - 'gaussian': mean, std

    Returns
    -------
    np.ndarray
        Normalized array with values in [0, 1].

    Raises
    ------
    ValueError
        If transformation type is unknown or required parameters are missing.

    Notes
    -----
    For 'inverted_linear' type, vmin and vmax are derived from data range
    at runtime if not provided in params.
    """
    logger.info(f"Normalizing layer '{layer_name}'")

    if 'type' not in params:
        raise ValueError(f"Transformation parameters for '{layer_name}' missing 'type' key")

    transform_type = params['type']

    if transform_type == 'linear':
        if 'vmin' not in params or 'vmax' not in params:
            raise ValueError(f"Linear transformation requires 'vmin' and 'vmax' parameters")
        return normalize_linear(
            array,
            vmin=params['vmin'],
            vmax=params['vmax'],
            invert=params.get('invert', False)
        )

    elif transform_type == 'inverted_linear':
        # For inverted linear, derive vmin/vmax from data if not provided
        vmin = params.get('vmin', np.nanmin(array))
        vmax = params.get('vmax', np.nanmax(array))
        logger.info(f"Inverted linear: using vmin={vmin}, vmax={vmax}")
        return normalize_linear(array, vmin=vmin, vmax=vmax, invert=True)

    elif transform_type == 'sigmoid':
        if 'inflection' not in params or 'slope' not in params:
            raise ValueError(f"Sigmoid transformation requires 'inflection' and 'slope' parameters")
        return normalize_sigmoid(
            array,
            inflection=params['inflection'],
            slope=params['slope']
        )

    elif transform_type == 'gaussian':
        if 'mean' not in params or 'std' not in params:
            raise ValueError(f"Gaussian transformation requires 'mean' and 'std' parameters")
        return normalize_gaussian(
            array,
            mean=params['mean'],
            std=params['std']
        )

    else:
        raise ValueError(
            f"Unknown transformation type '{transform_type}' for layer '{layer_name}'. "
            f"Must be one of: linear, inverted_linear, sigmoid, gaussian"
        )


# Legacy function stub for backward compatibility
def harmonise_raster(input_raster, target_crs, target_resolution, resampling_method="bilinear"):
    """
    Reproject and resample input raster to common grid.

    Args:
        input_raster: Path to input raster or xarray DataArray
        target_crs: Target CRS (e.g., 'EPSG:3035')
        target_resolution: Target resolution in meters
        resampling_method: Resampling algorithm ('bilinear', 'nearest', 'cubic')

    Returns:
        xarray DataArray in target CRS and resolution
    """
    raise NotImplementedError("Use load_raster, reproject_raster, and resample_raster instead")


# Legacy function stub for backward compatibility
def apply_transformation_function(raster_array, transform_config):
    """
    Apply transformation function to normalise criterion values to [0,1].

    Args:
        raster_array: Input xarray DataArray
        transform_config: Parameters from transformation_functions.yaml

    Returns:
        Transformed xarray DataArray with values in [0,1]
    """
    raise NotImplementedError("Use normalize_layer instead")
