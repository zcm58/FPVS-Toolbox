"""Animated welcome-page brain mark."""

from __future__ import annotations

from PySide6.QtCore import Property, QEasingCurve, QPointF, QPropertyAnimation, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget


class BrainPulseWidget(QWidget):
    """Decorative brain line-art widget with looping draw/undraw animation."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("landing_brain_animation")
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedSize(144, 124)

        self._draw_progress = 0.0
        self._animation = QPropertyAnimation(self, b"drawProgress", self)
        self._animation.setStartValue(0.0)
        self._animation.setKeyValueAt(0.48, 1.0)
        self._animation.setKeyValueAt(0.68, 1.0)
        self._animation.setEndValue(0.0)
        self._animation.setDuration(2600)
        self._animation.setLoopCount(-1)
        self._animation.setEasingCurve(QEasingCurve.InOutSine)
        self._animation.start()

    def start(self) -> None:
        if self._animation.state() != QPropertyAnimation.Running:
            self._animation.start()

    def stop(self) -> None:
        self._animation.stop()
        self.setDrawProgress(0.0)

    def sizeHint(self) -> QSize:
        return QSize(144, 124)

    def getDrawProgress(self) -> float:
        return self._draw_progress

    def setDrawProgress(self, value: float) -> None:
        self._draw_progress = max(0.0, min(float(value), 1.0))
        self.update()

    drawProgress = Property(float, getDrawProgress, setDrawProgress)

    def paintEvent(self, _event) -> None:  # noqa: ANN001
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        paths = self._brain_paths()
        guide_color = QColor("#D9EAF9")
        stroke_color = QColor("#3864A8")

        guide_pen = QPen(guide_color, 4.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        stroke_width = 4.2
        active_pen = QPen(stroke_color, stroke_width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)

        painter.setPen(guide_pen)
        for path in paths:
            painter.drawPath(path)

        for path in paths:
            length = max(path.length(), 1.0)
            visible_units = max(0.001, self._draw_progress) * length / stroke_width
            hidden_units = length / stroke_width
            active_pen.setDashPattern([visible_units, hidden_units])
            painter.setPen(active_pen)
            painter.drawPath(path)

    def _brain_paths(self) -> list[QPainterPath]:
        def p(x: float, y: float) -> QPointF:
            return QPointF(x, y)

        outline = QPainterPath(p(28, 58))
        outline.cubicTo(p(12, 54), p(12, 30), p(30, 30))
        outline.cubicTo(p(31, 14), p(54, 10), p(68, 21))
        outline.cubicTo(p(78, 5), p(108, 10), p(114, 30))
        outline.cubicTo(p(134, 30), p(142, 50), p(130, 66))
        outline.cubicTo(p(136, 86), p(108, 98), p(90, 88))
        outline.cubicTo(p(78, 101), p(54, 98), p(48, 82))
        outline.cubicTo(p(31, 88), p(16, 76), p(28, 58))

        stem = QPainterPath(p(76, 88))
        stem.cubicTo(p(84, 96), p(92, 108), p(88, 112))
        stem.cubicTo(p(80, 120), p(70, 108), p(70, 94))
        stem.cubicTo(p(69, 88), p(65, 84), p(58, 82))

        fold_top_left = QPainterPath(p(34, 45))
        fold_top_left.cubicTo(p(44, 29), p(59, 28), p(68, 41))

        fold_mid_left = QPainterPath(p(28, 64))
        fold_mid_left.cubicTo(p(42, 47), p(58, 50), p(64, 64))

        fold_bottom_left = QPainterPath(p(40, 78))
        fold_bottom_left.cubicTo(p(54, 68), p(70, 70), p(78, 82))

        fold_top_right = QPainterPath(p(78, 36))
        fold_top_right.cubicTo(p(92, 20), p(112, 24), p(118, 42))

        fold_mid_right = QPainterPath(p(74, 60))
        fold_mid_right.cubicTo(p(88, 44), p(108, 48), p(114, 66))

        fold_bottom_right = QPainterPath(p(78, 83))
        fold_bottom_right.cubicTo(p(92, 72), p(112, 74), p(122, 86))

        return [
            outline,
            stem,
            fold_top_left,
            fold_mid_left,
            fold_bottom_left,
            fold_top_right,
            fold_mid_right,
            fold_bottom_right,
        ]
