from __future__ import annotations

import numpy as np
import pytest

from plug_analyzer.analysis.corrections import (
    InsufficientReferenceError,
    median_background_correct,
    robust_mad_sigma,
)


def test_median_background_correction_is_per_plane_and_preserves_negatives() -> None:
    image = np.asarray(
        [
            [[10, 12], [8, 20]],
            [[100, 104], [96, 130]],
        ],
        dtype=np.uint16,
    )
    reference = np.asarray(
        [
            [[True, True], [True, False]],
            [[True, True], [True, False]],
        ]
    )

    result = median_background_correct(
        image,
        reference,
        min_reference_pixels_per_plane=3,
    )

    np.testing.assert_array_equal(result.offsets_by_z, [10.0, 100.0])
    np.testing.assert_array_equal(result.reference_counts_by_z, [3, 3])
    np.testing.assert_array_equal(
        result.corrected,
        [[[0.0, 2.0], [-2.0, 10.0]], [[0.0, 4.0], [-4.0, 30.0]]],
    )
    assert result.corrected[0, 1, 0] == -2.0


def test_background_correction_excludes_invalid_saturated_and_nonfinite_samples() -> None:
    image = np.asarray([[[1.0, 3.0], [100.0, np.nan]]])
    reference = np.ones(image.shape, dtype=np.bool_)
    saturated = np.zeros(image.shape, dtype=np.bool_)
    saturated[0, 1, 0] = True

    result = median_background_correct(
        image,
        reference,
        saturated_mask=saturated,
        min_reference_pixels_per_plane=2,
    )

    assert result.offsets_by_z[0] == 2.0
    assert result.reference_counts_by_z[0] == 2
    assert result.corrected[0, 0, 0] == -1.0
    assert np.isnan(result.corrected[0, 1, 1])


def test_background_correction_fails_closed_for_an_undersized_plane() -> None:
    image = np.ones((2, 2, 2), dtype=np.uint16)
    reference = np.ones(image.shape, dtype=np.bool_)
    reference[1] = False
    reference[1, 0, 0] = True

    with pytest.raises(InsufficientReferenceError) as error:
        median_background_correct(
            image,
            reference,
            min_reference_pixels_per_plane=2,
        )

    assert error.value.failed_planes == (1,)
    np.testing.assert_array_equal(error.value.counts_by_z, [4, 1])


def test_robust_mad_sigma_resists_a_large_outlier() -> None:
    values = np.asarray([1.0, 2.0, 3.0, 4.0, 100.0])

    assert robust_mad_sigma(values) == pytest.approx(1.4826)


def test_robust_mad_requires_a_boolean_shape_matched_mask() -> None:
    values = np.arange(4.0).reshape(2, 2)

    with pytest.raises(TypeError, match="boolean"):
        robust_mad_sigma(values, mask=np.ones((2, 2), dtype=np.uint8))
    with pytest.raises(ValueError, match="does not match"):
        robust_mad_sigma(values, mask=np.ones((4,), dtype=np.bool_))
