"""Qt worker for processing-end harmonic selection QC."""

from __future__ import annotations

import logging
from pathlib import Path

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
        previous_selection_fingerprint: str | None = None
        resolved_project_root = (
            Path(project_root).expanduser().resolve(strict=False)
            if project_root
            else None
        )
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
        report = None
        try:
            if (
                resolved_project_root is not None
                and (resolved_project_root / "project.json").is_file()
            ):
                from Main_App.processing.artifact_freshness import (
                    load_active_selection_fingerprint,
                )

                previous_selection_fingerprint = load_active_selection_fingerprint(
                    resolved_project_root
                )
            report = run_processing_harmonic_selection_qc(
                self._project,
                log_func=_record_status,
                force_recalculate=True,
            )
            downstream_result: dict[str, object] | None = None
            if (
                resolved_project_root is not None
                and (resolved_project_root / "project.json").is_file()
            ):
                from Main_App.workers.post_processing_pipeline_worker import (
                    run_postprocessing_from_selection,
                )
                _record_status(
                    "Rebuilding selection-dependent outputs without rerunning EEG preprocessing or FFT export."
                )
                downstream_result = run_postprocessing_from_selection(
                    self._project,
                    report.selection_metadata,
                    previous_selection_fingerprint=previous_selection_fingerprint,
                    progress_callback=_record_status,
                )
                if not bool(downstream_result.get("ok")):
                    failed_steps = [
                        str(step.get("name") or "post-processing")
                        for step in downstream_result.get("steps", [])
                        if isinstance(step, dict) and not step.get("ok")
                    ]
                    failed_text = ", ".join(failed_steps) or "unknown output"
                    raise RuntimeError(
                        "Harmonic selection was saved, but selection-dependent "
                        f"post-processing failed for: {failed_text}. The preceding "
                        "artifacts were retained and marked stale/failed; raw EEG "
                        "preprocessing was not rerun."
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
                    "messages": list(messages),
                    "downstream_postprocessing": downstream_result,
                    "downstream_rebuilt": downstream_result is not None,
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
            payload: dict[str, object] = {
                "ok": False,
                "error": str(exc),
                "messages": messages,
            }
            if report is not None:
                payload.update(
                    {
                        "selection_recalculated": True,
                        "workbook_path": str(report.workbook_path),
                        "selection_metadata": report.selection_metadata,
                    }
                )
            self.finished.emit(payload)


__all__ = ["ProcessingHarmonicSelectionWorker"]
