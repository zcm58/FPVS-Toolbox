"""File menu setup extracted from main_window.py."""
from __future__ import annotations

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu


def init_file_menu(self) -> None:
    """Configure the File menu with project actions."""
    menu_bar = self.menuBar()
    if not menu_bar:
        return

    file_menu = menu_bar.findChild(QMenu, "fileMenu")
    if file_menu is None:
        return

    file_menu.clear()

    action_new = QAction("New Project…", self)
    action_new.triggered.connect(self.new_project)
    self.actionCreateNewProject = action_new
    self.actionImportFpvsConfigProject = action_new
    file_menu.addAction(action_new)

    action_open = QAction("Open Existing Project…", self)
    action_open.triggered.connect(self.open_existing_project)
    self.actionOpenExistingProject = action_open
    file_menu.addAction(action_open)

    action_save = QAction("Save Project Settings", self)
    action_save.triggered.connect(self.saveProjectSettings)
    file_menu.addAction(action_save)

    action_reset_cache = QAction("Reset Project Processing Cache...", self)
    action_reset_cache.setObjectName("actionResetProjectProcessingCache")
    action_reset_cache.setStatusTip(
        "Remove only FPVS-managed cache state so the next processing run starts cold"
    )
    action_reset_cache.triggered.connect(self.reset_project_processing_cache)
    self.actionResetProjectProcessingCache = action_reset_cache
    file_menu.addAction(action_reset_cache)

    action_settings = QAction("Settings", self)
    action_settings.triggered.connect(self.open_settings_window)
    file_menu.addAction(action_settings)

    action_check = QAction("Check for Updates", self)
    action_check.triggered.connect(self.check_for_updates)
    file_menu.addAction(action_check)

    self.exit_action = QAction("Exit", self)
    self.exit_action.triggered.connect(self.quit)
    file_menu.addAction(self.exit_action)
