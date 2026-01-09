"""Project management utilities extracted from main_window.py."""
from __future__ import annotations

import logging
from pathlib import Path
import sys

from PySide6.QtCore import QObject, QRunnable, Qt, QThread, QThreadPool, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMessageBox,
    QInputDialog,
    QProgressDialog,
    QWidget,
)

from .project import Project
from .project_metadata import ProjectMetadata, read_project_metadata
from Main_App.PySide6_App.config.projects_root import ensure_projects_root
from Main_App.PySide6_App.utils.op_guard import OpGuard
from Main_App.PySide6_App.utils.settings import get_app_settings

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

_open_project_guard = OpGuard()
_open_selected_project_guard = OpGuard()


class _ProjectScanSignals(QObject):
    error = Signal(str)
    finished = Signal(object)
    progress = Signal(int)


CANCEL_SCAN_MESSAGE = "Project scan cancelled."


class _ProjectScanJob(QRunnable):
    def __init__(self, root: Path) -> None:
        super().__init__()
        self.root = root
        self.signals = _ProjectScanSignals()
        self._cancel_requested = False

    def request_cancel(self) -> None:
        self._cancel_requested = True

    def run(self) -> None:
        try:
            entries = list(self.root.iterdir())
        except (FileNotFoundError, PermissionError, OSError) as exc:
            self.signals.error.emit(str(exc))
            return

        metadata: list[ProjectMetadata] = []
        total = len(entries)
        for idx, entry in enumerate(entries, start=1):
            if self._cancel_requested:
                self.signals.error.emit(CANCEL_SCAN_MESSAGE)
                return
            self.signals.progress.emit(int(idx / total * 100) if total else 100)
            if not entry.is_dir():
                continue
            manifest_path = entry / "project.json"
            if not manifest_path.exists():
                continue
            try:
                metadata.append(read_project_metadata(entry))
            except Exception as exc:
                logger.error(
                    "Failed to read project metadata at %s: %s",
                    entry,
                    exc,
                    exc_info=exc,
                    extra={"op": "open_existing_project", "path": str(entry)},
                )
                continue

        if self._cancel_requested:
            self.signals.error.emit(CANCEL_SCAN_MESSAGE)
            return
        self.signals.finished.emit(metadata)


def select_projects_root(self) -> None:
    settings = get_app_settings()
    settings.beginGroup("paths")
    saved_root = settings.value("projectsRoot", "", type=str)
    settings.endGroup()

    if saved_root and Path(saved_root).is_dir():
        self.projectsRoot = Path(saved_root)
    else:
        root = QFileDialog.getExistingDirectory(
            self, "Select Projects Root Folder", ""
        )
        if not root:
            QMessageBox.critical(
                self,
                "Projects Root Required",
                "You must select a Projects Root folder to continue.",
            )
            sys.exit(1)
        self.projectsRoot = Path(root)
        settings.beginGroup("paths")
        settings.setValue("projectsRoot", str(self.projectsRoot))
        settings.endGroup()
        settings.sync()


def new_project(self) -> None:
    name, ok = QInputDialog.getText(
        self, "Project Name", "Enter a name for this new project:"
    )
    if not ok or not name.strip():
        return

    group_count, ok = QInputDialog.getInt(
        self,
        "Experimental Groups",
        "How many experimental groups does this project have?",
        1,
        1,
        20,
        1,
    )
    if not ok:
        return

    group_names: list[str] = []
    for idx in range(group_count):
        while True:
            default_name = f"Group {idx + 1}" if group_count > 1 else "Default"
            group_name, ok = QInputDialog.getText(
                self,
                "Group Name",
                f"Enter a name for group #{idx + 1}:",
                text=default_name,
            )
            if not ok:
                QMessageBox.information(
                    self,
                    "Project Creation Cancelled",
                    "Project creation cancelled.",
                )
                return
            group_name = group_name.strip()
            if not group_name:
                QMessageBox.warning(
                    self,
                    "Group Name Required",
                    "Group names cannot be empty.",
                )
                continue
            if group_name.lower() in {existing.lower() for existing in group_names}:
                QMessageBox.warning(
                    self,
                    "Duplicate Group",
                    "Each group must have a unique name.",
                )
                continue
            group_names.append(group_name)
            break

    group_folders: dict[str, str] = {}
    for group_name in group_names:
        folder = QFileDialog.getExistingDirectory(
            self,
            f"Select Input Folder for {group_name}",
            "",
        )
        if not folder:
            QMessageBox.information(
                self,
                "Project Creation Cancelled",
                "Project creation cancelled.",
            )
            return
        group_folders[group_name] = folder

    project_dir = self.projectsRoot / name.strip()
    project_dir.mkdir(parents=True, exist_ok=True)

    project = Project.load(project_dir)
    project.name = name.strip()
    if group_names:
        first_group = group_names[0]
        project.input_folder = group_folders[first_group]
    groups_payload = {
        group_name: {"raw_input_folder": Path(folder), "description": ""}
        for group_name, folder in group_folders.items()
    }
    project.groups = groups_payload
    project.participants = {}
    project.save()

    self.currentProject = project
    self.loadProject(project)


