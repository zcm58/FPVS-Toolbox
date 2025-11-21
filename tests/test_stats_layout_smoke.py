from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QPushButton, QTextEdit, QVBoxLayout  # noqa: E402

from Tools.Stats.PySide6.stats_ui_pyside6 import StatsWindow  # noqa: E402


@pytest.fixture
def app(qapp):
    """Ensure a QApplication exists for qtbot interactions."""
    return qapp


@pytest.mark.qt
def test_stats_window_layout_smoke(qtbot, tmp_path, app):
    window = StatsWindow(project_dir=str(tmp_path))
    qtbot.addWidget(window)
    window.show()

    layout = window.centralWidget().layout()
    assert isinstance(layout, QVBoxLayout)

    buttons = window.findChildren(QPushButton)
    texts = {btn.text() for btn in buttons}
    assert "Analyze Single Group" in texts
    assert "Analyze Group Differences" in texts

    log_widget = window.findChild(QTextEdit)
    assert log_widget is not None
    assert log_widget.isVisible()
