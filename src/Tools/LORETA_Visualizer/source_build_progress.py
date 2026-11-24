"""Inline progress for the LORETA source-map worker."""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Signal
from PySide6.QtGui import QHideEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QVBoxLayout, QWidget

from Main_App.gui.components import SubsectionHeaderLabel, make_action_button
from Main_App.gui.settings_navigation import widget_animation_duration


class SourceBuildProgress(QWidget):
    """Show the active method, its completed inputs, and safe cancellation."""

    cancel_requested = Signal()

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("loretaSourceBuildProgress")
        self._animation_duration = 0
        self._completed = 0

        title = SubsectionHeaderLabel("Preparing source maps", self)
        self._detail = QLabel(self)
        self._detail.setProperty("caption", True)
        self._detail.setWordWrap(True)
        self._detail.setObjectName("loretaSourceBuildStage")
        self._bar = QProgressBar(self)
        self._bar.setObjectName("loretaSourceBuildBar")
        self._bar.setAccessibleName("Participant-condition inputs completed")
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(12)
        self._bar.setStyleSheet(
            "QProgressBar { padding: 0; border-radius: 4px; }"
            "QProgressBar::chunk { border-radius: 3px; }"
        )
        self._cancel = make_action_button("Cancel build", compact=True, parent=self)
        self._cancel.setObjectName("loretaCancelSourceBuild")
        self._cancel.clicked.connect(self.cancel_requested)

        status = QVBoxLayout()
        status.setSpacing(2)
        status.addWidget(title)
        status.addWidget(self._detail)
        header = QHBoxLayout()
        header.setSpacing(12)
        header.addLayout(status, 1)
        header.addWidget(self._cancel)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 3, 2, 8)
        layout.setSpacing(6)
        layout.addLayout(header)
        layout.addWidget(self._bar)

        self._animation = QPropertyAnimation(self._bar, b"value", self)
        self._animation.setEasingCurve(QEasingCurve.Type.OutExpo)
        self.hide()

    def begin(self) -> None:
        self._animation_duration = widget_animation_duration(self, 180)
        self._cancel.setEnabled(True)
        self.set_stage("Checking source inputs…", 0, 0)
        self.show()

    def set_stage(self, detail: str, completed: int, total: int) -> None:
        self._animation.stop()
        self._completed = completed
        self._bar.setVisible(total > 0 or self._animation_duration > 0)
        if not total:
            self._detail.setText(detail)
            self._bar.setRange(0, 0)
            return

        self._detail.setText(f"{detail} · {completed} of {total} participant-condition inputs complete")
        if self._bar.maximum() != total:
            self._bar.setRange(0, total)
            self._bar.setValue(0)
        if self._animation_duration and self.isVisible() and self._bar.value() != completed:
            self._animation.setDuration(self._animation_duration)
            self._animation.setStartValue(self._bar.value())
            self._animation.setEndValue(completed)
            self._animation.start()
        else:
            self._bar.setValue(completed)

    def cancelling(self) -> None:
        self._cancel.setEnabled(False)
        self._animation.stop()
        self._bar.hide()
        self._detail.setText("Cancelling after the current step…")

    def hideEvent(self, event: QHideEvent) -> None:  # noqa: N802
        self._animation.stop()
        if self._bar.maximum():
            self._bar.setValue(self._completed)
        super().hideEvent(event)
