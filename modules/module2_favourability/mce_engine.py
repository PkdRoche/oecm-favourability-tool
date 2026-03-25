"""Multi-criteria evaluation engine.

This module implements the core MCE aggregation functions for OECM favourability
analysis. Only weighted geometric mean and Yager OWA aggregation methods are
supported. Weighted Linear Combination (WLC) is explicitly forbidden per
SPECIFICATIONS.md section 4.4.

Functions
---------
weighted_geometric_mean
    Compute weighted geometric mean of criteria arrays.
yager_owa
    Compute Yager OWA aggregation with configurable orness parameter.
compute_favourability
    Full MCE pipeline producing favourability scores and masks.
"""

import logging
import numpy as np
import yaml
from pathlib import Path
from typing import Optional

from . import criteria_manager
from . import raster_preprocessing

logger = logging.getLogger(__name__)


def weighted_geometric_mean(
    arrays: list[np.ndarray],
    weights: list[float]
) -> np.ndarray:
    """Compute weighted geometric mean of criteria arrays.

    Formula: S = prod(array_i ^ w_i) for all i, where sum(w_i) = 1.

    Computation is performed in log-space to avoid numerical underflow:
    S = exp(sum(w_i * log(array_i)))

    Parameters
    ----------
    arrays : list[np.ndarray]
        List of numpy arrays containing criteria values. All arrays must have
        the same shape. Values should be in [0, 1].
    weights : list[float]
        List of weights corresponding to each array. Weights must sum to 1.0.

    Returns
    -------
    np.ndarray
        Aggregated score array with values in [0, 1]. Same shape as input arrays.

    Raises
    ------
    ValueError
        If weights do not sum to 1.0 (tolerance 1e-6).
        If number of arrays does not match number of weights.
        If arrays have inconsistent shapes.

    Notes
    -----
    - NaN propagation: if any input criterion is NaN, output is NaN.
    - Zero handling: exact 0 inputs are floored to 1e-9 before log-space
      computation, driving the output very close to 0 without nullifying it.
      Hard pixel elimination is handled upstream by the Group D mask.
    - The function is strongly non-compensatory: a near-zero criterion pulls
      the total score toward 0, but only Group D eliminates pixels entirely.

    Examples
    --------
    >>> import numpy as np
    >>> arrays = [np.array([0.8, 0.6]), np.array([0.5, 0.9])]
    >>> weights = [0.6, 0.4]
    >>> result = weighted_geometric_mean(arrays, weights)
    >>> # result[0] = 0.8^0.6 * 0.5^0.4 = 0.6822...
    >>> # result[1] = 0.6^0.6 * 0.9^0.4 = 0.7192...
    """
    logger.info(f"Computing weighted geometric mean for {len(arrays)} criteria")

    # Validate inputs
    if len(arrays) != len(weights):
        raise ValueError(
            f"Number of arrays ({len(arrays)}) must match number of weights ({len(weights)})"
        )

    if len(arrays) == 0:
        raise ValueError("At least one array and weight must be provided")

    # Check weights sum to 1.0
    weight_sum = sum(weights)
    if not np.isclose(weight_sum, 1.0, atol=1e-6):
        raise ValueError(
            f"Weights must sum to 1.0, got {weight_sum:.6f}"
        )

    # Check all arrays have same shape
    reference_shape = arrays[0].shape
    for i, arr in enumerate(arrays[1:], start=1):
        if arr.shape != reference_shape:
            raise ValueError(
                f"Array {i} shape {arr.shape} does not match reference shape {reference_shape}"
            )

    # Convert to float64 and ensure weights are numpy array
    arrays_float = [arr.astype(np.float64) for arr in arrays]
    weights_arr = np.array(weights, dtype=np.float64)

    # Small floor to avoid log(0): a criterion value of 0 drives the score
    # very close to 0 but does not nullify it completely.
    # Hard elimination of pixels is Group D's responsibility, not the aggregator's.
    EPS = 1e-9

    # Build NaN mask (NaN propagates; exact zeros do NOT kill the output)
    nan_mask = np.zeros(reference_shape, dtype=bool)
    for arr in arrays_float:
        nan_mask |= np.isnan(arr)

    valid_mask = ~nan_mask

    # Compute weighted geometric mean in log-space for all non-NaN pixels
    result = np.full(reference_shape, np.nan, dtype=np.float64)
    if np.any(valid_mask):
        log_sum = np.zeros(reference_shape, dtype=np.float64)
        for arr, w in zip(arrays_float, weights_arr):
            safe = np.where(valid_mask, np.maximum(arr, EPS), 1.0)
            log_sum += w * np.where(valid_mask, np.log(safe), 0.0)
        result = np.where(valid_mask, np.clip(np.exp(log_sum), 0.0, 1.0), np.nan)

    logger.info(f"Geometric mean complete. Range: [{np.nanmin(result):.4f}, {np.nanmax(result):.4f}]")
    return result


