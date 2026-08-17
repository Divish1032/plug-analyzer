"""Auditable end-to-end deterministic analysis pipeline.

The low-level functions in :mod:`plug_analyzer.analysis` deliberately do one
scientific operation each.  This module fixes their order, records every
parameter, and attaches availability/qualification language to the outputs.
It does not infer a physical lumen or a true material porosity from one
fluorescence channel.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, is_dataclass
from enum import StrEnum
from typing import Any
from uuid import uuid4

import numpy as np
from numpy.typing import NDArray

from plug_analyzer import __version__
from plug_analyzer.analysis import (
    ApparentLowFluorescenceResult,
    AxialExtent,
    BoundaryQC,
    CrossSectionMetrics,
    OpenPathResult,
    PerPlaneMetrics,
    RobustnessInterval,
    SaturationQC,
    VolumeMetrics,
    apparent_low_fluorescence_fraction,
    axial_extent,
    binned_cross_section_metrics,
    boundary_qc,
    filter_components_by_volume,
    gaussian_filter_physical,
    hysteresis_threshold_3d,
    median_background_correct,
    open_path_connectivity,
    per_plane_metrics,
    robust_mad_sigma,
    robustness_interval,
    saturation_qc,
    threshold_variants,
    volume_metrics,
)
from plug_analyzer.analysis.clearance import BottleneckClearance, widest_open_path_clearance
from plug_analyzer.models import (
    Availability,
    FinalizedRun,
    MetricValue,
    ProtocolSnapshot,
)

BoolArray = NDArray[np.bool_]
FloatArray = NDArray[np.float64]
ProgressCallback = Callable[[str, float, str], None]
CancelCallback = Callable[[], bool]


class AnalysisCancelled(RuntimeError):
    """Raised at a safe stage boundary after a cooperative cancel request."""


class RobustnessMode(StrEnum):
    OFF = "off"
    STANDARD = "standard"


@dataclass(frozen=True, slots=True)
class RectangularRoi:
    """Half-open Y/X rectangle, repeated through every selected Z-plane."""

    y_start: int
    y_stop: int
    x_start: int
    x_stop: int

    @classmethod
    def full(cls, shape_zyx: Sequence[int]) -> RectangularRoi:
        _, height, width = (int(value) for value in shape_zyx)
        return cls(0, height, 0, width)

    def validate(self, shape_zyx: Sequence[int], *, name: str = "ROI") -> None:
        if len(shape_zyx) != 3:
            raise ValueError("shape_zyx must contain exactly Z, Y, and X")
        _, height, width = (int(value) for value in shape_zyx)
        if not (0 <= self.y_start < self.y_stop <= height):
            raise ValueError(f"{name} Y bounds must be inside [0, {height}]")
        if not (0 <= self.x_start < self.x_stop <= width):
            raise ValueError(f"{name} X bounds must be inside [0, {width}]")

    def mask(self, shape_zyx: Sequence[int]) -> BoolArray:
        self.validate(shape_zyx)
        result = np.zeros(tuple(int(value) for value in shape_zyx), dtype=np.bool_)
        result[:, self.y_start : self.y_stop, self.x_start : self.x_stop] = True
        return result


@dataclass(frozen=True, slots=True)
class PipelineMasks:
    """Reviewed geometry supplied to the deterministic measurement pipeline.

    Rectangles are useful for the prototype, while arbitrary reviewed 3D masks
    can be supplied without changing the scientific engine.
    """

    background: BoolArray
    analysis: BoolArray
    lumen: BoolArray
    envelope: BoolArray | None = None
    geometry_source: str = "reviewed-mask"

    def validated(self, shape: tuple[int, int, int]) -> PipelineMasks:
        converted: dict[str, BoolArray | None] = {}
        for name in ("background", "analysis", "lumen", "envelope"):
            raw = getattr(self, name)
            if raw is None:
                converted[name] = None
                continue
            array = np.asarray(raw)
            if array.shape != shape:
                raise ValueError(f"{name} mask shape {array.shape} does not match {shape}")
            if not np.issubdtype(array.dtype, np.bool_):
                raise TypeError(f"{name} mask must use boolean dtype")
            converted[name] = np.asarray(array, dtype=np.bool_)
        background = converted["background"]
        analysis = converted["analysis"]
        lumen = converted["lumen"]
        assert background is not None and analysis is not None and lumen is not None
        if not np.any(background):
            raise ValueError("background mask is empty")
        if not np.any(analysis):
            raise ValueError("analysis mask is empty")
        if not np.any(lumen):
            raise ValueError("lumen mask is empty")
        if np.any(analysis & ~lumen):
            raise ValueError("analysis mask must be contained inside the lumen mask")
        envelope = converted["envelope"]
        if envelope is not None and np.any(envelope & ~lumen):
            raise ValueError("envelope mask must be contained inside the lumen mask")
        return PipelineMasks(
            background=background,
            analysis=analysis,
            lumen=lumen,
            envelope=envelope,
            geometry_source=self.geometry_source,
        )


@dataclass(frozen=True, slots=True)
class PipelineConfig:
    """Candidate protocol parameters; all physical distances use micrometres."""

    spacing_zyx_um: tuple[float, float, float]
    filter_sigma_um: float = 0.75
    low_noise_multiplier: float = 2.0
    high_noise_multiplier: float = 4.0
    minimum_component_volume_um3: float = 5.0
    min_reference_pixels_per_plane: int = 1_000
    component_connectivity: int = 6
    saturation_threshold: float = 4_095.0
    axis_zyx: tuple[float, float, float] = (0.0, 0.0, 1.0)
    reference_point_zyx_um: tuple[float, float, float] = (0.0, 0.0, 0.0)
    cross_section_bin_width_um: float | None = None
    z_positions_um: tuple[float, ...] = ()
    robustness_mode: RobustnessMode = RobustnessMode.STANDARD
    threshold_variation: float = 0.10
    protocol_id: str = "candidate-hysteresis-3d"
    protocol_version: str = "candidate-v1-unlocked"

    def validate(self, z_count: int) -> None:
        if len(self.spacing_zyx_um) != 3 or not all(
            np.isfinite(value) and value > 0 for value in self.spacing_zyx_um
        ):
            raise ValueError("spacing_zyx_um must contain three positive finite values")
        if not np.isfinite(self.filter_sigma_um) or self.filter_sigma_um < 0:
            raise ValueError("filter_sigma_um must be finite and non-negative")
        if not 0 <= self.low_noise_multiplier <= self.high_noise_multiplier:
            raise ValueError("noise multipliers must satisfy 0 <= low <= high")
        if self.min_reference_pixels_per_plane < 1:
            raise ValueError("min_reference_pixels_per_plane must be positive")
        if self.component_connectivity not in (6, 26):
            raise ValueError("component_connectivity must be 6 or 26")
        if not np.isfinite(self.saturation_threshold):
            raise ValueError("saturation_threshold must be finite")
        if self.z_positions_um and len(self.z_positions_um) != z_count:
            raise ValueError("z_positions_um must contain one position per selected plane")
        if not 0 <= self.threshold_variation < 1:
            raise ValueError("threshold_variation must be in [0, 1)")


@dataclass(frozen=True, slots=True)
class PipelineResult:
    """Complete result, including the reviewed overlay arrays and audit record."""

    corrected: FloatArray
    filtered: FloatArray
    plug_mask: BoolArray
    uncertainty_mask: BoolArray
    thresholds: tuple[float, float]
    raw_background_sigma: float
    filtered_background_sigma: float
    background_offsets_by_z: FloatArray
    per_plane: PerPlaneMetrics
    volume: VolumeMetrics
    axial: AxialExtent
    cross_section: CrossSectionMetrics
    open_path: OpenPathResult
    bottleneck_clearance: BottleneckClearance
    apparent_low_fluorescence: ApparentLowFluorescenceResult | None
    saturation: SaturationQC
    boundary: BoundaryQC
    robustness: Mapping[str, RobustnessInterval]
    variant_metrics: Mapping[str, Mapping[str, float]]
    parameters: Mapping[str, Any]
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def scalar_metrics(self) -> dict[str, float | bool | None]:
        apparent = self.apparent_low_fluorescence
        return {
            "observed_volume_um3": self.volume.observed_volume_um3,
            "fluorescence_volume_integral_au_um3": (
                self.volume.fluorescence_volume_integral_au_um3
            ),
            "maximum_plane_area_um2": float(np.max(self.per_plane.area_um2)),
            "summed_corrected_integrated_intensity_au": float(
                np.sum(self.per_plane.corrected_integrated_intensity_au)
            ),
            "axial_maximum_um": self.axial.q_max_um,
            "axial_q95_um": self.axial.q95_um,
            "maximum_occlusion_percent": self.cross_section.maximum_occlusion_percent,
            "mean_occlusion_percent": self.cross_section.mean_occlusion_percent,
            "minimum_open_area_um2": self.cross_section.minimum_open_area_um2,
            "open_path_connected_6": self.open_path.connected_6,
            "open_path_connected_26": self.open_path.connected_26,
            "bottleneck_diameter_um": self.bottleneck_clearance.bottleneck_diameter_um,
            "apparent_low_fluorescence_percent": apparent.percent if apparent else None,
            "saturated_pixel_percent": 100.0 * self.saturation.fraction,
        }

    def summary_dict(self) -> dict[str, Any]:
        payload = {
            "schema_version": 1,
            "algorithm_version": __version__,
            "metrics": self.scalar_metrics(),
            "per_plane": {
                "z_index": list(range(self.per_plane.area_um2.size)),
                "area_um2": self.per_plane.area_um2.tolist(),
                "corrected_integrated_intensity_au": (
                    self.per_plane.corrected_integrated_intensity_au.tolist()
                ),
                "fluorescence_area_integral_au_um2": (
                    self.per_plane.fluorescence_area_integral_au_um2.tolist()
                ),
                "mean_corrected_intensity_au": self.per_plane.mean_corrected_intensity_au.tolist(),
            },
            "cross_section": {
                "position_um": self.cross_section.bin_centers_um.tolist(),
                "plug_area_um2": self.cross_section.plug_area_um2.tolist(),
                "lumen_area_um2": self.cross_section.lumen_area_um2.tolist(),
                "occlusion_percent": self.cross_section.occlusion_percent.tolist(),
                "open_area_um2": self.cross_section.open_area_um2.tolist(),
            },
            "thresholds": {
                "low": self.thresholds[0],
                "high": self.thresholds[1],
                "raw_background_sigma": self.raw_background_sigma,
                "filtered_background_sigma": self.filtered_background_sigma,
            },
            "qc": {
                "saturation": _jsonable(self.saturation, omit=("saturated_mask",)),
                "boundary": _jsonable(self.boundary),
                "warnings": list(self.warnings),
            },
            "robustness": {name: _jsonable(value) for name, value in self.robustness.items()},
            "variant_metrics": _jsonable(self.variant_metrics),
            "parameters": _jsonable(self.parameters),
        }
        return _jsonable(payload)

    def to_finalized_run(
        self,
        *,
        sample_id: str,
        artifacts: Mapping[str, str],
        run_id: str | None = None,
    ) -> FinalizedRun:
        boundary_qualification = (
            "Mask touches an image boundary; value is observed within the captured region."
            if self.boundary.touches_any_boundary
            else None
        )
        volume_availability = (
            Availability.LOWER_BOUND if self.boundary.touches_any_boundary else Availability.VALID
        )
        apparent = self.apparent_low_fluorescence
        metrics = (
            MetricValue(
                name="observed_volume_um3",
                value=self.volume.observed_volume_um3,
                unit="µm³",
                availability=volume_availability,
                qualification=boundary_qualification,
            ),
            MetricValue(
                name="maximum_plane_area_um2",
                value=float(np.max(self.per_plane.area_um2)),
                unit="µm²",
                availability=volume_availability,
                qualification="Maximum fluorescence-defined plug area among captured Z planes.",
            ),
            MetricValue(
                name="summed_corrected_integrated_intensity_au",
                value=float(np.sum(self.per_plane.corrected_integrated_intensity_au)),
                unit="summed corrected AU",
                availability=Availability.WARNING,
                qualification="Relative fluorescence; compare only matched acquisitions.",
            ),
            MetricValue(
                name="fluorescence_volume_integral_au_um3",
                value=self.volume.fluorescence_volume_integral_au_um3,
                unit="corrected AU·µm³",
                availability=Availability.WARNING,
                qualification="Relative fluorescence; not automatically a material amount.",
            ),
            MetricValue(
                name="axial_q95_um",
                value=self.axial.q95_um,
                unit="µm",
                availability=volume_availability,
                qualification=boundary_qualification,
            ),
            MetricValue(
                name="maximum_occlusion_percent",
                value=self.cross_section.maximum_occlusion_percent,
                unit="%",
                availability=Availability.IMAGED_VOLUME_ONLY,
                qualification="Uses the supplied lumen geometry within the imaged volume only.",
            ),
            MetricValue(
                name="minimum_open_area_um2",
                value=self.cross_section.minimum_open_area_um2,
                unit="µm²",
                availability=Availability.IMAGED_VOLUME_ONLY,
                qualification="Uses the supplied lumen geometry within the imaged volume only.",
            ),
            MetricValue(
                name="open_path_connected_6",
                value=self.open_path.connected_6,
                unit=None,
                availability=Availability.IMAGED_VOLUME_ONLY,
                qualification="Image-resolved connectivity is not a flow or pressure measurement.",
            ),
            MetricValue(
                name="bottleneck_diameter_um",
                value=self.bottleneck_clearance.bottleneck_diameter_um,
                unit="µm" if self.bottleneck_clearance.connected else None,
                availability=(
                    Availability.IMAGED_VOLUME_ONLY
                    if self.bottleneck_clearance.connected
                    else Availability.UNAVAILABLE
                ),
                qualification=self.bottleneck_clearance.qualification,
            ),
            MetricValue(
                name="apparent_low_fluorescence_percent",
                value=apparent.percent if apparent else None,
                unit="%" if apparent else None,
                availability=(Availability.WARNING if apparent else Availability.UNAVAILABLE),
                qualification=(
                    "Single-channel apparent low-fluorescence fraction; not true porosity."
                    if apparent
                    else "No reviewed plug-envelope mask was supplied."
                ),
            ),
        )
        return FinalizedRun(
            run_id=run_id or uuid4().hex,
            sample_id=sample_id,
            protocol=ProtocolSnapshot(
                protocol_id=str(self.parameters["protocol_id"]),
                protocol_version=str(self.parameters["protocol_version"]),
                algorithm_version=__version__,
                parameters=dict(self.parameters),
            ),
            metrics=metrics,
            parameters=dict(self.parameters),
            qc={
                "warnings": list(self.warnings),
                "saturation_fraction": self.saturation.fraction,
                "touches_boundary": self.boundary.touches_any_boundary,
                "connectivity_ambiguous": self.open_path.connectivity_ambiguous,
            },
            artifacts=dict(artifacts),
        )


def masks_from_rectangles(
    shape_zyx: tuple[int, int, int],
    *,
    background_rois: Sequence[RectangularRoi],
    analysis_roi: RectangularRoi | None = None,
    lumen_roi: RectangularRoi | None = None,
    envelope_roi: RectangularRoi | None = None,
) -> PipelineMasks:
    """Build prototype masks without hiding that the geometry is rectangular."""

    if not background_rois:
        raise ValueError("at least one background ROI is required")
    background = np.zeros(shape_zyx, dtype=np.bool_)
    for roi in background_rois:
        background |= roi.mask(shape_zyx)
    analysis = (analysis_roi or RectangularRoi.full(shape_zyx)).mask(shape_zyx)
    lumen = (lumen_roi or analysis_roi or RectangularRoi.full(shape_zyx)).mask(shape_zyx)
    envelope = envelope_roi.mask(shape_zyx) if envelope_roi else None
    return PipelineMasks(
        background=background,
        analysis=analysis,
        lumen=lumen,
        envelope=envelope,
        geometry_source="rectangular-prototype-rois",
    ).validated(shape_zyx)


def suggested_rectangles(
    shape_zyx: tuple[int, int, int],
) -> tuple[RectangularRoi, RectangularRoi]:
    """Return a neutral full analysis ROI and two-edge background band.

    This is only an initial display suggestion.  A user must visually review it.
    """

    _, height, width = shape_zyx
    band = max(1, height // 10)
    background = RectangularRoi(0, band, 0, width)
    return RectangularRoi.full(shape_zyx), background


def _check_cancel(cancelled: CancelCallback | None) -> None:
    if cancelled and cancelled():
        raise AnalysisCancelled("analysis cancelled")


def _progress(callback: ProgressCallback | None, stage: str, fraction: float, message: str) -> None:
    if callback:
        callback(stage, float(fraction), message)


def _segment(
    filtered: FloatArray,
    *,
    masks: PipelineMasks,
    config: PipelineConfig,
    low_threshold: float,
    high_threshold: float,
) -> BoolArray:
    preliminary = hysteresis_threshold_3d(
        filtered,
        low_threshold=low_threshold,
        high_threshold=high_threshold,
        analysis_mask=masks.analysis & masks.lumen,
        connectivity=config.component_connectivity,
    )
    return filter_components_by_volume(
        preliminary,
        spacing_zyx_um=config.spacing_zyx_um,
        min_component_volume_um3=config.minimum_component_volume_um3,
        z_positions_um=config.z_positions_um or None,
        connectivity=config.component_connectivity,
    ).mask


def _terminal_masks(
    lumen: BoolArray,
    *,
    axis_zyx: Sequence[float],
) -> tuple[BoolArray, BoolArray]:
    """Use the first/last occupied face along a cardinal reviewed duct axis."""

    axis = np.asarray(axis_zyx, dtype=np.float64)
    norm = float(np.linalg.norm(axis))
    if not np.isfinite(norm) or norm <= 0:
        raise ValueError("axis_zyx must be a finite non-zero vector")
    axis /= norm
    dominant = int(np.argmax(np.abs(axis)))
    if not np.allclose(np.delete(axis, dominant), 0.0, atol=1e-12):
        # Cross-section metrics support arbitrary reviewed axes.  Connectivity
        # terminals are deliberately limited to cardinal axes in this prototype
        # because a diagonal terminal surface needs an explicitly reviewed mask.
        return np.zeros(lumen.shape, dtype=np.bool_), np.zeros(lumen.shape, dtype=np.bool_)

    occupied = np.any(lumen, axis=tuple(index for index in range(3) if index != dominant))
    coordinates = np.flatnonzero(occupied)
    inlet = np.zeros(lumen.shape, dtype=np.bool_)
    outlet = np.zeros(lumen.shape, dtype=np.bool_)
    if coordinates.size == 0:
        return inlet, outlet
    first = int(coordinates[0])
    last = int(coordinates[-1])
    if axis[dominant] < 0:
        first, last = last, first
    inlet_index = [slice(None)] * 3
    outlet_index = [slice(None)] * 3
    inlet_index[dominant] = first
    outlet_index[dominant] = last
    inlet[tuple(inlet_index)] = lumen[tuple(inlet_index)]
    outlet[tuple(outlet_index)] = lumen[tuple(outlet_index)]
    return inlet, outlet


def run_analysis(
    volume: Any,
    *,
    masks: PipelineMasks,
    config: PipelineConfig,
    progress: ProgressCallback | None = None,
    cancelled: CancelCallback | None = None,
) -> PipelineResult:
    """Run the locked candidate pipeline on one canonical 3D Z/Y/X volume."""

    raw = np.asarray(volume)
    if raw.ndim != 3 or not np.issubdtype(raw.dtype, np.number):
        raise ValueError("volume must be a numeric 3D Z/Y/X array")
    if raw.size == 0:
        raise ValueError("volume cannot be empty")
    shape = tuple(int(value) for value in raw.shape)
    config.validate(shape[0])
    reviewed = masks.validated(shape)
    warnings: list[str] = []
    if reviewed.geometry_source == "rectangular-prototype-rois":
        warnings.append("Geometry uses prototype rectangles and requires SME visual review.")
    overlap_fraction = float(np.count_nonzero(reviewed.background & reviewed.analysis)) / float(
        np.count_nonzero(reviewed.background)
    )
    if overlap_fraction > 0:
        warnings.append(
            "The background and analysis masks overlap; confirm that area is plug-free."
        )

    _progress(progress, "qc", 0.03, "Checking detector saturation and input validity")
    _check_cancel(cancelled)
    saturation_initial = saturation_qc(
        raw,
        saturation_threshold=config.saturation_threshold,
    )
    invalid = ~np.isfinite(np.asarray(raw, dtype=np.float64))

    _progress(progress, "correction", 0.10, "Subtracting reviewed per-plane background")
    correction = median_background_correct(
        raw,
        reviewed.background,
        invalid_mask=invalid,
        saturated_mask=saturation_initial.saturated_mask,
        min_reference_pixels_per_plane=config.min_reference_pixels_per_plane,
    )
    _check_cancel(cancelled)

    _progress(progress, "filter", 0.22, "Applying physical 3D segmentation filter")
    filtered = gaussian_filter_physical(
        correction.corrected,
        spacing_zyx_um=config.spacing_zyx_um,
        sigma_um=config.filter_sigma_um,
        valid_mask=~invalid,
    )
    filtered_sigma = robust_mad_sigma(filtered, mask=reviewed.background & ~invalid)
    if filtered_sigma <= np.finfo(np.float64).eps:
        raise ValueError(
            "filtered background noise is zero; choose a representative background ROI"
        )
    low_threshold = config.low_noise_multiplier * filtered_sigma
    high_threshold = config.high_noise_multiplier * filtered_sigma
    _check_cancel(cancelled)

    _progress(progress, "segmentation", 0.38, "Running deterministic 3D hysteresis")
    plug = _segment(
        filtered,
        masks=reviewed,
        config=config,
        low_threshold=low_threshold,
        high_threshold=high_threshold,
    )
    _check_cancel(cancelled)

    _progress(progress, "metrics", 0.55, "Calculating per-plane and physical-volume metrics")
    per_plane = per_plane_metrics(
        plug,
        correction.corrected,
        spacing_zyx_um=config.spacing_zyx_um,
    )
    volume_result = volume_metrics(
        plug,
        correction.corrected,
        spacing_zyx_um=config.spacing_zyx_um,
        z_positions_um=config.z_positions_um or None,
    )
    axial_result = axial_extent(
        plug,
        spacing_zyx_um=config.spacing_zyx_um,
        reference_point_zyx_um=config.reference_point_zyx_um,
        axis_zyx=config.axis_zyx,
        z_positions_um=config.z_positions_um or None,
    )
    normalized_axis = np.asarray(config.axis_zyx, dtype=np.float64)
    normalized_axis /= np.linalg.norm(normalized_axis)
    native_axis_step = float(
        np.sqrt(
            np.sum(
                np.square(normalized_axis * np.asarray(config.spacing_zyx_um)),
                dtype=np.float64,
            )
        )
    )
    bin_width = config.cross_section_bin_width_um or native_axis_step
    cross_section = binned_cross_section_metrics(
        plug,
        reviewed.lumen,
        spacing_zyx_um=config.spacing_zyx_um,
        reference_point_zyx_um=config.reference_point_zyx_um,
        axis_zyx=config.axis_zyx,
        bin_width_um=bin_width,
        z_positions_um=config.z_positions_um or None,
    )
    inlet, outlet = _terminal_masks(reviewed.lumen, axis_zyx=config.axis_zyx)
    open_path = open_path_connectivity(reviewed.lumen, plug, inlet, outlet)
    if open_path.connected_6:
        bottleneck = widest_open_path_clearance(
            reviewed.lumen,
            plug,
            inlet,
            outlet,
            spacing_zyx_um=config.spacing_zyx_um,
        )
    else:
        # The exact connectivity pass already proves no 6-neighbour path.
        # Avoid allocating an EDT plus Dijkstra work arrays over the full
        # volume merely to rediscover that fact.
        open_lumen = reviewed.lumen & ~plug
        bottleneck = BottleneckClearance(
            connected=False,
            bottleneck_radius_um=None,
            bottleneck_diameter_um=None,
            path_voxel_count=0,
            inlet_open_voxels=int(np.count_nonzero(open_lumen & inlet)),
            outlet_open_voxels=int(np.count_nonzero(open_lumen & outlet)),
            path_mask=np.zeros(shape, dtype=np.bool_),
            qualification=(
                "No image-resolved 6-neighbour open inlet-to-outlet path in the reviewed volume."
            ),
        )
    if not np.any(inlet) or not np.any(outlet):
        warnings.append(
            "Open-path connectivity is unavailable for a non-cardinal duct axis without "
            "reviewed inlet/outlet masks."
        )
    apparent = (
        apparent_low_fluorescence_fraction(
            plug,
            reviewed.lumen,
            reviewed.envelope,
            spacing_zyx_um=config.spacing_zyx_um,
            z_positions_um=config.z_positions_um or None,
        )
        if reviewed.envelope is not None
        else None
    )
    boundary = boundary_qc(plug)
    saturation = saturation_qc(
        raw,
        saturation_threshold=config.saturation_threshold,
        plug_mask=plug,
    )
    if saturation.fraction > 0:
        warnings.append(
            f"{100 * saturation.fraction:.4f}% of valid pixels meet the saturation threshold."
        )
    if boundary.touches_any_boundary:
        warnings.append("The mask touches an image boundary; extent/volume may be censored.")
    if open_path.connectivity_ambiguous:
        warnings.append("Open-path result changes between 6- and 26-neighbour connectivity.")
    _check_cancel(cancelled)

    intervals: dict[str, RobustnessInterval] = {}
    variant_values: dict[str, dict[str, float]] = {}
    uncertainty = np.zeros(shape, dtype=np.bool_)
    if config.robustness_mode is RobustnessMode.STANDARD:
        _progress(progress, "robustness", 0.72, "Running predeclared ± threshold variants")
        for variant in threshold_variants(
            low_threshold,
            high_threshold,
            relative_variation=config.threshold_variation,
        ):
            if variant.name == "primary":
                continue
            _check_cancel(cancelled)
            variant_mask = _segment(
                filtered,
                masks=reviewed,
                config=config,
                low_threshold=variant.low_threshold,
                high_threshold=variant.high_threshold,
            )
            variant_plane = per_plane_metrics(
                variant_mask,
                correction.corrected,
                spacing_zyx_um=config.spacing_zyx_um,
            )
            uncertainty |= variant_mask != plug
            variant_volume = volume_metrics(
                variant_mask,
                correction.corrected,
                spacing_zyx_um=config.spacing_zyx_um,
                z_positions_um=config.z_positions_um or None,
            )
            variant_values[variant.name] = {
                "observed_volume_um3": variant_volume.observed_volume_um3,
                "summed_corrected_integrated_intensity_au": float(
                    np.sum(variant_plane.corrected_integrated_intensity_au)
                ),
                "maximum_plane_area_um2": float(np.max(variant_plane.area_um2)),
            }
        primary_values = {
            "observed_volume_um3": volume_result.observed_volume_um3,
            "summed_corrected_integrated_intensity_au": float(
                np.sum(per_plane.corrected_integrated_intensity_au)
            ),
            "maximum_plane_area_um2": float(np.max(per_plane.area_um2)),
        }
        for metric_name, primary_value in primary_values.items():
            intervals[metric_name] = robustness_interval(
                primary_value,
                {name: values[metric_name] for name, values in variant_values.items()},
            )

    _progress(progress, "complete", 1.0, "Analysis complete; review the overlay before saving")
    parameters = {
        **_jsonable(config),
        "geometry_source": reviewed.geometry_source,
        "low_threshold": low_threshold,
        "high_threshold": high_threshold,
    }
    return PipelineResult(
        corrected=correction.corrected,
        filtered=filtered,
        plug_mask=plug,
        uncertainty_mask=uncertainty,
        thresholds=(low_threshold, high_threshold),
        raw_background_sigma=correction.raw_background_sigma,
        filtered_background_sigma=filtered_sigma,
        background_offsets_by_z=correction.offsets_by_z,
        per_plane=per_plane,
        volume=volume_result,
        axial=axial_result,
        cross_section=cross_section,
        open_path=open_path,
        bottleneck_clearance=bottleneck,
        apparent_low_fluorescence=apparent,
        saturation=saturation,
        boundary=boundary,
        robustness=intervals,
        variant_metrics=variant_values,
        parameters=parameters,
        warnings=tuple(warnings),
    )


def _jsonable(value: Any, *, omit: tuple[str, ...] = ()) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        value = asdict(value)
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items() if str(key) not in omit}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value
