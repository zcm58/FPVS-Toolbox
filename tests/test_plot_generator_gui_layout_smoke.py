import os
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from Tools.Plot_Generator.gui import PlotGeneratorWindow


def test_plot_generator_gui_layout_smoke(qtbot):
    window = PlotGeneratorWindow()
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)

    assert window.folder_edit is not None
    assert window.out_edit is not None
    assert window.condition_combo is not None
    assert window.roi_combo is not None
    assert window.gen_btn is not None
    assert window.log_toggle_btn is not None

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
