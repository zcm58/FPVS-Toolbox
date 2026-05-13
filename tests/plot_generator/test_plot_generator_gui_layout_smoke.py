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
    assert window.log_toggle_btn is not None
    assert isinstance(window.folder_edit.parentWidget(), PathPickerRow)
    assert isinstance(window.out_edit.parentWidget(), PathPickerRow)
    assert len(window.findChildren(SectionCard)) >= 7
    assert window.progress_box.width() >= 420
    progress_origin = window.progress_box.mapTo(window, QPoint(0, 0))
    progress_center = progress_origin.x() + (window.progress_box.width() // 2)
    assert abs(progress_center - (window.width() // 2)) <= 30
    assert progress_origin.y() > window.height() // 2
    assert window.folder_edit.width() >= 250
    assert window.title_edit.width() >= 250
    assert window.gen_btn.property("primary") is True
    assert window.cancel_btn.property("danger") is True
    assert window.log.property("logSurface") is True

    initial_visible = window.condition_b_label.isVisible()
    window.overlay_check.setChecked(not window.overlay_check.isChecked())
    qtbot.wait(50)
    assert window.condition_b_label.isVisible() != initial_visible

    window.overlay_check.setChecked(not window.overlay_check.isChecked())
    qtbot.wait(50)
    assert window.condition_b_label.isVisible() == initial_visible

    window.log_toggle_btn.toggle()
    qtbot.wait(10)
    window.log_toggle_btn.toggle()
    qtbot.wait(10)
