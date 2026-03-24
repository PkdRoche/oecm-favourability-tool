"""
Tests for raster preprocessing functions.

All tests use synthetic data from tests/synthetic_data/.
Run generate_synthetic_data.py first if synthetic_data/ does not exist.
"""

import pytest
import numpy as np
import rasterio
from pathlib import Path

# Import functions to test
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from modules.module2_favourability.raster_preprocessing import (
    load_raster,
    reproject_raster,
    resample_raster,
    align_rasters,
    apply_nodata_mask,
    normalize_linear,
    normalize_sigmoid,
    normalize_gaussian,
    normalize_layer
)


# Test data directory
SYNTHETIC_DATA_DIR = Path(__file__).parent / "synthetic_data"


@pytest.fixture
def ecosystem_condition_path():
    """Path to ecosystem condition test raster."""
    return str(SYNTHETIC_DATA_DIR / "ecosystem_condition.tif")


@pytest.fixture
def regulating_es_path():
    """Path to regulating ES test raster."""
    return str(SYNTHETIC_DATA_DIR / "regulating_es.tif")


@pytest.fixture
def cultural_es_path():
    """Path to cultural ES test raster."""
    return str(SYNTHETIC_DATA_DIR / "cultural_es.tif")


@pytest.fixture
def provisioning_es_path():
    """Path to provisioning ES test raster."""
    return str(SYNTHETIC_DATA_DIR / "provisioning_es.tif")


@pytest.fixture
def anthropogenic_pressure_path():
    """Path to anthropogenic pressure test raster."""
    return str(SYNTHETIC_DATA_DIR / "anthropogenic_pressure.tif")


@pytest.fixture
def land_use_path():
    """Path to land use test raster."""
    return str(SYNTHETIC_DATA_DIR / "land_use.tif")


def test_load_raster_returns_array_and_profile(ecosystem_condition_path):
    """Test that load_raster returns array and profile."""
    array, profile = load_raster(ecosystem_condition_path)

    assert isinstance(array, np.ndarray)
    assert isinstance(profile, dict)
    assert 'crs' in profile
    assert 'transform' in profile
    assert 'width' in profile
    assert 'height' in profile


def test_load_raster_shape_matches_file(ecosystem_condition_path):
    """Test that loaded array shape matches file dimensions."""
    array, profile = load_raster(ecosystem_condition_path)

    # Verify against direct rasterio read
    with rasterio.open(ecosystem_condition_path) as src:
        expected_shape = src.shape
        expected_dtype = src.dtypes[0]

    assert array.shape == expected_shape
    assert array.shape == (profile['height'], profile['width'])
    assert str(array.dtype) == expected_dtype


def test_reproject_output_crs_matches_target(ecosystem_condition_path):
    """Test that reprojected raster has correct target CRS."""
    array, profile = load_raster(ecosystem_condition_path)

    # Reproject from EPSG:3035 to EPSG:4326
    target_crs = "EPSG:4326"
    reprojected_array, reprojected_profile = reproject_raster(
        array, profile, target_crs
    )

    assert str(reprojected_profile['crs']).upper() == target_crs.upper()
    assert isinstance(reprojected_array, np.ndarray)
    assert reprojected_array.size > 0


def test_reproject_invalid_crs_raises_value_error(ecosystem_condition_path):
    """Test that invalid CRS raises ValueError."""
    array, profile = load_raster(ecosystem_condition_path)

    with pytest.raises(ValueError, match="Invalid target CRS"):
        reproject_raster(array, profile, "INVALID:CRS:12345")


