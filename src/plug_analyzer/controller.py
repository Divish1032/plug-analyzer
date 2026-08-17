"""Qt application controller for the complete local prototype workflow."""

from __future__ import annotations

import csv
import json
import os
import shutil
import threading
import traceback
from collections.abc import Callable, Mapping
from dataclasses import asdict, replace
from io import StringIO
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMessageBox

from plug_analyzer.baseline import prepare_registered_baseline, saturation_qc_bounded
from plug_analyzer.compatibility import assess_run_compatibility
from plug_analyzer.io import (
    ImportCancelled,
    VolumeSelection,
    fingerprint_source,
    open_cached_volume,
    open_reader,
)
from plug_analyzer.models import (
    CalibrationSource,
    CalibrationValue,
    VoxelCalibration,
)
from plug_analyzer.pipeline import (
    AnalysisCancelled,
    PipelineConfig,
    PipelineResult,
    RectangularRoi,
    RobustnessMode,
)
from plug_analyzer.project import PROJECT_SUFFIX, ProjectStore
from plug_analyzer.resources import SourceSnapshot, source_snapshot, source_unchanged
from plug_analyzer.service import (
    ImportResult,
    analyze_cached_volume,
    preflight_cached_shape,
    preflight_source,
    prepare_source_cache,
    publish_import,
    save_analysis,
    virtual_masks_from_geometry,
    write_project_manifest,
)
from plug_analyzer.ui import MainWindow
from plug_analyzer.ui.view_models import (
    AnalysisResultDisplay,
    ChoiceDisplay,
    CrossSectionSeries,
    MetricDisplay,
    NoticeLevel,
    PlaneSeries,
    PreflightSummary,
    SavedMetricComparisonDisplay,
    SourceSummary,
    StorageSummary,
    metric_label,
)

ProgressFunction = Callable[[str, float, str], None]
CancelFunction = Callable[[], bool]
TaskFunction = Callable[[ProgressFunction, CancelFunction], object]


class _TaskSignals(QObject):
    progress = Signal(int, str, str)
    result = Signal(object)
    error = Signal(str, str)
    cancelled = Signal(str)
    finished = Signal()


class _BackgroundTask(QRunnable):
    """One cooperative job; numeric libraries release the GIL for heavy stages."""

    def __init__(self, function: TaskFunction, cancel_event: threading.Event) -> None:
        super().__init__()
        self.function = function
        self.cancel_event = cancel_event
        self.signals = _TaskSignals()

    @Slot()
    def run(self) -> None:
        def progress(stage: str, fraction: float, detail: str) -> None:
            percent = max(0, min(100, round(100 * float(fraction))))
            self.signals.progress.emit(percent, stage, detail)

        try:
            result = self.function(progress, self.cancel_event.is_set)
        except (AnalysisCancelled, ImportCancelled, InterruptedError) as error:
            self.signals.cancelled.emit(str(error) or "Operation cancelled")
        except Exception as error:  # controller boundary reports an actionable message
            self.signals.error.emit(f"{type(error).__name__}: {error}", traceback.format_exc())
        else:
            self.signals.result.emit(result)
        finally:
            self.signals.finished.emit()


