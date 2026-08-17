"""Nikon ND2 reader adapter with fail-closed compatibility diagnostics."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import nd2
import numpy as np
from numpy.typing import NDArray

from ._util import json_safe, positive_float, selection_bounds
from .base import BaseMicroscopeReader
from .errors import SelectionError, SourceReadError, UnsupportedFormatError
from .models import (
    AxisCalibration,
    CalibrationSource,
    DatasetInfo,
    SceneInfo,
    SourceFormat,
    VolumeSelection,
    VoxelCalibration,
)


def is_nd2_content(path: Path) -> bool:
    try:
        return bool(nd2.is_supported_file(path))
    except (OSError, ValueError):
        return False


def nd2_compatibility_report(path: Path, reason: str) -> str:
    try:
        with path.open("rb") as source:
            signature = source.read(16).hex(" ")
    except OSError:
        signature = "unavailable"
    try:
        legacy = bool(nd2.is_legacy(path))
    except (OSError, ValueError):
        legacy = False
    return "\n".join(
        (
            "Plug Analyzer ND2 compatibility report",
            f"File: {path.name}",
            f"Size: {path.stat().st_size if path.exists() else 'unavailable'} bytes",
            f"Header (first 16 bytes): {signature}",
            f"nd2 library version: {getattr(nd2, '__version__', 'unknown')}",
            f"Legacy signature detected: {legacy}",
            f"Reason: {reason}",
            "The file was not reinterpreted or converted.",
            "Fallback: export from NIS-Elements as OME-TIFF at original bit depth, "
            "or provide a lossless original-bit-depth TIFF plus the acquisition-properties report.",
        )
    )


def _channel_names(metadata: Any) -> tuple[str, ...]:
    channels = metadata.get("channels") if isinstance(metadata, Mapping) else None
    if channels is None:
        channels = getattr(metadata, "channels", None)
    names: list[str] = []
    for item in channels or ():
        channel = (
            item.get("channel") if isinstance(item, Mapping) else getattr(item, "channel", None)
        )
        name = (
            channel.get("name") if isinstance(channel, Mapping) else getattr(channel, "name", None)
        )
        if name:
            names.append(str(name))
    return tuple(names)


def _position_names(experiment: Any, count: int) -> tuple[str, ...]:
    names: list[str] = []
    for loop in experiment or ():
        loop_type = loop.get("type") if isinstance(loop, Mapping) else getattr(loop, "type", None)
        if loop_type != "XYPosLoop":
            continue
        parameters = (
            loop.get("parameters")
            if isinstance(loop, Mapping)
            else getattr(loop, "parameters", None)
        )
        points = (
            parameters.get("points")
            if isinstance(parameters, Mapping)
            else getattr(parameters, "points", None)
        )
        for index, point in enumerate(points or ()):
            name = point.get("name") if isinstance(point, Mapping) else getattr(point, "name", None)
            names.append(str(name or f"Position {index + 1}"))
    if len(names) != count:
        return tuple(f"Position {index + 1}" for index in range(count))
    return tuple(names)


def _axis_calibration(axis: str, value: Any, *, present: bool = True) -> AxisCalibration:
    parsed = positive_float(value) if present else None
    if parsed is None:
        return AxisCalibration(axis, None)
    return AxisCalibration(
        axis=axis,
        value_um=parsed,
        source=CalibrationSource.NATIVE,
        raw_value=parsed,
        raw_unit="µm",
    )


class ND2Reader(BaseMicroscopeReader):
    """Read modern or legacy Nikon ND2 through the pure-Python ``nd2`` package."""

    reader_id = "nd2"

    def _open(self) -> nd2.ND2File:
        # Fail closed: ``validate_frames=True`` may rescue shifted frame offsets,
        # which would silently reinterpret a damaged acquisition.
        return nd2.ND2File(self.path, validate_frames=False)

    def _probe(self) -> DatasetInfo:
        if not is_nd2_content(self.path):
            reason = "The file header is not recognized by the installed Nikon ND2 reader."
            raise UnsupportedFormatError(
                self.path,
                reason,
                compatibility_report=nd2_compatibility_report(self.path, reason),
            )
        try:
            with self._open() as source:
                sizes = {str(axis): int(size) for axis, size in source.sizes.items()}
                scene_count = sizes.get("P", 1)
                time_count = sizes.get("T", 1)
                channel_count = sizes.get("C", 1)
                z_count = sizes.get("Z", 1)
                height = sizes.get("Y", 0)
                width = sizes.get("X", 0)
                source_axes = "".join(sizes)
                source_shape = tuple(sizes.values())
                warnings: list[str] = []
                unsupported = [
                    f"{axis}={size}"
                    for axis, size in sizes.items()
                    if axis not in "PTCZYX" and size > 1
                ]
                if unsupported:
                    warnings.append(
                        "Unsupported ND2 dimensions will not be flattened: "
                        + ", ".join(unsupported)
                    )
                if sizes.get("S", 1) > 1:
                    warnings.append(
                        "RGB/component ND2 data is not a single quantitative fluorescence channel."
                    )
                if not height or not width:
                    warnings.append("Required ND2 X/Y spatial dimensions are missing.")

                metadata = source.metadata
                experiment = source.experiment
                names = _position_names(experiment, scene_count)
                channels = _channel_names(metadata)
                attrs = source.attributes
                dtype = np.dtype(source.dtype)
                significant_bits = int(
                    positive_float(getattr(attrs, "bitsPerComponentSignificant", None))
                    or dtype.itemsize * 8
                )
                scenes = tuple(
                    SceneInfo(
                        index=index,
                        name=names[index],
                        source_axes=source_axes,
                        source_shape=source_shape,
                        canonical_shape_tczyx=(
                            time_count,
                            channel_count,
                            z_count,
                            height,
                            width,
                        ),
                        dtype=dtype.str,
                        significant_bits=significant_bits,
                        channel_names=channels,
                        warnings=tuple(warnings),
                    )
                    for index in range(scene_count)
                )

                voxel = source.voxel_size(channel=0)
                calibration = VoxelCalibration(
                    _axis_calibration("x", voxel.x),
                    _axis_calibration("y", voxel.y),
                    _axis_calibration("z", voxel.z, present="Z" in sizes),
                )
                calibration_warnings = tuple(
                    f"{axis.axis.upper()} calibration is missing; dependent physical-unit metrics are unavailable."
                    for axis in (calibration.x, calibration.y, calibration.z)
                    if not axis.available
                )
                calibration = VoxelCalibration(
                    calibration.x, calibration.y, calibration.z, calibration_warnings
                )

                raw_warnings: list[str] = []
                try:
                    unstructured = source.unstructured_metadata(strip_prefix=False)
                except Exception as exc:  # vendor metadata varies substantially
                    unstructured = None
                    raw_warnings.append(
                        f"Some unstructured ND2 metadata could not be decoded: {type(exc).__name__}: {exc}"
                    )
                raw_metadata = {
                    "attributes": json_safe(attrs),
                    "metadata": json_safe(metadata),
                    "experiment": json_safe(experiment),
                    "text_info": json_safe(source.text_info),
                    "unstructured": json_safe(unstructured),
                    "is_legacy": bool(nd2.is_legacy(self.path)),
                }
                return DatasetInfo(
                    path=self.path,
                    reader_id=self.reader_id,
                    source_format=SourceFormat.ND2,
                    scenes=scenes,
                    calibration=calibration,
                    raw_metadata=raw_metadata,
                    warnings=tuple(warnings) + calibration_warnings + tuple(raw_warnings),
                )
        except UnsupportedFormatError:
            raise
        except Exception as exc:
            reason = f"ND2 metadata or frame validation failed: {type(exc).__name__}: {exc}"
            raise SourceReadError(nd2_compatibility_report(self.path, reason)) from exc

    def _read_region(
        self,
        selection: VolumeSelection,
        region: tuple[slice, slice, slice],
    ) -> NDArray[np.generic]:
        scene = self._scene(selection)
        if scene.warnings and any("Unsupported ND2 dimensions" in item for item in scene.warnings):
            raise SelectionError("This ND2 contains unsupported non-singleton dimensions.")
        z_start, _, _ = selection_bounds(scene, selection)
        source_z = slice(z_start + region[0].start, z_start + region[0].stop)
        try:
            with self._open() as source:
                axes = tuple(str(axis) for axis in source.sizes)
                indexer: list[int | slice] = []
                remaining_axes: list[str] = []
                for axis in axes:
                    if axis == "P":
                        indexer.append(selection.scene)
                    elif axis == "T":
                        indexer.append(selection.time)
                    elif axis == "C":
                        indexer.append(selection.channel)
                    elif axis == "Z":
                        indexer.append(source_z)
                        remaining_axes.append("Z")
                    elif axis == "Y":
                        indexer.append(region[1])
                        remaining_axes.append("Y")
                    elif axis == "X":
                        indexer.append(region[2])
                        remaining_axes.append("X")
                    elif source.sizes[axis] == 1:
                        indexer.append(0)
                    else:
                        raise SelectionError(
                            f"Cannot flatten unsupported ND2 axis {axis!r} with size {source.sizes[axis]}."
                        )
                lazy = source.to_dask(wrapper=True, copy=True)
                result = np.asarray(lazy[tuple(indexer)].compute(scheduler="synchronous"))
        except SelectionError:
            raise
        except Exception as exc:
            raise SourceReadError(
                f"ND2 pixel region could not be decoded from {self.path}: {type(exc).__name__}: {exc}"
            ) from exc

        if "Z" not in remaining_axes:
            result = np.expand_dims(result, axis=0)
            remaining_axes.insert(0, "Z")
        if set(remaining_axes) != set("ZYX") or len(remaining_axes) != 3:
            raise SelectionError(
                f"ND2 axes {''.join(axes)!r} cannot produce an unambiguous ZYX volume."
            )
        return np.transpose(result, tuple(remaining_axes.index(axis) for axis in "ZYX"))
