"""Settings dialog helpers for managing the projects root path."""
from __future__ import annotations

from PySide6.QtWidgets import QFileDialog, QMessageBox

from Main_App.PySide6_App.utils.settings import get_app_settings


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
