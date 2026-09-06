"""Background inventory and removal of explicitly managed Toolbox caches."""

from __future__ import annotations

import logging
from pathlib import Path
from threading import Event

from PySide6.QtCore import QObject, Signal, Slot

from Main_App.processing.toolbox_cache import (
    clear_toolbox_caches,
    inspect_toolbox_caches,
)

logger = logging.getLogger(__name__)


class ToolboxCacheWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)
    done = Signal()

    def __init__(
        self, *, active_project_root: Path | None = None,
        projects_root: Path | None = None, inventory=None,
    ) -> None:
        super().__init__()
        self.active_project_root = active_project_root
        self.projects_root = projects_root
        self.inventory = inventory
        self.cancel_requested = Event()

    @Slot()
    def run(self) -> None:
        try:
            if self.inventory is None:
                result = inspect_toolbox_caches(
                    active_project_root=self.active_project_root,
                    projects_root=self.projects_root,
                    should_cancel=self.cancel_requested.is_set,
                )
            else:
                result = clear_toolbox_caches(
                    self.inventory, should_cancel=self.cancel_requested.is_set,
                )
            self.finished.emit(result)
        except Exception as exc:  # noqa: BLE001 - always release the owning thread
            logger.exception("toolbox_cache_operation_failed")
            self.failed.emit(str(exc))
        finally:
            self.done.emit()
