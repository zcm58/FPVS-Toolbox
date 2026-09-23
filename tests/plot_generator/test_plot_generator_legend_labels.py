from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

try:
    has_pyside = importlib.util.find_spec("PySide6") is not None
    has_pytestqt = importlib.util.find_spec("pytestqt") is not None
except ValueError:
    has_pyside = False
    has_pytestqt = False

if not has_pyside or not has_pytestqt:
    pytest.skip("PySide6/pytest-qt not available", allow_module_level=True)

from PySide6.QtWidgets import QMessageBox  # noqa: E402

from Tools.Plot_Generator import gui as plot_gui  # noqa: E402


class _DummySignal:
    def connect(self, *args, **kwargs):  # noqa: ANN001, ARG002
        return None


class _DummyThread:
    def __init__(self) -> None:
        self.started = _DummySignal()
        self.finished = _DummySignal()

    def start(self) -> None:
        return None

    def quit(self) -> None:
        return None

    def deleteLater(self) -> None:
        return None


def _configure_window(
    qtbot,
    tmp_path: Path,
    monkeypatch,
) -> tuple[plot_gui.PlotGeneratorWindow, dict[str, object]]:
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "project.json").write_text("{}", encoding="utf-8")

    win = plot_gui.PlotGeneratorWindow(project_dir=str(project_root))
    qtbot.addWidget(win)
    win.show()

    win.folder_edit.setText(str(tmp_path / "excel"))
    win.out_edit.setText(str(tmp_path / "out"))

    win.condition_combo.clear()
    win.condition_b_combo.clear()
    win.condition_combo.addItems(["CondA", "CondB"])
    win.condition_b_combo.addItems(["CondA", "CondB"])
    win.overlay_check.setChecked(True)
    win.condition_combo.setCurrentText("CondA")
    win.condition_b_combo.setCurrentText("CondB")
    win.setup_tabs.setCurrentIndex(1)

    captured: dict[str, object] = {}

    class DummyWorker:
        def __init__(self, *args, **kwargs):  # noqa: ANN001, ARG002
            captured["args"] = args
            captured["kwargs"] = kwargs
            self.progress = _DummySignal()
            self.finished = _DummySignal()

        def moveToThread(self, *args, **kwargs):  # noqa: ANN001, ARG002
            return None

    monkeypatch.setattr(plot_gui, "_Worker", DummyWorker, raising=False)
    monkeypatch.setattr(plot_gui, "QThread", _DummyThread)
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None, raising=False)

    return win, captured


@pytest.mark.qt
def test_custom_legend_labels_payload(qtbot, tmp_path, monkeypatch):
    win, captured = _configure_window(qtbot, tmp_path, monkeypatch)

    win.legend_custom_check.setChecked(True)
    win.legend_condition_a_edit.setText("Condition A")
    win.legend_condition_b_edit.setText("Condition B")
    win.legend_a_peaks_edit.setText("A Peaks")
    win.legend_b_peaks_edit.setText("B Peaks")

    win._generate()
    qtbot.waitUntil(lambda: "kwargs" in captured)

    kwargs = captured["kwargs"]
    assert kwargs["legend_custom_enabled"] is True
    assert kwargs["legend_condition_a"] == "Condition A"
    assert kwargs["legend_condition_b"] == "Condition B"
    assert kwargs["legend_a_peaks"] == "A Peaks"
    assert kwargs["legend_b_peaks"] == "B Peaks"


@pytest.mark.qt
def test_blank_custom_label_payload(qtbot, tmp_path, monkeypatch):
    win, captured = _configure_window(qtbot, tmp_path, monkeypatch)

    win.legend_custom_check.setChecked(True)
    win.legend_condition_a_edit.setText("")
    win.legend_condition_b_edit.setText("Condition B")
    win.legend_a_peaks_edit.setText("A Peaks")
    win.legend_b_peaks_edit.setText("B Peaks")

    win._generate()
    qtbot.waitUntil(lambda: "kwargs" in captured)

    kwargs = captured["kwargs"]
    assert kwargs["legend_custom_enabled"] is True
    assert kwargs["legend_condition_a"] == ""


