"""Settings category selection with the Studio indicator motion."""

from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes

from PySide6.QtCore import QEasingCurve, QRectF, QSignalBlocker, Qt, QVariantAnimation
from PySide6.QtGui import QHideEvent, QPainter, QPaintEvent
from PySide6.QtWidgets import QListWidget, QStyle, QWidget

from Main_App.gui.style_tokens import ACCENT_COLOR
from Main_App.gui.theme import theme_color


def widget_animation_duration(widget: QWidget, maximum_ms: int) -> int:
    """Respect the Qt style and the Windows animation effects preference."""
    duration = widget.style().styleHint(QStyle.StyleHint.SH_Widget_Animation_Duration, None, widget)
    if duration <= 0:
        return 0
    if sys.platform == "win32":
        enabled = wintypes.BOOL()
        spi_get_client_area_animation = 0x1042
        system_parameters_info = ctypes.WinDLL("user32", use_last_error=True).SystemParametersInfoW
        if not system_parameters_info(spi_get_client_area_animation, 0, ctypes.byref(enabled), 0):
            logging.getLogger(__name__).warning(
                "settings_animation_preference_read_failed", extra={"error": ctypes.get_last_error()}
            )
            return 0
        if not enabled.value:
            return 0
    return min(duration, maximum_ms)


class SettingsNavigation(QListWidget):
    """Keep native list navigation and animate its selected category marker."""

    _TRANSITION_MS = 150
    _INDICATOR_WIDTH = 3
    _INDICATOR_HEIGHT = 18
    _INDICATOR_INSET = 7

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._indicator_row = -1.0
        self._indicator_animation = QVariantAnimation(self)
        self._indicator_animation.setEasingCurve(QEasingCurve.Type.OutExpo)
        self._indicator_animation.valueChanged.connect(self._set_indicator_row)
        self.currentRowChanged.connect(self._animate_indicator)

    def sync_current_row(self, index: int) -> None:
        """Show a programmatic page change immediately, including validation jumps."""
        if self.currentRow() == index:
            return
        self._indicator_animation.stop()
        with QSignalBlocker(self):
            self.setCurrentRow(index)
        self._set_indicator_row(float(index))

    def _animate_indicator(self, index: int) -> None:
        start, target = self._indicator_row, float(index)
        self._indicator_animation.stop()
        duration = (
            widget_animation_duration(self, self._TRANSITION_MS)
            if self.isVisible() and min(start, target) >= 0 and start != target
            else 0
        )
        if not duration:
            self._set_indicator_row(target)
            return
        self._indicator_animation.setDuration(duration)
        self._indicator_animation.setStartValue(start)
        self._indicator_animation.setEndValue(target)
        self._indicator_animation.start()

    def _set_indicator_row(self, row: float) -> None:
        self._indicator_row = row
        self.viewport().update()

    def _indicator_rect(self) -> QRectF:
        row = self._indicator_row
        if not 0 <= row < self.count():
            return QRectF()
        index = int(row)
        item_rect = QRectF(self.visualItemRect(self.item(index)))
        center_y = item_rect.center().y()
        if index + 1 < self.count():
            next_y = QRectF(self.visualItemRect(self.item(index + 1))).center().y()
            center_y += (next_y - center_y) * (row - index)
        return QRectF(
            item_rect.left() + self._INDICATOR_INSET,
            center_y - self._INDICATOR_HEIGHT / 2,
            self._INDICATOR_WIDTH,
            self._INDICATOR_HEIGHT,
        )

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        super().paintEvent(event)
        indicator = self._indicator_rect()
        if indicator.isEmpty():
            return
        radius = self._INDICATOR_WIDTH / 2
        with QPainter(self.viewport()) as painter:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(theme_color(ACCENT_COLOR))
            painter.drawRoundedRect(indicator, radius, radius)

    def hideEvent(self, event: QHideEvent) -> None:  # noqa: N802
        self._indicator_animation.stop()
        self._set_indicator_row(float(self.currentRow()))
        super().hideEvent(event)
