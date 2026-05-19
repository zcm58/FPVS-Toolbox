from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QComboBox, QPushButton, QStackedWidget, QTabWidget  # noqa: E402

from Tools.Stats.ui.stats_window import StatsWindow  # noqa: E402


@pytest.fixture(autouse=True)
def _stub_default_loader(monkeypatch):
    monkeypatch.setattr(StatsWindow, "_load_default_data_folder", lambda self: None, raising=False)


@pytest.mark.qt
def test_stats_gui_cleanliness_layout_and_copy(qtbot, tmp_path):
    window = StatsWindow(project_dir=str(tmp_path))
    qtbot.addWidget(window)
    window.show()

    assert window.manual_exclusion_group.header.title_label.text() == "Manual Exclusions"

    buttons = {btn.text(): btn for btn in window.findChildren(QPushButton)}
    assert window.manual_exclusion_edit_btn.text() in buttons
    assert "Clear" in buttons

    setup_tabs = window.findChild(QTabWidget, "stats_setup_tabs")
    assert setup_tabs is not None
    assert [setup_tabs.tabText(i) for i in range(setup_tabs.count())] == [
        "Basic",
        "Advanced",
    ]
    results_selector = window.findChild(QComboBox, "stats_results_selector")
    results_stack = window.findChild(QStackedWidget, "stats_results_stack")
    assert results_selector is not None
    assert results_stack is not None
    assert results_stack.indexOf(window.summary_text) == 0
    assert results_stack.indexOf(window.reporting_summary_text) == 1
    assert results_stack.indexOf(window.log_text) == 2

    long_path = str(tmp_path / "a" / "very" / "long" / "path" / "to" / "fpvs" / "results")
    window._set_data_folder_path(long_path)
    window.le_folder.setFixedWidth(120)
    qtbot.wait(50)
    assert window.le_folder.toolTip() == long_path
    assert window.le_folder.displayed_text() != long_path

    window.summary_text.setPlainText("Summary content")
    window.log_text.setPlainText("Log content")

    clipboard = QGuiApplication.clipboard()

    qtbot.mouseClick(window.copy_summary_btn, Qt.LeftButton)
    assert clipboard.text() == "Summary content"

    results_selector.setCurrentText("Log")
    qtbot.wait(20)
    qtbot.mouseClick(window.copy_log_btn, Qt.LeftButton)
    assert clipboard.text() == "Log content"

    assert window.btn_copy_folder.isEnabled()
    qtbot.mouseClick(window.btn_copy_folder, Qt.LeftButton)
    assert clipboard.text() == long_path
