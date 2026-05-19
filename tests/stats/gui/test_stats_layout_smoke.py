from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QComboBox, QScrollArea, QSplitter, QStackedWidget, QTabWidget  # noqa: E402

from Main_App.gui.components import ActionRow, SectionCard, StatusBanner  # noqa: E402
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

    setup_tabs = window.findChild(QTabWidget, "stats_setup_tabs")
    assert setup_tabs is not None
    assert setup_tabs.isVisible()
    assert [setup_tabs.tabText(i) for i in range(setup_tabs.count())] == [
        "Basic",
        "Advanced",
    ]
    assert root_splitter.widget(1) is not None
    assert root_splitter.widget(0) is setup_tabs

    basic_scroll = window.findChild(QScrollArea, "stats_basic_setup_scroll_area")
    advanced_scroll = window.findChild(QScrollArea, "stats_advanced_setup_scroll_area")
    assert basic_scroll is not None
    assert advanced_scroll is not None
    assert basic_scroll.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
    assert advanced_scroll.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff

    group_boxes = {
        card.header.title_label.text(): card for card in window.findChildren(SectionCard)
    }
    for title in [
        "Included Conditions",
        "Summed BCA definition",
        "Single Group Analysis",
    ]:
        assert title in group_boxes
    assert "Multi-Group Scan Summary" not in group_boxes
    assert "Between-Group Analysis" not in group_boxes

    assert setup_tabs.widget(0).isAncestorOf(group_boxes["Included Conditions"])
    assert setup_tabs.widget(0).isAncestorOf(group_boxes["Single Group Analysis"])
    assert setup_tabs.widget(0).isAncestorOf(group_boxes["Manual Exclusions"])
    assert setup_tabs.widget(1).isAncestorOf(group_boxes["Summed BCA definition"])
    assert setup_tabs.widget(1).isAncestorOf(window.group_mean_preview_table)
    assert window.group_mean_preview_table.maximumHeight() <= 180

    results_selector = window.findChild(QComboBox, "stats_results_selector")
    results_stack = window.findChild(QStackedWidget, "stats_results_stack")
    assert results_selector is not None
    assert results_stack is not None
    assert [results_selector.itemText(i) for i in range(results_selector.count())] == [
        "Summary",
        "Report",
        "Log",
    ]
    assert results_stack.indexOf(window.summary_text) == 0
    assert results_stack.indexOf(window.reporting_summary_text) == 1
    assert results_stack.indexOf(window.log_text) == 2

    assert window.analyze_single_btn.text() == "Analyze Single Group"
    assert window.analyze_single_btn.property("primary") is True
    assert isinstance(window.single_status_lbl, StatusBanner)
    assert isinstance(window.lbl_status, StatusBanner)
    assert not hasattr(window, "analyze_between_btn")
    assert not hasattr(window, "between_status_lbl")
    assert not hasattr(window, "multi_group_ready_value")
    assert window.log_text.property("logSurface") is True
    assert window.summary_text.property("logSurface") is True

    action_rows = {row.objectName(): row for row in window.findChildren(ActionRow)}
    expected_rows = {
        "stats_conditions_actions",
        "stats_manual_exclusion_actions",
        "stats_single_group_actions",
        "stats_data_folder_actions",
        "stats_export_path_actions",
        "stats_reporting_summary_actions",
        "stats_output_copy_actions",
    }
    assert expected_rows <= set(action_rows)
    assert "stats_between_group_actions" not in action_rows
    assert "stats_multigroup_harmonic_actions" not in action_rows
    assert "stats_multigroup_issue_actions" not in action_rows
    assert action_rows["stats_single_group_actions"].row_layout.indexOf(window.analyze_single_btn) >= 0
    assert action_rows["stats_output_copy_actions"].row_layout.indexOf(window.copy_summary_btn) >= 0
    assert action_rows["stats_reporting_summary_actions"].row_layout.indexOf(window.reporting_summary_save_btn) >= 0
