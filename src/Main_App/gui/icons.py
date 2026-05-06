from __future__ import annotations

from functools import lru_cache

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
