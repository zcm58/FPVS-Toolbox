"""Settings dialog helpers for managing the projects root path."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

from Main_App.Shared.settings_manager import SettingsManager


def ensure_projects_root(parent: QWidget | None) -> Path | None:
    """Ensure a valid projects root exists, prompting the user if necessary."""

    settings = SettingsManager()
    saved_root = settings.get_project_root()
    if saved_root:
        root_path = Path(saved_root)
        if root_path.is_dir():
            return root_path
    options = QFileDialog.Options()
    options |= QFileDialog.ShowDirsOnly
    options |= QFileDialog.DontResolveSymlinks
    selected = QFileDialog.getExistingDirectory(
        parent,
        "Select Projects Root",
        saved_root or "",
        options=options,
    )
    if not selected:
        return None
    root_path = Path(selected)
    settings.set_project_root(selected)
    settings.save()
    return root_path


def changeProjectsRoot(self) -> None:
    settings = getattr(self, "manager", None)
    if not isinstance(settings, SettingsManager):
        settings = SettingsManager()
    root = QFileDialog.getExistingDirectory(
        self,
        "Select Projects Root Folder",
        settings.get_project_root(),
    )
    if not root:
        return
    settings.set_project_root(root)
    settings.save()
    if hasattr(self, "projectsRoot"):
        self.projectsRoot = Path(root)
    QMessageBox.information(
        self,
        "Projects Root Updated",
        f"New Projects Root: {root}",
    )
