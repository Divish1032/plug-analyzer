from __future__ import annotations

import shutil
from pathlib import Path
from uuid import uuid4

import numpy as np
import tifffile

from plug_analyzer.controller import ApplicationController
from plug_analyzer.io import fingerprint_source
from plug_analyzer.models import SampleAnnotation
from plug_analyzer.ui import MainWindow


def _source(path: Path, *, signal: int) -> None:
    image = np.full((3, 210, 80), 10, dtype=np.uint16)
    coordinates = np.indices((3, 210, 15))
    stable_pattern = (
        20 + (np.indices((3, 210, 15)).sum(axis=0) * 7 + np.indices((3, 210, 15))[1] ** 2) % 17
    )
    if signal >= 50:
        stable_pattern = stable_pattern + ((coordinates[0] + coordinates[1]) % 3) - 1
    image[:, :, 0:15] = stable_pattern.astype(np.uint16)
    image[:, 70:130, 35:55] = signal
    tifffile.imwrite(
        path,
        image,
        imagej=True,
        metadata={"axes": "ZYX", "spacing": 2.0, "unit": "um"},
        resolution=(1, 1),
    )


def _two_channel_source(path: Path) -> None:
    image = np.full((2, 3, 210, 80), 10, dtype=np.uint16)
    image[:, :, :, 0:5] = 9
    image[:, :, :, 10:15] = 11
    image[0, :, 70:130, 35:55] = 70
    image[1, :, 70:130, 35:55] = 140
    tifffile.imwrite(
        path,
        image,
        ome=True,
        metadata={
            "axes": "CZYX",
            "PhysicalSizeX": 1.0,
            "PhysicalSizeXUnit": "µm",
            "PhysicalSizeY": 1.0,
            "PhysicalSizeYUnit": "µm",
            "PhysicalSizeZ": 2.0,
            "PhysicalSizeZUnit": "µm",
            "Channel": {"Name": ["weak", "strong"]},
        },
    )


def _parameters() -> dict[str, object]:
    return {
        "calibration_xyz_um": (1.0, 1.0, 2.0),
        "calibration_confirmed": True,
        "analysis_roi_xywh_px": {"x": 20, "y": 0, "width": 60, "height": 210},
        "background_roi_xywh_px": {"x": 0, "y": 0, "width": 15, "height": 210},
        "envelope_roi_xywh_px": {"x": 35, "y": 70, "width": 20, "height": 60},
        "low_threshold_sigma": 2.0,
        "high_threshold_sigma": 4.0,
        "smoothing_sigma_um": 0.0,
        "minimum_component_volume_um3": 1.0,
    }


def test_controller_import_analyze_save_and_cross_sample_compare(
    qtbot,
    tmp_path: Path,
) -> None:
    first_source = tmp_path / "weak.tif"
    second_source = tmp_path / "strong.tif"
    _source(first_source, signal=80)
    _source(second_source, signal=120)
    window = MainWindow()
    qtbot.addWidget(window)
    controller = ApplicationController(window)
    project = tmp_path / "study.plug-project"

    controller.create_project(str(project))
    controller.inspect_source(str(first_source))
    assert window.state.source_ready
    assert window.viewer.plane_count == 3
    controller.start_analysis(_parameters())
    qtbot.waitUntil(lambda: controller.current_result is not None, timeout=30_000)
    qtbot.waitUntil(lambda: controller._active_task is None, timeout=5_000)
    controller.save_current_result()
    first_run = controller.current_saved_run_id
    assert first_run is not None

    controller.inspect_source(str(second_source))
    controller.start_analysis(_parameters())
    qtbot.waitUntil(lambda: controller.current_result is not None, timeout=30_000)
    qtbot.waitUntil(lambda: controller._active_task is None, timeout=5_000)
    controller.save_current_result()
    second_run = controller.current_saved_run_id
    assert second_run is not None and second_run != first_run

    assert controller.store is not None
    assert len(controller.store.list_samples()) == 2
    assert len(controller.store.list_runs()) == 2
    assert window.sample_selector.count() == 2
    assert window.left_run_selector.count() == 2
    controller.compare_saved_runs(first_run, second_run)
    assert window.saved_run_comparison_table.rowCount() >= 7
    metric_names = {
        window.saved_run_comparison_table.item(row, 0).text()
        for row in range(window.saved_run_comparison_table.rowCount())
    }
    assert "Observed plug volume" in metric_names
    assert "Corrected integrated intensity" in metric_names
    intensity_row = next(
        row
        for row in range(window.saved_run_comparison_table.rowCount())
        if window.saved_run_comparison_table.item(row, 0).text() == "Corrected integrated intensity"
    )
    assert window.saved_run_comparison_table.item(intensity_row, 3).text() != "Not available"
    assert "same method" in window.compatibility_label.text().casefold()
    controller.close()


