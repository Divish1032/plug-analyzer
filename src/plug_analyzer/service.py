"""Application service joining readers, project storage, analysis, and exports."""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
from numpy.typing import NDArray
from skimage.draw import polygon as rasterize_polygon

from plug_analyzer import __version__
from plug_analyzer.exports import finalize_project_run
from plug_analyzer.io import (
    DatasetInfo,
    IOProgress,
    VolumeSelection,
    choose_storage_chunks,
    fingerprint_source,
    import_to_zarr,
    load_cache_manifest,
    open_cached_volume,
    open_reader,
    verify_cache,
)
from plug_analyzer.io.models import model_to_dict
from plug_analyzer.large_pipeline import (
    OutOfCorePipelineResult,
    inspect_large_analysis,
    run_large_analysis,
)
from plug_analyzer.models import (
    CalibrationSource,
    CalibrationValue,
    SourceMetadata,
    SourceSelection,
    VoxelCalibration,
)
from plug_analyzer.pipeline import (
    PipelineConfig,
    PipelineMasks,
    PipelineResult,
    RectangularRoi,
    run_analysis,
)
from plug_analyzer.project import ProjectStore
from plug_analyzer.resources import (
    REFERENCE_PIPELINE_SOURCE_AMPLIFICATION,
    build_resource_plan,
)

ProgressCallback = Callable[[str, float, str], None]
CancelCallback = Callable[[], bool]


@dataclass(frozen=True, slots=True)
class ImportResult:
    sample_id: str
    metadata: SourceMetadata
    cache_relative_path: str
    cache_verification_errors: tuple[str, ...]


class VirtualRectangularMask:
    """Read-only broadcast rectangle without a volume-sized allocation.

    The object exposes the small subset of NumPy/Zarr indexing used by both
    analysis services. A request materializes only the requested slice. Calling
    ``np.asarray`` intentionally fails so a future caller cannot accidentally
    allocate a multi-GB boolean volume.
    """

    dtype = np.dtype(np.bool_)
    ndim = 3

    def __init__(
        self,
        shape_zyx: tuple[int, int, int],
        rectangles: tuple[RectangularRoi, ...],
    ) -> None:
        self.shape = tuple(int(value) for value in shape_zyx)
        if len(self.shape) != 3 or any(value < 1 for value in self.shape):
            raise ValueError("shape_zyx must contain three positive dimensions")
        if not rectangles:
            raise ValueError("at least one rectangle is required")
        for rectangle in rectangles:
            rectangle.validate(self.shape)
        self.rectangles = rectangles

    def __array__(self, dtype: Any = None, copy: Any = None) -> NDArray[np.bool_]:
        del dtype, copy
        raise MemoryError(
            "VirtualRectangularMask cannot be materialized as a full volume; request a slice"
        )

    def __getitem__(self, key: Any) -> NDArray[np.bool_]:
        normalized = _normalize_zyx_key(key, self.shape)
        coordinates: list[NDArray[np.int64]] = []
        scalar_axes: list[int] = []
        for axis, item in enumerate(normalized):
            if isinstance(item, int):
                index = item if item >= 0 else self.shape[axis] + item
                if not 0 <= index < self.shape[axis]:
                    raise IndexError(f"index {item} is out of bounds for axis {axis}")
                coordinates.append(np.asarray([index], dtype=np.int64))
                scalar_axes.append(axis)
            elif isinstance(item, slice):
                start, stop, step = item.indices(self.shape[axis])
                coordinates.append(np.arange(start, stop, step, dtype=np.int64))
            else:
                raise IndexError("virtual masks support only integer and slice indexing")
        output = np.zeros(tuple(item.size for item in coordinates), dtype=np.bool_)
        y_coordinates = coordinates[1]
        x_coordinates = coordinates[2]
        for rectangle in self.rectangles:
            y_selected = (y_coordinates >= rectangle.y_start) & (y_coordinates < rectangle.y_stop)
            x_selected = (x_coordinates >= rectangle.x_start) & (x_coordinates < rectangle.x_stop)
            output |= y_selected[None, :, None] & x_selected[None, None, :]
        if scalar_axes:
            output = np.squeeze(output, axis=tuple(scalar_axes))
        return output