class ApplicationController(QObject):
    """Own mutable workflow state while domain and UI layers stay independent."""

    def __init__(self, window: MainWindow) -> None:
        super().__init__(window)
        self.window = window
        self.store: ProjectStore | None = None
        self.source_path: Path | None = None
        self.source_info: Any | None = None
        self.selection = VolumeSelection()
        self.current_sample_id: str | None = None
        self.current_sample_name = ""
        self.current_cache_relative: str | None = None
        self.current_result: Any | None = None
        self.current_config: PipelineConfig | None = None
        self.current_saved_run_id: str | None = None
        self.current_significant_bits = 16
        self._preflight_safe = False
        self._active_task: _BackgroundTask | None = None
        self._cancel_event: threading.Event | None = None
        self._next_action: Callable[[], None] | None = None
        self._pending_parameters: dict[str, Any] | None = None
        self._pending_sample_id: str | None = None
        self._inspected_source_snapshot: SourceSnapshot | None = None
        self._project_generation = 0
        self._close_requested = False
        self._thread_pool = QThreadPool.globalInstance()
        self._connect_signals()

    def _connect_signals(self) -> None:
        self.window.createProjectRequested.connect(self.create_project)
        self.window.openProjectRequested.connect(self.open_project)
        self.window.sourceImportRequested.connect(self.inspect_source)
        self.window.analyzeRequested.connect(self.start_analysis)
        self.window.cancelRequested.connect(self.cancel_active_task)
        self.window.saveResultRequested.connect(self.save_current_result)
        self.window.exportCsvRequested.connect(self.export_csv)
        self.window.exportJsonRequested.connect(self.export_json)
        self.window.exportPngRequested.connect(self.export_png)
        self.window.clearCacheRequested.connect(self.clear_cache)
        self.window.revealStorageRequested.connect(self.reveal_storage)
        self.window.planeRequested.connect(self.show_plane)
        self.window.orthogonalPositionRequested.connect(self.show_orthogonal)
        self.window.sampleSelectedRequested.connect(self.select_sample)
        self.window.savedRunsCompareRequested.connect(self.compare_saved_runs)
        self.window.dimensionSelectionChanged.connect(self.dimension_selection_changed)
        self.window.closing.connect(self.close)

    def _replace_state(self, **changes: Any) -> None:
        self.window.set_state(replace(self.window.state, **changes))

    @Slot(str)
    def create_project(self, path_text: str) -> None:
        if self._active_task is not None:
            self.window.show_error("Cancel the current operation before changing projects.")
            return
        try:
            path = Path(path_text).expanduser().resolve()
            if path.suffix != PROJECT_SUFFIX and path.exists() and any(path.iterdir()):
                raise ValueError(
                    "Choose an empty folder for a new project; existing files are never reused."
                )
            candidate = ProjectStore.create(path, name=path.stem or "Plug Analyzer Project")
            try:
                write_project_manifest(candidate)
            except Exception:
                candidate.close()
                raise
            self._close_store()
            self.store = candidate
            self._project_generation += 1
            self._reset_sample_state()
            self.window.set_project_path(path, status="Project created")
            self.window.show_notice(
                f"Project created at {path}. All generated data stays in this folder.",
                NoticeLevel.SUCCESS,
            )
            self.window.go_to_page("import")
            self._refresh_storage()
            self._refresh_project_choices()
            pending_count = len(tuple(self.store.paths.work.glob("pending-import-*.json")))
            if pending_count:
                self.window.show_notice(
                    f"Found {pending_count} interrupted import job(s). Reinspect the same source "
                    "file to resume its lossless cache.",
                    NoticeLevel.WARNING,
                )
        except Exception as error:
            self.window.show_error(str(error))

    @Slot(str)
    def open_project(self, path_text: str) -> None:
        if self._active_task is not None:
            self.window.show_error("Cancel the current operation before changing projects.")
            return
        try:
            path = Path(path_text).expanduser().resolve()
            if self.store is not None and self.store.paths.root == path:
                self.window.show_notice("That project is already open.", NoticeLevel.INFO)
                return
            try:
                candidate = ProjectStore.open(path)
                read_only = False
            except Exception as writable_error:
                # A live lock is useful information; opening read-only lets an SME
                # inspect a project without bypassing the single-writer rule.
                try:
                    candidate = ProjectStore.open(path, read_only=True)
                    read_only = True
                except Exception as read_only_error:
                    raise writable_error from read_only_error
            self._close_store()
            self.store = candidate
            self._project_generation += 1
            self._reset_sample_state()
            self.window.set_project_path(
                path,
                read_only=read_only,
                status="Project open read-only" if read_only else "Project opened",
            )
            samples = self.store.list_samples()
            if samples:
                self._load_sample_row(samples[-1])
            else:
                self.window.go_to_page("import")
            self._refresh_storage()
            self._refresh_project_choices()
            pending_count = len(tuple(self.store.paths.work.glob("pending-import-*.json")))
            if pending_count:
                self.window.show_notice(
                    f"Found {pending_count} interrupted import job(s). Reinspect the same source "
                    "file to resume its lossless cache.",
                    NoticeLevel.WARNING,
                )
        except Exception as error:
            self.window.show_error(str(error))

    def _load_sample_row(self, row: Mapping[str, Any]) -> None:
        assert self.store is not None
        self.window.clear_result()
        self.current_sample_id = str(row["sample_id"])
        self.current_sample_name = str(row["name"])
        self.current_cache_relative = row.get("cache_path")
        metadata = self.store.sample_metadata(self.current_sample_id)
        self.selection = VolumeSelection(
            scene=metadata.selection.scene,
            time=metadata.selection.time,
            channel=metadata.selection.channel,
            z_start=metadata.selection.z_start,
            z_stop=metadata.selection.z_stop,
        )
        self.window.set_source_selection(asdict(self.selection))
        self.source_path = Path(metadata.source_path)
        self._inspected_source_snapshot = (
            source_snapshot(self.source_path) if self.source_path.is_file() else None
        )
        self.source_info = None
        self.current_significant_bits = int(metadata.significant_bits or 16)
        self.window.set_source_path(self.source_path)
        self.window.set_source_summary(_source_summary_from_metadata(metadata))
        self.window.set_roi_overlays(self.window.analysis_parameters())
        plan = preflight_cached_shape(
            metadata.selected_shape_zyx,
            dtype=metadata.dtype,
            project_path=self.store.paths.root,
        )
        self._set_preflight(plan)
        cache_ready = bool(
            self.current_cache_relative
            and (self.store.paths.root / self.current_cache_relative).is_dir()
        )
        self._replace_state(
            source_path=self.source_path,
            source_ready=True,
            results_ready=bool(self.store.list_runs(self.current_sample_id)),
            status="Sample ready" if cache_ready else "Sample cache can be rebuilt",
        )
        self.window.set_plane_count(metadata.selected_shape_zyx[0])
        self.show_plane(0)
        self.window.go_to_page("analyze")

    @Slot(str)
    def inspect_source(self, path_text: str) -> None:
        if self.store is None:
            self.window.show_error("Create or open a project before inspecting a source.")
            return
        if self._active_task is not None:
            self.window.show_error("Wait for the current operation to finish.")
            return
        try:
            path = Path(path_text).expanduser().resolve()
            self.selection = VolumeSelection(**self.window.source_selection())
            info, plan = preflight_source(
                path,
                project_path=self.store.paths.root,
                selection=self.selection,
            )
            scene = info.scenes[self.selection.scene]
            selected_shape = open_reader(path).selected_shape(self.selection)
            self.window.set_dimension_limits(
                scene_count=info.scene_count,
                time_count=scene.time_count,
                channel_count=scene.channel_count,
                z_count=scene.zyx_shape[0],
            )
            self.source_path = path
            self._inspected_source_snapshot = source_snapshot(path)
            self._pending_sample_id = self._find_resumable_pending_import(path)
            self.source_info = info
            self.current_significant_bits = int(scene.significant_bits)
            self.current_sample_id = None
            self.current_sample_name = path.stem
            self.current_cache_relative = None
            self.current_result = None
            self.current_saved_run_id = None
            self._pending_parameters = None
            self.window.clear_result()
            self.window.set_source_path(path)
            self.window.set_source_summary(_source_summary_from_probe(info, self.selection))
            self.window.set_roi_overlays(self.window.analysis_parameters())
            self._set_preflight(plan)
            self._replace_state(
                source_path=path,
                source_ready=True,
                results_ready=False,
                status="Source inspected",
            )
            self.window.set_plane_count(selected_shape[0])
            self.show_plane(0)
            self.window.go_to_page("analyze")
            if plan.safe_to_start:
                resume_note = (
                    " An interrupted lossless import was found and will resume."
                    if self._pending_sample_id is not None
                    else ""
                )
                self.window.show_notice(
                    "Metadata and resource checks passed. Confirm calibration and ROIs before "
                    f"analysis; the source will be cached losslessly on first run.{resume_note}",
                    NoticeLevel.SUCCESS,
                )
        except Exception as error:
            self.window.show_error(str(error))

    @Slot(dict)
    def dimension_selection_changed(self, selection: dict[str, Any]) -> None:
        try:
            self.selection = VolumeSelection(**selection)
        except Exception as error:
            self.window.show_error(str(error))
            return
        self._preflight_safe = False
        self.current_result = None
        self.current_saved_run_id = None
        self.window.clear_result()
        self.window.invalidate_preflight("Selection changed; inspect this selection again.")
        self._replace_state(source_ready=False, status="Selection needs inspection")

    def _set_preflight(self, plan: Any) -> None:
        self._preflight_safe = bool(plan.safe_to_start)
        self.window.set_preflight(
            PreflightSummary(
                safe_to_start=plan.safe_to_start,
                available_memory_bytes=plan.available_memory_bytes,
                memory_budget_bytes=plan.memory_budget_bytes,
                disk_free_bytes=plan.disk_free_bytes,
                disk_required_bytes=plan.disk_required_bytes,
                compute_chunk_bytes=plan.compute_chunk_bytes,
                worker_threads=plan.worker_threads,
                warnings=plan.warnings,
            )
        )

    @Slot(dict)
    def start_analysis(self, parameters: dict[str, Any]) -> None:
        if self.store is None or self.source_path is None:
            self.window.show_error("Inspect a source inside an open project first.")
            return
        if self.store.read_only:
            self.window.show_error("This project is open read-only.")
            return
        if not self._preflight_safe:
            self.window.show_error("Resource preflight did not pass; analysis was not started.")
            return
        if self._active_task is not None:
            self.window.show_error("An operation is already running.")
            return
        self._pending_parameters = dict(parameters)
        self.current_result = None
        self.current_saved_run_id = None
        self.window.clear_result()
        if self._cache_path() is None:
            if self.current_sample_id is None and self._pending_sample_id is None:
                self._pending_sample_id = uuid4().hex
                self._record_pending_import()
            self._start_import()
        else:
            self._start_scientific_analysis()

    def _start_import(self) -> None:
        assert self.store is not None and self.source_path is not None
        project_root = self.store.paths.root
        source = self.source_path
        expected_snapshot = self._inspected_source_snapshot
        existing_id = self.current_sample_id or self._pending_sample_id
        generation = self._project_generation

        def task(progress: ProgressFunction, cancelled: CancelFunction) -> object:
            if expected_snapshot is None or not source_unchanged(source, expected_snapshot):
                raise RuntimeError(
                    "The source changed after preflight. Reinspect it before caching or analysis."
                )
            stage_ranges = {
                "fingerprint": (0.0, 0.10),
                "import": (0.10, 0.82),
                "verify": (0.82, 1.0),
            }

            def mapped(stage: str, fraction: float, detail: str) -> None:
                start, stop = stage_ranges.get(stage, (0.0, 1.0))
                progress(f"Cache: {stage}", start + (stop - start) * fraction, detail)

            return prepare_source_cache(
                project_root,
                source_path=source,
                selection=self.selection,
                sample_id=existing_id,
                progress=mapped,
                cancelled=cancelled,
            )

        self._start_task(
            task,
            lambda value: self._import_completed(value, generation=generation),
            status="Caching source losslessly",
        )

    def _import_completed(self, value: object, *, generation: int) -> None:
        assert isinstance(value, ImportResult)
        if generation != self._project_generation or self.store is None:
            raise RuntimeError("Project changed before import finalization.")
        if self.current_sample_id is None:
            if self.source_path is None or value.metadata.source_path != str(self.source_path):
                raise RuntimeError("Source selection changed after preflight.")
            if self._inspected_source_snapshot is None or not source_unchanged(
                self.source_path, self._inspected_source_snapshot
            ):
                raise RuntimeError(
                    "The source file changed after preflight. Reinspect it and reconfirm the "
                    "calibration and ROIs before analysis."
                )
            self._verify_import_matches_inspection(value)
            value = self._with_reviewed_calibration(value)
            publish_import(
                self.store,
                prepared=value,
                sample_name=self.current_sample_name or Path(value.metadata.source_path).stem,
            )
        else:
            stored = self.store.sample_metadata(self.current_sample_id)
            if (
                value.metadata.source_sha256 != stored.source_sha256
                or value.metadata.selected_shape_zyx != stored.selected_shape_zyx
                or np.dtype(value.metadata.dtype) != np.dtype(stored.dtype)
            ):
                raise RuntimeError(
                    "The source bytes or dimensions changed since this sample was created. "
                    "Import it as a new sample; the existing sample was not altered."
                )
            self.store.set_sample_cache(self.current_sample_id, value.cache_relative_path)
        self.current_sample_id = value.sample_id
        self.current_cache_relative = value.cache_relative_path
        self.current_significant_bits = int(value.metadata.significant_bits or 16)
        self._remove_pending_import_record(value.sample_id)
        self._pending_sample_id = None
        self._refresh_storage()
        self._refresh_project_choices()
        self._next_action = self._start_scientific_analysis

    def _verify_import_matches_inspection(self, prepared: ImportResult) -> None:
        """Compare reader metadata, independently of editable SME parameters."""

        if self.source_info is None:
            raise RuntimeError("Inspected source metadata is no longer available; reinspect it.")
        inspected_scene = self.source_info.scenes[self.selection.scene]
        imported = prepared.metadata
        expected_shape = (
            (self.selection.z_stop or inspected_scene.zyx_shape[0]) - self.selection.z_start,
            inspected_scene.zyx_shape[1],
            inspected_scene.zyx_shape[2],
        )
        if (
            imported.selected_shape_zyx != expected_shape
            or np.dtype(imported.dtype) != np.dtype(inspected_scene.dtype)
            or imported.significant_bits != inspected_scene.significant_bits
        ):
            raise RuntimeError(
                "Source dimensions, dtype, or significant-bit metadata changed after preflight. "
                "Reinspect the file before analysis."
            )
        expected_xyz = self.source_info.calibration.xyz_um
        actual_xyz = (
            imported.calibration.x.value,
            imported.calibration.y.value,
            imported.calibration.z.value,
        )
        for expected, actual in zip(expected_xyz, actual_xyz, strict=True):
            if (expected is None) != (actual is None) or (
                expected is not None
                and actual is not None
                and not np.isclose(expected, actual, rtol=1e-12, atol=1e-12)
            ):
                raise RuntimeError(
                    "Detected source calibration changed after preflight. Reinspect the file "
                    "before analysis."
                )

    def _with_reviewed_calibration(self, prepared: ImportResult) -> ImportResult:
        parameters = self._pending_parameters or {}
        reviewed = tuple(float(item) for item in parameters.get("calibration_xyz_um", ()))
        if len(reviewed) != 3 or not all(np.isfinite(item) and item > 0 for item in reviewed):
            raise RuntimeError("Reviewed calibration is missing or invalid after import.")
        detected = prepared.metadata.calibration

        def confirmed(value: float, original: CalibrationValue) -> CalibrationValue:
            matches_displayed_metadata = original.value is not None and np.isclose(
                value,
                original.value,
                rtol=1e-6,
                atol=5e-7,
            )
            return CalibrationValue(
                value=original.value if matches_displayed_metadata else value,
                source=original.source if matches_displayed_metadata else CalibrationSource.MANUAL,
                confirmed=True,
            )

        calibration = VoxelCalibration(
            x=confirmed(reviewed[0], detected.x),
            y=confirmed(reviewed[1], detected.y),
            z=confirmed(reviewed[2], detected.z),
            z_positions=detected.z_positions,
        )
        metadata = prepared.metadata.model_copy(update={"calibration": calibration})
        return replace(prepared, metadata=metadata)

    def _start_scientific_analysis(self) -> None:
        cache_path = self._cache_path()
        parameters = self._pending_parameters
        if cache_path is None or parameters is None:
            self.window.show_error("The verified cache or analysis parameters are missing.")
            return
        try:
            cached = open_cached_volume(cache_path)
            masks, config = _pipeline_inputs(
                tuple(cached.shape),
                parameters,
                significant_bits=self.current_significant_bits,
            )
        except Exception as error:
            self.window.show_error(str(error))
            return
        self.current_config = config
        if self.store is None or self.current_sample_id is None:
            self.window.show_error("Project or sample identity is missing.")
            return
        workspace = self.store.paths.work / f"analysis-{self.current_sample_id}-{uuid4().hex}"
        baseline_id = str(parameters.get("baseline_sample_id") or "")
        baseline_cache_path: Path | None = None
        baseline_audit_context: dict[str, Any] = {}
        if baseline_id:
            if not bool(parameters.get("baseline_reviewer_approved")):
                self.window.show_error(
                    "Confirm that the chosen pre-contact/post acquisition settings and geometry "
                    "match before registration."
                )
                return
            try:
                baseline_cache_path, baseline_audit_context = self._baseline_eligibility(
                    baseline_id
                )
            except Exception as error:
                self.window.show_error(str(error))
                return

        def task(progress: ProgressFunction, cancelled: CancelFunction) -> object:
            local_cache = open_cached_volume(cache_path)
            analysis_volume: Any = local_cache
            registration_audit: dict[str, Any] | None = None
            if baseline_cache_path is not None:
                progress("registration", 0.01, "Registering reviewed pre-contact baseline")
                baseline_cache = open_cached_volume(baseline_cache_path)
                prepared = prepare_registered_baseline(
                    local_cache,
                    baseline_cache,
                    masks.background,
                    spacing_zyx_um=config.spacing_zyx_um,
                )
                if not prepared.registration.accepted:
                    raise RuntimeError(
                        "Pre-contact registration failed automatic QC: "
                        + prepared.registration.reason
                    )
                analysis_volume = prepared.difference
                registration_audit = {
                    **baseline_audit_context,
                    "sampling_stride_zyx": list(prepared.sampling_stride_zyx),
                    "shift_zyx_pixels": list(prepared.registration.shift_zyx_pixels),
                    "shift_zyx_um": list(prepared.registration.shift_zyx_um),
                    "phase_error": prepared.registration.phase_error,
                    "overlap_fraction": prepared.registration.overlap_fraction,
                    "residual_nrmse": prepared.registration.residual_nrmse,
                    "interpolation": "trilinear baseline-to-post fixed grid",
                    "reviewer_approved_matching_acquisition": True,
                    "automatic_qc_accepted": True,
                }
            result = analyze_cached_volume(
                analysis_volume,
                config=config,
                masks=masks,
                progress=progress,
                cancelled=cancelled,
                workspace_directory=workspace,
            )
            if baseline_cache_path is not None:
                workspace.mkdir(parents=True, exist_ok=True)
                raw_saturation = saturation_qc_bounded(
                    local_cache,
                    result.plug_mask,
                    saturation_threshold=config.saturation_threshold,
                    workspace_directory=workspace,
                )
                retained_warnings = tuple(
                    warning for warning in result.warnings if "saturation threshold" not in warning
                )
                if raw_saturation.fraction > 0:
                    retained_warnings += (
                        f"{100 * raw_saturation.fraction:.4f}% of raw post-contact pixels meet "
                        "the saturation threshold.",
                    )
                result = replace(result, saturation=raw_saturation, warnings=retained_warnings)
            return result, registration_audit

        generation = self._project_generation
        sample_id = self.current_sample_id
        self._start_task(
            task,
            lambda value: self._analysis_completed(
                value,
                generation=generation,
                sample_id=sample_id,
            ),
            status="Running deterministic analysis",
        )

    def _analysis_completed(
        self,
        value: object,
        *,
        generation: int,
        sample_id: str | None,
    ) -> None:
        registration_audit: dict[str, Any] | None = None
        if isinstance(value, tuple) and len(value) == 2:
            value, registration_audit = value
        if not isinstance(value, PipelineResult) and not hasattr(value, "scalar_metrics"):
            raise TypeError("Analysis returned an unsupported result object.")
        if generation != self._project_generation or sample_id != self.current_sample_id:
            raise RuntimeError("Project or sample changed before analysis finalization.")
        reviewed_parameters = dict(getattr(value, "parameters", {}))
        reviewed_parameters["reviewed_geometry"] = {
            "analysis_roi_xywh_px": (self._pending_parameters or {}).get("analysis_roi_xywh_px"),
            "background_roi_xywh_px": (self._pending_parameters or {}).get(
                "background_roi_xywh_px"
            ),
            "envelope_roi_xywh_px": (self._pending_parameters or {}).get("envelope_roi_xywh_px"),
            "analysis_polygon_xy_px": (self._pending_parameters or {}).get(
                "analysis_polygon_xy_px"
            ),
            "background_polygon_xy_px": (self._pending_parameters or {}).get(
                "background_polygon_xy_px"
            ),
            "envelope_polygon_xy_px": (self._pending_parameters or {}).get(
                "envelope_polygon_xy_px"
            ),
            "axis_zyx": list(self.current_config.axis_zyx) if self.current_config else None,
            "reference_point_zyx_um": (
                list(self.current_config.reference_point_zyx_um) if self.current_config else None
            ),
        }
        reviewed_parameters["source_selection"] = asdict(self.selection)
        reviewed_parameters["calibration_confirmed"] = bool(
            (self._pending_parameters or {}).get("calibration_confirmed")
        )
        reviewed_parameters["correction_path"] = (
            "registered-pre-contact-subtraction"
            if registration_audit is not None
            else "reviewed-per-plane-background"
        )
        if registration_audit is not None:
            reviewed_parameters["pre_contact_registration"] = registration_audit
        try:
            value = replace(value, parameters=reviewed_parameters)
        except TypeError as error:
            raise TypeError(
                "Analysis result cannot preserve its reviewed parameter snapshot."
            ) from error
        self.current_result = value
        self.current_saved_run_id = None
        self.window.set_result(self._display_result(value, finalized=False))
        self.show_plane(self.window.viewer.current_z)
        self.window.show_notice(
            "Analysis finished. Review the red overlay and QC qualifications before saving.",
            NoticeLevel.SUCCESS,
        )
        self._refresh_storage()

    def _baseline_eligibility(self, baseline_id: str) -> tuple[Path, dict[str, Any]]:
        if self.store is None or self.current_sample_id is None:
            raise RuntimeError("Save/import the post-contact sample before choosing a baseline.")
        if baseline_id == self.current_sample_id:
            raise ValueError("A sample cannot be its own pre-contact baseline.")
        rows = {str(row["sample_id"]): row for row in self.store.list_samples()}
        baseline_row = rows.get(baseline_id)
        if baseline_row is None:
            raise KeyError("The selected pre-contact sample no longer exists.")
        relative = baseline_row.get("cache_path")
        if not relative:
            raise ValueError(
                "The selected pre-contact sample has no verified cache. Open and analyze/import "
                "that sample once before using it as a baseline."
            )
        cache_path = (self.store.paths.root / str(relative)).resolve()
        if (
            not cache_path.is_relative_to(self.store.paths.data.resolve())
            or not cache_path.is_dir()
        ):
            raise ValueError("The pre-contact cache is missing or outside project storage.")
        post = self.store.sample_metadata(self.current_sample_id)
        baseline = self.store.sample_metadata(baseline_id)
        if post.selected_shape_zyx != baseline.selected_shape_zyx:
            raise ValueError("Pre-contact and post-contact selections must have the same ZYX grid.")
        for axis in ("x", "y", "z"):
            post_value = getattr(post.calibration, axis).value
            baseline_value = getattr(baseline.calibration, axis).value
            if (
                post_value is None
                or baseline_value is None
                or not np.isclose(post_value, baseline_value, rtol=1e-9, atol=1e-12)
            ):
                raise ValueError(
                    f"Pre-contact {axis.upper()} calibration does not match post-contact."
                )
        if (post.channel_name or "").casefold() != (baseline.channel_name or "").casefold():
            raise ValueError("Pre-contact and post-contact fluorescence channels do not match.")
        post_context = self.store.sample_annotation(self.current_sample_id)
        baseline_context = self.store.sample_annotation(baseline_id)
        acquisition_fields = (
            "fluorophore",
            "objective",
            "laser_power",
            "detector_gain",
            "dwell_time",
            "pinhole",
            "averaging",
        )
        missing = [
            field
            for field in acquisition_fields
            if not getattr(post_context, field) or not getattr(baseline_context, field)
        ]
        if missing:
            raise ValueError(
                "Pre-contact subtraction requires recorded acquisition context: "
                + ", ".join(missing)
            )
        mismatched = [
            field
            for field in acquisition_fields
            if getattr(post_context, field).casefold()
            != getattr(baseline_context, field).casefold()
        ]
        if mismatched:
            raise ValueError("Pre-contact acquisition fields differ: " + ", ".join(mismatched))
        return cache_path, {
            "baseline_sample_id": baseline_id,
            "baseline_source_sha256": baseline.source_sha256,
        }

    def _display_result(self, result: Any, *, finalized: bool) -> AnalysisResultDisplay:
        assert self.current_config is not None
        run = result.to_finalized_run(
            sample_id=self.current_sample_id or "preview",
            artifacts={},
            run_id=self.current_saved_run_id or "Preview",
        )
        metrics = [
            MetricDisplay(
                name=metric_label(item.name),
                value=item.value,
                unit=item.unit or "",
                availability=item.availability.value,
                qualification=item.qualification or "",
            )
            for item in run.metrics
        ]
        if self.current_config.z_positions_um:
            z_um = self.current_config.z_positions_um
        else:
            z_um = tuple(
                index * self.current_config.spacing_zyx_um[0]
                for index in range(result.per_plane.area_um2.size)
            )
        return AnalysisResultDisplay(
            sample_name=self.current_sample_name or "Sample",
            run_id=self.current_saved_run_id or "Preview",
            metrics=tuple(metrics),
            planes=PlaneSeries(
                z_um=z_um,
                area_um2=result.per_plane.area_um2,
                integrated_intensity=result.per_plane.corrected_integrated_intensity_au,
            ),
            cross_sections=CrossSectionSeries(
                position_um=result.cross_section.bin_centers_um,
                occlusion_percent=result.cross_section.occlusion_percent,
                open_area_um2=result.cross_section.open_area_um2,
            ),
            protocol_label=(
                f"{self.current_config.protocol_id} {self.current_config.protocol_version}"
            ),
            qc_summary="; ".join(result.warnings) or "No automatic warnings",
            finalized=finalized,
        )

    def _start_task(
        self,
        function: TaskFunction,
        on_result: Callable[[object], None],
        *,
        status: str,
    ) -> None:
        if self._active_task is not None:
            self.window.show_error("An operation is already running.")
            return
        cancel = threading.Event()
        worker = _BackgroundTask(function, cancel)
        self._active_task = worker
        self._cancel_event = cancel
        worker.signals.progress.connect(self.window.set_analysis_progress)
        worker.signals.result.connect(lambda value: self._handle_task_result(on_result, value))
        worker.signals.error.connect(self._task_error)
        worker.signals.cancelled.connect(self._task_cancelled)
        worker.signals.finished.connect(lambda: self._task_finished(worker))
        self.window.set_analysis_running(True, status=status)
        self._thread_pool.start(worker)

    def _handle_task_result(
        self,
        callback: Callable[[object], None],
        value: object,
    ) -> None:
        try:
            callback(value)
        except Exception as error:
            self._task_error(
                f"{type(error).__name__}: {error}",
                traceback.format_exc(),
            )

    @Slot(str, str)
    def _task_error(self, message: str, details: str) -> None:
        self._next_action = None
        if self._pending_sample_id is not None and not self._pending_import_has_cache(
            self._pending_sample_id
        ):
            self._remove_pending_import_record(self._pending_sample_id)
            self._pending_sample_id = None
        self.window.show_error(message)
        if self.store is not None:
            log = self.store.paths.logs / "last-error.log"
            log.write_text(details, encoding="utf-8")

    @Slot(str)
    def _task_cancelled(self, message: str) -> None:
        self._next_action = None
        self.window.show_notice(message or "Operation cancelled", NoticeLevel.WARNING)

    def _task_finished(self, worker: _BackgroundTask) -> None:
        if self._active_task is not worker:
            return
        self._active_task = None
        self._cancel_event = None
        next_action = self._next_action
        self._next_action = None
        if self._close_requested:
            self._close_store()
            self._close_requested = False
            QTimer.singleShot(0, self.window.close)
            return
        if next_action is None:
            self.window.set_analysis_running(False, status="Ready")
        else:
            QTimer.singleShot(0, next_action)

    @Slot()
    def cancel_active_task(self) -> None:
        if self._cancel_event is not None:
            self._cancel_event.set()
            self.window.set_analysis_progress(
                None, "Cancelling", "Waiting for a safe stage boundary"
            )

    @Slot()
    def save_current_result(self) -> None:
        if self.store is None or self.current_result is None or self.current_sample_id is None:
            self.window.show_error("There is no reviewed result to save.")
            return
        if self.current_saved_run_id is not None:
            self.window.show_notice("This result is already saved and immutable.", NoticeLevel.INFO)
            return
        try:
            finalized = save_analysis(
                self.store,
                sample_id=self.current_sample_id,
                result=self.current_result,
            )
            self.current_saved_run_id = finalized.run_id
            write_project_manifest(self.store)
            self.window.set_result(self._display_result(self.current_result, finalized=True))
            self.window.show_notice("Analysis saved as an immutable run.", NoticeLevel.SUCCESS)
            self._refresh_storage()
            self._refresh_project_choices()
        except Exception as error:
            self.window.show_error(str(error))

    @Slot(str)
    def export_csv(self, path_text: str) -> None:
        if self.current_result is None:
            self.window.show_error("Run an analysis before exporting.")
            return
        try:
            plane = self.current_result.per_plane
            buffer = StringIO(newline="")
            writer = csv.writer(buffer, lineterminator="\n")
            writer.writerow(
                (
                    "z_index",
                    "area_um2",
                    "corrected_integrated_intensity_au",
                    "fluorescence_area_integral_au_um2",
                    "mean_corrected_intensity_au",
                )
            )
            writer.writerows(
                zip(
                    range(plane.area_um2.size),
                    plane.area_um2,
                    plane.corrected_integrated_intensity_au,
                    plane.fluorescence_area_integral_au_um2,
                    plane.mean_corrected_intensity_au,
                    strict=True,
                )
            )
            _atomic_user_export(Path(path_text), buffer.getvalue())
            self.window.show_notice(f"CSV exported to {path_text}", NoticeLevel.SUCCESS)
        except Exception as error:
            self.window.show_error(str(error))

    @Slot(str)
    def export_json(self, path_text: str) -> None:
        if self.current_result is None:
            self.window.show_error("Run an analysis before exporting.")
            return
        try:
            text = json.dumps(
                self.current_result.summary_dict(),
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
                allow_nan=False,
            )
            _atomic_user_export(Path(path_text), f"{text}\n")
            self.window.show_notice(f"JSON exported to {path_text}", NoticeLevel.SUCCESS)
        except Exception as error:
            self.window.show_error(str(error))

    @Slot(str)
    def export_png(self, path_text: str) -> None:
        if self.current_result is None:
            self.window.show_error("Run an analysis before exporting a figure.")
            return
        path = Path(path_text).expanduser().resolve()
        if path.suffix.casefold() != ".png":
            path = path.with_suffix(".png")
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp.png")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            image = self.window.result_charts.grab().toImage()
            if image.isNull() or not image.save(str(temporary), "PNG"):
                raise RuntimeError("Qt could not render the result charts as PNG.")
            os.replace(temporary, path)
            self.window.show_notice(f"Figure exported to {path}", NoticeLevel.SUCCESS)
        except Exception as error:
            temporary.unlink(missing_ok=True)
            self.window.show_error(str(error))

    @Slot(str)
    def select_sample(self, sample_id: str) -> None:
        if self.store is None or self._active_task is not None:
            return
        row = next(
            (item for item in self.store.list_samples() if item["sample_id"] == sample_id),
            None,
        )
        if row is None:
            self.window.show_error(f"Unknown sample: {sample_id}")
            return
        try:
            self.current_result = None
            self.current_config = None
            self.current_saved_run_id = None
            self.window.clear_result()
            self._load_sample_row(row)
            self._refresh_project_choices()
        except Exception as error:
            self.window.show_error(str(error))

    @Slot(str, str)
    def compare_saved_runs(self, left_id: str, right_id: str) -> None:
        if self.store is None:
            return
        runs = {run.run_id: run for run in self.store.list_runs()}
        left = runs.get(left_id)
        right = runs.get(right_id)
        if left is None or right is None:
            self.window.show_error("One of the selected saved runs no longer exists.")
            return
        compatibility = assess_run_compatibility(
            left,
            right,
            left_source=self.store.sample_metadata(left.sample_id),
            right_source=self.store.sample_metadata(right.sample_id),
        )
        left_metrics = {metric.name: metric for metric in left.metrics}
        right_metrics = {metric.name: metric for metric in right.metrics}
        rows: list[SavedMetricComparisonDisplay] = []
        for name in sorted(set(left_metrics) | set(right_metrics)):
            left_metric = left_metrics.get(name)
            right_metric = right_metrics.get(name)
            left_value = left_metric.value if left_metric else None
            right_value = right_metric.value if right_metric else None
            metric_allowed = compatibility.metric_allowed(name)
            difference = (
                float(right_value) - float(left_value)
                if isinstance(left_value, (int, float))
                and not isinstance(left_value, bool)
                and isinstance(right_value, (int, float))
                and not isinstance(right_value, bool)
                and metric_allowed
                else None
            )
            unit = (left_metric.unit if left_metric else None) or (
                right_metric.unit if right_metric else None
            )
            if not metric_allowed:
                difference = None
                qualification = compatibility.summary
            elif (
                left_metric is not None
                and right_metric is not None
                and left_metric.unit != right_metric.unit
            ):
                difference = None
                qualification = "Units differ, so change is not shown."
            else:
                qualification = "; ".join(
                    dict.fromkeys(
                        item
                        for item in (
                            left_metric.qualification if left_metric else None,
                            right_metric.qualification if right_metric else None,
                        )
                        if item
                    )
                )
            rows.append(
                SavedMetricComparisonDisplay(
                    metric_name=name,
                    left_value=left_value,
                    right_value=right_value,
                    unit=unit or "",
                    difference=difference,
                    qualification=qualification,
                )
            )
        self.window.set_saved_run_comparison(rows, compatibility=compatibility.summary)

    @Slot(int)
    def show_plane(self, z_index: int) -> None:
        try:
            if self.current_cache_relative and self.store is not None:
                cached = open_cached_volume(self.store.paths.root / self.current_cache_relative)
                plane = np.asarray(cached[z_index])
                count = cached.shape[0]
            elif self.source_path is not None:
                reader = open_reader(self.source_path)
                plane = reader.read_plane(self.selection, z_index)
                count = reader.selected_shape(self.selection)[0]
            else:
                return
            mask = (
                self.current_result.plug_mask[z_index] if self.current_result is not None else None
            )
            uncertainty = (
                self.current_result.uncertainty_mask[z_index]
                if self.current_result is not None
                else None
            )
            self.window.set_plane(
                plane,
                mask,
                uncertainty,
                z_index=z_index,
                plane_count=int(count),
            )
        except Exception as error:
            self.window.show_error(str(error))

    @Slot(int, int)
    def show_orthogonal(self, x_index: int, y_index: int) -> None:
        try:
            if self.current_cache_relative and self.store is not None:
                volume = open_cached_volume(self.store.paths.root / self.current_cache_relative)
                xz = np.asarray(volume[:, y_index, :])
                yz = np.asarray(volume[:, :, x_index])
            elif self.source_path is not None:
                reader = open_reader(self.source_path)
                shape = reader.selected_shape(self.selection)
                xz = reader.read_region(
                    self.selection,
                    (slice(0, shape[0]), slice(y_index, y_index + 1), slice(0, shape[2])),
                )[:, 0, :]
                yz = reader.read_region(
                    self.selection,
                    (slice(0, shape[0]), slice(0, shape[1]), slice(x_index, x_index + 1)),
                )[:, :, 0]
            else:
                return
            if self.current_result is None:
                xz_mask = yz_mask = xz_uncertainty = yz_uncertainty = None
            else:
                xz_mask = np.asarray(self.current_result.plug_mask[:, y_index, :])
                yz_mask = np.asarray(self.current_result.plug_mask[:, :, x_index])
                xz_uncertainty = np.asarray(self.current_result.uncertainty_mask[:, y_index, :])
                yz_uncertainty = np.asarray(self.current_result.uncertainty_mask[:, :, x_index])
            self.window.set_orthogonal(
                xz,
                yz,
                xz_mask,
                yz_mask,
                xz_uncertainty,
                yz_uncertainty,
            )
        except Exception as error:
            self.window.show_error(str(error))

    @Slot(str)
    def reveal_storage(self, path_text: str) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path_text).resolve())))

    @Slot()
    def clear_cache(self) -> None:
        cache_path = self._cache_path()
        if cache_path is None or self.store is None or self.current_sample_id is None:
            self.window.show_notice("This sample has no rebuildable cache.", NoticeLevel.INFO)
            return
        resolved = cache_path.resolve()
        if resolved.parent != self.store.paths.data.resolve():
            self.window.show_error("Refusing to clear a cache outside the project data folder.")
            return
        metadata = self.store.sample_metadata(self.current_sample_id)
        source = Path(metadata.source_path)
        if not source.is_file():
            self.window.show_error(
                "Cache deletion is blocked because the original source is missing; this cache "
                "may be the only valid voxel copy."
            )
            return
        answer = QMessageBox.question(
            self.window,
            "Clear rebuildable cache?",
            f"Verify the original source, then delete this cache only?\n\n{resolved}\n\n"
            "The checksum check runs in the background. Saved results remain, and analysis must "
            "rebuild the cache.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        generation = self._project_generation
        sample_id = self.current_sample_id
        expected_sha256 = metadata.source_sha256

        def task(progress: ProgressFunction, cancelled: CancelFunction) -> object:
            def report(item: Any) -> None:
                progress("Verify source", item.fraction, item.message)

            fingerprint = fingerprint_source(
                source,
                progress=report,
                should_cancel=cancelled,
            )
            if fingerprint.sha256 != expected_sha256:
                raise RuntimeError(
                    "Cache deletion is blocked because the original source checksum no longer "
                    "matches this sample."
                )
            if cancelled():
                raise InterruptedError("Cache deletion cancelled before removal.")
            shutil.rmtree(resolved)
            return resolved

        def completed(value: object) -> None:
            if (
                generation != self._project_generation
                or self.store is None
                or sample_id != self.current_sample_id
            ):
                raise RuntimeError("Project or sample changed before cache finalization.")
            self.store.set_sample_cache(self.current_sample_id, None)
            self.current_cache_relative = None
            self.current_result = None
            self.window.clear_result()
            self._replace_state(results_ready=False, status="Cache cleared")
            self.window.show_notice(
                f"Removed rebuildable cache {value}. It is not recoverable, but can be rebuilt "
                "from the source file.",
                NoticeLevel.WARNING,
            )
            self._refresh_storage()

        self._start_task(task, completed, status="Verifying source before cache deletion")

    def _cache_path(self) -> Path | None:
        if self.store is None or not self.current_cache_relative:
            return None
        path = self.store.paths.root / self.current_cache_relative
        return path if path.is_dir() else None

    def _pending_import_record_path(self, sample_id: str) -> Path:
        if self.store is None:
            raise RuntimeError("No project is open.")
        return self.store.paths.work / f"pending-import-{sample_id}.json"

    def _record_pending_import(self) -> None:
        if (
            self.store is None
            or self.source_path is None
            or self._pending_sample_id is None
            or self._inspected_source_snapshot is None
        ):
            raise RuntimeError("Pending import identity is incomplete.")
        destination = self._pending_import_record_path(self._pending_sample_id)
        temporary = destination.with_suffix(".json.tmp")
        payload = {
            "schema_version": 1,
            "sample_id": self._pending_sample_id,
            "sample_name": self.current_sample_name,
            "source_path": str(self.source_path),
            "source_snapshot": asdict(self._inspected_source_snapshot),
            "selection": asdict(self.selection),
        }
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        temporary.replace(destination)

    def _find_resumable_pending_import(self, source: Path) -> str | None:
        if self.store is None:
            return None
        current = source_snapshot(source)
        expected_selection = asdict(self.selection)
        for record in sorted(self.store.paths.work.glob("pending-import-*.json")):
            try:
                payload = json.loads(record.read_text(encoding="utf-8"))
                identifier = str(payload["sample_id"])
                snapshot = SourceSnapshot(**payload["source_snapshot"])
                matches = (
                    int(payload.get("schema_version", 0)) == 1
                    and Path(payload["source_path"]).resolve() == source
                    and snapshot == current
                    and payload["selection"] == expected_selection
                    and record.name == f"pending-import-{identifier}.json"
                )
            except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue
            if matches:
                self.current_sample_name = str(payload.get("sample_name") or source.stem)
                return identifier
        return None

    def _remove_pending_import_record(self, sample_id: str) -> None:
        if self.store is not None:
            self._pending_import_record_path(sample_id).unlink(missing_ok=True)

    def _pending_import_has_cache(self, sample_id: str) -> bool:
        if self.store is None:
            return False
        target = self.store.paths.data / sample_id
        return target.is_dir() or target.with_name(f"{target.name}.partial").is_dir()

    def _refresh_storage(self) -> None:
        if self.store is None:
            return
        paths = self.store.paths
        self.window.set_storage_summary(
            StorageSummary(
                project_path=paths.root,
                source_bytes=_tree_bytes(paths.sources),
                cache_bytes=_tree_bytes(paths.data) + _tree_bytes(paths.work),
                result_bytes=(_tree_bytes(paths.runs) + _tree_bytes(paths.exports)),
                other_bytes=_file_bytes(paths.database) + _tree_bytes(paths.logs),
            )
        )

    def _refresh_project_choices(self) -> None:
        if self.store is None:
            self.window.set_sample_choices(())
            self.window.set_saved_run_choices(())
            return
        samples = self.store.list_samples()
        sample_names = {str(row["sample_id"]): str(row["name"]) for row in samples}
        self.window.set_sample_choices(
            tuple(
                ChoiceDisplay(identifier=identifier, label=name)
                for identifier, name in sample_names.items()
            ),
            current_identifier=self.current_sample_id,
        )
        runs = self.store.list_runs()
        self.window.set_saved_run_choices(
            tuple(
                ChoiceDisplay(
                    identifier=run.run_id,
                    label=(
                        f"{sample_names.get(run.sample_id, run.sample_id)} · "
                        f"{run.finalized_at.astimezone().strftime('%Y-%m-%d %H:%M')} · "
                        f"{run.run_id[:8]}"
                    ),
                )
                for run in runs
            )
        )

    def _reset_sample_state(self) -> None:
        self.source_path = None
        self.source_info = None
        self.current_sample_id = None
        self.current_sample_name = ""
        self.current_cache_relative = None
        self.current_result = None
        self.current_config = None
        self.current_saved_run_id = None
        self.current_significant_bits = 16
        self._preflight_safe = False
        self._pending_sample_id = None
        self._pending_parameters = None
        self._inspected_source_snapshot = None

    @Slot()
    def close(self) -> None:
        self.request_close()

    def request_close(self) -> bool:
        """Cancel active work and report whether the window may close now."""

        if self._active_task is not None:
            self._close_requested = True
            self._next_action = None
            if self._cancel_event is not None:
                self._cancel_event.set()
            self.window.show_notice(
                "Cancellation requested. The project will close after the worker reaches a safe "
                "stage boundary.",
                NoticeLevel.WARNING,
            )
            return False
        self._close_store()
        return True

    def _close_store(self) -> None:
        if self.store is not None:
            self.store.close()
            self.store = None


def _source_summary_from_probe(info: Any, selection: VolumeSelection) -> SourceSummary:
    scene = info.scenes[selection.scene]
    channel = (
        scene.channel_names[selection.channel]
        if selection.channel < len(scene.channel_names)
        else f"Channel {selection.channel + 1}"
    )
    sources = {
        str(axis.source) for axis in (info.calibration.x, info.calibration.y, info.calibration.z)
    }
    z_stop = selection.z_stop or scene.zyx_shape[0]
    selected_shape = (z_stop - selection.z_start, scene.zyx_shape[1], scene.zyx_shape[2])
    return SourceSummary(
        filename=info.path.name,
        source_format=info.source_format.value,
        dimensions_zyx=selected_shape,
        dtype=np.dtype(scene.dtype).name,
        channel=channel,
        calibration_xyz_um=info.calibration.xyz_um,
        calibration_source=", ".join(sorted(sources)),
        reader=info.reader_id,
        warnings=tuple((*info.warnings, *scene.warnings)),
        extra={
            "Selected scene": selection.scene,
            "Available scenes": info.scene_count,
            "Time points": scene.time_count,
            "Channels": scene.channel_count,
            "Selected Z range": (
                f"{selection.z_start}:{selection.z_stop}"
                if selection.z_stop is not None
                else f"{selection.z_start}:all"
            ),
            "Significant bits": scene.significant_bits,
        },
    )


def _source_summary_from_metadata(metadata: Any) -> SourceSummary:
    calibration = metadata.calibration
    return SourceSummary(
        filename=Path(metadata.source_path).name,
        source_format=metadata.source_format,
        dimensions_zyx=metadata.selected_shape_zyx,
        dtype=np.dtype(metadata.dtype).name,
        channel=metadata.channel_name or "Channel 1",
        calibration_xyz_um=(
            calibration.x.value,
            calibration.y.value,
            calibration.z.value,
        ),
        calibration_source=", ".join(
            sorted({item.source.value for item in (calibration.x, calibration.y, calibration.z)})
        ),
        reader=metadata.reader_name,
        warnings=metadata.warnings,
        extra={"Significant bits": metadata.significant_bits or "Unknown"},
    )


def _roi_from_xywh(
    data: Mapping[str, Any],
    shape: tuple[int, int, int],
) -> RectangularRoi:
    _, height, width = shape
    x = int(data.get("x", 0))
    y = int(data.get("y", 0))
    roi_width = int(data.get("width", 0)) or width - x
    roi_height = int(data.get("height", 0)) or height - y
    return RectangularRoi(y, y + roi_height, x, x + roi_width)


def _pipeline_inputs(
    shape: tuple[int, int, int],
    parameters: Mapping[str, Any],
    *,
    significant_bits: int,
):
    calibration = tuple(float(value) for value in parameters["calibration_xyz_um"])
    x_um, y_um, z_um = calibration
    analysis = _roi_from_xywh(parameters.get("analysis_roi_xywh_px", {}), shape)
    background_data = parameters.get("background_roi_xywh_px", {})
    if not int(background_data.get("width", 0)) and not int(background_data.get("height", 0)):
        band = max(1, shape[1] // 10)
        background = RectangularRoi(0, band, 0, shape[2])
    else:
        background = _roi_from_xywh(background_data, shape)
    envelope_data = parameters.get("envelope_roi_xywh_px", {})
    envelope = (
        _roi_from_xywh(envelope_data, shape)
        if int(envelope_data.get("width", 0)) > 0 and int(envelope_data.get("height", 0)) > 0
        else None
    )

    def vertices(key: str) -> tuple[tuple[float, float], ...]:
        return tuple(
            tuple(float(coordinate) for coordinate in point) for point in parameters.get(key, ())
        )  # type: ignore[return-value]

    analysis_polygon = vertices("analysis_polygon_xy_px")
    masks = virtual_masks_from_geometry(
        shape,
        background_rois=(background,),
        analysis_roi=analysis,
        lumen_roi=analysis,
        envelope_roi=envelope,
        background_polygon_xy=vertices("background_polygon_xy_px"),
        analysis_polygon_xy=analysis_polygon,
        lumen_polygon_xy=analysis_polygon,
        envelope_polygon_xy=vertices("envelope_polygon_xy_px"),
    )
    if not 1 <= significant_bits <= 64:
        raise ValueError("significant_bits must be between 1 and 64")
    saturation = float((1 << significant_bits) - 1)
    config = PipelineConfig(
        spacing_zyx_um=(z_um, y_um, x_um),
        filter_sigma_um=float(parameters["smoothing_sigma_um"]),
        low_noise_multiplier=float(parameters["low_threshold_sigma"]),
        high_noise_multiplier=float(parameters["high_threshold_sigma"]),
        minimum_component_volume_um3=float(parameters["minimum_component_volume_um3"]),
        min_reference_pixels_per_plane=1_000,
        saturation_threshold=saturation,
        axis_zyx=(0.0, 0.0, 1.0),
        reference_point_zyx_um=(0.0, 0.0, analysis.x_start * x_um),
        robustness_mode=RobustnessMode.STANDARD,
    )
    return masks, config


def _atomic_user_export(path: Path, text: str) -> None:
    destination = path.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(destination)


def _tree_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(
        item.stat().st_size for item in path.rglob("*") if item.is_file() and not item.is_symlink()
    )


def _file_bytes(path: Path) -> int:
    return path.stat().st_size if path.is_file() else 0


def connect_main_window(window: MainWindow) -> ApplicationController:
    """Default application factory used by source and packaged GUI launches."""

    return ApplicationController(window)
