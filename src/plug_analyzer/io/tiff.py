"""TIFF, ImageJ TIFF, OME-TIFF, and BigTIFF reader adapter."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import tifffile
import zarr
from numpy.typing import NDArray

from ._util import json_safe, positive_float, selection_bounds, unit_factor_um
from .base import BaseMicroscopeReader
from .errors import SelectionError, SourceReadError
from .models import (
    AxisCalibration,
    CalibrationCandidate,
    CalibrationSource,
    DatasetInfo,
    SceneInfo,
    SourceFormat,
    VolumeSelection,
    VoxelCalibration,
)

_INFO_VALUE = re.compile(r"^\s*([^=\n]+?)\s*=\s*(.*?)\s*$", re.MULTILINE)
_SEQUENCE_AXES = frozenset({"I", "Q"})


def is_tiff_content(path: Path) -> bool:
    """Recognize classic TIFF and BigTIFF byte-order/version signatures."""

    try:
        with path.open("rb") as source:
            header = source.read(4)
    except OSError:
        return False
    return header in {b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+"}


def _rational_float(value: Any) -> float | None:
    if isinstance(value, tuple) and len(value) == 2:
        numerator, denominator = value
        return positive_float(float(numerator) / float(denominator)) if denominator else None
    return positive_float(value)


def _parse_info(info: Any) -> dict[str, str]:
    if not isinstance(info, str):
        return {}
    return {match.group(1).strip(): match.group(2).strip() for match in _INFO_VALUE.finditer(info)}


def _ome_elements(ome_xml: str | None) -> tuple[dict[str, Any], tuple[str, ...]]:
    if not ome_xml:
        return {}, ()
    try:
        root = ET.fromstring(ome_xml)
    except ET.ParseError:
        return {}, ("OME-XML metadata is present but malformed; OME calibration was ignored.",)
    pixels = next((element for element in root.iter() if element.tag.endswith("Pixels")), None)
    if pixels is None:
        return {}, ()
    channels = tuple(
        element.attrib.get("Name") or element.attrib.get("ID") or ""
        for element in pixels
        if element.tag.endswith("Channel")
    )
    values: dict[str, Any] = dict(pixels.attrib)
    values["channel_names"] = channels
    return values, ()


def _format_from_flags(tf: tifffile.TiffFile) -> SourceFormat:
    if tf.is_ome:
        return SourceFormat.OME_TIFF
    if tf.is_imagej:
        return SourceFormat.IMAGEJ_TIFF
    if tf.is_bigtiff:
        return SourceFormat.BIGTIFF
    return SourceFormat.TIFF


def _effective_axes(source_axes: str, shape: tuple[int, ...]) -> tuple[str, tuple[str, ...]]:
    """Map TIFF sequence/sample conventions to analysis dimensions conservatively."""

    axes = list(source_axes.upper())
    warnings: list[str] = []
    if "Z" not in axes:
        candidates = [i for i, axis in enumerate(axes) if axis in _SEQUENCE_AXES]
        if len(candidates) == 1:
            axes[candidates[0]] = "Z"
            warnings.append(
                f"TIFF sequence axis {source_axes[candidates[0]]!r} is interpreted as Z."
            )
    if "C" not in axes and "S" in axes:
        sample_index = axes.index("S")
        axes[sample_index] = "C"
        if shape[sample_index] > 1:
            warnings.append("TIFF sample axis 'S' is exposed as selectable channels.")
    return "".join(axes), tuple(warnings)


def _canonical_shape(
    effective_axes: str, shape: tuple[int, ...]
) -> tuple[tuple[int, int, int, int, int], tuple[str, ...]]:
    warnings: list[str] = []
    dims = dict(zip(effective_axes, shape, strict=True))
    for required in "YX":
        if required not in dims:
            warnings.append(f"Required spatial axis {required} is absent.")
    for axis, size in zip(effective_axes, shape, strict=True):
        if axis not in "TCZYX" and size > 1:
            warnings.append(
                f"Non-singleton TIFF axis {axis!r} ({size}) is unsupported and will not be flattened."
            )
    if len(set(effective_axes)) != len(effective_axes):
        warnings.append(f"Ambiguous duplicate axes in TIFF series: {effective_axes}.")
    return (
        dims.get("T", 1),
        dims.get("C", 1),
        dims.get("Z", 1),
        dims.get("Y", 0),
        dims.get("X", 0),
    ), tuple(warnings)


def _candidate(
    axis: str,
    value: Any,
    unit: str | None,
    source: CalibrationSource,
) -> CalibrationCandidate | None:
    numeric = positive_float(value)
    factor = unit_factor_um(unit)
    if numeric is None or factor is None:
        return None
    return CalibrationCandidate(axis, numeric * factor, source, value, unit or "")


def _select_axis(
    axis: str,
    candidates: list[CalibrationCandidate],
) -> tuple[AxisCalibration, tuple[str, ...]]:
    priority = {
        CalibrationSource.NATIVE: 0,
        CalibrationSource.OME: 1,
        CalibrationSource.IMAGEJ: 2,
        CalibrationSource.TIFF_TAG: 3,
        CalibrationSource.MANUAL: 4,
        CalibrationSource.MISSING: 5,
    }
    ordered = sorted(candidates, key=lambda item: priority[item.source])
    if not ordered:
        return AxisCalibration(axis, None), ()
    selected = ordered[0]
    alternatives = tuple(ordered[1:])
    warnings: list[str] = []
    for other in alternatives:
        relative = abs(other.value_um - selected.value_um) / selected.value_um
        if relative > 0.01:
            warnings.append(
                f"{axis.upper()} calibration conflict: {selected.value_um:g} µm "
                f"({selected.source.value}) versus {other.value_um:g} µm "
                f"({other.source.value}); review is required."
            )
    return (
        AxisCalibration(
            axis,
            selected.value_um,
            selected.source,
            selected.raw_value,
            selected.raw_unit,
            alternatives,
        ),
        tuple(warnings),
    )


def _calibration(
    tf: tifffile.TiffFile,
    imagej: Mapping[str, Any],
    ome: Mapping[str, Any],
) -> VoxelCalibration:
    candidates: dict[str, list[CalibrationCandidate]] = {axis: [] for axis in "xyz"}

    for axis in "XYZ":
        value = ome.get(f"PhysicalSize{axis}")
        unit = ome.get(f"PhysicalSize{axis}Unit", "µm")
        found = _candidate(axis.lower(), value, unit, CalibrationSource.OME)
        if found:
            candidates[axis.lower()].append(found)

    ij_unit = str(imagej.get("unit", "")) or None
    z_candidate = _candidate("z", imagej.get("spacing"), ij_unit, CalibrationSource.IMAGEJ)
    if z_candidate:
        candidates["z"].append(z_candidate)

    if tf.pages:
        page = tf.pages[0]
        resolution_unit_tag = page.tags.get("ResolutionUnit")
        resolution_unit = resolution_unit_tag.value if resolution_unit_tag else None
        tag_units = {2: "inch", 3: "cm"}
        for axis, tag_name in (("x", "XResolution"), ("y", "YResolution")):
            tag = page.tags.get(tag_name)
            pixels_per_unit = _rational_float(tag.value) if tag else None
            physical_unit = ij_unit or tag_units.get(int(resolution_unit or 1))
            if pixels_per_unit and unit_factor_um(physical_unit):
                source = CalibrationSource.IMAGEJ if ij_unit else CalibrationSource.TIFF_TAG
                candidates[axis].append(
                    CalibrationCandidate(
                        axis,
                        unit_factor_um(physical_unit) / pixels_per_unit,  # type: ignore[operator]
                        source,
                        repr(tag.value),
                        physical_unit or "",
                    )
                )

    selected: dict[str, AxisCalibration] = {}
    warnings: list[str] = []
    for axis in "xyz":
        selected[axis], axis_warnings = _select_axis(axis, candidates[axis])
        warnings.extend(axis_warnings)
        if not selected[axis].available:
            warnings.append(
                f"{axis.upper()} calibration is missing; dependent physical-unit metrics are unavailable."
            )
    return VoxelCalibration(selected["x"], selected["y"], selected["z"], tuple(warnings))


class TiffReader(BaseMicroscopeReader):
    """Read supported TIFF-family sources without loading the complete stack."""

    reader_id = "tifffile"

    def _probe(self) -> DatasetInfo:
        try:
            with tifffile.TiffFile(self.path) as tf:
                imagej = dict(tf.imagej_metadata or {})
                ome_values, ome_warnings = _ome_elements(tf.ome_metadata)
                info_values = _parse_info(imagej.get("Info"))
                scenes: list[SceneInfo] = []
                for index, series in enumerate(tf.series):
                    source_shape = tuple(int(item) for item in series.shape)
                    effective_axes, axis_warnings = _effective_axes(series.axes, source_shape)
                    canonical, canonical_warnings = _canonical_shape(effective_axes, source_shape)
                    dtype = np.dtype(series.dtype)
                    significant_bits = int(
                        positive_float(
                            ome_values.get("SignificantBits")
                            or info_values.get("uiBpcSignificant")
                            or info_values.get("BitsPerPixel")
                        )
                        or dtype.itemsize * 8
                    )
                    channel_names = tuple(
                        name for name in ome_values.get("channel_names", ()) if name
                    )
                    if not channel_names:
                        name = info_values.get("Name") or info_values.get("ChannelName")
                        if name:
                            channel_names = (name,)
                    scene_name = series.name or f"Scene {index + 1}"
                    scenes.append(
                        SceneInfo(
                            index=index,
                            name=scene_name,
                            source_axes=series.axes,
                            source_shape=source_shape,
                            canonical_shape_tczyx=canonical,
                            dtype=dtype.str,
                            significant_bits=significant_bits,
                            channel_names=channel_names,
                            warnings=axis_warnings + canonical_warnings,
                        )
                    )

                calibration = _calibration(tf, imagej, ome_values)
                raw_metadata = {
                    "tiff": {
                        "is_imagej": bool(tf.is_imagej),
                        "is_ome": bool(tf.is_ome),
                        "is_bigtiff": bool(tf.is_bigtiff),
                        "byteorder": tf.byteorder,
                        "series": [
                            {
                                "index": i,
                                "name": series.name,
                                "axes": series.axes,
                                "shape": list(series.shape),
                                "dtype": np.dtype(series.dtype).str,
                            }
                            for i, series in enumerate(tf.series)
                        ],
                        "first_page_tags": {
                            tag.name: json_safe(tag.value) for tag in tf.pages[0].tags.values()
                        }
                        if tf.pages
                        else {},
                    },
                    "imagej": json_safe(imagej),
                    "ome_xml": tf.ome_metadata,
                }
                warnings = tuple(ome_warnings) + calibration.warnings
                if not scenes:
                    raise SourceReadError(f"TIFF source has no readable image series: {self.path}")
                return DatasetInfo(
                    path=self.path,
                    reader_id=self.reader_id,
                    source_format=_format_from_flags(tf),
                    scenes=tuple(scenes),
                    calibration=calibration,
                    raw_metadata=raw_metadata,
                    warnings=warnings,
                )
        except SourceReadError:
            raise
        except Exception as exc:
            raise SourceReadError(
                f"TIFF metadata could not be read from {self.path}: {exc}"
            ) from exc

    def _read_region(
        self,
        selection: VolumeSelection,
        region: tuple[slice, slice, slice],
    ) -> NDArray[np.generic]:
        scene = self._scene(selection)
        z_start, _, _ = selection_bounds(scene, selection)
        source_z = slice(z_start + region[0].start, z_start + region[0].stop)
        try:
            with tifffile.TiffFile(self.path) as tf:
                series = tf.series[selection.scene]
                effective_axes, _ = _effective_axes(series.axes, tuple(series.shape))
                indexer: list[int | slice] = []
                remaining_axes: list[str] = []
                for axis, size in zip(effective_axes, series.shape, strict=True):
                    if axis == "T":
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
                    elif int(size) == 1:
                        indexer.append(0)
                    else:
                        raise SelectionError(
                            f"Cannot flatten unsupported TIFF axis {axis!r} with size {size}."
                        )

                store = series.aszarr()
                try:
                    array = zarr.open(store, mode="r")
                    result = np.asarray(array[tuple(indexer)])
                finally:
                    close = getattr(store, "close", None)
                    if close:
                        close()
        except SelectionError:
            raise
        except Exception as exc:
            raise SourceReadError(
                f"TIFF pixel region could not be decoded from {self.path}: {exc}"
            ) from exc

        if "Z" not in remaining_axes:
            result = np.expand_dims(result, axis=0)
            remaining_axes.insert(0, "Z")
        if set(remaining_axes) != set("ZYX") or len(remaining_axes) != 3:
            raise SelectionError(
                f"TIFF series axes {series.axes!r} cannot produce an unambiguous ZYX volume."
            )
        return np.transpose(result, tuple(remaining_axes.index(axis) for axis in "ZYX"))
