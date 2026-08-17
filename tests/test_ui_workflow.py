from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QLabel,
    QRadioButton,
    QScrollArea,
    QSpinBox,
)

from plug_analyzer.app import create_application
from plug_analyzer.ui import (
    AnalysisResultDisplay,
    AppState,
    ChoiceDisplay,
    MainWindow,
    MetricDisplay,
    PlaneSeries,
    PreflightSummary,
    SavedMetricComparisonDisplay,
    SourceSummary,
    StorageSummary,
)
from plug_analyzer.ui.main_window import APP_STYLESHEET


@pytest.fixture
def window(qtbot):
    widget = MainWindow()
    qtbot.addWidget(widget)
    widget.show()
    return widget


def _ready_state(tmp_path: Path) -> AppState:
    return AppState(
        project_path=tmp_path / "project",
        source_path=tmp_path / "sample.tif",
        project_open=True,
        source_ready=True,
        status="Source ready",
    )


def _safe_preflight() -> PreflightSummary:
    return PreflightSummary(
        safe_to_start=True,
        available_memory_bytes=16 * 1024**3,
        memory_budget_bytes=6 * 1024**3,
        disk_free_bytes=100 * 1024**3,
        disk_required_bytes=3 * 1024**3,
        compute_chunk_bytes=128 * 1024**2,
        worker_threads=3,
    )


@pytest.mark.gui
def test_main_window_exposes_four_step_local_workflow(window: MainWindow) -> None:
    assert window.pages.count() == 4
    assert window.windowTitle() == "Plug Analyzer"
    assert window.navigation.count() == 4


@pytest.mark.gui
def test_main_window_forces_light_theme_when_system_palette_is_dark(qtbot) -> None:
    application = QApplication.instance()
    assert application is not None
    dark_palette = QPalette()
    dark_palette.setColor(QPalette.ColorRole.Window, QColor("#191919"))
    dark_palette.setColor(QPalette.ColorRole.Base, QColor("#111111"))
    dark_palette.setColor(QPalette.ColorRole.Text, QColor("#eeeeee"))
    application.setPalette(dark_palette)
    create_application([])

    widget = MainWindow()
    qtbot.addWidget(widget)
    widget.show()
    qtbot.waitExposed(widget)

    palette = application.palette()
    assert palette.color(QPalette.ColorRole.Window).name() == "#f4f6f8"
    assert palette.color(QPalette.ColorRole.Base).name() == "#ffffff"
    assert palette.color(QPalette.ColorRole.Text).name() == "#243244"
    assert palette.color(QPalette.ColorRole.Button).name() == "#f7f9fb"
    assert "QScrollBar::handle:vertical" in widget.styleSheet()
    assert "QSlider::handle:horizontal" in widget.styleSheet()


def _rendered_colours(widget) -> set[str]:
    widget.resize(widget.sizeHint())
    image = QImage(widget.size(), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor("#ffffff"))
    widget.render(image)
    indicator_width = min(20, image.width())
    return {
        image.pixelColor(x, y).name() for y in range(image.height()) for x in range(indicator_width)
    }


def _rendered_right_edge_colours(widget) -> set[str]:
    widget.resize(max(180, widget.sizeHint().width()), widget.sizeHint().height())
    image = QImage(widget.size(), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor("#ffffff"))
    widget.render(image)
    return {
        image.pixelColor(x, y).name()
        for y in range(image.height())
        for x in range(max(0, image.width() - 24), image.width())
    }


@pytest.mark.gui
def test_light_theme_selection_indicators_are_visible(qtbot) -> None:
    application = create_application([])

    checkbox = QCheckBox("Visible checkbox")
    qtbot.addWidget(checkbox)
    checkbox.show()
    qtbot.waitExposed(checkbox)
    unchecked_colours = _rendered_colours(checkbox)
    assert "#718595" in unchecked_colours

    checkbox.setChecked(True)
    checked_colours = _rendered_colours(checkbox)
    assert "#276e9d" in checked_colours
    assert "#ffffff" in checked_colours

    radio = QRadioButton("Visible radio button")
    qtbot.addWidget(radio)
    radio.setChecked(True)
    radio.show()
    qtbot.waitExposed(radio)
    radio_colours = _rendered_colours(radio)
    assert "#276e9d" in radio_colours

    combo = QComboBox()
    qtbot.addWidget(combo)
    combo.addItem("Microscope channel 1")
    combo.setStyleSheet(APP_STYLESHEET)
    combo.show()
    qtbot.waitExposed(combo)
    assert "#526b7d" in _rendered_right_edge_colours(combo)

    spin = QSpinBox()
    qtbot.addWidget(spin)
    spin.setStyleSheet(combo.styleSheet())
    spin.show()
    qtbot.waitExposed(spin)
    assert {"#526b7d", "#555555"} & _rendered_right_edge_colours(spin)

    assert application.applicationVersion() == "0.2.2"


