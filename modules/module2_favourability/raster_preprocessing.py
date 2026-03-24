"""Raster data preprocessing and harmonisation."""


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
    raise NotImplementedError("Raster harmonisation not yet implemented")


def apply_transformation_function(raster_array, transform_config):
    """
    Apply transformation function to normalise criterion values to [0,1].

    Args:
        raster_array: Input xarray DataArray
        transform_config: Parameters from transformation_functions.yaml

    Returns:
        Transformed xarray DataArray with values in [0,1]
    """
    raise NotImplementedError("Transformation function application not yet implemented")
