from __future__ import annotations

import numpy as np
import pytest

from plug_analyzer.analysis.qc import boundary_qc, saturation_qc
from plug_analyzer.analysis.robustness import robustness_interval, threshold_variants


def test_saturation_qc_reports_overall_plane_and_plug_fractions() -> None:
    image = np.asarray(
        [
            [[0, 9], [10, 11]],
            [[2, 3], [4, 10]],
        ],
        dtype=np.uint16,
    )
    plug = np.zeros(image.shape, dtype=np.bool_)
    plug[0, 1, :] = True
    plug[1, 1, 1] = True

    result = saturation_qc(image, saturation_threshold=10, plug_mask=plug)

    assert result.saturated_count == 3
    assert result.valid_count == 8
    assert result.fraction == pytest.approx(3 / 8)
    np.testing.assert_array_equal(result.count_by_z, [2, 1])
    np.testing.assert_allclose(result.fraction_by_z, [0.5, 0.25])
    assert result.plug_saturated_count == 3
    assert result.plug_valid_count == 3
    assert result.plug_fraction == 1.0


def test_boundary_qc_identifies_each_contact_and_contact_fraction() -> None:
    mask = np.zeros((3, 3, 4), dtype=np.bool_)
    mask[0, 1, 1] = True
    mask[1, 1, 1] = True
    mask[1, 1, 3] = True

    result = boundary_qc(mask)

    assert result.touches_z_min
    assert not result.touches_z_max
    assert not result.touches_y_min
    assert not result.touches_y_max
    assert not result.touches_x_min
    assert result.touches_x_max
    assert result.touches_z_boundary
    assert result.touches_xy_boundary
    assert result.touches_any_boundary
    assert result.fraction_on_z_min == pytest.approx(1 / 3)
    assert result.fraction_on_x_max == pytest.approx(1 / 3)


def test_empty_mask_boundary_fractions_are_undefined() -> None:
    result = boundary_qc(np.zeros((1, 1, 1), dtype=np.bool_))

    assert not result.touches_any_boundary
    assert np.isnan(result.fraction_on_z_min)


def test_threshold_variants_scale_both_hysteresis_thresholds() -> None:
    variants = threshold_variants(2.0, 5.0, relative_variation=0.10)

    assert [variant.name for variant in variants] == [
        "lower_thresholds",
        "primary",
        "upper_thresholds",
    ]
    assert [(variant.low_threshold, variant.high_threshold) for variant in variants] == [
        pytest.approx((1.8, 4.5)),
        pytest.approx((2.0, 5.0)),
        pytest.approx((2.2, 5.5)),
    ]


def test_robustness_interval_is_not_a_confidence_interval() -> None:
    result = robustness_interval(10.0, {"lower": 8.0, "upper": 13.0})

    assert result.minimum == 8.0
    assert result.maximum == 13.0
    assert result.absolute_span == 5.0
    assert result.maximum_absolute_deviation == 3.0
    assert result.maximum_relative_deviation_percent == 30.0
    assert result.variant_count == 2


def test_zero_primary_robustness_has_no_relative_deviation() -> None:
    result = robustness_interval(0.0, (-1.0, 1.0))

    assert result.maximum_relative_deviation_percent is None
