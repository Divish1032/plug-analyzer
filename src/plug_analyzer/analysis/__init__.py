"""Deterministic, physically calibrated scientific analysis primitives."""

from .corrections import (
    BackgroundCorrectionResult,
    InsufficientReferenceError,
    median_background_correct,
    robust_mad_sigma,
)
from .metrics import (
    ApparentLowFluorescenceResult,
    AxialExtent,
    CrossSectionMetrics,
    OpenPathResult,
    PerPlaneMetrics,
    VolumeMetrics,
    apparent_low_fluorescence_fraction,
    axial_extent,
    binned_cross_section_metrics,
    open_path_connectivity,
    per_plane_metrics,
    represented_plane_thicknesses_um,
    resolve_plane_thicknesses_um,
    volume_metrics,
)
from .qc import BoundaryQC, SaturationQC, boundary_qc, saturation_qc
from .robustness import (
    RobustnessInterval,
    ThresholdVariant,
    robustness_interval,
    threshold_variants,
)
from .segmentation import (
    ComponentFilterResult,
    filter_components_by_volume,
    gaussian_filter_physical,
    hysteresis_threshold_3d,
)

__all__ = [
    "ApparentLowFluorescenceResult",
    "AxialExtent",
    "BackgroundCorrectionResult",
    "BoundaryQC",
    "ComponentFilterResult",
    "CrossSectionMetrics",
    "InsufficientReferenceError",
    "OpenPathResult",
    "PerPlaneMetrics",
    "RobustnessInterval",
    "SaturationQC",
    "ThresholdVariant",
    "VolumeMetrics",
    "apparent_low_fluorescence_fraction",
    "axial_extent",
    "binned_cross_section_metrics",
    "boundary_qc",
    "filter_components_by_volume",
    "gaussian_filter_physical",
    "hysteresis_threshold_3d",
    "median_background_correct",
    "open_path_connectivity",
    "per_plane_metrics",
    "represented_plane_thicknesses_um",
    "resolve_plane_thicknesses_um",
    "robust_mad_sigma",
    "robustness_interval",
    "saturation_qc",
    "threshold_variants",
    "volume_metrics",
]
