from PySide6.QtWidgets import QMessageBox

from Tools.Plot_Generator.gui import PlotGeneratorWindow
from Tools.Plot_Generator.plot_settings import PlotSettingsManager


def test_scalp_controls_are_not_exposed(qtbot, tmp_path):
    ini_path = tmp_path / "plot.ini"
    mgr = PlotSettingsManager(ini_path)
    mgr.set("plot", "include_scalp_maps", "true")
    mgr.set("plot", "scalp_min", "-2.5")
    mgr.set("plot", "scalp_max", "2.5")
    mgr.set("scalp", "title_a_template", "Custom {roi}")
    mgr.set("scalp", "title_b_template", "Second {condition}")
    mgr.save()

    window = PlotGeneratorWindow(plot_mgr=mgr)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)

    assert not hasattr(window, "scalp_check")
    assert not hasattr(window, "scalp_min_spin")
    assert not hasattr(window, "scalp_max_spin")
    assert not hasattr(window, "scalp_title_a_edit")
    assert not hasattr(window, "scalp_title_b_edit")
    assert not hasattr(window, "_persist_scalp_settings")


def test_finish_all_prompts_to_view_generated_plots(qtbot, monkeypatch, tmp_path):
    window = PlotGeneratorWindow()
    qtbot.addWidget(window)
    window.out_edit.setText(str(tmp_path))
    window._generated_paths = [str(tmp_path / "plot.png")]

    prompts: list[tuple[str, str]] = []
    opened: list[bool] = []

    def fake_question(_parent, title, message, *_args):
        prompts.append((title, message))
        return QMessageBox.Yes

    monkeypatch.setattr(QMessageBox, "question", fake_question)
    monkeypatch.setattr(window, "_open_output_folder", lambda: opened.append(True))

    window._finish_all()

    assert prompts == [("Finished", "Plots have been successfully generated. View plots?")]
    assert opened == [True]
