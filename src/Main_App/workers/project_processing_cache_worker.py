"""Qt worker for non-blocking active-project processing-cache resets."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from Main_App.processing.project_processing_cache import (
    clear_project_processing_cache,
)

logger = logging.getLogger(__name__)


class ProjectProcessingCacheResetWorker(QObject):
    """Clear one project's FPVS-managed processing cache off the GUI thread."""

    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, project_root: Path) -> None:
        super().__init__()
        self._project_root = Path(project_root)

    @Slot()
    def run(self) -> None:
        try:
            usage = clear_project_processing_cache(self._project_root)
        except Exception as exc:  # noqa: BLE001 - never strand the owning QThread
            logger.exception(
                "project_processing_cache_worker_failed root=%s",
                self._project_root,
            )
            self.failed.emit(str(exc))
            return
        self.finished.emit(usage)


__all__ = ["ProjectProcessingCacheResetWorker"]
