from __future__ import annotations

import numpy as np
import pytest
from scipy import ndimage

from plug_analyzer.analysis.registration import (
    register_translation_baseline,
    subtract_registered_baseline,
)


def test_translation_registration_recovers_shift_and_overlap() -> None:
    rng = np.random.default_rng(4)
    baseline = ndimage.gaussian_filter(rng.normal(size=(12, 24, 28)), 1.0)
    known_shift = (1.0, -2.0, 3.0)
    post = ndimage.shift(
        baseline,
        shift=known_shift,
        order=1,
        mode="constant",
        cval=0.0,
        prefilter=False,
    )
    stable = np.ones(baseline.shape, dtype=np.bool_)

    result = register_translation_baseline(
        post,
        baseline,
        stable,
        spacing_zyx_um=(2.0, 0.5, 0.5),
        upsample_factor=1,
        minimum_overlap_fraction=0.6,
        maximum_residual_nrmse=0.20,
    )

    assert result.accepted
    assert result.shift_zyx_pixels == pytest.approx(known_shift, abs=0.1)
    assert result.shift_zyx_um == pytest.approx((2.0, -1.0, 1.5), abs=0.1)
    corrected = subtract_registered_baseline(post, result)
    assert np.sqrt(np.nanmean(np.square(corrected))) < 1e-6


def test_registration_fails_closed_on_unrelated_baseline() -> None:
    rng = np.random.default_rng(7)
    post = rng.normal(size=(8, 12, 14))
    baseline = rng.normal(size=post.shape)
    stable = np.ones(post.shape, dtype=np.bool_)

    result = register_translation_baseline(
        post,
        baseline,
        stable,
        spacing_zyx_um=(1, 1, 1),
        maximum_residual_nrmse=0.01,
    )

    assert not result.accepted
    with pytest.raises(ValueError, match="fallback"):
        subtract_registered_baseline(post, result)
