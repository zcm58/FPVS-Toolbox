from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QIconEngine, QPainter, QPalette, QPixmap, QPen
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

from Main_App.gui.style_tokens import ACCENT_COLOR


def _icon_color() -> QColor:
    app = QApplication.instance()
    return app.palette().color(QPalette.ButtonText) if app else QColor("white")


def _draw_dot(painter: QPainter, center: QPointF, radius: float) -> None:
    painter.setBrush(_icon_color())
    painter.drawEllipse(center, radius, radius)
    painter.setBrush(Qt.NoBrush)


_SIDEBAR_ICON_PATHS = {
    "home": """
        <path d="M3 10.5 12 3l9 7.5"/><path d="M5.5 9.5V21h13V9.5"/>
        <path d="M9.5 21v-7h5v7"/>
    """,
    "stats": """
        <rect x="3" y="3.5" width="18" height="14" rx="2"/>
        <path d="m7 13 3-3 3 2 4-4"/><path d="M8 21h8M12 17.5V21"/>
    """,
    "harmonic": """
        <path d="M2.5 13 6 7l4 10 4-8 4 6 3.5-4"/>
        <circle cx="2.5" cy="13" r=".8"/><circle cx="6" cy="7" r=".8"/>
        <circle cx="10" cy="17" r=".8"/><circle cx="14" cy="9" r=".8"/>
        <circle cx="18" cy="15" r=".8"/><circle cx="21.5" cy="11" r=".8"/>
    """,
    "sensitivity": """
        <path d="M4 18a8 8 0 0 1 16 0"/><path d="M6.5 18h11"/>
        <path d="m12 15 4-4"/><circle cx="12" cy="15" r="1"/>
    """,
    "chart": """
        <path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>
    """,
    "ratio": """
        <circle cx="12" cy="6" r="1.5"/><path d="M6 12h12"/>
        <circle cx="12" cy="18" r="1.5"/>
    """,
    "detectability": """
        <circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3"/>
        <path d="M12 2v3M12 19v3M2 12h3M19 12h3"/>
    """,
    "scalp": """
        <circle cx="12" cy="12" r="8.5"/><path d="M12 3.5v4M7 6.5l2.5 3M17 6.5l-2.5 3"/>
        <path d="M6 14.5h12M8.5 18l2-3.5M15.5 18l-2-3.5"/>
        <circle cx="12" cy="11" r="1"/>
    """,
    "loreta": """
        <path d="M12 5.5c-1-3.5-6-3-6 1-3 .5-3 5-.5 6.5-1 3.5 3 6.5 6.5 4.5"/>
        <path d="M12 5.5c1-3.5 6-3 6 1 3 .5 3 5 .5 6.5 1 3.5-3 6.5-6.5 4.5V5.5Z"/>
        <path d="M8 8.5c2 0 2 2 4 2M16 8.5c-2 0-2 2-4 2M8 14c2 0 2-2 4-2M16 14c-2 0-2-2-4-2"/>
    """,
    "image": """
        <rect x="3" y="4" width="18" height="16" rx="2"/>
        <circle cx="8.5" cy="9" r="1.5"/><path d="m4 18 5-5 3 3 3-3 5 5"/>
    """,
    "sequence": """
        <rect x="2.5" y="4" width="5" height="5" rx="1"/>
        <rect x="9.5" y="4" width="5" height="5" rx="1"/>
        <rect x="16.5" y="4" width="5" height="5" rx="1"/>
        <path d="M5 14v5M19 14v5M5 16.5h14"/>
    """,
    "report": """
        <path d="M6 2.5h9l4 4V21.5H6Z"/><path d="M15 2.5v4h4M9 11h6M9 15h6M9 19h4"/>
    """,
    "settings": """
        <circle cx="12" cy="12" r="3"/>
        <path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5.3 5.3l2.1 2.1M16.6 16.6l2.1 2.1M18.7 5.3l-2.1 2.1M7.4 16.6l-2.1 2.1"/>
        <circle cx="12" cy="12" r="7"/>
    """,
    "info": """
        <circle cx="12" cy="12" r="9"/><path d="M12 11v6"/>
        <path d="M12 7h.01" stroke-width="3"/>
    """,
    "help": """
        <circle cx="12" cy="12" r="9"/>
        <path d="M9.6 9a2.5 2.5 0 1 1 3.5 2.3c-.8.4-1.1.9-1.1 1.7v.5M12 17h.01"/>
    """,
}


