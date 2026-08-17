"""Deterministic light-only Qt theme.

Qt otherwise inherits the operating-system palette.  A dark macOS or Windows
palette can therefore leak into scroll-area viewports and native controls even
when individual cards are styled white.  Apply this palette before constructing
widgets so every supported platform starts from the same light colour roles.
"""

from __future__ import annotations

from typing import ClassVar

from PySide6.QtCore import QRect, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPalette, QPen
from PySide6.QtWidgets import QApplication, QProxyStyle, QStyle, QStyleFactory


class LightFusionStyle(QProxyStyle):
    """Fusion style with deterministic, visible light selection controls.

    macOS can delegate checkbox and radio indicators back to an appearance-aware
    native renderer even after a Qt palette is replaced.  Painting these two
    primitives here keeps them visible on white backgrounds without introducing
    image assets or platform-specific paths.
    """

    _INDICATOR_METRICS: ClassVar[set[QStyle.PixelMetric]] = {
        QStyle.PixelMetric.PM_IndicatorWidth,
        QStyle.PixelMetric.PM_IndicatorHeight,
        QStyle.PixelMetric.PM_ExclusiveIndicatorWidth,
        QStyle.PixelMetric.PM_ExclusiveIndicatorHeight,
    }

    def __init__(self) -> None:
        base_style = QStyleFactory.create("Fusion")
        if base_style is None:  # pragma: no cover - every supported Qt build has Fusion
            raise RuntimeError("Qt Fusion style is unavailable")
        super().__init__(base_style)

    def pixelMetric(
        self,
        metric: QStyle.PixelMetric,
        option=None,
        widget=None,
    ) -> int:
        if metric in self._INDICATOR_METRICS:
            return 16
        return super().pixelMetric(metric, option, widget)

    def drawPrimitive(
        self,
        element: QStyle.PrimitiveElement,
        option,
        painter: QPainter,
        widget=None,
    ) -> None:
        if element == QStyle.PrimitiveElement.PE_IndicatorCheckBox:
            self._draw_checkbox(option, painter)
            return
        if element == QStyle.PrimitiveElement.PE_IndicatorRadioButton:
            self._draw_radio_button(option, painter)
            return
        spin_arrow_directions = {
            QStyle.PrimitiveElement.PE_IndicatorSpinDown: "down",
            QStyle.PrimitiveElement.PE_IndicatorSpinUp: "up",
        }
        if element in spin_arrow_directions:
            self._draw_arrow(
                option,
                painter,
                spin_arrow_directions[element],
                minimum_radius=4.0,
                scale=0.32,
            )
            return
        arrow_directions = {
            QStyle.PrimitiveElement.PE_IndicatorArrowDown: "down",
            QStyle.PrimitiveElement.PE_IndicatorArrowUp: "up",
            QStyle.PrimitiveElement.PE_IndicatorArrowLeft: "left",
            QStyle.PrimitiveElement.PE_IndicatorArrowRight: "right",
        }
        if element in arrow_directions:
            self._draw_arrow(option, painter, arrow_directions[element])
            return
        super().drawPrimitive(element, option, painter, widget)

    def subControlRect(
        self,
        control: QStyle.ComplexControl,
        option,
        sub_control: QStyle.SubControl,
        widget=None,
    ) -> QRect:
        if control == QStyle.ComplexControl.CC_SpinBox:
            outer = QRect(option.rect)
            button_width = min(28, max(20, outer.width() // 3))
            inner_height = max(2, outer.height() - 2)
            upper_height = inner_height // 2
            button_left = outer.right() - button_width + 1
            if sub_control == QStyle.SubControl.SC_SpinBoxUp:
                logical = QRect(
                    button_left,
                    outer.top() + 1,
                    button_width - 1,
                    upper_height,
                )
                return self.visualRect(option.direction, outer, logical)
            if sub_control == QStyle.SubControl.SC_SpinBoxDown:
                logical = QRect(
                    button_left,
                    outer.top() + 1 + upper_height,
                    button_width - 1,
                    inner_height - upper_height,
                )
                return self.visualRect(option.direction, outer, logical)
            if sub_control == QStyle.SubControl.SC_SpinBoxEditField:
                logical = outer.adjusted(6, 2, -button_width - 2, -2)
                return self.visualRect(option.direction, outer, logical)
        return super().subControlRect(control, option, sub_control, widget)

    @staticmethod
    def _control_colours(option) -> tuple[QColor, QColor, QColor]:
        enabled = bool(option.state & QStyle.StateFlag.State_Enabled)
        checked = bool(option.state & QStyle.StateFlag.State_On)
        partial = bool(option.state & QStyle.StateFlag.State_NoChange)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        focused = bool(option.state & QStyle.StateFlag.State_HasFocus)

        if not enabled:
            return QColor("#f2f4f5"), QColor("#bdc7cf"), QColor("#8c98a3")
        if checked or partial:
            return QColor("#276e9d"), QColor("#205f88"), QColor("#ffffff")
        border = QColor("#2b78a7") if hovered or focused else QColor("#718595")
        return QColor("#ffffff"), border, QColor("#ffffff")

    @classmethod
    def _draw_checkbox(cls, option, painter: QPainter) -> None:
        fill, border, mark = cls._control_colours(option)
        rect = QRectF(option.rect).adjusted(0.75, 0.75, -0.75, -0.75)
        checked = bool(option.state & QStyle.StateFlag.State_On)
        partial = bool(option.state & QStyle.StateFlag.State_NoChange)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(border, 1.5))
        painter.setBrush(fill)
        painter.drawRoundedRect(rect, 3.0, 3.0)

        if checked:
            path = QPainterPath()
            path.moveTo(rect.left() + rect.width() * 0.22, rect.top() + rect.height() * 0.52)
            path.lineTo(rect.left() + rect.width() * 0.43, rect.top() + rect.height() * 0.73)
            path.lineTo(rect.left() + rect.width() * 0.79, rect.top() + rect.height() * 0.30)
            pen = QPen(mark, 2.0)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
        elif partial:
            pen = QPen(mark, 2.0)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            y = rect.center().y()
            painter.drawLine(
                int(rect.left() + rect.width() * 0.25),
                int(y),
                int(rect.right() - rect.width() * 0.25),
                int(y),
            )
        painter.restore()

    @classmethod
    def _draw_radio_button(cls, option, painter: QPainter) -> None:
        fill, border, mark = cls._control_colours(option)
        rect = QRectF(option.rect).adjusted(0.75, 0.75, -0.75, -0.75)
        checked = bool(option.state & QStyle.StateFlag.State_On)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(border, 1.5))
        painter.setBrush(fill if not checked else QColor("#ffffff"))
        painter.drawEllipse(rect)
        if checked:
            inner = rect.adjusted(
                rect.width() * 0.27,
                rect.height() * 0.27,
                -rect.width() * 0.27,
                -rect.height() * 0.27,
            )
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(fill if fill != QColor("#ffffff") else mark)
            painter.drawEllipse(inner)
        painter.restore()

    @staticmethod
    def _draw_arrow(
        option,
        painter: QPainter,
        direction: str,
        *,
        minimum_radius: float = 2.5,
        scale: float = 0.22,
    ) -> None:
        enabled = bool(option.state & QStyle.StateFlag.State_Enabled)
        colour = QColor("#526b7d") if enabled else QColor("#9ca8b2")
        center = QRectF(option.rect).center()
        radius = max(minimum_radius, min(option.rect.width(), option.rect.height()) * scale)
        points = {
            "down": (
                (center.x() - radius, center.y() - radius * 0.45),
                (center.x(), center.y() + radius * 0.55),
                (center.x() + radius, center.y() - radius * 0.45),
            ),
            "up": (
                (center.x() - radius, center.y() + radius * 0.45),
                (center.x(), center.y() - radius * 0.55),
                (center.x() + radius, center.y() + radius * 0.45),
            ),
            "left": (
                (center.x() + radius * 0.45, center.y() - radius),
                (center.x() - radius * 0.55, center.y()),
                (center.x() + radius * 0.45, center.y() + radius),
            ),
            "right": (
                (center.x() - radius * 0.45, center.y() - radius),
                (center.x() + radius * 0.55, center.y()),
                (center.x() - radius * 0.45, center.y() + radius),
            ),
        }[direction]
        path = QPainterPath()
        path.moveTo(*points[0])
        path.lineTo(*points[1])
        path.lineTo(*points[2])
        pen = QPen(colour, 1.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        painter.restore()


def light_palette() -> QPalette:
    """Return the complete application palette used by the light-only UI."""

    palette = QPalette()
    colours = {
        QPalette.ColorRole.Window: "#f4f6f8",
        QPalette.ColorRole.WindowText: "#243244",
        QPalette.ColorRole.Base: "#ffffff",
        QPalette.ColorRole.AlternateBase: "#f7f9fb",
        QPalette.ColorRole.ToolTipBase: "#ffffff",
        QPalette.ColorRole.ToolTipText: "#243244",
        QPalette.ColorRole.Text: "#243244",
        QPalette.ColorRole.Button: "#f7f9fb",
        QPalette.ColorRole.ButtonText: "#243244",
        QPalette.ColorRole.BrightText: "#ffffff",
        QPalette.ColorRole.Light: "#ffffff",
        QPalette.ColorRole.Midlight: "#e7edf2",
        QPalette.ColorRole.Mid: "#bdc9d3",
        QPalette.ColorRole.Dark: "#718292",
        QPalette.ColorRole.Shadow: "#465767",
        QPalette.ColorRole.Highlight: "#2b78a7",
        QPalette.ColorRole.HighlightedText: "#ffffff",
        QPalette.ColorRole.Link: "#176b9b",
        QPalette.ColorRole.LinkVisited: "#62529b",
        QPalette.ColorRole.PlaceholderText: "#7d8b98",
    }
    for role, colour in colours.items():
        palette.setColor(QPalette.ColorGroup.All, role, QColor(colour))
    for role, colour in (
        (QPalette.ColorRole.WindowText, "#8c98a3"),
        (QPalette.ColorRole.Text, "#8c98a3"),
        (QPalette.ColorRole.ButtonText, "#8c98a3"),
        (QPalette.ColorRole.HighlightedText, "#ffffff"),
    ):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(colour))
    return palette


def apply_light_theme(application: QApplication) -> None:
    """Force Fusion plus a light palette, independent of the OS appearance."""

    style = LightFusionStyle()
    application.setStyle(style)
    # Keep the Python wrapper alive for the process lifetime. Qt owns the C++
    # style after setStyle(), but retaining the wrapper avoids binding-specific
    # collection differences across supported PySide releases.
    application._plug_analyzer_light_style = style  # type: ignore[attr-defined]
    application.setPalette(light_palette())