def test_pre_contact_registration_is_available_in_normal_gui_workflow(
    qtbot, tmp_path: Path
) -> None:
    baseline_source = tmp_path / "baseline.tif"
    post_source = tmp_path / "post.tif"
    _source(baseline_source, signal=20)
    _source(post_source, signal=90)
    window = MainWindow()
    qtbot.addWidget(window)
    controller = ApplicationController(window)
    controller.create_project(str(tmp_path / "paired.plug-project"))
    acquisition = {
        "fluorophore": "FITC",
        "objective": "20x",
        "laser_power": "2%",
        "detector_gain": "100",
        "dwell_time": "1 us",
        "pinhole": "1 AU",
        "averaging": "2",
    }

    controller.inspect_source(str(baseline_source))
    controller.start_analysis(_parameters())
    qtbot.waitUntil(lambda: controller.current_result is not None, timeout=30_000)
    qtbot.waitUntil(lambda: controller._active_task is None, timeout=5_000)
    baseline_id = controller.current_sample_id
    assert baseline_id is not None
    assert controller.store is not None
    controller.store.set_sample_annotation(baseline_id, SampleAnnotation(**acquisition))

    controller.inspect_source(str(post_source))
    controller.start_analysis(_parameters())
    qtbot.waitUntil(lambda: controller.current_result is not None, timeout=30_000)
    qtbot.waitUntil(lambda: controller._active_task is None, timeout=5_000)
    assert controller.current_sample_id is not None
    controller.store.set_sample_annotation(
        controller.current_sample_id, SampleAnnotation(**acquisition)
    )

    paired = _parameters()
    paired["baseline_sample_id"] = baseline_id
    paired["baseline_reviewer_approved"] = True
    controller.start_analysis(paired)
    qtbot.waitUntil(lambda: controller.current_result is not None, timeout=30_000)
    qtbot.waitUntil(lambda: controller._active_task is None, timeout=5_000)
    assert controller.current_result.parameters["correction_path"] == (
        "registered-pre-contact-subtraction"
    )
    registration = controller.current_result.parameters["pre_contact_registration"]
    assert registration["automatic_qc_accepted"]
    assert registration["baseline_sample_id"] == baseline_id
    controller.close()


def test_source_change_is_blocked_when_rebuilding_existing_sample(
    qtbot,
    tmp_path: Path,
) -> None:
    source = tmp_path / "sample.tif"
    _source(source, signal=80)
    window = MainWindow()
    qtbot.addWidget(window)
    controller = ApplicationController(window)
    controller.create_project(str(tmp_path / "study.plug-project"))
    controller.inspect_source(str(source))
    controller.start_analysis(_parameters())
    qtbot.waitUntil(lambda: controller.current_result is not None, timeout=30_000)
    qtbot.waitUntil(lambda: controller._active_task is None, timeout=5_000)
    original_sample = controller.current_sample_id
    assert controller.store is not None and original_sample is not None
    old_metadata = controller.store.sample_metadata(original_sample)
    cache_path = controller._cache_path()
    assert cache_path is not None
    # Simulate a verified cache removal, then replace the file at the same path.
    shutil.rmtree(cache_path)
    controller.store.set_sample_cache(original_sample, None)
    controller.current_cache_relative = None
    _source(source, signal=150)
    assert fingerprint_source(source).sha256 != old_metadata.source_sha256

    controller.start_analysis(_parameters())
    qtbot.waitUntil(lambda: controller._active_task is None, timeout=30_000)

    assert (
        controller.store.sample_metadata(original_sample).source_sha256
        == old_metadata.source_sha256
    )
    assert controller.store.list_samples()[0]["cache_path"] is None
    assert "source changed after preflight" in window.notice._label.text()
    controller.close()


