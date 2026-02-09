import importlib.util

import pytest


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except ValueError:
        return False


def _tools_menu_titles(window) -> list[str]:
    menu_bar = window.menuBar()
    tools_menu = None
    for action in menu_bar.actions():
        menu = action.menu()
        if menu and menu.title() == "Tools":
            tools_menu = menu
            break
    assert tools_menu is not None
    return [action.text() for action in tools_menu.actions() if action.text()]


def test_ratio_calculator_removed_from_ui(qtbot):
    if not _module_available("PySide6") or not _module_available("pytestqt"):
        pytest.skip("PySide6 or pytest-qt not available")

    from PySide6.QtWidgets import QApplication

    from Main_App.PySide6_App.GUI.main_window import MainWindow
    from Main_App.PySide6_App.GUI.sidebar import SidebarButton

    QApplication.instance() or QApplication([])
    window = MainWindow()
    qtbot.addWidget(window)

    sidebar_labels = [btn.text_lbl.text() for btn in window.sidebar.findChildren(SidebarButton)]
    assert "Ratio Calculator" not in sidebar_labels

    tools_menu_actions = _tools_menu_titles(window)
    assert "Ratio Calculator" not in tools_menu_actions
