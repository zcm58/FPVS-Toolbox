import pytest

from Tools.Plot_Generator.gui import PlotGeneratorWindow
from Tools.Plot_Generator.plot_settings import PlotSettingsManager


@pytest.mark.parametrize("initial_checked", [False, True])
def test_scalp_controls_toggle_and_persistence(qtbot, tmp_path, initial_checked):
    ini_path = tmp_path / "plot.ini"
    mgr = PlotSettingsManager(ini_path)
    mgr.set_include_scalp_maps(initial_checked)
    mgr.set_scalp_bounds(-1.0, 1.0)
    mgr.set_scalp_title_a_template("{condition} {roi} scalp map")
    mgr.set_scalp_title_b_template("B: {condition} {roi}")
    mgr.save()

    window = PlotGeneratorWindow(plot_mgr=mgr)
    qtbot.addWidget(window)

    assert window.scalp_check.isChecked() is initial_checked
    assert window.scalp_min_spin.isEnabled() is initial_checked
    assert window.scalp_max_spin.isEnabled() is initial_checked
    assert window.scalp_title_a_edit.isEnabled() is initial_checked
    assert window.scalp_title_b_edit.isVisible() is False

    window.scalp_check.setChecked(not initial_checked)
    assert window.scalp_min_spin.isEnabled() is (not initial_checked)
    assert window.scalp_max_spin.isEnabled() is (not initial_checked)
    assert window.scalp_title_a_edit.isEnabled() is (not initial_checked)
    window.overlay_check.setChecked(True)
    assert window.scalp_title_b_edit.isVisible() is window.scalp_check.isChecked()
    window.scalp_check.setChecked(True)
    assert window.scalp_title_b_edit.isVisible() is True
    window.scalp_check.setChecked(False)
    assert window.scalp_title_b_edit.isVisible() is False
    window.close()

    mgr.set_include_scalp_maps(True)
    mgr.set_scalp_bounds(-2.5, 2.5)
    mgr.set_scalp_title_a_template("Custom {roi}")
    mgr.set_scalp_title_b_template("Second {condition}")
    mgr.save()

    restored_mgr = PlotSettingsManager(ini_path)
    restored_window = PlotGeneratorWindow(plot_mgr=restored_mgr)
    qtbot.addWidget(restored_window)

    assert restored_window.scalp_check.isChecked() is True
    assert restored_window.scalp_min_spin.value() == pytest.approx(-2.5)
    assert restored_window.scalp_max_spin.value() == pytest.approx(2.5)
    assert restored_window.scalp_title_a_edit.text() == "Custom {roi}"
    assert restored_window.scalp_title_b_edit.text() == "Second {condition}"

    restored_window.scalp_title_a_edit.setText("Persist A")
    restored_window.scalp_title_b_edit.setText("Persist B {condition}")
    restored_window.scalp_min_spin.setValue(-4.2)
    restored_window.scalp_max_spin.setValue(4.2)
    restored_window._persist_scalp_settings(save=True)

    reloaded_mgr = PlotSettingsManager(ini_path)
    assert reloaded_mgr.get_scalp_title_a_template() == "Persist A"
    assert reloaded_mgr.get_scalp_title_b_template() == "Persist B {condition}"
    assert reloaded_mgr.get_scalp_bounds() == (-4.2, 4.2)
    restored_window.close()