def test_align_rasters_identical_extents():
    """Test that aligned rasters have identical extents."""
    # Load multiple rasters
    paths = {
        "ecosystem_condition": str(SYNTHETIC_DATA_DIR / "ecosystem_condition.tif"),
        "regulating_es": str(SYNTHETIC_DATA_DIR / "regulating_es.tif"),
        "cultural_es": str(SYNTHETIC_DATA_DIR / "cultural_es.tif")
    }

    raster_dict = {}
    for name, path in paths.items():
        array, profile = load_raster(path)
        raster_dict[name] = (array, profile)

    # Align rasters
    aligned = align_rasters(raster_dict)

    # Get reference bounds (first sorted name)
    ref_name = sorted(raster_dict.keys())[0]
    ref_profile = aligned[ref_name][1]
    ref_bounds = rasterio.transform.array_bounds(
        ref_profile['height'],
        ref_profile['width'],
        ref_profile['transform']
    )

    # Check all rasters have same bounds
    for name, (array, profile) in aligned.items():
        bounds = rasterio.transform.array_bounds(
            profile['height'],
            profile['width'],
            profile['transform']
        )
        assert np.allclose(bounds, ref_bounds), f"{name} bounds differ from reference"


def test_align_rasters_identical_resolution():
    """Test that aligned rasters have identical resolution."""
    # Load multiple rasters
    paths = {
        "ecosystem_condition": str(SYNTHETIC_DATA_DIR / "ecosystem_condition.tif"),
        "regulating_es": str(SYNTHETIC_DATA_DIR / "regulating_es.tif"),
        "cultural_es": str(SYNTHETIC_DATA_DIR / "cultural_es.tif")
    }

    raster_dict = {}
    for name, path in paths.items():
        array, profile = load_raster(path)
        raster_dict[name] = (array, profile)

    # Align rasters
    aligned = align_rasters(raster_dict)

    # Get reference resolution
    ref_name = sorted(raster_dict.keys())[0]
    ref_profile = aligned[ref_name][1]
    ref_res_x = abs(ref_profile['transform'][0])
    ref_res_y = abs(ref_profile['transform'][4])

    # Check all rasters have same resolution
    for name, (array, profile) in aligned.items():
        res_x = abs(profile['transform'][0])
        res_y = abs(profile['transform'][4])
        assert np.isclose(res_x, ref_res_x), f"{name} x-resolution differs from reference"
        assert np.isclose(res_y, ref_res_y), f"{name} y-resolution differs from reference"


def test_normalize_linear_range_zero_to_one(ecosystem_condition_path):
    """Test that linear normalization produces values in [0, 1]."""
    array, profile = load_raster(ecosystem_condition_path)

    # Apply nodata mask first
    array_masked = apply_nodata_mask(array, profile.get('nodata'))

    # Normalize
    vmin, vmax = 0.0, 1.0
    normalized = normalize_linear(array_masked, vmin, vmax, invert=False)

    # Check range (ignoring NaN)
    valid_values = normalized[~np.isnan(normalized)]
    assert np.all(valid_values >= 0.0), "Some values below 0"
    assert np.all(valid_values <= 1.0), "Some values above 1"
    assert len(valid_values) > 0, "No valid values after normalization"


def test_normalize_linear_inverted_monotone_decreasing(anthropogenic_pressure_path):
    """Test that inverted linear normalization is monotone decreasing."""
    array, profile = load_raster(anthropogenic_pressure_path)

    # Apply nodata mask
    array_masked = apply_nodata_mask(array, profile.get('nodata'))

    # Get min/max for normalization
    vmin = np.nanmin(array_masked)
    vmax = np.nanmax(array_masked)

    # Normalize with invert=True
    normalized = normalize_linear(array_masked, vmin, vmax, invert=True)

    # Check that higher input values produce lower output values
    # Find non-NaN values
    valid_mask = ~np.isnan(array_masked)
    if np.sum(valid_mask) < 2:
        pytest.skip("Not enough valid values to test monotonicity")

    # Get a sample of input-output pairs
    input_vals = array_masked[valid_mask]
    output_vals = normalized[valid_mask]

    # Check monotonicity: sort by input and verify output is decreasing
    sorted_indices = np.argsort(input_vals)
    sorted_output = output_vals[sorted_indices]

    # Compute differences (should be <= 0 for monotone decreasing)
    diffs = np.diff(sorted_output)
    # Allow small numerical errors
    assert np.all(diffs <= 1e-10), "Inverted normalization is not monotone decreasing"


