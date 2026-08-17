from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import zarr
from scipy import ndimage

from plug_analyzer.baseline import (
    RegisteredDifferenceVolume,
    prepare_registered_baseline,
    saturation_qc_bounded,
)


def test_registered_difference_matches_scipy_whole_volume_and_chunks() -> None:
    rng = np.random.default_rng(31)
    baseline = rng.normal(size=(9, 17, 19))
    shift = (1.0, -2.0, 0.5)
    registered = ndimage.shift(
        baseline,
        shift=shift,
        order=1,
        mode="constant",
        cval=np.nan,
        prefilter=False,
    )
    post = registered + 7.0
    lazy = RegisteredDifferenceVolume(post, baseline, shift)
    expected = post - registered
    np.testing.assert_allclose(lazy[:, :, :], expected, equal_nan=True)
    np.testing.assert_allclose(lazy[2:7, 3:12, 5:16], expected[2:7, 3:12, 5:16], equal_nan=True)


def test_bounded_registration_recovers_full_grid_shift() -> None:
    rng = np.random.default_rng(42)
    baseline = ndimage.gaussian_filter(rng.normal(size=(16, 32, 40)), 1.0)
    shift = (2.0, -2.0, 4.0)
    post = ndimage.shift(
        baseline,
        shift=shift,
        order=1,
        mode="constant",
        cval=0.0,
        prefilter=False,
    )
    stable = np.ones(baseline.shape, dtype=bool)
    result = prepare_registered_baseline(
        post,
        baseline,
        stable,
        spacing_zyx_um=(1, 1, 1),
        maximum_sample_voxels=3_000,
        minimum_overlap_fraction=0.5,
    )
    assert result.registration.accepted
    assert result.registration.shift_zyx_pixels == pytest.approx(shift, abs=0.35)


def test_raw_saturation_qc_streams_to_workspace(tmp_path: Path) -> None:
    raw = np.zeros((5, 7, 9), dtype=np.uint16)
    raw[2, 3, 4] = 4095
    plug = np.ones_like(raw, dtype=bool)
    result = saturation_qc_bounded(
        raw,
        plug,
        saturation_threshold=4095,
        workspace_directory=tmp_path,
        z_chunk=2,
    )
    assert result.saturated_count == 1
    assert result.plug_saturated_count == 1
    mask = zarr.open_array(str(tmp_path / "raw-post-saturated-mask.zarr"), mode="r")
    assert bool(mask[2, 3, 4])
