"""Qt worker for project-wide FullFFT grid inspection."""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal, Slot

from Main_App.processing.full_fft_grid_qc import audit_project_full_fft_grids

logger = logging.getLogger(__name__)


class FullFftGridQcWorker(QObject):
    """Inspect workbook headers without blocking the Settings dialog."""

    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, project_root) -> None:
        super().__init__()
        self._project_root = project_root

    @Slot()
    def run(self) -> None:
        project_root = str(self._project_root or "")
        logger.info(
            "harmonic_recalculation_grid_check_started project_root=%r",
            project_root,
        )
        try:
            audit = audit_project_full_fft_grids(self._project_root)
            logger.info(
                "harmonic_recalculation_grid_check_completed project_root=%r "
                "workbooks=%d review_candidates=%d unresolved_conflict=%s "
                "reference_support=%d reference_total=%d",
                project_root,
                len(audit.observations),
                len(audit.review_candidates),
                audit.has_unresolved_grid_conflict,
                audit.reference_support,
                audit.reference_total,
            )
            self.finished.emit(audit)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "harmonic_recalculation_grid_check_failed project_root=%r error=%r",
                project_root,
                str(exc),
            )
            self.failed.emit(str(exc))


__all__ = ["FullFftGridQcWorker"]
