import pytest

from Tools.Plot_Generator.gui import PlotGeneratorWindow


@pytest.mark.usefixtures("qtbot")
def test_scalp_title_clearing_disables_generate(qtbot, tmp_path):
    excel_root = tmp_path / "excel"
    excel_root.mkdir()
    (excel_root / "CondA").mkdir()
    (excel_root / "CondB").mkdir()
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    win = PlotGeneratorWindow()
    qtbot.addWidget(win)
    win.folder_edit.setText(str(excel_root))
    win._populate_conditions(str(excel_root))
    win.out_edit.setText(str(out_dir))

    win.condition_combo.setCurrentText("CondA")
    win.overlay_check.setChecked(True)
    win.condition_b_combo.setCurrentText("CondB")
    win.scalp_check.setChecked(True)
    win.scalp_title_a_edit.setText("Title A")
    win.scalp_title_b_edit.setText("Title B")
    win._check_required()
    assert win.gen_btn.isEnabled()

    win.condition_combo.setCurrentText("CondB")
    qtbot.wait(50)
    assert win.scalp_title_a_edit.text() == ""
    assert not win.gen_btn.isEnabled()

    win.scalp_title_a_edit.setText("Again")
    qtbot.wait(50)
    assert win.gen_btn.isEnabled()

    win.condition_b_combo.setCurrentText("CondA")
    qtbot.wait(50)
    assert win.scalp_title_b_edit.text() == ""
    assert not win.gen_btn.isEnabled()


@pytest.mark.usefixtures("qtbot")
def test_log_output_is_fixed_height(qtbot):
    win = PlotGeneratorWindow()
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)

    height_before = win.height()
    assert not hasattr(win, "log_toggle_btn")
    assert win.log_body.isVisible() is True
    assert win.advanced_box.height() >= 290
    assert win.console_box.height() <= 180
    assert 95 <= win.log.height() <= 120

    win.log.append("Fixed log output")
    qtbot.wait(100)
    height_after = win.height()

    assert "Fixed log output" in win.log.toPlainText()
    assert height_after <= height_before + 10
