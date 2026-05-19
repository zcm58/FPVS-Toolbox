from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QLabel,
    QListWidget,
    QSizePolicy,
    QWidget,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTabWidget,
)

from Main_App.gui.components import ActionRow, SectionCard  # noqa: E402
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

    assert root_splitter.widget(1) is not None
    setup_area = root_splitter.widget(0)
    assert setup_area.objectName() == "stats_setup_area"
    setup_tabs = window.findChild(QTabWidget, "stats_setup_tabs")
    assert setup_tabs is not None
    assert [setup_tabs.tabText(i) for i in range(setup_tabs.count())] == [
        "Basic",
        "Significant Harmonics",
        "Review",
    ]
    assert setup_tabs.widget(0).objectName() == "stats_basic_setup_page"
    assert setup_tabs.widget(1).objectName() == "stats_harmonics_setup_page"
    assert setup_tabs.widget(2).objectName() == "stats_review_setup_page"
    assert "QTabWidget#stats_setup_tabs::pane" in setup_tabs.styleSheet()
    assert "border: 0" in setup_tabs.styleSheet()
    assert "background: transparent" in setup_tabs.styleSheet()

    setup_scroll_areas = [
        scroll.objectName()
        for scroll in window.findChildren(QScrollArea)
        if setup_area.isAncestorOf(scroll)
    ]
    assert setup_scroll_areas == ["stats_conditions_scroll_area"]

    group_boxes = {
        card.header.title_label.text(): card for card in window.findChildren(SectionCard)
    }
    for title in [
        "File I/O",
        "Included Conditions",
        "Manual Exclusions",
        "Summed BCA definition",
        "Review",
    ]:
        assert title in group_boxes
    for title in [
        "Data Folder",
        "Outlier Flagging",
        "Comparison Exports",
        "Single Group Analysis",
    ]:
        assert title not in group_boxes
    assert "Multi-Group Scan Summary" not in group_boxes
    assert "Between-Group Analysis" not in group_boxes

    basic_page = setup_tabs.widget(0)
    harmonics_page = setup_tabs.widget(1)
    review_page = setup_tabs.widget(2)
    assert basic_page.isAncestorOf(group_boxes["File I/O"])
    assert basic_page.isAncestorOf(group_boxes["Included Conditions"])
    assert basic_page.isAncestorOf(group_boxes["Manual Exclusions"])
    assert group_boxes["Included Conditions"].sizePolicy().verticalPolicy() == QSizePolicy.Expanding
    assert window.conditions_scroll_area.sizePolicy().verticalPolicy() == QSizePolicy.Expanding
    assert harmonics_page.isAncestorOf(group_boxes["Summed BCA definition"])
    assert review_page.isAncestorOf(group_boxes["Review"])
    assert basic_page.isAncestorOf(window.le_folder)
    assert basic_page.isAncestorOf(window.findChild(QWidget, "stats_manual_exclusion_row"))
    assert group_boxes["Included Conditions"].header.title_label.text() == "Included Conditions"
    assert group_boxes["Manual Exclusions"].isAncestorOf(
        window.findChild(QWidget, "stats_manual_exclusion_row")
    )
    assert isinstance(window.manual_exclusion_candidates_list, QListWidget)
    assert group_boxes["Manual Exclusions"].isAncestorOf(window.manual_exclusion_candidates_list)
    assert group_boxes["Summed BCA definition"].isAncestorOf(window.group_mean_preview_table)
    assert window.group_mean_preview_table.maximumHeight() <= 180

    assert window.findChild(QWidget, "stats_results_selector") is None
    assert window.findChild(QWidget, "stats_results_stack") is None
    output_headers = [
        label.text()
        for label in window.findChildren(QLabel)
        if label.text() == "Significant Results Summary:"
    ]
    assert output_headers == ["Significant Results Summary:"]
    assert window.summary_text.isVisible()
    assert not window.log_text.isVisible()
    assert not window.reporting_summary_text.isVisible()

    assert window.analyze_single_btn.text() == "Analyze Single Group"
    assert window.analyze_single_btn.property("primary") is True
    assert window.analyze_single_btn.minimumHeight() >= 36
    run_action_bar = window.findChild(QWidget, "stats_run_action_bar")
    assert run_action_bar is not None
    assert setup_area.isAncestorOf(run_action_bar)
    assert run_action_bar.isAncestorOf(window.analyze_single_btn)
    assert run_action_bar.isAncestorOf(window.single_advanced_btn)
    run_action_layout = run_action_bar.layout()
    assert run_action_layout.indexOf(window.analyze_single_btn) < run_action_layout.indexOf(
        window.single_advanced_btn
    )
    assert not hasattr(window, "single_status_lbl")
    assert window.lbl_status.objectName() == "stats_status_internal"
    assert not window.lbl_status.isVisible()
    assert not setup_area.isAncestorOf(window.lbl_status)
    assert window.findChild(QWidget, "stats_status_chip") is None
    assert window.findChild(QWidget, "stats_status_footer") is None
    assert not hasattr(window, "btn_copy_folder")
    assert not hasattr(window, "btn_open_results")
    assert not hasattr(window, "info_button")
    assert not hasattr(window, "on_show_analysis_info")
    assert not hasattr(window, "analyze_between_btn")
    assert not hasattr(window, "between_status_lbl")
    assert not hasattr(window, "multi_group_ready_value")
    assert not hasattr(window, "manual_exclusion_edit_btn")
    assert window.manual_exclusion_select_all_btn.text() == "Exclude all"
    assert window.manual_exclusion_clear_btn.text() == "Clear exclusions"
    assert isinstance(window.manual_exclusion_summary_label, QLabel)
    assert not hasattr(window, "reporting_summary_export_checkbox")
    assert window.reporting_summary_export_action.isCheckable()
    assert window.reporting_summary_export_action.isChecked()
    assert window.log_text.property("logSurface") is True
    assert window.summary_text.property("logSurface") is True

    action_rows = {row.objectName(): row for row in window.findChildren(ActionRow)}
    expected_rows = {
        "stats_conditions_actions",
        "stats_manual_exclusion_actions",
        "stats_data_folder_actions",
        "stats_export_path_actions",
        "stats_review_export_actions",
        "stats_output_copy_actions",
    }
    assert expected_rows <= set(action_rows)
    assert "stats_between_group_actions" not in action_rows
    assert "stats_single_group_actions" not in action_rows
    assert "stats_reporting_summary_actions" not in action_rows
    assert "stats_multigroup_harmonic_actions" not in action_rows
    assert "stats_multigroup_issue_actions" not in action_rows
    data_buttons = [
        button.text()
        for button in action_rows["stats_data_folder_actions"].findChildren(QPushButton)
    ]
    assert data_buttons == ["Browse..."]
    assert action_rows["stats_output_copy_actions"].row_layout.indexOf(window.copy_summary_btn) >= 0
    assert not hasattr(window, "copy_log_btn")
    assert not hasattr(window, "reporting_summary_copy_btn")
    assert not hasattr(window, "reporting_summary_save_btn")
