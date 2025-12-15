import pytest

from Tools.Plot_Generator.gui import PlotGeneratorWindow
from Tools.Plot_Generator.plot_settings import PlotSettingsManager


@pytest.mark.parametrize("initial_checked", [False, True])
def test_scalp_controls_toggle_and_persistence(qtbot, tmp_path, initial_checked):
    ini_path = tmp_path / "plot.ini"
    mgr = PlotSettingsManager(ini_path)
    mgr.set_include_scalp_maps(initial_checked)
    mgr.set_scalp_bounds(-1.0, 1.0)
    mgr.save()

    window = PlotGeneratorWindow(plot_mgr=mgr)
    qtbot.addWidget(window)

    assert window.scalp_check.isChecked() is initial_checked
    assert window.scalp_min_spin.isEnabled() is initial_checked
    assert window.scalp_max_spin.isEnabled() is initial_checked

    window.scalp_check.setChecked(not initial_checked)
    assert window.scalp_min_spin.isEnabled() is (not initial_checked)
    assert window.scalp_max_spin.isEnabled() is (not initial_checked)
    window.close()

    mgr.set_include_scalp_maps(True)
    mgr.set_scalp_bounds(-2.5, 2.5)
    mgr.save()

    restored_mgr = PlotSettingsManager(ini_path)
    restored_window = PlotGeneratorWindow(plot_mgr=restored_mgr)
    qtbot.addWidget(restored_window)

    assert restored_window.scalp_check.isChecked() is True
    assert restored_window.scalp_min_spin.value() == pytest.approx(-2.5)
    assert restored_window.scalp_max_spin.value() == pytest.approx(2.5)
    restored_window.close()
