from __future__ import annotations

from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QMenuBar, QMainWindow

from Main_App.gui.shell_actions import BETA_TOOL_SPECS as BETA_TOOL_SPECS
from Main_App.gui.shell_actions import ShellActions


def build_menu_bar(parent: QMainWindow, actions: ShellActions) -> QMenuBar:
    """Return the app-level menus using the shared command identities."""
    menu_bar = QMenuBar(parent)
    menu_bar.setObjectName("workspaceMenuBar")
    menu_bar.setNativeMenuBar(False)

    file_menu = menu_bar.addMenu("&File")
    file_menu.setObjectName("fileMenu")

    view_menu = menu_bar.addMenu("&View")
    view_menu.setObjectName("viewMenu")
    actions.home.setShortcut(QKeySequence("Ctrl+1"))
    parent.addAction(actions.home)
    view_menu.addAction(actions.home)

    view_menu.addAction(actions.library)

    tools_menu = menu_bar.addMenu("&Tools")
    tools_menu.setObjectName("toolsMenu")
    tools_menu.addActions(actions.default_tools)
    parent.tool_actions = {
        action.objectName(): action
        for action in (*actions.default_tools, *actions.beta_tools)
    }
    if actions.beta_tools:
        tools_menu.addSeparator()
        beta_menu = tools_menu.addMenu("Beta Tools")
        beta_menu.setObjectName("betaToolsMenu")
        beta_menu.addActions(actions.beta_tools)

    return menu_bar
