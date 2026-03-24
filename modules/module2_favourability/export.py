"""Export functionality for favourability results."""


def export_favourability_raster(favourability_array, output_path, crs="EPSG:3035"):
    """
    Export favourability index as GeoTIFF.

    Args:
        favourability_array: xarray DataArray with favourability scores
        output_path: Path for output GeoTIFF
        crs: Coordinate reference system
    """
    raise NotImplementedError("Raster export not yet implemented")


def export_high_favourability_polygons(favourability_array, threshold, output_path):
    """
    Vectorise high-favourability areas and export as shapefile/GeoPackage.

    Args:
        favourability_array: xarray DataArray with favourability scores
        threshold: Minimum favourability score for inclusion
        output_path: Path for output vector file
    """
    raise NotImplementedError("Polygon export not yet implemented")


def generate_favourability_report(favourability_array, criteria_dict, weights_config, output_path):
    """
    Generate comprehensive PDF report with maps and statistics.

    Args:
        favourability_array: Final favourability index
        criteria_dict: Input criterion layers
        weights_config: MCE weights used
        output_path: Path for output PDF
    """
    raise NotImplementedError("Report generation not yet implemented")
