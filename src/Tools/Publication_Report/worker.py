"""Qt worker for publication report generation."""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal, Slot

from Tools.Publication_Report.models import PublicationReportRequest, PublicationReportResult
from Tools.Publication_Report.runner import generate_publication_report

logger = logging.getLogger(__name__)


class PublicationReportWorker(QObject):
    """Background worker that generates the publication report bundle."""

    progress = Signal(int)
    message = Signal(str)
    error = Signal(str)
    finished = Signal(object)

    def __init__(self, request: PublicationReportRequest) -> None:
        super().__init__()
        self.request = request
        self._cancel_requested = False

    @Slot()
    def run(self) -> None:
        try:
            if self._cancel_requested:
                self.message.emit("Cancelled.")
                self.finished.emit(None)
                return

            def _progress(value: int, message: str) -> None:
                self.progress.emit(int(value))
                self.message.emit(message)

            result = generate_publication_report(self.request, progress=_progress)
            if self._cancel_requested:
                self.message.emit("Cancel requested after report generation completed.")
            self.finished.emit(result)
        except Exception as exc:
            logger.exception(
                "publication_report_worker_failed",
                extra={
                    "project_root": str(self.request.project_root),
                    "excel_root": str(self.request.excel_root or ""),
                    "output_root": str(self.request.output_root or ""),
                },
            )
            self.error.emit(str(exc))

    @Slot()
    def cancel(self) -> None:
        self._cancel_requested = True


__all__ = ("PublicationReportWorker", "PublicationReportResult")
