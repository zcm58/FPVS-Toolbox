from PySide6.QtWidgets import QMessageBox

import Tools.Plot_Generator.gui as plot_gui
from Main_App.processing.roi_settings import ALL_ROIS_OPTION
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


def test_finish_all_reports_success_inline_without_modal(qtbot, monkeypatch, tmp_path):
    window = PlotGeneratorWindow()
    qtbot.addWidget(window)
    window.out_edit.setText(str(tmp_path))
    window._generated_paths = [str(tmp_path / "plot.png")]

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("routine completion must not open a modal")
        ),
    )

    window._finish_all()

    assert window.workflow_status.property("statusVariant") == "success"
    assert "Generated 1 figure file" in window.workflow_status.text()
    assert "Open Plot Folder" in window.workflow_status.text()
    assert not window.workflow_status.isHidden()
    assert window.progress_bar.isHidden()


def test_late_cancel_after_saved_figure_reports_warning(qtbot, tmp_path):
    window = PlotGeneratorWindow()
    qtbot.addWidget(window)
    window.out_edit.setText(str(tmp_path))
    window._generated_paths = [str(tmp_path / "plot.png")]
    window._thread = object()
    window._worker = object()
    window._cancel_requested = True
    window._worker_reported_cancelled = False
    window._worker_outcome_received = True

    window._generation_finished()

    assert window.workflow_status.property("statusVariant") == "warning"
    assert "after these files were saved" in window.workflow_status.text()
    assert not window.workflow_status.isHidden()
    assert window.progress_bar.isHidden()
    assert window._late_cancel_after_commit is False


def test_refresh_rois_preserves_valid_selection_and_blocks_empty_configuration(
    qtbot,
    monkeypatch,
):
    roi_state = {
        "First": ["Cz"],
        "Keep": ["O1"],
    }

    def load_rois(_manager=None):
        return {name: list(electrodes) for name, electrodes in roi_state.items()}

    monkeypatch.setattr(plot_gui, "load_rois_from_settings", load_rois)
    window = PlotGeneratorWindow()
    qtbot.addWidget(window)
    window.folder_edit.setText("input")
    window.out_edit.setText("output")
    window.condition_combo.addItem("Condition A")
    window.condition_combo.setCurrentText("Condition A")
    window.roi_combo.setCurrentText("Keep")

    captured_worker_payload = window._worker_roi_selection()
    assert captured_worker_payload == ({"Keep": ["O1"]}, "Keep")

    roi_state["Keep"] = ["O2"]
    roi_state["New"] = ["P10"]
    window.refresh_rois(object())

    assert window.roi_map == {
        "First": ["Cz"],
        "Keep": ["O2"],
        "New": ["P10"],
    }
    assert [window.roi_combo.itemText(i) for i in range(window.roi_combo.count())] == [
        ALL_ROIS_OPTION,
        "First",
        "Keep",
        "New",
    ]
    assert window.roi_combo.currentText() == "Keep"
    assert window.gen_btn.isEnabled()

    del roi_state["Keep"]
    window.refresh_rois(object())
    assert window.roi_combo.currentText() == ALL_ROIS_OPTION

    roi_state.clear()
    roi_state["Empty"] = []
    window.refresh_rois(object())
    assert window.roi_map == {}
    assert window.roi_combo.isEnabled() is False
    assert window.gen_btn.isEnabled() is False
    assert window.workflow_status.property("statusVariant") == "warning"
    assert "Settings > ROIs" in window.workflow_status.text()
    assert captured_worker_payload == ({"Keep": ["O1"]}, "Keep")
