"""Exact, disk-backed candidate pipeline for volumes that do not fit in RAM.

The regular :func:`plug_analyzer.pipeline.run_analysis` is the reference
implementation.  This module preserves its scientific operations while using
fixed Z/Y/X chunks, Zarr result arrays, and disk-backed SciPy label buffers.
It deliberately supports only a cardinal X duct axis: silently changing the
meaning of axial/cross-section/connectivity metrics would be worse than a
clear error.
"""

from __future__ import annotations

import math
import shutil
import sqlite3
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import zarr
from numpy.typing import NDArray
from scipy import ndimage

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
    resolve_plane_thicknesses_um,
    robustness_interval,
    threshold_variants,
)
from plug_analyzer.analysis.clearance import BottleneckClearance
from plug_analyzer.pipeline import (
    AnalysisCancelled,
    PipelineConfig,
    PipelineMasks,
    PipelineResult,
    RobustnessMode,
)

BoolArray = NDArray[np.bool_]
FloatArray = NDArray[np.float64]
ProgressCallback = Callable[[str, float, str], None]
CancelCallback = Callable[[], bool]


@dataclass(frozen=True, slots=True)
class LargeAnalysisInventory:
    """Preflight resource and deterministic chunk-plan inventory."""

    shape_zyx: tuple[int, int, int]
    source_dtype: str
    source_bytes: int
    chunk_shape_zyx: tuple[int, int, int]
    gaussian_halo_zyx: tuple[int, int, int]
    largest_input_chunk_bytes: int
    estimated_peak_ram_bytes: int
    estimated_workspace_bytes: int
    free_workspace_bytes: int
    disk_safe: bool
    notes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OutOfCorePipelineResult:
    """PipelineResult-compatible result whose large arrays remain on disk."""

    corrected: Any
    filtered: Any
    plug_mask: Any
    uncertainty_mask: Any
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
    workspace_directory: str = ""
    inventory: LargeAnalysisInventory | None = None

    def scalar_metrics(self) -> dict[str, float | bool | None]:
        return PipelineResult.scalar_metrics(self)  # type: ignore[arg-type]

    def summary_dict(self) -> dict[str, Any]:
        """Return the normal summary without materializing the saturation mask."""

        saturation = {
            key: _jsonable(value)
            for key, value in asdict_shallow(self.saturation).items()
            if key != "saturated_mask"
        }
        return {
            "schema_version": 1,
            "algorithm_version": __version__,
            "execution_mode": "out-of-core-exact-candidate",
            "metrics": _jsonable(self.scalar_metrics()),
            "per_plane": {
                "z_index": list(range(self.per_plane.area_um2.size)),
                "area_um2": self.per_plane.area_um2.tolist(),
                "corrected_integrated_intensity_au": (
                    self.per_plane.corrected_integrated_intensity_au.tolist()
                ),
                "fluorescence_area_integral_au_um2": (
                    self.per_plane.fluorescence_area_integral_au_um2.tolist()
                ),
                "mean_corrected_intensity_au": (
                    self.per_plane.mean_corrected_intensity_au.tolist()
                ),
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
                "saturation": saturation,
                "boundary": _jsonable(asdict(self.boundary)),
                "warnings": list(self.warnings),
            },
            "robustness": {
                name: _jsonable(asdict(value)) for name, value in self.robustness.items()
            },
            "variant_metrics": _jsonable(self.variant_metrics),
            "parameters": _jsonable(self.parameters),
            "workspace_directory": self.workspace_directory,
            "resource_inventory": _jsonable(asdict(self.inventory)) if self.inventory else None,
        }

    def to_finalized_run(self, **kwargs: Any) -> Any:
        return PipelineResult.to_finalized_run(self, **kwargs)  # type: ignore[arg-type]


def asdict_shallow(value: Any) -> dict[str, Any]:
    """Dataclass field extraction that does not recurse into a Zarr array."""

    return {name: getattr(value, name) for name in value.__dataclass_fields__}


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def _shape_and_dtype(array: Any) -> tuple[tuple[int, int, int], np.dtype[Any]]:
    shape = tuple(int(value) for value in array.shape)
    if len(shape) != 3 or any(value < 1 for value in shape):
        raise ValueError("cached_volume must be a non-empty 3D Z/Y/X array")
    dtype = np.dtype(array.dtype)
    if not np.issubdtype(dtype, np.number):
        raise TypeError("cached_volume must have a numeric dtype")
    return shape, dtype


