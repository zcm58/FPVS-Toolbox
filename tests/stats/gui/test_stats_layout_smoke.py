from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QCheckBox,
    QComboBox,
    QHeaderView,
    QLabel,
    QListWidget,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QTextEdit,
    QWidget,
)

from Main_App.gui.components import (  # noqa: E402
    ActionRow,
    SectionCard,
    SubsectionHeaderLabel,
)
from Tools.Stats.ui.stats_window import StatsWindow  # noqa: E402
from Tools.Stats.ui.tool_info import STATS_TOOL_INFO  # noqa: E402


@pytest.fixture
def app(qapp):
    """Ensure a QApplication exists for qtbot interactions."""
    return qapp


@pytest.fixture(autouse=True)
def _stub_default_loader(monkeypatch):
    monkeypatch.setattr(
        StatsWindow,
        "_load_default_data_folder",
        lambda self: None,
        raising=False,
    )


@pytest.mark.qt
def test_stats_window_layout_smoke(qtbot, tmp_path, app):
    window = StatsWindow(project_dir=str(tmp_path))
    qtbot.addWidget(window)
    window.show()
    assert window.windowTitle() == "Standard FPVS Screening"

    splitters = window.findChildren(QSplitter)
    root_splitter = next(
        (
            splitter
            for splitter in splitters
            if splitter.objectName() == "stats_root_splitter"
            and splitter.orientation() == Qt.Vertical
        ),
        None,
    )
    assert root_splitter is not None
    assert root_splitter.widget(1) is not None

    setup_area = root_splitter.widget(0)
    assert setup_area.objectName() == "stats_setup_area"
    setup_tabs = window.findChild(QTabWidget, "stats_setup_tabs")
    assert setup_tabs is not None
    assert [setup_tabs.tabText(index) for index in range(setup_tabs.count())] == [
        "Basic",
        "Advanced",
    ]
    assert setup_tabs.widget(0).objectName() == "stats_basic_setup_page"
    assert setup_tabs.widget(1).objectName() == "stats_advanced_setup_page"
    assert "QTabWidget#stats_setup_tabs::pane" in setup_tabs.styleSheet()
    assert "border: 0" in setup_tabs.styleSheet()
    assert "background: transparent" in setup_tabs.styleSheet()

    setup_scroll_areas = {
        scroll.objectName()
        for scroll in window.findChildren(QScrollArea)
        if setup_area.isAncestorOf(scroll)
    }
    assert setup_scroll_areas == {
        "stats_basic_setup_page",
        "stats_conditions_scroll_area",
        "stats_advanced_inference_page",
        "stats_advanced_dv_quality_page",
        "stats_advanced_export_context_page",
    }

    cards = {
        card.header.title_label.text(): card
        for card in window.findChildren(SectionCard)
    }
    for title in [
        "File I/O",
        "Analysis Design",
        "Included Conditions",
        "Manual Exclusions",
        "Standard FPVS Screening",
        "Summed BCA definition",
        "Outlier Flagging",
        "Exports",
        "Last Export",
        "ROI Context",
    ]:
        assert title in cards
    for title in ["Data Folder", "Single Group Analysis", "Review"]:
        assert title not in cards
    assert "Multi-Group Scan Summary" not in cards
    assert "Between-Group Analysis" not in cards

    for card in window.findChildren(SectionCard):
        ancestor = card.parentWidget()
        while ancestor is not None:
            assert not isinstance(ancestor, SectionCard)
            ancestor = ancestor.parentWidget()

    basic_page = setup_tabs.widget(0)
    advanced_page = setup_tabs.widget(1)
    assert isinstance(basic_page, QScrollArea)
    assert basic_page.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
    assert basic_page.verticalScrollBarPolicy() == Qt.ScrollBarAsNeeded
    advanced_tabs = window.findChild(QTabWidget, "stats_advanced_tabs")
    assert advanced_tabs is window.advanced_tabs
    assert advanced_page.isAncestorOf(advanced_tabs)
    assert [
        advanced_tabs.tabText(index)
        for index in range(advanced_tabs.count())
    ] == [
        "Screening",
        "DV & quality",
        "Export & context",
    ]
    for index in range(advanced_tabs.count()):
        page = advanced_tabs.widget(index)
        assert isinstance(page, QScrollArea)
        assert page.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
        assert page.verticalScrollBarPolicy() == Qt.ScrollBarAsNeeded
    for title in [
        "File I/O",
        "Analysis Design",
        "Included Conditions",
        "Manual Exclusions",
    ]:
        assert basic_page.isAncestorOf(cards[title])
    for title in [
        "Standard FPVS Screening",
        "Summed BCA definition",
        "Outlier Flagging",
        "Exports",
        "Last Export",
        "ROI Context",
    ]:
        assert advanced_page.isAncestorOf(cards[title])

    assert cards["Included Conditions"].sizePolicy().verticalPolicy() == QSizePolicy.Expanding
    assert window.conditions_scroll_area.sizePolicy().verticalPolicy() == QSizePolicy.Expanding
    assert cards["Outlier Flagging"].isAncestorOf(
        window.findChild(QWidget, "stats_outlier_flagging")
    )
    assert cards["Last Export"].isAncestorOf(
        window.findChild(QWidget, "stats_export_path_actions")
    )
    assert cards["ROI Context"].isAncestorOf(window.roi_context_text)
    assert window.lbl_rois is window.roi_context_text
    assert window.roi_context_text.objectName() == "stats_roi_context_text"
    assert isinstance(window.roi_context_text, QTextEdit)
    assert window.roi_context_text.isReadOnly()
    assert window.roi_context_text.minimumHeight() >= 120
    assert basic_page.isAncestorOf(window.le_folder)
    assert basic_page.isAncestorOf(
        window.findChild(QWidget, "stats_manual_exclusion_row")
    )
    assert isinstance(window.manual_exclusion_candidates_list, QListWidget)
    assert cards["Manual Exclusions"].isAncestorOf(
        window.manual_exclusion_candidates_list
    )
    assert cards["Summed BCA definition"].isAncestorOf(
        window.fixed_predefined_preview_table
    )
    assert window.recalculate_harmonics_btn.text() == "Open Recalculation Settings"
    assert "Settings > Preprocessing" in window.recalculate_harmonics_btn.toolTip()
    assert (
        window.fixed_predefined_preview_table.sizePolicy().verticalPolicy()
        == QSizePolicy.Fixed
    )
    assert (
        window.fixed_predefined_preview_table.sizePolicy().horizontalPolicy()
        == QSizePolicy.Expanding
    )
    assert window.fixed_predefined_preview_table.maximumHeight() <= 150
    header = window.fixed_predefined_preview_table.horizontalHeader()
    assert header.sectionResizeMode(0) == QHeaderView.Stretch
    assert header.sectionResizeMode(5) == QHeaderView.Stretch

    assert window.analysis_design_group.objectName() == "stats_analysis_design_group"
    assert window.analysis_mode_value.objectName() == "stats_analysis_mode_value"
    assert window.analysis_mode_value.text() == "Single Group"
    assert window.analysis_profile_value.objectName() == "stats_analysis_profile_value"
    assert window.analysis_profile_value.text() == "Standard FPVS Screening"
    assert window.analysis_group_value.objectName() == "stats_analysis_group_value"
    assert window.analysis_coverage_value.objectName() == "stats_analysis_coverage_value"

    expected_controls = {
        "stats_analysis_profile_combo": QComboBox,
        "stats_group_pair_combo": QComboBox,
        "stats_multiplicity_combo": QComboBox,
        "stats_response_alternative_combo": QComboBox,
        "stats_analysis_scope_combo": QComboBox,
        "stats_independent_selection_attestation": QCheckBox,
        "stats_strict_omnibus_family_checkbox": QCheckBox,
        "stats_robust_sensitivity_checkbox": QCheckBox,
        "stats_resampling_sensitivity_checkbox": QCheckBox,
        "stats_stability_sensitivity_checkbox": QCheckBox,
    }
    for object_name, widget_type in expected_controls.items():
        widget = window.findChild(widget_type, object_name)
        assert widget is not None
        assert advanced_page.isAncestorOf(widget)
    methods = window.findChild(QLabel, "stats_standard_screening_methods")
    assert methods is window.standard_screening_methods_label
    assert "Primary participant-random-intercept LMM" in methods.text()
    assert "one-sided > 0 response tests" in methods.text()
    assert "finite observations with no imputation" in methods.text()
    assert "Holm family-wise correction" in methods.text()
    assert "balanced-only secondary ANOVA compatibility" in methods.text()
    assert window.analysis_profile_combo.currentData() == "published_style_exploratory"
    assert window.multiplicity_combo.currentData() == "holm"
    assert window.multiplicity_combo.count() == 1
    assert window.response_alternative_combo.currentData() == "greater"
    assert window.analysis_scope_combo.currentData() == "available_case"
    assert window.analysis_scope_combo.count() == 1
    for locked_control in (
        window.analysis_profile_combo,
        window.multiplicity_combo,
        window.response_alternative_combo,
        window.analysis_scope_combo,
        window.strict_omnibus_family_checkbox,
    ):
        assert locked_control.isHidden()
        assert not locked_control.isEnabled()
    assert window.resample_count_spin.objectName() == "stats_resample_count_spin"
    assert window.resample_count_spin.value() == 9_999
    assert window.resample_count_spin.isHidden()
    assert window.strict_omnibus_family_checkbox.isChecked()
    assert window.robust_sensitivity_checkbox.isChecked()
    assert not window.resampling_sensitivity_checkbox.isChecked()
    assert window.resampling_sensitivity_checkbox.isHidden()
    assert not window.resampling_sensitivity_checkbox.isEnabled()
    assert not window.resample_count_spin.isEnabled()
    assert window.stability_sensitivity_checkbox.isChecked()
    assert window.group_pair_combo.isHidden()
    assert not window.group_pair_combo.isEnabled()
    assert "exactly two canonical groups" in window.group_pair_combo.toolTip()

    assert not hasattr(window, "provenance_warning")
    assert window.findChild(QWidget, "stats_provenance_warning") is None
    assert window.findChild(QWidget, "stats_results_selector") is None
    assert window.findChild(QWidget, "stats_results_stack") is None
    output_headers = [
        label.text()
        for label in window.findChildren(SubsectionHeaderLabel)
        if label.text() == "Screening Results"
    ]
    assert output_headers == ["Screening Results"]
    results_tabs = window.findChild(QTabWidget, "stats_results_tabs")
    assert results_tabs is window.results_tabs
    assert [results_tabs.tabText(index) for index in range(results_tabs.count())] == [
        "At a glance",
        "Run log",
    ]
    assert results_tabs.widget(0) is window.summary_text
    assert results_tabs.widget(1) is window.log_text
    assert window.summary_text.objectName() == "stats_at_a_glance_text"
    assert window.log_text.objectName() == "stats_run_log_text"
    assert not hasattr(window, "reporting_summary_text")
    assert window.findChild(QWidget, "stats_methods_checks_text") is None
    assert window.summary_output_container.isVisible()
    assert window.summary_text.isVisible()
    assert not window.log_text.isVisible()
    results_tabs.setCurrentIndex(1)
    qtbot.wait(20)
    assert not window.summary_text.isVisible()
    assert window.log_text.isVisible()
    results_tabs.setCurrentIndex(0)

    assert window.run_action_bar.isVisible()
    setup_tabs.setCurrentIndex(1)
    qtbot.wait(20)
    assert window.summary_output_container.isVisible()
    assert window.run_action_bar.isVisible()
    setup_tabs.setCurrentIndex(0)

    assert window.analyze_single_btn.text() == "Run Standard Screening"
    assert window.analyze_single_btn.objectName() == "stats_analyze_single_primary"
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

    window._project_is_multi_group = True
    window._group_participant_counts = {"anxious": 6, "non_anxious": 7}
    window._group_display_labels = {
        "anxious": "Anxious",
        "non_anxious": "Non-anxious",
    }
    window._populate_group_pair_combo()
    window._sync_analysis_mode_ui()
    assert window.analyze_single_btn.text() == "Run Standard Screening"
    assert window.analysis_mode_value.text() == "Multi-Group"
    assert not window.group_pair_combo.isHidden()
    assert not window.group_pair_combo.isEnabled()
    assert window.group_pair_combo.currentData() == ("anxious", "non_anxious")
    window._project_is_multi_group = False
    window._populate_group_pair_combo()
    window._sync_analysis_mode_ui()

    assert window.lbl_status.objectName() == "stats_status_internal"
    assert setup_area.isAncestorOf(window.lbl_status)
    assert window.lbl_status.isVisible()
    assert window.pipeline_phase_label.objectName() == "stats_pipeline_phase_label"
    assert window.pipeline_phase_label.text() == "Ready"
    assert isinstance(window.pipeline_progress_bar, QProgressBar)
    assert window.pipeline_progress_bar.objectName() == "stats_pipeline_progress_bar"
    assert window.pipeline_progress_bar.value() == 0
    assert window.cancel_analysis_btn.objectName() == "stats_cancel_analysis_button"
    assert not window.cancel_analysis_btn.isEnabled()
    window.set_pipeline_progress("Resampling sensitivity", 2, 4)
    assert window.pipeline_phase_label.text() == "Resampling sensitivity"
    assert window.pipeline_progress_bar.value() == 50
    window.set_pipeline_running(True, phase="Fitting models", cancellable=False)
    assert not window.cancel_analysis_btn.isEnabled()
    window.set_pipeline_running(True, phase="Resampling", cancellable=True)
    assert window.cancel_analysis_btn.isEnabled()
    assert window.pipeline_phase_label.text() == "Resampling"
    window.set_pipeline_running(False)
    assert not window.cancel_analysis_btn.isEnabled()

    assert window.stats_processing_notice.objectName() == "stats_processing_notice"
    assert not window.stats_processing_notice.isVisible()
    assert window.stats_processing_message.text().startswith(
        "FPVS Toolbox is currently calculating an average FFT spectrum"
    )
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

    window._set_roi_status("Using 2 ROIs from Settings: Central, Left Occipito-Temporal")
    roi_context = window.roi_context_text.toPlainText()
    assert "ROI definitions loaded from Settings." in roi_context
    assert "Central" in roi_context
    window._set_detected_info(
        "Baseline vs Zero tests completed.\n"
        "Corrected significant findings:\n"
        "1. A in Central: mean=0.4, corrected p=0.01"
    )
    assert "Baseline vs Zero tests completed" not in window.roi_context_text.toPlainText()

    action_rows = {
        row.objectName(): row for row in window.findChildren(ActionRow)
    }
    expected_rows = {
        "stats_conditions_actions",
        "stats_manual_exclusion_actions",
        "stats_data_folder_actions",
        "stats_export_path_actions",
        "stats_export_options_actions",
        "stats_output_copy_actions",
    }
    assert expected_rows <= set(action_rows)
    data_buttons = [
        button.text()
        for button in action_rows["stats_data_folder_actions"].findChildren(QPushButton)
    ]
    assert data_buttons == ["Browse..."]
    assert (
        action_rows["stats_output_copy_actions"].row_layout.indexOf(
            window.copy_summary_btn
        )
        >= 0
    )
    assert not hasattr(window, "copy_log_btn")
    assert not hasattr(window, "reporting_summary_copy_btn")
    assert not hasattr(window, "reporting_summary_save_btn")