def test_project_switch_is_blocked_while_task_is_active(qtbot, tmp_path: Path) -> None:
    source = tmp_path / "sample.tif"
    _source(source, signal=80)
    window = MainWindow()
    qtbot.addWidget(window)
    controller = ApplicationController(window)
    first = tmp_path / "first.plug-project"
    second = tmp_path / "second.plug-project"
    controller.create_project(str(first))
    controller.inspect_source(str(source))
    controller.start_analysis(_parameters())

    controller.create_project(str(second))

    assert controller.store is not None
    assert controller.store.paths.root == first.resolve()
    assert "before changing projects" in window.notice._label.text()
    controller.cancel_active_task()
    qtbot.waitUntil(lambda: controller._active_task is None, timeout=30_000)
    controller.close()


def test_new_source_mutated_after_inspection_is_not_published(qtbot, tmp_path: Path) -> None:
    source = tmp_path / "sample.tif"
    _source(source, signal=80)
    window = MainWindow()
    qtbot.addWidget(window)
    controller = ApplicationController(window)
    controller.create_project(str(tmp_path / "study.plug-project"))
    controller.inspect_source(str(source))

    _source(source, signal=150)
    controller.start_analysis(_parameters())
    qtbot.waitUntil(lambda: controller._active_task is None, timeout=30_000)

    assert controller.store is not None
    assert controller.store.list_samples() == []
    assert "changed after preflight" in window.notice._label.text()
    controller.close()


def test_failed_project_open_keeps_current_project(qtbot, tmp_path: Path) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    controller = ApplicationController(window)
    current = tmp_path / "current.plug-project"
    controller.create_project(str(current))
    bad = tmp_path / "not-a-project"
    bad.mkdir()

    controller.open_project(str(bad))

    assert controller.store is not None
    assert controller.store.paths.root == current.resolve()
    controller.close()


def test_pending_new_import_is_discovered_after_reopen(qtbot, tmp_path: Path) -> None:
    source = tmp_path / "sample.tif"
    _source(source, signal=80)
    project = tmp_path / "study.plug-project"
    first_window = MainWindow()
    qtbot.addWidget(first_window)
    first = ApplicationController(first_window)
    first.create_project(str(project))
    first.inspect_source(str(source))
    identifier = uuid4().hex
    first._pending_sample_id = identifier
    first._record_pending_import()
    first.close()

    second_window = MainWindow()
    qtbot.addWidget(second_window)
    second = ApplicationController(second_window)
    second.open_project(str(project))
    second.inspect_source(str(source))

    assert second._pending_sample_id == identifier
    assert "will resume" in second_window.notice._label.text()
    second.close()


def test_starting_rerun_clears_stale_result_display(qtbot, tmp_path: Path) -> None:
    source = tmp_path / "sample.tif"
    _source(source, signal=80)
    window = MainWindow()
    qtbot.addWidget(window)
    controller = ApplicationController(window)
    controller.create_project(str(tmp_path / "study.plug-project"))
    controller.inspect_source(str(source))
    controller.start_analysis(_parameters())
    qtbot.waitUntil(lambda: controller.current_result is not None, timeout=30_000)
    qtbot.waitUntil(lambda: controller._active_task is None, timeout=5_000)
    assert window._result is not None

    controller.start_analysis(_parameters())

    assert window._result is None
    assert not window.save_result_button.isEnabled()
    controller.cancel_active_task()
    qtbot.waitUntil(lambda: controller._active_task is None, timeout=30_000)
    controller.close()


def test_gui_explicit_channel_selection_is_saved_with_sample(qtbot, tmp_path: Path) -> None:
    source = tmp_path / "channels.ome.tif"
    _two_channel_source(source)
    window = MainWindow()
    qtbot.addWidget(window)
    controller = ApplicationController(window)
    controller.create_project(str(tmp_path / "study.plug-project"))
    controller.inspect_source(str(source))
    assert window.channel_spin.maximum() == 1

    window.channel_spin.setValue(1)
    assert not window.state.source_ready
    controller.inspect_source(str(source))
    controller.start_analysis(_parameters())
    qtbot.waitUntil(lambda: controller.current_result is not None, timeout=30_000)
    qtbot.waitUntil(lambda: controller._active_task is None, timeout=5_000)

    assert controller.store is not None and controller.current_sample_id is not None
    metadata = controller.store.sample_metadata(controller.current_sample_id)
    assert metadata.selection.channel == 1
    assert metadata.channel_name == "strong"
    controller.close()
