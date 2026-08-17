"""Typed, format-neutral microscope input models.

The analysis layer receives exactly one canonical ``ZYX`` volume.  Source-specific
dimensions remain visible in :class:`DatasetInfo` and must be selected explicitly.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import numpy as np
from numpy.typing import NDArray


class SourceFormat(StrEnum):
    TIFF = "tiff"
    IMAGEJ_TIFF = "imagej-tiff"
    OME_TIFF = "ome-tiff"
    BIGTIFF = "bigtiff"
    ND2 = "nd2"


class CalibrationSource(StrEnum):
    NATIVE = "native-structured-metadata"
    OME = "ome-metadata"
    IMAGEJ = "imagej-metadata"
    TIFF_TAG = "tiff-resolution-tag"
    MANUAL = "manual"
    MISSING = "missing"


@dataclass(frozen=True, slots=True)
class CalibrationCandidate:
    """One physical sampling value found in source metadata."""

    axis: str
    value_um: float
    source: CalibrationSource
    raw_value: float | str
    raw_unit: str


@dataclass(frozen=True, slots=True)
class AxisCalibration:
    """Selected sampling for one spatial axis, including competing values."""

    axis: str
    value_um: float | None
    source: CalibrationSource = CalibrationSource.MISSING
    raw_value: float | str | None = None
    raw_unit: str | None = None
    alternatives: tuple[CalibrationCandidate, ...] = ()

    @property
    def available(self) -> bool:
        return self.value_um is not None and self.value_um > 0


@dataclass(frozen=True, slots=True)
class VoxelCalibration:
    """Voxel spacing in micrometres, never silently invented."""

    x: AxisCalibration
    y: AxisCalibration
    z: AxisCalibration
    warnings: tuple[str, ...] = ()

    @property
    def xyz_um(self) -> tuple[float | None, float | None, float | None]:
        return self.x.value_um, self.y.value_um, self.z.value_um

    @property
    def complete_xy(self) -> bool:
        return self.x.available and self.y.available

    @property
    def complete_xyz(self) -> bool:
        return self.complete_xy and self.z.available


@dataclass(frozen=True, slots=True)
class SceneInfo:
    """A selectable scene/position normalized to ``TCZYX`` dimensions."""

    index: int
    name: str
    source_axes: str
    source_shape: tuple[int, ...]
    canonical_shape_tczyx: tuple[int, int, int, int, int]
    dtype: str
    significant_bits: int
    channel_names: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def time_count(self) -> int:
        return self.canonical_shape_tczyx[0]

    @property
    def channel_count(self) -> int:
        return self.canonical_shape_tczyx[1]

    @property
    def zyx_shape(self) -> tuple[int, int, int]:
        return self.canonical_shape_tczyx[2:]


@dataclass(frozen=True, slots=True)
class DatasetInfo:
    """Content and metadata probe result for a source file."""

    path: Path
    reader_id: str
    source_format: SourceFormat
    scenes: tuple[SceneInfo, ...]
    calibration: VoxelCalibration
    raw_metadata: Mapping[str, Any] = field(repr=False)
    warnings: tuple[str, ...] = ()

    @property
    def scene_count(self) -> int:
        return len(self.scenes)


@dataclass(frozen=True, slots=True)
class VolumeSelection:
    """One scene, one time point, one channel, and an optional half-open Z range."""

    scene: int = 0
    time: int = 0
    channel: int = 0
    z_start: int = 0
    z_stop: int | None = None


@dataclass(frozen=True, slots=True)
class SourceFingerprint:
    """Full-file SHA-256 identity plus mutation-detection file attributes."""

    algorithm: str
    sha256: str
    size_bytes: int
    mtime_ns: int


@dataclass(frozen=True, slots=True)
class VolumeChunk:
    """One canonical ``ZYX`` region."""

    slices: tuple[slice, slice, slice]
    data: NDArray[np.generic]


@dataclass(frozen=True, slots=True)
class IOProgress:
    """Cooperative progress message emitted by hashing/import/verification."""

    stage: str
    completed: int
    total: int
    message: str = ""

    @property
    def fraction(self) -> float:
        return 1.0 if self.total <= 0 else min(1.0, self.completed / self.total)


ProgressCallback = Callable[[IOProgress], None]
CancelCallback = Callable[[], bool]


@runtime_checkable
class MicroscopeReader(Protocol):
    """Reader adapter contract consumed by import and analysis code."""

    path: Path
    reader_id: str

    def probe(self) -> DatasetInfo:
        """Read dimensions and metadata without decoding the complete volume."""

    def selected_shape(self, selection: VolumeSelection) -> tuple[int, int, int]:
        """Return the selected canonical ``ZYX`` shape after validation."""

    def read_region(
        self,
        selection: VolumeSelection,
        region: tuple[slice, slice, slice],
    ) -> NDArray[np.generic]:
        """Decode only a selected canonical ``ZYX`` region."""

    def iter_chunks(
        self,
        selection: VolumeSelection,
        chunk_shape: tuple[int, int, int],
    ) -> Iterator[VolumeChunk]:
        """Decode a selected volume lazily in bounded canonical chunks."""


def model_to_dict(value: Any) -> Any:
    """Convert nested I/O dataclasses/enums/paths to JSON-compatible values."""

    if hasattr(value, "__dataclass_fields__"):
        return model_to_dict(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): model_to_dict(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [model_to_dict(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, np.generic):
        return value.item()
    return value
