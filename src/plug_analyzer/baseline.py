"""Bounded-memory registered pre-contact subtraction for cached ZYX volumes."""

from __future__ import annotations

import math
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import zarr
from numpy.typing import NDArray
from scipy import ndimage

from plug_analyzer.analysis.qc import SaturationQC
from plug_analyzer.analysis.registration import (
    TranslationRegistration,
    register_translation_baseline,
)


def _normalized_key(
    key: Any, shape: tuple[int, int, int]
) -> tuple[tuple[int | slice, int | slice, int | slice], tuple[int, ...]]:
    items = list(key if isinstance(key, tuple) else (key,))
    if items.count(Ellipsis) > 1:
        raise IndexError("only one ellipsis is supported")
    if Ellipsis in items:
        index = items.index(Ellipsis)
        items[index : index + 1] = [slice(None)] * (3 - (len(items) - 1))
    items.extend([slice(None)] * (3 - len(items)))
    if len(items) != 3:
        raise IndexError("registered volumes require Z/Y/X indexing")
    scalar_axes: list[int] = []
    normalized: list[int | slice] = []
    for axis, item in enumerate(items):
        if isinstance(item, int):
            value = item if item >= 0 else shape[axis] + item
            if not 0 <= value < shape[axis]:
                raise IndexError(f"index {item} is out of bounds for axis {axis}")
            normalized.append(value)
            scalar_axes.append(axis)
        elif isinstance(item, slice):
            normalized.append(item)
        else:
            raise IndexError("registered volumes support only integer and slice indexing")
    return tuple(normalized), tuple(scalar_axes)  # type: ignore[return-value]


class RegisteredDifferenceVolume:
    """Lazy ``post - shifted baseline`` view that materializes only requested chunks."""

    dtype = np.dtype(np.float64)
    ndim = 3

    def __init__(self, post: Any, baseline: Any, shift_zyx_pixels: tuple[float, float, float]):
        self.post = post
        self.baseline = baseline
        self.shape = tuple(int(value) for value in post.shape)
        if self.shape != tuple(int(value) for value in baseline.shape) or len(self.shape) != 3:
            raise ValueError("post and baseline caches must use the same ZYX grid")
        self.shift_zyx_pixels = tuple(float(value) for value in shift_zyx_pixels)

    def __array__(self, dtype: Any = None, copy: Any = None) -> NDArray[np.float64]:
        array = self[:, :, :]
        if dtype is not None:
            array = array.astype(dtype, copy=False)
        return np.array(array, copy=bool(copy)) if copy else array

    def __getitem__(self, key: Any) -> NDArray[np.float64]:
        normalized, scalar_axes = _normalized_key(key, self.shape)
        coordinates: list[NDArray[np.float64]] = []
        for axis, item in enumerate(normalized):
            if isinstance(item, int):
                coordinates.append(np.asarray([item], dtype=np.float64))
            else:
                start, stop, step = item.indices(self.shape[axis])
                coordinates.append(np.arange(start, stop, step, dtype=np.float64))
        output_shape = tuple(len(values) for values in coordinates)
        if any(length == 0 for length in output_shape):
            result = np.empty(output_shape, dtype=np.float64)
        else:
            input_coordinates = [
                values - shift
                for values, shift in zip(coordinates, self.shift_zyx_pixels, strict=True)
            ]
            bounds: list[tuple[int, int]] = []
            for axis, values in enumerate(input_coordinates):
                lower = max(0, math.floor(float(np.min(values))) - 1)
                upper = min(self.shape[axis], math.ceil(float(np.max(values))) + 2)
                bounds.append((lower, upper))
            baseline_block = np.asarray(
                self.baseline[
                    bounds[0][0] : bounds[0][1],
                    bounds[1][0] : bounds[1][1],
                    bounds[2][0] : bounds[2][1],
                ],
                dtype=np.float64,
            )
            mesh = np.meshgrid(
                *(values - bounds[axis][0] for axis, values in enumerate(input_coordinates)),
                indexing="ij",
            )
            registered = ndimage.map_coordinates(
                baseline_block,
                mesh,
                order=1,
                mode="constant",
                cval=np.nan,
                prefilter=False,
            )
            post_block = np.asarray(self.post[normalized], dtype=np.float64)
            if scalar_axes:
                post_block = np.expand_dims(post_block, axis=scalar_axes)
            result = post_block - registered
        if scalar_axes:
            result = np.squeeze(result, axis=scalar_axes)
        return result


@dataclass(frozen=True, slots=True)
class PreparedBaseline:
    difference: RegisteredDifferenceVolume
    registration: TranslationRegistration
    sampling_stride_zyx: tuple[int, int, int]