class VirtualPlaneMask:
    """Broadcast one reviewed arbitrary Y/X mask through Z with bounded memory."""

    dtype = np.dtype(np.bool_)
    ndim = 3

    def __init__(self, shape_zyx: tuple[int, int, int], plane_yx: Any) -> None:
        self.shape = tuple(int(value) for value in shape_zyx)
        plane = np.asarray(plane_yx, dtype=np.bool_)
        if plane.shape != self.shape[1:]:
            raise ValueError("plane mask must match the selected Y/X shape")
        if not np.any(plane):
            raise ValueError("reviewed plane mask is empty")
        self.plane_yx = plane

    def __array__(self, dtype: Any = None, copy: Any = None) -> NDArray[np.bool_]:
        del dtype, copy
        raise MemoryError("VirtualPlaneMask cannot be materialized; request a bounded slice")

    def __getitem__(self, key: Any) -> NDArray[np.bool_]:
        normalized = _normalize_zyx_key(key, self.shape)
        coordinates: list[NDArray[np.int64]] = []
        scalar_axes: list[int] = []
        for axis, item in enumerate(normalized):
            if isinstance(item, int):
                index = item if item >= 0 else self.shape[axis] + item
                if not 0 <= index < self.shape[axis]:
                    raise IndexError(f"index {item} is out of bounds for axis {axis}")
                coordinates.append(np.asarray([index], dtype=np.int64))
                scalar_axes.append(axis)
            else:
                start, stop, step = item.indices(self.shape[axis])
                coordinates.append(np.arange(start, stop, step, dtype=np.int64))
        plane = self.plane_yx[np.ix_(coordinates[1], coordinates[2])]
        output = np.broadcast_to(plane[None, :, :], tuple(item.size for item in coordinates))
        if scalar_axes:
            output = np.squeeze(output, axis=tuple(scalar_axes))
        return np.asarray(output, dtype=np.bool_)


def polygon_plane_mask(
    shape_yx: tuple[int, int], vertices_xy: tuple[tuple[float, float], ...]
) -> NDArray[np.bool_]:
    """Rasterize an SME-reviewed closed polygon without extrapolating outside the image."""

    if len(vertices_xy) < 3:
        raise ValueError("a reviewed polygon requires at least three vertices")
    vertices = np.asarray(vertices_xy, dtype=np.float64)
    if vertices.shape != (len(vertices_xy), 2) or not np.all(np.isfinite(vertices)):
        raise ValueError("polygon vertices must be finite X/Y pairs")
    rows, columns = rasterize_polygon(vertices[:, 1], vertices[:, 0], shape=shape_yx)
    mask = np.zeros(shape_yx, dtype=np.bool_)
    mask[rows, columns] = True
    if not np.any(mask):
        raise ValueError("polygon does not cover a pixel inside the selected image")
    return mask


def _normalize_zyx_key(
    key: Any, shape: tuple[int, int, int]
) -> tuple[int | slice, int | slice, int | slice]:
    items = list(key if isinstance(key, tuple) else (key,))
    if items.count(Ellipsis) > 1:
        raise IndexError("only one ellipsis is supported")
    if Ellipsis in items:
        index = items.index(Ellipsis)
        fill = 3 - (len(items) - 1)
        items[index : index + 1] = [slice(None)] * fill
    items.extend([slice(None)] * (3 - len(items)))
    if len(items) != 3 or any(item is None for item in items):
        raise IndexError("virtual masks require exactly Z/Y/X indexing")
    return tuple(items)  # type: ignore[return-value]


