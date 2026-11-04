"""Always-visible, asynchronous processing history on the project home page."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThreadPool, Qt, Slot
from PySide6.QtWidgets import QLabel, QWidget

from Main_App.gui.components import apply_font_role
from Main_App.gui.processing_history_model import format_processing_history
from Main_App.processing.processing_history import ProcessingHistoryStatus, load_processing_history
from Main_App.workers.processing_history_worker import ProcessingHistoryWorker


class ProcessingHistoryLabel(QLabel):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("No project open", parent)
        self.setObjectName("project_processing_history")
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setWordWrap(True)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.setToolTip(
            "Participants successfully processed in that run; skipped and excluded "
            "recordings are not counted. This does not indicate downstream analysis readiness."
        )
        apply_font_role(self, "caption")
        self._request_id = 0
        self._project_root: str | None = None
        self._worker: ProcessingHistoryWorker | None = None
        self._reload_requested = False

    def refresh(self, project_root: Path | str | None) -> None:
        # Project.project_root is already canonical; filesystem checks belong to the worker.
        root = str(Path(project_root)) if project_root is not None else None
        if self._worker is not None and root == self._project_root:
            self._reload_requested = True
            return
        self._reload_requested = False
        self._request_id += 1
        changed_project = root != self._project_root
        self._project_root = root
        if root is None:
            self._worker = None
            self.setText("No project open")
            return
        if changed_project:
            self.setText("Last completed processing: Checking history…")
        worker = ProcessingHistoryWorker(root, self._request_id, load_processing_history)
        worker.signals.finished.connect(self._on_loaded, Qt.ConnectionType.QueuedConnection)
        self._worker = worker
        QThreadPool.globalInstance().start(worker)

    @Slot(str, int, object)
    def _on_loaded(self, project_root: str, request_id: int, status: object) -> None:
        if project_root != self._project_root or request_id != self._request_id:
            return
        self._worker = None
        if not isinstance(status, ProcessingHistoryStatus):
            status = ProcessingHistoryStatus(state="unavailable")
        self.setText(format_processing_history(status))
        if self._reload_requested:
            self.refresh(project_root)


def refresh_processing_history(host) -> None:
    label = getattr(host, "processing_history_label", None)
    if label is not None:
        project = getattr(host, "currentProject", None)
        label.refresh(getattr(project, "project_root", None))
