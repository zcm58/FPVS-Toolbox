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
        project_root = str(getattr(self._project, "project_root", "") or "")

        def _record_status(message: str) -> None:
            text = str(message).strip()
            if not text:
                return
            messages.append(text)
            logger.info(
                "harmonic_recalculation_progress project_root=%r message=%r",
                project_root,
                text,
            )

        logger.info(
            "harmonic_recalculation_started project_root=%r force_recalculate=true",
            project_root,
        )
        try:
            report = run_processing_harmonic_selection_qc(
                self._project,
                log_func=_record_status,
                force_recalculate=True,
            )
            selected_harmonics = report.selection_metadata.get(
                "selected_harmonics_hz",
                (),
            )
            logger.info(
                "harmonic_recalculation_completed project_root=%r "
                "workbook_path=%r selected_harmonics=%r status_messages=%d",
                project_root,
                str(report.workbook_path),
                selected_harmonics,
                len(messages),
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
            logger.exception(
                "harmonic_recalculation_failed project_root=%r "
                "status_messages=%d error=%r",
                project_root,
                len(messages),
                str(exc),
            )
            self.finished.emit(
                {
                    "ok": False,
                    "error": str(exc),
                    "messages": messages,
                }
            )


__all__ = ["ProcessingHarmonicSelectionWorker"]
