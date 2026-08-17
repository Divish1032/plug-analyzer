"""Deterministic, physically parameterized 3D plug segmentation primitives."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from ._validation import (
    BoolArray,
    FloatArray,
    IntArray,
    as_bool_mask,
    as_zyx_array,
    connectivity_structure,
    validate_spacing_zyx,
)
from .metrics import resolve_plane_thicknesses_um


@dataclass(frozen=True, slots=True)
class ComponentFilterResult:
    """A physically filtered mask plus component-level audit information."""

    mask: BoolArray
    component_volumes_um3: FloatArray
    kept_component_labels: IntArray
    removed_component_count: int

    @property
    def retained_component_count(self) -> int:
        return int(self.kept_component_labels.size)


def _physical_sigma_pixels(
    sigma_um: float | Sequence[float],
    spacing_zyx_um: Sequence[float],
) -> tuple[float, float, float]:
    spacing = validate_spacing_zyx(spacing_zyx_um)
    if np.isscalar(sigma_um):
        physical = (float(sigma_um),) * 3
    else:
        if len(sigma_um) != 3:
            raise ValueError("sigma_um must be a scalar or exactly (sigma_z, sigma_y, sigma_x)")
        physical = tuple(float(value) for value in sigma_um)
    if not all(np.isfinite(value) and value >= 0.0 for value in physical):
        raise ValueError(f"sigma_um values must be finite and non-negative; got {physical}")
    return tuple(value / step for value, step in zip(physical, spacing, strict=True))  # type: ignore[return-value]


def gaussian_filter_physical(
    image: Any,
    *,
    spacing_zyx_um: Sequence[float],
    sigma_um: float | Sequence[float],
    valid_mask: Any | None = None,
    mode: str = "reflect",
    truncate: float = 4.0,
) -> FloatArray:
    """Create a segmentation-only Gaussian-filtered copy using physical widths.

    If invalid pixels exist, normalized convolution prevents them from spreading
    NaNs or acting like zero-valued signal. Invalid output locations remain NaN.
    The returned array is always floating point and never aliases the input.
    """

    from scipy import ndimage

    raw = as_zyx_array(image, name="image")
    if not np.issubdtype(raw.dtype, np.number):
        raise TypeError(f"image must contain numeric values; got {raw.dtype}")
    data = np.asarray(raw, dtype=np.float64)
    sigma_pixels = _physical_sigma_pixels(sigma_um, spacing_zyx_um)
    if not np.isfinite(truncate) or truncate <= 0.0:
        raise ValueError("truncate must be finite and positive")

    valid = np.isfinite(data)
    if valid_mask is not None:
        valid &= as_bool_mask(valid_mask, name="valid_mask", shape=data.shape)
    if not np.any(valid):
        raise ValueError("at least one finite valid image voxel is required")

    if all(value == 0.0 for value in sigma_pixels):
        result = data.copy()
        result[~valid] = np.nan
        return result

    if np.all(valid):
        return np.asarray(
            ndimage.gaussian_filter(
                data,
                sigma=sigma_pixels,
                mode=mode,
                truncate=truncate,
            ),
            dtype=np.float64,
        )

    numerator = ndimage.gaussian_filter(
        np.where(valid, data, 0.0),
        sigma=sigma_pixels,
        mode=mode,
        truncate=truncate,
    )
    denominator = ndimage.gaussian_filter(
        valid.astype(np.float64),
        sigma=sigma_pixels,
        mode=mode,
        truncate=truncate,
    )
    result = np.full(data.shape, np.nan, dtype=np.float64)
    np.divide(numerator, denominator, out=result, where=denominator > 0.0)
    result[~valid] = np.nan
    return result


def hysteresis_threshold_3d(
    filtered_image: Any,
    *,
    low_threshold: float,
    high_threshold: float,
    analysis_mask: Any | None = None,
    connectivity: int = 6,
) -> BoolArray:
    """Retain low-threshold candidates connected in 3D to a high-threshold seed."""

    from scipy import ndimage

    raw = as_zyx_array(filtered_image, name="filtered_image")
    if not np.issubdtype(raw.dtype, np.number):
        raise TypeError(f"filtered_image must contain numeric values; got {raw.dtype}")
    if not np.isfinite(low_threshold) or not np.isfinite(high_threshold):
        raise ValueError("thresholds must be finite")
    if low_threshold > high_threshold:
        raise ValueError("low_threshold must be less than or equal to high_threshold")

    data = np.asarray(raw, dtype=np.float64)
    allowed = np.isfinite(data)
    if analysis_mask is not None:
        allowed &= as_bool_mask(analysis_mask, name="analysis_mask", shape=data.shape)

    candidate = allowed & (data >= low_threshold)
    seeds = candidate & (data >= high_threshold)
    if not np.any(seeds):
        return np.zeros(data.shape, dtype=np.bool_)

    structure = connectivity_structure(connectivity)
    return np.asarray(
        ndimage.binary_propagation(seeds, structure=structure, mask=candidate),
        dtype=np.bool_,
    )


def filter_components_by_volume(
    mask: Any,
    *,
    spacing_zyx_um: Sequence[float],
    min_component_volume_um3: float,
    z_positions_um: Sequence[float] | None = None,
    connectivity: int = 6,
) -> ComponentFilterResult:
    """Remove components smaller than a physical volume using 3D connectivity."""

    from scipy import ndimage

    raw = as_zyx_array(mask, name="mask")
    boolean = as_bool_mask(raw, name="mask", shape=raw.shape)
    spacing = validate_spacing_zyx(spacing_zyx_um)
    if not np.isfinite(min_component_volume_um3) or min_component_volume_um3 < 0.0:
        raise ValueError("min_component_volume_um3 must be finite and non-negative")

    labels, component_count = ndimage.label(
        boolean,
        structure=connectivity_structure(connectivity),
    )
    if component_count == 0:
        return ComponentFilterResult(
            mask=np.zeros(boolean.shape, dtype=np.bool_),
            component_volumes_um3=np.empty(0, dtype=np.float64),
            kept_component_labels=np.empty(0, dtype=np.int64),
            removed_component_count=0,
        )

    thicknesses = resolve_plane_thicknesses_um(
        boolean.shape[0],
        spacing_z_um=spacing[0],
        z_positions_um=z_positions_um,
    )
    pixel_area = spacing[1] * spacing[2]
    volumes_with_background = np.zeros(component_count + 1, dtype=np.float64)
    for z_index, thickness in enumerate(thicknesses):
        plane_counts = np.bincount(
            labels[z_index].ravel(),
            minlength=component_count + 1,
        )
        volumes_with_background += plane_counts * pixel_area * thickness

    component_volumes = volumes_with_background[1:]
    keep_flags = component_volumes >= min_component_volume_um3
    kept_labels = np.flatnonzero(keep_flags).astype(np.int64) + 1
    lookup = np.zeros(component_count + 1, dtype=np.bool_)
    lookup[kept_labels] = True
    filtered = lookup[labels]
    return ComponentFilterResult(
        mask=np.asarray(filtered, dtype=np.bool_),
        component_volumes_um3=component_volumes,
        kept_component_labels=kept_labels,
        removed_component_count=int(component_count - kept_labels.size),
    )