def virtual_masks_from_rectangles(
    shape_zyx: tuple[int, int, int],
    *,
    background_rois: tuple[RectangularRoi, ...],
    analysis_roi: RectangularRoi | None = None,
    lumen_roi: RectangularRoi | None = None,
    envelope_roi: RectangularRoi | None = None,
) -> PipelineMasks:
    """Build rectangular pipeline geometry with constant metadata-sized memory."""

    full = RectangularRoi.full(shape_zyx)
    analysis = analysis_roi or full
    lumen = lumen_roi or analysis_roi or full
    return PipelineMasks(
        background=VirtualRectangularMask(shape_zyx, tuple(background_rois)),  # type: ignore[arg-type]
        analysis=VirtualRectangularMask(shape_zyx, (analysis,)),  # type: ignore[arg-type]
        lumen=VirtualRectangularMask(shape_zyx, (lumen,)),  # type: ignore[arg-type]
        envelope=(
            VirtualRectangularMask(shape_zyx, (envelope_roi,))  # type: ignore[arg-type]
            if envelope_roi is not None
            else None
        ),
        geometry_source="rectangular-prototype-rois",
    )


def virtual_masks_from_geometry(
    shape_zyx: tuple[int, int, int],
    *,
    background_rois: tuple[RectangularRoi, ...],
    analysis_roi: RectangularRoi,
    lumen_roi: RectangularRoi,
    envelope_roi: RectangularRoi | None,
    background_polygon_xy: tuple[tuple[float, float], ...] = (),
    analysis_polygon_xy: tuple[tuple[float, float], ...] = (),
    lumen_polygon_xy: tuple[tuple[float, float], ...] = (),
    envelope_polygon_xy: tuple[tuple[float, float], ...] = (),
) -> PipelineMasks:
    """Prefer editable polygons while retaining rectangles for unset geometry."""

    rectangles = virtual_masks_from_rectangles(
        shape_zyx,
        background_rois=background_rois,
        analysis_roi=analysis_roi,
        lumen_roi=lumen_roi,
        envelope_roi=envelope_roi,
    )

    def polygon_or_rectangle(vertices: tuple[tuple[float, float], ...], fallback: Any) -> Any:
        return (
            VirtualPlaneMask(shape_zyx, polygon_plane_mask(shape_zyx[1:], vertices))
            if vertices
            else fallback
        )

    analysis = polygon_or_rectangle(analysis_polygon_xy, rectangles.analysis)
    lumen = polygon_or_rectangle(lumen_polygon_xy or analysis_polygon_xy, rectangles.lumen)
    background = polygon_or_rectangle(background_polygon_xy, rectangles.background)
    envelope = (
        polygon_or_rectangle(envelope_polygon_xy, rectangles.envelope)
        if envelope_polygon_xy or rectangles.envelope is not None
        else None
    )
    return PipelineMasks(
        background=background,
        analysis=analysis,
        lumen=lumen,
        envelope=envelope,
        geometry_source=(
            "reviewed-polygon-prisms"
            if any(
                (
                    background_polygon_xy,
                    analysis_polygon_xy,
                    lumen_polygon_xy,
                    envelope_polygon_xy,
                )
            )
            else rectangles.geometry_source
        ),
    )


