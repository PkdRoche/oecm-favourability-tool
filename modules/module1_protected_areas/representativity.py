"""Ecosystem representativity assessment (KMGBF Target 3)."""

import logging
from typing import Dict
import geopandas as gpd
import pandas as pd
from shapely.ops import unary_union

logger = logging.getLogger(__name__)


def cross_with_ecosystem_types(
    pa_gdf: gpd.GeoDataFrame,
    ecosystem_layer: gpd.GeoDataFrame,
    type_column: str = "ecosystem_type"
) -> pd.DataFrame:
    """
    Spatial intersection of PA polygons with ecosystem type polygons.

    Computes the area of each ecosystem type covered by each protection class.

    Parameters
    ----------
    pa_gdf : gpd.GeoDataFrame
        Protected areas GeoDataFrame with 'protection_class' column.
        Must be in EPSG:3035.
    ecosystem_layer : gpd.GeoDataFrame
        Ecosystem types GeoDataFrame with ecosystem type classification column.
        Must be in EPSG:3035.
    type_column : str, default='ecosystem_type'
        Column name in ecosystem_layer containing ecosystem type labels.

    Returns
    -------
    pd.DataFrame
        DataFrame with columns:
        - ecosystem_type : ecosystem type label
        - pa_class : protection class
        - area_ha : area of intersection in hectares

    Raises
    ------
    ValueError
        If input GeoDataFrames are not in EPSG:3035 or missing required columns.

    Notes
    -----
    - Both input GeoDataFrames must be in EPSG:3035 before calling.
    - Performs spatial overlay (intersection) between PA and ecosystem layers.
    - Areas are computed in square meters and converted to hectares.

    Examples
    --------
    >>> coverage_df = cross_with_ecosystem_types(
    ...     pa_gdf=protected_areas,
    ...     ecosystem_layer=ecosystems,
    ...     type_column='eunis_class'
    ... )
    >>> coverage_df.head()
      ecosystem_type    pa_class  area_ha
    0        forests strict_core   1250.5
    1        forests  regulatory    850.3
    2       wetlands strict_core    320.1
    """
    # Verify CRS
    if pa_gdf.crs != 'EPSG:3035':
        raise ValueError(f"PA GeoDataFrame must be in EPSG:3035. Current: {pa_gdf.crs}")

    if ecosystem_layer.crs != 'EPSG:3035':
        raise ValueError(f"Ecosystem layer must be in EPSG:3035. Current: {ecosystem_layer.crs}")

    # Verify required columns
    if 'protection_class' not in pa_gdf.columns:
        raise ValueError("PA GeoDataFrame must have 'protection_class' column")

    if type_column not in ecosystem_layer.columns:
        raise ValueError(f"Ecosystem layer must have '{type_column}' column")

    logger.info("Computing spatial intersection between PAs and ecosystem types...")

    # Perform spatial overlay
    overlay = gpd.overlay(
        pa_gdf[['protection_class', 'geometry']],
        ecosystem_layer[[type_column, 'geometry']],
        how='intersection'
    )

    if len(overlay) == 0:
        logger.warning("No spatial overlap found between PAs and ecosystem layer")
        return pd.DataFrame(columns=['ecosystem_type', 'pa_class', 'area_ha'])

    # Compute area for each intersection
    overlay['area_ha'] = overlay.geometry.area / 10000.0

    # Group by ecosystem type and protection class
    result = overlay.groupby([type_column, 'protection_class'])['area_ha'].sum().reset_index()
    result.columns = ['ecosystem_type', 'pa_class', 'area_ha']

    logger.info(f"Computed coverage for {len(result)} ecosystem-PA class combinations")
    return result