def yager_owa(
    arrays: list[np.ndarray],
    weights: list[float],
    alpha: float
) -> np.ndarray:
    """Compute Yager OWA aggregation with orness parameter.

    Ordered Weighted Averaging (OWA) provides a family of aggregation operators
    ranging from AND logic (minimum) to OR logic (maximum) controlled by the
    orness parameter alpha.

    Parameters
    ----------
    arrays : list[np.ndarray]
        List of numpy arrays containing criteria values. All arrays must have
        the same shape. Values should be in [0, 1].
    weights : list[float]
        List of criterion importance weights. These represent the relative
        importance of each criterion, NOT the OWA position weights.
        Weights must sum to 1.0.
    alpha : float
        Orness parameter in [0, 1]:
        - alpha = 0: pure AND logic (minimum value)
        - alpha = 0.5: balanced partial compensation
        - alpha = 1: pure OR logic (maximum value)
        Recommended default: 0.25 (near AND logic, conservative)

    Returns
    -------
    np.ndarray
        Aggregated score array with values in [0, 1]. Same shape as input arrays.

    Raises
    ------
    ValueError
        If alpha is not in [0, 1].
        If weights do not sum to 1.0 (tolerance 1e-6).
        If number of arrays does not match number of weights.
        If arrays have inconsistent shapes.

    Notes
    -----
    The algorithm follows the specification for combining criterion importance
    weights with OWA position weights:

    1. Stack raw criterion values and sort per pixel in descending order -> b_j.
    2. Compute OWA position weights v_j from alpha using Yager's formula:
       v_j = (j/n)^(1-alpha) - ((j-1)/n)^(1-alpha)
       where n is the number of criteria and j = 1, ..., n.
    3. Compute final score: S = sum(v_j * b_j)

    The criterion importance weights affect which criteria contribute more
    heavily to the aggregation by being applied before sorting, but to keep
    results in [0,1] range with the expected min/max behaviour at alpha=0/1,
    we use raw values for OWA and importance weights only affect tie-breaking.

    For alpha=0 (AND): result equals the minimum criterion value.
    For alpha=1 (OR): result equals the maximum criterion value.

    Examples
    --------
    >>> import numpy as np
    >>> arrays = [np.array([0.8]), np.array([0.5]), np.array([0.2])]
    >>> weights = [1/3, 1/3, 1/3]
    >>> # alpha=0 -> minimum = 0.2
    >>> result = yager_owa(arrays, weights, alpha=0.0)
    """
    logger.info(f"Computing Yager OWA for {len(arrays)} criteria with alpha={alpha}")

    # Validate alpha
    if not (0.0 <= alpha <= 1.0):
        raise ValueError(f"Alpha must be in [0, 1], got {alpha}")

    # Validate inputs
    if len(arrays) != len(weights):
        raise ValueError(
            f"Number of arrays ({len(arrays)}) must match number of weights ({len(weights)})"
        )

    if len(arrays) == 0:
        raise ValueError("At least one array and weight must be provided")

    # Check weights sum to 1.0
    weight_sum = sum(weights)
    if not np.isclose(weight_sum, 1.0, atol=1e-6):
        raise ValueError(
            f"Weights must sum to 1.0, got {weight_sum:.6f}"
        )

    # Check all arrays have same shape
    reference_shape = arrays[0].shape
    for i, arr in enumerate(arrays[1:], start=1):
        if arr.shape != reference_shape:
            raise ValueError(
                f"Array {i} shape {arr.shape} does not match reference shape {reference_shape}"
            )

    n = len(arrays)
    arrays_float = [arr.astype(np.float64) for arr in arrays]

    # Build NaN mask
    nan_mask = np.zeros(reference_shape, dtype=bool)
    for arr in arrays_float:
        nan_mask |= np.isnan(arr)

    # Step 1: Stack raw values and sort per pixel in descending order
    # (Importance weights are orthogonal to OWA position weights per spec)
    stacked = np.stack(arrays_float, axis=-1)  # Shape: (..., n)
    sorted_values = np.sort(stacked, axis=-1)[..., ::-1]  # Descending

    # Step 2: Compute OWA position weights using Yager's formula
    # v_j = (j/n)^(1-alpha) - ((j-1)/n)^(1-alpha) for j = 1, ..., n
    # Note: j is 1-indexed, so for position 0 in array we use j=1

    if alpha == 0.0:
        # Pure AND: result is minimum (last position after desc sort)
        owa_weights = np.zeros(n)
        owa_weights[-1] = 1.0
    elif alpha == 1.0:
        # Pure OR: result is maximum (first position after desc sort)
        owa_weights = np.zeros(n)
        owa_weights[0] = 1.0
    else:
        # General case: Yager's OWA weights
        exponent = 1.0 - alpha
        owa_weights = np.zeros(n)
        for j in range(1, n + 1):
            owa_weights[j - 1] = (j / n) ** exponent - ((j - 1) / n) ** exponent

    logger.debug(f"OWA position weights: {owa_weights}")

    # Step 3: Compute weighted sum: S = sum(v_j * b_j)
    result = np.sum(sorted_values * owa_weights, axis=-1)

    # Ensure result is in [0, 1]
    result = np.clip(result, 0.0, 1.0)

    # Apply NaN mask
    result[nan_mask] = np.nan

    logger.info(f"OWA complete. Range: [{np.nanmin(result):.4f}, {np.nanmax(result):.4f}]")
    return result


