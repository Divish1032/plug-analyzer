"""Intensity correction and robust background-noise estimation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from ._validation import FloatArray, IntArray, as_bool_mask, as_zyx_array


class InsufficientReferenceError(ValueError):
    """Raised when one or more Z-planes lack the required reference samples."""

    def __init__(self, counts_by_z: IntArray, minimum: int) -> None:
        failed = np.flatnonzero(counts_by_z < minimum).tolist()
        super().__init__(
            f"reference ROI has fewer than {minimum} valid pixels in Z-plane(s) {failed}"
        )
        self.counts_by_z = counts_by_z.copy()
        self.minimum = minimum
        self.failed_planes = tuple(int(index) for index in failed)


@dataclass(frozen=True, slots=True)
class BackgroundCorrectionResult:
    """Per-plane median background correction and its auditable diagnostics."""

    corrected: FloatArray
    offsets_by_z: FloatArray
    reference_counts_by_z: IntArray
    raw_background_sigma: float


def robust_mad_sigma(
    values: Any,
    *,
    mask: Any | None = None,
    scale: float = 1.4826,
) -> float:
    """Estimate Gaussian-equivalent noise as ``scale * median(|x-median(x)|)``.

    Non-finite values are excluded. A provided mask must be boolean and exactly
    match the data shape, which prevents accidental numeric-mask coercion.
    """

    data = np.asarray(values, dtype=np.float64)
    if not np.isfinite(scale) or scale < 0.0:
        raise ValueError("scale must be finite and non-negative")

    selected = np.isfinite(data)
    if mask is not None:
        raw_mask = np.asarray(mask)
        if raw_mask.shape != data.shape:
            raise ValueError(
                f"mask shape {raw_mask.shape} does not match values shape {data.shape}"
            )
        if not np.issubdtype(raw_mask.dtype, np.bool_):
            raise TypeError(f"mask must have boolean dtype; got {raw_mask.dtype}")
        selected &= raw_mask

    samples = data[selected]
    if samples.size == 0:
        raise ValueError("at least one finite selected value is required")
    center = float(np.median(samples))
    mad = float(np.median(np.abs(samples - center)))
    return float(scale * mad)


def median_background_correct(
    image: Any,
    reference_mask: Any,
    *,
    invalid_mask: Any | None = None,
    saturated_mask: Any | None = None,
    min_reference_pixels_per_plane: int = 1,
) -> BackgroundCorrectionResult:
    """Subtract each plane's valid reference-ROI median without clipping negatives.

    Invalid, saturated, and non-finite pixels are excluded from the reference
    estimate. They remain in the returned image (non-finite source values remain
    non-finite), while every finite source value receives the same plane offset.
    No missing plane is interpolated: an undersized plane raises
    :class:`InsufficientReferenceError`.
    """

    source = as_zyx_array(image, name="image")
    if not np.issubdtype(source.dtype, np.number):
        raise TypeError(f"image must contain numeric values; got {source.dtype}")
    shape = source.shape
    reference = as_bool_mask(reference_mask, name="reference_mask", shape=shape)

    if not isinstance(min_reference_pixels_per_plane, int):
        raise TypeError("min_reference_pixels_per_plane must be an integer")
    if min_reference_pixels_per_plane < 1:
        raise ValueError("min_reference_pixels_per_plane must be at least 1")

    excluded = np.zeros(shape, dtype=np.bool_)
    if invalid_mask is not None:
        excluded |= as_bool_mask(invalid_mask, name="invalid_mask", shape=shape)
    if saturated_mask is not None:
        excluded |= as_bool_mask(saturated_mask, name="saturated_mask", shape=shape)

    work = np.asarray(source, dtype=np.float64)
    valid_reference = reference & ~excluded & np.isfinite(work)
    counts = np.count_nonzero(valid_reference, axis=(1, 2)).astype(np.int64, copy=False)
    if np.any(counts < min_reference_pixels_per_plane):
        raise InsufficientReferenceError(counts, min_reference_pixels_per_plane)

    offsets = np.empty(shape[0], dtype=np.float64)
    corrected = np.empty(shape, dtype=np.float64)
    for z_index in range(shape[0]):
        offsets[z_index] = np.median(work[z_index][valid_reference[z_index]])
        corrected[z_index] = work[z_index] - offsets[z_index]

    sigma = robust_mad_sigma(corrected, mask=valid_reference)
    return BackgroundCorrectionResult(
        corrected=corrected,
        offsets_by_z=offsets,
        reference_counts_by_z=counts,
        raw_background_sigma=sigma,
    )