@pytest.mark.qt
def test_reset_legend_defaults(qtbot, tmp_path, monkeypatch):
    win, _ = _configure_window(qtbot, tmp_path, monkeypatch)

    win.legend_custom_check.setChecked(True)
    for edit, text in (
        (win.legend_condition_a_edit, "Custom A"),
        (win.legend_condition_b_edit, "Custom B"),
        (win.legend_a_peaks_edit, "Custom A Peaks"),
        (win.legend_b_peaks_edit, "Custom B Peaks"),
    ):
        edit.clear()
        qtbot.keyClicks(edit, text)

    win.legend_reset_btn.click()

    assert win.legend_custom_check.isChecked() is True
    assert win.legend_condition_a_edit.isEnabled() is True
    assert win.legend_condition_b_edit.isEnabled() is True
    assert win.legend_a_peaks_edit.isEnabled() is True
    assert win.legend_b_peaks_edit.isEnabled() is True
    assert win.legend_condition_a_edit.text() == "CondA"
    assert win.legend_condition_b_edit.text() == "CondB"
    assert win.legend_a_peaks_edit.text() == "CondA Peaks"
    assert win.legend_b_peaks_edit.text() == "CondB Peaks"


@pytest.mark.qt
def test_legend_group_visibility_retains_values(qtbot, tmp_path, monkeypatch):
    win, _ = _configure_window(qtbot, tmp_path, monkeypatch)

    win.legend_custom_check.setChecked(True)
    for edit, text in (
        (win.legend_condition_a_edit, "Custom A"),
        (win.legend_condition_b_edit, "Custom B"),
        (win.legend_a_peaks_edit, "Custom A Peaks"),
        (win.legend_b_peaks_edit, "Custom B Peaks"),
    ):
        edit.clear()
        qtbot.keyClicks(edit, text)

    win.overlay_check.setChecked(False)
    qtbot.wait(50)
    assert win.legend_condition_b_edit.isVisible() is False
    assert win.legend_b_peaks_edit.isVisible() is False

    win.overlay_check.setChecked(True)
    qtbot.wait(50)
    assert win.legend_group.isVisible() is True
    assert win.legend_condition_b_edit.isVisible() is True
    assert win.legend_b_peaks_edit.isVisible() is True
    assert win.legend_condition_a_edit.text() == "Custom A"
    assert win.legend_condition_b_edit.text() == "Custom B"


@pytest.mark.qt
def test_legend_defaults_follow_condition_selection(qtbot, tmp_path, monkeypatch):
    win, _ = _configure_window(qtbot, tmp_path, monkeypatch)

    win.legend_custom_check.setChecked(True)
    assert win.legend_condition_a_edit.text() == "CondA"
    assert win.legend_condition_b_edit.text() == "CondB"
    assert win.legend_a_peaks_edit.text() == "CondA Peaks"
    assert win.legend_b_peaks_edit.text() == "CondB Peaks"

    win.condition_combo.setCurrentText("CondB")
    win.condition_b_combo.setCurrentText("CondA")
    qtbot.wait(50)

    assert win.legend_condition_a_edit.text() == "CondB"
    assert win.legend_condition_b_edit.text() == "CondA"
    assert win.legend_a_peaks_edit.text() == "CondB Peaks"
    assert win.legend_b_peaks_edit.text() == "CondA Peaks"


@pytest.mark.qt
def test_legend_peak_manual_override_is_preserved(qtbot, tmp_path, monkeypatch):
    win, _ = _configure_window(qtbot, tmp_path, monkeypatch)

    win.legend_custom_check.setChecked(True)
    win.legend_a_peaks_edit.clear()
    qtbot.keyClicks(win.legend_a_peaks_edit, "Manual A Peaks")

    win.condition_combo.setCurrentText("CondB")
    qtbot.wait(50)

    assert win.legend_condition_a_edit.text() == "CondB"
    assert win.legend_a_peaks_edit.text() == "Manual A Peaks"


def _set_five_conditions(win):
    conditions = [f"Cond{letter}" for letter in "ABCDE"]
    for index, combo in enumerate([win.condition_combo, win.condition_b_combo, *win.extra_condition_combos]):
        combo.clear()
        combo.addItems(conditions)
        combo.setCurrentIndex(index)
    win.overlay_count_spin.setValue(5)
    return conditions


