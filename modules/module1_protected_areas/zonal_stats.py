"""Zonal statistics of MCE criterion rasters within protected areas."""

import logging
from typing import Dict, Optional
import numpy as np
import pandas as pd
import geopandas as gpd
import rasterio
from rasterio.mask import mask
from rasterio.warp import reproject, Resampling, calculate_default_transform
from shapely.geometry import mapping
from shapely.ops import unary_union

logger = logging.getLogger(__name__)


def zonal_stats_by_pa_class(
    pa_gdf: gpd.GeoDataFrame,
    raster_paths: Dict[str, str],
    nodata: Optional[float] = None
) -> pd.DataFrame:
    """
    Compute zonal statistics of MCE criterion rasters within protected areas.

    For each (criterion × PA class) combination, masks the raster to the PA
    class polygons and computes summary statistics: mean, median, std, min, max,
    and pixel count. Also computes statistics for areas outside all PAs.

    Parameters
    ----------
    pa_gdf : gpd.GeoDataFrame
        Protected areas GeoDataFrame with 'protection_class' column (output of
        classify_iucn() in wdpa_loader.py). Must be in EPSG:3035.
    raster_paths : dict
        Dictionary mapping criterion name (str) to GeoTIFF file path.
        Example: {"ecosystem_condition": "path/to/condition.tif"}
    nodata : float or None, optional
        Custom nodata value to use for all rasters. If None, uses the nodata
        value specified in each raster's metadata.

    Returns
    -------
    pd.DataFrame
        Tidy DataFrame with columns:
        - criterion : criterion name
        - pa_class : protection class (or 'outside' for unprotected areas)
        - mean : mean pixel value
        - median : median pixel value
        - std : standard deviation
        - min : minimum pixel value
        - max : maximum pixel value
        - pixel_count : number of valid pixels

    Raises
    ------
    ValueError
        If pa_gdf CRS is not EPSG:3035.

    Notes
    -----
    - If a raster CRS differs from EPSG:3035, it is reprojected on-the-fly
      (with a warning logged).
    - Nodata pixels are excluded from all statistics.
    - The 'outside' class represents areas not covered by any PA.

    Examples
    --------
    >>> raster_paths = {
    ...     "ecosystem_condition": "data/rasters/condition.tif",
    ...     "connectivity": "data/rasters/connectivity.tif"
    ... }
    >>> stats_df = zonal_stats_by_pa_class(pa_gdf, raster_paths)
    >>> print(stats_df.head())
         criterion     pa_class   mean  median   std   min   max  pixel_count
    0   ecosystem_condition  strict_core  0.75    0.80  0.12  0.20  1.00      1500
    1   ecosystem_condition   regulatory  0.65    0.68  0.15  0.10  0.95      2000
    """
    # Verify CRS
    if pa_gdf.crs != 'EPSG:3035':
        raise ValueError(
            f"PA GeoDataFrame must be in EPSG:3035 for zonal statistics. "
            f"Current CRS: {pa_gdf.crs}"
        )

    # Verify protection_class column
    if 'protection_class' not in pa_gdf.columns:
        raise ValueError("PA GeoDataFrame must have 'protection_class' column")

    if len(pa_gdf) == 0:
        logger.warning("PA GeoDataFrame is empty, returning empty statistics")
        return pd.DataFrame(columns=[
            'criterion', 'pa_class', 'mean', 'median', 'std', 'min', 'max', 'pixel_count'
        ])

    results = []

    # Process each criterion raster
    for criterion_name, raster_path in raster_paths.items():
        logger.info(f"Processing criterion: {criterion_name} ({raster_path})")

        try:
            with rasterio.open(raster_path) as src:
                # Check CRS and reproject if needed
                raster_crs = src.crs
                if raster_crs is None:
                    logger.warning(
                        f"Raster {raster_path} has no CRS defined. "
                        f"Assuming EPSG:3035."
                    )
                    raster_crs = 'EPSG:3035'

                # Determine nodata value
                nodata_value = nodata if nodata is not None else src.nodata

                # Get PA classes
                pa_classes = pa_gdf['protection_class'].unique()

                # Process each PA class
                for pa_class in pa_classes:
                    class_gdf = pa_gdf[pa_gdf['protection_class'] == pa_class].copy()

                    # Reproject PA geometries if raster CRS differs
                    if str(raster_crs).upper() != 'EPSG:3035':
                        logger.warning(
                            f"Raster CRS ({raster_crs}) differs from EPSG:3035. "
                            f"Reprojecting PA geometries for masking."
                        )
                        class_gdf = class_gdf.to_crs(raster_crs)

                    # Union all geometries for this class to avoid overlap
                    union_geom = unary_union(class_gdf.geometry)

                    # Mask raster to this PA class
                    try:
                        masked_array, _ = mask(
                            src,
                            [mapping(union_geom)],
                            crop=True,
                            nodata=nodata_value,
                            filled=True
                        )

                        # Extract valid pixels (first band)
                        pixels = masked_array[0]
                        if nodata_value is not None:
                            valid_pixels = pixels[pixels != nodata_value]
                        else:
                            # If no nodata, consider all pixels
                            valid_pixels = pixels[~np.isnan(pixels)]

                        # Compute statistics
                        if len(valid_pixels) > 0:
                            stats = {
                                'criterion': criterion_name,
                                'pa_class': pa_class,
                                'mean': float(np.mean(valid_pixels)),
                                'median': float(np.median(valid_pixels)),
                                'std': float(np.std(valid_pixels)),
                                'min': float(np.min(valid_pixels)),
                                'max': float(np.max(valid_pixels)),
                                'pixel_count': int(len(valid_pixels))
                            }
                            results.append(stats)
                        else:
                            logger.warning(
                                f"No valid pixels for {criterion_name} in class {pa_class}"
                            )

                    except ValueError as e:
                        logger.warning(
                            f"Failed to mask {criterion_name} for class {pa_class}: {e}"
                        )
                        continue

                # Compute statistics for areas OUTSIDE all PAs
                logger.info(f"Computing statistics for areas outside PAs ({criterion_name})")

                # Union all PA geometries
                all_pa_union = unary_union(pa_gdf.geometry)

                # Reproject if needed
                if str(raster_crs).upper() != 'EPSG:3035':
                    pa_gdf_reproj = pa_gdf.to_crs(raster_crs)
                    all_pa_union = unary_union(pa_gdf_reproj.geometry)

                # Read entire raster
                raster_data = src.read(1)

                # Create mask from PA union
                from rasterio.features import geometry_mask
                pa_mask = geometry_mask(
                    [mapping(all_pa_union)],
                    transform=src.transform,
                    invert=False,  # False = mask out PA areas
                    out_shape=raster_data.shape
                )

                # Extract pixels OUTSIDE PAs
                outside_pixels = raster_data[pa_mask]

                # Filter out nodata
                if nodata_value is not None:
                    outside_pixels = outside_pixels[outside_pixels != nodata_value]
                else:
                    outside_pixels = outside_pixels[~np.isnan(outside_pixels)]

                # Compute statistics for outside areas
                if len(outside_pixels) > 0:
                    stats = {
                        'criterion': criterion_name,
                        'pa_class': 'outside',
                        'mean': float(np.mean(outside_pixels)),
                        'median': float(np.median(outside_pixels)),
                        'std': float(np.std(outside_pixels)),
                        'min': float(np.min(outside_pixels)),
                        'max': float(np.max(outside_pixels)),
                        'pixel_count': int(len(outside_pixels))
                    }
                    results.append(stats)
                else:
                    logger.warning(
                        f"No valid pixels outside PAs for {criterion_name}"
                    )

        except Exception as e:
            logger.error(f"Failed to process raster {raster_path}: {e}")
            continue

    # Convert to DataFrame
    if len(results) == 0:
        logger.warning("No zonal statistics computed")
        return pd.DataFrame(columns=[
            'criterion', 'pa_class', 'mean', 'median', 'std', 'min', 'max', 'pixel_count'
        ])

    df = pd.DataFrame(results)

    logger.info(
        f"Zonal statistics computed for {len(df)} (criterion × PA class) combinations"
    )

    return df