def open_existing_project(self, parent: QWidget | None = None) -> None:
    if _open_selected_project_guard.is_active():
        logger.info(
            "Open existing project skipped because another open is active.",
            extra={"op": "open_existing_project", "path": None},
        )
        return
    if not _open_project_guard.start():
        return

    # Derive a parent if not provided to keep backward compatibility with older callers
    if parent is None:
        parent = getattr(self, "window", lambda: None)() or getattr(self, "parent", lambda: None)() or None

    root = ensure_projects_root(parent)
    if root is None:
        QMessageBox.information(parent, "Projects Root", "Project root not set.")
        logger.warning(
            "Projects root missing.",
            extra={"op": "open_existing_project", "path": None},
        )
        _open_project_guard.end()
        return

    self.projectsRoot = root

    progress = QProgressDialog("Scanning projects...", "Cancel", 0, 100, parent)
    progress.setWindowTitle("Scanning Projects")
    progress.setWindowModality(Qt.WindowModal)
    progress.setAutoClose(False)
    progress.setAutoReset(False)
    progress.setMinimumDuration(0)
    progress.show()

    cleaned = False

    def log_thread_context(label: str) -> None:
        app = QApplication.instance()
        gui_thread = app.thread() if app else None
        current = QThread.currentThread()
        logger.debug(
            "%s thread=%s gui_thread=%s is_gui=%s",
            label,
            current,
            gui_thread,
            current == gui_thread if gui_thread else False,
            extra={"op": "open_existing_project", "path": str(root)},
        )

    def finalize_guard() -> None:
        nonlocal cleaned
        if cleaned:
            return
        cleaned = True
        progress.close()
        progress.deleteLater()
        self._active_scan_job = None
        _open_project_guard.end()

    def handle_error(message: str) -> None:
        log_thread_context("handle_error")
        if message == CANCEL_SCAN_MESSAGE:
            logger.info(
                "Project scan cancelled for %s.",
                root,
                extra={"op": "open_existing_project", "path": str(root)},
            )
            finalize_guard()
            return
        logger.info(
            "Project scan error for %s: %s",
            root,
            message,
            extra={"op": "open_existing_project", "path": str(root)},
        )
        logger.error(
            "Unable to enumerate projects under %s: %s",
            root,
            message,
            extra={"op": "open_existing_project", "path": str(root)},
        )
        QMessageBox.critical(
            parent,
            "Projects Root Unavailable",
            f"Unable to access projects root:\n{root}\n{message}",
        )
        finalize_guard()

    def handle_finished(metadata: list[ProjectMetadata]) -> None:
        log_thread_context("handle_finished")
        if __debug__:
            app = QApplication.instance()
            assert app is not None
            assert QThread.currentThread() == app.thread()
        logger.info(
            "Project scan finished for %s with %s projects.",
            root,
            len(metadata),
            extra={"op": "open_existing_project", "path": str(root)},
        )
        if not metadata:
            QMessageBox.information(
                parent,
                "No Projects Found",
                f"No projects found under {root}.",
            )
            logger.info(
                "No projects discovered under %s.",
                root,
                extra={"op": "open_existing_project", "path": str(root)},
            )
            finalize_guard()
            return

        labels: list[str] = []
        label_to_metadata: dict[str, ProjectMetadata] = {}
        for entry in metadata:
            label = entry.name
            labels.append(label)
            label_to_metadata[label] = entry

        if not labels:
            QMessageBox.warning(
                parent,
                "Projects Unavailable",
                "No valid projects could be loaded.",
            )
            finalize_guard()
            return

        choice, ok = QInputDialog.getItem(
            parent,
            "Open Existing Project",
            "Select a project:",
            labels,
            0,
            editable=False,
        )
        if not ok or choice not in label_to_metadata:
            logger.info(
                "Project selection cancelled.",
                extra={"op": "open_existing_project", "path": str(root)},
            )
            finalize_guard()
            return

        selected = label_to_metadata[choice]
        finalize_guard()

        _set_open_existing_action_enabled(self, False)
        logger.info(
            "Project selection confirmed: %s",
            selected.project_root,
            extra={"op": "open_existing_project", "path": str(root)},
        )
        QTimer.singleShot(
            0,
            lambda: _open_selected_project(self, selected, parent, root),
        )

    job = _ProjectScanJob(root)
    job.setAutoDelete(False)
    self._active_scan_job = job
    logger.info(
        "Starting project scan under %s.",
        root,
        extra={"op": "open_existing_project", "path": str(root)},
    )
    job.signals.error.connect(handle_error, Qt.QueuedConnection)
    job.signals.finished.connect(handle_finished, Qt.QueuedConnection)

    def handle_progress(value: int) -> None:
        log_thread_context("handle_progress")
        progress.setValue(value)

    job.signals.progress.connect(handle_progress, Qt.QueuedConnection)
    progress.canceled.connect(job.request_cancel)
    QThreadPool.globalInstance().start(job)


