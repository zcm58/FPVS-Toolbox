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

    library_action = actions.addAction("Experiment Library…")
    library_action.setObjectName("actionExperimentLibrary")

    def show_library() -> None:
        from Main_App.gui.experiment_library_workflow import show_experiment_library

        if menu_bar.isVisible() and menu_bar.isEnabled():
            show_experiment_library(parent)

    library_action.triggered.connect(show_library)
    view_menu.addAction(library_action)

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

    help_menu = menu_bar.addMenu("&Help")
    help_menu.setObjectName("helpMenu")
    actions.documentation.setText("Documentation")
    help_menu.addAction(actions.documentation)

    return menu_bar
