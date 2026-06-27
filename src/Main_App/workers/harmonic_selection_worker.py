"""Qt worker for processing-end harmonic selection QC."""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal, Slot

from Main_App.processing.harmonic_selection_qc import run_processing_harmonic_selection_qc

logger = logging.getLogger(__name__)


class ProcessingHarmonicSelectionWorker(QObject):
    """Run harmonic-selection QC without touching GUI widgets."""

    finished = Signal(dict)

    def __init__(self, project) -> None:
        super().__init__()
        self._project = project

    @Slot()
    def run(self) -> None:
        messages: list[str] = []
        try:
            report = run_processing_harmonic_selection_qc(
                self._project,
                log_func=messages.append,
            )
            self.finished.emit(
                {
                    "ok": True,
                    "workbook_path": str(report.workbook_path),
                    "selection_metadata": report.selection_metadata,
                    "messages": list(report.messages),
                }
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("processing_harmonic_selection_qc_failed")
            self.finished.emit(
                {
                    "ok": False,
                    "error": str(exc),
                    "messages": messages,
                }
            )


__all__ = ["ProcessingHarmonicSelectionWorker"]
