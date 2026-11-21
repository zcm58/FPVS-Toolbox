"""Keep the desktop responsive while the ledger owner checks processing inputs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from threading import Event
from typing import Any

from PySide6.QtCore import QEventLoop, Qt, QThread, QTimer
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QProgressBar, QWidget
from shiboken6 import isValid

from Main_App.gui.components import AppDialog
from Main_App.processing.processing_controller import RawFileInfo
from Main_App.processing.processing_ledger import (
    ProcessingPlan, carry_forward_pre_qc_completed_states, classify_processing_inputs,
)


def _checked_plan(project, files, settings, event_map, pre_qc_plan, cancel_event=None):
    plan = classify_processing_inputs(project, files, settings, event_map, cancel_event=cancel_event)
    return carry_forward_pre_qc_completed_states(project, pre_qc_plan, plan, cancel_event=cancel_event)


class _InputCheck(QThread):
    def __init__(self, project, files, settings, event_map, pre_qc_plan):
        super().__init__()
        # Only the GUI thread reads the active project's mutable in-memory model.
        # RawFileInfo is frozen. No widgets or callbacks go to the classifier.
        self.project = deepcopy(project)
        self.files = tuple(files)
        self.settings = deepcopy(settings)
        self.event_map = dict(event_map)
        self.pre_qc_plan = deepcopy(pre_qc_plan)
        self.cancel_event = Event()
        self.plan: ProcessingPlan | None = None
        self.error: Exception | None = None

    def run(self) -> None:
        try:
            self.plan = _checked_plan(
                self.project, self.files, self.settings, self.event_map, self.pre_qc_plan, self.cancel_event,
            )
        except Exception as exc:
            self.error = exc


class _InputCheckDialog(AppDialog):
    def __init__(self, host: QWidget, cancel_event: Event):
        super().__init__("Checking processing inputs", host)
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.cancel_event = cancel_event
        self.status = QLabel("Checking recordings and previously saved results.", self)
        self.root_layout.addWidget(self.status)
        progress = QProgressBar(self)
        progress.setRange(0, 0)
        self.root_layout.addWidget(progress)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel, self)
        self.buttons.rejected.connect(self.reject)
        self.root_layout.addWidget(self.buttons)

    def reject(self) -> None:
        # Keep the parent protected until the classifier releases its read handles.
        self.cancel_event.set()
        self.buttons.setEnabled(False)
        self.status.setText("Cancelling the input check…")


def check_processing_inputs(
    host: Any,
    files: Sequence[RawFileInfo],
    settings: Mapping[str, Any],
    event_map: Mapping[str, int],
    *,
    pre_qc_plan: ProcessingPlan | None = None,
) -> ProcessingPlan | None:
    """Finish this check before the next prompt, while Qt continues handling events."""
    project = host.currentProject
    if not isinstance(host, QWidget):
        # Non-widget workflow callers have no Qt window or running GUI event loop.
        return _checked_plan(project, files, settings, event_map, pre_qc_plan)
    if getattr(host, "_processing_input_check", None) is not None:
        return None
    thread = _InputCheck(project, files, settings, event_map, pre_qc_plan)
    dialog = _InputCheckDialog(host, thread.cancel_event)
    host._processing_input_check = dialog
    grace = QEventLoop()
    delay = QTimer()
    delay.setSingleShot(True)
    delay.timeout.connect(grace.quit)
    dialog.destroyed.connect(grace.quit)
    thread.finished.connect(dialog.accept, Qt.ConnectionType.QueuedConnection)
    thread.finished.connect(grace.quit, Qt.ConnectionType.QueuedConnection)
    try:
        thread.start()
        # Fast checks finish without flashing a dialog. Paint and timer events
        # continue during this brief interval before the window becomes modal.
        delay.start(200)
        grace.exec(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
        if not delay.isActive() and isValid(dialog) and dialog.result() != QDialog.DialogCode.Accepted:
            dialog.exec()
    finally:
        delay.stop()
        # An application quit can unwind the modal loop before the reader finishes.
        if not isValid(dialog) or dialog.result() != QDialog.DialogCode.Accepted:
            thread.cancel_event.set()
        thread.wait()
        host._processing_input_check = None
        if isValid(dialog):
            dialog.deleteLater()
    if thread.cancel_event.is_set() or host.currentProject is not project:
        return None
    if thread.error is not None:
        raise thread.error
    return thread.plan
