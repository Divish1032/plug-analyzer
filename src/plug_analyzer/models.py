from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


class CalibrationSource(StrEnum):
    NATIVE = "native"
    OME = "ome"
    IMAGEJ = "imagej"
    MANUAL = "manual"
    MISSING = "missing"


class Availability(StrEnum):
    VALID = "valid"
    WARNING = "valid_with_warning"
    LOWER_BOUND = "lower_bound"
    IMAGED_VOLUME_ONLY = "within_imaged_volume_only"
    UNAVAILABLE = "not_available"


class RunStatus(StrEnum):
    DRAFT = "draft"
    RUNNING = "running"
    CANCELLED = "cancelled"
    FAILED = "failed"
    FINALIZED = "finalized"


class CalibrationValue(BaseModel):
    model_config = ConfigDict(frozen=True)

    value: float | None
    unit: str = "micrometer"
    source: CalibrationSource = CalibrationSource.MISSING
    confirmed: bool = False

    @field_validator("value")
    @classmethod
    def positive_when_present(cls, value: float | None) -> float | None:
        if value is not None and value <= 0:
            raise ValueError("calibration value must be positive")
        return value


class VoxelCalibration(BaseModel):
    model_config = ConfigDict(frozen=True)

    x: CalibrationValue
    y: CalibrationValue
    z: CalibrationValue
    z_positions: tuple[float, ...] = ()

    @model_validator(mode="after")
    def validate_z_positions(self) -> VoxelCalibration:
        if self.z_positions and any(
            right <= left
            for left, right in zip(self.z_positions, self.z_positions[1:], strict=False)
        ):
            raise ValueError("z_positions must be strictly increasing")
        return self

    @property
    def complete(self) -> bool:
        return all(item.value is not None for item in (self.x, self.y, self.z))


class SourceSelection(BaseModel):
    model_config = ConfigDict(frozen=True)

    scene: int = 0
    time: int = 0
    channel: int = 0
    z_start: int = 0
    z_stop: int | None = None

    @field_validator("scene", "time", "channel", "z_start")
    @classmethod
    def non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("selection indices must be non-negative")
        return value

    @model_validator(mode="after")
    def valid_z_range(self) -> SourceSelection:
        if self.z_stop is not None and self.z_stop <= self.z_start:
            raise ValueError("z_stop must be greater than z_start")
        return self


class SourceMetadata(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_path: str
    source_sha256: str
    source_size_bytes: int
    reader_name: str
    reader_version: str
    source_format: str
    original_axes: str
    original_shape: tuple[int, ...]
    selected_shape_zyx: tuple[int, int, int]
    dtype: str
    significant_bits: int | None = None
    selection: SourceSelection = Field(default_factory=SourceSelection)
    calibration: VoxelCalibration
    channel_name: str | None = None
    acquisition: dict[str, Any] = Field(default_factory=dict)
    raw_metadata: dict[str, Any] = Field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    @field_validator("source_size_bytes")
    @classmethod
    def non_negative_size(cls, value: int) -> int:
        if value < 0:
            raise ValueError("source size cannot be negative")
        return value


class ResourcePlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    decoded_bytes: int
    available_memory_bytes: int
    memory_budget_bytes: int
    compute_chunk_bytes: int
    worker_threads: int
    disk_free_bytes: int
    disk_required_bytes: int
    safe_to_start: bool
    warnings: tuple[str, ...] = ()


class ProtocolSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    protocol_id: str
    protocol_version: str
    algorithm_version: str
    parameters: dict[str, Any]


class MetricValue(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    value: float | bool | str | None
    unit: str | None = None
    availability: Availability = Availability.VALID
    qualification: str | None = None


class FinalizedRun(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    sample_id: str
    protocol: ProtocolSnapshot
    metrics: tuple[MetricValue, ...]
    parameters: dict[str, Any] = Field(default_factory=dict)
    qc: dict[str, Any] = Field(default_factory=dict)
    artifacts: dict[str, str] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    finalized_at: datetime = Field(default_factory=utc_now)

    @field_validator("artifacts")
    @classmethod
    def artifacts_are_relative(cls, value: dict[str, str]) -> dict[str, str]:
        for path in value.values():
            if Path(path).is_absolute() or ".." in Path(path).parts:
                raise ValueError("artifact paths must stay relative to the project")
        return value


class SampleAnnotation(BaseModel):
    """Stored context used only by the optional pre-contact baseline calculation."""

    model_config = ConfigDict(frozen=True)

    group: str = ""
    formulation: str = ""
    timepoint: str = ""
    concentration: str = ""
    fluorophore: str = ""
    objective: str = ""
    laser_power: str = ""
    detector_gain: str = ""
    dwell_time: str = ""
    pinhole: str = ""
    averaging: str = ""
    notes: str = ""
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator(
        "group",
        "formulation",
        "timepoint",
        "concentration",
        "fluorophore",
        "objective",
        "laser_power",
        "detector_gain",
        "dwell_time",
        "pinhole",
        "averaging",
        "notes",
    )
    @classmethod
    def trim_text(cls, value: str) -> str:
        return value.strip()