def _fixed_chunks(
    shape: tuple[int, int, int],
    dtype: np.dtype[Any],
    requested: Sequence[int] | None,
) -> tuple[int, int, int]:
    if requested is not None:
        chunks = tuple(int(value) for value in requested)
        if len(chunks) != 3 or any(value < 1 for value in chunks):
            raise ValueError("chunk_shape_zyx must contain three positive integers")
        return tuple(min(chunks[index], shape[index]) for index in range(3))  # type: ignore[return-value]
    # A fixed plan near 32 MiB, with shallow Z for cancellation and plane metrics.
    target_voxels = max(1, (32 * 1024**2) // max(dtype.itemsize, 8))
    z_chunk = min(shape[0], 4)
    side = max(1, int(math.sqrt(target_voxels / z_chunk)))
    return (z_chunk, min(shape[1], side), min(shape[2], side))


def _sigma_pixels(config: PipelineConfig) -> tuple[float, float, float]:
    return tuple(config.filter_sigma_um / step for step in config.spacing_zyx_um)  # type: ignore[return-value]


def _halo(config: PipelineConfig, truncate: float = 4.0) -> tuple[int, int, int]:
    return tuple(int(truncate * sigma + 0.5) for sigma in _sigma_pixels(config))  # type: ignore[return-value]


def inspect_large_analysis(
    cached_volume: Any,
    *,
    config: PipelineConfig,
    workspace_parent: str | Path,
    chunk_shape_zyx: Sequence[int] | None = None,
) -> LargeAnalysisInventory:
    """Calculate the fixed chunk, halo, RAM and conservative disk preflight."""

    shape, dtype = _shape_and_dtype(cached_volume)
    config.validate(shape[0])
    chunks = _fixed_chunks(shape, dtype, chunk_shape_zyx)
    halo = _halo(config)
    expanded = tuple(min(shape[index], chunks[index] + 2 * halo[index]) for index in range(3))
    source_bytes = math.prod(shape) * dtype.itemsize
    chunk_bytes = math.prod(chunks) * dtype.itemsize
    # Gaussian normalized convolution can hold source, numerator, denominator,
    # result and validity over one halo-expanded chunk.
    peak_ram = math.prod(expanded) * (8 * 4 + 1) + math.prod(chunks) * 16
    # Persistent corrected+filtered, masks, exact EDT, threshold/label scratch,
    # component lookup and a worst-case disk-backed unique-clearance index.
    workspace = math.ceil(math.prod(shape) * 64 * 1.30)
    parent = Path(workspace_parent).expanduser().resolve()
    parent.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(parent).free
    safe = free >= workspace
    notes = (
        "Disk estimate assumes the pathological upper bound of one component per two voxels.",
        "SciPy global labeling uses disk-backed input/output; its small internal buffers are library-managed.",
        "Exact large-volume bottleneck clearance uses disk-backed EDT and connectivity search.",
    )
    return LargeAnalysisInventory(
        shape_zyx=shape,
        source_dtype=dtype.str,
        source_bytes=source_bytes,
        chunk_shape_zyx=chunks,
        gaussian_halo_zyx=halo,
        largest_input_chunk_bytes=chunk_bytes,
        estimated_peak_ram_bytes=peak_ram,
        estimated_workspace_bytes=workspace,
        free_workspace_bytes=free,
        disk_safe=safe,
        notes=notes,
    )


def _regions(
    shape: tuple[int, int, int], chunks: tuple[int, int, int]
) -> Iterator[tuple[slice, slice, slice]]:
    for z0 in range(0, shape[0], chunks[0]):
        for y0 in range(0, shape[1], chunks[1]):
            for x0 in range(0, shape[2], chunks[2]):
                yield (
                    slice(z0, min(shape[0], z0 + chunks[0])),
                    slice(y0, min(shape[1], y0 + chunks[1])),
                    slice(x0, min(shape[2], x0 + chunks[2])),
                )


def _yx_regions(
    shape_yx: tuple[int, int], chunks_yx: tuple[int, int]
) -> Iterator[tuple[slice, slice]]:
    for y0 in range(0, shape_yx[0], chunks_yx[0]):
        for x0 in range(0, shape_yx[1], chunks_yx[1]):
            yield (
                slice(y0, min(shape_yx[0], y0 + chunks_yx[0])),
                slice(x0, min(shape_yx[1], x0 + chunks_yx[1])),
            )


def _check_cancel(cancelled: CancelCallback | None) -> None:
    if cancelled and cancelled():
        raise AnalysisCancelled("analysis cancelled")


def _progress(callback: ProgressCallback | None, stage: str, fraction: float, message: str) -> None:
    if callback:
        callback(stage, float(fraction), message)


def _validate_masks(
    masks: PipelineMasks,
    shape: tuple[int, int, int],
    chunks: tuple[int, int, int],
) -> None:
    for name in ("background", "analysis", "lumen", "envelope"):
        array = getattr(masks, name)
        if array is None:
            continue
        if tuple(array.shape) != shape:
            raise ValueError(f"{name} mask shape {tuple(array.shape)} does not match {shape}")
        if not np.issubdtype(np.dtype(array.dtype), np.bool_):
            raise TypeError(f"{name} mask must use boolean dtype")
    counts = {"background": 0, "analysis": 0, "lumen": 0}
    for region in _regions(shape, chunks):
        background = np.asarray(masks.background[region], dtype=np.bool_)
        analysis = np.asarray(masks.analysis[region], dtype=np.bool_)
        lumen = np.asarray(masks.lumen[region], dtype=np.bool_)
        counts["background"] += int(np.count_nonzero(background))
        counts["analysis"] += int(np.count_nonzero(analysis))
        counts["lumen"] += int(np.count_nonzero(lumen))
        if np.any(analysis & ~lumen):
            raise ValueError("analysis mask must be contained inside the lumen mask")
        if masks.envelope is not None and np.any(
            np.asarray(masks.envelope[region], dtype=np.bool_) & ~lumen
        ):
            raise ValueError("envelope mask must be contained inside the lumen mask")
    for name, count in counts.items():
        if count == 0:
            raise ValueError(f"{name} mask is empty")


def _new_zarr(
    path: Path,
    shape: tuple[int, int, int],
    chunks: tuple[int, int, int],
    dtype: str,
) -> Any:
    return zarr.open_array(
        path,
        mode="w",
        shape=shape,
        chunks=chunks,
        dtype=dtype,
        zarr_format=3,
        dimension_names=("z", "y", "x"),
    )


def _memmap(path: Path, shape: tuple[int, ...], dtype: str, *, fill: Any = None) -> Any:
    result = np.memmap(path, mode="w+", shape=shape, dtype=dtype)
    if fill is not None:
        result[...] = fill
        result.flush()
    return result


def _close_memmap(value: Any) -> None:
    value.flush()
    mapping = getattr(value, "_mmap", None)
    if mapping is not None:
        mapping.close()


def _median_mad(values: np.memmap[Any, Any]) -> tuple[float, float]:
    center = float(np.median(values, overwrite_input=True))
    block = 1_000_000
    for start in range(0, values.size, block):
        stop = min(values.size, start + block)
        values[start:stop] = np.abs(values[start:stop] - center)
    mad = float(np.median(values, overwrite_input=True))
    return center, 1.4826 * mad


def _gather_selected(
    data: Any,
    selector: Callable[[tuple[slice, slice, slice], NDArray[Any]], BoolArray],
    *,
    shape: tuple[int, int, int],
    chunks: tuple[int, int, int],
    path: Path,
) -> np.memmap[Any, Any]:
    count = 0
    for region in _regions(shape, chunks):
        block = np.asarray(data[region])
        count += int(np.count_nonzero(selector(region, block)))
    if count == 0:
        raise ValueError("selected background contains no finite pixels")
    values = _memmap(path, (count,), "float64")
    cursor = 0
    for region in _regions(shape, chunks):
        block = np.asarray(data[region], dtype=np.float64)
        selected = block[selector(region, block)]
        values[cursor : cursor + selected.size] = selected
        cursor += selected.size
    values.flush()
    return values


def _plane_offset(
    source: Any,
    background: Any,
    z_index: int,
    *,
    threshold: float,
    shape_yx: tuple[int, int],
    chunks_yx: tuple[int, int],
    path: Path,
) -> tuple[float, int]:
    count = 0
    for yr, xr in _yx_regions(shape_yx, chunks_yx):
        raw = np.asarray(source[z_index, yr, xr], dtype=np.float64)
        bg = np.asarray(background[z_index, yr, xr], dtype=np.bool_)
        count += int(np.count_nonzero(bg & np.isfinite(raw) & (raw < threshold)))
    if count == 0:
        return np.nan, 0
    values = _memmap(path, (count,), "float64")
    cursor = 0
    for yr, xr in _yx_regions(shape_yx, chunks_yx):
        raw = np.asarray(source[z_index, yr, xr], dtype=np.float64)
        bg = np.asarray(background[z_index, yr, xr], dtype=np.bool_)
        selected = raw[bg & np.isfinite(raw) & (raw < threshold)]
        values[cursor : cursor + selected.size] = selected
        cursor += selected.size
    offset = float(np.median(values, overwrite_input=True))
    _close_memmap(values)
    path.unlink(missing_ok=True)
    return offset, count


def _write_correction_and_saturation(
    source: Any,
    masks: PipelineMasks,
    config: PipelineConfig,
    corrected: Any,
    saturated: Any,
    *,
    shape: tuple[int, int, int],
    chunks: tuple[int, int, int],
    scratch: Path,
    cancelled: CancelCallback | None,
) -> tuple[FloatArray, NDArray[np.int64], NDArray[np.int64], float]:
    offsets = np.empty(shape[0], dtype=np.float64)
    counts = np.empty(shape[0], dtype=np.int64)
    for z_index in range(shape[0]):
        _check_cancel(cancelled)
        offsets[z_index], counts[z_index] = _plane_offset(
            source,
            masks.background,
            z_index,
            threshold=config.saturation_threshold,
            shape_yx=(shape[1], shape[2]),
            chunks_yx=(chunks[1], chunks[2]),
            path=scratch / "plane-values.bin",
        )
    failed = np.flatnonzero(counts < config.min_reference_pixels_per_plane)
    if failed.size:
        raise ValueError(
            f"reference ROI has fewer than {config.min_reference_pixels_per_plane} valid "
            f"pixels in Z-plane(s) {failed.tolist()}"
        )

    sat_counts = np.zeros(shape[0], dtype=np.int64)
    valid_counts = np.zeros(shape[0], dtype=np.int64)
    for region in _regions(shape, chunks):
        _check_cancel(cancelled)
        raw = np.asarray(source[region], dtype=np.float64)
        finite = np.isfinite(raw)
        sat = finite & (raw >= config.saturation_threshold)
        corrected[region] = raw - offsets[region[0]][:, None, None]
        saturated[region] = sat
        sat_counts[region[0]] += np.count_nonzero(sat, axis=(1, 2))
        valid_counts[region[0]] += np.count_nonzero(finite, axis=(1, 2))

    def reference_selector(region: tuple[slice, slice, slice], block: NDArray[Any]) -> BoolArray:
        bg = np.asarray(masks.background[region], dtype=np.bool_)
        sat = np.asarray(saturated[region], dtype=np.bool_)
        return bg & np.isfinite(block) & ~sat

    values = _gather_selected(
        corrected,
        reference_selector,
        shape=shape,
        chunks=chunks,
        path=scratch / "raw-mad-values.bin",
    )
    _, raw_sigma = _median_mad(values)
    _close_memmap(values)
    (scratch / "raw-mad-values.bin").unlink(missing_ok=True)
    return offsets, sat_counts, valid_counts, raw_sigma


def _write_gaussian(
    corrected: Any,
    filtered: Any,
    *,
    shape: tuple[int, int, int],
    chunks: tuple[int, int, int],
    config: PipelineConfig,
    cancelled: CancelCallback | None,
) -> None:
    sigma = _sigma_pixels(config)
    halo = _halo(config)
    for region in _regions(shape, chunks):
        _check_cancel(cancelled)
        starts = tuple(item.start for item in region)
        stops = tuple(item.stop for item in region)
        expanded_start = tuple(max(0, starts[i] - halo[i]) for i in range(3))
        expanded_stop = tuple(min(shape[i], stops[i] + halo[i]) for i in range(3))
        expanded_region = tuple(slice(expanded_start[i], expanded_stop[i]) for i in range(3))
        data = np.asarray(corrected[expanded_region], dtype=np.float64)
        valid = np.isfinite(data)
        if all(value == 0 for value in sigma):
            result = data.copy()
        elif np.all(valid):
            result = ndimage.gaussian_filter(data, sigma=sigma, mode="reflect", truncate=4.0)
        else:
            numerator = ndimage.gaussian_filter(
                np.where(valid, data, 0.0), sigma=sigma, mode="reflect", truncate=4.0
            )
            denominator = ndimage.gaussian_filter(
                valid.astype(np.float64), sigma=sigma, mode="reflect", truncate=4.0
            )
            result = np.full(data.shape, np.nan, dtype=np.float64)
            np.divide(numerator, denominator, out=result, where=denominator > 0)
            result[~valid] = np.nan
        crop = tuple(
            slice(starts[i] - expanded_start[i], stops[i] - expanded_start[i]) for i in range(3)
        )
        filtered[region] = result[crop]


def _filtered_sigma(
    filtered: Any,
    background: Any,
    *,
    shape: tuple[int, int, int],
    chunks: tuple[int, int, int],
    scratch: Path,
) -> float:
    def selector(region: tuple[slice, slice, slice], block: NDArray[Any]) -> BoolArray:
        return np.asarray(background[region], dtype=np.bool_) & np.isfinite(block)

    values = _gather_selected(
        filtered,
        selector,
        shape=shape,
        chunks=chunks,
        path=scratch / "filtered-mad-values.bin",
    )
    _, sigma = _median_mad(values)
    _close_memmap(values)
    (scratch / "filtered-mad-values.bin").unlink(missing_ok=True)
    return sigma


def _structure(connectivity: int) -> BoolArray:
    if connectivity == 6:
        return ndimage.generate_binary_structure(3, 1)
    if connectivity == 26:
        return ndimage.generate_binary_structure(3, 3)
    raise ValueError("connectivity must be 6 or 26")


def _segment_to_zarr(
    filtered: Any,
    masks: PipelineMasks,
    config: PipelineConfig,
    *,
    low: float,
    high: float,
    target: Any,
    shape: tuple[int, int, int],
    chunks: tuple[int, int, int],
    scratch: Path,
    cancelled: CancelCallback | None,
) -> None:
    candidate = _memmap(scratch / "candidate.bin", shape, "bool", fill=False)
    seeds = _memmap(scratch / "seeds.bin", shape, "bool", fill=False)
    for region in _regions(shape, chunks):
        _check_cancel(cancelled)
        data = np.asarray(filtered[region], dtype=np.float64)
        allowed = (
            np.isfinite(data)
            & np.asarray(masks.analysis[region], dtype=np.bool_)
            & np.asarray(masks.lumen[region], dtype=np.bool_)
        )
        block_candidate = allowed & (data >= low)
        candidate[region] = block_candidate
        seeds[region] = block_candidate & (data >= high)
    candidate.flush()
    seeds.flush()

    labels = _memmap(scratch / "labels.bin", shape, "int64", fill=0)
    component_count = int(
        ndimage.label(candidate, structure=_structure(config.component_connectivity), output=labels)
    )
    if component_count == 0:
        for region in _regions(shape, chunks):
            target[region] = False
    else:
        seeded = _memmap(
            scratch / "seeded-components.bin", (component_count + 1,), "bool", fill=False
        )
        volumes = _memmap(
            scratch / "component-volumes.bin",
            (component_count + 1,),
            "float64",
            fill=0.0,
        )
        thicknesses = resolve_plane_thicknesses_um(
            shape[0],
            spacing_z_um=config.spacing_zyx_um[0],
            z_positions_um=config.z_positions_um or None,
        )
        pixel_area = config.spacing_zyx_um[1] * config.spacing_zyx_um[2]
        for region in _regions(shape, chunks):
            _check_cancel(cancelled)
            local_labels = np.asarray(labels[region])
            local_seeds = np.asarray(seeds[region])
            seed_labels = np.unique(local_labels[local_seeds])
            seeded[seed_labels[seed_labels != 0]] = True
            # Component volume depends on Z thickness, so accumulate one plane at a time.
            for local_z, global_z in enumerate(range(region[0].start, region[0].stop)):
                unique, counts = np.unique(local_labels[local_z], return_counts=True)
                keep = unique != 0
                np.add.at(
                    volumes,
                    unique[keep],
                    counts[keep] * pixel_area * thicknesses[global_z],
                )
        seeded.flush()
        volumes.flush()
        keep_lookup = _memmap(
            scratch / "kept-components.bin", (component_count + 1,), "bool", fill=False
        )
        block = 1_000_000
        for start in range(1, component_count + 1, block):
            stop = min(component_count + 1, start + block)
            keep_lookup[start:stop] = seeded[start:stop] & (
                volumes[start:stop] >= config.minimum_component_volume_um3
            )
        keep_lookup.flush()
        for region in _regions(shape, chunks):
            _check_cancel(cancelled)
            target[region] = keep_lookup[np.asarray(labels[region])]
        # ``del`` alone leaves an open mapping on Windows. Close these
        # explicitly before removing the scratch files below.
        del local_labels, local_seeds
        _close_memmap(seeded)
        _close_memmap(volumes)
        _close_memmap(keep_lookup)

    _close_memmap(candidate)
    _close_memmap(seeds)
    _close_memmap(labels)
    for name in (
        "candidate.bin",
        "seeds.bin",
        "labels.bin",
        "seeded-components.bin",
        "component-volumes.bin",
        "kept-components.bin",
    ):
        (scratch / name).unlink(missing_ok=True)


def _per_plane(
    plug: Any,
    corrected: Any,
    *,
    shape: tuple[int, int, int],
    chunks: tuple[int, int, int],
    spacing: tuple[float, float, float],
) -> PerPlaneMetrics:
    counts = np.zeros(shape[0], dtype=np.int64)
    cii = np.zeros(shape[0], dtype=np.float64)
    for region in _regions(shape, chunks):
        mask = np.asarray(plug[region], dtype=np.bool_)
        image = np.asarray(corrected[region], dtype=np.float64)
        counts[region[0]] += np.count_nonzero(mask, axis=(1, 2))
        cii[region[0]] += np.sum(np.where(mask, image, 0.0), axis=(1, 2), dtype=np.float64)
    pixel_area = spacing[1] * spacing[2]
    means = np.full(shape[0], np.nan, dtype=np.float64)
    np.divide(cii, counts, out=means, where=counts > 0)
    return PerPlaneMetrics(
        voxel_count=counts,
        area_um2=counts.astype(np.float64) * pixel_area,
        corrected_integrated_intensity_au=cii,
        fluorescence_area_integral_au_um2=cii * pixel_area,
        mean_corrected_intensity_au=means,
    )


def _volume(
    per_plane: PerPlaneMetrics,
    config: PipelineConfig,
) -> VolumeMetrics:
    thicknesses = resolve_plane_thicknesses_um(
        per_plane.voxel_count.size,
        spacing_z_um=config.spacing_zyx_um[0],
        z_positions_um=config.z_positions_um or None,
    )
    pixel_area = config.spacing_zyx_um[1] * config.spacing_zyx_um[2]
    return VolumeMetrics(
        observed_volume_um3=float(
            np.sum(per_plane.voxel_count * pixel_area * thicknesses, dtype=np.float64)
        ),
        fluorescence_volume_integral_au_um3=float(
            np.sum(
                per_plane.corrected_integrated_intensity_au * pixel_area * thicknesses,
                dtype=np.float64,
            )
        ),
        plane_thicknesses_um=thicknesses,
    )


def _cardinal_x(config: PipelineConfig) -> float:
    axis = np.asarray(config.axis_zyx, dtype=np.float64)
    norm = float(np.linalg.norm(axis))
    if not np.isfinite(norm) or norm <= 0:
        raise ValueError("axis_zyx must be a finite non-zero vector")
    axis /= norm
    if not np.allclose(axis[:2], 0.0, atol=1e-12) or not np.isclose(abs(axis[2]), 1.0, atol=1e-12):
        raise NotImplementedError(
            "out-of-core axial, cross-section, and connectivity metrics are certified only "
            "for a cardinal X axis"
        )
    return float(axis[2])


def _x_counts(mask: Any, shape: tuple[int, int, int], chunks: tuple[int, int, int]) -> Any:
    counts = np.zeros(shape[2], dtype=np.int64)
    for region in _regions(shape, chunks):
        counts[region[2]] += np.count_nonzero(np.asarray(mask[region], dtype=np.bool_), axis=(0, 1))
    return counts


def _weighted_percentile_sorted(values: FloatArray, counts: NDArray[np.int64], q: float) -> float:
    order = np.argsort(values)
    values = values[order]
    counts = counts[order]
    total = int(np.sum(counts, dtype=np.int64))
    h = (total - 1) * q
    lo = math.floor(h)
    hi = math.ceil(h)
    cumulative = np.cumsum(counts, dtype=np.int64)
    lo_value = float(values[np.searchsorted(cumulative, lo + 1, side="left")])
    hi_value = float(values[np.searchsorted(cumulative, hi + 1, side="left")])
    return lo_value + (h - lo) * (hi_value - lo_value)


def _axial(
    plug: Any,
    shape: tuple[int, int, int],
    chunks: tuple[int, int, int],
    config: PipelineConfig,
    direction: float,
) -> AxialExtent:
    counts = _x_counts(plug, shape, chunks)
    x = np.arange(shape[2], dtype=np.float64) * config.spacing_zyx_um[2]
    q = (x - config.reference_point_zyx_um[2]) * direction
    selected = counts > 0
    total = int(np.sum(counts, dtype=np.int64))
    if total == 0:
        return AxialExtent(0, np.nan, np.nan, np.nan)
    return AxialExtent(
        voxel_count=total,
        q_min_um=float(np.min(q[selected])),
        q_max_um=float(np.max(q[selected])),
        q95_um=_weighted_percentile_sorted(q[selected], counts[selected], 0.95),
    )


def _bin_edges(q: FloatArray, width: float) -> FloatArray:
    minimum = float(np.min(q))
    maximum = float(np.max(q))
    start = minimum - 0.5 * width
    count = max(1, int(np.ceil((maximum - minimum) / width)) + 1)
    return start + np.arange(count + 1, dtype=np.float64) * width


def _cross_section(
    plug: Any,
    lumen: Any,
    *,
    shape: tuple[int, int, int],
    chunks: tuple[int, int, int],
    config: PipelineConfig,
    direction: float,
) -> CrossSectionMetrics:
    thicknesses = resolve_plane_thicknesses_um(
        shape[0],
        spacing_z_um=config.spacing_zyx_um[0],
        z_positions_um=config.z_positions_um or None,
    )
    pixel_area = config.spacing_zyx_um[1] * config.spacing_zyx_um[2]
    lumen_volume_x = np.zeros(shape[2], dtype=np.float64)
    plug_volume_x = np.zeros(shape[2], dtype=np.float64)
    for z in range(shape[0]):
        for yr, xr in _yx_regions((shape[1], shape[2]), (chunks[1], chunks[2])):
            factor = pixel_area * thicknesses[z]
            lumen_volume_x[xr] += np.count_nonzero(np.asarray(lumen[z, yr, xr]), axis=0) * factor
            plug_volume_x[xr] += np.count_nonzero(np.asarray(plug[z, yr, xr]), axis=0) * factor
    occupied = lumen_volume_x > 0
    if not np.any(occupied):
        raise ValueError("lumen mask is empty")
    x = np.arange(shape[2], dtype=np.float64) * config.spacing_zyx_um[2]
    q = (x - config.reference_point_zyx_um[2]) * direction
    native_step = config.spacing_zyx_um[2]
    width = config.cross_section_bin_width_um or native_step
    edges = _bin_edges(q[occupied], width)
    lumen_volume, _ = np.histogram(q, bins=edges, weights=lumen_volume_x)
    plug_volume, _ = np.histogram(q, bins=edges, weights=plug_volume_x)
    lumen_area = lumen_volume / width
    plug_area = plug_volume / width
    open_area = np.maximum(0.0, lumen_area - plug_area)
    occlusion = np.full(lumen_area.shape, np.nan, dtype=np.float64)
    np.divide(100 * plug_area, lumen_area, out=occlusion, where=lumen_area > 0)
    valid = lumen_area > 0
    occlusion[valid] = np.clip(occlusion[valid], 0, 100)
    centers = 0.5 * (edges[:-1] + edges[1:])
    valid_indices = np.flatnonzero(valid)
    max_index = int(valid_indices[int(np.nanargmax(occlusion[valid]))])
    min_index = int(valid_indices[int(np.argmin(open_area[valid]))])
    return CrossSectionMetrics(
        bin_edges_um=edges,
        bin_centers_um=centers,
        plug_area_um2=np.asarray(plug_area),
        lumen_area_um2=np.asarray(lumen_area),
        occlusion_percent=occlusion,
        open_area_um2=open_area,
        maximum_occlusion_percent=float(occlusion[max_index]),
        maximum_occlusion_position_um=float(centers[max_index]),
        mean_occlusion_percent=float(np.mean(occlusion[valid], dtype=np.float64)),
        minimum_open_area_um2=float(open_area[min_index]),
        minimum_open_area_position_um=float(centers[min_index]),
    )


def _connectivity(
    plug: Any,
    lumen: Any,
    *,
    shape: tuple[int, int, int],
    chunks: tuple[int, int, int],
    direction: float,
    scratch: Path,
) -> OpenPathResult:
    open_mask = _memmap(scratch / "open.bin", shape, "bool", fill=False)
    lumen_x = _x_counts(lumen, shape, chunks)
    occupied = np.flatnonzero(lumen_x > 0)
    first, last = int(occupied[0]), int(occupied[-1])
    if direction < 0:
        first, last = last, first
    for region in _regions(shape, chunks):
        open_mask[region] = np.asarray(lumen[region]) & ~np.asarray(plug[region])
    open_mask.flush()
    inlet_count = int(np.count_nonzero(open_mask[:, :, first]))
    outlet_count = int(np.count_nonzero(open_mask[:, :, last]))
    outcomes: dict[int, bool] = {}
    for connectivity in (6, 26):
        labels = _memmap(scratch / "open-labels.bin", shape, "int64", fill=0)
        ndimage.label(open_mask, structure=_structure(connectivity), output=labels)
        inlet = np.unique(labels[:, :, first])
        outlet = np.unique(labels[:, :, last])
        outcomes[connectivity] = bool(
            np.intersect1d(inlet[inlet != 0], outlet[outlet != 0], assume_unique=True).size
        )
        _close_memmap(labels)
        (scratch / "open-labels.bin").unlink(missing_ok=True)
    _close_memmap(open_mask)
    (scratch / "open.bin").unlink(missing_ok=True)
    return OpenPathResult(
        connected_6=outcomes[6],
        connected_26=outcomes[26],
        connectivity_ambiguous=outcomes[26] and not outcomes[6],
        inlet_open_voxels=inlet_count,
        outlet_open_voxels=outlet_count,
    )


def _bottleneck_clearance_disk(
    plug: Any,
    lumen: Any,
    *,
    shape: tuple[int, int, int],
    chunks: tuple[int, int, int],
    spacing_zyx_um: tuple[float, float, float],
    direction: float,
    scratch: Path,
    arrays: Path,
) -> BottleneckClearance:
    """Exact widest 6-neighbour clearance using disk rather than a volume-sized heap."""

    lumen_x = _x_counts(lumen, shape, chunks)
    occupied = np.flatnonzero(lumen_x > 0)
    first, last = int(occupied[0]), int(occupied[-1])
    if direction < 0:
        first, last = last, first
    open_mask = _memmap(scratch / "clearance-open.bin", shape, "bool", fill=False)
    for region in _regions(shape, chunks):
        open_mask[region] = np.asarray(lumen[region], dtype=np.bool_) & ~np.asarray(
            plug[region], dtype=np.bool_
        )
    open_mask.flush()
    inlet_count = int(np.count_nonzero(open_mask[:, :, first]))
    outlet_count = int(np.count_nonzero(open_mask[:, :, last]))
    path_output = _new_zarr(arrays / "clearance-path.zarr", shape, chunks, "bool")
    for region in _regions(shape, chunks):
        path_output[region] = False
    if inlet_count == 0 or outlet_count == 0:
        _close_memmap(open_mask)
        (scratch / "clearance-open.bin").unlink(missing_ok=True)
        return BottleneckClearance(
            connected=False,
            bottleneck_radius_um=None,
            bottleneck_diameter_um=None,
            path_voxel_count=0,
            inlet_open_voxels=inlet_count,
            outlet_open_voxels=outlet_count,
            path_mask=path_output,  # type: ignore[arg-type]
            qualification="No image-resolved open inlet-to-outlet path in the reviewed volume.",
        )

    distances = _memmap(scratch / "clearance-distance.bin", shape, "float64", fill=0)
    ndimage.distance_transform_edt(
        open_mask,
        sampling=spacing_zyx_um,
        return_distances=True,
        return_indices=False,
        distances=distances,
    )
    distances.flush()
    database_path = scratch / "clearance-values.sqlite"
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA journal_mode = OFF")
        connection.execute("PRAGMA synchronous = OFF")
        connection.execute("PRAGMA temp_store = FILE")
        connection.execute("CREATE TABLE clearance_values(value REAL PRIMARY KEY)")
        for region in _regions(shape, chunks):
            values = np.unique(np.asarray(distances[region])[np.asarray(open_mask[region])])
            connection.executemany(
                "INSERT OR IGNORE INTO clearance_values(value) VALUES (?)",
                ((float(value),) for value in values if value > 0),
            )
        connection.commit()
        count = int(connection.execute("SELECT COUNT(*) FROM clearance_values").fetchone()[0])
        if count == 0:
            raise RuntimeError("open lumen has no positive EDT clearance values")

        threshold_mask = _memmap(scratch / "clearance-threshold.bin", shape, "bool", fill=False)
        labels = _memmap(scratch / "clearance-labels.bin", shape, "int64", fill=0)

        def candidate(index: int) -> float:
            row = connection.execute(
                "SELECT value FROM clearance_values ORDER BY value LIMIT 1 OFFSET ?", (index,)
            ).fetchone()
            assert row is not None
            return float(row[0])

        def connected(threshold: float) -> tuple[bool, int | None]:
            for region in _regions(shape, chunks):
                threshold_mask[region] = np.asarray(open_mask[region]) & (
                    np.asarray(distances[region]) >= threshold
                )
            threshold_mask.flush()
            labels[:] = 0
            ndimage.label(threshold_mask, structure=_structure(6), output=labels)
            inlet = np.unique(labels[:, :, first])
            outlet = np.unique(labels[:, :, last])
            shared = np.intersect1d(inlet[inlet != 0], outlet[outlet != 0], assume_unique=True)
            return bool(shared.size), int(shared[0]) if shared.size else None

        low_index, high_index = 0, count - 1
        best_index = -1
        while low_index <= high_index:
            middle = (low_index + high_index) // 2
            if connected(candidate(middle))[0]:
                best_index = middle
                low_index = middle + 1
            else:
                high_index = middle - 1
        if best_index < 0:
            radius = None
            support_count = 0
        else:
            radius = candidate(best_index)
            is_connected, component = connected(radius)
            assert is_connected and component is not None
            support_count = 0
            for region in _regions(shape, chunks):
                selected = np.asarray(labels[region]) == component
                path_output[region] = selected
                support_count += int(np.count_nonzero(selected))
        labels.flush()
        threshold_mask.flush()

    # Close mappings before unlinking so this path is valid on Windows too.
    for mapping in (labels, threshold_mask, distances, open_mask):
        _close_memmap(mapping)
    for name in (
        "clearance-open.bin",
        "clearance-distance.bin",
        "clearance-threshold.bin",
        "clearance-labels.bin",
        "clearance-values.sqlite",
    ):
        (scratch / name).unlink(missing_ok=True)
    if radius is None:
        return BottleneckClearance(
            connected=False,
            bottleneck_radius_um=None,
            bottleneck_diameter_um=None,
            path_voxel_count=0,
            inlet_open_voxels=inlet_count,
            outlet_open_voxels=outlet_count,
            path_mask=path_output,  # type: ignore[arg-type]
            qualification="No image-resolved 6-neighbour inlet-to-outlet path.",
        )
    return BottleneckClearance(
        connected=True,
        bottleneck_radius_um=radius,
        bottleneck_diameter_um=2.0 * radius,
        path_voxel_count=support_count,
        inlet_open_voxels=inlet_count,
        outlet_open_voxels=outlet_count,
        path_mask=path_output,  # type: ignore[arg-type]
        qualification=(
            "Exact disk-backed EDT bottleneck. The mask is the connected corridor supporting "
            "that clearance, not a unique flow trajectory or pressure measurement."
        ),
    )


def _apparent(
    plug: Any,
    lumen: Any,
    envelope: Any | None,
    *,
    shape: tuple[int, int, int],
    chunks: tuple[int, int, int],
    config: PipelineConfig,
) -> ApparentLowFluorescenceResult | None:
    if envelope is None:
        return None
    thicknesses = resolve_plane_thicknesses_um(
        shape[0],
        spacing_z_um=config.spacing_zyx_um[0],
        z_positions_um=config.z_positions_um or None,
    )
    area = config.spacing_zyx_um[1] * config.spacing_zyx_um[2]
    denominator = 0.0
    numerator = 0.0
    for region in _regions(shape, chunks):
        evaluated = np.asarray(envelope[region]) & np.asarray(lumen[region])
        low = evaluated & ~np.asarray(plug[region])
        weights = area * thicknesses[region[0]]
        denominator += float(
            np.sum(np.count_nonzero(evaluated, axis=(1, 2)) * weights, dtype=np.float64)
        )
        numerator += float(np.sum(np.count_nonzero(low, axis=(1, 2)) * weights, dtype=np.float64))
    if denominator <= 0:
        raise ValueError("envelope and lumen have no overlapping physical volume")
    return ApparentLowFluorescenceResult(
        percent=100 * numerator / denominator,
        low_fluorescence_volume_um3=numerator,
        envelope_lumen_volume_um3=denominator,
    )


def _boundary(plug: Any, shape: tuple[int, int, int]) -> BoundaryQC:
    total = sum(int(np.count_nonzero(np.asarray(plug[z]))) for z in range(shape[0]))
    counts = (
        int(np.count_nonzero(np.asarray(plug[0, :, :]))),
        int(np.count_nonzero(np.asarray(plug[-1, :, :]))),
        int(np.count_nonzero(np.asarray(plug[:, 0, :]))),
        int(np.count_nonzero(np.asarray(plug[:, -1, :]))),
        int(np.count_nonzero(np.asarray(plug[:, :, 0]))),
        int(np.count_nonzero(np.asarray(plug[:, :, -1]))),
    )
    fractions = tuple(count / total if total else np.nan for count in counts)
    return BoundaryQC(
        mask_voxel_count=total,
        touches_z_min=counts[0] > 0,
        touches_z_max=counts[1] > 0,
        touches_y_min=counts[2] > 0,
        touches_y_max=counts[3] > 0,
        touches_x_min=counts[4] > 0,
        touches_x_max=counts[5] > 0,
        fraction_on_z_min=fractions[0],
        fraction_on_z_max=fractions[1],
        fraction_on_y_min=fractions[2],
        fraction_on_y_max=fractions[3],
        fraction_on_x_min=fractions[4],
        fraction_on_x_max=fractions[5],
    )


def run_large_analysis(
    cached_volume: Any,
    *,
    masks: PipelineMasks,
    config: PipelineConfig,
    workspace_directory: str | Path,
    chunk_shape_zyx: Sequence[int] | None = None,
    progress: ProgressCallback | None = None,
    cancelled: CancelCallback | None = None,
    require_disk_preflight: bool = True,
) -> OutOfCorePipelineResult:
    """Run the candidate protocol without materializing the full volume in RAM."""

    shape, _dtype = _shape_and_dtype(cached_volume)
    config.validate(shape[0])
    direction = _cardinal_x(config)
    inventory = inspect_large_analysis(
        cached_volume,
        config=config,
        workspace_parent=Path(workspace_directory).parent,
        chunk_shape_zyx=chunk_shape_zyx,
    )
    if require_disk_preflight and not inventory.disk_safe:
        raise OSError(
            f"insufficient workspace disk: need approximately "
            f"{inventory.estimated_workspace_bytes} bytes, have {inventory.free_workspace_bytes}"
        )
    chunks = inventory.chunk_shape_zyx
    _validate_masks(masks, shape, chunks)
    workspace = Path(workspace_directory).expanduser().resolve()
    if workspace.exists() and any(workspace.iterdir()):
        raise FileExistsError(f"analysis workspace is not empty: {workspace}")
    workspace.mkdir(parents=True, exist_ok=True)
    arrays = workspace / "arrays"
    scratch = workspace / "scratch"
    arrays.mkdir(exist_ok=True)
    scratch.mkdir(exist_ok=True)

    corrected = _new_zarr(arrays / "corrected.zarr", shape, chunks, "float64")
    filtered = _new_zarr(arrays / "filtered.zarr", shape, chunks, "float64")
    plug = _new_zarr(arrays / "plug-mask.zarr", shape, chunks, "bool")
    saturated = _new_zarr(arrays / "saturated-mask.zarr", shape, chunks, "bool")

    warnings: list[str] = []
    if masks.geometry_source == "rectangular-prototype-rois":
        warnings.append("Geometry uses prototype rectangles and requires SME visual review.")

    _progress(progress, "correction", 0.08, "Computing per-plane background offsets")
    offsets, sat_by_z, valid_by_z, raw_sigma = _write_correction_and_saturation(
        cached_volume,
        masks,
        config,
        corrected,
        saturated,
        shape=shape,
        chunks=chunks,
        scratch=scratch,
        cancelled=cancelled,
    )
    _progress(progress, "filter", 0.22, "Applying exact haloed physical Gaussian")
    _write_gaussian(
        corrected,
        filtered,
        shape=shape,
        chunks=chunks,
        config=config,
        cancelled=cancelled,
    )
    filtered_sigma = _filtered_sigma(
        filtered,
        masks.background,
        shape=shape,
        chunks=chunks,
        scratch=scratch,
    )
    if filtered_sigma <= np.finfo(np.float64).eps:
        raise ValueError("filtered background noise is zero; review the background ROI")
    low = config.low_noise_multiplier * filtered_sigma
    high = config.high_noise_multiplier * filtered_sigma

    _progress(progress, "segmentation", 0.40, "Reconciling global 3D components on disk")
    _segment_to_zarr(
        filtered,
        masks,
        config,
        low=low,
        high=high,
        target=plug,
        shape=shape,
        chunks=chunks,
        scratch=scratch,
        cancelled=cancelled,
    )

    _progress(progress, "metrics", 0.58, "Reducing physical metrics by deterministic chunks")
    plane = _per_plane(plug, corrected, shape=shape, chunks=chunks, spacing=config.spacing_zyx_um)
    volume = _volume(plane, config)
    axial = _axial(plug, shape, chunks, config, direction)
    cross = _cross_section(
        plug,
        masks.lumen,
        shape=shape,
        chunks=chunks,
        config=config,
        direction=direction,
    )
    open_path = _connectivity(
        plug,
        masks.lumen,
        shape=shape,
        chunks=chunks,
        direction=direction,
        scratch=scratch,
    )
    bottleneck = _bottleneck_clearance_disk(
        plug,
        masks.lumen,
        shape=shape,
        chunks=chunks,
        spacing_zyx_um=config.spacing_zyx_um,
        direction=direction,
        scratch=scratch,
        arrays=arrays,
    )
    apparent = _apparent(
        plug,
        masks.lumen,
        masks.envelope,
        shape=shape,
        chunks=chunks,
        config=config,
    )
    boundary = _boundary(plug, shape)

    sat_total = int(np.sum(sat_by_z, dtype=np.int64))
    valid_total = int(np.sum(valid_by_z, dtype=np.int64))
    sat_fraction_by_z = np.full(shape[0], np.nan, dtype=np.float64)
    np.divide(sat_by_z, valid_by_z, out=sat_fraction_by_z, where=valid_by_z > 0)
    plug_sat = 0
    plug_valid = 0
    for region in _regions(shape, chunks):
        local_plug = np.asarray(plug[region], dtype=np.bool_)
        local_corrected = np.asarray(corrected[region], dtype=np.float64)
        plug_valid += int(np.count_nonzero(local_plug & np.isfinite(local_corrected)))
        plug_sat += int(np.count_nonzero(local_plug & np.asarray(saturated[region])))
    saturation = SaturationQC(
        threshold=config.saturation_threshold,
        saturated_mask=saturated,  # type: ignore[arg-type]
        saturated_count=sat_total,
        valid_count=valid_total,
        fraction=sat_total / valid_total if valid_total else np.nan,
        count_by_z=sat_by_z,
        valid_count_by_z=valid_by_z,
        fraction_by_z=sat_fraction_by_z,
        plug_saturated_count=plug_sat,
        plug_valid_count=plug_valid,
        plug_fraction=plug_sat / plug_valid if plug_valid else np.nan,
    )
    if saturation.fraction > 0:
        warnings.append(
            f"{100 * saturation.fraction:.4f}% of valid pixels meet the saturation threshold."
        )
    if boundary.touches_any_boundary:
        warnings.append("The mask touches an image boundary; extent/volume may be censored.")
    if open_path.connectivity_ambiguous:
        warnings.append("Open-path result changes between 6- and 26-neighbour connectivity.")

    intervals: dict[str, RobustnessInterval] = {}
    variants: dict[str, dict[str, float]] = {}
    uncertainty = _new_zarr(arrays / "uncertainty-mask.zarr", shape, chunks, "bool")
    if config.robustness_mode is RobustnessMode.STANDARD:
        _progress(progress, "robustness", 0.76, "Running fixed threshold variants")
        variant_zarr = _new_zarr(arrays / "variant-mask.zarr", shape, chunks, "bool")
        for variant in threshold_variants(low, high, relative_variation=config.threshold_variation):
            if variant.name == "primary":
                continue
            _segment_to_zarr(
                filtered,
                masks,
                config,
                low=variant.low_threshold,
                high=variant.high_threshold,
                target=variant_zarr,
                shape=shape,
                chunks=chunks,
                scratch=scratch,
                cancelled=cancelled,
            )
            for region in _regions(shape, chunks):
                uncertainty[region] = np.asarray(uncertainty[region], dtype=np.bool_) | (
                    np.asarray(variant_zarr[region], dtype=np.bool_)
                    != np.asarray(plug[region], dtype=np.bool_)
                )
            variant_plane = _per_plane(
                variant_zarr,
                corrected,
                shape=shape,
                chunks=chunks,
                spacing=config.spacing_zyx_um,
            )
            variant_volume = _volume(variant_plane, config)
            variants[variant.name] = {
                "observed_volume_um3": variant_volume.observed_volume_um3,
                "summed_corrected_integrated_intensity_au": float(
                    np.sum(variant_plane.corrected_integrated_intensity_au)
                ),
                "maximum_plane_area_um2": float(np.max(variant_plane.area_um2)),
            }
        primary = {
            "observed_volume_um3": volume.observed_volume_um3,
            "summed_corrected_integrated_intensity_au": float(
                np.sum(plane.corrected_integrated_intensity_au)
            ),
            "maximum_plane_area_um2": float(np.max(plane.area_um2)),
        }
        for name, value in primary.items():
            intervals[name] = robustness_interval(
                value, {variant: metrics[name] for variant, metrics in variants.items()}
            )

    parameters = {
        **asdict(config),
        "robustness_mode": config.robustness_mode.value,
        "geometry_source": masks.geometry_source,
        "low_threshold": low,
        "high_threshold": high,
        "execution_mode": "out-of-core-exact-candidate",
        "chunk_shape_zyx": chunks,
        "gaussian_halo_zyx": inventory.gaussian_halo_zyx,
    }
    _progress(progress, "complete", 1.0, "Out-of-core analysis complete")
    return OutOfCorePipelineResult(
        corrected=corrected,
        filtered=filtered,
        plug_mask=plug,
        uncertainty_mask=uncertainty,
        thresholds=(low, high),
        raw_background_sigma=raw_sigma,
        filtered_background_sigma=filtered_sigma,
        background_offsets_by_z=offsets,
        per_plane=plane,
        volume=volume,
        axial=axial,
        cross_section=cross,
        open_path=open_path,
        bottleneck_clearance=bottleneck,
        apparent_low_fluorescence=apparent,
        saturation=saturation,
        boundary=boundary,
        robustness=intervals,
        variant_metrics=variants,
        parameters=parameters,
        warnings=tuple(warnings),
        workspace_directory=str(workspace),
        inventory=inventory,
    )
