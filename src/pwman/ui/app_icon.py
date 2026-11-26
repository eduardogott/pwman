"""The application icon, drawn with QPainter (also used to generate the .ico file)."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QLinearGradient, QPainter, QPainterPath, QPixmap


def render(size: int) -> QImage:
    img = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    s = size / 256.0

    # Background tile
    grad = QLinearGradient(QPointF(0, 0), QPointF(size, size))
    grad.setColorAt(0.0, QColor("#7c6cff"))
    grad.setColorAt(1.0, QColor("#3f35c9"))
    p.setPen(Qt.NoPen)
    p.setBrush(grad)
    margin = 8 * s
    p.drawRoundedRect(QRectF(margin, margin, size - 2 * margin, size - 2 * margin), 56 * s, 56 * s)

    # Shield
    shield = QPainterPath()
    shield.moveTo(128 * s, 42 * s)
    shield.cubicTo(150 * s, 56 * s, 176 * s, 64 * s, 198 * s, 66 * s)
    shield.cubicTo(198 * s, 140 * s, 178 * s, 192 * s, 128 * s, 216 * s)
    shield.cubicTo(78 * s, 192 * s, 58 * s, 140 * s, 58 * s, 66 * s)
    shield.cubicTo(80 * s, 64 * s, 106 * s, 56 * s, 128 * s, 42 * s)
    shield.closeSubpath()
    p.setBrush(QColor("#ffffff"))
    p.drawPath(shield)

    # Keyhole
    p.setBrush(QColor("#4b40d6"))
    p.drawEllipse(QPointF(128 * s, 114 * s), 20 * s, 20 * s)
    hole = QPainterPath()
    hole.moveTo(119 * s, 122 * s)
    hole.lineTo(137 * s, 122 * s)
    hole.lineTo(143 * s, 168 * s)
    hole.lineTo(113 * s, 168 * s)
    hole.closeSubpath()
    p.drawPath(hole)
    p.end()
    return img


def app_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 20, 24, 32, 40, 48, 64, 128, 256):
        icon.addPixmap(QPixmap.fromImage(render(size)))
    return icon