def prepare_registered_baseline(
    post: Any,
    baseline: Any,
    stable_reference_mask: Any,
    *,
    spacing_zyx_um: tuple[float, float, float],
    maximum_sample_voxels: int = 2_000_000,
    minimum_overlap_fraction: float = 0.80,
    maximum_residual_nrmse: float = 0.25,
) -> PreparedBaseline:
    """Estimate registration on a bounded decimation, then expose exact-grid lazy subtraction."""

    shape = tuple(int(value) for value in post.shape)
    if shape != tuple(int(value) for value in baseline.shape) or len(shape) != 3:
        raise ValueError("post and baseline caches must have the same ZYX shape")
    if maximum_sample_voxels < 32:
        raise ValueError("maximum_sample_voxels must be at least 32")
    scale = max(1, math.ceil((int(np.prod(shape)) / maximum_sample_voxels) ** (1 / 3)))
    stride = (scale, scale, scale)
    slices = tuple(slice(None, None, item) for item in stride)
    post_sample = np.asarray(post[slices])
    baseline_sample = np.asarray(baseline[slices])
    stable_sample = np.asarray(stable_reference_mask[slices], dtype=np.bool_)
    sampled_spacing = tuple(
        spacing * item for spacing, item in zip(spacing_zyx_um, stride, strict=True)
    )
    sampled = register_translation_baseline(
        post_sample,
        baseline_sample,
        stable_sample,
        spacing_zyx_um=sampled_spacing,
        minimum_overlap_fraction=minimum_overlap_fraction,
        maximum_residual_nrmse=maximum_residual_nrmse,
    )
    full_shift = tuple(
        value * item for value, item in zip(sampled.shift_zyx_pixels, stride, strict=True)
    )
    registration = TranslationRegistration(
        shift_zyx_pixels=full_shift,
        shift_zyx_um=tuple(
            value * spacing for value, spacing in zip(full_shift, spacing_zyx_um, strict=True)
        ),
        phase_error=sampled.phase_error,
        overlap_fraction=sampled.overlap_fraction,
        residual_nrmse=sampled.residual_nrmse,
        accepted=sampled.accepted,
        reason=sampled.reason,
        registered_baseline=sampled.registered_baseline,
        overlap_mask=sampled.overlap_mask,
    )
    return PreparedBaseline(
        difference=RegisteredDifferenceVolume(post, baseline, full_shift),
        registration=registration,
        sampling_stride_zyx=stride,
    )


def saturation_qc_bounded(
    image: Any,
    plug_mask: Any,
    *,
    saturation_threshold: float,
    workspace_directory: str | Path,
    z_chunk: int = 4,
) -> SaturationQC:
    """Preserve raw-post saturation QC for a baseline-subtracted large analysis."""

    shape = tuple(int(value) for value in image.shape)
    workspace = Path(workspace_directory).expanduser().resolve()
    destination = workspace / "raw-post-saturated-mask.zarr"
    if destination.exists():
        shutil.rmtree(destination)
    saturated_mask = zarr.open_array(
        str(destination),
        mode="w",
        shape=shape,
        chunks=(min(z_chunk, shape[0]), min(512, shape[1]), min(512, shape[2])),
        dtype="bool",
    )
    count_by_z = np.zeros(shape[0], dtype=np.int64)
    valid_by_z = np.zeros(shape[0], dtype=np.int64)
    plug_saturated = 0
    plug_valid = 0
    for start in range(0, shape[0], z_chunk):
        stop = min(shape[0], start + z_chunk)
        raw = np.asarray(image[start:stop], dtype=np.float64)
        plug = np.asarray(plug_mask[start:stop], dtype=np.bool_)
        valid = np.isfinite(raw)
        saturated = valid & (raw >= saturation_threshold)
        saturated_mask[start:stop] = saturated
        count_by_z[start:stop] = np.count_nonzero(saturated, axis=(1, 2))
        valid_by_z[start:stop] = np.count_nonzero(valid, axis=(1, 2))
        plug_saturated += int(np.count_nonzero(saturated & plug))
        plug_valid += int(np.count_nonzero(valid & plug))
    fraction_by_z = np.full(shape[0], np.nan, dtype=np.float64)
    np.divide(count_by_z, valid_by_z, out=fraction_by_z, where=valid_by_z > 0)
    saturated_total = int(np.sum(count_by_z))
    valid_total = int(np.sum(valid_by_z))
    return SaturationQC(
        threshold=float(saturation_threshold),
        saturated_mask=saturated_mask,  # type: ignore[arg-type]
        saturated_count=saturated_total,
        valid_count=valid_total,
        fraction=float(saturated_total / valid_total) if valid_total else float("nan"),
        count_by_z=count_by_z,
        valid_count_by_z=valid_by_z,
        fraction_by_z=fraction_by_z,
        plug_saturated_count=plug_saturated,
        plug_valid_count=plug_valid,
        plug_fraction=float(plug_saturated / plug_valid) if plug_valid else float("nan"),
    )