def _sidebar_svg(kind: str, *, disabled: bool) -> QByteArray:
    paths = _SIDEBAR_ICON_PATHS.get(kind, '<circle cx="12" cy="12" r="8"/>')
    opacity = "0.38" if disabled else "1"
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"
        fill="none" stroke="#ffffff" stroke-width="1.8" stroke-linecap="round"
        stroke-linejoin="round" stroke-opacity="{opacity}">{paths}</svg>"""
    return QByteArray(svg.encode("utf-8"))


class _SidebarSvgIconEngine(QIconEngine):
    """Render a consistent sidebar SVG at the display's native pixel density."""

    def __init__(self, kind: str) -> None:
        super().__init__()
        self._kind = kind

    def clone(self) -> QIconEngine:
        return _SidebarSvgIconEngine(self._kind)

    def key(self) -> str:
        return "FPVSSidebarSvgIcon"

    def isNull(self) -> bool:
        return False

    def paint(
        self,
        painter: QPainter,
        rect: QRect,
        mode: QIcon.Mode,
        _state: QIcon.State,
    ) -> None:
        renderer = QSvgRenderer(
            _sidebar_svg(self._kind, disabled=mode == QIcon.Disabled)
        )
        renderer.render(painter, QRectF(rect))

    def pixmap(
        self,
        size: QSize,
        mode: QIcon.Mode,
        state: QIcon.State,
    ) -> QPixmap:
        pixmap = QPixmap(size)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        self.paint(painter, QRect(0, 0, size.width(), size.height()), mode, state)
        painter.end()
        return pixmap

    def scaledPixmap(
        self,
        size: QSize,
        mode: QIcon.Mode,
        state: QIcon.State,
        scale: float,
    ) -> QPixmap:
        pixel_size = QSize(
            max(1, round(size.width() * scale)),
            max(1, round(size.height() * scale)),
        )
        pixmap = QPixmap(pixel_size)
        pixmap.setDevicePixelRatio(scale)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        self.paint(painter, QRect(0, 0, size.width(), size.height()), mode, state)
        painter.end()
        return pixmap


@lru_cache(maxsize=32)
def sidebar_icon(kind: str, size: int = 20) -> QIcon:
    """Return a resolution-independent sidebar icon.

    ``size`` remains part of the compatibility API and cache key; the SVG
    engine renders at the actual size and device-pixel ratio requested by Qt.
    """
    del size
    return QIcon(_SidebarSvgIconEngine(kind))


@lru_cache(maxsize=4)
def division_icon(size: int = 16) -> QIcon:
    return sidebar_icon("ratio", size)


@lru_cache(maxsize=4)
def individual_detectability_icon(size: int = 16) -> QIcon:
    return sidebar_icon("detectability", size)


@lru_cache(maxsize=4)
def settings_icon(size: int = 16) -> QIcon:
    return sidebar_icon("settings", size)


@lru_cache(maxsize=4)
def tool_info_icon(size: int = 20) -> QIcon:
    """Return a high-contrast filled information glyph for icon-only buttons."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(ACCENT_COLOR))

    center = QPointF(size * 0.50, size * 0.50)
    painter.drawEllipse(center, size * 0.42, size * 0.42)

    painter.setBrush(QColor("white"))
    _draw_dot(painter, QPointF(size * 0.50, size * 0.33), size * 0.055)

    pen = QPen(QColor("white"))
    pen.setWidth(max(2, round(size * 0.14)))
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    painter.drawLine(QPointF(size * 0.50, size * 0.47), QPointF(size * 0.50, size * 0.69))

    painter.end()
    return QIcon(pixmap)
