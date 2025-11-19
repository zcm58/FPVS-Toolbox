"""Project management utilities extracted from main_window.py."""
from __future__ import annotations

import logging
from pathlib import Path
import sys

from PySide6.QtWidgets import QFileDialog, QMessageBox, QInputDialog, QWidget

from .project import Project
from Main_App.PySide6_App.config.projects_root import ensure_projects_root
from Main_App.PySide6_App.utils.op_guard import OpGuard
from Main_App.PySide6_App.utils.settings import get_app_settings

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

_open_project_guard = OpGuard()


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
    if not _open_project_guard.start():
        return

    try:
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
            return

        self.projectsRoot = root

        try:
            entries = list(root.iterdir())
        except (FileNotFoundError, PermissionError, OSError) as exc:
            logger.error(
                "Unable to enumerate projects under %s: %s",
                root,
                exc,
                exc_info=exc,
                extra={"op": "open_existing_project", "path": str(root)},
            )
            QMessageBox.critical(
                parent,
                "Projects Root Unavailable",
                f"Unable to access projects root:\n{root}\n{exc}",
            )
            return

        candidates = [d for d in entries if (d / "project.json").exists()]
        if not candidates:
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
            return

        labels: list[str] = []
        label_to_path: dict[str, Path] = {}
        for candidate in candidates:
            try:
                project = Project.load(candidate)
            except Exception as exc:
                logger.error(
                    "Failed to load project at %s: %s",
                    candidate,
                    exc,
                    exc_info=exc,
                    extra={"op": "open_existing_project", "path": str(candidate)},
                )
                continue
            label = project.name
            labels.append(label)
            label_to_path[label] = candidate

        if not labels:
            QMessageBox.warning(
                parent,
                "Projects Unavailable",
                "No valid projects could be loaded.",
            )
            return

        choice, ok = QInputDialog.getItem(
            parent,
            "Open Existing Project",
            "Select a project:",
            labels,
            0,
            editable=False,
        )
        if not ok or choice not in label_to_path:
            logger.info(
                "Project selection cancelled.",
                extra={"op": "open_existing_project", "path": str(root)},
            )
            return

        project = Project.load(label_to_path[choice])
        self.currentProject = project
        self.loadProject(project)
    finally:
        _open_project_guard.end()



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
    self.cb_loreta.setChecked(bool(project.options.get("run_loreta", False)))

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
