"""Private helpers shared by microscope reader adapters."""

from __future__ import annotations

import math
from collections.abc import Iterator, Mapping
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import numpy as np

from .errors import SelectionError
from .models import SceneInfo, VolumeSelection

UNIT_TO_UM: dict[str, float] = {
    "um": 1.0,
    "µm": 1.0,
    "micron": 1.0,
    "microns": 1.0,
    "micrometer": 1.0,
    "micrometers": 1.0,
    "nm": 1e-3,
    "nanometer": 1e-3,
    "nanometers": 1e-3,
    "mm": 1e3,
    "millimeter": 1e3,
    "millimeters": 1e3,
    "cm": 1e4,
    "centimeter": 1e4,
    "centimeters": 1e4,
    "m": 1e6,
    "meter": 1e6,
    "meters": 1e6,
    "inch": 25_400.0,
    "in": 25_400.0,
}


def unit_factor_um(unit: str | None) -> float | None:
    if not unit:
        return None
    normalized = unit.strip().lower().replace("μ", "µ")
    return UNIT_TO_UM.get(normalized)


def positive_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) and parsed > 0 else None


def json_safe(value: Any, *, max_depth: int = 24, _depth: int = 0) -> Any:
    """Preserve vendor metadata in JSON-safe form without failing on odd objects."""

    if _depth >= max_depth:
        return repr(value)
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else repr(value)
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, (Path, Enum)):
        return str(value.value if isinstance(value, Enum) else value)
    if is_dataclass(value) and not isinstance(value, type):
        return json_safe(asdict(value), max_depth=max_depth, _depth=_depth + 1)
    if hasattr(value, "_asdict"):
        return json_safe(value._asdict(), max_depth=max_depth, _depth=_depth + 1)
    if isinstance(value, Mapping):
        return {
            str(key): json_safe(item, max_depth=max_depth, _depth=_depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, (tuple, list, set)):
        return [json_safe(item, max_depth=max_depth, _depth=_depth + 1) for item in value]
    if isinstance(value, np.ndarray):
        # Metadata arrays should be small.  Avoid ever embedding pixel payloads by accident.
        if value.size <= 10_000:
            return value.tolist()
        return {"dtype": value.dtype.str, "shape": list(value.shape), "omitted": True}
    if hasattr(value, "__dict__"):
        return json_safe(vars(value), max_depth=max_depth, _depth=_depth + 1)
    return repr(value)


def selection_bounds(
    scene: SceneInfo, selection: VolumeSelection
) -> tuple[int, int, tuple[int, int, int]]:
    if selection.scene != scene.index:
        raise SelectionError(
            f"Scene {selection.scene} does not match the selected scene descriptor {scene.index}."
        )
    if not 0 <= selection.time < scene.time_count:
        raise SelectionError(f"Time index {selection.time} is outside 0..{scene.time_count - 1}.")
    if not 0 <= selection.channel < scene.channel_count:
        raise SelectionError(
            f"Channel index {selection.channel} is outside 0..{scene.channel_count - 1}."
        )
    total_z, height, width = scene.zyx_shape
    z_start = selection.z_start
    z_stop = total_z if selection.z_stop is None else selection.z_stop
    if not 0 <= z_start < z_stop <= total_z:
        raise SelectionError(
            f"Z range [{z_start}, {z_stop}) is invalid for a {total_z}-plane scene."
        )
    return z_start, z_stop, (z_stop - z_start, height, width)


def normalize_region(
    region: tuple[slice, slice, slice], shape: tuple[int, int, int]
) -> tuple[slice, slice, slice]:
    if len(region) != 3:
        raise SelectionError("A canonical region must contain exactly Z, Y, and X slices.")
    normalized: list[slice] = []
    for axis, (item, length) in enumerate(zip(region, shape, strict=True)):
        if not isinstance(item, slice):
            raise SelectionError(
                "Region indices must be slices so output remains three-dimensional."
            )
        start, stop, step = item.indices(length)
        if step != 1:
            raise SelectionError(f"Region stride on ZYX axis {axis} must be 1, not {step}.")
        if stop < start:
            stop = start
        normalized.append(slice(start, stop, 1))
    return tuple(normalized)  # type: ignore[return-value]


def chunk_slices(
    shape: tuple[int, int, int], chunks: tuple[int, int, int]
) -> Iterator[tuple[slice, slice, slice]]:
    if any(size <= 0 for size in chunks):
        raise ValueError("Chunk dimensions must all be positive.")
    for z0 in range(0, shape[0], chunks[0]):
        for y0 in range(0, shape[1], chunks[1]):
            for x0 in range(0, shape[2], chunks[2]):
                yield (
                    slice(z0, min(shape[0], z0 + chunks[0])),
                    slice(y0, min(shape[1], y0 + chunks[1])),
                    slice(x0, min(shape[2], x0 + chunks[2])),
                )


def slice_key(region: tuple[slice, slice, slice]) -> str:
    return ",".join(f"{item.start}:{item.stop}" for item in region)
