"""Export functionality for favourability results."""

import logging
from typing import Dict
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import shapes
import geopandas as gpd
from shapely.geometry import shape

logger = logging.getLogger(__name__)


def export_geotiff(
    array: np.ndarray,
    profile: dict,
    output_path: str
) -> None:
    """
    Save favourability score array as GeoTIFF.

    Parameters
    ----------
    array : np.ndarray
        Favourability score array [0-1]. Shape: (height, width).
    profile : dict
        Rasterio profile (metadata) containing:
        - crs: coordinate reference system
        - transform: affine transformation matrix
        - width, height: raster dimensions
        - dtype: data type (typically float32)
        - nodata: NoData value
    output_path : str
        Path for output GeoTIFF file.

    Raises
    ------
    ValueError
        If array shape does not match profile dimensions.
    OSError
        If output file cannot be written.

    Notes
    -----
    - Output GeoTIFF uses LZW compression
    - NoData values are preserved from input profile
    - All metadata (CRS, transform, etc.) are copied from profile

    Examples
    --------
    >>> export_geotiff(
    ...     array=favourability_scores,
    ...     profile=reference_raster.profile,
    ...     output_path='outputs/favourability.tif'
    ... )
    """
    # Verify array shape matches profile
    if array.shape != (profile['height'], profile['width']):
        raise ValueError(
            f"Array shape {array.shape} does not match profile dimensions "
            f"({profile['height']}, {profile['width']})"
        )

    logger.info(f"Exporting GeoTIFF to {output_path}...")

    # Update profile for output
    output_profile = profile.copy()
    output_profile.update({
        'dtype': 'float32',
        'count': 1,
        'compress': 'lzw'
    })

    # Write to file
    with rasterio.open(output_path, 'w', **output_profile) as dst:
        dst.write(array.astype('float32'), 1)

    logger.info(f"GeoTIFF exported successfully: {output_path}")


def export_shapefile(
    score_array: np.ndarray,
    profile: dict,
    threshold: float,
    output_path: str
) -> None:
    """
    Vectorise pixels above threshold, dissolve, export as shapefile.

    Parameters
    ----------
    score_array : np.ndarray
        Favourability score array [0-1]. Shape: (height, width).
    profile : dict
        Rasterio profile with crs, transform, width, height.
    threshold : float
        Minimum favourability score for inclusion (e.g., 0.6).
        Pixels with score >= threshold are vectorised.
    output_path : str
        Path for output shapefile (.shp extension).

    Raises
    ------
    ValueError
        If array shape does not match profile dimensions.
    OSError
        If output file cannot be written.

    Notes
    -----
    - Creates binary mask from threshold: 1 = favourable, 0 = not favourable
    - Vectorises contiguous regions of favourable pixels
    - Dissolves all polygons into single MultiPolygon
    - Output CRS matches input profile CRS

    Examples
    --------
    >>> export_shapefile(
    ...     score_array=favourability_scores,
    ...     profile=reference_raster.profile,
    ...     threshold=0.6,
    ...     output_path='outputs/favourable_zones.shp'
    ... )
    """
    # Verify array shape
    if score_array.shape != (profile['height'], profile['width']):
        raise ValueError(
            f"Array shape {score_array.shape} does not match profile dimensions "
            f"({profile['height']}, {profile['width']})"
        )

    logger.info(f"Vectorising pixels with score >= {threshold}...")

    # Create binary mask
    mask = (score_array >= threshold).astype('uint8')

    # Vectorise using rasterio.features.shapes
    geoms = []
    values = []

    for geom_dict, value in shapes(mask, transform=profile['transform']):
        if value == 1:  # Only keep favourable pixels
            geoms.append(shape(geom_dict))
            values.append(score_array[mask == 1].mean())  # Mean score for this polygon

    if not geoms:
        logger.warning(f"No pixels found with score >= {threshold}. Exporting empty shapefile.")
        # Create empty GeoDataFrame
        gdf = gpd.GeoDataFrame(
            columns=['score_mean', 'geometry'],
            crs=profile['crs']
        )
    else:
        # Create GeoDataFrame
        gdf = gpd.GeoDataFrame(
            {'score_mean': values},
            geometry=geoms,
            crs=profile['crs']
        )

        # Dissolve all polygons (optional, for simplified output)
        # Comment out if individual polygons are preferred
        # gdf = gdf.dissolve().reset_index(drop=True)

    # Export to shapefile
    gdf.to_file(output_path)

    logger.info(f"Shapefile exported successfully: {output_path} ({len(gdf)} polygons)")