@pytest.mark.qt
def test_five_condition_labels_colors_and_preflight_match_worker(qtbot, tmp_path, monkeypatch):
    win, captured = _configure_window(qtbot, tmp_path, monkeypatch)
    conditions = _set_five_conditions(win)
    win._legend_fields["condition_c_label"].clear()
    qtbot.keyClicks(win._legend_fields["condition_c_label"], "Custom C")
    assert win._legend_fields["c_peaks_label"].text() == "Custom C Peaks"
    win.extra_colors[:] = ["#118833", "#8844AA", "#AA7711"]
    title = " vs ".join(conditions)
    assert all(identity[0] == title for identity in win._export_identities())

    win._generate()
    qtbot.waitUntil(lambda: "kwargs" in captured)
    kwargs = captured["kwargs"]
    assert captured["args"][4] == title
    assert kwargs["extra_conditions"] == tuple(conditions[2:])
    assert kwargs["extra_colors"] == ("#118833", "#8844AA", "#AA7711")
    assert kwargs["legend_extra_conditions"] == ("Custom C", "CondD", "CondE")
    assert kwargs["legend_extra_peaks"] == ("Custom C Peaks", "CondD Peaks", "CondE Peaks")


@pytest.mark.qt
def test_extra_condition_defaults_overrides_and_hidden_rows(qtbot, tmp_path, monkeypatch):
    win, _ = _configure_window(qtbot, tmp_path, monkeypatch)
    _set_five_conditions(win)
    win.extra_condition_combos[0].setCurrentText("CondE")
    assert win._legend_fields["condition_c_label"].text() == "CondE"
    assert win._legend_fields["c_peaks_label"].text() == "CondE Peaks"
    win._legend_fields["condition_c_label"].clear()
    qtbot.keyClicks(win._legend_fields["condition_c_label"], "Saved label")
    win.extra_condition_combos[0].setCurrentText("CondC")
    assert win._legend_fields["condition_c_label"].text() == "Saved label"
    win._load_legend_settings()
    assert win._legend_fields["condition_c_label"].text() == "Saved label"

    win.overlay_count_spin.setValue(2)
    assert all(not widgets[1].isVisible() for widgets in win.extra_legend_widgets)
    assert win._extra_overlay_worker_kwargs()["extra_conditions"] == ()
    assert all(identity[0] == "CondA vs CondB" for identity in win._export_identities())
    win.overlay_count_spin.setValue(5)
    assert win._legend_fields["condition_c_label"].text() == "Saved label"
    win.legend_reset_btn.click()
    assert win._legend_fields["condition_c_label"].text() == "CondC"
    assert win._legend_fields["c_peaks_label"].text() == "CondC Peaks"
    win.legend_custom_check.setChecked(False)
    assert all(not field.isEnabled() for field in win._legend_fields.values())


@pytest.mark.qt
@pytest.mark.parametrize("custom", [False, True])
def test_extra_labels_follow_selection_after_project_reopen(qtbot, tmp_path, monkeypatch, custom):
    win, _ = _configure_window(qtbot, tmp_path, monkeypatch)
    _set_five_conditions(win)
    win.extra_condition_combos[0].setCurrentText("CondE")
    if custom:
        win._legend_fields["condition_c_label"].clear()
        qtbot.keyClicks(win._legend_fields["condition_c_label"], "Keep custom C")
    win._persist_legend_settings()

    reopened = plot_gui.PlotGeneratorWindow(project_dir=str(tmp_path / "project"))
    qtbot.addWidget(reopened)
    _set_five_conditions(reopened)
    expected = "Keep custom C" if custom else "CondC"
    assert reopened._legend_fields["condition_c_label"].text() == expected
    assert reopened._legend_fields["c_peaks_label"].text() == f"{expected} Peaks"
    reopened.extra_condition_combos[0].setCurrentText("CondD")
    expected = "Keep custom C" if custom else "CondD"
    assert reopened._legend_fields["condition_c_label"].text() == expected
    assert reopened._legend_fields["c_peaks_label"].text() == f"{expected} Peaks"
