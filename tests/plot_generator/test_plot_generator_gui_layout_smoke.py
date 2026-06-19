from PySide6.QtCore import QPoint

from Main_App.gui.typography import font_for_role
from Tools.Plot_Generator.gui import PlotGeneratorWindow
from Tools.Plot_Generator.settings_dialog import _SettingsDialog
from Main_App.gui.components import ActionRow, PathPickerRow, SectionCard, SubsectionHeaderLabel


def test_plot_generator_gui_layout_smoke(qtbot):
    window = PlotGeneratorWindow()
    qtbot.addWidget(window)
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
    assert isinstance(window.folder_edit.parentWidget(), PathPickerRow)
    assert isinstance(window.out_edit.parentWidget(), PathPickerRow)
    section_titles = [
        card.header.title_label.text() for card in window.findChildren(SectionCard)
    ]
    assert "Progress" not in section_titles
    assert "File I/O" in section_titles
    assert "Legend labels (optional)" in section_titles
    assert len(window.findChildren(SectionCard)) >= 6
    assert window.params_box.header.title_label.font().bold()
    assert (
        window.params_box.header.title_label.font().pointSize()
        == font_for_role("subsection_header").pointSize()
    )
    legend_top = window.legend_group.mapTo(window, QPoint(0, 0)).y()
    legend_field_top = window.legend_condition_a_edit.mapTo(window, QPoint(0, 0)).y()
    assert 80 <= legend_field_top - legend_top <= 120
    progress_origin = window.progress_bar.mapTo(window, QPoint(0, 0))
    assert progress_origin.y() > window.height() - 80
    reset_right = window.load_defaults_btn.mapTo(
        window, window.load_defaults_btn.rect().topRight()
    ).x()
    generate_left = window.gen_btn.mapTo(window, window.gen_btn.rect().topLeft()).x()
    assert progress_origin.x() > reset_right
    assert progress_origin.x() + window.progress_bar.width() < generate_left
    assert 8 <= window.progress_bar.height() <= 12
    assert window.folder_edit.width() >= 220
    assert window.out_edit.width() >= 220
    assert window.title_edit.width() >= 250
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
    assert action_row.row_layout.indexOf(window.save_defaults_btn) >= 0
    assert action_row.row_layout.indexOf(window.load_defaults_btn) >= 0
    assert action_row.row_layout.indexOf(window.gen_btn) >= 0
    assert action_row.row_layout.indexOf(window.cancel_btn) >= 0
    assert window.log.property("logSurface") is True
    assert window.log_body.isVisible() is True
    assert window.advanced_box.height() >= 250
    assert window.console_box.height() <= 180
    assert 95 <= window.log.height() <= 120
    assert window.console_box.y() > window.advanced_box.y() + 240
    params_top = window.params_box.mapTo(window, QPoint(0, 0)).y()
    advanced_top = window.advanced_box.mapTo(window, QPoint(0, 0)).y()
    legend_bottom = (
        window.legend_group.mapTo(window, QPoint(0, 0)).y()
        + window.legend_group.height()
    )
    console_bottom = (
        window.console_box.mapTo(window, QPoint(0, 0)).y()
        + window.console_box.height()
    )
    assert abs(params_top - advanced_top) <= 2
    assert abs(window.params_box.height() - window.legend_group.height()) <= 4
    assert abs(legend_bottom - console_bottom) <= 4
    assert not window.group_box.isVisible()

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
        assert window.legend_condition_a_label.y() < window.legend_condition_a_edit.y()
        assert window.legend_condition_b_label.y() < window.legend_condition_b_edit.y()
        assert window.legend_a_peaks_label.y() < window.legend_a_peaks_edit.y()
        assert window.legend_b_peaks_label.y() < window.legend_b_peaks_edit.y()
        assert window.legend_condition_a_edit.width() >= 220
        assert window.legend_condition_b_edit.width() >= 220
        assert window.legend_condition_b_edit.height() >= 20
        assert window.legend_b_peaks_edit.height() >= 20

    window.overlay_check.setChecked(not window.overlay_check.isChecked())
    qtbot.wait(50)
    assert window.condition_b_label.isVisible() == initial_visible

    window.log.append("Smoke log line")
    qtbot.wait(10)
    assert "Smoke log line" in window.log.toPlainText()


def test_plot_generator_settings_dialog_uses_shared_action_row(qtbot):
    parent = PlotGeneratorWindow()
    qtbot.addWidget(parent)
    dialog = _SettingsDialog(parent, "#112233", "#445566")
    qtbot.addWidget(dialog)

    action_row = dialog.findChild(ActionRow, "plot_generator_settings_actions")
    assert action_row is not None
    labels = [
        item.widget().text()
        for idx in range(action_row.row_layout.count())
        if (item := action_row.row_layout.itemAt(idx)).widget() is not None
    ]
    assert "OK" in labels
    assert "Cancel" in labels
