"""Automatic scientific quality-control diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from ._validation import BoolArray, FloatArray, IntArray, as_bool_mask, as_zyx_array


@dataclass(frozen=True, slots=True)
class SaturationQC:
    """Saturated-pixel counts/fractions overall, by plane, and inside the plug."""

    threshold: float
    saturated_mask: BoolArray
    saturated_count: int
    valid_count: int
    fraction: float
    count_by_z: IntArray
    valid_count_by_z: IntArray
    fraction_by_z: FloatArray
    plug_saturated_count: int | None
    plug_valid_count: int | None
    plug_fraction: float | None


@dataclass(frozen=True, slots=True)
class BoundaryQC:
    """Mask contact with all six image-volume faces."""

    mask_voxel_count: int
    touches_z_min: bool
    touches_z_max: bool
    touches_y_min: bool
    touches_y_max: bool
    touches_x_min: bool
    touches_x_max: bool
    fraction_on_z_min: float
    fraction_on_z_max: float
    fraction_on_y_min: float
    fraction_on_y_max: float
    fraction_on_x_min: float
    fraction_on_x_max: float

    @property
    def touches_any_boundary(self) -> bool:
        return any(
            (
                self.touches_z_min,
                self.touches_z_max,
                self.touches_y_min,
                self.touches_y_max,
                self.touches_x_min,
                self.touches_x_max,
            )
        )

    @property
    def touches_z_boundary(self) -> bool:
        return self.touches_z_min or self.touches_z_max

    @property
    def touches_xy_boundary(self) -> bool:
        return any(
            (
                self.touches_y_min,
                self.touches_y_max,
                self.touches_x_min,
                self.touches_x_max,
            )
        )


def _safe_fraction(numerator: int, denominator: int) -> float:
    return float(numerator / denominator) if denominator else np.nan


def saturation_qc(
    image: Any,
    *,
    saturation_threshold: float,
    valid_mask: Any | None = None,
    plug_mask: Any | None = None,
) -> SaturationQC:
    """Identify values at/above the meaningful detector saturation threshold."""

    raw = as_zyx_array(image, name="image")
    if not np.issubdtype(raw.dtype, np.number):
        raise TypeError(f"image must contain numeric values; got {raw.dtype}")
    if not np.isfinite(saturation_threshold):
        raise ValueError("saturation_threshold must be finite")
    data = np.asarray(raw, dtype=np.float64)
    valid = np.isfinite(data)
    if valid_mask is not None:
        valid &= as_bool_mask(valid_mask, name="valid_mask", shape=data.shape)
    saturated = valid & (data >= saturation_threshold)
    count_by_z = np.count_nonzero(saturated, axis=(1, 2)).astype(np.int64, copy=False)
    valid_by_z = np.count_nonzero(valid, axis=(1, 2)).astype(np.int64, copy=False)
    fraction_by_z = np.full(data.shape[0], np.nan, dtype=np.float64)
    np.divide(count_by_z, valid_by_z, out=fraction_by_z, where=valid_by_z > 0)
    saturated_count = int(np.sum(count_by_z, dtype=np.int64))
    valid_count = int(np.sum(valid_by_z, dtype=np.int64))

    if plug_mask is None:
        plug_saturated_count = None
        plug_valid_count = None
        plug_fraction = None
    else:
        plug = as_bool_mask(plug_mask, name="plug_mask", shape=data.shape)
        valid_plug = valid & plug
        plug_saturated_count = int(np.count_nonzero(saturated & plug))
        plug_valid_count = int(np.count_nonzero(valid_plug))
        plug_fraction = _safe_fraction(plug_saturated_count, plug_valid_count)

    return SaturationQC(
        threshold=float(saturation_threshold),
        saturated_mask=saturated,
        saturated_count=saturated_count,
        valid_count=valid_count,
        fraction=_safe_fraction(saturated_count, valid_count),
        count_by_z=count_by_z,
        valid_count_by_z=valid_by_z,
        fraction_by_z=fraction_by_z,
        plug_saturated_count=plug_saturated_count,
        plug_valid_count=plug_valid_count,
        plug_fraction=plug_fraction,
    )


def boundary_qc(mask: Any) -> BoundaryQC:
    """Report whether and how much of a mask lies on each volume boundary face."""

    raw = as_zyx_array(mask, name="mask")
    boolean = as_bool_mask(raw, name="mask", shape=raw.shape)
    total = int(np.count_nonzero(boolean))
    faces = (
        boolean[0, :, :],
        boolean[-1, :, :],
        boolean[:, 0, :],
        boolean[:, -1, :],
        boolean[:, :, 0],
        boolean[:, :, -1],
    )
    counts = tuple(int(np.count_nonzero(face)) for face in faces)
    touches = tuple(count > 0 for count in counts)
    fractions = tuple(_safe_fraction(count, total) for count in counts)
    return BoundaryQC(
        mask_voxel_count=total,
        touches_z_min=touches[0],
        touches_z_max=touches[1],
        touches_y_min=touches[2],
        touches_y_max=touches[3],
        touches_x_min=touches[4],
        touches_x_max=touches[5],
        fraction_on_z_min=fractions[0],
        fraction_on_z_max=fractions[1],
        fraction_on_y_min=fractions[2],
        fraction_on_y_max=fractions[3],
        fraction_on_x_min=fractions[4],
        fraction_on_x_max=fractions[5],
    )
