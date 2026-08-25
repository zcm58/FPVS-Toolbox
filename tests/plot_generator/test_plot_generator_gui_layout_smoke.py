from pathlib import Path

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QLabel, QScrollArea, QWidget

from Main_App.gui.typography import FONT_ROLES
from Tools.Plot_Generator.gui import PlotGeneratorWindow
from Tools.Plot_Generator import selection_state as plot_selection_state
from Tools.Plot_Generator import session_selection as plot_session_selection
from Main_App.projects import (
    GroupInfo,
    ProjectDatasetIndex,
    SessionInfo,
    WorkbookRecord,
)
from Main_App.gui.components import (
    ActionRow,
    PathPickerRow,
    SectionCard,
    StatusBanner,
    SubsectionHeaderLabel,
)


def test_plot_generator_gui_layout_smoke(qtbot):
    window = PlotGeneratorWindow()
    qtbot.addWidget(window)
    window.resize(1280, 900)
    window.show()
    qtbot.waitExposed(window)

    assert window.minimumWidth() >= 980
    assert window.width() > window.height()
    assert window.folder_edit is not None
    assert window.out_edit is not None
    assert window.condition_combo is not None
    assert window.roi_combo is not None
    assert window.gen_btn is not None
    assert not hasattr(window, "log_toggle_btn")
    assert window.findChildren(QScrollArea) == []
    assert isinstance(window.folder_edit.parentWidget(), PathPickerRow)
    assert isinstance(window.out_edit.parentWidget(), PathPickerRow)
    section_titles = [
        card.header.title_label.text() for card in window.findChildren(SectionCard)
    ]
    assert "Progress" not in section_titles
    assert "Input and Output" in section_titles
    assert "Legend labels (optional)" in section_titles
    assert "Log Output" not in section_titles
    assert len(window.findChildren(SectionCard)) >= 5
    assert window.params_box.header.title_label.font().bold()
    header_font = window.params_box.header.title_label.font()
    header_spec = FONT_ROLES["subsection_header"]
    assert (
        header_font.pointSize() == header_spec.point_size
        or header_font.pixelSize() == header_spec.css_size_px
    )
    assert window.findChild(QLabel, "snr_plots_title").text() == "SNR Plots"
    assert window.findChild(QLabel, "snr_plots_eyebrow") is None
    assert window.findChild(QLabel, "snr_plots_subtitle") is None
    assert window.findChild(StatusBanner, "snr_plot_workflow_status") is window.workflow_status
    assert window.workflow_status.isHidden()
    assert window.progress_bar.isHidden()
    assert window.progress_bar.height() >= 18
    assert window.progress_bar.isTextVisible()
    assert window.folder_edit.width() >= 220
    assert window.out_edit.width() >= 220
    assert window.input_folder_btn.text() == "Choose Excel Folder"
    assert window.output_folder_btn.text() == "Choose Plot Folder"
    input_picker = window.findChild(PathPickerRow, "snr_input_folder_picker")
    output_picker = window.findChild(PathPickerRow, "snr_output_folder_picker")
    assert input_picker is not None
    assert output_picker is not None
    assert input_picker.width() == output_picker.width()
    assert window.input_folder_btn.width() == window.output_folder_btn.width()
    assert window.input_folder_btn.styleSheet() == window.output_folder_btn.styleSheet()
    assert "text-align: left" in window.input_folder_btn.styleSheet()
    assert window.folder_edit.width() == window.out_edit.width()
    assert window.folder_edit.mapTo(window, QPoint(0, 0)).x() == window.out_edit.mapTo(
        window, QPoint(0, 0)
    ).x()
    assert window.input_folder_btn.mapTo(window, QPoint(0, 0)).x() == (
        window.output_folder_btn.mapTo(window, QPoint(0, 0)).x()
    )
    assert window.open_output_btn.text() == "Open Plot Folder"
    assert window.view_log_btn.text() == "View Log"
    assert window.load_defaults_btn.text() == "Restore Plot Defaults"
    assert window.gen_btn.text() == "Generate SNR Plots"
    assert window.title_edit.objectName() == "plot_generator_internal_figure_name"
    assert not window.title_edit.isVisible()
    advanced_labels = [label.text() for label in window.advanced_box.findChildren(QLabel)]
    assert "Figure name:" not in advanced_labels
    assert "X-axis label:" in advanced_labels
    assert "Y-axis label:" in advanced_labels
    assert window.xmin_spin.width() >= 100
    assert window.xmax_spin.width() >= 100
    assert window.ymin_spin.width() >= 100
    assert window.ymax_spin.width() >= 100
    assert window.ymin_spin.value() == 0.5
    assert not hasattr(window, "scalp_check")
    assert not hasattr(window, "scalp_min_spin")
    assert not hasattr(window, "scalp_max_spin")
    assert not hasattr(window, "scalp_title_a_edit")
    assert not hasattr(window, "scalp_title_b_edit")
    assert isinstance(window.condition_b_label, SubsectionHeaderLabel)
    assert isinstance(window.axis_ranges_label, SubsectionHeaderLabel)
    subsection_titles = [
        label.text() for label in window.findChildren(SubsectionHeaderLabel)
    ]
    assert "Condition A" in subsection_titles
    assert "Condition B" in subsection_titles
    assert "ROI" in subsection_titles
    assert "Axis Ranges" in subsection_titles
    assert window.axis_ranges_label.isVisible()
    assert window.legend_group.isVisible()
    assert window.gen_btn.property("primary") is True
    assert window.cancel_btn.property("danger") is True
    action_row = window.findChild(ActionRow, "plot_generator_bottom_actions")
    assert action_row is not None
    assert action_row.row_layout.indexOf(window.load_defaults_btn) >= 0
    assert action_row.row_layout.indexOf(window.open_output_btn) >= 0
    assert action_row.row_layout.indexOf(window.view_log_btn) >= 0
    assert action_row.row_layout.indexOf(window.gen_btn) >= 0
    assert action_row.row_layout.indexOf(window.cancel_btn) >= 0
    assert window.log.property("logSurface") is True
    assert window.folder_edit.accessibleName() == "Processed Excel folder"
    assert window.out_edit.accessibleName() == "Plot output folder"
    assert window.condition_combo.accessibleName() == "Condition to plot"
    assert window.roi_combo.accessibleName() == "Region of interest to plot"
    assert window.progress_bar.accessibleName() == "SNR plot generation progress"
    assert window.log.accessibleName() == "SNR plot generation log"
    assert window.view_log_btn.accessibleName() == "View SNR plot generation log"
    assert window.generation_log_dialog.isHidden()
    assert window.advanced_box.height() >= 250
    params_top = window.params_box.mapTo(window, QPoint(0, 0)).y()
    advanced_top = window.advanced_box.mapTo(window, QPoint(0, 0)).y()
    assert abs(params_top - advanced_top) <= 2
    params_bottom = params_top + window.params_box.height()
    advanced_bottom = advanced_top + window.advanced_box.height()
    assert abs(params_bottom - advanced_bottom) <= 2
    input_output_card = window.findChild(SectionCard, "snr_input_output_card")
    assert input_output_card is not None
    file_left = input_output_card.mapTo(window, QPoint(0, 0)).x()
    legend_left = window.legend_group.mapTo(window, QPoint(0, 0)).x()
    assert abs(legend_left - file_left) <= 2
    assert abs(window.legend_group.width() - input_output_card.width()) <= 2
    left_layout = window.params_box.parentWidget().layout()
    assert left_layout.indexOf(window.params_box) < left_layout.indexOf(window.group_box)
    columns = window.findChild(QWidget, "snr_plot_content_columns")
    assert columns is not None
    columns_bottom = columns.mapTo(window, QPoint(0, 0)).y() + columns.height()
    legend_top = window.legend_group.mapTo(window, QPoint(0, 0)).y()
    assert legend_top > columns_bottom
    assert not window.group_box.isVisible()
    legend_label_widths = {
        label.width()
        for label in (
            window.legend_condition_a_label,
            window.legend_condition_b_label,
            window.legend_a_peaks_label,
            window.legend_b_peaks_label,
        )
    }
    assert len(legend_label_widths) == 1
    assert action_row.geometry().bottom() <= window.height()

    initial_visible = window.condition_b_label.isVisible()
    initial_width = window.width()
    condition_a_x = window.condition_combo.mapTo(window, QPoint(0, 0)).x()
    condition_a_y = window.condition_combo.mapTo(window, QPoint(0, 0)).y()
    window.overlay_check.setChecked(not window.overlay_check.isChecked())
    qtbot.wait(50)
    assert window.condition_b_label.isVisible() != initial_visible
    if window.overlay_check.isChecked():
        condition_b_x = window.condition_b_combo.mapTo(window, QPoint(0, 0)).x()
        condition_b_y = window.condition_b_combo.mapTo(window, QPoint(0, 0)).y()
        assert abs(window.width() - initial_width) <= 2
        assert abs(condition_b_x - condition_a_x) <= 2
        assert condition_b_y > condition_a_y
        assert window.condition_b_combo.width() <= window.condition_combo.width() + 2
        assert window.legend_condition_b_label.isVisible()
        assert window.legend_condition_b_edit.isVisible()
        assert window.legend_b_peaks_label.isVisible()
        assert window.legend_b_peaks_edit.isVisible()
        assert abs(
            window.legend_condition_a_label.geometry().center().y()
            - window.legend_condition_a_edit.geometry().center().y()
        ) <= 4
        assert abs(
            window.legend_a_peaks_label.geometry().center().y()
            - window.legend_a_peaks_edit.geometry().center().y()
        ) <= 4
        assert window.legend_condition_a_edit.width() >= 80
        assert window.legend_condition_b_edit.width() >= 80
        assert window.legend_condition_b_edit.height() >= 20
        assert window.legend_b_peaks_edit.height() >= 20
        for field in (
            window.legend_condition_a_edit,
            window.legend_condition_b_edit,
            window.legend_a_peaks_edit,
            window.legend_b_peaks_edit,
        ):
            field_right = field.mapTo(window.legend_group, QPoint(0, 0)).x() + field.width()
            assert field_right <= window.legend_group.width()

    window.overlay_check.setChecked(not window.overlay_check.isChecked())
    qtbot.wait(50)
    assert window.condition_b_label.isVisible() == initial_visible

    window.log.append("Smoke log line")
    qtbot.wait(10)
    assert "Smoke log line" in window.log.toPlainText()


