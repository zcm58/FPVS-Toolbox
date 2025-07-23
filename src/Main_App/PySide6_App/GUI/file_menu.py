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
    file_menu.addAction(action_new)

    action_open = QAction("Open Existing Project…", self)
    action_open.triggered.connect(self.open_existing_project)
    file_menu.addAction(action_open)
    file_menu.addSeparator()

    action_settings = QAction("Settings", self)
    action_settings.triggered.connect(self.open_settings_window)
    file_menu.addAction(action_settings)

    action_check = QAction("Check for Updates", self)
    action_check.triggered.connect(self.check_for_updates)
    file_menu.addAction(action_check)

    action_save = QAction("Save Project Settings", self)
    action_save.triggered.connect(self.saveProjectSettings)
    self.exit_action = QAction("Exit", self)
    self.exit_action.triggered.connect(self.quit)

    file_menu.addAction(action_save)
    file_menu.addAction(self.exit_action)
