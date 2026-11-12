from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMenuBar, QMainWindow

from Main_App.gui.shell_actions import ShellActions
from Main_App.gui.theme import apply_native_menu_appearance


def build_menu_bar(parent: QMainWindow, actions: ShellActions) -> QMenuBar:
    """Return the app-level File, View and Tools menus."""
    menu_bar = QMenuBar(parent)
    menu_bar.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    apply_native_menu_appearance(menu_bar)

    file_menu = menu_bar.addMenu("File")
    file_menu.setObjectName("fileMenu")
    apply_native_menu_appearance(file_menu)

    view_menu = menu_bar.addMenu("View")
    view_menu.setObjectName("viewMenu")
    apply_native_menu_appearance(view_menu)
    view_menu.addAction(actions.home)

    tools_menu = menu_bar.addMenu("Tools")
    tools_menu.setObjectName("toolsMenu")
    apply_native_menu_appearance(tools_menu)
    tools_menu.addActions(actions.default_tools)

    if actions.beta_tools:
        tools_menu.addSeparator()
        beta_menu = tools_menu.addMenu("Beta Tools")
        beta_menu.setObjectName("betaToolsMenu")
        apply_native_menu_appearance(beta_menu)
        beta_menu.addActions(actions.beta_tools)

    return menu_bar
