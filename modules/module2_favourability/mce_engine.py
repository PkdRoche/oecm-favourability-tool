"""Multi-criteria evaluation engine."""


def weighted_linear_combination(criteria_arrays, weights):
    """
    Compute weighted linear combination of normalised criteria.

    Args:
        criteria_arrays: List of xarray DataArrays (normalised to [0,1])
        weights: List of weights (must sum to 1.0)

    Returns:
        xarray DataArray with aggregated scores
    """
    raise NotImplementedError("Weighted linear combination not yet implemented")


def geometric_mean_aggregation(criteria_arrays, weights):
    """
    Compute weighted geometric mean of normalised criteria.

    Args:
        criteria_arrays: List of xarray DataArrays (normalised to [0,1])
        weights: List of weights (used as exponents)

    Returns:
        xarray DataArray with aggregated scores
    """
    raise NotImplementedError("Geometric mean aggregation not yet implemented")


def owa_aggregation(criteria_arrays, alpha=0.5):
    """
    Ordered weighted averaging with linguistic quantifier.

    Args:
        criteria_arrays: List of xarray DataArrays (normalised to [0,1])
        alpha: Orness parameter (0=AND-like, 1=OR-like)

    Returns:
        xarray DataArray with aggregated scores
    """
    raise NotImplementedError("OWA aggregation not yet implemented")


def compute_favourability_index(criteria_dict, weights_config, method="geometric"):
    """
    Compute final OECM favourability index using hierarchical MCE.

    Args:
        criteria_dict: Dictionary of criterion DataArrays by group
        weights_config: Configuration from criteria_defaults.yaml
        method: Aggregation method ('geometric', 'owa', 'wlc')

    Returns:
        xarray DataArray with favourability scores [0,1]
    """
    raise NotImplementedError("Favourability index computation not yet implemented")
