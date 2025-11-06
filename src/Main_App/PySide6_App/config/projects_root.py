"""Settings dialog helpers for managing the projects root path."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

from Main_App.PySide6_App.utils.settings import get_app_settings


def ensure_projects_root(parent: QWidget | None) -> Path | None:
    """Ensure a valid projects root exists, prompting the user if necessary."""

    settings = get_app_settings()
    saved_root = settings.value("paths/projectsRoot", "", type=str)
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
    settings.setValue("paths/projectsRoot", selected)
    settings.sync()
    return root_path


def changeProjectsRoot(self) -> None:
    settings = get_app_settings()
    root = QFileDialog.getExistingDirectory(
        self,
        "Select Projects Root Folder",
        settings.value("paths/projectsRoot", ""),
    )
    if not root:
        return
    settings.setValue("paths/projectsRoot", root)
    settings.sync()
    QMessageBox.information(
        self,
        "Projects Root Updated",
        f"New Projects Root: {root}",
    )