def test_normalize_sigmoid_range_zero_to_one(ecosystem_condition_path):
    """Test that sigmoid normalization produces values in [0, 1]."""
    array, profile = load_raster(ecosystem_condition_path)

    # Apply nodata mask
    array_masked = apply_nodata_mask(array, profile.get('nodata'))

    # Normalize with sigmoid
    inflection = 0.5
    slope = 8.0
    normalized = normalize_sigmoid(array_masked, inflection, slope)

    # Check range (ignoring NaN)
    valid_values = normalized[~np.isnan(normalized)]
    assert np.all(valid_values >= 0.0), "Some sigmoid values below 0"
    assert np.all(valid_values <= 1.0), "Some sigmoid values above 1"
    assert len(valid_values) > 0, "No valid values after sigmoid normalization"


def test_normalize_gaussian_maximum_at_mean(provisioning_es_path):
    """Test that Gaussian normalization has maximum at specified mean."""
    array, profile = load_raster(provisioning_es_path)

    # Apply nodata mask
    array_masked = apply_nodata_mask(array, profile.get('nodata'))

    # Normalize with Gaussian
    mean = 0.45
    std = 0.20
    normalized = normalize_gaussian(array_masked, mean, std)

    # The normalized value should be maximum (=1.0) at input values equal to mean
    # Find values closest to mean
    valid_mask = ~np.isnan(array_masked)
    if np.sum(valid_mask) == 0:
        pytest.skip("No valid values to test")

    distances = np.abs(array_masked - mean)
    distances[~valid_mask] = np.inf

    closest_idx = np.unravel_index(np.argmin(distances), distances.shape)
    max_normalized_value = normalized[closest_idx]

    # Should be close to 1.0
    assert max_normalized_value >= 0.9, f"Maximum value {max_normalized_value} not close to 1.0"

    # Also verify that the maximum normalized value occurs at an input near the mean
    max_norm_idx = np.unravel_index(np.nanargmax(normalized), normalized.shape)
    input_at_max = array_masked[max_norm_idx]
    assert np.abs(input_at_max - mean) < std, f"Maximum occurs at {input_at_max}, far from mean {mean}"


def test_normalize_gaussian_symmetric_around_mean(provisioning_es_path):
    """Test that Gaussian normalization is symmetric around mean."""
    array, profile = load_raster(provisioning_es_path)

    # Apply nodata mask
    array_masked = apply_nodata_mask(array, profile.get('nodata'))

    mean = 0.45
    std = 0.20

    # Create test points symmetric around mean
    test_points = np.array([mean - 0.1, mean, mean + 0.1])
    expected = normalize_gaussian(test_points, mean, std)

    # Values at mean - delta and mean + delta should be equal
    assert np.isclose(expected[0], expected[2]), "Gaussian not symmetric around mean"
    # Value at mean should be maximum (1.0)
    assert np.isclose(expected[1], 1.0), "Value at mean not equal to 1.0"


def test_apply_nodata_mask_converts_to_nan(ecosystem_condition_path):
    """Test that nodata values are converted to np.nan."""
    array, profile = load_raster(ecosystem_condition_path)

    nodata_value = profile.get('nodata')
    if nodata_value is None:
        pytest.skip("No nodata value in test file")

    # Count nodata values before masking
    nodata_count_before = np.sum(array == nodata_value)

    # Apply mask
    masked = apply_nodata_mask(array, nodata_value)

    # Count NaN values after masking
    nan_count_after = np.sum(np.isnan(masked))

    # Should be equal
    assert nan_count_after == nodata_count_before, \
        f"Expected {nodata_count_before} NaN values, got {nan_count_after}"

    # No original nodata values should remain
    assert np.sum(masked == nodata_value) == 0, "Some nodata values not converted to NaN"


def test_apply_nodata_mask_none_nodata_is_safe():
    """Test that apply_nodata_mask handles None nodata gracefully."""
    # Create test array
    test_array = np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32)

    # Apply with None nodata
    masked = apply_nodata_mask(test_array, None)

    # Should return array unchanged (except dtype conversion)
    assert masked.shape == test_array.shape
    assert np.all(masked == test_array)
    assert np.sum(np.isnan(masked)) == 0, "Unexpected NaN values when nodata is None"


