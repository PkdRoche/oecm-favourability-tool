"""Monte Carlo sensitivity analysis for MCE weight uncertainty.

Runs MCE n_runs times with inter-group and intra-group weights sampled from
Dirichlet distributions centred on the user-specified base values.

The concentration parameter controls how tightly samples cluster around the
base weights:
  - concentration = 5   → wide spread, high uncertainty
  - concentration = 20  → moderate spread (default)
  - concentration = 100 → tight spread, low uncertainty

Returns:
  stability_map : float32 array [0, 1] — fraction of runs where pixel score
                  is >= threshold.  1.0 = always above, 0.0 = never above.
  std_map       : float32 array — standard deviation of scores across runs.
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Dirichlet weight sampling
# ---------------------------------------------------------------------------

def _sample_dirichlet(base: np.ndarray, concentration: float, rng: np.random.Generator) -> np.ndarray:
    """Sample a weight vector from Dirichlet(base * concentration).

    Ensures non-zero alpha values and that the result sums to 1.
    """
    alpha = np.maximum(base * concentration, 0.1)
    return rng.dirichlet(alpha).astype(np.float32)


# ---------------------------------------------------------------------------
# Fast in-place geometric mean aggregation (no YAML loading, no I/O)
# ---------------------------------------------------------------------------

_EPS = np.float32(1e-9)


def _geometric_mean(arrays: list[np.ndarray], weights: np.ndarray) -> np.ndarray:
    """Weighted geometric mean of pre-normalised [0,1] arrays."""
    log_sum = np.zeros(arrays[0].shape, dtype=np.float32)
    for arr, w in zip(arrays, weights):
        safe = np.where(np.isnan(arr), _EPS, np.maximum(arr, _EPS))
        log_sum += w * np.log(safe)
    result = np.exp(log_sum)
    # propagate NaN
    nan_mask = np.zeros(arrays[0].shape, dtype=bool)
    for arr in arrays:
        nan_mask |= np.isnan(arr)
    result[nan_mask] = np.nan
    return result


def _group_score(arrays: list[np.ndarray], weights: np.ndarray) -> np.ndarray:
    """Normalised-weight geometric mean for a single MCE group."""
    w = weights / weights.sum()
    return _geometric_mean(arrays, w)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_sensitivity(
    normalised_arrays: dict[str, np.ndarray],
    base_weights: dict,
    eliminatory_mask: np.ndarray,
    threshold: float,
    n_runs: int = 200,
    concentration: float = 20.0,
    perturb_intra: bool = True,
    seed: Optional[int] = 42,
) -> tuple[np.ndarray, np.ndarray]:
    """Monte Carlo weight sensitivity analysis.

    Parameters
    ----------
    normalised_arrays : dict
        Pre-normalised criterion arrays keyed by criterion name.
        Must include: ecosystem_condition, regulating_es, low_pressure,
        cultural_es, provisioning_es, compatible_landuse.
    base_weights : dict
        User-specified weights dict with keys:
        inter_group_weights  → {W_A, W_B, W_C}
        group_a_weights      → {ecosystem_condition, regulating_es, low_pressure}
        group_b_weights      → {cultural_es}
        group_c_weights      → {provisioning_es, compatible_landuse}
    eliminatory_mask : np.ndarray
        Boolean mask: True = pixel survived Group D (eligible).
    threshold : float
        Score threshold for stability computation.
    n_runs : int
        Number of Monte Carlo iterations.
    concentration : float
        Dirichlet concentration parameter (higher = tighter spread).
    perturb_intra : bool
        If True, also perturb intra-group weights. If False, only inter-group
        weights are perturbed (faster, simpler interpretation).
    seed : int or None
        Random seed for reproducibility.

    Returns
    -------
    stability_map : np.ndarray float32
        Fraction of runs where pixel score >= threshold. Shape = raster shape.
    std_map : np.ndarray float32
        Standard deviation of pixel scores across runs. Shape = raster shape.
    """
    rng   = np.random.default_rng(seed)
    shape = eliminatory_mask.shape

    # Extract base weight vectors
    iw = base_weights['inter_group_weights']
    aw = base_weights['group_a_weights']
    cw = base_weights['group_c_weights']

    base_inter = np.array([iw['W_A'], iw['W_B'], iw['W_C']], dtype=np.float32)
    base_a     = np.array([aw['ecosystem_condition'], aw['regulating_es'], aw['low_pressure']], dtype=np.float32)
    base_c     = np.array([cw['provisioning_es'], cw['compatible_landuse']], dtype=np.float32)

    # Normalise base vectors (safety)
    base_inter /= base_inter.sum()
    base_a     /= base_a.sum()
    base_c     /= base_c.sum()

    # Pre-extract criterion arrays (avoid repeated dict lookups in loop)
    eco  = normalised_arrays['ecosystem_condition']
    reg  = normalised_arrays['regulating_es']
    pres = normalised_arrays['low_pressure']
    cult = normalised_arrays['cultural_es']
    prov = normalised_arrays['provisioning_es']
    luse = normalised_arrays['compatible_landuse']

    # Accumulators
    above_count = np.zeros(shape, dtype=np.float32)
    score_sum   = np.zeros(shape, dtype=np.float32)
    score_sq    = np.zeros(shape, dtype=np.float32)

    logger.info(
        f"Running sensitivity analysis: {n_runs} runs, "
        f"concentration={concentration}, perturb_intra={perturb_intra}"
    )

    for i in range(n_runs):
        # Sample inter-group weights
        w_inter = _sample_dirichlet(base_inter, concentration, rng)

        # Sample or keep intra-group weights
        if perturb_intra:
            w_a = _sample_dirichlet(base_a, concentration, rng)
            w_c = _sample_dirichlet(base_c, concentration, rng)
        else:
            w_a = base_a
            w_c = base_c

        # Group scores
        score_a = _group_score([eco, reg, pres], w_a)
        score_b = cult                                  # single criterion
        score_c = _group_score([prov, luse], w_c)

        # Inter-group aggregation (geometric mean)
        run_score = _geometric_mean([score_a, score_b, score_c], w_inter)

        # Apply eliminatory mask
        run_score = np.where(eliminatory_mask, run_score, np.nan)

        # Accumulate
        valid = ~np.isnan(run_score)
        above_count[valid & (run_score >= threshold)] += 1.0
        score_sum[valid]  += run_score[valid]
        score_sq[valid]   += run_score[valid] ** 2

    # Stability = fraction of runs above threshold (NaN for eliminated pixels)
    stability_map = np.where(eliminatory_mask, above_count / n_runs, np.nan).astype(np.float32)

    # Std dev of scores
    n_valid_runs = n_runs  # same denominator for all eligible pixels
    mean_scores  = np.where(eliminatory_mask, score_sum / n_valid_runs, np.nan)
    variance     = np.where(eliminatory_mask,
                            score_sq / n_valid_runs - mean_scores ** 2,
                            np.nan)
    std_map = np.sqrt(np.maximum(variance, 0.0)).astype(np.float32)

    n_stable = int(np.nansum(stability_map >= 0.8))
    n_unstable = int(np.nansum((stability_map < 0.5) & ~np.isnan(stability_map)))
    logger.info(
        f"Sensitivity complete: {n_stable} stable pixels (≥80% runs), "
        f"{n_unstable} unstable pixels (<50% runs)"
    )

    return stability_map, std_map
