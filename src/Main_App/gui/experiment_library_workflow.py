"""Public Library lifecycle and normal Toolbox project-opening handoff."""

from __future__ import annotations

from pathlib import Path
from threading import Event

from PySide6.QtCore import QObject, QThread, Slot

from Main_App.gui.experiment_library_page import ExperimentLibraryPage
from Main_App.gui import project_workflows
from Main_App.projects.experiment_library import PublicDataset
from Main_App.projects.projects_root import ensure_projects_root
from Main_App.workers.experiment_library_worker import (
    CatalogSnapshot, ExperimentCatalogWorker, ExperimentInstallWorker,
)


class ExperimentLibraryController(QObject):
    def __init__(self, host) -> None:
        super().__init__(host)
        self.host = host
        self.page = ExperimentLibraryPage(host.stacked)
        host._experiment_library_page = self.page
        host.stacked.addWidget(self.page)
        self.page.primary_requested.connect(self._primary)
        self.page.cancel_requested.connect(self._cancel)
        self.page.selection_changed.connect(self._selected)
        self.thread: QThread | None = None
        self.worker = None
        self._cancel_event = Event()
        self._installed: dict[tuple[str, str], Path] = {}
        self._catalog_notice = ""
        self._catalog_failed = True
        self._result = None
        self._failure: str | None = None
        self._canceled = False
        self._install_item: PublicDataset | None = None

    def show(self) -> None:
        self.host.stacked.setCurrentWidget(self.page)
        if self.thread is None:
            self.refresh()

    def _projects_root(self) -> Path | None:
        root = ensure_projects_root(self.host)
        if root is not None:
            self.host.projectsRoot = root
        return root

    def refresh(self) -> None:
        self._catalog_failed = True
        root = self._projects_root()
        if root is None:
            self.page.show_status("Choose a projects folder", "Try again to select where Toolbox projects are stored.")
            self.page.primary_button.setText("Choose folder")
            return
        self._install_item = None
        self.page.show_status("Loading public datasets…", busy=True)
        self._start_worker(ExperimentCatalogWorker(root))

    def _start_worker(self, worker) -> None:
        self._result = None
        self._failure = None
        self._canceled = False
        self.thread = QThread(self)
        self.worker = worker
        worker.moveToThread(self.thread)
        self.thread.started.connect(worker.run)
        worker.result.connect(self._receive_result)
        worker.failed.connect(self._receive_failure)
        if isinstance(worker, ExperimentInstallWorker):
            worker.phase.connect(self._phase)
            worker.progress.connect(self.page.show_download_progress)
            worker.canceled.connect(self._receive_canceled)
        worker.finished.connect(self.thread.quit)
        worker.finished.connect(worker.deleteLater)
        self.thread.finished.connect(self._thread_finished)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

    @Slot(object)
    def _receive_result(self, result) -> None:
        self._result = result

    @Slot(str)
    def _receive_failure(self, message: str) -> None:
        self._failure = message

    @Slot()
    def _receive_canceled(self) -> None:
        self._canceled = True

    @Slot()
    def _thread_finished(self) -> None:
        self.thread = None
        self.worker = None
        if self._failure is not None:
            title = "Download could not finish" if self._install_item else "Public catalog unavailable"
            self.page.show_status(title, self._failure)
            self.page.primary_button.setText("Try again")
            return
        if self._canceled:
            self._selected(self.page.selected_dataset)
            self.page.operation_detail.setText("Download canceled. You can try again.")
            return
        if isinstance(self._result, CatalogSnapshot):
            self._catalog_failed = False
            self._installed = self._result.installed
            self._catalog_notice = self._result.notice
            self.page.set_datasets(self._result.items)
            return
        if isinstance(self._result, Path) and self._install_item is not None:
            item = self._install_item
            self._installed[(item.item_id, item.version)] = self._result
            self._selected(item)
            if not self._cancel_event.is_set():
                self._open(self._result)

    @Slot(object)
    def _selected(self, item: PublicDataset | None) -> None:
        if item is None:
            return
        path = self._installed.get((item.item_id, item.version))
        if path is None:
            title = "Download from OpenFPVS"
            detail = f"{item.size_bytes / 1_000_000:.1f} MB download"
            action = "Download and open"
        else:
            title, detail, action = "Installed", "Ready to open on this computer.", "Open project"
        self.page.show_status(title, self._catalog_notice or detail)
        self.page.primary_button.setText(action)

    @Slot()
    def _primary(self) -> None:
        if self.thread is not None:
            return
        item = self.page.selected_dataset
        if item is None or self._catalog_failed:
            self.refresh()
            return
        path = self._installed.get((item.item_id, item.version))
        if path is not None:
            self._open(path)
            return
        root = self._projects_root()
        if root is None:
            return
        self._cancel_event = Event()
        self._install_item = item
        self._phase("download")
        self._start_worker(ExperimentInstallWorker(item, root, self._cancel_event))

    @Slot(str)
    def _phase(self, phase: str) -> None:
        if self._cancel_event.is_set():
            self.page.show_canceling()
            return
        titles = {
            "download": ("Downloading dataset…", "From OpenFPVS"),
            "verify": ("Verifying experiment files…", "Checking the archive and file checksums."),
            "setup": ("Setting up project…", "Preparing participants, conditions, and processing settings."),
        }
        title, detail = titles[phase]
        self.page.show_status(title, detail, busy=True, cancelable=True)

    @Slot()
    def _cancel(self) -> None:
        self._cancel_event.set()
        self.page.show_canceling()

    def _open(self, path: Path) -> None:
        guard = getattr(self.host, "_start_guard", None)
        if getattr(self.host, "_run_active", False) or (guard is not None and guard.is_active()):
            self.page.show_status("Project ready", "Finish the current operation, then open this project.")
            self.page.primary_button.setText("Open project")
            return
        project_workflows.open_project_path(self.host, str(path))


def show_experiment_library(host) -> None:
    controller = getattr(host, "_experiment_library_controller", None)
    if controller is None:
        controller = ExperimentLibraryController(host)
        host._experiment_library_controller = controller
    controller.show()