def _set_open_existing_action_enabled(self, enabled: bool) -> None:
    action = getattr(self, "actionOpenExistingProject", None)
    if action is not None:
        action.setEnabled(enabled)


def _open_selected_project(
    self,
    selected: ProjectMetadata,
    parent: QWidget | None,
    root: Path,
) -> None:
    if __debug__:
        app = QApplication.instance()
        assert app is not None
        assert QThread.currentThread() == app.thread()
    if not _open_selected_project_guard.start():
        logger.info(
            "Open project request skipped because another open is active.",
            extra={"op": "open_existing_project", "path": str(root)},
        )
        _set_open_existing_action_enabled(self, True)
        return
    logger.info(
        "Opening project from selection: %s",
        selected.project_root,
        extra={"op": "open_existing_project", "path": str(root)},
    )
    try:
        project = Project.load(
            selected.project_root,
            manifest=selected.manifest,
            manifest_path=selected.manifest_path,
        )
        self.currentProject = project
        self.loadProject(project)
        if hasattr(self, "_on_project_ready"):
            self._on_project_ready()
        logger.info(
            "Project opened successfully: %s",
            selected.project_root,
            extra={"op": "open_existing_project", "path": str(root)},
        )
    except Exception as exc:
        logger.error(
            "Failed to open project at %s: %s",
            selected.project_root,
            exc,
            exc_info=exc,
            extra={"op": "open_existing_project", "path": str(root)},
        )
        raise
    finally:
        _open_selected_project_guard.end()
        _set_open_existing_action_enabled(self, True)


def openProjectPath(self, folder: str) -> None:
    project = Project.load(folder)
    self.currentProject = project
    self.loadProject(project)

    settings = get_app_settings()
    recent = settings.value("recentProjects", [], type=list)
    if folder in recent:
        recent.remove(folder)
    recent.insert(0, folder)
    settings.setValue("recentProjects", recent)
    settings.sync()


def loadProject(self, project: Project) -> None:
    self.currentProject = project
    self.lbl_currentProject.setText(f"Current Project: {project.name}")

    self.settings.set("paths", "data_folder", str(project.input_folder))
    self.settings.save()

    mode = project.options.get("mode", "batch").lower()
    self.rb_single.setChecked(mode == "single")
    self.rb_batch.setChecked(mode == "batch")

    for row in list(self.event_rows):
        row.setParent(None)
    self.event_rows.clear()

    if project.event_map:
        for label, ident in project.event_map.items():
            self.add_event_row(str(label), str(ident))
    else:
        self.add_event_row()

    self.log(f"Loaded project: {project.name}")


def edit_project_settings(self) -> None:
    if not getattr(self, "currentProject", None):
        QMessageBox.warning(self, "No Project", "Please open or create a project first.")
        return
    folder = QFileDialog.getExistingDirectory(
        self, "Select Input Folder", str(self.currentProject.input_folder)
    )
    if not folder:
        return
    self.currentProject.input_folder = folder
    self.currentProject.save()
    self.loadProject(self.currentProject)
