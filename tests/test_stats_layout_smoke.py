from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QGroupBox, QHBoxLayout, QPushButton, QSplitter, QTextEdit  # noqa: E402

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
    splitter = None
    for idx in range(layout.count()):
        item = layout.itemAt(idx)
        if item is None:
            continue
        widget = item.widget()
        if isinstance(widget, QSplitter):
            splitter = widget
            break
    assert splitter is not None
    assert splitter.orientation() == Qt.Horizontal

    buttons = window.findChildren(QPushButton)
    texts = {btn.text() for btn in buttons}
    assert "Analyze Single Group" in texts
    assert "Analyze Group Differences" in texts

    log_widget = window.findChild(QTextEdit)
    assert log_widget is not None
    assert log_widget.isVisible()

    left_pane = splitter.widget(0)
    right_pane = splitter.widget(1)
    assert left_pane is not None
    assert right_pane is not None
    assert left_pane.isAncestorOf(window.conditions_group)
    assert right_pane.isAncestorOf(window.output_text)

    group_boxes = window.findChildren(QGroupBox)
    analysis_box = next(box for box in group_boxes if box.title() == "Analysis Controls")
    single_group_box = next(box for box in group_boxes if box.title() == "Single Group Analysis")
    between_group_box = next(box for box in group_boxes if box.title() == "Between-Group Analysis")
    analysis_layout = analysis_box.layout()
    assert isinstance(analysis_layout, QHBoxLayout)
    assert analysis_layout.indexOf(single_group_box) != -1
    assert analysis_layout.indexOf(between_group_box) != -1