def _repeated_plot_index(tmp_path: Path) -> ProjectDatasetIndex:
    excel_root = tmp_path / "excel"
    (excel_root / "Faces").mkdir(parents=True)
    groups = {
        "birth_control": GroupInfo(
            "birth_control",
            "Birth control",
            "Birth Control",
            tmp_path / "raw-bc",
        ),
        "no_birth_control": GroupInfo(
            "no_birth_control",
            "No birth control",
            "No Birth Control",
            tmp_path / "raw-no-bc",
        ),
    }
    sessions = {
        "luteal": SessionInfo("luteal", "Luteal phase", 1),
        "follicular": SessionInfo("follicular", "Follicular phase", 2),
    }
    workbooks = tuple(
        WorkbookRecord(
            participant_id=participant_id,
            condition="Faces",
            path=(
                excel_root
                / "Faces"
                / groups[group_id].folder_name
                / session.session_id
                / f"{participant_id}.xlsx"
            ),
            group_id=group_id,
            group_label=groups[group_id].label,
            observed_layout="condition_group_session",
            observed_group_folder=groups[group_id].folder_name,
            recording_id=f"{participant_id}_{session.session_id}",
            session_id=session.session_id,
            session_label=session.label,
            visit_index=session.visit_index,
        )
        for participant_id, group_id in (
            ("P01", "birth_control"),
            ("P02", "no_birth_control"),
        )
        for session in sessions.values()
    )
    return ProjectDatasetIndex(
        project_root=tmp_path,
        excel_root=excel_root,
        scan_root=excel_root,
        manifest={"name": "Repeated"},
        groups=groups,
        participants={},
        workbooks=workbooks,
        excluded_workbooks=(),
        diagnostics=(),
        sessions=sessions,
    )


