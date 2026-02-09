from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPainter, QPalette, QPixmap
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
