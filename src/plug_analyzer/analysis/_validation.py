"""Shared validation helpers for deterministic ZYX analysis."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
from numpy.typing import NDArray

BoolArray = NDArray[np.bool_]
FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]


def as_zyx_array(array: Any, *, name: str) -> NDArray[Any]:
    """Return *array* as a non-empty three-dimensional NumPy array."""

    result = np.asarray(array)
    if result.ndim != 3:
        raise ValueError(f"{name} must be a 3D ZYX array; got shape {result.shape}")
    if any(size == 0 for size in result.shape):
        raise ValueError(f"{name} must not contain an empty dimension; got shape {result.shape}")
    return result


def as_bool_mask(mask: Any, *, name: str, shape: tuple[int, int, int]) -> BoolArray:
    """Validate a boolean mask without silently treating numeric data as a mask."""

    result = as_zyx_array(mask, name=name)
    if result.shape != shape:
        raise ValueError(f"{name} shape {result.shape} does not match expected shape {shape}")
    if not np.issubdtype(result.dtype, np.bool_):
        raise TypeError(f"{name} must have boolean dtype; got {result.dtype}")
    return np.asarray(result, dtype=np.bool_)


def validate_spacing_zyx(spacing_zyx_um: Sequence[float]) -> tuple[float, float, float]:
    """Validate physical voxel-center spacing ordered as Z, Y, X."""

    if len(spacing_zyx_um) != 3:
        raise ValueError("spacing_zyx_um must contain exactly (s_z, s_y, s_x)")
    spacing = tuple(float(value) for value in spacing_zyx_um)
    if not all(np.isfinite(value) and value > 0.0 for value in spacing):
        raise ValueError(f"all spacing values must be finite and positive; got {spacing}")
    return spacing  # type: ignore[return-value]


def validate_vector_zyx(vector: Sequence[float], *, name: str) -> FloatArray:
    """Return a finite length-three physical-coordinate vector."""

    result = np.asarray(vector, dtype=np.float64)
    if result.shape != (3,) or not np.all(np.isfinite(result)):
        raise ValueError(f"{name} must contain exactly three finite ZYX values")
    return result


def normalized_axis_zyx(axis_zyx: Sequence[float]) -> FloatArray:
    """Validate and normalize a ZYX direction vector."""

    axis = validate_vector_zyx(axis_zyx, name="axis_zyx")
    norm = float(np.linalg.norm(axis))
    if norm <= np.finfo(np.float64).eps:
        raise ValueError("axis_zyx must have non-zero length")
    return axis / norm


def connectivity_structure(connectivity: int) -> BoolArray:
    """Return a 3D centrosymmetric structure for 6- or 26-neighbour connectivity."""

    from scipy import ndimage

    if connectivity == 6:
        return np.asarray(ndimage.generate_binary_structure(3, 1), dtype=np.bool_)
    if connectivity == 26:
        return np.asarray(ndimage.generate_binary_structure(3, 3), dtype=np.bool_)
    raise ValueError("connectivity must be 6 or 26")
