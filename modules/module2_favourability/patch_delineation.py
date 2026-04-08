"""Patch delineation, MMU filtering and candidate OECM site ranking.

Pipeline
--------
1. Threshold the MCE score array → binary raster
2. Connected-component labelling (8-connectivity)
3. Remove patches below the Minimum Mapping Unit (MMU)
4. Vectorise surviving patches → GeoDataFrame in EPSG:3035
5. Compute per-patch attributes:
     area_ha, mean_score, max_score, compactness, dist_to_pa_km,
     gap_overlap_pct, rank_score
6. Rank by rank_score (descending)

Compactness = 4π·area / perimeter²  (Polsby-Popper index, 1 = circle)
Proximity to PA = distance of patch centroid to nearest WDPA geometry (km)
Gap overlap = % of patch area intersecting strict gap layer
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import geopandas as gpd
import pandas as pd
from rasterio.features import shapes as _rasterio_shapes
from rasterio.transform import from_bounds as _from_bounds
from shapely.geometry import shape as _shape, MultiPolygon, Polygon
from shapely.ops import unary_union
from scipy.ndimage import label as _ndlabel

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _polsby_popper(geom) -> float:
    """Polsby-Popper compactness index [0, 1]. 1 = perfect circle."""
    import math
    if geom is None or geom.is_empty:
        return 0.0
    area = geom.area
    perim = geom.length
    if perim == 0:
        return 0.0
    return float(4 * math.pi * area / (perim ** 2))


def _dist_to_pa_km(centroid, pa_union_geom) -> float:
    """Distance in km from centroid to nearest PA boundary (EPSG:3035 metres)."""
    if pa_union_geom is None or pa_union_geom.is_empty:
        return np.nan
    return float(centroid.distance(pa_union_geom)) / 1000.0


def _gap_overlap_pct(patch_geom, gap_geom) -> float:
    """% of patch area that overlaps the strict-gap layer."""
    if gap_geom is None or gap_geom.is_empty:
        return 0.0
    try:
        inter = patch_geom.intersection(gap_geom)
        if inter.is_empty:
            return 0.0
        return float(inter.area / patch_geom.area * 100.0)
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def delineate_patches(
    score_array: np.ndarray,
    profile: dict,
    threshold: float,
    mmu_ha: float = 100.0,
    pa_gdf: Optional[gpd.GeoDataFrame] = None,
    strict_gaps_gdf: Optional[gpd.GeoDataFrame] = None,
) -> gpd.GeoDataFrame:
    """
    Delineate candidate OECM sites from the MCE score raster.

    Parameters
    ----------
    score_array : np.ndarray
        MCE favourability score (NaN = eliminated).
    profile : dict
        Rasterio profile (transform, crs, width, height).
    threshold : float
        Minimum score for a pixel to be included in a candidate patch.
    mmu_ha : float
        Minimum Mapping Unit in hectares. Patches smaller than this are
        discarded.
    pa_gdf : GeoDataFrame, optional
        WDPA protected area polygons (EPSG:3035). Used to compute
        distance-to-PA attribute.
    strict_gaps_gdf : GeoDataFrame, optional
        Strict gap layer from Module 1 gap analysis (EPSG:3035). Used to
        compute gap overlap attribute.

    Returns
    -------
    GeoDataFrame
        One row per candidate site, columns:
        patch_id, area_ha, mean_score, max_score, compactness,
        dist_to_pa_km, gap_overlap_pct, rank_score, geometry (EPSG:3035)
        Sorted by rank_score descending.
    """
    transform = profile['transform']
    crs       = profile['crs']
    pixel_area_ha = abs(transform[0] * transform[4]) / 10000.0

    # ------------------------------------------------------------------
    # 1. Binary mask at threshold
    # ------------------------------------------------------------------
    valid     = ~np.isnan(score_array)
    binary    = (valid & (score_array >= threshold)).astype(np.uint8)

    if binary.sum() == 0:
        logger.warning("No pixels above threshold — empty patch GeoDataFrame.")
        return gpd.GeoDataFrame(
            columns=['patch_id', 'area_ha', 'mean_score', 'max_score',
                     'compactness', 'dist_to_pa_km', 'gap_overlap_pct',
                     'rank_score', 'geometry'],
            geometry='geometry',
            crs=crs,
        )

    # ------------------------------------------------------------------
    # 2. Connected components (8-connectivity)
    # ------------------------------------------------------------------
    struct   = np.ones((3, 3), dtype=int)   # 8-connectivity
    labelled, n_patches = _ndlabel(binary, structure=struct)
    logger.info(f"Found {n_patches} raw patches before MMU filter")

    # ------------------------------------------------------------------
    # 3. MMU filter — remove patches below mmu_ha
    # ------------------------------------------------------------------
    mmu_pixels = mmu_ha / pixel_area_ha
    patch_sizes = np.bincount(labelled.ravel())  # index 0 = background

    keep_ids = np.where(patch_sizes >= mmu_pixels)[0]
    keep_ids = keep_ids[keep_ids > 0]            # exclude background (0)

    if len(keep_ids) == 0:
        logger.warning(
            f"All {n_patches} patches smaller than MMU ({mmu_ha:.0f} ha). "
            "Lower the MMU or threshold."
        )
        return gpd.GeoDataFrame(
            columns=['patch_id', 'area_ha', 'mean_score', 'max_score',
                     'compactness', 'dist_to_pa_km', 'gap_overlap_pct',
                     'rank_score', 'geometry'],
            geometry='geometry',
            crs=crs,
        )

    # Zero-out small patches for vectorisation
    keep_mask = np.isin(labelled, keep_ids)
    filtered_binary = np.where(keep_mask, binary, 0).astype(np.uint8)
    filtered_labels = np.where(keep_mask, labelled, 0).astype(np.int32)

    logger.info(
        f"{len(keep_ids)} patches survive MMU filter "
        f"({n_patches - len(keep_ids)} removed)"
    )

    # ------------------------------------------------------------------
    # 4. Pre-compute spatial context (once, outside patch loop)
    # ------------------------------------------------------------------
    pa_union = None
    if pa_gdf is not None and len(pa_gdf) > 0:
        try:
            pa_union = pa_gdf.geometry.union_all()
        except Exception as e:
            logger.warning(f"Could not compute PA union for proximity: {e}")

    gap_union = None
    if strict_gaps_gdf is not None and len(strict_gaps_gdf) > 0:
        try:
            gap_union = strict_gaps_gdf.geometry.union_all()
        except Exception as e:
            logger.warning(f"Could not compute gap union: {e}")

    # ------------------------------------------------------------------
    # 5. Vectorise patches and compute attributes
    # ------------------------------------------------------------------
    records = []

    for pid in keep_ids:
        patch_binary = (filtered_labels == pid).astype(np.uint8)

        # --- Vectorise via rasterio.features.shapes ---
        geoms = [
            _shape(geom_dict)
            for geom_dict, val in _rasterio_shapes(
                patch_binary, mask=patch_binary, transform=transform
            )
            if val == 1
        ]
        if not geoms:
            continue
        patch_geom = unary_union(geoms)
        if patch_geom.is_empty:
            continue

        # --- Score statistics ---
        pixel_scores = score_array[filtered_labels == pid]
        pixel_scores = pixel_scores[~np.isnan(pixel_scores)]
        if len(pixel_scores) == 0:
            continue

        area_ha   = len(pixel_scores) * pixel_area_ha
        mean_sc   = float(np.mean(pixel_scores))
        max_sc    = float(np.max(pixel_scores))

        # --- Spatial attributes ---
        compact   = _polsby_popper(patch_geom)
        dist_pa   = _dist_to_pa_km(patch_geom.centroid, pa_union)
        gap_pct   = _gap_overlap_pct(patch_geom, gap_union)

        records.append({
            'patch_id':        int(pid),
            'area_ha':         round(area_ha, 1),
            'mean_score':      round(mean_sc, 4),
            'max_score':       round(max_sc, 4),
            'compactness':     round(compact, 3),
            'dist_to_pa_km':   round(dist_pa, 2) if not np.isnan(dist_pa) else None,
            'gap_overlap_pct': round(gap_pct, 1),
            'geometry':        patch_geom,
        })

    if not records:
        return gpd.GeoDataFrame(
            columns=['patch_id', 'area_ha', 'mean_score', 'max_score',
                     'compactness', 'dist_to_pa_km', 'gap_overlap_pct',
                     'rank_score', 'geometry'],
            geometry='geometry',
            crs=crs,
        )

    gdf = gpd.GeoDataFrame(records, geometry='geometry', crs=crs)

    # ------------------------------------------------------------------
    # 6. Rank score
    #
    # Composite of:
    #   - 50 % mean favourability score
    #   - 20 % gap overlap (high gap overlap = high OECM complementarity)
    #   - 20 % area (log-scaled, normalised)
    #   - 10 % PA proximity (closer = better — distance inverted)
    # ------------------------------------------------------------------
    def _norm01(series: pd.Series) -> pd.Series:
        mn, mx = series.min(), series.max()
        if mx == mn:
            return pd.Series(np.ones(len(series)), index=series.index)
        return (series - mn) / (mx - mn)

    score_norm    = _norm01(gdf['mean_score'])
    gap_norm      = _norm01(gdf['gap_overlap_pct'])
    area_norm     = _norm01(np.log1p(gdf['area_ha']))

    # Proximity: closer is better → invert distance
    if gdf['dist_to_pa_km'].notna().any():
        prox_norm = _norm01(-gdf['dist_to_pa_km'].fillna(gdf['dist_to_pa_km'].max()))
    else:
        prox_norm = pd.Series(np.zeros(len(gdf)), index=gdf.index)

    gdf['rank_score'] = (
        0.50 * score_norm +
        0.20 * gap_norm   +
        0.20 * area_norm  +
        0.10 * prox_norm
    ).round(4)

    gdf = gdf.sort_values('rank_score', ascending=False).reset_index(drop=True)
    gdf['patch_id'] = gdf.index + 1   # renumber 1-based after sort

    logger.info(
        f"Delineated {len(gdf)} candidate OECM sites. "
        f"Top site: {gdf.iloc[0]['area_ha']:.0f} ha, "
        f"score={gdf.iloc[0]['mean_score']:.3f}"
    )
    return gdf
