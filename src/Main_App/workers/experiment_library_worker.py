"""Worker boundaries for public dataset discovery and verified installation."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from threading import Event

from PySide6.QtCore import QObject, Signal, Slot

from Main_App.projects.experiment_library import (
    LibraryCancelled, LibraryError, PublicDataset, install_public_dataset,
    installed_dataset_path, list_installed_datasets, list_public_datasets,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CatalogSnapshot:
    items: tuple[PublicDataset, ...]
    installed: dict[tuple[str, str], Path]
    notice: str = ""


class ExperimentCatalogWorker(QObject):
    result = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, projects_root: Path) -> None:
        super().__init__()
        self.projects_root = projects_root

    @Slot()
    def run(self) -> None:
        try:
            notices = []
            try:
                local = list_installed_datasets(self.projects_root)
            except LibraryError as exc:
                local = ()
                notices.append(f"Installed project needs attention. {exc}")
            try:
                public = list_public_datasets()
            except LibraryError as exc:
                if not local:
                    raise
                public = ()
                notices.append(f"Public catalog unavailable. Showing installed datasets. {exc}")
            by_identity = {(item.item_id, item.version): item for item in local}
            by_identity.update({(item.item_id, item.version): item for item in public})
            items = tuple(by_identity.values())
            installed = {}
            for item in items:
                try:
                    path = installed_dataset_path(item, self.projects_root)
                except LibraryError as exc:
                    notices.append(f"{item.title} could not be reopened. {exc}")
                    continue
                if path is not None:
                    installed[(item.item_id, item.version)] = path
            self.result.emit(CatalogSnapshot(items, installed, " ".join(notices)))
        except Exception as exc:  # noqa: BLE001 - report failure and always end the QThread
            logger.exception("experiment_library_catalog_failed")
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()


class ExperimentInstallWorker(QObject):
    result = Signal(object)
    failed = Signal(str)
    canceled = Signal()
    phase = Signal(str)
    progress = Signal(object, object)
    finished = Signal()

    def __init__(self, item: PublicDataset, projects_root: Path, cancel_event: Event) -> None:
        super().__init__()
        self.item = item
        self.projects_root = projects_root
        self.cancel_event = cancel_event

    @Slot()
    def run(self) -> None:
        try:
            path = install_public_dataset(
                self.item, self.projects_root,
                progress_callback=self.progress.emit,
                phase_callback=self.phase.emit,
                cancel_event=self.cancel_event,
            )
            self.result.emit(path)
        except LibraryCancelled:
            self.canceled.emit()
        except Exception as exc:  # noqa: BLE001 - report failure and always end the QThread
            logger.exception("experiment_library_install_failed item=%s", self.item.item_id)
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()
