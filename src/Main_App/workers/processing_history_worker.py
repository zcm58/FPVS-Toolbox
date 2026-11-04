"""Read saved project processing history away from the GUI thread."""

from __future__ import annotations

from collections.abc import Callable
import logging
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Signal

from Main_App.processing.processing_history import ProcessingHistoryStatus


logger = logging.getLogger(__name__)


class ProcessingHistorySignals(QObject):
    finished = Signal(str, int, object)


class ProcessingHistoryWorker(QRunnable):
    def __init__(
        self, project_root: str, request_id: int,
        loader: Callable[[Path], ProcessingHistoryStatus],
    ) -> None:
        super().__init__()
        self.project_root = project_root
        self.request_id = request_id
        self.loader = loader
        self.signals = ProcessingHistorySignals()

    def run(self) -> None:
        try:
            result = self.loader(Path(self.project_root))
        except Exception:  # GUI worker boundary: always return a visible unavailable state.
            logger.warning("processing_history_read_failed project=%s", self.project_root, exc_info=True)
            result = ProcessingHistoryStatus(state="unavailable")
        self.signals.finished.emit(self.project_root, self.request_id, result)
