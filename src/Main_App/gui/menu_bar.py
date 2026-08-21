from __future__ import annotations

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenuBar, QMainWindow


def build_menu_bar(parent: QMainWindow) -> QMenuBar:
    """
    Returns a QMenuBar with app-level File and Help menus.
    """
    menu_bar = QMenuBar(parent)

    file_menu = menu_bar.addMenu("File")
    file_menu.setObjectName("fileMenu")

    help_menu = menu_bar.addMenu("Help")
    about_action = QAction("About…", parent)
    about_action.triggered.connect(parent.show_about_dialog)
    help_menu.addAction(about_action)

    return menu_bar