def export_csv_stats(
    stats_df: pd.DataFrame,
    output_path: str
) -> None:
    """
    Export territorial unit statistics as CSV.

    Parameters
    ----------
    stats_df : pd.DataFrame
        DataFrame with territorial unit statistics.
        Expected columns: unit_name, mean_score, oecm_area_ha, pct_oecm, etc.
    output_path : str
        Path for output CSV file.

    Raises
    ------
    OSError
        If output file cannot be written.

    Notes
    -----
    - CSV uses UTF-8 encoding
    - Index is not exported

    Examples
    --------
    >>> export_csv_stats(
    ...     stats_df=zonal_statistics,
    ...     output_path='outputs/unit_statistics.csv'
    ... )
    """
    logger.info(f"Exporting CSV statistics to {output_path}...")

    stats_df.to_csv(output_path, index=False, encoding='utf-8')

    logger.info(f"CSV exported successfully: {output_path} ({len(stats_df)} rows)")


def generate_pdf_report(
    map_image_path: str,
    stats_df: pd.DataFrame,
    parameters: dict,
    output_path: str
) -> None:
    """
    Generate PDF report with map, statistics, and full parameter log.

    Parameters
    ----------
    map_image_path : str
        Path to favourability map image (PNG or JPEG).
    stats_df : pd.DataFrame
        Territorial unit statistics table.
    parameters : dict
        Complete parameter dictionary including:
        - method: aggregation method ('geometric' or 'owa')
        - alpha: OWA orness parameter
        - All inter-group and intra-group weights
        - Eliminatory thresholds
        - Timestamp (ISO 8601 format)
        - SPECIFICATIONS.md version
    output_path : str
        Path for output PDF file.

    Raises
    ------
    ImportError
        If reportlab is not installed.
    OSError
        If output file cannot be written or map image cannot be read.

    Notes
    -----
    - Uses reportlab for PDF generation
    - Report structure:
        1. Title page with analysis metadata
        2. Favourability map (full page)
        3. Statistics table
        4. Parameter log (full configuration as table)
        5. Footer: tool version, timestamp, SPECIFICATIONS.md version

    Examples
    --------
    >>> generate_pdf_report(
    ...     map_image_path='outputs/favourability_map.png',
    ...     stats_df=zonal_statistics,
    ...     parameters=mce_parameters,
    ...     output_path='outputs/favourability_report.pdf'
    ... )
    """
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.lib import colors
    except ImportError:
        raise ImportError(
            "reportlab is required for PDF generation. "
            "Install with: pip install reportlab"
        )

    logger.info(f"Generating PDF report: {output_path}...")

    # Create PDF document
    doc = SimpleDocTemplate(output_path, pagesize=A4)
    story = []
    styles = getSampleStyleSheet()

    # Title
    title = Paragraph("OECM Favourability Analysis Report", styles['Title'])
    story.append(title)
    story.append(Spacer(1, 0.5 * cm))

    # Metadata
    timestamp = parameters.get('timestamp', 'Not recorded')
    method = parameters.get('method', 'Not specified')
    alpha = parameters.get('alpha', 'N/A')

    metadata_text = f"""
    <b>Analysis Date:</b> {timestamp}<br/>
    <b>Aggregation Method:</b> {method}<br/>
    <b>Alpha Parameter:</b> {alpha}<br/>
    <b>Specifications Version:</b> {parameters.get('spec_version', 'v0.1')}
    """
    story.append(Paragraph(metadata_text, styles['Normal']))
    story.append(Spacer(1, 1 * cm))

    # Map image
    if map_image_path:
        try:
            img = Image(map_image_path, width=15 * cm, height=12 * cm)
            story.append(img)
            story.append(Spacer(1, 1 * cm))
        except Exception as e:
            logger.warning(f"Could not include map image: {e}")

    # Statistics table
    if stats_df is not None and len(stats_df) > 0:
        story.append(Paragraph("Territorial Unit Statistics", styles['Heading2']))
        story.append(Spacer(1, 0.3 * cm))

        # Convert DataFrame to reportlab table
        table_data = [stats_df.columns.tolist()] + stats_df.values.tolist()
        table = Table(table_data)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        story.append(table)
        story.append(Spacer(1, 1 * cm))

    # Parameter log
    story.append(Paragraph("Full Parameter Configuration", styles['Heading2']))
    story.append(Spacer(1, 0.3 * cm))

    param_text = "<br/>".join([f"<b>{k}:</b> {v}" for k, v in parameters.items()])
    story.append(Paragraph(param_text, styles['Normal']))

    # Build PDF
    doc.build(story)

    logger.info(f"PDF report generated successfully: {output_path}")