def criterion_coverage_summary(
    zonal_df: pd.DataFrame
) -> pd.DataFrame:
    """
    Create pivot table of mean criterion values per PA class.

    Transforms the tidy output of zonal_stats_by_pa_class() into a wide-format
    table for easy comparison across criteria and PA classes.

    Parameters
    ----------
    zonal_df : pd.DataFrame
        Output from zonal_stats_by_pa_class() with columns:
        criterion, pa_class, mean, median, std, min, max, pixel_count

    Returns
    -------
    pd.DataFrame
        Pivot table with:
        - Index: pa_class
        - Columns: criterion names
        - Values: mean criterion values

    Examples
    --------
    >>> summary = criterion_coverage_summary(zonal_df)
    >>> print(summary)
                      ecosystem_condition  connectivity  species_richness
    pa_class
    strict_core                    0.75          0.82              0.68
    regulatory                     0.65          0.74              0.55
    contractual                    0.58          0.68              0.50
    outside                        0.45          0.52              0.38
    """
    if len(zonal_df) == 0:
        logger.warning("Input DataFrame is empty, returning empty summary")
        return pd.DataFrame()

    # Verify required columns
    required_cols = ['criterion', 'pa_class', 'mean']
    missing_cols = [col for col in required_cols if col not in zonal_df.columns]
    if missing_cols:
        raise ValueError(
            f"Input DataFrame missing required columns: {missing_cols}"
        )

    # Create pivot table
    pivot = zonal_df.pivot(
        index='pa_class',
        columns='criterion',
        values='mean'
    )

    # Sort index: put 'outside' last if present
    if 'outside' in pivot.index:
        other_classes = sorted([idx for idx in pivot.index if idx != 'outside'])
        pivot = pivot.reindex(other_classes + ['outside'])

    logger.info(
        f"Coverage summary created: {len(pivot)} PA classes × "
        f"{len(pivot.columns)} criteria"
    )

    return pivot
