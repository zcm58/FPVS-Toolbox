"""Background loading and saving for the dataset exclusions manager."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QThread, Signal, Slot

from Main_App.processing.dataset_exclusions import (
    DatasetExclusionsSnapshot,
    load_dataset_exclusions,
    save_dataset_exclusions,
)


logger = logging.getLogger(__name__)
_RUNNING_WORKERS: set[DatasetExclusionsWorker] = set()


class DatasetExclusionsWorker(QThread):
    """Keep project I/O off the GUI thread and outlive a deleted receiver."""

    result_ready = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        project_root: Path,
        *,
        snapshot: DatasetExclusionsSnapshot | None = None,
        changes: dict[str, str] | None = None,
        reasons: dict[str, str] | None = None,
    ) -> None:
        super().__init__()
        self.project_root = project_root
        self.snapshot = snapshot
        self.changes = dict(changes or {})
        self.reasons = dict(reasons or {})
        self.finished.connect(self._release)

    def start(self) -> None:
        _RUNNING_WORKERS.add(self)
        try:
            super().start()
        except RuntimeError:
            _RUNNING_WORKERS.discard(self)
            raise

    def run(self) -> None:
        try:
            if self.snapshot is None:
                result = load_dataset_exclusions(self.project_root)
            else:
                result = save_dataset_exclusions(
                    self.project_root, self.snapshot, self.changes, reasons=self.reasons,
                )
            self.result_ready.emit(result)
        except Exception as exc:
            logger.exception("Dataset exclusions operation failed")
            self.failed.emit(str(exc))

    @Slot()
    def _release(self) -> None:
        _RUNNING_WORKERS.discard(self)
        self.deleteLater()