def prepare_source_cache(
    project_root: Path,
    *,
    source_path: Path,
    selection: VolumeSelection | None = None,
    sample_id: str | None = None,
    progress: ProgressCallback | None = None,
    cancelled: CancelCallback | None = None,
) -> ImportResult:
    """Create and fully verify a cache without touching the project database."""

    selection = selection or VolumeSelection()
    reader = open_reader(source_path)
    info = reader.probe()
    shape = reader.selected_shape(selection)
    scene = info.scenes[selection.scene]
    chunk_shape = choose_storage_chunks(shape, scene.dtype)
    identifier = sample_id or uuid4().hex
    relative_cache = Path("data") / identifier
    cache_path = project_root.resolve() / relative_cache
    if cache_path.is_dir():
        # Cancellation can happen during verification after the cache has
        # already been atomically published. Reuse it on retry only after
        # proving that its source identity and selection are unchanged.
        manifest = load_cache_manifest(cache_path)
        fingerprint = fingerprint_source(
            source_path,
            progress=_progress_adapter(progress),
            should_cancel=cancelled,
        )
        mismatches: list[str] = []
        if manifest.status != "complete":
            mismatches.append("completion status")
        if manifest.source != fingerprint:
            mismatches.append("source fingerprint")
        if manifest.reader_id != reader.reader_id:
            mismatches.append("reader")
        if manifest.selection != selection:
            mismatches.append("selection")
        if manifest.shape_zyx != shape:
            mismatches.append("shape")
        if manifest.dtype != np.dtype(scene.dtype).str:
            mismatches.append("dtype")
        if mismatches:
            raise RuntimeError(
                "Existing unpublished cache cannot be resumed because these changed: "
                + ", ".join(mismatches)
            )
    else:
        manifest = import_to_zarr(
            reader,
            selection,
            cache_path,
            chunk_shape=chunk_shape,
            progress=_progress_adapter(progress),
            should_cancel=cancelled,
        )
    verification = verify_cache(
        cache_path,
        progress=_progress_adapter(progress),
        should_cancel=cancelled,
    )
    if not verification.valid:
        raise RuntimeError("Imported cache failed verification: " + "; ".join(verification.errors))
    metadata = source_metadata_from_probe(
        info,
        selection=selection,
        sha256=manifest.source.sha256,
        size_bytes=manifest.source.size_bytes,
    )
    return ImportResult(
        sample_id=identifier,
        metadata=metadata,
        cache_relative_path=str(relative_cache),
        cache_verification_errors=verification.errors,
    )


def publish_import(store: ProjectStore, *, prepared: ImportResult, sample_name: str) -> None:
    """Publish a previously verified import as one project sample row."""

    store.add_sample(
        name=sample_name,
        metadata=prepared.metadata,
        cache_path=prepared.cache_relative_path,
        sample_id=prepared.sample_id,
    )


def _progress_adapter(callback: ProgressCallback | None) -> Callable[[IOProgress], None]:
    def emit(item: IOProgress) -> None:
        if callback:
            callback(item.stage, item.fraction, item.message)

    return emit


def source_metadata_from_probe(
    info: DatasetInfo,
    *,
    selection: VolumeSelection,
    sha256: str,
    size_bytes: int,
) -> SourceMetadata:
    scene = info.scenes[selection.scene]
    shape = (
        (selection.z_stop or scene.zyx_shape[0]) - selection.z_start,
        scene.zyx_shape[1],
        scene.zyx_shape[2],
    )

    def calibration(axis: Any) -> CalibrationValue:
        source_map = {
            "native-structured-metadata": CalibrationSource.NATIVE,
            "ome-metadata": CalibrationSource.OME,
            "imagej-metadata": CalibrationSource.IMAGEJ,
            "manual": CalibrationSource.MANUAL,
        }
        return CalibrationValue(
            value=axis.value_um,
            source=source_map.get(str(axis.source), CalibrationSource.MISSING),
            confirmed=False,
        )

    channel_name = (
        scene.channel_names[selection.channel]
        if selection.channel < len(scene.channel_names)
        else None
    )
    return SourceMetadata(
        source_path=str(info.path),
        source_sha256=sha256,
        source_size_bytes=size_bytes,
        reader_name=info.reader_id,
        reader_version=__version__,
        source_format=info.source_format.value,
        original_axes=scene.source_axes,
        original_shape=scene.source_shape,
        selected_shape_zyx=shape,
        dtype=scene.dtype,
        significant_bits=scene.significant_bits,
        selection=SourceSelection(
            scene=selection.scene,
            time=selection.time,
            channel=selection.channel,
            z_start=selection.z_start,
            z_stop=selection.z_stop,
        ),
        calibration=VoxelCalibration(
            x=calibration(info.calibration.x),
            y=calibration(info.calibration.y),
            z=calibration(info.calibration.z),
        ),
        channel_name=channel_name,
        acquisition={"scene_name": scene.name},
        raw_metadata=model_to_dict(info.raw_metadata),
        warnings=tuple((*info.warnings, *scene.warnings)),
    )


