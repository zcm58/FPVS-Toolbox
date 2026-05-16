from __future__ import annotations

from functools import lru_cache
import math

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPainter, QPalette, QPixmap, QPen
from PySide6.QtWidgets import QApplication


@lru_cache(maxsize=4)
def division_icon(size: int = 16) -> QIcon:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(QApplication.palette().color(QPalette.ButtonText))

    font = QApplication.font()
    font.setBold(True)
    font.setPixelSize(max(1, int(size * 0.9)))
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignCenter, "÷")
    painter.end()

    return QIcon(pixmap)


@lru_cache(maxsize=4)
def individual_detectability_icon(size: int = 16) -> QIcon:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    color = QApplication.palette().color(QPalette.ButtonText)
    pen = QPen(color)
    pen.setWidth(max(1, int(size * 0.08)))
    painter.setPen(pen)

    center = pixmap.rect().center()
    radius = int(size * 0.42)
    painter.drawEllipse(center, radius, radius)
    painter.drawEllipse(center, int(radius * 0.55), int(radius * 0.55))
    painter.drawLine(center.x(), int(size * 0.1), center.x(), int(size * 0.9))
    painter.drawLine(int(size * 0.1), center.y(), int(size * 0.9), center.y())

    font = QApplication.font()
    font.setBold(True)
    font.setPixelSize(max(1, int(size * 0.45)))
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignCenter, "ID")
    painter.end()

    return QIcon(pixmap)


@lru_cache(maxsize=4)
def settings_icon(size: int = 16) -> QIcon:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    color = QApplication.palette().color(QPalette.ButtonText)
    pen = QPen(color)
    pen.setWidth(max(1, int(size * 0.1)))
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)

    center = pixmap.rect().center()
    outer_radius = size * 0.33
    inner_radius = size * 0.13
    tooth_inner = size * 0.38
    tooth_outer = size * 0.48

    painter.drawEllipse(center, int(outer_radius), int(outer_radius))
    painter.drawEllipse(center, int(inner_radius), int(inner_radius))

    for index in range(8):
        angle = index * math.pi / 4
        x1 = center.x() + math.cos(angle) * tooth_inner
        y1 = center.y() + math.sin(angle) * tooth_inner
        x2 = center.x() + math.cos(angle) * tooth_outer
        y2 = center.y() + math.sin(angle) * tooth_outer
        painter.drawLine(int(x1), int(y1), int(x2), int(y2))

    painter.end()
    return QIcon(pixmap)
