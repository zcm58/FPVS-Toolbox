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
        try:
            self.finished.emit(audit_project_full_fft_grids(self._project_root))
        except Exception as exc:  # noqa: BLE001
            logger.exception("full_fft_grid_qc_failed")
            self.failed.emit(str(exc))


__all__ = ["FullFftGridQcWorker"]
