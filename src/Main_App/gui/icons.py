from __future__ import annotations

from functools import lru_cache
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPalette, QPixmap, QPen
from PySide6.QtWidgets import QApplication

from Main_App.gui.typography import font_for_role


def _icon_color() -> QColor:
    app = QApplication.instance()
    return app.palette().color(QPalette.ButtonText) if app else QColor("white")


def _stroke(size: int) -> QPen:
    pen = QPen(_icon_color())
    pen.setWidth(max(2, round(size * 0.1)))
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    return pen


def _draw_dot(painter: QPainter, center: QPointF, radius: float) -> None:
    painter.setBrush(_icon_color())
    painter.drawEllipse(center, radius, radius)
    painter.setBrush(Qt.NoBrush)


@lru_cache(maxsize=32)
def sidebar_icon(kind: str, size: int = 20) -> QIcon:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(_stroke(size))
    painter.setBrush(Qt.NoBrush)

    if kind == "home":
        painter.drawLine(QPointF(size * 0.18, size * 0.48), QPointF(size * 0.50, size * 0.20))
        painter.drawLine(QPointF(size * 0.50, size * 0.20), QPointF(size * 0.82, size * 0.48))
        painter.drawRoundedRect(QRectF(size * 0.27, size * 0.45, size * 0.46, size * 0.38), 2, 2)
    elif kind == "stats":
        painter.drawRoundedRect(QRectF(size * 0.18, size * 0.22, size * 0.64, size * 0.46), 2, 2)
        painter.drawLine(QPointF(size * 0.50, size * 0.68), QPointF(size * 0.50, size * 0.82))
        painter.drawLine(QPointF(size * 0.35, size * 0.82), QPointF(size * 0.65, size * 0.82))
    elif kind == "chart":
        for index, height in enumerate((0.30, 0.52, 0.72)):
            x = size * (0.26 + index * 0.22)
            painter.drawLine(QPointF(x, size * 0.78), QPointF(x, size * (0.78 - height)))
    elif kind == "ratio":
        painter.drawLine(QPointF(size * 0.28, size * 0.50), QPointF(size * 0.72, size * 0.50))
        _draw_dot(painter, QPointF(size * 0.50, size * 0.30), size * 0.055)
        _draw_dot(painter, QPointF(size * 0.50, size * 0.70), size * 0.055)
    elif kind == "detectability":
        center = QPointF(size * 0.50, size * 0.50)
        painter.drawEllipse(center, size * 0.34, size * 0.34)
        painter.drawEllipse(center, size * 0.16, size * 0.16)
        painter.drawLine(QPointF(size * 0.50, size * 0.14), QPointF(size * 0.50, size * 0.28))
        painter.drawLine(QPointF(size * 0.50, size * 0.72), QPointF(size * 0.50, size * 0.86))
        painter.drawLine(QPointF(size * 0.14, size * 0.50), QPointF(size * 0.28, size * 0.50))
        painter.drawLine(QPointF(size * 0.72, size * 0.50), QPointF(size * 0.86, size * 0.50))
    elif kind == "scalp":
        center = QPointF(size * 0.50, size * 0.50)
        painter.drawEllipse(center, size * 0.34, size * 0.34)
        painter.drawArc(QRectF(size * 0.28, size * 0.28, size * 0.44, size * 0.44), 25 * 16, 300 * 16)
        painter.drawArc(QRectF(size * 0.38, size * 0.36, size * 0.24, size * 0.28), 25 * 16, 300 * 16)
        _draw_dot(painter, QPointF(size * 0.36, size * 0.38), size * 0.035)
        _draw_dot(painter, QPointF(size * 0.64, size * 0.38), size * 0.035)
        _draw_dot(painter, QPointF(size * 0.50, size * 0.62), size * 0.035)
    elif kind == "loreta":
        center = QPointF(size * 0.50, size * 0.50)
        painter.drawEllipse(center, size * 0.32, size * 0.36)
        painter.drawLine(QPointF(size * 0.50, size * 0.20), QPointF(size * 0.50, size * 0.80))
        painter.drawArc(QRectF(size * 0.26, size * 0.26, size * 0.25, size * 0.22), 20 * 16, 210 * 16)
        painter.drawArc(QRectF(size * 0.49, size * 0.26, size * 0.25, size * 0.22), -50 * 16, 210 * 16)
        painter.drawArc(QRectF(size * 0.28, size * 0.51, size * 0.22, size * 0.20), 30 * 16, 210 * 16)
        painter.drawArc(QRectF(size * 0.50, size * 0.51, size * 0.22, size * 0.20), -60 * 16, 210 * 16)
        _draw_dot(painter, QPointF(size * 0.61, size * 0.58), size * 0.045)
    elif kind == "image":
        painter.drawRoundedRect(QRectF(size * 0.18, size * 0.24, size * 0.64, size * 0.52), 2, 2)
        painter.drawEllipse(QPointF(size * 0.38, size * 0.40), size * 0.055, size * 0.055)
        painter.drawLine(QPointF(size * 0.28, size * 0.68), QPointF(size * 0.43, size * 0.55))
        painter.drawLine(QPointF(size * 0.43, size * 0.55), QPointF(size * 0.55, size * 0.64))
        painter.drawLine(QPointF(size * 0.55, size * 0.64), QPointF(size * 0.68, size * 0.48))
    elif kind == "report":
        painter.drawRoundedRect(QRectF(size * 0.24, size * 0.16, size * 0.52, size * 0.68), 2, 2)
        painter.drawLine(QPointF(size * 0.35, size * 0.34), QPointF(size * 0.65, size * 0.34))
        painter.drawLine(QPointF(size * 0.35, size * 0.48), QPointF(size * 0.65, size * 0.48))
        painter.drawLine(QPointF(size * 0.35, size * 0.62), QPointF(size * 0.56, size * 0.62))
    elif kind == "epoch":
        painter.drawArc(QRectF(size * 0.20, size * 0.20, size * 0.60, size * 0.60), 35 * 16, 285 * 16)
        painter.drawLine(QPointF(size * 0.76, size * 0.24), QPointF(size * 0.80, size * 0.42))
        painter.drawLine(QPointF(size * 0.76, size * 0.24), QPointF(size * 0.59, size * 0.27))
    elif kind == "settings":
        center = QPointF(size * 0.50, size * 0.50)
        painter.drawEllipse(center, size * 0.22, size * 0.22)
        painter.drawEllipse(center, size * 0.075, size * 0.075)
        for index in range(8):
            angle = index * math.pi / 4
            inner = size * 0.31
            outer = size * 0.42
            painter.drawLine(
                QPointF(center.x() + math.cos(angle) * inner, center.y() + math.sin(angle) * inner),
                QPointF(center.x() + math.cos(angle) * outer, center.y() + math.sin(angle) * outer),
            )
    elif kind == "info":
        center = QPointF(size * 0.50, size * 0.50)
        painter.drawEllipse(center, size * 0.34, size * 0.34)
        _draw_dot(painter, QPointF(size * 0.50, size * 0.34), size * 0.045)
        painter.drawLine(QPointF(size * 0.50, size * 0.46), QPointF(size * 0.50, size * 0.66))
    elif kind == "help":
        center = QPointF(size * 0.50, size * 0.50)
        painter.drawEllipse(center, size * 0.34, size * 0.34)
        font = font_for_role("icon_glyph", QApplication.font() if QApplication.instance() else None)
        font.setPixelSize(max(1, int(size * 0.58)))
        painter.setFont(font)
        painter.drawText(pixmap.rect(), Qt.AlignCenter, "?")
    else:
        painter.drawEllipse(QPointF(size * 0.50, size * 0.50), size * 0.32, size * 0.32)

    painter.end()
    return QIcon(pixmap)


@lru_cache(maxsize=4)
def division_icon(size: int = 16) -> QIcon:
    return sidebar_icon("ratio", size)


@lru_cache(maxsize=4)
def individual_detectability_icon(size: int = 16) -> QIcon:
    return sidebar_icon("detectability", size)


@lru_cache(maxsize=4)
def settings_icon(size: int = 16) -> QIcon:
    return sidebar_icon("settings", size)
