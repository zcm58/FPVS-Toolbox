from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QListWidget, QWidget, QPushButton, QTabWidget  # noqa: E402

from Tools.Stats.ui.stats_window import StatsWindow  # noqa: E402


@pytest.fixture(autouse=True)
def _stub_default_loader(monkeypatch):
    monkeypatch.setattr(StatsWindow, "_load_default_data_folder", lambda self: None, raising=False)


@pytest.mark.qt
def test_stats_gui_cleanliness_layout_and_copy(qtbot, tmp_path):
    window = StatsWindow(project_dir=str(tmp_path))
    qtbot.addWidget(window)
    window.show()

    setup_area = window.findChild(QWidget, "stats_setup_area")
    assert setup_area is not None
    setup_tabs = window.findChild(QTabWidget, "stats_setup_tabs")
    assert setup_tabs is not None
    assert [setup_tabs.tabText(i) for i in range(setup_tabs.count())] == [
        "Basic",
        "Significant Harmonics",
        "Review",
    ]
    assert setup_tabs.widget(0).isAncestorOf(window.le_folder)
    assert setup_tabs.widget(0).isAncestorOf(window.manual_exclusion_group)
    assert not setup_area.isAncestorOf(window.lbl_status)
    assert not window.lbl_status.isVisible()
    assert not hasattr(window, "data_folder_group")
    assert not hasattr(window, "btn_copy_folder")
    assert not hasattr(window, "btn_open_results")
    assert not hasattr(window, "info_button")
    assert not hasattr(window, "on_show_analysis_info")

    buttons = {btn.text(): btn for btn in window.findChildren(QPushButton)}
    assert "Manage Exclusions" not in buttons
    assert window.manual_exclusion_select_all_btn.text() in buttons
    assert window.manual_exclusion_clear_btn.text() in buttons
    assert isinstance(window.manual_exclusion_candidates_list, QListWidget)
    assert not hasattr(window, "reporting_summary_export_checkbox")
    assert window.reporting_summary_export_action.isChecked()

    assert window.findChild(QWidget, "stats_results_selector") is None
    assert window.findChild(QWidget, "stats_results_stack") is None
    assert window.summary_text.isVisible()
    assert not window.reporting_summary_text.isVisible()
    assert not window.log_text.isVisible()

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
    assert not hasattr(window, "copy_log_btn")
