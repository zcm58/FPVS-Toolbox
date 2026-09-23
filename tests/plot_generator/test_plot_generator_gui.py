import os
from pathlib import Path

from PySide6.QtWidgets import QDialog, QMessageBox, QScrollArea
from PySide6.QtCore import QObject, QPoint, QRect, QTimer, Qt, Signal
import pytest

import Tools.Plot_Generator.gui as plot_gui
from Main_App.processing.roi_settings import ALL_ROIS_OPTION
from Tools.Plot_Generator.gui import PlotGeneratorWindow
from Tools.Plot_Generator.plot_settings import PlotSettingsManager
from tests.gui.ux_capture import ux_capture_theme  # noqa: F401


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


def test_disabled_overlay_explains_problem_and_focuses_second_condition(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(plot_gui, "load_rois_from_settings", lambda *_: {"ROI": ["Cz"]})
    window = PlotGeneratorWindow()
    qtbot.addWidget(window)
    window.folder_edit.setText(str(tmp_path))
    window.out_edit.setText(str(tmp_path / "plots"))
    window.condition_combo.clear()
    window.condition_b_combo.clear()
    window.condition_combo.addItems(["A", "B"])
    window.condition_b_combo.addItems(["A", "B"])
    window.overlay_check.setChecked(True)
    window.resize(1280, 900)
    window.show()
    qtbot.waitExposed(window)
    window.activateWindow()
    window._check_required()
    assert not window.gen_btn.isEnabled()
    for button in (window.input_folder_btn, window.output_folder_btn):
        assert button.width() >= button.sizeHint().width()
    assert window.workflow_status.isVisible()
    assert "two different conditions" in window.workflow_status.text()
    qtbot.mouseClick(window.fix_setup_btn, Qt.LeftButton)
    qtbot.waitUntil(lambda: window.focusWidget() is window.condition_b_combo)
    screenshot_dir = os.environ.get("FPVS_UX_SCREENSHOT_DIR")
    if screenshot_dir:
        path = Path(screenshot_dir)
        path.mkdir(parents=True, exist_ok=True)
        window.grab().save(str(path / "snr_setup_validation.png"))
    window.condition_b_combo.setCurrentText("B")
    assert window.gen_btn.isEnabled()
    assert window.workflow_status.isHidden()
    window._session_control_error = (
        "Choose a valid session comparison. The selected recording set is missing "
        "canonical session identities; review the project's recording registration "
        "and select two different registered sessions before generating plots."
    )
    window._check_required()
    window.layout().activate()
    assert window.width() == 1280 and window.height() == 900
    for control in (window.workflow_status, window.gen_btn, window.cancel_btn):
        assert window.rect().contains(QRect(control.mapTo(window, QPoint()), control.size()))
    assert window.workflow_status.label.height() >= window.workflow_status.label.heightForWidth(
        window.workflow_status.label.width()
    )
    if screenshot_dir:
        window.grab().save(str(Path(screenshot_dir) / "snr_long_validation.png"))


def test_five_conditions_fit_validate_and_freeze_at_supported_size(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(plot_gui, "load_rois_from_settings", lambda *_: {"ROI": ["Cz"]})
    conditions = [f"Condition {letter} with a long descriptive experimental name" for letter in "ABCDE"]
    excel = tmp_path / "excel"
    for condition in conditions:
        (excel / condition).mkdir(parents=True)
    window = PlotGeneratorWindow()
    qtbot.addWidget(window)
    window.folder_edit.setText(str(excel))
    window._populate_conditions(str(excel))
    window.out_edit.setText(str(tmp_path / "plots"))
    window.overlay_check.setChecked(True)
    window.overlay_count_spin.setValue(5)
    window.resize(1280, 900)
    window.show()
    qtbot.waitExposed(window)
    window.activateWindow()
    assert window._selected_overlay_conditions() == tuple(conditions)
    assert window.gen_btn.isEnabled()
    assert not window.findChildren(QScrollArea)
    assert window.width() == 1280 and window.height() == 900
    for control in (*window._overlay_condition_combos(), window.overlay_count_spin, window.gen_btn):
        assert control.isVisible()
        assert window.rect().contains(QRect(control.mapTo(window, QPoint()), control.size()))
    assert all(combo.toolTip() == condition for combo, condition in zip(window._overlay_condition_combos(), conditions))

    window.extra_condition_combos[-1].setCurrentIndex(0)
    assert not window.gen_btn.isEnabled()
    assert "Condition E repeats" in window.workflow_status.text()
    window.setup_tabs.setCurrentIndex(1)
    qtbot.mouseClick(window.fix_setup_btn, Qt.LeftButton)
    qtbot.waitUntil(lambda: window.focusWidget() is window.extra_condition_combos[-1])
    assert window.setup_tabs.currentIndex() == 0
    window.extra_condition_combos[-1].setCurrentIndex(4)
    assert window.gen_btn.isEnabled()

    window.setup_tabs.setCurrentIndex(1)
    for field in window._legend_fields.values():
        assert field.isVisible()
        assert window.rect().contains(QRect(field.mapTo(window, QPoint()), field.size()))
    controls = [
        *window._overlay_condition_combos(), *window.extra_color_buttons,
        *window._legend_fields.values(), window.overlay_count_spin,
        window.folder_edit, window.out_edit, window.spectral_qc_check,
    ]
    window._set_generation_navigation_locked(True)
    assert all(not control.isEnabled() for control in controls)
    window._set_generation_navigation_locked(False)
    assert all(control.isEnabled() for control in controls)

    window.overlay_count_spin.setValue(2)
    window.setup_tabs.setCurrentIndex(0)
    assert all(container.isHidden() for container in window.extra_condition_containers)
    assert window._selected_overlay_conditions() == tuple(conditions[:2])


@pytest.mark.parametrize("choice", ["replace", "keep", "cancel"])
def test_export_preflight_confirms_collisions_before_launch(qtbot, tmp_path, monkeypatch, choice):
    monkeypatch.setattr(plot_gui, "load_rois_from_settings", lambda *_: {"ROI": ["Cz"]})
    plans = []

    class Worker(QObject):
        progress = Signal(str, int, int)
        finished = Signal(dict)

        def __init__(self, *_args, **kwargs):
            super().__init__()
            plans.append(kwargs["export_plan"])

        def run(self):
            self.finished.emit({"generated_paths": [], "failed_items": [], "warning_items": []})

    monkeypatch.setattr(plot_gui, "_Worker", Worker, raising=False)
    window = PlotGeneratorWindow()
    qtbot.addWidget(window)
    window.folder_edit.setText(str(tmp_path))
    window.out_edit.setText(str(tmp_path))
    window.condition_combo.clear()
    window.condition_combo.addItem("A")
    window.title_edit.setText("A")
    window.roi_combo.setCurrentText("ROI")
    png, pdf = tmp_path / "A - ROI.png", tmp_path / "A - ROI.pdf"
    png.write_bytes(b"old png")
    pdf.write_bytes(b"old pdf")
    prompts = []

    def decide(choices):
        prompts.append(choices)
        assert plans == []
        assert not window.params_box.isEnabled()
        return {"replace": choices.replace, "keep": choices.keep_both, "cancel": None}[choice]

    monkeypatch.setattr(window, "_choose_export_collision_action", decide)
    window._generate()
    qtbot.waitUntil(lambda: bool(prompts) and not window.has_active_generation(), timeout=5000)
    assert len(prompts) == 1
    assert window.params_box.isEnabled()
    assert png.read_bytes() == b"old png"
    assert pdf.read_bytes() == b"old pdf"
    if choice == "cancel":
        assert not plans
    else:
        assert len(plans) == 1
        expected = "A - ROI.png" if choice == "replace" else "A - ROI (2).png"
        assert plans[0][0].png_path.name == expected


@pytest.mark.parametrize("action", ["Keep both", "Replace existing", "Cancel", "Escape"])
def test_collision_dialog_safe_default_real_actions_and_geometry(qtbot, tmp_path, monkeypatch, action):
    from Tools.Plot_Generator.export_plan import inspect_destinations

    window = PlotGeneratorWindow()
    qtbot.addWidget(window)
    window.resize(1280, 900)
    window.show()
    qtbot.waitExposed(window)
    (tmp_path / "A - ROI.png").write_bytes(b"old")
    choices = inspect_destinations(str(tmp_path), (("A", "ROI", ""),))
    observed = {}
    # The suite normally auto-dismisses QMessageBox; this case exercises the real popup.
    monkeypatch.setattr(QMessageBox, "exec", lambda box: QDialog.exec(box))

    def choose():
        dialog = window.findChild(QMessageBox)
        try:
            observed["default"] = dialog.defaultButton().text()
            observed["fits"] = dialog.width() <= 1280 and dialog.height() <= 900
            observed["buttons_fit"] = all(
                dialog.rect().contains(QRect(button.mapTo(dialog, QPoint()), button.size()))
                for button in dialog.buttons()
            )
            screenshot_dir = os.environ.get("FPVS_UX_SCREENSHOT_DIR")
            if screenshot_dir:
                path = Path(screenshot_dir)
                path.mkdir(parents=True, exist_ok=True)
                dialog.grab().save(str(path / f"snr_collision_{action.lower().replace(' ', '_')}.png"))
            if action == "Escape":
                qtbot.keyClick(dialog, Qt.Key_Escape)
            elif action == "Cancel":
                dialog.button(QMessageBox.Cancel).click()
            else:
                next(button for button in dialog.buttons() if button.text() == action).click()
        finally:
            if dialog.isVisible():
                dialog.reject()

    QTimer.singleShot(0, choose)
    result = window._choose_export_collision_action(choices)
    assert observed == {"default": "Keep both", "fits": True, "buttons_fit": True}
    expected = {"Keep both": choices.keep_both, "Replace existing": choices.replace}.get(action)
    assert result == expected
    assert (tmp_path / "A - ROI.png").read_bytes() == b"old"