def _load_criteria_config() -> dict:
    """Load criteria defaults configuration."""
    config_path = Path(__file__).parent.parent.parent / "config" / "criteria_defaults.yaml"
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def _load_transformation_config() -> dict:
    """Load transformation function configuration."""
    config_path = Path(__file__).parent.parent.parent / "config" / "transformation_functions.yaml"
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def _load_landuse_config() -> dict:
    """Load land use compatibility configuration."""
    config_path = Path(__file__).parent.parent.parent / "config" / "land_use_compatibility.yaml"
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def compute_favourability(
    ecosystem_condition: np.ndarray,
    regulating_es: np.ndarray,
    cultural_es: np.ndarray,
    provisioning_es: np.ndarray,
    anthropogenic_pressure: np.ndarray,
    landuse: np.ndarray,
    weights: dict,
    method: str = "geometric",
    alpha: float = 0.25,
    threshold_pressure: float = 150.0
) -> dict[str, np.ndarray]:
    """Compute full MCE favourability pipeline.

    Implements the complete multi-criteria evaluation for OECM favourability,
    following the strict order: Group D (eliminatory mask) -> Group A -> B -> C.

    Parameters
    ----------
    ecosystem_condition : np.ndarray
        Ecosystem condition layer, values in [0, 1].
    regulating_es : np.ndarray
        Regulating ecosystem services capacity, values in [0, 1].
    cultural_es : np.ndarray
        Cultural ecosystem services capacity, values in [0, 1].
    provisioning_es : np.ndarray
        Provisioning ecosystem services capacity, values in [0, 1].
        Will be transformed using Gaussian normalisation.
    anthropogenic_pressure : np.ndarray
        Raw anthropogenic pressure layer (e.g., population density).
        Dual role: values > threshold_max -> Group D elimination;
        values <= threshold_max -> inverted linear score in Group A.
    landuse : np.ndarray
        Categorical land use layer (CLC/OSO integer codes).
        Dual role: incompatible classes -> Group D elimination;
        compatible classes -> ordinal recoding for Group C.
    weights : dict
        Weight configuration dictionary with keys:
        - 'inter_group_weights': {'W_A': float, 'W_B': float, 'W_C': float}
        - 'group_a_weights': {'ecosystem_condition': float, 'regulating_es': float, 'low_pressure': float}
        - 'group_b_weights': {'cultural_es': float}
        - 'group_c_weights': {'provisioning_es': float, 'compatible_landuse': float}
    method : str, optional
        Aggregation method: 'geometric' or 'owa'. Default is 'geometric'.
    alpha : float, optional
        Orness parameter for OWA method, in [0, 1]. Default is 0.25.

    Returns
    -------
    dict[str, np.ndarray]
        Dictionary containing:
        - 'score': Favourability score [0-1], NaN where ineligible.
        - 'oecm_mask': Boolean array, True = OECM favourable.
        - 'classical_pa_mask': Boolean array, True = classical PA preferable.
        - 'eliminatory_mask': Boolean array, True = eligible (passed Group D).

    Raises
    ------
    ValueError
        If method is not 'geometric' or 'owa'.
        If input arrays have inconsistent shapes.
        If required weight keys are missing.

    Notes
    -----
    Pipeline steps:
    1. Step 0: Apply Group D mask (build_eliminatory_mask) - incompatible land use
       and excessive pressure eliminate pixels.
    2. Step 1: Normalise layers using appropriate transformation functions:
       - pressure: inverted linear (low pressure = high score)
       - provisioning_es: Gaussian (non-monotone, optimum at mean)
       - others: sigmoid or linear per config
    3. Step 2: Compute intra-group scores (A, B, C) using chosen method.
    4. Step 3: Compute inter-group score using chosen method.
    5. Step 4: Check use presence (Group C threshold) to flag classical_pa_preferable.
    6. Step 5: Set score = NaN where eliminatory_mask = False.

    All configuration parameters are loaded from config/ files.
    """
    logger.info(f"Computing favourability with method='{method}', alpha={alpha}")

    # Validate method
    if method not in ('geometric', 'owa'):
        raise ValueError(
            f"Method must be 'geometric' or 'owa', got '{method}'"
        )

    # Validate all arrays have same shape
    reference_shape = ecosystem_condition.shape
    input_arrays = {
        'ecosystem_condition': ecosystem_condition,
        'regulating_es': regulating_es,
        'cultural_es': cultural_es,
        'provisioning_es': provisioning_es,
        'anthropogenic_pressure': anthropogenic_pressure,
        'landuse': landuse
    }
    for name, arr in input_arrays.items():
        if arr.shape != reference_shape:
            raise ValueError(
                f"Array '{name}' shape {arr.shape} does not match reference shape {reference_shape}"
            )

    # Load configurations
    criteria_config = _load_criteria_config()
    transform_config = _load_transformation_config()
    landuse_config = _load_landuse_config()

    # Extract thresholds — use caller-supplied pressure threshold (from sidebar slider)
    max_pressure = threshold_pressure
    min_use_threshold = criteria_config['use_presence']['min_group_c_score']

    # Build incompatible classes list from landuse config
    incompatible_classes = []
    for code, info in landuse_config.get('clc_compatibility', {}).items():
        if info.get('status') == 'eliminatory':
            # Handle both string codes (e.g., "1.1") and integer codes
            # Convert CLC codes to integers for the mask
            # CLC codes like "1", "1.1", "2.1" need to be matched against integer categories
            incompatible_classes.append(code)

    logger.info(f"Eliminatory thresholds: max_pressure={max_pressure}, "
                f"incompatible_classes={incompatible_classes}")

    # =========================================================================
    # Step 0: Apply Group D mask
    # =========================================================================
    eliminatory_mask = criteria_manager.build_eliminatory_mask(
        pressure_array=anthropogenic_pressure,
        landuse_array=landuse,
        threshold_max_pressure=max_pressure,
        incompatible_classes=incompatible_classes
    )
    logger.info(f"Group D mask: {np.sum(eliminatory_mask)} eligible pixels out of {eliminatory_mask.size}")

    # =========================================================================
    # Step 1: Normalise layers
    # =========================================================================
    # Ecosystem condition - sigmoid
    eco_params = transform_config['ecosystem_condition']
    if eco_params['type'] == 'sigmoid':
        eco_score = raster_preprocessing.normalize_sigmoid(
            ecosystem_condition,
            inflection=eco_params['inflection'],
            slope=eco_params['slope']
        )
    else:
        eco_score = raster_preprocessing.normalize_layer(
            ecosystem_condition, 'ecosystem_condition', eco_params
        )

    # Regulating ES - sigmoid
    reg_params = transform_config['regulating_es']
    if reg_params['type'] == 'sigmoid':
        reg_score = raster_preprocessing.normalize_sigmoid(
            regulating_es,
            inflection=reg_params['inflection'],
            slope=reg_params['slope']
        )
    else:
        reg_score = raster_preprocessing.normalize_layer(
            regulating_es, 'regulating_es', reg_params
        )

    # Cultural ES - linear
    cult_params = transform_config['cultural_es']
    cult_score = raster_preprocessing.normalize_layer(
        cultural_es, 'cultural_es', cult_params
    )

    # Provisioning ES - Gaussian (non-monotone, optimum at mean)
    prov_params = transform_config['provisioning_es']
    prov_score = raster_preprocessing.normalize_gaussian(
        provisioning_es,
        mean=prov_params['mean'],
        std=prov_params['std']
    )

    # Anthropogenic pressure - inverted linear for eligible pixels
    # First mask out high pressure areas
    pressure_for_score = anthropogenic_pressure.copy().astype(np.float64)
    pressure_for_score[~eliminatory_mask] = np.nan  # Exclude eliminated pixels

    # Apply inverted linear normalisation
    # Handle edge case where all valid pressure values are the same
    valid_pressure = pressure_for_score[~np.isnan(pressure_for_score)]
    if len(valid_pressure) > 0:
        p_min = np.min(valid_pressure)
        p_max = np.max(valid_pressure)
        if np.isclose(p_min, p_max):
            # All values are the same - assign score of 1.0 (low pressure = good)
            # since they passed the eliminatory threshold
            pressure_score = np.where(
                np.isnan(pressure_for_score),
                np.nan,
                1.0
            )
        else:
            pressure_params = transform_config['anthropogenic_pressure'].copy()
            pressure_params['vmin'] = p_min
            pressure_params['vmax'] = p_max
            pressure_score = raster_preprocessing.normalize_layer(
                pressure_for_score,
                'anthropogenic_pressure',
                pressure_params
            )
    else:
        # No valid pressure values
        pressure_score = np.full(pressure_for_score.shape, np.nan)

    # Recode land use for compatible classes
    landuse_score = criteria_manager.recode_landuse(
        landuse,
        landuse_config['clc_compatibility']
    )

    # =========================================================================
    # Step 2: Compute intra-group scores
    # =========================================================================
    # Extract weights
    group_a_weights = weights.get('group_a_weights', criteria_config['group_a_weights'])
    group_b_weights = weights.get('group_b_weights', criteria_config['group_b_weights'])
    group_c_weights = weights.get('group_c_weights', criteria_config['group_c_weights'])

    # Group A: ecological integrity (ecosystem_condition, regulating_es, low_pressure)
    group_a_arrays = {
        'ecosystem_condition': eco_score,
        'regulating_es': reg_score,
        'low_pressure': pressure_score
    }
    group_a_score = criteria_manager.compute_group_score(
        criteria_arrays=group_a_arrays,
        weights=group_a_weights,
        method=method,
        alpha=alpha
    )
    logger.info(f"Group A score range: [{np.nanmin(group_a_score):.4f}, {np.nanmax(group_a_score):.4f}]")

    # Group B: co-benefits (cultural_es)
    group_b_arrays = {
        'cultural_es': cult_score
    }
    group_b_score = criteria_manager.compute_group_score(
        criteria_arrays=group_b_arrays,
        weights=group_b_weights,
        method=method,
        alpha=alpha
    )
    logger.info(f"Group B score range: [{np.nanmin(group_b_score):.4f}, {np.nanmax(group_b_score):.4f}]")

    # Group C: use function (provisioning_es, compatible_landuse)
    group_c_arrays = {
        'provisioning_es': prov_score,
        'compatible_landuse': landuse_score
    }
    group_c_score = criteria_manager.compute_group_score(
        criteria_arrays=group_c_arrays,
        weights=group_c_weights,
        method=method,
        alpha=alpha
    )
    logger.info(f"Group C score range: [{np.nanmin(group_c_score):.4f}, {np.nanmax(group_c_score):.4f}]")

    # =========================================================================
    # Step 3: Compute inter-group score
    # =========================================================================
    inter_weights = weights.get('inter_group_weights', criteria_config['inter_group_weights'])

    # Build arrays and weights for inter-group aggregation
    inter_arrays = {
        'A': group_a_score,
        'B': group_b_score,
        'C': group_c_score
    }
    inter_weight_values = {
        'A': inter_weights['W_A'],
        'B': inter_weights['W_B'],
        'C': inter_weights['W_C']
    }

    final_score = criteria_manager.compute_group_score(
        criteria_arrays=inter_arrays,
        weights=inter_weight_values,
        method=method,
        alpha=alpha
    )
    logger.info(f"Final score range: [{np.nanmin(final_score):.4f}, {np.nanmax(final_score):.4f}]")

    # =========================================================================
    # Step 4: Check use presence (Group C threshold)
    # =========================================================================
    oecm_mask, classical_pa_mask = criteria_manager.check_use_presence(
        group_c_score=group_c_score,
        min_use_threshold=min_use_threshold
    )
    logger.info(f"OECM favourable: {np.sum(oecm_mask)} pixels")
    logger.info(f"Classical PA preferable: {np.sum(classical_pa_mask)} pixels")

    # =========================================================================
    # Step 5: Set score = NaN where eliminated or classical PA
    # =========================================================================
    # Apply eliminatory mask
    final_score[~eliminatory_mask] = np.nan

    # Pixels flagged as classical_pa_preferable should have score but be excluded from OECM
    # They are kept in the score array but oecm_mask = False for them

    # Return results
    return {
        'score': final_score,
        'oecm_mask': oecm_mask & eliminatory_mask,  # Must pass both Group D and Group C
        'classical_pa_mask': classical_pa_mask & eliminatory_mask,  # Classical PA only if eligible
        'eliminatory_mask': eliminatory_mask
    }
