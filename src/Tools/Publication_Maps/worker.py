"""Qt worker for publication scalp-map generation."""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal, Slot

from Tools.Publication_Maps.metrics import build_publication_map_result
from Tools.Publication_Maps.models import PublicationMapRequest, PublicationMapResult
from Tools.Publication_Maps.rendering import export_source_workbook, render_publication_figures

logger = logging.getLogger(__name__)


class PublicationMapsWorker(QObject):
    """Background worker that reads workbooks, exports data, and renders maps."""

    progress = Signal(int)
    message = Signal(str)
    error = Signal(str)
    finished = Signal(object)

    def __init__(self, request: PublicationMapRequest) -> None:
        super().__init__()
        self.request = request
        self._cancel_requested = False

    @Slot()
    def run(self) -> None:
        try:
            self.progress.emit(5)
            self.message.emit("Reading workbooks...")
            result = build_publication_map_result(self.request)
            if self._cancel_requested:
                self.message.emit("Cancelled.")
                self.finished.emit(result)
                return
            self.progress.emit(55)
            self.message.emit("Writing source-data workbook...")
            export_source_workbook(result, self.request)
            self.progress.emit(70)
            self.message.emit("Rendering scalp maps...")
            render_publication_figures(result, self.request)
            self.progress.emit(100)
            self.message.emit("Complete.")
            self.finished.emit(result)
        except Exception as exc:
            logger.exception(
                "publication_maps_worker_failed",
                extra={
                    "input_root": str(self.request.input_root),
                    "output_root": str(self.request.output_root),
                },
            )
            self.error.emit(str(exc))

    @Slot()
    def cancel(self) -> None:
        self._cancel_requested = True


__all__ = ("PublicationMapsWorker", "PublicationMapResult")
