from __future__ import annotations
from PySide6.QtCore import QTimer, QSize, Qt
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import QWidget


class BusySpinner(QWidget):
    """Tiny rotating arc spinner. Start/stop to show activity."""

    def __init__(self, parent: QWidget | None = None, diameter: int = 18) -> None:
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.setInterval(16)  # ~60 FPS
        self._timer.timeout.connect(self._tick)
        self._angle = 0
        self._diameter = int(diameter)
        # +2 padding ensures the anti-aliased edges don't get clipped
        self.setFixedSize(QSize(self._diameter + 2, self._diameter + 2))
        # Crucial: lets clicks pass through to the widget underneath
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def sizeHint(self) -> QSize:  # type: ignore[override]
        return QSize(self._diameter + 2, self._diameter + 2)

    def start(self) -> None:
        if not self._timer.isActive():
            self._angle = 0
            self._timer.start()
            self.show()

    def stop(self) -> None:
        if self._timer.isActive():
            self._timer.stop()
        self.hide()

    # --- internals ---
    def _tick(self) -> None:
        self._angle = (self._angle + 6) % 360
        self.update()

    def paintEvent(self, _e) -> None:  # type: ignore[override]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # Use system highlight color (adapts to dark/light mode automatically)
        pen = QPen(self.palette().highlight().color())

        # Dynamic pen width based on screen DPI
        pen.setWidthF(max(1.5, self.devicePixelRatioF() * 1.25))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)

        # CLOCKWISE FIX:
        # We invert the angle (-self._angle).
        # Positive angle moves CCW (math standard), Negative moves CW.
        start_deg = int(-self._angle * 16)
        span_deg = int(-270 * 16)

        # Inset rect by 3px to ensure the thick pen stroke isn't clipped at the edges
        rect = self.rect().adjusted(3, 3, -3, -3)

        p.drawArc(rect, start_deg, span_deg)

        p.end()