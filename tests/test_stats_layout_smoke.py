from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QSplitter, QTabWidget  # noqa: E402

from Main_App.gui.widgets import SectionCard, StatusBanner  # noqa: E402
from Tools.Stats.ui.stats_window import StatsWindow  # noqa: E402


@pytest.fixture
def app(qapp):
    """Ensure a QApplication exists for qtbot interactions."""
    return qapp


@pytest.mark.qt
def test_stats_window_layout_smoke(qtbot, tmp_path, app):
    window = StatsWindow(project_dir=str(tmp_path))
    qtbot.addWidget(window)
    window.show()

    splitters = window.findChildren(QSplitter)
    root_splitter = next(
        (
            sp
            for sp in splitters
            if sp.objectName() == "stats_root_splitter" and sp.orientation() == Qt.Vertical
        ),
        None,
    )
    assert root_splitter is not None

    tab_widget = window.findChild(QTabWidget)
    assert tab_widget is not None
    assert tab_widget.isVisible()
    assert root_splitter.widget(1) is not None
    assert root_splitter.widget(1).isAncestorOf(tab_widget)

    group_boxes = {
        card.header.title_label.text(): card for card in window.findChildren(SectionCard)
    }
    for title in [
        "Included Conditions",
        "Summed BCA definition",
        "Multi-Group Scan Summary",
        "Single Group Analysis",
        "Between-Group Analysis",
    ]:
        assert title in group_boxes

    top_panel = root_splitter.widget(0)
    assert top_panel is not None
    assert top_panel.isAncestorOf(group_boxes["Included Conditions"])
    assert top_panel.isAncestorOf(group_boxes["Summed BCA definition"])
    assert top_panel.isAncestorOf(group_boxes["Multi-Group Scan Summary"])

    assert window.analyze_single_btn.text() == "Analyze Single Group"
    assert window.analyze_between_btn.text() == "Analyze Group Differences"
    assert window.analyze_single_btn.property("primary") is True
    assert window.analyze_between_btn.property("primary") is True
    assert isinstance(window.single_status_lbl, StatusBanner)
    assert isinstance(window.between_status_lbl, StatusBanner)
    assert isinstance(window.lbl_status, StatusBanner)
    assert isinstance(window.multi_group_ready_value, StatusBanner)
    assert window.log_text.property("logSurface") is True
    assert window.summary_text.property("logSurface") is True
