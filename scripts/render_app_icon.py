#!/usr/bin/env python3
"""Render the code-native Plug Analyzer app icon as PNG and Windows ICO."""

from __future__ import annotations

import argparse
import struct
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen


def render_icon(size: int) -> QImage:
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    scale = size / 1024.0

    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    background = QPainterPath()
    background.addRoundedRect(
        QRectF(52 * scale, 52 * scale, 920 * scale, 920 * scale), 190 * scale, 190 * scale
    )
    painter.fillPath(background, QColor("#10263f"))

    lumen = QPainterPath()
    lumen.addRoundedRect(
        QRectF(165 * scale, 330 * scale, 694 * scale, 364 * scale), 150 * scale, 150 * scale
    )
    painter.fillPath(lumen, QColor("#081623"))

    wall_pen = QPen(QColor("#63d5e8"), 42 * scale)
    wall_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(wall_pen)
    painter.drawLine(255 * scale, 343 * scale, 796 * scale, 343 * scale)
    painter.drawLine(255 * scale, 681 * scale, 796 * scale, 681 * scale)

    plug = QPainterPath()
    plug.moveTo(172 * scale, 365 * scale)
    plug.cubicTo(250 * scale, 338 * scale, 338 * scale, 374 * scale, 402 * scale, 434 * scale)
    plug.cubicTo(438 * scale, 469 * scale, 438 * scale, 555 * scale, 402 * scale, 590 * scale)
    plug.cubicTo(338 * scale, 650 * scale, 250 * scale, 686 * scale, 172 * scale, 659 * scale)
    plug.closeSubpath()
    painter.fillPath(plug, QColor("#f6bb43"))

    highlight_pen = QPen(QColor("#fff1ae"), 22 * scale)
    highlight_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(highlight_pen)
    painter.drawLine(224 * scale, 425 * scale, 325 * scale, 459 * scale)

    slice_pen = QPen(QColor("#a5eef7"), 20 * scale)
    slice_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(slice_pen)
    for x, half_height in ((570, 92), (650, 120), (730, 92)):
        painter.drawLine(
            x * scale,
            (512 - half_height) * scale,
            x * scale,
            (512 + half_height) * scale,
        )

    painter.end()
    return image


def save_png(image: QImage, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
        ) as stream:
            temporary = Path(stream.name)
        if not image.save(str(temporary), "PNG"):
            raise RuntimeError(f"Qt could not encode PNG: {path}")
        temporary.replace(path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def save_ico(image: QImage, path: Path) -> None:
    icon_image = image.scaled(
        256,
        256,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    buffer = QBuffer()
    if not buffer.open(QIODevice.OpenModeFlag.WriteOnly) or not icon_image.save(buffer, "PNG"):
        raise RuntimeError("Qt could not encode the PNG payload for the ICO")
    payload = bytes(buffer.data())
    # ICO width/height bytes use zero to represent 256 pixels. Modern Windows
    # supports a PNG payload, preserving alpha without a hand-written bitmap mask.
    directory = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack("<BBBBHHII", 0, 0, 0, 0, 1, 32, len(payload), 22)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(directory + entry + payload)
        temporary.replace(path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--png", type=Path, required=True)
    parser.add_argument("--ico", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        image = render_icon(1024)
        save_png(image, args.png.resolve())
        save_ico(image, args.ico.resolve())
    except (OSError, RuntimeError) as exc:
        print(f"icon generation failed: {exc}", file=sys.stderr)
        return 2
    print(f"wrote code-generated app icons: {args.png.resolve()}, {args.ico.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
