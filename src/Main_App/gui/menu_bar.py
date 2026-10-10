from __future__ import annotations

from functools import partial

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenuBar, QMainWindow

from Main_App.gui.sidebar import BETA_TOOL_SPECS, DEFAULT_TOOL_SPECS, TOOL_ACCESSIBLE_NAMES
from Main_App.gui.theme import apply_native_menu_appearance


def build_menu_bar(parent: QMainWindow) -> QMenuBar:
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
    home_action = QAction("Home", parent)
    home_action.triggered.connect(parent.show_home_page)
    view_menu.addAction(home_action)

    tools_menu = menu_bar.addMenu("Tools")
    tools_menu.setObjectName("toolsMenu")
    apply_native_menu_appearance(tools_menu)
    for role, text, _icon_kind, opener_name in DEFAULT_TOOL_SPECS:
        action = QAction(TOOL_ACCESSIBLE_NAMES.get(role, text), parent)
        action.setObjectName(role)
        action.triggered.connect(getattr(parent, opener_name))
        tools_menu.addAction(action)

    if parent.settings.beta_tools_enabled():
        tools_menu.addSeparator()
        beta_menu = tools_menu.addMenu("Beta Tools")
        beta_menu.setObjectName("betaToolsMenu")
        apply_native_menu_appearance(beta_menu)
        for role, text, _icon_kind, opener_name in BETA_TOOL_SPECS:
            action = QAction(TOOL_ACCESSIBLE_NAMES.get(role, text), parent)
            action.setObjectName(role)
            action.triggered.connect(
                partial(parent._open_beta_tool, role, getattr(parent, opener_name))
            )
            beta_menu.addAction(action)

    return menu_bar
