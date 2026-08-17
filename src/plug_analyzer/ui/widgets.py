"""Reusable Qt widgets for the Plug Analyzer desktop application."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)


def format_bytes(value: int) -> str:
    """Format a byte count without pulling storage policy into the UI."""

    size = float(max(0, value))
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} TiB"


class NoticeBanner(QFrame):
    """A compact, accessible status banner with four semantic levels."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("noticeBanner")
        self._label = QLabel()
        self._label.setObjectName("noticeText")
        self._label.setWordWrap(True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.addWidget(self._label)
        self.set_level("info")
        self.hide()

    def show_message(self, message: str, level: str = "info") -> None:
        self._label.setText(message)
        self.set_level(level)
        self.setVisible(bool(message))

    def clear(self) -> None:
        self._label.clear()
        self.hide()

    def set_level(self, level: str) -> None:
        palette = {
            "info": ("#e8f1ff", "#245a9c", "#b6d2f5"),
            "success": ("#e9f7ef", "#23643d", "#a9dbbd"),
            "warning": ("#fff5df", "#805810", "#efd493"),
            "error": ("#fdebec", "#8a2930", "#eab4b8"),
        }
        background, foreground, border = palette.get(level, palette["info"])
        self.setStyleSheet(
            "QFrame#noticeBanner {"
            f"background: {background}; color: {foreground}; "
            f"border: 1px solid {border}; border-radius: 6px;"
            "}"
        )


class RectangleField(QWidget):
    """Four numeric controls representing an optional rectangular XY ROI."""

    changed = Signal()

    def __init__(self, *, object_prefix: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        self._spins: dict[str, QSpinBox] = {}
        for index, (label, key) in enumerate(
            (("X", "x"), ("Y", "y"), ("W", "width"), ("H", "height"))
        ):
            text = QLabel(label)
            text.setToolTip(
                "Exact image position. You can usually drag the coloured outline in the image "
                "instead; Full covers the remaining image width or height."
            )
            spin = QSpinBox()
            spin.setObjectName(f"{object_prefix}{key.title()}Spin")
            spin.setRange(0, 1_000_000)
            spin.setSpecialValueText("Full" if key in {"width", "height"} else "0")
            spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
            spin.setMinimumWidth(78)
            spin.setMaximumWidth(96)
            spin.setToolTip("Use only when you need an exact position for the coloured outline.")
            spin.valueChanged.connect(self.changed)
            self._spins[key] = spin
            row, pair = divmod(index, 2)
            layout.addWidget(text, row, pair * 2)
            layout.addWidget(spin, row, pair * 2 + 1)
        layout.setColumnStretch(4, 1)

    def value(self) -> dict[str, int]:
        return {name: spin.value() for name, spin in self._spins.items()}

    def set_value(self, value: dict[str, int] | None) -> None:
        data = value or {}
        previous = self.blockSignals(True)
        for name, spin in self._spins.items():
            spin.setValue(int(data.get(name, 0)))
        self.blockSignals(previous)
        self.changed.emit()


class AnalysisParameterEditor(QWidget):
    """Explicit deterministic protocol parameters; no scientific work occurs here."""

    parametersChanged = Signal(dict)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("analysisParameterEditor")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self._layout = layout

        title = QLabel("Analysis setup")
        title.setProperty("class", "sectionTitle")
        layout.addWidget(title)
        summary = QLabel(
            "Review calibration and the coloured image outlines. Plug detection uses the same "
            "fixed method for every run."
        )
        summary.setWordWrap(True)
        summary.setProperty("class", "helpText")
        layout.addWidget(summary)

        self.sections = QTabWidget()
        self.sections.setObjectName("analysisParameterTabs")
        self.sections.setDocumentMode(True)

        calibration_page = QWidget()
        calibration_layout = QVBoxLayout(calibration_page)
        calibration_layout.setContentsMargins(10, 12, 10, 10)
        calibration_help = QLabel(
            "These physical pixel sizes come from the microscope metadata. Confirm them before "
            "analysis; incorrect values change every physical measurement."
        )
        calibration_help.setWordWrap(True)
        calibration_help.setProperty("class", "helpText")
        calibration_layout.addWidget(calibration_help)
        calibration_form = QFormLayout()
        calibration_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.calibration_x = self._float_spin(
            "calibrationXSpin", 0.001, 10_000, 0.863, " µm/px", decimals=6
        )
        self.calibration_y = self._float_spin(
            "calibrationYSpin", 0.001, 10_000, 0.863, " µm/px", decimals=6
        )
        self.calibration_z = self._float_spin(
            "calibrationZSpin", 0.001, 10_000, 0.446, " µm", decimals=6
        )
        self.calibration_x.setToolTip(
            "The real-world width of one image pixel. Change only if the microscope metadata is wrong."
        )
        self.calibration_y.setToolTip(
            "The real-world height of one image pixel. Change only if the microscope metadata is wrong."
        )
        self.calibration_z.setToolTip(
            "The real-world distance between image slices. Change only if the microscope metadata is wrong."
        )
        calibration_form.addRow("X sampling", self.calibration_x)
        calibration_form.addRow("Y sampling", self.calibration_y)
        calibration_form.addRow("Z step", self.calibration_z)
        self.calibration_confirmed = QCheckBox("Calibration checked against metadata")
        self.calibration_confirmed.setObjectName("calibrationConfirmedCheck")
        self.calibration_confirmed.setToolTip(
            "Confirm that X, Y, and Z values match the microscope metadata"
        )
        calibration_layout.addLayout(calibration_form)
        calibration_layout.addWidget(self.calibration_confirmed)
        calibration_layout.addStretch(1)
        self.sections.addTab(calibration_page, "Calibration")
        self.sections.setTabToolTip(
            self.sections.indexOf(calibration_page),
            "Confirm the real-world size of each pixel and the distance between slices.",
        )

        regions_page = QWidget()
        regions_layout = QVBoxLayout(regions_page)
        regions_layout.setContentsMargins(10, 12, 10, 10)
        regions_layout.setSpacing(9)
        regions_help = QLabel(
            "Use the blue and green outlines in the image to tell the app where to measure and "
            "where to find background. Drag an outline in XY; use exact coordinates only when needed."
        )
        regions_help.setWordWrap(True)
        regions_help.setProperty("class", "helpText")
        regions_layout.addWidget(regions_help)
        self.analysis_roi = RectangleField(object_prefix="analysisRoi")
        self.analysis_roi.setObjectName("analysisRoiField")
        self.background_roi = RectangleField(object_prefix="backgroundRoi")
        self.background_roi.setObjectName("backgroundRoiField")
        self.envelope_roi = RectangleField(object_prefix="envelopeRoi")
        self.envelope_roi.setObjectName("envelopeRoiField")
        for heading, description, field in (
            (
                "Measure here · blue",
                "The channel area in which the plug is measured.",
                self.analysis_roi,
            ),
            (
                "Background here · green",
                "A representative dark area. Keep out the plug and bright channel wall.",
                self.background_roi,
            ),
            (
                "Optional plug outline · amber",
                "Use only when reviewing the low-fluorescence estimate inside the plug.",
                self.envelope_roi,
            ),
        ):
            group = QGroupBox(heading)
            group.setToolTip(description)
            group_layout = QVBoxLayout(group)
            group_layout.setContentsMargins(10, 9, 10, 8)
            group_help = QLabel(description)
            group_help.setWordWrap(True)
            group_help.setProperty("class", "helpText")
            group_layout.addWidget(group_help)
            field.setToolTip(description)
            group_layout.addWidget(field)
            regions_layout.addWidget(group)
        self._polygons: dict[str, list[list[float]]] = {
            "analysis": [],
            "background": [],
            "envelope": [],
        }
        self.polygon_status = QLabel("Rectangles are active. A curved outline is optional.")
        self.polygon_status.setObjectName("polygonStatusLabel")
        self.polygon_status.setProperty("class", "helpText")
        self.polygon_status.setWordWrap(True)
        regions_layout.addWidget(self.polygon_status)
        regions_layout.addStretch(1)
        self.sections.addTab(regions_page, "Regions")
        self.sections.setTabToolTip(
            self.sections.indexOf(regions_page),
            "Review the blue measurement area and green background area shown in the image.",
        )

        layout.addWidget(self.sections, 1)

        for spin in (
            self.calibration_x,
            self.calibration_y,
            self.calibration_z,
        ):
            spin.valueChanged.connect(self._emit_parameters)
        self.calibration_confirmed.toggled.connect(self._emit_parameters)
        self.analysis_roi.changed.connect(self._emit_parameters)
        self.background_roi.changed.connect(self._emit_parameters)
        self.envelope_roi.changed.connect(self._emit_parameters)

    def add_run_controls(self, controls: QWidget) -> None:
        """Place the run action directly below the analysis-setup summary."""

        self._layout.insertWidget(2, controls)

    @staticmethod
    def _float_spin(
        object_name: str,
        minimum: float,
        maximum: float,
        value: float,
        suffix: str,
        *,
        decimals: int = 4,
    ) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setObjectName(object_name)
        spin.setDecimals(decimals)
        spin.setRange(minimum, maximum)
        spin.setValue(value)
        spin.setSuffix(suffix)
        spin.setKeyboardTracking(False)
        spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        spin.setMinimumWidth(150)
        return spin

    def parameters(self) -> dict[str, Any]:
        """Return plain data suitable for serialization into a protocol snapshot."""

        return {
            "calibration_xyz_um": (
                self.calibration_x.value(),
                self.calibration_y.value(),
                self.calibration_z.value(),
            ),
            "calibration_confirmed": self.calibration_confirmed.isChecked(),
            "analysis_roi_xywh_px": self.analysis_roi.value(),
            "background_roi_xywh_px": self.background_roi.value(),
            "envelope_roi_xywh_px": self.envelope_roi.value(),
            "analysis_polygon_xy_px": self._polygons["analysis"],
            "background_polygon_xy_px": self._polygons["background"],
            "envelope_polygon_xy_px": self._polygons["envelope"],
            "low_threshold_sigma": 3.0,
            "high_threshold_sigma": 6.0,
            "smoothing_sigma_um": 0.75,
            "minimum_component_volume_um3": 5.0,
        }

    def set_parameters(self, parameters: dict[str, Any]) -> None:
        calibration = parameters.get("calibration_xyz_um")
        if calibration and len(calibration) == 3:
            self.calibration_x.setValue(float(calibration[0]))
            self.calibration_y.setValue(float(calibration[1]))
            self.calibration_z.setValue(float(calibration[2]))
        self.calibration_confirmed.setChecked(bool(parameters.get("calibration_confirmed", False)))
        self.analysis_roi.set_value(parameters.get("analysis_roi_xywh_px"))
        self.background_roi.set_value(parameters.get("background_roi_xywh_px"))
        self.envelope_roi.set_value(parameters.get("envelope_roi_xywh_px"))
        for name in self._polygons:
            self._polygons[name] = [
                [float(point[0]), float(point[1])]
                for point in parameters.get(f"{name}_polygon_xy_px", ())
            ]
        self._update_polygon_status()

    def validation_error(self) -> str | None:
        if not self.calibration_confirmed.isChecked():
            return "Confirm the voxel calibration before analysis."
        return None

    def _emit_parameters(self, *_args: object) -> None:
        self.parametersChanged.emit(self.parameters())

    def set_polygon(self, name: str, points: list[list[float]]) -> None:
        if name not in self._polygons:
            raise ValueError(f"unknown polygon target: {name}")
        self._polygons[name] = [[float(x), float(y)] for x, y in points]
        self._update_polygon_status()
        self._emit_parameters()

    def _update_polygon_status(self) -> None:
        active = [name for name, points in self._polygons.items() if points]
        self.polygon_status.setText(
            "Curved boundary active for: " + ", ".join(active)
            if active
            else "Rectangles are active. Curved boundaries are optional and edited in the viewer."
        )


class ZStackViewer(QWidget):
    """Linked XY/XZ/YZ viewer with segmentation and display controls.

    ``set_plane`` is the primary large-file API.  ``set_stack`` retains an in-memory
    stack only as a convenience for small inputs, examples, and UI tests.
    """

    planeRequested = Signal(int)
    zChanged = Signal(int)
    roiChanged = Signal(str, dict)
    positionRequested = Signal(int, int)
    polygonChanged = Signal(str, list)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("zStackViewer")
        self._raw_stack: np.ndarray[Any, Any] | None = None
        self._mask_stack: np.ndarray[Any, Any] | None = None
        self._plane_count = 0
        self._current_z = 0
        self._current_xy_plane: np.ndarray[Any, Any] | None = None
        self._current_xz_plane: np.ndarray[Any, Any] | None = None
        self._current_yz_plane: np.ndarray[Any, Any] | None = None
        self.polygon_items: dict[str, pg.PolyLineROI] = {}
        self._polygon_history: list[dict[str, list[list[float]]]] = []
        self._polygon_future: list[dict[str, list[list[float]]]] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        toolbar = QFrame()
        toolbar.setObjectName("viewerToolbar")
        toolbar_layout = QGridLayout(toolbar)
        toolbar_layout.setContentsMargins(10, 8, 10, 8)
        toolbar_layout.setHorizontalSpacing(9)
        toolbar_layout.setVerticalSpacing(7)
        self.plane_label = QLabel("Z plane — / —")
        self.plane_label.setObjectName("planeLabel")
        self.plane_label.setProperty("class", "sectionTitle")
        self.overlay_check = QCheckBox("Detected plug")
        self.overlay_check.setObjectName("overlayCheck")
        self.overlay_check.setChecked(True)
        self.overlay_check.setToolTip(
            "Shows the red area the app identifies as plug material. Turn it off to see only "
            "the microscope image."
        )
        self.uncertainty_check = QCheckBox("Uncertain edge")
        self.uncertainty_check.setObjectName("uncertaintyOverlayCheck")
        self.uncertainty_check.setChecked(True)
        self.uncertainty_check.setToolTip(
            "Shows yellow pixels that change when the fixed detection cutoff is moved slightly. "
            "These areas are less certain, not necessarily wrong."
        )
        self.fit_button = QPushButton("Fit views")
        self.fit_button.setObjectName("fitImageButton")
        self.fit_button.setToolTip("Resize all three images so their full outlines are visible.")
        toolbar_layout.addWidget(self.plane_label, 0, 0)
        toolbar_layout.setColumnStretch(1, 1)
        toolbar_layout.addWidget(self.fit_button, 0, 6)

        self.x_position = QSpinBox()
        self.x_position.setObjectName("orthogonalXSpin")
        self.x_position.setRange(0, 0)
        self.x_position.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.x_position.setMaximumWidth(74)
        self.x_position.setToolTip("Move this position to choose where the YZ side view is cut.")
        self.y_position = QSpinBox()
        self.y_position.setObjectName("orthogonalYSpin")
        self.y_position.setRange(0, 0)
        self.y_position.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.y_position.setMaximumWidth(74)
        self.y_position.setToolTip("Move this position to choose where the XZ side view is cut.")
        self.low_percentile = QDoubleSpinBox()
        self.low_percentile.setObjectName("displayLowPercentileSpin")
        self.low_percentile.setRange(0.0, 99.0)
        self.low_percentile.setDecimals(1)
        self.low_percentile.setValue(0.5)
        self.low_percentile.setSuffix(" %")
        self.low_percentile.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.low_percentile.setMaximumWidth(78)
        self.low_percentile.setToolTip(
            "Controls on-screen darkness. It changes only how the image looks, not the measurement."
        )
        self.high_percentile = QDoubleSpinBox()
        self.high_percentile.setObjectName("displayHighPercentileSpin")
        self.high_percentile.setRange(1.0, 100.0)
        self.high_percentile.setDecimals(1)
        self.high_percentile.setValue(99.5)
        self.high_percentile.setSuffix(" %")
        self.high_percentile.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.high_percentile.setMaximumWidth(78)
        self.high_percentile.setToolTip(
            "Controls on-screen brightness. It changes only how the image looks, not the measurement."
        )
        toolbar_layout.addWidget(self.overlay_check, 1, 0, 1, 2)
        toolbar_layout.addWidget(self.uncertainty_check, 1, 2, 1, 2)
        toolbar_layout.setColumnStretch(4, 1)
        toolbar_layout.addWidget(QLabel("XZ at Y"), 1, 5)
        toolbar_layout.addWidget(self.y_position, 1, 6)
        toolbar_layout.addWidget(QLabel("YZ at X"), 1, 7)
        toolbar_layout.addWidget(self.x_position, 1, 8)
        layout.addWidget(toolbar)

        geometry_header = QHBoxLayout()
        self.polygon_toggle_button = QPushButton("Use a curved outline…")
        self.polygon_toggle_button.setObjectName("polygonToolsToggle")
        self.polygon_toggle_button.setCheckable(True)
        self.polygon_toggle_button.setProperty("class", "quietToggle")
        self.polygon_toggle_button.setToolTip(
            "Use this only when a rectangular blue or green outline does not fit the channel. "
            "You can draw and adjust a curved outline in the top image."
        )
        self.display_toggle_button = QPushButton("Brightness & contrast…")
        self.display_toggle_button.setObjectName("displayToolsToggle")
        self.display_toggle_button.setCheckable(True)
        self.display_toggle_button.setProperty("class", "quietToggle")
        self.display_toggle_button.setToolTip(
            "Adjusts only the on-screen brightness and contrast. It never changes the source "
            "image or the measurement."
        )
        polygon_hint = QLabel("Optional—only when rectangles do not fit")
        polygon_hint.setProperty("class", "helpText")
        geometry_header.addWidget(self.polygon_toggle_button)
        geometry_header.addWidget(self.display_toggle_button)
        geometry_header.addWidget(polygon_hint)
        geometry_header.addStretch(1)
        layout.addLayout(geometry_header)

        self.display_tools = QDialog(self)
        self.display_tools.setObjectName("displayTools")
        self.display_tools.setWindowTitle("Brightness & contrast")
        self.display_tools.setWindowFlag(Qt.WindowType.Tool, True)
        self.display_tools.setModal(False)
        display_layout = QHBoxLayout(self.display_tools)
        display_layout.setContentsMargins(14, 12, 14, 12)
        display_layout.addWidget(QLabel("Make this level black"))
        display_layout.addWidget(self.low_percentile)
        display_layout.addWidget(QLabel("Make this level white"))
        display_layout.addWidget(self.high_percentile)
        display_layout.addStretch(1)
        self.display_tools.hide()

        self.polygon_tools = QDialog(self)
        self.polygon_tools.setObjectName("polygonTools")
        self.polygon_tools.setWindowTitle("Use a curved outline")
        self.polygon_tools.setWindowFlag(Qt.WindowType.Tool, True)
        self.polygon_tools.setModal(False)
        self.polygon_tools.setMinimumWidth(620)
        geometry_layout = QVBoxLayout(self.polygon_tools)
        geometry_layout.setContentsMargins(14, 12, 14, 12)
        polygon_help = QLabel(
            "Use this only when a rectangle includes unrelated material or cannot follow a curved "
            "channel edge. Drag the outline handles in the top XY image."
        )
        polygon_help.setWordWrap(True)
        polygon_help.setProperty("class", "helpText")
        geometry_layout.addWidget(polygon_help)
        geometry_controls = QHBoxLayout()
        self.polygon_target = QComboBox()
        self.polygon_target.setObjectName("polygonTargetCombo")
        for label, value in (
            ("Analysis / lumen", "analysis"),
            ("Background", "background"),
            ("Plug envelope", "envelope"),
        ):
            self.polygon_target.addItem(label, value)
        self.create_polygon_button = QPushButton("Add polygon to XY")
        self.create_polygon_button.setObjectName("createPolygonButton")
        self.erase_polygon_button = QPushButton("Remove")
        self.erase_polygon_button.setObjectName("erasePolygonButton")
        self.undo_polygon_button = QPushButton("Undo")
        self.undo_polygon_button.setObjectName("undoPolygonButton")
        self.redo_polygon_button = QPushButton("Redo")
        self.redo_polygon_button.setObjectName("redoPolygonButton")
        boundary_label = QLabel("Outline to draw")
        boundary_label.setToolTip("Choose which coloured outline you want to draw.")
        geometry_controls.addWidget(boundary_label)
        geometry_controls.addWidget(self.polygon_target)
        geometry_controls.addWidget(self.create_polygon_button)
        geometry_controls.addWidget(self.erase_polygon_button)
        geometry_controls.addWidget(self.undo_polygon_button)
        geometry_controls.addWidget(self.redo_polygon_button)
        geometry_controls.addStretch(1)
        geometry_layout.addLayout(geometry_controls)
        self.polygon_tools.hide()

        orthogonal_help = QLabel(
            "Top: the selected slice. Bottom left/right: side views through the full stack. "
            "Move the slice slider or X/Y positions to move the cyan guide lines."
        )
        orthogonal_help.setObjectName("orthogonalViewHelp")
        orthogonal_help.setWordWrap(True)
        orthogonal_help.setProperty("class", "helpText")
        layout.addWidget(orthogonal_help)

        self.graphics = pg.GraphicsLayoutWidget()
        self.graphics.setObjectName("imageCanvas")
        self.graphics.setBackground("#eef2f5")
        self.graphics.setMinimumHeight(360)
        self.view_box = self.graphics.addViewBox(row=0, col=0, colspan=2, lockAspect=True)
        self.view_box.setMouseMode(self.view_box.PanMode)
        self.view_box.invertY(True)
        self.raw_item = pg.ImageItem(axisOrder="row-major")
        self.mask_item = pg.ImageItem(axisOrder="row-major")
        self.uncertainty_item = pg.ImageItem(axisOrder="row-major")
        self.mask_item.setOpacity(0.46)
        mask_lut = np.zeros((256, 4), dtype=np.ubyte)
        mask_lut[1:, :] = np.array([255, 86, 68, 255], dtype=np.ubyte)
        self.mask_item.setLookupTable(mask_lut)
        self.mask_item.setLevels((0, 1))
        self.view_box.addItem(self.raw_item)
        self.view_box.addItem(self.mask_item)
        uncertainty_lut = np.zeros((256, 4), dtype=np.ubyte)
        uncertainty_lut[1:, :] = np.array([255, 213, 64, 255], dtype=np.ubyte)
        self.uncertainty_item.setOpacity(0.64)
        self.uncertainty_item.setLookupTable(uncertainty_lut)
        self.uncertainty_item.setLevels((0, 1))
        self.view_box.addItem(self.uncertainty_item)
        self.xy_label = pg.TextItem(
            "XY · selected Z", color="#ffffff", fill=pg.mkBrush(23, 35, 49, 205), anchor=(0, 0)
        )
        self.xy_label.setZValue(100)
        self.xy_label.setPos(4, 4)
        self.view_box.addItem(self.xy_label)
        crosshair_pen = pg.mkPen("#46b8e6", width=1, style=Qt.PenStyle.DashLine)
        self.xy_x_line = pg.InfiniteLine(pos=0, angle=90, movable=False, pen=crosshair_pen)
        self.xy_y_line = pg.InfiniteLine(pos=0, angle=0, movable=False, pen=crosshair_pen)
        self.xy_x_line.setZValue(15)
        self.xy_y_line.setZValue(15)
        self.view_box.addItem(self.xy_x_line)
        self.view_box.addItem(self.xy_y_line)

        self.xz_view_box = self.graphics.addViewBox(row=1, col=0, lockAspect=False)
        self.xz_view_box.invertY(True)
        self.xz_raw_item = pg.ImageItem(axisOrder="row-major")
        self.xz_mask_item = pg.ImageItem(axisOrder="row-major")
        self.xz_uncertainty_item = pg.ImageItem(axisOrder="row-major")
        self.xz_view_box.addItem(self.xz_raw_item)
        self.xz_view_box.addItem(self.xz_mask_item)
        self.xz_view_box.addItem(self.xz_uncertainty_item)
        self.xz_label = pg.TextItem(
            "XZ · full depth", color="#ffffff", fill=pg.mkBrush(23, 35, 49, 205), anchor=(0, 0)
        )
        self.xz_label.setZValue(100)
        self.xz_label.setPos(1, 1)
        self.xz_view_box.addItem(self.xz_label)
        self.xz_z_line = pg.InfiniteLine(pos=0.5, angle=0, movable=False, pen=crosshair_pen)
        self.xz_z_line.setZValue(90)
        self.xz_view_box.addItem(self.xz_z_line)

        self.yz_view_box = self.graphics.addViewBox(row=1, col=1, lockAspect=False)
        self.yz_view_box.invertY(True)
        self.yz_raw_item = pg.ImageItem(axisOrder="row-major")
        self.yz_mask_item = pg.ImageItem(axisOrder="row-major")
        self.yz_uncertainty_item = pg.ImageItem(axisOrder="row-major")
        self.yz_view_box.addItem(self.yz_raw_item)
        self.yz_view_box.addItem(self.yz_mask_item)
        self.yz_view_box.addItem(self.yz_uncertainty_item)
        self.yz_label = pg.TextItem(
            "YZ · full depth", color="#ffffff", fill=pg.mkBrush(23, 35, 49, 205), anchor=(0, 0)
        )
        self.yz_label.setZValue(100)
        self.yz_label.setPos(1, 1)
        self.yz_view_box.addItem(self.yz_label)
        self.yz_z_line = pg.InfiniteLine(pos=0.5, angle=0, movable=False, pen=crosshair_pen)
        self.yz_z_line.setZValue(90)
        self.yz_view_box.addItem(self.yz_z_line)
        self.graphics.ci.layout.setRowStretchFactor(0, 3)
        self.graphics.ci.layout.setRowStretchFactor(1, 2)
        for item in (self.xz_mask_item, self.yz_mask_item):
            item.setOpacity(0.46)
            item.setLookupTable(mask_lut)
            item.setLevels((0, 1))
        for item in (self.xz_uncertainty_item, self.yz_uncertainty_item):
            item.setOpacity(0.64)
            item.setLookupTable(uncertainty_lut)
            item.setLevels((0, 1))
        self.roi_items: dict[str, pg.ROI] = {}
        layout.addWidget(self.graphics, 1)

        self.z_navigation = QFrame()
        self.z_navigation.setObjectName("zNavigation")
        navigation_layout = QHBoxLayout(self.z_navigation)
        navigation_layout.setContentsMargins(10, 7, 10, 7)
        navigation_layout.setSpacing(8)
        first_slice = QLabel("First slice")
        first_slice.setToolTip("The first image slice in the selected stack.")
        navigation_layout.addWidget(first_slice)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setObjectName("zSlider")
        self.slider.setRange(0, 0)
        self.slider.setEnabled(False)
        self.slider.setToolTip("Move through the image slices. The top view changes to this slice.")
        navigation_layout.addWidget(self.slider, 1)
        last_slice = QLabel("Last slice")
        last_slice.setToolTip("The last image slice in the selected stack.")
        navigation_layout.addWidget(last_slice)
        layout.addWidget(self.z_navigation)
        self.stats_label = QLabel("No image loaded")
        self.stats_label.setObjectName("planeStatsLabel")
        self.stats_label.setProperty("class", "helpText")
        self.stats_label.setWordWrap(True)
        self.stats_label.setToolTip(
            "This describes the image values used for on-screen brightness only; it does not "
            "change any measurement."
        )
        layout.addWidget(self.stats_label)

        self.slider.valueChanged.connect(self._select_z)
        self.overlay_check.toggled.connect(self.mask_item.setVisible)
        self.overlay_check.toggled.connect(self.xz_mask_item.setVisible)
        self.overlay_check.toggled.connect(self.yz_mask_item.setVisible)
        self.uncertainty_check.toggled.connect(self.uncertainty_item.setVisible)
        self.uncertainty_check.toggled.connect(self.xz_uncertainty_item.setVisible)
        self.uncertainty_check.toggled.connect(self.yz_uncertainty_item.setVisible)
        self.fit_button.clicked.connect(self.fit_image)
        self.x_position.valueChanged.connect(self._request_orthogonal_position)
        self.y_position.valueChanged.connect(self._request_orthogonal_position)
        self.low_percentile.valueChanged.connect(self._apply_display_levels)
        self.high_percentile.valueChanged.connect(self._apply_display_levels)
        self.create_polygon_button.clicked.connect(self._create_polygon)
        self.erase_polygon_button.clicked.connect(self._erase_polygon)
        self.undo_polygon_button.clicked.connect(self._undo_polygon)
        self.redo_polygon_button.clicked.connect(self._redo_polygon)
        self.polygon_toggle_button.toggled.connect(self._toggle_polygon_tools)
        self.display_toggle_button.toggled.connect(self._toggle_display_tools)
        self.polygon_tools.finished.connect(
            lambda _result: self.polygon_toggle_button.setChecked(False)
        )
        self.display_tools.finished.connect(
            lambda _result: self.display_toggle_button.setChecked(False)
        )

    @property
    def plane_count(self) -> int:
        return self._plane_count

    @property
    def current_z(self) -> int:
        return self._current_z

    def _toggle_polygon_tools(self, visible: bool) -> None:
        self._show_tool_dialog(
            self.polygon_tools,
            self.polygon_toggle_button,
            visible,
        )

    def _toggle_display_tools(self, visible: bool) -> None:
        self._show_tool_dialog(
            self.display_tools,
            self.display_toggle_button,
            visible,
        )

    @staticmethod
    def _show_tool_dialog(dialog: QDialog, anchor: QWidget, visible: bool) -> None:
        if not visible:
            dialog.hide()
            return
        dialog.adjustSize()
        dialog.move(anchor.mapToGlobal(QPoint(0, anchor.height() + 5)))
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def set_plane_count(self, count: int, *, current: int = 0) -> None:
        self._plane_count = max(0, int(count))
        maximum = max(0, self._plane_count - 1)
        self.slider.blockSignals(True)
        self.slider.setRange(0, maximum)
        self.slider.setValue(min(max(0, int(current)), maximum))
        self.slider.blockSignals(False)
        self.slider.setEnabled(self._plane_count > 1)
        self._current_z = self.slider.value()
        self._update_plane_label()
        self._update_slice_indicators()

    def set_stack(self, raw: Any, mask: Any | None = None, *, initial_z: int = 0) -> None:
        raw_array = np.asarray(raw)
        if raw_array.ndim != 3:
            raise ValueError("raw stack must have shape (Z, Y, X)")
        mask_array = None if mask is None else np.asarray(mask)
        if mask_array is not None and mask_array.shape != raw_array.shape:
            raise ValueError("mask stack must have the same shape as raw stack")
        self._raw_stack = raw_array
        self._mask_stack = mask_array
        self.set_plane_count(raw_array.shape[0], current=initial_z)
        self._display_stack_plane(self._current_z)
        self.fit_image()

    def set_plane(
        self,
        raw: Any,
        mask: Any | None = None,
        uncertainty: Any | None = None,
        *,
        z_index: int | None = None,
        plane_count: int | None = None,
    ) -> None:
        raw_plane = np.asarray(raw)
        if raw_plane.ndim != 2:
            raise ValueError("raw plane must be two-dimensional")
        mask_plane = None if mask is None else np.asarray(mask)
        if mask_plane is not None and mask_plane.shape != raw_plane.shape:
            raise ValueError("mask plane must have the same shape as raw plane")
        uncertainty_plane = None if uncertainty is None else np.asarray(uncertainty)
        if uncertainty_plane is not None and uncertainty_plane.shape != raw_plane.shape:
            raise ValueError("uncertainty plane must have the same shape as raw plane")
        if plane_count is not None:
            self.set_plane_count(plane_count, current=z_index or 0)
        elif z_index is not None:
            self._current_z = int(z_index)
            self.slider.blockSignals(True)
            self.slider.setValue(self._current_z)
            self.slider.blockSignals(False)
            self._update_plane_label()

        self._current_xy_plane = raw_plane
        self.x_position.blockSignals(True)
        self.y_position.blockSignals(True)
        old_x_max = self.x_position.maximum()
        old_y_max = self.y_position.maximum()
        self.x_position.setRange(0, raw_plane.shape[1] - 1)
        self.y_position.setRange(0, raw_plane.shape[0] - 1)
        if old_x_max == 0:
            self.x_position.setValue(raw_plane.shape[1] // 2)
        if old_y_max == 0:
            self.y_position.setValue(raw_plane.shape[0] // 2)
        self.x_position.blockSignals(False)
        self.y_position.blockSignals(False)
        self._update_slice_indicators()
        display_plane = self._current_xy_plane
        finite = display_plane[np.isfinite(display_plane)]
        if finite.size:
            low, high = self._display_range(finite)
            if high <= low:
                high = low + 1.0
            self.raw_item.setImage(
                display_plane, autoLevels=False, levels=(float(low), float(high))
            )
            self.stats_label.setText(
                f"On-screen brightness {low:.1f} to {high:.1f}  •  "
                f"source values {finite.min():.1f} to {finite.max():.1f}"
            )
        else:
            self.raw_item.setImage(display_plane, autoLevels=True)
            self.stats_label.setText("Plane contains no finite intensity values")

        if mask_plane is None:
            self.mask_item.clear()
            self.mask_item.hide()
        else:
            self.mask_item.setImage(mask_plane.astype(np.uint8, copy=False), autoLevels=False)
            self.mask_item.setVisible(self.overlay_check.isChecked())
            fraction = float(np.count_nonzero(mask_plane)) / float(mask_plane.size)
            self.stats_label.setText(
                f"{self.stats_label.text()}  •  detected plug {fraction:.2%} of this slice"
            )
        if uncertainty_plane is None:
            self.uncertainty_item.clear()
            self.uncertainty_item.hide()
        else:
            self.uncertainty_item.setImage(
                uncertainty_plane.astype(np.uint8, copy=False), autoLevels=False
            )
            self.uncertainty_item.setVisible(self.uncertainty_check.isChecked())
        self.positionRequested.emit(self.x_position.value(), self.y_position.value())

    def set_orthogonal(
        self,
        xz: Any,
        yz: Any,
        xz_mask: Any | None = None,
        yz_mask: Any | None = None,
        xz_uncertainty: Any | None = None,
        yz_uncertainty: Any | None = None,
    ) -> None:
        xz_array = np.asarray(xz)
        yz_array = np.asarray(yz)
        if xz_array.ndim != 2 or yz_array.ndim != 2:
            raise ValueError("orthogonal views must be two-dimensional")
        self._current_xz_plane = xz_array
        self._current_yz_plane = yz_array
        self.xz_raw_item.setImage(self._current_xz_plane, autoLevels=False)
        self.yz_raw_item.setImage(self._current_yz_plane, autoLevels=False)
        for item, mask, shape in (
            (self.xz_mask_item, xz_mask, xz_array.shape),
            (self.yz_mask_item, yz_mask, yz_array.shape),
        ):
            if mask is None:
                item.clear()
                item.hide()
            else:
                mask_array = np.asarray(mask)
                if mask_array.shape != shape:
                    raise ValueError("orthogonal mask does not match its image view")
                item.setImage(mask_array.astype(np.uint8, copy=False), autoLevels=False)
                item.setVisible(self.overlay_check.isChecked())
        for item, mask, shape in (
            (self.xz_uncertainty_item, xz_uncertainty, xz_array.shape),
            (self.yz_uncertainty_item, yz_uncertainty, yz_array.shape),
        ):
            if mask is None:
                item.clear()
                item.hide()
            else:
                mask_array = np.asarray(mask)
                if mask_array.shape != shape:
                    raise ValueError("orthogonal uncertainty does not match its image view")
                item.setImage(mask_array.astype(np.uint8, copy=False), autoLevels=False)
                item.setVisible(self.uncertainty_check.isChecked())
        self._apply_display_levels()
        self._update_slice_indicators()

    def clear(self) -> None:
        self._raw_stack = None
        self._mask_stack = None
        self._plane_count = 0
        self._current_z = 0
        self.raw_item.clear()
        self.mask_item.clear()
        self.uncertainty_item.clear()
        self.xz_raw_item.clear()
        self.xz_mask_item.clear()
        self.xz_uncertainty_item.clear()
        self.yz_raw_item.clear()
        self.yz_mask_item.clear()
        self.yz_uncertainty_item.clear()
        self.set_plane_count(0)
        self.stats_label.setText("No image loaded")

    def set_roi_overlays(self, rois: dict[str, dict[str, int] | None]) -> None:
        """Draw reviewed numeric ROIs over the raw plane with fixed semantic colours."""

        colours = {
            "analysis": "#29a3ff",
            "background": "#32c776",
            "envelope": "#ffb020",
        }
        visible_names = {
            name
            for name, value in rois.items()
            if value and int(value.get("width", 0)) > 0 and int(value.get("height", 0)) > 0
        }
        for name in tuple(self.roi_items):
            if name not in visible_names:
                item = self.roi_items.pop(name)
                self.view_box.removeItem(item)
        for name, value in rois.items():
            if not value:
                continue
            width = int(value.get("width", 0))
            height = int(value.get("height", 0))
            if width <= 0 or height <= 0:
                continue
            position = (int(value.get("x", 0)), int(value.get("y", 0)))
            item = self.roi_items.get(name)
            if item is None:
                item = pg.RectROI(
                    position,
                    (width, height),
                    pen=pg.mkPen(colours.get(name, "#ffffff"), width=2),
                    movable=True,
                    resizable=True,
                    rotatable=False,
                )
                item.setZValue(20)
                item.setToolTip(
                    {
                        "analysis": "Blue outline: drag or resize to choose where the plug is measured.",
                        "background": "Green outline: drag or resize to choose a plug-free background area.",
                        "envelope": "Amber outline: drag or resize only when reviewing low-fluorescence inside the plug.",
                    }.get(name, "Drag or resize this outline in the image.")
                )
                item.sigRegionChangeFinished.connect(
                    lambda changed_item, roi_name=name: self._roi_change_finished(
                        roi_name, changed_item
                    )
                )
                item.sigRegionChangeStarted.connect(lambda *_args: self._record_polygon_history())
                self.view_box.addItem(item)
                self.roi_items[name] = item
            else:
                previous = item.blockSignals(True)
                item.setPos(position, update=False)
                item.setSize((width, height), update=False)
                item.blockSignals(previous)
                item.update()

    def set_polygon_overlays(self, polygons: dict[str, Any]) -> None:
        colours = {"analysis": "#29a3ff", "background": "#32c776", "envelope": "#ffb020"}
        for name, points_value in polygons.items():
            points = [[float(point[0]), float(point[1])] for point in (points_value or ())]
            item = self.polygon_items.get(name)
            if len(points) < 3:
                if item is not None:
                    self.view_box.removeItem(item)
                    del self.polygon_items[name]
                continue
            if item is None:
                item = pg.PolyLineROI(
                    points,
                    closed=True,
                    pen=pg.mkPen(colours.get(name, "#ffffff"), width=2),
                    movable=False,
                )
                item.setZValue(25)
                item.sigRegionChangeFinished.connect(
                    lambda changed, polygon_name=name: self._polygon_finished(polygon_name, changed)
                )
                self.view_box.addItem(item)
                self.polygon_items[name] = item
            else:
                previous = item.blockSignals(True)
                item.setPoints(points, closed=True)
                item.blockSignals(previous)

    def _polygon_snapshot(self) -> dict[str, list[list[float]]]:
        return {name: self._polygon_points(item) for name, item in self.polygon_items.items()}

    def _polygon_points(self, item: pg.PolyLineROI) -> list[list[float]]:
        points: list[list[float]] = []
        for _handle, scene_position in item.getSceneHandlePositions():
            view_position = self.view_box.mapSceneToView(scene_position)
            points.append([float(view_position.x()), float(view_position.y())])
        return points

    def _record_polygon_history(self) -> None:
        self._polygon_history.append(self._polygon_snapshot())
        self._polygon_history = self._polygon_history[-50:]
        self._polygon_future.clear()

    def _create_polygon(self) -> None:
        if self._current_xy_plane is None:
            return
        self._record_polygon_history()
        name = str(self.polygon_target.currentData())
        height, width = self._current_xy_plane.shape
        margin_x = max(1, width // 10)
        margin_y = max(1, height // 10)
        points = [
            [margin_x, margin_y],
            [width - margin_x - 1, margin_y],
            [width - margin_x - 1, height - margin_y - 1],
            [margin_x, height - margin_y - 1],
        ]
        self.set_polygon_overlays({name: points})
        self.polygonChanged.emit(name, points)

    def _erase_polygon(self) -> None:
        name = str(self.polygon_target.currentData())
        if name not in self.polygon_items:
            return
        self._record_polygon_history()
        item = self.polygon_items.pop(name)
        self.view_box.removeItem(item)
        self.polygonChanged.emit(name, [])

    def _polygon_finished(self, name: str, item: pg.PolyLineROI) -> None:
        self.polygonChanged.emit(name, self._polygon_points(item))

    def _restore_polygon_snapshot(self, snapshot: dict[str, list[list[float]]]) -> None:
        for name in ("analysis", "background", "envelope"):
            self.set_polygon_overlays({name: snapshot.get(name, [])})
            self.polygonChanged.emit(name, snapshot.get(name, []))

    def _undo_polygon(self) -> None:
        if not self._polygon_history:
            return
        self._polygon_future.append(self._polygon_snapshot())
        self._restore_polygon_snapshot(self._polygon_history.pop())

    def _redo_polygon(self) -> None:
        if not self._polygon_future:
            return
        self._polygon_history.append(self._polygon_snapshot())
        self._restore_polygon_snapshot(self._polygon_future.pop())

    def _roi_change_finished(self, name: str, item: pg.ROI) -> None:
        position = item.pos()
        size = item.size()
        x = max(0, round(float(position.x())))
        y = max(0, round(float(position.y())))
        width = max(1, round(float(size.x())))
        height = max(1, round(float(size.y())))
        image = self.raw_item.image
        if image is not None and np.asarray(image).ndim == 2:
            image_height, image_width = np.asarray(image).shape
            x = min(x, max(0, image_width - 1))
            y = min(y, max(0, image_height - 1))
            width = min(width, image_width - x)
            height = min(height, image_height - y)
        self.roiChanged.emit(
            name,
            {"x": x, "y": y, "width": width, "height": height},
        )

    def fit_image(self) -> None:
        self.view_box.autoRange(padding=0.02)
        self.xz_view_box.autoRange(padding=0.02)
        self.yz_view_box.autoRange(padding=0.02)

    def _request_orthogonal_position(self, *_args: object) -> None:
        self._update_slice_indicators()
        self.positionRequested.emit(self.x_position.value(), self.y_position.value())

    def _display_range(self, finite: np.ndarray[Any, Any]) -> tuple[float, float]:
        low_percentile = self.low_percentile.value()
        high_percentile = self.high_percentile.value()
        if high_percentile <= low_percentile:
            high_percentile = min(100.0, low_percentile + 0.1)
        low, high = np.percentile(
            finite.astype(np.float64, copy=False), (low_percentile, high_percentile)
        )
        if high <= low:
            high = low + 1.0
        return float(low), float(high)

    def _apply_display_levels(self, *_args: object) -> None:
        arrays = tuple(
            array
            for array in (
                self._current_xy_plane,
                self._current_xz_plane,
                self._current_yz_plane,
            )
            if array is not None
        )
        for array, item in zip(
            arrays,
            (self.raw_item, self.xz_raw_item, self.yz_raw_item),
            strict=False,
        ):
            finite = array[np.isfinite(array)]
            if finite.size:
                item.setLevels(self._display_range(finite))

    def _select_z(self, z_index: int) -> None:
        self._current_z = int(z_index)
        self._update_plane_label()
        self._update_slice_indicators()
        if self._raw_stack is not None:
            self._display_stack_plane(self._current_z)
        self.zChanged.emit(self._current_z)
        self.planeRequested.emit(self._current_z)

    def _display_stack_plane(self, z_index: int) -> None:
        if self._raw_stack is None:
            return
        mask = None if self._mask_stack is None else self._mask_stack[z_index]
        self.set_plane(self._raw_stack[z_index], mask, z_index=z_index)

    def _update_plane_label(self) -> None:
        if self._plane_count <= 0:
            self.plane_label.setText("Slice — of —")
        else:
            self.plane_label.setText(f"Slice {self._current_z + 1} of {self._plane_count}")

    def _update_slice_indicators(self) -> None:
        """Keep all three views visibly linked without reloading full-depth slices."""

        x_value = self.x_position.value()
        y_value = self.y_position.value()
        self.xy_x_line.setValue(x_value + 0.5)
        self.xy_y_line.setValue(y_value + 0.5)
        self.xz_z_line.setValue(self._current_z + 0.5)
        self.yz_z_line.setValue(self._current_z + 0.5)
        self.xz_label.setText(f"XZ · all Z at Y={y_value}")
        self.yz_label.setText(f"YZ · all Z at X={x_value}")


class ResultCharts(QWidget):
    """Per-Z and along-duct profiles, with click-to-plane navigation."""

    planeRequested = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.area_plot = pg.PlotWidget(title="Plug area by Z plane")
        self.area_plot.setObjectName("areaChart")
        self.intensity_plot = pg.PlotWidget(title="Integrated intensity by Z plane")
        self.occlusion_plot = pg.PlotWidget(title="Occlusion along duct axis")
        self.open_area_plot = pg.PlotWidget(title="Open area along duct axis")
        self.intensity_plot.setObjectName("intensityChart")
        for chart in (self.area_plot, self.intensity_plot):
            chart.setBackground("#ffffff")
            chart.showGrid(x=True, y=True, alpha=0.16)
            chart.setLabel("bottom", "Z position", units="µm")
        self.area_plot.setLabel("left", "Area", units="µm²")
        self.intensity_plot.setLabel("left", "Integrated intensity", units="a.u.")
        for chart in (self.occlusion_plot, self.open_area_plot):
            chart.setBackground("#ffffff")
            chart.showGrid(x=True, y=True, alpha=0.16)
            chart.setLabel("bottom", "Duct-axis position", units="µm")
        self.occlusion_plot.setLabel("left", "Occlusion", units="%")
        self.open_area_plot.setLabel("left", "Open area", units="µm²")
        layout.addWidget(self.area_plot, 0, 0)
        layout.addWidget(self.intensity_plot, 1, 0)
        layout.addWidget(self.occlusion_plot, 0, 1)
        layout.addWidget(self.open_area_plot, 1, 1)
        self._z_positions = np.asarray([], dtype=float)
        for chart in (self.area_plot, self.intensity_plot):
            chart.scene().sigMouseClicked.connect(
                lambda event, selected=chart: self._chart_clicked(selected, event)
            )

    def set_series(
        self,
        z_um: Sequence[float],
        area_um2: Sequence[float],
        integrated_intensity: Sequence[float],
    ) -> None:
        if not (len(z_um) == len(area_um2) == len(integrated_intensity)):
            raise ValueError("per-plane chart series must have equal lengths")
        self.clear()
        if not z_um:
            return
        x = np.asarray(z_um, dtype=float)
        self._z_positions = x
        self.area_plot.plot(
            x,
            np.asarray(area_um2, dtype=float),
            pen=pg.mkPen(QColor("#2774ae"), width=2),
            symbol="o",
            symbolSize=5,
            symbolBrush=QColor("#2774ae"),
        )
        self.intensity_plot.plot(
            x,
            np.asarray(integrated_intensity, dtype=float),
            pen=pg.mkPen(QColor("#7b4ab2"), width=2),
            symbol="o",
            symbolSize=5,
            symbolBrush=QColor("#7b4ab2"),
        )

    def set_cross_sections(
        self,
        position_um: Sequence[float],
        occlusion_percent: Sequence[float],
        open_area_um2: Sequence[float],
    ) -> None:
        if not (len(position_um) == len(occlusion_percent) == len(open_area_um2)):
            raise ValueError("cross-section chart series must have equal lengths")
        self.occlusion_plot.clear()
        self.open_area_plot.clear()
        if len(position_um) == 0:
            return
        x = np.asarray(position_um, dtype=float)
        self.occlusion_plot.plot(
            x,
            np.asarray(occlusion_percent, dtype=float),
            pen=pg.mkPen(QColor("#d86132"), width=2),
        )
        self.open_area_plot.plot(
            x,
            np.asarray(open_area_um2, dtype=float),
            pen=pg.mkPen(QColor("#21866f"), width=2),
        )

    def _chart_clicked(self, chart: pg.PlotWidget, event: Any) -> None:
        if self._z_positions.size == 0 or not chart.sceneBoundingRect().contains(event.scenePos()):
            return
        coordinate = chart.plotItem.vb.mapSceneToView(event.scenePos()).x()
        index = int(np.argmin(np.abs(self._z_positions - coordinate)))
        self.planeRequested.emit(index)

    def clear(self) -> None:
        self.area_plot.clear()
        self.intensity_plot.clear()
        self.occlusion_plot.clear()
        self.open_area_plot.clear()
        self._z_positions = np.asarray([], dtype=float)