def representativity_index(
    coverage_df: pd.DataFrame,
    territory_totals: Dict[str, float],
    target_threshold: float = 0.30
) -> pd.DataFrame:
    """
    Compute representativity index (RI) per ecosystem type.

    Formula: RI_e = min(coverage_e / target_threshold_e, 1.0)
    Synthetic RI: mean of all RI_e values.

    Parameters
    ----------
    coverage_df : pd.DataFrame
        Output from cross_with_ecosystem_types with columns:
        ecosystem_type, pa_class, area_ha.
    territory_totals : dict
        Dictionary mapping ecosystem_type to total area (ha) in territory.
        Example: {'forests': 10000.0, 'wetlands': 5000.0, 'grasslands': 8000.0}
    target_threshold : float, default=0.30
        Target protection percentage (0.30 = 30% KMGBF Target 3).

    Returns
    -------
    pd.DataFrame
        DataFrame with columns:
        - ecosystem_type : ecosystem type label
        - total_ha : total area of this type in territory
        - protected_ha : area under protection (all classes)
        - coverage_pct : percentage protected (0-100)
        - RI : representativity index (0-1, capped at 1.0)
        - gap_ha : remaining area needed to reach target

    Notes
    -----
    RI interpretation:
    - RI = 1.0 : target threshold achieved or exceeded
    - RI < 1.0 : under-represented ecosystem type
    - RI = 0.0 : no protection

    The synthetic RI is the mean of all individual RI_e values and represents
    overall network representativity.

    Examples
    --------
    >>> territory_totals = {'forests': 10000, 'wetlands': 5000, 'grasslands': 8000}
    >>> ri_df = representativity_index(coverage_df, territory_totals, target_threshold=0.30)
    >>> print(ri_df)
      ecosystem_type  total_ha  protected_ha  coverage_pct    RI   gap_ha
    0        forests   10000.0        3500.0          35.0  1.00      0.0
    1       wetlands    5000.0         800.0          16.0  0.53    700.0
    2     grasslands    8000.0        1200.0          15.0  0.50   1200.0
    >>> synthetic_ri = ri_df['RI'].mean()
    >>> print(f"Synthetic RI: {synthetic_ri:.2f}")
    """
    if len(coverage_df) == 0:
        logger.warning("Empty coverage DataFrame — returning RI=0.0 for all ecosystem types")
        if not territory_totals:
            return pd.DataFrame(
                columns=['ecosystem_type', 'total_ha', 'protected_ha', 'coverage_pct', 'RI', 'gap_ha']
            )
        return pd.DataFrame([{
            'ecosystem_type': eco_type,
            'total_ha': total_ha,
            'protected_ha': 0.0,
            'coverage_pct': 0.0,
            'RI': 0.0,
            'gap_ha': total_ha * target_threshold,
        } for eco_type, total_ha in territory_totals.items()])

    # Aggregate protected area by ecosystem type (sum across all PA classes)
    protected = coverage_df.groupby('ecosystem_type')['area_ha'].sum().to_dict()

    results = []

    for eco_type, total_ha in territory_totals.items():
        protected_ha = protected.get(eco_type, 0.0)

        # Coverage percentage
        coverage_pct = (protected_ha / total_ha * 100.0) if total_ha > 0 else 0.0

        # Representativity index (capped at 1.0)
        coverage_fraction = protected_ha / total_ha if total_ha > 0 else 0.0
        ri = min(coverage_fraction / target_threshold, 1.0)

        # Gap to target
        target_ha = total_ha * target_threshold
        gap_ha = max(0.0, target_ha - protected_ha)

        results.append({
            'ecosystem_type': eco_type,
            'total_ha': total_ha,
            'protected_ha': protected_ha,
            'coverage_pct': coverage_pct,
            'RI': ri,
            'gap_ha': gap_ha
        })

    df = pd.DataFrame(results)

    # Compute synthetic RI
    synthetic_ri = df['RI'].mean()

    logger.info(
        f"Representativity analysis complete. Synthetic RI: {synthetic_ri:.3f}\n"
        f"Ecosystem types at target: {(df['RI'] >= 1.0).sum()} / {len(df)}"
    )

    return df