def preflight_source(
    source_path: Path,
    *,
    project_path: Path,
    selection: VolumeSelection | None = None,
):
    """Probe metadata and produce a conservative resource plan without decoding all pixels."""

    selection = selection or VolumeSelection()
    reader = open_reader(source_path)
    info = reader.probe()
    shape = reader.selected_shape(selection)
    dtype = np.dtype(info.scenes[selection.scene].dtype)
    plan = preflight_cached_shape(
        shape,
        dtype=dtype,
        project_path=project_path,
        include_normalized_cache=True,
    )
    return info, plan


def preflight_cached_shape(
    shape_zyx: tuple[int, int, int],
    *,
    dtype: np.dtype[Any] | str,
    project_path: Path,
    include_normalized_cache: bool = False,
):
    """Resource plan for a selected cached volume and its scientific workspace."""

    voxel_count = int(np.prod(shape_zyx, dtype=np.int64))
    decoded_bytes = voxel_count * np.dtype(dtype).itemsize
    # Simultaneous no-compression high-water: normalized source cache,
    # bounded-memory workspace, temporary + published final mask during atomic
    # finalize, previews/metadata, 20% filesystem margin, and a 2 GiB reserve.
    normalized_cache_bytes = decoded_bytes if include_normalized_cache else 0
    large_workspace_bytes = math.ceil(voxel_count * 64 * 1.30)
    final_mask_atomic_bytes = 2 * voxel_count
    support_reserve_bytes = max(16 * 1024**2, decoded_bytes // 32)
    disk_required = math.ceil(
        1.20
        * (
            normalized_cache_bytes
            + large_workspace_bytes
            + final_mask_atomic_bytes
            + support_reserve_bytes
        )
        + 2 * 1024**3
    )
    plan = build_resource_plan(
        decoded_bytes=decoded_bytes,
        project_path=project_path,
        disk_required_bytes=disk_required,
        require_in_memory_fit=False,
    )
    return plan


def import_source(
    store: ProjectStore,
    *,
    source_path: Path,
    sample_name: str,
    selection: VolumeSelection | None = None,
    progress: ProgressCallback | None = None,
    cancelled: CancelCallback | None = None,
) -> ImportResult:
    """Create a complete verified project cache before publishing the sample row."""

    prepared = prepare_source_cache(
        store.paths.root,
        source_path=source_path,
        selection=selection,
        progress=progress,
        cancelled=cancelled,
    )
    publish_import(store, prepared=prepared, sample_name=sample_name)
    return prepared


def sample_volume(store: ProjectStore, sample_id: str):
    row = next((item for item in store.list_samples() if item["sample_id"] == sample_id), None)
    if row is None:
        raise KeyError(sample_id)
    if not row["cache_path"]:
        raise RuntimeError("sample has no normalized cache")
    return open_cached_volume(store.paths.root / row["cache_path"])


def analyze_sample(
    store: ProjectStore,
    *,
    sample_id: str,
    config: PipelineConfig,
    masks: PipelineMasks,
    progress: ProgressCallback | None = None,
    cancelled: CancelCallback | None = None,
    workspace_directory: Path | None = None,
) -> PipelineResult | OutOfCorePipelineResult:
    """Analyze the selected cache.  Small stacks are bounded in memory by preflight."""

    cached = sample_volume(store, sample_id)
    return analyze_cached_volume(
        cached,
        config=config,
        masks=masks,
        progress=progress,
        cancelled=cancelled,
        workspace_directory=workspace_directory,
    )


def analyze_cached_volume(
    cached: Any,
    *,
    config: PipelineConfig,
    masks: PipelineMasks,
    progress: ProgressCallback | None = None,
    cancelled: CancelCallback | None = None,
    workspace_directory: Path | None = None,
) -> PipelineResult | OutOfCorePipelineResult:
    """Select the exact reference or bounded-memory candidate execution path.

    Selection uses the documented source-byte amplification in
    :mod:`plug_analyzer.resources`. The out-of-core path always requires an
    explicit caller-owned workspace; it never writes into the current working
    directory. A completed out-of-core workspace contains the auditable result
    arrays and is not a resumable cancelled job.
    """

    shape = tuple(int(value) for value in cached.shape)
    dtype = np.dtype(cached.dtype)
    decoded_bytes = int(np.prod(shape, dtype=np.int64)) * dtype.itemsize
    project_path = (
        Path(workspace_directory).expanduser().resolve().parent
        if workspace_directory is not None
        else _cached_storage_path(cached)
    )
    memory = build_resource_plan(
        decoded_bytes=decoded_bytes,
        project_path=project_path,
        disk_required_bytes=0,
        stage_amplification=REFERENCE_PIPELINE_SOURCE_AMPLIFICATION,
    )
    reference_peak = math.ceil(decoded_bytes * REFERENCE_PIPELINE_SOURCE_AMPLIFICATION)
    if reference_peak > memory.memory_budget_bytes:
        if workspace_directory is None:
            raise ValueError(
                "workspace_directory is required when the bounded-memory analysis path is selected"
            )
        inventory = inspect_large_analysis(
            cached,
            config=config,
            workspace_parent=Path(workspace_directory).expanduser().resolve().parent,
        )
        if not inventory.disk_safe:
            raise OSError(
                "The project volume does not have enough worst-case free space for the "
                "bounded-memory analysis workspace."
            )
        return run_large_analysis(
            cached,
            masks=masks,
            config=config,
            workspace_directory=workspace_directory,
            progress=progress,
            cancelled=cancelled,
        )

    # Virtual geometry is materialized only after the reference path has passed
    # the conservative whole-volume memory check.
    concrete_masks = _materialize_masks(masks, shape)
    volume: NDArray[np.generic] = np.asarray(cached[:])
    return run_analysis(
        volume,
        masks=concrete_masks,
        config=config,
        progress=progress,
        cancelled=cancelled,
    )


def save_analysis(
    store: ProjectStore,
    *,
    sample_id: str,
    result: PipelineResult | OutOfCorePipelineResult,
):
    return finalize_project_run(store, sample_id=sample_id, result=result)


def _materialize_masks(masks: PipelineMasks, shape: tuple[int, int, int]) -> PipelineMasks:
    full = (slice(None), slice(None), slice(None))

    def materialize(value: Any | None) -> NDArray[np.bool_] | None:
        if value is None:
            return None
        if isinstance(value, np.ndarray):
            return value
        return np.asarray(value[full], dtype=np.bool_)

    return PipelineMasks(
        background=materialize(masks.background),  # type: ignore[arg-type]
        analysis=materialize(masks.analysis),  # type: ignore[arg-type]
        lumen=materialize(masks.lumen),  # type: ignore[arg-type]
        envelope=materialize(masks.envelope),
        geometry_source=masks.geometry_source,
    ).validated(shape)


def _cached_storage_path(cached: Any) -> Path:
    """Resolve local cache storage for read-only small-path disk accounting."""

    store = getattr(cached, "store", None)
    root = getattr(store, "root", None)
    if root is not None:
        return Path(root).expanduser().resolve()
    store_path = getattr(cached, "store_path", None)
    nested_store = getattr(store_path, "store", None)
    root = getattr(nested_store, "root", None)
    if root is not None:
        return Path(root).expanduser().resolve()
    raise ValueError(
        "workspace_directory is required when cached storage is not a discoverable local path"
    )


def project_manifest(store: ProjectStore) -> dict[str, Any]:
    """Visible, portable overview suitable for support and copy preparation."""

    return {
        "schema_version": 1,
        "app_version": __version__,
        "project": store.project_info(),
        "samples": [
            {key: value for key, value in row.items() if key not in {"metadata_json"}}
            for row in store.list_samples()
        ],
        "run_count": len(store.list_runs()),
    }


def write_project_manifest(store: ProjectStore) -> Path:
    destination = store.paths.root / "project-manifest.json"
    temporary = store.paths.work / "project-manifest.json.tmp"
    temporary.write_text(
        json.dumps(project_manifest(store), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(destination)
    return destination
