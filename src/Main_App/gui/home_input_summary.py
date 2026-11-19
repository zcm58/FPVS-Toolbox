"""Read-only recording preview for the current Home processing scope."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, Signal, Slot
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from Main_App.gui.components import SubsectionHeaderLabel
from Main_App.processing.processing_controller import (
    RawFileInfo,
    prepare_batch_file_infos,
    prepare_raw_registration_review,
)
from Main_App.projects.grouping import project_group_context

if TYPE_CHECKING:
    from Main_App.projects import Project

logger = logging.getLogger(__name__)


def summarize_batch(project: Project) -> tuple[str, str]:
    """Count files from the same read-only discovery used at processing start."""
    if project.groups_locked or project.frequency_protocol.condition_trigger_maps is not None:
        files = prepare_raw_registration_review(project).files
    else:
        files = prepare_batch_file_infos(project)
    counts = Counter(info.group for info in files)
    groups = project_group_context(project).groups
    distribution = [f"{counts[group.group_id]:,} in {group.label}" for group in groups]
    if groups and counts[None]:
        distribution.append(f"{counts[None]:,} without a group")
    count = len(files)
    unit = "file" if count == 1 else "files"
    return f"{count:,} {unit} found", " · ".join(distribution)


class _SummarySignals(QObject):
    finished = Signal(int, str, str, str)


class _BatchSummaryJob(QRunnable):
    def __init__(self, request: int, project: Project) -> None:
        super().__init__()
        self.request = request
        self.project = project
        self.signals = _SummarySignals()

    def run(self) -> None:
        try:
            title, details = summarize_batch(self.project)
            error = ""
        except Exception as exc:
            logger.warning("home_batch_summary_failed", exc_info=True)
            title, details, error = "Could not check input files", "", str(exc)
        self.signals.finished.emit(self.request, title, details, error)


class HomeInputSummary(QWidget):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.title = SubsectionHeaderLabel("Select a data input folder", self)
        self.title.setObjectName("home_recording_count")
        self.details = QLabel(self)
        self.details.setObjectName("home_recording_details")
        for label in (self.title, self.details):
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setWordWrap(True)
            layout.addWidget(label)
        self.details.hide()
        self._request = 0
        self._job: _BatchSummaryJob | None = None
        self._pending: _BatchSummaryJob | None = None

    def refresh_batch(self, project: Project | None) -> None:
        self._request += 1
        self._pending = None
        if project is None:
            self._show("Select a data input folder")
            return
        self._show("Checking input files…")
        self._pending = _BatchSummaryJob(self._request, deepcopy(project))
        self._start_pending()

    def show_single(self, project: Project, info: RawFileInfo) -> None:
        self._request += 1
        self._pending = None
        group = project.groups.get(info.group, {}) if info.group else {}
        details = (group.get("label") or info.group, info.session_label or info.session_id)
        self._show(info.subject_id, " · ".join(value for value in details if value))

    def _start_pending(self) -> None:
        if self._job is not None or self._pending is None:
            return
        self._job, self._pending = self._pending, None
        self._job.signals.finished.connect(self._loaded, Qt.ConnectionType.QueuedConnection)
        QThreadPool.globalInstance().start(self._job)

    @Slot(int, str, str, str)
    def _loaded(self, request: int, title: str, details: str, error: str) -> None:
        self._job = None
        if request == self._request:
            self._show(title, details, error)
        self._start_pending()

    def _show(self, title: str, details: str = "", error: str = "") -> None:
        self.title.setText(title)
        self.title.setToolTip(error)
        self.details.setText(details)
        self.details.setVisible(bool(details))
