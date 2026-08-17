"""Fail-closed translation-only registration for eligible pre-contact stacks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy import ndimage
from skimage.registration import phase_cross_correlation

from ._validation import as_bool_mask, as_zyx_array, validate_spacing_zyx

FloatArray = NDArray[np.float64]
BoolArray = NDArray[np.bool_]


@dataclass(frozen=True, slots=True)
class TranslationRegistration:
    shift_zyx_pixels: tuple[float, float, float]
    shift_zyx_um: tuple[float, float, float]
    phase_error: float
    overlap_fraction: float
    residual_nrmse: float
    accepted: bool
    reason: str
    registered_baseline: FloatArray
    overlap_mask: BoolArray


def register_translation_baseline(
    post_image: Any,
    baseline_image: Any,
    stable_reference_mask: Any,
    *,
    spacing_zyx_um: tuple[float, float, float],
    upsample_factor: int = 10,
    minimum_overlap_fraction: float = 0.80,
    maximum_residual_nrmse: float = 0.25,
) -> TranslationRegistration:
    """Estimate a 3D translation and resample only the baseline onto the post grid.

    Registration uses the supplied stable reference region.  Pixels outside the
    shared overlap become NaN and are excluded.  Acceptance combines overlap and
    a post-registration normalized RMSE; a caller must still obtain visual SME
    approval and confirm matching acquisition settings.
    """

    post_raw = as_zyx_array(post_image, name="post_image")
    base_raw = as_zyx_array(baseline_image, name="baseline_image")
    if post_raw.shape != base_raw.shape:
        raise ValueError("post and baseline images must use the same fixed ZYX grid")
    if not np.issubdtype(post_raw.dtype, np.number) or not np.issubdtype(base_raw.dtype, np.number):
        raise TypeError("post and baseline images must be numeric")
    spacing = validate_spacing_zyx(spacing_zyx_um)
    reference = as_bool_mask(
        stable_reference_mask,
        name="stable_reference_mask",
        shape=post_raw.shape,
    )
    post = np.asarray(post_raw, dtype=np.float64)
    baseline = np.asarray(base_raw, dtype=np.float64)
    finite_reference = reference & np.isfinite(post) & np.isfinite(baseline)
    if np.count_nonzero(finite_reference) < 32:
        raise ValueError("stable reference mask must contain at least 32 finite voxels")
    if upsample_factor < 1:
        raise ValueError("upsample_factor must be positive")
    if not 0 < minimum_overlap_fraction <= 1:
        raise ValueError("minimum_overlap_fraction must be in (0, 1]")
    if maximum_residual_nrmse <= 0:
        raise ValueError("maximum_residual_nrmse must be positive")

    # A zero-valued exterior confines phase correlation to the reviewed stable
    # region without letting the growing plug drive the transform.
    reference_image = np.where(finite_reference, post, 0.0)
    moving_image = np.where(finite_reference, baseline, 0.0)
    shift, phase_error, _ = phase_cross_correlation(
        reference_image,
        moving_image,
        upsample_factor=upsample_factor,
        normalization="phase",
    )
    registered = ndimage.shift(
        baseline,
        shift=shift,
        order=1,
        mode="constant",
        cval=np.nan,
        prefilter=False,
    )
    original_valid = np.isfinite(baseline).astype(np.float64)
    overlap_weight = ndimage.shift(
        original_valid,
        shift=shift,
        order=0,
        mode="constant",
        cval=0.0,
        prefilter=False,
    )
    overlap = (overlap_weight >= 0.5) & np.isfinite(post) & np.isfinite(registered)
    overlap_fraction = float(np.count_nonzero(overlap) / overlap.size)
    residual_region = reference & overlap
    if not np.any(residual_region):
        residual_nrmse = float("inf")
    else:
        difference = post[residual_region] - registered[residual_region]
        dynamic = float(np.ptp(post[residual_region]))
        if dynamic <= np.finfo(np.float64).eps:
            dynamic = max(float(np.std(post[residual_region])), 1.0)
        residual_nrmse = float(np.sqrt(np.mean(np.square(difference))) / dynamic)
    accepted = (
        overlap_fraction >= minimum_overlap_fraction and residual_nrmse <= maximum_residual_nrmse
    )
    reasons: list[str] = []
    if overlap_fraction < minimum_overlap_fraction:
        reasons.append("shared overlap is below the required fraction")
    if residual_nrmse > maximum_residual_nrmse:
        reasons.append("stable-region residual error exceeds the limit")
    reason = (
        "Automatic QC passed; visual approval and matching acquisition settings are still required."
        if accepted
        else "; ".join(reasons)
    )
    registered[~overlap] = np.nan
    return TranslationRegistration(
        shift_zyx_pixels=tuple(float(value) for value in shift),
        shift_zyx_um=tuple(float(value * step) for value, step in zip(shift, spacing, strict=True)),
        phase_error=float(phase_error),
        overlap_fraction=overlap_fraction,
        residual_nrmse=residual_nrmse,
        accepted=accepted,
        reason=reason,
        registered_baseline=registered,
        overlap_mask=overlap,
    )


def subtract_registered_baseline(
    post_image: Any,
    registration: TranslationRegistration,
) -> FloatArray:
    """Subtract only an accepted registered baseline on the valid shared grid."""

    if not registration.accepted:
        raise ValueError("registration QC was not accepted; use reviewed background fallback")
    post = np.asarray(as_zyx_array(post_image, name="post_image"), dtype=np.float64)
    if post.shape != registration.registered_baseline.shape:
        raise ValueError("post image shape does not match the registration grid")
    result = np.full(post.shape, np.nan, dtype=np.float64)
    result[registration.overlap_mask] = (
        post[registration.overlap_mask]
        - registration.registered_baseline[registration.overlap_mask]
    )
    return result
