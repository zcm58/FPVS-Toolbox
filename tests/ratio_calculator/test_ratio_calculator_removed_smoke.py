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


def test_ratio_calculator_present_in_ui(qtbot):
    if not _module_available("PySide6") or not _module_available("pytestqt"):
        pytest.skip("PySide6 or pytest-qt not available")

    from PySide6.QtWidgets import QApplication

    from Main_App.gui.main_window import MainWindow
    from Main_App.gui.sidebar import SidebarButton

    QApplication.instance() or QApplication([])
    window = MainWindow()
    qtbot.addWidget(window)

    sidebar_labels = [btn.text_lbl.text() for btn in window.sidebar.findChildren(SidebarButton)]
    assert "Ratio Calculator" in sidebar_labels

    tools_menu_actions = _tools_menu_titles(window)
    assert "Ratio Calculator" in tools_menu_actions


def test_ratio_calculator_window_smoke(qtbot):
    if not _module_available("PySide6") or not _module_available("pytestqt"):
        pytest.skip("PySide6 or pytest-qt not available")

    from PySide6.QtWidgets import QApplication

    from Main_App.gui.components import SectionCard, StatusBanner
    from Tools.Ratio_Calculator.gui import RatioCalculatorWindow

    QApplication.instance() or QApplication([])
    window = RatioCalculatorWindow()
    qtbot.addWidget(window)
    window.show()

    cards = {card.objectName(): card for card in window.findChildren(SectionCard)}
    expected_cards = {
        "ratio_calculator_conditions",
        "ratio_calculator_participants",
        "ratio_calculator_rois",
        "ratio_calculator_harmonic_settings",
        "ratio_calculator_run",
    }
    assert expected_cards <= set(cards)
    assert isinstance(window.status_label, StatusBanner)
    assert isinstance(window.validation_label, StatusBanner)
    assert window.run_btn.property("variant") == "primary"
    assert window.log_toggle_btn.property("variant") == "tertiary"
    assert window.log_box.property("logSurface") is True
