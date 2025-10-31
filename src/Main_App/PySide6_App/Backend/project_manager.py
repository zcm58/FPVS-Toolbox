"""Project management utilities extracted from main_window.py."""
from __future__ import annotations

from pathlib import Path
import sys

from PySide6.QtWidgets import QFileDialog, QMessageBox, QInputDialog

from .project import Project
from Main_App.PySide6_App.utils.settings import get_app_settings


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

    input_folder = QFileDialog.getExistingDirectory(
        self, "Select Input Folder (BDF files)", ""
    )
    if not input_folder:
        return

    project_dir = self.projectsRoot / name.strip()
    project_dir.mkdir(parents=True, exist_ok=True)

    project = Project.load(project_dir)
    project.name = name.strip()
    project.input_folder = input_folder
    project.save()

    self.currentProject = project
    self.loadProject(project)


def open_existing_project(self) -> None:
    candidates = [d for d in self.projectsRoot.iterdir() if (d / "project.json").exists()]
    if not candidates:
        QMessageBox.information(
            self, "No Projects", "No projects found under your Projects Root."
        )
        return

    labels = []
    label_to_path = {}
    for d in candidates:
        proj = Project.load(d)
        label = proj.name
        labels.append(label)
        label_to_path[label] = d

    choice, ok = QInputDialog.getItem(
        self, "Open Project", "Select a project:", labels, editable=False
    )
    if not ok or choice not in label_to_path:
        return

    project = Project.load(label_to_path[choice])
    self.currentProject = project
    self.loadProject(project)


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
