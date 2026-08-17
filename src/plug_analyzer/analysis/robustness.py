"""Parameter-robustness helpers for locked deterministic analyses."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class ThresholdVariant:
    """A named deterministic low/high hysteresis threshold pair."""

    name: str
    low_threshold: float
    high_threshold: float
    scale: float


@dataclass(frozen=True, slots=True)
class RobustnessInterval:
    """Observed parameter range, explicitly not a statistical confidence interval."""

    primary: float
    minimum: float
    maximum: float
    absolute_span: float
    maximum_absolute_deviation: float
    maximum_relative_deviation_percent: float | None
    variant_count: int


def threshold_variants(
    low_threshold: float,
    high_threshold: float,
    *,
    relative_variation: float = 0.10,
) -> tuple[ThresholdVariant, ThresholdVariant, ThresholdVariant]:
    """Return locked lower, primary, and upper threshold-sensitivity variants."""

    if not np.isfinite(low_threshold) or not np.isfinite(high_threshold):
        raise ValueError("thresholds must be finite")
    if low_threshold > high_threshold:
        raise ValueError("low_threshold must be less than or equal to high_threshold")
    if not np.isfinite(relative_variation) or not 0.0 <= relative_variation < 1.0:
        raise ValueError("relative_variation must be finite and in [0, 1)")
    scales = (1.0 - relative_variation, 1.0, 1.0 + relative_variation)
    names = ("lower_thresholds", "primary", "upper_thresholds")
    return tuple(
        ThresholdVariant(
            name=name,
            low_threshold=float(low_threshold * scale),
            high_threshold=float(high_threshold * scale),
            scale=float(scale),
        )
        for name, scale in zip(names, scales, strict=True)
    )  # type: ignore[return-value]


def robustness_interval(
    primary: float,
    variant_values: Mapping[str, float] | Iterable[float],
) -> RobustnessInterval:
    """Summarize finite scalar outcomes across predeclared parameter variants."""

    primary_value = float(primary)
    if not np.isfinite(primary_value):
        raise ValueError("primary must be finite")
    if isinstance(variant_values, Mapping):
        raw_values = tuple(float(value) for value in variant_values.values())
    else:
        raw_values = tuple(float(value) for value in variant_values)
    if not raw_values:
        raise ValueError("at least one variant value is required")
    if not all(np.isfinite(value) for value in raw_values):
        raise ValueError("all variant values must be finite")

    values = np.asarray((primary_value, *raw_values), dtype=np.float64)
    minimum = float(np.min(values))
    maximum = float(np.max(values))
    maximum_deviation = float(np.max(np.abs(values - primary_value)))
    relative = 100.0 * maximum_deviation / abs(primary_value) if primary_value != 0.0 else None
    return RobustnessInterval(
        primary=primary_value,
        minimum=minimum,
        maximum=maximum,
        absolute_span=maximum - minimum,
        maximum_absolute_deviation=maximum_deviation,
        maximum_relative_deviation_percent=relative,
        variant_count=len(raw_values),
    )
