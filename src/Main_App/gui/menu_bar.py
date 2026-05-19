from __future__ import annotations
from PySide6.QtWidgets import QMenuBar, QMainWindow
from PySide6.QtGui import QAction


def build_menu_bar(parent: QMainWindow) -> QMenuBar:
    """
    Returns a QMenuBar with app-level File and Help menus.
    """
    menu_bar = QMenuBar(parent)

    # File
    file_menu = menu_bar.addMenu("File")
    file_menu.setObjectName("fileMenu")
    for text, slot in [
        ("Settings",         parent.open_settings_window),
        ("Check for Updates", parent.check_for_updates),
        ("Exit",              parent.quit),
    ]:
        action = QAction(text, parent)
        action.triggered.connect(slot)
        file_menu.addAction(action)
        file_menu.addSeparator()
    file_menu.removeAction(file_menu.actions()[-1])  # drop trailing separator

    # Help
    help_menu = menu_bar.addMenu("Help")
    for text, slot in [
        ("About…",                parent.show_about_dialog),
    ]:
        action = QAction(text, parent)
        action.triggered.connect(slot)
        help_menu.addAction(action)
        help_menu.addSeparator()
    help_menu.removeAction(help_menu.actions()[-1])

    return menu_bar
