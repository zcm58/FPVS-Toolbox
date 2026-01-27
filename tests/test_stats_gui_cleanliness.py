from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QGroupBox, QPushButton, QTabWidget  # noqa: E402

from Tools.Stats.PySide6.stats_ui_pyside6 import StatsWindow  # noqa: E402


@pytest.fixture(autouse=True)
def _stub_default_loader(monkeypatch):
    monkeypatch.setattr(StatsWindow, "_load_default_data_folder", lambda self: None, raising=False)


@pytest.mark.qt
def test_stats_gui_cleanliness_layout_and_copy(qtbot, tmp_path):
    window = StatsWindow(project_dir=str(tmp_path))
    qtbot.addWidget(window)
    window.show()

    group_boxes = window.findChildren(QGroupBox)
    manual_group = next(box for box in group_boxes if box.title() == "Manual Exclusions")
    assert manual_group is not None

    buttons = {btn.text(): btn for btn in window.findChildren(QPushButton)}
    assert "Edit…" in buttons
    assert "Clear" in buttons

    tab_widget = window.findChild(QTabWidget)
    assert tab_widget is not None
    assert tab_widget.indexOf(window.summary_text) != -1
    assert tab_widget.indexOf(window.log_text) != -1
    assert tab_widget.tabText(tab_widget.indexOf(window.summary_text)) == "Summary"
    assert tab_widget.tabText(tab_widget.indexOf(window.log_text)) == "Log"

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

    qtbot.mouseClick(window.copy_log_btn, Qt.LeftButton)
    assert clipboard.text() == "Log content"

    assert window.btn_copy_folder.isEnabled()
    qtbot.mouseClick(window.btn_copy_folder, Qt.LeftButton)
    assert clipboard.text() == long_path