def test_plot_generator_repeated_session_controls_build_canonical_worker_kwargs(
    qtbot,
    monkeypatch,
    tmp_path,
) -> None:
    index = _repeated_plot_index(tmp_path)
    monkeypatch.setattr(
        plot_session_selection,
        "load_project_dataset_index",
        lambda _path: index,
    )
    monkeypatch.setattr(
        plot_selection_state,
        "load_manifest_for_excel_root",
        lambda _path: {"name": "Repeated"},
    )
    monkeypatch.setattr(
        plot_selection_state,
        "normalize_participants_map",
        lambda _manifest: {
            "P01": "Birth control",
            "P02": "No birth control",
        },
    )
    monkeypatch.setattr(
        plot_selection_state,
        "extract_group_names",
        lambda _manifest: ["Birth control", "No birth control"],
    )
    monkeypatch.setattr(
        plot_selection_state,
        "has_multi_groups",
        lambda _manifest: True,
    )

    window = PlotGeneratorWindow()
    qtbot.addWidget(window)
    window.folder_edit.setText(str(index.excel_root))
    window._populate_conditions(str(index.excel_root))
    window.out_edit.setText(str(tmp_path / "plots"))
    window.show()

    assert window.session_controls_widget.isVisible()
    assert window.session_dimension_combo.currentData() == "session_comparison"
    assert window.reference_session_combo.currentText() == "Luteal phase — Visit 1"
    assert window.comparison_session_combo.currentText() == "Follicular phase — Visit 2"
    assert window.session_error_label.text() == ""
    assert window.session_error_label.isHidden()
    assert window.condition_combo.currentText() == "Faces"
    assert window.legend_group.isVisible() is False

    kwargs = window._session_worker_kwargs()
    assert kwargs["session_comparison_ids"] == ("luteal", "follicular")
    assert kwargs["session_group_ids"] == (
        "birth_control",
        "no_birth_control",
    )
    assert "include_paired_session_difference" not in kwargs
    assert not hasattr(window, "session_difference_check")

    window.session_dimension_combo.setCurrentIndex(
        window.session_dimension_combo.findData("condition")
    )
    assert window._session_worker_kwargs() == {
        "workbook_session_ids": ("luteal",)
    }
