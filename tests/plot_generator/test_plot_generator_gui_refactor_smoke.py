import pytest

from Tools.Plot_Generator.gui import PlotGeneratorWindow


@pytest.mark.usefixtures("qtbot")
def test_condition_changes_do_not_require_removed_scalp_titles(qtbot, tmp_path):
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
    win._check_required()
    assert win.gen_btn.isEnabled()
    assert win.workflow_status.isHidden()
    assert win.progress_bar.isHidden()

    win.condition_combo.setCurrentText("CondB")
    qtbot.wait(50)
    assert not win.gen_btn.isEnabled()
    assert "two different conditions" in win.workflow_status.text()
    assert win.workflow_status.isVisible()
    assert win.progress_bar.isHidden()

    win.condition_b_combo.setCurrentText("CondA")
    qtbot.wait(50)
    assert win.gen_btn.isEnabled()
    assert win.workflow_status.isHidden()


@pytest.mark.usefixtures("qtbot")
def test_idle_status_and_progress_do_not_consume_page_rows(qtbot):
    win = PlotGeneratorWindow()
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)

    assert win.workflow_status.isHidden()
    assert win.progress_bar.isHidden()
    assert not hasattr(win, "console_box")

    win._set_workflow_status("Action is required.", "warning")
    assert win.workflow_status.isVisible()
    assert win.progress_bar.isHidden()

    win._check_required()
    assert win.workflow_status.isHidden()