def test_analysis_sidebar_fits_without_horizontal_clipping(qtbot, window: MainWindow) -> None:
    window.resize(1280, 800)
    window.navigation.setCurrentRow(2)
    window.show()
    qtbot.waitExposed(window)
    scroll = window.findChild(QScrollArea, "analysisParameterScroll")
    assert scroll is not None
    assert scroll.horizontalScrollBar().maximum() == 0
    assert scroll.widget() is not None
    assert scroll.widget().isAncestorOf(window.run_analysis_button)
    assert window.viewer.graphics.minimumHeight() >= 360
    assert window.viewer.graphics.geometry().bottom() < window.viewer.z_navigation.geometry().top()
    assert window.navigation.item(3).text() == "4  Results"
    assert not window.run_analysis_button.isEnabled()
    assert not window.save_result_button.isEnabled()


@pytest.mark.gui
def test_fixed_method_is_kept_out_of_the_setup_form(window: MainWindow) -> None:
    editor = window.parameter_editor
    assert editor.sections.count() == 2
    assert editor.parameters()["low_threshold_sigma"] == 3.0
    assert editor.parameters()["high_threshold_sigma"] == 6.0
    assert "red area" in window.viewer.overlay_check.toolTip()
    assert "yellow pixels" in window.viewer.uncertainty_check.toolTip()
    assert window.findChild(QComboBox, "imageViewModeCombo") is None
    assert "source image" in window.viewer.display_toggle_button.toolTip()
    assert "curved outline" in window.viewer.polygon_toggle_button.toolTip()


@pytest.mark.gui
def test_home_page_keeps_only_simple_project_storage_actions(qtbot, window: MainWindow) -> None:
    window.resize(1280, 800)
    window.navigation.setCurrentRow(window.PAGE_HOME)
    window.show()
    qtbot.waitExposed(window)

    home_scroll = window.findChild(QScrollArea, "homeScroll")
    assert home_scroll is not None
    assert home_scroll.horizontalScrollBar().maximum() == 0
    assert window.findChild(QLabel, "projectStorageLabel") is not None
    assert window.reveal_storage_button.text() == "Show project folder"
    assert window.clear_cache_button.text() == "Remove cached image data…"


@pytest.mark.gui
def test_project_source_preflight_and_analysis_signals(
    qtbot, window: MainWindow, tmp_path: Path
) -> None:
    project_path = tmp_path / "project"
    source_path = tmp_path / "sample.tif"

    with qtbot.waitSignal(window.createProjectRequested) as created:
        window.request_create_project(project_path)
    assert created.args == [str(project_path)]

    window.set_state(_ready_state(tmp_path))
    assert window.project_path_edit.text() == str(project_path)
    assert window.source_path_edit.text() == str(source_path)

    summary = SourceSummary(
        filename="sample.tif",
        source_format="ImageJ TIFF",
        dimensions_zyx=(62, 234, 1024),
        dtype="uint16",
        calibration_xyz_um=(0.863, 0.863, 0.446),
        calibration_source="ImageJ metadata",
        reader="tifffile",
        warnings=("Structure touches the right image boundary.",),
    )
    window.set_source_summary(summary)
    assert window.metadata_table.rowCount() >= 10
    assert window.parameter_editor.calibration_z.value() == pytest.approx(0.446)
    assert window.notice.isVisible()

    window.set_preflight(_safe_preflight())
    assert window.run_analysis_button.isEnabled()
    assert "passed" in window.preflight_status.text()

    # Analysis is blocked until the operator explicitly confirms calibration.
    qtbot.mouseClick(window.run_analysis_button, Qt.MouseButton.LeftButton)
    assert "Confirm" in window.notice.findChild(QLabel, "noticeText").text()

    window.parameter_editor.calibration_confirmed.setChecked(True)
    with qtbot.waitSignal(window.analyzeRequested) as requested:
        qtbot.mouseClick(window.run_analysis_button, Qt.MouseButton.LeftButton)
    parameters = requested.args[0]
    assert parameters["calibration_xyz_um"] == pytest.approx((0.863, 0.863, 0.446))
    assert parameters["high_threshold_sigma"] > parameters["low_threshold_sigma"]

    window.set_analysis_running(True)
    assert window.cancel_analysis_button.isEnabled()
    assert not window.run_analysis_button.isEnabled()
    window.set_analysis_progress(42, "Segmenting", "plane chunk 3 of 7")
    assert window.progress_bar.value() == 42
    assert "plane chunk" in window.progress_label.text()