@pytest.mark.qt
def test_stats_harmonic_action_opens_settings_without_clearing_cache(
    qtbot,
    tmp_path,
    app,
):
    manifest_path = tmp_path / "project.json"
    manifest_text = (
        '{"tools":{"stats":{"group_significant_harmonics_cache":'
        '{"entries":{"keep-me":{"selection_metadata":{"selected_harmonics_hz":[1.2]}}}}}}}'
    )
    manifest_path.write_text(manifest_text, encoding="utf-8")

    host = QWidget()
    qtbot.addWidget(host)
    opened: list[bool] = []
    host.open_settings_window = lambda: opened.append(True)
    workspace = QStackedWidget(host)

    window = StatsWindow(parent=host, project_dir=str(tmp_path))
    qtbot.addWidget(window)
    workspace.addWidget(window)
    window.show()
    window.setup_tabs.setCurrentIndex(1)
    window.advanced_tabs.setCurrentIndex(1)
    qtbot.wait(20)

    qtbot.mouseClick(window.recalculate_harmonics_btn, Qt.LeftButton)

    assert opened == [True]
    assert manifest_path.read_text(encoding="utf-8") == manifest_text
    assert "Opened Settings > Preprocessing" in window.lbl_status.text()


def test_stats_tool_info_uses_expected_nonexpert_tabs():
    assert [tab.title for tab in STATS_TOOL_INFO.tabs] == [
        "Workflow",
        "Standard methods",
        "How to interpret results",
    ]
    combined_html = "\n".join(tab.html for tab in STATS_TOOL_INFO.tabs)
    assert "finite" in combined_html.casefold()
    assert "without imputation" in combined_html
    assert "exploratory post-selection" in combined_html
    assert "does <b>not</b> prove equivalence" in combined_html
