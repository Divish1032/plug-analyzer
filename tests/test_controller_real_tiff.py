from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from plug_analyzer.controller import ApplicationController
from plug_analyzer.ui import MainWindow


@pytest.mark.integration
@pytest.mark.gui
def test_supplied_tiff_completes_gui_import_analysis_and_save(qtbot, tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[2] / "test.tif"
    if not source.is_file():
        pytest.skip("supplied microscope regression stack is not present")

    window = MainWindow()
    qtbot.addWidget(window)
    controller = ApplicationController(window)
    project = tmp_path / "real-tiff.plug-project"
    controller.create_project(str(project))
    controller.inspect_source(str(source))

    assert window.state.source_ready
    assert controller._preflight_safe
    assert window.viewer.plane_count == 62
    assert window.parameter_editor.calibration_x.value() == pytest.approx(0.863168)
    assert window.parameter_editor.calibration_y.value() == pytest.approx(0.863168)
    assert window.parameter_editor.calibration_z.value() == pytest.approx(0.446)

    window.parameter_editor.calibration_confirmed.setChecked(True)
    parameters = window.analysis_parameters()
    parameters.update(
        {
            "low_threshold_sigma": 2.0,
            "high_threshold_sigma": 4.0,
            "smoothing_sigma_um": 0.75,
            "minimum_component_volume_um3": 5.0,
        }
    )
    controller.start_analysis(parameters)
    qtbot.waitUntil(lambda: controller.current_result is not None, timeout=60_000)
    qtbot.waitUntil(lambda: controller._active_task is None, timeout=10_000)

    result = controller.current_result
    assert result is not None
    assert result.plug_mask.shape == (62, 234, 1024)
    assert result.per_plane.area_um2.shape == (62,)
    assert int(result.per_plane.corrected_integrated_intensity_au.argmax()) == 18
    assert result.saturation.fraction == pytest.approx(0.00006953329628480839)
    controller.save_current_result()

    run_id = controller.current_saved_run_id
    assert run_id is not None
    run_directory = project / "runs" / run_id
    summary = json.loads((run_directory / "analysis-summary.json").read_text(encoding="utf-8"))
    assert summary["metrics"]["observed_volume_um3"] > 0
    with (run_directory / "per-z-metrics.csv").open(newline="", encoding="utf-8") as handle:
        assert len(list(csv.reader(handle))) == 63
    assert (run_directory / "plug-mask.npy").is_file()
    assert (run_directory / "threshold-disagreement-mask.npy").is_file()
    controller.show_orthogonal(512, 117)
    assert window.viewer.xz_raw_item.image.shape == (62, 1024)
    assert window.viewer.yz_raw_item.image.shape == (62, 234)
    controller.close()