@pytest.mark.gui
def test_unsafe_preflight_disables_analysis(window: MainWindow, tmp_path: Path) -> None:
    window.set_state(_ready_state(tmp_path))
    window.set_preflight(
        PreflightSummary(
            safe_to_start=False,
            available_memory_bytes=1024**3,
            memory_budget_bytes=0,
            disk_free_bytes=1024**3,
            disk_required_bytes=4 * 1024**3,
            compute_chunk_bytes=32 * 1024**2,
            worker_threads=1,
            warnings=("Not enough free disk space.",),
        )
    )
    assert not window.run_analysis_button.isEnabled()
    assert "unsafe" in window.preflight_status.text()
    assert "disk" in window.preflight_warnings.text()


@pytest.mark.gui
def test_explicit_dimension_selection_invalidates_prior_preflight(
    qtbot, window: MainWindow, tmp_path: Path
) -> None:
    window.set_state(_ready_state(tmp_path))
    window.set_dimension_limits(scene_count=3, time_count=2, channel_count=4, z_count=62)
    window.set_preflight(_safe_preflight())

    with qtbot.waitSignal(window.dimensionSelectionChanged) as changed:
        window.channel_spin.setValue(2)

    assert changed.args[0] == {
        "scene": 0,
        "time": 0,
        "channel": 2,
        "z_start": 0,
        "z_stop": None,
    }
    window.invalidate_preflight("Selection changed; inspect this selection again.")
    assert not window.run_analysis_button.isEnabled()
    assert "Selection changed" in window.preflight_status.text()


@pytest.mark.gui
def test_z_viewer_supports_small_stack_and_streamed_plane(qtbot, window: MainWindow) -> None:
    raw = np.arange(4 * 8 * 9, dtype=np.uint16).reshape(4, 8, 9)
    mask = np.zeros_like(raw, dtype=bool)
    mask[:, 2:5, 3:7] = True
    window.set_stack(raw, mask)

    assert window.viewer.plane_count == 4
    assert window.viewer.slider.isEnabled()
    assert np.array_equal(window.viewer.raw_item.image, raw[0])
    assert np.array_equal(window.viewer.mask_item.image, mask[0].astype(np.uint8))

    with qtbot.waitSignal(window.planeRequested) as requested:
        window.viewer.slider.setValue(2)
    assert requested.args == [2]
    assert window.viewer.current_z == 2
    assert np.array_equal(window.viewer.raw_item.image, raw[2])
    assert window.viewer.plane_label.text() == "Slice 3 of 4"
    assert window.viewer.xz_z_line.value() == 2.5
    assert window.viewer.yz_z_line.value() == 2.5

    window.viewer.overlay_check.setChecked(False)
    assert not window.viewer.mask_item.isVisible()

    # The primary API accepts a single plane, so a controller need not load a GB stack.
    window.viewer.clear()
    window.set_plane(raw[1], mask[1], z_index=17, plane_count=62)
    assert window.viewer.plane_count == 62
    assert window.viewer.current_z == 17
    assert window.viewer.plane_label.text() == "Slice 18 of 62"


@pytest.mark.gui
def test_viewer_links_raw_orthogonal_and_uncertainty_views(window: MainWindow) -> None:
    raw = np.arange(4 * 8 * 9, dtype=np.uint16).reshape(4, 8, 9)
    mask = raw > 100
    uncertainty = (raw > 120) & (raw < 140)
    window.set_plane(
        raw[2],
        mask[2],
        uncertainty[2],
        z_index=2,
        plane_count=4,
    )
    window.set_orthogonal(
        raw[:, 4, :],
        raw[:, :, 4],
        mask[:, 4, :],
        mask[:, :, 4],
        uncertainty[:, 4, :],
        uncertainty[:, :, 4],
    )
    np.testing.assert_array_equal(window.viewer.raw_item.image, raw[2])
    np.testing.assert_array_equal(window.viewer.xz_raw_item.image, raw[:, 4, :])
    np.testing.assert_array_equal(window.viewer.yz_raw_item.image, raw[:, :, 4])
    assert np.array_equal(window.viewer.uncertainty_item.image, uncertainty[2].astype(np.uint8))
    assert "all Z at Y=4" in window.viewer.xz_label.toPlainText()
    assert "all Z at X=4" in window.viewer.yz_label.toPlainText()