def propose_group_a_weights(
    ri_df: pd.DataFrame,
    criterion_ecosystem_mapping: Dict[str, str]
) -> Dict[str, float]:
    """
    Derive default Group A criterion weights from representativity deficits.

    Formula: w_i = deficit_e / Σ deficit_e
    where deficit_e = max(0, target_threshold_e - current_coverage_e)

    Only informs intra-Group A weights. Returns normalised dict (Σ = 1.0).

    Parameters
    ----------
    ri_df : pd.DataFrame
        Output from representativity_index with columns:
        ecosystem_type, total_ha, protected_ha, coverage_pct, RI, gap_ha.
    criterion_ecosystem_mapping : dict
        Mapping from Group A criterion name to ecosystem type.
        From config/criteria_defaults.yaml.
        Example: {
            'ecosystem_condition': 'all',
            'regulating_es': 'wetlands',
            'low_pressure': 'all'
        }

    Returns
    -------
    dict
        Normalised weights for Group A criteria (sum = 1.0).
        Example: {
            'ecosystem_condition': 0.35,
            'regulating_es': 0.45,
            'low_pressure': 0.20
        }

    Warnings
    --------
    This function ONLY proposes weights for Group A criteria (ecological
    integrity). It CANNOT inform inter-group weights (W_A, W_B, W_C) which
    require user value judgement.

    The mapping between criteria and ecosystem types must be defined manually
    in config/criteria_defaults.yaml and reflects expert judgement about which
    criteria best capture conservation priorities for each ecosystem.

    Notes
    -----
    - If an ecosystem type is mapped to 'all', the average deficit across all
      types is used.
    - If total deficit is zero (all types at target), equal weights are returned.
    - Weights are normalised to sum to 1.0.

    Examples
    --------
    >>> criterion_mapping = {
    ...     'ecosystem_condition': 'all',
    ...     'regulating_es': 'wetlands',
    ...     'low_pressure': 'all'
    ... }
    >>> weights = propose_group_a_weights(ri_df, criterion_mapping)
    >>> print(weights)
    {'ecosystem_condition': 0.33, 'regulating_es': 0.47, 'low_pressure': 0.20}
    >>> assert abs(sum(weights.values()) - 1.0) < 1e-6
    """
    logger.warning(
        "Weight proposal is valid ONLY for Group A criteria. "
        "Inter-group weights (W_A, W_B, W_C) require user value judgement and "
        "cannot be derived from representativity deficits alone."
    )

    if len(ri_df) == 0:
        logger.warning("Empty representativity DataFrame, returning equal weights")
        n_criteria = len(criterion_ecosystem_mapping)
        equal_weight = 1.0 / n_criteria if n_criteria > 0 else 0.0
        return {crit: equal_weight for crit in criterion_ecosystem_mapping.keys()}

    # Build deficit lookup by ecosystem type
    deficit_by_type = ri_df.set_index('ecosystem_type')['gap_ha'].to_dict()

    # Compute average deficit for 'all' mapping
    avg_deficit = ri_df['gap_ha'].mean()

    # Map criteria to deficits
    criterion_deficits = {}

    for criterion, eco_type in criterion_ecosystem_mapping.items():
        if eco_type == 'all':
            deficit = avg_deficit
        else:
            deficit = deficit_by_type.get(eco_type, 0.0)

        criterion_deficits[criterion] = deficit

    # Normalise weights
    total_deficit = sum(criterion_deficits.values())

    if total_deficit == 0:
        logger.info("All ecosystem types at target, returning equal weights")
        n_criteria = len(criterion_ecosystem_mapping)
        equal_weight = 1.0 / n_criteria
        weights = {crit: equal_weight for crit in criterion_ecosystem_mapping.keys()}
    else:
        weights = {
            crit: deficit / total_deficit
            for crit, deficit in criterion_deficits.items()
        }

    logger.info(f"Proposed Group A weights (from representativity): {weights}")

    # Verify sum
    weight_sum = sum(weights.values())
    assert abs(weight_sum - 1.0) < 1e-6, f"Weights do not sum to 1.0: {weight_sum}"

    return weights