def test_normalize_layer_dispatcher_linear():
    """Test normalize_layer dispatcher with linear transformation."""
    test_array = np.array([[0.0, 0.5], [1.0, 1.5]], dtype=np.float64)

    params = {
        'type': 'linear',
        'vmin': 0.0,
        'vmax': 1.0,
        'invert': False
    }

    normalized = normalize_layer(test_array, 'test_layer', params)

    expected = np.array([[0.0, 0.5], [1.0, 1.0]])  # 1.5 clipped to 1.0
    assert np.allclose(normalized, expected)


def test_normalize_layer_dispatcher_sigmoid():
    """Test normalize_layer dispatcher with sigmoid transformation."""
    test_array = np.array([[0.0, 0.5], [1.0, 1.5]], dtype=np.float64)

    params = {
        'type': 'sigmoid',
        'inflection': 0.5,
        'slope': 8.0
    }

    normalized = normalize_layer(test_array, 'test_layer', params)

    # Check range
    assert np.all(normalized >= 0.0)
    assert np.all(normalized <= 1.0)
    # Value at inflection should be ~0.5
    assert np.isclose(normalized[0, 1], 0.5, atol=0.01)


def test_normalize_layer_dispatcher_gaussian():
    """Test normalize_layer dispatcher with gaussian transformation."""
    test_array = np.array([[0.0, 0.45], [0.9, 1.5]], dtype=np.float64)

    params = {
        'type': 'gaussian',
        'mean': 0.45,
        'std': 0.20
    }

    normalized = normalize_layer(test_array, 'test_layer', params)

    # Check range
    assert np.all(normalized >= 0.0)
    assert np.all(normalized <= 1.0)
    # Value at mean should be 1.0
    assert np.isclose(normalized[0, 1], 1.0)


def test_normalize_layer_dispatcher_inverted_linear():
    """Test normalize_layer dispatcher with inverted_linear transformation."""
    test_array = np.array([[0.0, 50.0], [100.0, 150.0]], dtype=np.float64)

    params = {
        'type': 'inverted_linear',
        'vmin': 0.0,
        'vmax': 100.0
    }

    normalized = normalize_layer(test_array, 'test_layer', params)

    # Check that higher values map to lower normalized values
    assert normalized[0, 0] > normalized[1, 0]  # 0.0 > 100.0 after inversion
    assert np.all(normalized >= 0.0)
    assert np.all(normalized <= 1.0)


def test_normalize_layer_missing_type_raises_error():
    """Test that missing 'type' in params raises ValueError."""
    test_array = np.array([[0.0, 1.0]], dtype=np.float64)

    params = {'vmin': 0.0, 'vmax': 1.0}  # Missing 'type'

    with pytest.raises(ValueError, match="missing 'type' key"):
        normalize_layer(test_array, 'test_layer', params)


def test_normalize_layer_unknown_type_raises_error():
    """Test that unknown transformation type raises ValueError."""
    test_array = np.array([[0.0, 1.0]], dtype=np.float64)

    params = {'type': 'unknown_transform'}

    with pytest.raises(ValueError, match="Unknown transformation type"):
        normalize_layer(test_array, 'test_layer', params)


def test_resample_raster_changes_resolution():
    """Test that resample_raster produces correct output resolution."""
    # Load a test raster
    path = str(SYNTHETIC_DATA_DIR / "ecosystem_condition.tif")
    array, profile = load_raster(path)

    # Original resolution is 100m, resample to 200m
    target_resolution = 200.0
    resampled_array, resampled_profile = resample_raster(
        array, profile, target_resolution, method='bilinear'
    )

    # Check resolution
    res_x = abs(resampled_profile['transform'][0])
    res_y = abs(resampled_profile['transform'][4])

    assert np.isclose(res_x, target_resolution), f"X resolution {res_x} != {target_resolution}"
    assert np.isclose(res_y, target_resolution), f"Y resolution {res_y} != {target_resolution}"

    # Shape should be approximately halved
    expected_width = profile['width'] // 2
    expected_height = profile['height'] // 2

    assert abs(resampled_profile['width'] - expected_width) <= 1
    assert abs(resampled_profile['height'] - expected_height) <= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
