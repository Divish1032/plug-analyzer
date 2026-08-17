"""Automatic, auditable compatibility rules for saved-run comparisons."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import numpy as np

from plug_analyzer.models import FinalizedRun, SourceMetadata


class CompatibilitySeverity(StrEnum):
    BLOCKER = "blocker"
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class CompatibilityIssue:
    field: str
    severity: CompatibilitySeverity
    scope: str
    message: str
    left: str = ""
    right: str = ""


@dataclass(frozen=True, slots=True)
class ComparisonCompatibility:
    issues: tuple[CompatibilityIssue, ...]

    @property
    def morphology_compatible(self) -> bool:
        return not any(
            issue.severity is CompatibilitySeverity.BLOCKER and issue.scope == "all"
            for issue in self.issues
        )

    @property
    def intensity_compatible(self) -> bool:
        return self.morphology_compatible and not any(
            issue.severity is CompatibilitySeverity.BLOCKER and issue.scope in {"all", "intensity"}
            for issue in self.issues
        )

    @property
    def summary(self) -> str:
        blockers = [item.message for item in self.issues if item.severity == "blocker"]
        warnings = [item.message for item in self.issues if item.severity == "warning"]
        if blockers:
            return "Some values cannot be compared: " + "; ".join(dict.fromkeys(blockers))
        if warnings:
            return "The runs can be compared, but review: " + "; ".join(dict.fromkeys(warnings))
        return "The runs use the same method, calibration, and image channel."

    def metric_allowed(self, metric_name: str) -> bool:
        if not self.morphology_compatible:
            return False
        return self.intensity_compatible or not is_intensity_metric(metric_name)


INTENSITY_METRIC_TOKENS = ("intensity", "fluorescence", "saturation")

CONFIGURATION_KEYS = (
    "filter_sigma_um",
    "low_noise_multiplier",
    "high_noise_multiplier",
    "minimum_component_volume_um3",
    "min_reference_pixels_per_plane",
    "component_connectivity",
    "cross_section_bin_width_um",
    "robustness_mode",
    "threshold_variation",
    "correction_path",
)


def is_intensity_metric(metric_name: str) -> bool:
    lowered = metric_name.casefold()
    return any(token in lowered for token in INTENSITY_METRIC_TOKENS)


def _display(value: Any) -> str:
    if value is None:
        return "missing"
    return str(value)


def _same_value(left: Any, right: Any) -> bool:
    if (
        isinstance(left, (int, float))
        and not isinstance(left, bool)
        and isinstance(right, (int, float))
        and not isinstance(right, bool)
    ):
        return bool(np.isclose(float(left), float(right), rtol=1e-9, atol=1e-12))
    if isinstance(left, (tuple, list)) and isinstance(right, (tuple, list)):
        return len(left) == len(right) and all(
            _same_value(a, b) for a, b in zip(left, right, strict=True)
        )
    return left == right


def _add_mismatch(
    issues: list[CompatibilityIssue],
    *,
    field: str,
    left: Any,
    right: Any,
    scope: str,
    message: str,
    severity: CompatibilitySeverity = CompatibilitySeverity.WARNING,
) -> None:
    if not _same_value(left, right):
        issues.append(
            CompatibilityIssue(
                field=field,
                severity=severity,
                scope=scope,
                message=message,
                left=_display(left),
                right=_display(right),
            )
        )


def assess_run_compatibility(
    left: FinalizedRun,
    right: FinalizedRun,
    *,
    left_source: SourceMetadata,
    right_source: SourceMetadata,
) -> ComparisonCompatibility:
    """Return clear warnings and the few metric-specific blockers for two app runs."""

    issues: list[CompatibilityIssue] = []
    _add_mismatch(
        issues,
        field="protocol_id",
        left=left.protocol.protocol_id,
        right=right.protocol.protocol_id,
        scope="all",
        message="the analysis method differs",
    )
    _add_mismatch(
        issues,
        field="protocol_version",
        left=left.protocol.protocol_version,
        right=right.protocol.protocol_version,
        scope="all",
        message="the method version differs",
    )
    _add_mismatch(
        issues,
        field="algorithm_version",
        left=left.protocol.algorithm_version,
        right=right.protocol.algorithm_version,
        scope="all",
        message="the app analysis version differs",
    )
    for key in CONFIGURATION_KEYS:
        _add_mismatch(
            issues,
            field=f"parameter.{key}",
            left=left.protocol.parameters.get(key),
            right=right.protocol.parameters.get(key),
            scope="all",
            message="one or more analysis settings differ",
        )

    for axis in ("x", "y", "z"):
        left_value = getattr(left_source.calibration, axis).value
        right_value = getattr(right_source.calibration, axis).value
        _add_mismatch(
            issues,
            field=f"calibration.{axis}",
            left=left_value,
            right=right_value,
            scope="all",
            message="voxel calibration differs",
        )

    _add_mismatch(
        issues,
        field="channel_name",
        left=(left_source.channel_name or "").casefold(),
        right=(right_source.channel_name or "").casefold(),
        scope="intensity",
        message="image channels differ, so intensity change is not shown",
        severity=CompatibilitySeverity.BLOCKER,
    )

    left_roi = left.parameters.get("reviewed_geometry")
    right_roi = right.parameters.get("reviewed_geometry")
    if left_roi is None or right_roi is None:
        issues.append(
            CompatibilityIssue(
                field="reviewed_geometry",
                severity=CompatibilitySeverity.WARNING,
                scope="all",
                message="one or both older runs do not include the saved analysis region",
            )
        )
    else:
        _add_mismatch(
            issues,
            field="reviewed_geometry",
            left=left_roi,
            right=right_roi,
            scope="all",
            message="the analysis regions differ",
        )

    return ComparisonCompatibility(tuple(issues))
