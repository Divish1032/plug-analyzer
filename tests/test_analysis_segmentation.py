from __future__ import annotations

import numpy as np
import pytest
from scipy import ndimage

from plug_analyzer.analysis.segmentation import (
    filter_components_by_volume,
    gaussian_filter_physical,
    hysteresis_threshold_3d,
)


def test_gaussian_filter_converts_physical_sigma_per_axis() -> None:
    image = np.zeros((9, 9, 9), dtype=np.float64)
    image[4, 4, 4] = 1.0

    actual = gaussian_filter_physical(
        image,
        spacing_zyx_um=(2.0, 1.0, 0.5),
        sigma_um=2.0,
        mode="constant",
    )
    expected = ndimage.gaussian_filter(
        image,
        sigma=(1.0, 2.0, 4.0),
        mode="constant",
        truncate=4.0,
    )

    np.testing.assert_allclose(actual, expected, rtol=0.0, atol=1e-15)
    assert not np.shares_memory(actual, image)


def test_gaussian_filter_uses_normalized_convolution_around_invalid_voxel() -> None:
    image = np.full((3, 5, 5), 7.0)
    image[1, 2, 2] = np.nan

    filtered = gaussian_filter_physical(
        image,
        spacing_zyx_um=(1.0, 1.0, 1.0),
        sigma_um=1.0,
    )

    assert np.isnan(filtered[1, 2, 2])
    np.testing.assert_allclose(filtered[np.isfinite(filtered)], 7.0, atol=1e-12)


def test_hysteresis_retains_only_candidates_connected_to_seed() -> None:
    filtered = np.zeros((3, 3, 3), dtype=np.float64)
    filtered[1, 1, 1] = 10.0  # seed
    filtered[1, 1, 2] = 6.0  # face-connected candidate
    filtered[0, 0, 0] = 6.0  # disconnected candidate under 6-neighbour rule

    result = hysteresis_threshold_3d(
        filtered,
        low_threshold=5.0,
        high_threshold=8.0,
    )

    expected = np.zeros_like(result)
    expected[1, 1, 1] = True
    expected[1, 1, 2] = True
    np.testing.assert_array_equal(result, expected)


def test_hysteresis_connectivity_sensitivity_detects_diagonal_candidate() -> None:
    filtered = np.zeros((2, 2, 2), dtype=np.float64)
    filtered[0, 0, 0] = 10.0
    filtered[1, 1, 1] = 6.0

    conservative = hysteresis_threshold_3d(
        filtered,
        low_threshold=5.0,
        high_threshold=8.0,
        connectivity=6,
    )
    diagonal = hysteresis_threshold_3d(
        filtered,
        low_threshold=5.0,
        high_threshold=8.0,
        connectivity=26,
    )

    assert np.count_nonzero(conservative) == 1
    assert np.count_nonzero(diagonal) == 2


def test_component_filter_uses_physical_volume_and_six_neighbours() -> None:
    mask = np.zeros((2, 3, 4), dtype=np.bool_)
    mask[0, 0, 0] = True  # one voxel = 1 um3
    mask[1, 1, 2:4] = True  # two voxels = 2 um3

    result = filter_components_by_volume(
        mask,
        spacing_zyx_um=(2.0, 1.0, 0.5),
        min_component_volume_um3=2.0,
    )

    np.testing.assert_allclose(np.sort(result.component_volumes_um3), [1.0, 2.0])
    assert result.retained_component_count == 1
    assert result.removed_component_count == 1
    assert not result.mask[0, 0, 0]
    assert np.all(result.mask[1, 1, 2:4])


def test_component_filter_accounts_for_nonuniform_plane_thickness() -> None:
    mask = np.zeros((3, 2, 2), dtype=np.bool_)
    mask[0, 0, 0] = True
    mask[2, 1, 1] = True

    result = filter_components_by_volume(
        mask,
        spacing_zyx_um=(1.0, 1.0, 1.0),
        z_positions_um=(0.0, 1.0, 3.0),  # represented thicknesses 1, 1.5, 2
        min_component_volume_um3=1.5,
    )

    np.testing.assert_allclose(np.sort(result.component_volumes_um3), [1.0, 2.0])
    assert not result.mask[0, 0, 0]
    assert result.mask[2, 1, 1]


def test_segmentation_rejects_inverted_thresholds() -> None:
    with pytest.raises(ValueError, match="low_threshold"):
        hysteresis_threshold_3d(
            np.zeros((1, 1, 1)),
            low_threshold=2.0,
            high_threshold=1.0,
        )
