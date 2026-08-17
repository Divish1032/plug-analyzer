"""Physical plug, fluorescence, obstruction, and connectivity metrics."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from ._validation import (
    BoolArray,
    FloatArray,
    IntArray,
    as_bool_mask,
    as_zyx_array,
    connectivity_structure,
    normalized_axis_zyx,
    validate_spacing_zyx,
    validate_vector_zyx,
)


@dataclass(frozen=True, slots=True)
class PerPlaneMetrics:
    """Requested ImageJ-compatible and physical measurements for every Z-plane."""

    voxel_count: IntArray
    area_um2: FloatArray
    corrected_integrated_intensity_au: FloatArray
    fluorescence_area_integral_au_um2: FloatArray
    mean_corrected_intensity_au: FloatArray


@dataclass(frozen=True, slots=True)
class VolumeMetrics:
    """Observed mask volume and volume-weighted fluorescence integral."""

    observed_volume_um3: float
    fluorescence_volume_integral_au_um3: float
    plane_thicknesses_um: FloatArray


@dataclass(frozen=True, slots=True)
class AxialExtent:
    """Plug-coordinate extent along the reviewed physical duct axis."""

    voxel_count: int
    q_min_um: float
    q_max_um: float
    q95_um: float


@dataclass(frozen=True, slots=True)
class CrossSectionMetrics:
    """Volume-conserving binned obstruction measurements along the duct axis."""

    bin_edges_um: FloatArray
    bin_centers_um: FloatArray
    plug_area_um2: FloatArray
    lumen_area_um2: FloatArray
    occlusion_percent: FloatArray
    open_area_um2: FloatArray
    maximum_occlusion_percent: float
    maximum_occlusion_position_um: float
    mean_occlusion_percent: float
    minimum_open_area_um2: float
    minimum_open_area_position_um: float


@dataclass(frozen=True, slots=True)
class OpenPathResult:
    """Conservative and diagonal-sensitivity inlet-to-outlet connectivity flags."""

    connected_6: bool
    connected_26: bool
    connectivity_ambiguous: bool
    inlet_open_voxels: int
    outlet_open_voxels: int


@dataclass(frozen=True, slots=True)
class ApparentLowFluorescenceResult:
    """Single-channel low-fluorescence proxy; never a true porosity claim."""

    percent: float
    low_fluorescence_volume_um3: float
    envelope_lumen_volume_um3: float


def represented_plane_thicknesses_um(z_positions_um: Sequence[float]) -> FloatArray:
    """Derive represented plane thicknesses from strictly increasing Z centers.

    Interior boundaries are center midpoints. The nearest center interval is
    extrapolated by half an interval at each end, as defined by the candidate
    scientific protocol.
    """

    positions = np.asarray(z_positions_um, dtype=np.float64)
    if positions.ndim != 1 or positions.size < 2:
        raise ValueError("z_positions_um must contain at least two plane centers")
    if not np.all(np.isfinite(positions)):
        raise ValueError("z_positions_um must contain only finite values")
    differences = np.diff(positions)
    if np.any(differences <= 0.0):
        raise ValueError("z_positions_um must be strictly increasing with no duplicates")

    thicknesses = np.empty(positions.size, dtype=np.float64)
    thicknesses[0] = differences[0]
    thicknesses[-1] = differences[-1]
    if positions.size > 2:
        thicknesses[1:-1] = 0.5 * (differences[:-1] + differences[1:])
    return thicknesses


def resolve_plane_thicknesses_um(
    z_count: int,
    *,
    spacing_z_um: float,
    z_positions_um: Sequence[float] | None = None,
) -> FloatArray:
    """Return one represented physical thickness for every Z-plane."""

    if not isinstance(z_count, int) or z_count < 1:
        raise ValueError("z_count must be a positive integer")
    if not np.isfinite(spacing_z_um) or spacing_z_um <= 0.0:
        raise ValueError("spacing_z_um must be finite and positive")
    if z_positions_um is None:
        return np.full(z_count, float(spacing_z_um), dtype=np.float64)

    positions = np.asarray(z_positions_um, dtype=np.float64)
    if positions.shape != (z_count,):
        raise ValueError(f"z_positions_um must contain one center for each of {z_count} planes")
    if z_count == 1:
        if not np.all(np.isfinite(positions)):
            raise ValueError("z_positions_um must contain only finite values")
        return np.asarray([spacing_z_um], dtype=np.float64)
    return represented_plane_thicknesses_um(positions)


def _validated_mask_and_intensity(mask: Any, corrected_image: Any) -> tuple[BoolArray, FloatArray]:
    raw_mask = as_zyx_array(mask, name="mask")
    boolean = as_bool_mask(raw_mask, name="mask", shape=raw_mask.shape)
    raw_image = as_zyx_array(corrected_image, name="corrected_image")
    if raw_image.shape != boolean.shape:
        raise ValueError(
            f"corrected_image shape {raw_image.shape} does not match mask shape {boolean.shape}"
        )
    if not np.issubdtype(raw_image.dtype, np.number):
        raise TypeError(f"corrected_image must contain numeric values; got {raw_image.dtype}")
    image = np.asarray(raw_image, dtype=np.float64)
    if np.any(boolean & ~np.isfinite(image)):
        raise ValueError("corrected_image contains a non-finite value inside the plug mask")
    return boolean, image


def per_plane_metrics(
    mask: Any,
    corrected_image: Any,
    *,
    spacing_zyx_um: Sequence[float],
) -> PerPlaneMetrics:
    """Calculate area, signed CII, spatial integral, and mean for each plane."""

    boolean, image = _validated_mask_and_intensity(mask, corrected_image)
    spacing = validate_spacing_zyx(spacing_zyx_um)
    pixel_area = spacing[1] * spacing[2]
    counts = np.count_nonzero(boolean, axis=(1, 2)).astype(np.int64, copy=False)
    selected_values = np.where(boolean, image, 0.0)
    cii = np.sum(selected_values, axis=(1, 2), dtype=np.float64)
    means = np.full(boolean.shape[0], np.nan, dtype=np.float64)
    np.divide(cii, counts, out=means, where=counts > 0)
    return PerPlaneMetrics(
        voxel_count=counts,
        area_um2=counts.astype(np.float64) * pixel_area,
        corrected_integrated_intensity_au=cii,
        fluorescence_area_integral_au_um2=cii * pixel_area,
        mean_corrected_intensity_au=means,
    )


def volume_metrics(
    mask: Any,
    corrected_image: Any,
    *,
    spacing_zyx_um: Sequence[float],
    z_positions_um: Sequence[float] | None = None,
) -> VolumeMetrics:
    """Calculate observed physical volume and signed volume fluorescence integral."""

    boolean, image = _validated_mask_and_intensity(mask, corrected_image)
    spacing = validate_spacing_zyx(spacing_zyx_um)
    thicknesses = resolve_plane_thicknesses_um(
        boolean.shape[0],
        spacing_z_um=spacing[0],
        z_positions_um=z_positions_um,
    )
    pixel_area = spacing[1] * spacing[2]
    counts = np.count_nonzero(boolean, axis=(1, 2)).astype(np.float64)
    plane_cii = np.sum(np.where(boolean, image, 0.0), axis=(1, 2), dtype=np.float64)
    volume = float(np.sum(counts * pixel_area * thicknesses, dtype=np.float64))
    fluorescence = float(np.sum(plane_cii * pixel_area * thicknesses, dtype=np.float64))
    return VolumeMetrics(
        observed_volume_um3=volume,
        fluorescence_volume_integral_au_um3=fluorescence,
        plane_thicknesses_um=thicknesses,
    )


def _physical_coordinates_for_indices(
    indices_zyx: tuple[IntArray, IntArray, IntArray],
    *,
    spacing_zyx_um: tuple[float, float, float],
    z_positions_um: Sequence[float] | None,
) -> tuple[FloatArray, FloatArray, FloatArray]:
    z_indices, y_indices, x_indices = indices_zyx
    if z_positions_um is None:
        z_coordinates = z_indices.astype(np.float64) * spacing_zyx_um[0]
    else:
        positions = np.asarray(z_positions_um, dtype=np.float64)
        z_coordinates = positions[z_indices]
    y_coordinates = y_indices.astype(np.float64) * spacing_zyx_um[1]
    x_coordinates = x_indices.astype(np.float64) * spacing_zyx_um[2]
    return z_coordinates, y_coordinates, x_coordinates


def _project_indices(
    indices_zyx: tuple[IntArray, IntArray, IntArray],
    *,
    spacing_zyx_um: tuple[float, float, float],
    z_positions_um: Sequence[float] | None,
    reference_point_zyx_um: Sequence[float],
    axis_zyx: Sequence[float],
) -> FloatArray:
    reference = validate_vector_zyx(reference_point_zyx_um, name="reference_point_zyx_um")
    axis = normalized_axis_zyx(axis_zyx)
    z, y, x = _physical_coordinates_for_indices(
        indices_zyx,
        spacing_zyx_um=spacing_zyx_um,
        z_positions_um=z_positions_um,
    )
    return (
        (z - reference[0]) * axis[0] + (y - reference[1]) * axis[1] + (x - reference[2]) * axis[2]
    )


def axial_extent(
    mask: Any,
    *,
    spacing_zyx_um: Sequence[float],
    reference_point_zyx_um: Sequence[float],
    axis_zyx: Sequence[float],
    z_positions_um: Sequence[float] | None = None,
) -> AxialExtent:
    """Return maximum and robust 95th-percentile physical plug penetration."""

    raw = as_zyx_array(mask, name="mask")
    boolean = as_bool_mask(raw, name="mask", shape=raw.shape)
    spacing = validate_spacing_zyx(spacing_zyx_um)
    if z_positions_um is not None:
        resolve_plane_thicknesses_um(
            boolean.shape[0],
            spacing_z_um=spacing[0],
            z_positions_um=z_positions_um,
        )
    indices = tuple(np.asarray(index, dtype=np.int64) for index in np.nonzero(boolean))
    count = int(indices[0].size)
    if count == 0:
        return AxialExtent(voxel_count=0, q_min_um=np.nan, q_max_um=np.nan, q95_um=np.nan)
    q_values = _project_indices(
        indices,  # type: ignore[arg-type]
        spacing_zyx_um=spacing,
        z_positions_um=z_positions_um,
        reference_point_zyx_um=reference_point_zyx_um,
        axis_zyx=axis_zyx,
    )
    return AxialExtent(
        voxel_count=count,
        q_min_um=float(np.min(q_values)),
        q_max_um=float(np.max(q_values)),
        q95_um=float(np.percentile(q_values, 95.0, method="linear")),
    )


def _bin_edges_for_range(
    q_values: FloatArray,
    *,
    bin_width_um: float,
    q_range_um: tuple[float, float] | None,
) -> FloatArray:
    if not np.isfinite(bin_width_um) or bin_width_um <= 0.0:
        raise ValueError("bin_width_um must be finite and positive")
    if q_range_um is None:
        minimum = float(np.min(q_values))
        maximum = float(np.max(q_values))
        start = minimum - 0.5 * bin_width_um
        bin_count = max(1, int(np.ceil((maximum - minimum) / bin_width_um)) + 1)
        return start + np.arange(bin_count + 1, dtype=np.float64) * bin_width_um

    start, stop = (float(value) for value in q_range_um)
    if not np.isfinite(start) or not np.isfinite(stop) or stop <= start:
        raise ValueError("q_range_um must contain finite (start, stop) values with stop > start")
    raw_count = (stop - start) / bin_width_um
    bin_count = round(raw_count)
    if bin_count < 1 or not np.isclose(raw_count, bin_count, rtol=1e-10, atol=1e-12):
        raise ValueError("q_range_um width must be an integer multiple of bin_width_um")
    return start + np.arange(bin_count + 1, dtype=np.float64) * bin_width_um


def binned_cross_section_metrics(
    plug_mask: Any,
    lumen_mask: Any,
    *,
    spacing_zyx_um: Sequence[float],
    reference_point_zyx_um: Sequence[float],
    axis_zyx: Sequence[float],
    bin_width_um: float,
    q_range_um: tuple[float, float] | None = None,
    z_positions_um: Sequence[float] | None = None,
) -> CrossSectionMetrics:
    """Conserve voxel volume while binning plug/lumen cross-sections along ``q``."""

    raw_lumen = as_zyx_array(lumen_mask, name="lumen_mask")
    lumen = as_bool_mask(raw_lumen, name="lumen_mask", shape=raw_lumen.shape)
    plug = as_bool_mask(plug_mask, name="plug_mask", shape=lumen.shape)
    if np.any(plug & ~lumen):
        raise ValueError("plug_mask must be entirely contained in lumen_mask")
    if not np.any(lumen):
        raise ValueError("lumen_mask must contain at least one voxel")

    spacing = validate_spacing_zyx(spacing_zyx_um)
    thicknesses = resolve_plane_thicknesses_um(
        lumen.shape[0],
        spacing_z_um=spacing[0],
        z_positions_um=z_positions_um,
    )
    lumen_indices = tuple(np.asarray(index, dtype=np.int64) for index in np.nonzero(lumen))
    q_lumen = _project_indices(
        lumen_indices,  # type: ignore[arg-type]
        spacing_zyx_um=spacing,
        z_positions_um=z_positions_um,
        reference_point_zyx_um=reference_point_zyx_um,
        axis_zyx=axis_zyx,
    )
    edges = _bin_edges_for_range(
        q_lumen,
        bin_width_um=float(bin_width_um),
        q_range_um=q_range_um,
    )
    pixel_area = spacing[1] * spacing[2]
    lumen_weights = thicknesses[lumen_indices[0]] * pixel_area
    lumen_volume, _ = np.histogram(q_lumen, bins=edges, weights=lumen_weights)

    plug_indices = tuple(np.asarray(index, dtype=np.int64) for index in np.nonzero(plug))
    if plug_indices[0].size:
        q_plug = _project_indices(
            plug_indices,  # type: ignore[arg-type]
            spacing_zyx_um=spacing,
            z_positions_um=z_positions_um,
            reference_point_zyx_um=reference_point_zyx_um,
            axis_zyx=axis_zyx,
        )
        plug_weights = thicknesses[plug_indices[0]] * pixel_area
        plug_volume, _ = np.histogram(q_plug, bins=edges, weights=plug_weights)
    else:
        plug_volume = np.zeros(edges.size - 1, dtype=np.float64)

    lumen_area = np.asarray(lumen_volume / bin_width_um, dtype=np.float64)
    plug_area = np.asarray(plug_volume / bin_width_um, dtype=np.float64)
    # Weighted histogram addition can leave sub-nanometre-scale floating error
    # even though plug is a strict subset of lumen.  Clamp only that numerical
    # residue; the underlying plug/lumen arrays remain untouched and auditable.
    open_area = np.maximum(0.0, lumen_area - plug_area)
    occlusion = np.full(lumen_area.shape, np.nan, dtype=np.float64)
    np.divide(100.0 * plug_area, lumen_area, out=occlusion, where=lumen_area > 0.0)
    valid = lumen_area > 0.0
    occlusion[valid] = np.clip(occlusion[valid], 0.0, 100.0)
    centers = 0.5 * (edges[:-1] + edges[1:])

    if np.any(valid):
        valid_indices = np.flatnonzero(valid)
        maximum_local = int(np.nanargmax(occlusion[valid]))
        minimum_local = int(np.argmin(open_area[valid]))
        maximum_index = int(valid_indices[maximum_local])
        minimum_index = int(valid_indices[minimum_local])
        maximum = float(occlusion[maximum_index])
        maximum_position = float(centers[maximum_index])
        mean = float(np.mean(occlusion[valid], dtype=np.float64))
        minimum_open = float(open_area[minimum_index])
        minimum_open_position = float(centers[minimum_index])
    else:  # pragma: no cover - a non-empty lumen normally makes at least one valid bin
        maximum = maximum_position = mean = minimum_open = minimum_open_position = np.nan

    return CrossSectionMetrics(
        bin_edges_um=edges,
        bin_centers_um=centers,
        plug_area_um2=plug_area,
        lumen_area_um2=lumen_area,
        occlusion_percent=occlusion,
        open_area_um2=open_area,
        maximum_occlusion_percent=maximum,
        maximum_occlusion_position_um=maximum_position,
        mean_occlusion_percent=mean,
        minimum_open_area_um2=minimum_open,
        minimum_open_area_position_um=minimum_open_position,
    )


def _has_connected_path(
    open_mask: BoolArray,
    inlet_mask: BoolArray,
    outlet_mask: BoolArray,
    *,
    connectivity: int,
) -> bool:
    from scipy import ndimage

    labels, _ = ndimage.label(open_mask, structure=connectivity_structure(connectivity))
    inlet_labels = np.unique(labels[inlet_mask & open_mask])
    outlet_labels = np.unique(labels[outlet_mask & open_mask])
    inlet_labels = inlet_labels[inlet_labels != 0]
    outlet_labels = outlet_labels[outlet_labels != 0]
    return bool(np.intersect1d(inlet_labels, outlet_labels, assume_unique=True).size)


def open_path_connectivity(
    lumen_mask: Any,
    plug_mask: Any,
    inlet_mask: Any,
    outlet_mask: Any,
) -> OpenPathResult:
    """Test image-resolved inlet-to-outlet paths with 6 and 26 neighbours."""

    raw_lumen = as_zyx_array(lumen_mask, name="lumen_mask")
    lumen = as_bool_mask(raw_lumen, name="lumen_mask", shape=raw_lumen.shape)
    plug = as_bool_mask(plug_mask, name="plug_mask", shape=lumen.shape)
    inlet = as_bool_mask(inlet_mask, name="inlet_mask", shape=lumen.shape)
    outlet = as_bool_mask(outlet_mask, name="outlet_mask", shape=lumen.shape)
    if np.any(plug & ~lumen):
        raise ValueError("plug_mask must be entirely contained in lumen_mask")

    open_mask = lumen & ~plug
    inlet_count = int(np.count_nonzero(open_mask & inlet))
    outlet_count = int(np.count_nonzero(open_mask & outlet))
    connected_6 = _has_connected_path(
        open_mask,
        inlet,
        outlet,
        connectivity=6,
    )
    connected_26 = _has_connected_path(
        open_mask,
        inlet,
        outlet,
        connectivity=26,
    )
    return OpenPathResult(
        connected_6=connected_6,
        connected_26=connected_26,
        connectivity_ambiguous=connected_26 and not connected_6,
        inlet_open_voxels=inlet_count,
        outlet_open_voxels=outlet_count,
    )


def apparent_low_fluorescence_fraction(
    plug_mask: Any,
    lumen_mask: Any,
    envelope_mask: Any,
    *,
    spacing_zyx_um: Sequence[float],
    z_positions_um: Sequence[float] | None = None,
) -> ApparentLowFluorescenceResult:
    """Calculate ``100 * V(E ∩ L ∩ ¬M) / V(E ∩ L)`` in physical units."""

    raw_lumen = as_zyx_array(lumen_mask, name="lumen_mask")
    lumen = as_bool_mask(raw_lumen, name="lumen_mask", shape=raw_lumen.shape)
    plug = as_bool_mask(plug_mask, name="plug_mask", shape=lumen.shape)
    envelope = as_bool_mask(envelope_mask, name="envelope_mask", shape=lumen.shape)
    spacing = validate_spacing_zyx(spacing_zyx_um)
    thicknesses = resolve_plane_thicknesses_um(
        lumen.shape[0],
        spacing_z_um=spacing[0],
        z_positions_um=z_positions_um,
    )

    evaluated = envelope & lumen
    counts_by_z = np.count_nonzero(evaluated, axis=(1, 2)).astype(np.float64)
    low_counts_by_z = np.count_nonzero(evaluated & ~plug, axis=(1, 2)).astype(np.float64)
    voxel_factor = spacing[1] * spacing[2] * thicknesses
    denominator = float(np.sum(counts_by_z * voxel_factor, dtype=np.float64))
    if denominator <= 0.0:
        raise ValueError("envelope_mask and lumen_mask have no overlapping physical volume")
    numerator = float(np.sum(low_counts_by_z * voxel_factor, dtype=np.float64))
    return ApparentLowFluorescenceResult(
        percent=100.0 * numerator / denominator,
        low_fluorescence_volume_um3=numerator,
        envelope_lumen_volume_um3=denominator,
    )
