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

    from PySide6.QtWidgets import QApplication, QSizePolicy, QWidget

    from Main_App.gui.components import ActionRow, SectionCard, StatusBanner
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
    assert cards["ratio_calculator_conditions"].sizePolicy().verticalPolicy() == QSizePolicy.Maximum
    assert not cards["ratio_calculator_conditions"].header.isVisible()
    assert window.input_a_open_btn.minimumHeight() >= 30
    assert window.input_a_btn.minimumHeight() >= 30
    assert cards["ratio_calculator_participants"].toolTip()
    assert not cards["ratio_calculator_run"].header.isVisible()
    assert window.findChild(QWidget, "ratio_calculator_run_output_row") is not None
    assert window.run_btn.property("variant") == "primary"
    assert window.log_toggle_btn.property("variant") == "tertiary"
    assert window.log_toggle_btn.text() == "Open log"
    assert "Select both condition folders" in window._log_text

    action_rows = {row.objectName(): row for row in window.findChildren(ActionRow)}
    expected_rows = {
        "ratio_calculator_condition_actions",
        "ratio_calculator_input_a_actions",
        "ratio_calculator_input_b_actions",
        "ratio_calculator_output_actions",
        "ratio_calculator_participant_actions",
        "ratio_calculator_run_actions",
        "ratio_calculator_bottom_actions",
    }
    assert expected_rows <= set(action_rows)
    assert action_rows["ratio_calculator_run_actions"].row_layout.indexOf(window.run_btn) >= 0
    assert action_rows["ratio_calculator_bottom_actions"].row_layout.indexOf(window.open_output_btn) >= 0


def test_ratio_calculator_folder_cancel_preserves_state(qtbot, monkeypatch):
    if not _module_available("PySide6") or not _module_available("pytestqt"):
        pytest.skip("PySide6 or pytest-qt not available")

    from PySide6.QtWidgets import QApplication

    from Tools.Ratio_Calculator.gui import RatioCalculatorWindow

    QApplication.instance() or QApplication([])
    window = RatioCalculatorWindow()
    qtbot.addWidget(window)

    window.input_a_edit.setText("existing-a")
    window.input_b_edit.setText("existing-b")
    window.output_edit.setText("existing-output")
    previous_last_dir = window._last_dir

    monkeypatch.setattr(
        "Tools.Ratio_Calculator.gui.QFileDialog.getExistingDirectory",
        lambda *args, **kwargs: "",
    )

    window._browse_folder(window.input_a_edit, is_output=False, condition_key="a")
    window._browse_folder(window.input_b_edit, is_output=False, condition_key="b")
    window._browse_folder(window.output_edit, is_output=True)

    assert window.input_a_edit.text() == "existing-a"
    assert window.input_b_edit.text() == "existing-b"
    assert window.output_edit.text() == "existing-output"
    assert window._last_dir == previous_last_dir
