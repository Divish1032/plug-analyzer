"""Small, dependency-light view models used at the desktop UI boundary.

The scientific engine and persistence layer intentionally do not depend on Qt.  A
controller can translate their domain objects into these immutable records before
calling :class:`plug_analyzer.ui.MainWindow` methods.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class NoticeLevel(StrEnum):
    """Visual severity for a notice shown by the desktop shell."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    SUCCESS = "success"


@dataclass(frozen=True, slots=True)
class AppState:
    """Top-level state that controls navigation and enabled actions."""

    project_path: Path | None = None
    source_path: Path | None = None
    project_open: bool = False
    source_ready: bool = False
    analysis_running: bool = False
    results_ready: bool = False
    project_read_only: bool = False
    status: str = "Ready"


@dataclass(frozen=True, slots=True)
class SourceSummary:
    """Human-readable source metadata for the import page."""

    filename: str
    source_format: str = "Unknown"
    dimensions_zyx: tuple[int, int, int] | None = None
    dtype: str = "Unknown"
    channel: str = "Channel 1"
    calibration_xyz_um: tuple[float | None, float | None, float | None] = (
        None,
        None,
        None,
    )
    calibration_source: str = "Not confirmed"
    reader: str = ""
    warnings: tuple[str, ...] = ()
    extra: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PreflightSummary:
    """Resource estimate shown before an analysis starts."""

    safe_to_start: bool
    available_memory_bytes: int
    memory_budget_bytes: int
    disk_free_bytes: int
    disk_required_bytes: int
    compute_chunk_bytes: int
    worker_threads: int
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MetricDisplay:
    """One result metric with its scientific qualification."""

    name: str
    value: float | int | bool | str | None
    unit: str = ""
    availability: str = "valid"
    qualification: str = ""


@dataclass(frozen=True, slots=True)
class PlaneSeries:
    """Per-Z measurements used by the two result charts."""

    z_um: Sequence[float]
    area_um2: Sequence[float]
    integrated_intensity: Sequence[float]


@dataclass(frozen=True, slots=True)
class CrossSectionSeries:
    position_um: Sequence[float]
    occlusion_percent: Sequence[float]
    open_area_um2: Sequence[float]


@dataclass(frozen=True, slots=True)
class AnalysisResultDisplay:
    """Complete display payload for one finalized or preview analysis."""

    sample_name: str
    run_id: str
    metrics: Sequence[MetricDisplay]
    planes: PlaneSeries | None = None
    cross_sections: CrossSectionSeries | None = None
    protocol_label: str = "Deterministic protocol"
    qc_summary: str = ""
    finalized: bool = False


@dataclass(frozen=True, slots=True)
class StorageSummary:
    """Visible local project storage usage."""

    project_path: Path
    source_bytes: int = 0
    cache_bytes: int = 0
    result_bytes: int = 0
    other_bytes: int = 0

    @property
    def total_bytes(self) -> int:
        return self.source_bytes + self.cache_bytes + self.result_bytes + self.other_bytes


@dataclass(frozen=True, slots=True)
class ChoiceDisplay:
    """Stable identifier and human label for samples and immutable runs."""

    identifier: str
    label: str


@dataclass(frozen=True, slots=True)
class SavedMetricComparisonDisplay:
    """Aligned scalar metric from two saved runs, potentially from different samples."""

    metric_name: str
    left_value: float | int | bool | str | None
    right_value: float | int | bool | str | None
    unit: str = ""
    difference: float | None = None
    qualification: str = ""


METRIC_LABELS = {
    "observed_volume_um3": "Observed plug volume",
    "maximum_plane_area_um2": "Maximum plug area",
    "summed_corrected_integrated_intensity_au": "Corrected integrated intensity",
    "fluorescence_volume_integral_au_um3": "Fluorescence volume integral",
    "maximum_occlusion_percent": "Maximum occlusion",
    "minimum_open_area_um2": "Minimum open area",
    "open_path_connected_6": "Open path detected",
    "bottleneck_diameter_um": "Bottleneck diameter",
    "apparent_low_fluorescence_percent": "Apparent low-fluorescence fraction",
}


def metric_label(name: str) -> str:
    """Return a plain-language label for a stored metric name."""

    return METRIC_LABELS.get(name, name.replace("_", " ").strip().capitalize())