@pytest.mark.gui
def test_viewer_roi_drag_updates_numeric_protocol_fields(qtbot, window: MainWindow) -> None:
    window.set_plane(np.ones((100, 120), dtype=np.uint16), z_index=0, plane_count=1)
    window.parameter_editor.analysis_roi.set_value({"x": 10, "y": 12, "width": 50, "height": 40})
    roi = window.viewer.roi_items["analysis"]

    roi.setPos((18, 21))
    roi.setSize((44, 33))
    roi.sigRegionChangeFinished.emit(roi)
    qtbot.waitUntil(lambda: window.parameter_editor.analysis_roi.value()["x"] == 18)

    assert window.parameter_editor.analysis_roi.value() == {
        "x": 18,
        "y": 21,
        "width": 44,
        "height": 33,
    }


@pytest.mark.gui
def test_editable_polygon_roi_supports_erase_undo_and_protocol_snapshot(
    qtbot, window: MainWindow
) -> None:
    window.set_plane(np.ones((80, 120), dtype=np.uint16), z_index=0, plane_count=1)
    qtbot.mouseClick(window.viewer.polygon_toggle_button, Qt.MouseButton.LeftButton)
    assert window.viewer.polygon_tools.isVisible()
    qtbot.mouseClick(window.viewer.create_polygon_button, Qt.MouseButton.LeftButton)
    points = window.analysis_parameters()["analysis_polygon_xy_px"]
    assert len(points) == 4
    assert "analysis" in window.viewer.polygon_items
    qtbot.mouseClick(window.viewer.erase_polygon_button, Qt.MouseButton.LeftButton)
    assert window.analysis_parameters()["analysis_polygon_xy_px"] == []
    qtbot.mouseClick(window.viewer.undo_polygon_button, Qt.MouseButton.LeftButton)
    assert len(window.analysis_parameters()["analysis_polygon_xy_px"]) == 4


@pytest.mark.gui
def test_results_saved_run_comparison_and_project_storage(
    qtbot, window: MainWindow, tmp_path: Path
) -> None:
    window.set_state(_ready_state(tmp_path))
    window.set_preflight(_safe_preflight())
    result = AnalysisResultDisplay(
        sample_name="sample.tif",
        run_id="run-001",
        metrics=(
            MetricDisplay("Plug volume", 124.5, "µm³"),
            MetricDisplay(
                "Apparent low-fluorescence fraction",
                0.18,
                "%",
                "within_imaged_volume_only",
                "Optical proxy; not physical porosity.",
            ),
        ),
        planes=PlaneSeries(
            z_um=(0.0, 0.446, 0.892),
            area_um2=(10.0, 12.0, 9.0),
            integrated_intensity=(100.0, 140.0, 95.0),
        ),
        protocol_label="Protocol v1",
        qc_summary="low saturation; right boundary contact",
    )
    window.set_result(result)

    assert window.metric_table.rowCount() == 2
    assert window.result_charts.area_plot.listDataItems()
    assert window.result_charts.intensity_plot.listDataItems()
    assert window.pages.currentIndex() == window.PAGE_HOME
    assert window.save_result_button.isEnabled()
    assert window.view_results_button.isEnabled()

    qtbot.mouseClick(window.view_results_button, Qt.MouseButton.LeftButton)
    assert window.pages.currentIndex() == window.PAGE_RESULTS

    with qtbot.waitSignal(window.saveResultRequested):
        qtbot.mouseClick(window.save_result_button, Qt.MouseButton.LeftButton)
    with qtbot.waitSignal(window.exportCsvRequested) as exported:
        window.request_export_csv(tmp_path / "result.csv")
    assert exported.args == [str(tmp_path / "result.csv")]

    window.set_saved_run_choices(
        (
            ChoiceDisplay("run-a", "Sample · Run A"),
            ChoiceDisplay("run-b", "Sample · Run B"),
        )
    )
    window.set_saved_run_comparison(
        (
            SavedMetricComparisonDisplay(
                metric_name="observed_volume_um3",
                left_value=120.0,
                right_value=124.5,
                unit="µm³",
                difference=4.5,
            ),
        ),
        compatibility="The runs use the same method, calibration, and image channel.",
    )
    assert window.saved_run_comparison_table.rowCount() == 1
    assert window.saved_run_comparison_table.item(0, 0).text() == "Observed plug volume"
    assert window.saved_run_comparison_table.item(0, 3).text() == "4.5"

    storage = StorageSummary(
        project_path=tmp_path / "project",
        cache_bytes=2 * 1024**3,
        result_bytes=512 * 1024,
    )
    window.set_storage_summary(storage)
    assert "2.00 GiB" in window.project_storage_label.text()
