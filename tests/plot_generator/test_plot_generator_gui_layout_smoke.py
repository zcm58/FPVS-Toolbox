import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint

from Tools.Plot_Generator.gui import PlotGeneratorWindow
from Main_App.gui.components import PathPickerRow, SectionCard


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
    assert window.params_box.header.title_label.font().pointSize() > window.font().pointSize()
    legend_top = window.legend_group.mapTo(window, QPoint(0, 0)).y()
    legend_field_top = window.legend_condition_a_edit.mapTo(window, QPoint(0, 0)).y()
    assert legend_field_top - legend_top > 80
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
    assert window.scalp_min_spin.width() >= 100
    assert window.scalp_max_spin.width() >= 100
    assert window.axis_ranges_label.isVisible()
    assert window.legend_group.isVisible()
    assert window.gen_btn.property("primary") is True
    assert window.cancel_btn.property("danger") is True
    assert window.log.property("logSurface") is True
    assert window.log_body.isVisible() is True
    assert window.advanced_box.height() >= 290
    assert window.console_box.height() <= 180
    assert 95 <= window.log.height() <= 120
    assert window.console_box.y() > window.advanced_box.y() + 280
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
    assert abs(legend_bottom - console_bottom) <= 4
    assert not window.scalp_title_a_edit.isEnabled()
    assert not window.scalp_title_b_edit.isEnabled()

    initial_visible = window.condition_b_label.isVisible()
    window.overlay_check.setChecked(not window.overlay_check.isChecked())
    qtbot.wait(50)
    assert window.condition_b_label.isVisible() != initial_visible
    if window.overlay_check.isChecked():
        assert window.legend_condition_b_label.isVisible()
        assert window.legend_condition_b_edit.isVisible()
        assert window.legend_b_peaks_label.isVisible()
        assert window.legend_b_peaks_edit.isVisible()
        assert window.legend_condition_b_edit.height() >= 20
        assert window.legend_b_peaks_edit.height() >= 20
    window.scalp_check.setChecked(True)
    qtbot.wait(50)
    assert window.scalp_title_a_edit.isEnabled()
    assert window.scalp_title_b_edit.isEnabled()

    window.overlay_check.setChecked(not window.overlay_check.isChecked())
    qtbot.wait(50)
    assert window.condition_b_label.isVisible() == initial_visible

    window.log.append("Smoke log line")
    qtbot.wait(10)
    assert "Smoke log line" in window.log.toPlainText()
