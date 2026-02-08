from __future__ import annotations

import importlib.util
import os
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

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

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

    win.folder_edit.setText(str(tmp_path / "excel"))
    win.out_edit.setText(str(tmp_path / "out"))

    win.condition_combo.clear()
    win.condition_b_combo.clear()
    win.condition_combo.addItems(["CondA", "CondB"])
    win.condition_b_combo.addItems(["CondA", "CondB"])
    win.overlay_check.setChecked(True)
    win.condition_combo.setCurrentText("CondA")
    win.condition_b_combo.setCurrentText("CondB")

    captured: dict[str, object] = {}

    class DummyWorker:
        def __init__(self, *args, **kwargs):  # noqa: ANN001, ARG002
            captured["args"] = args
            captured["kwargs"] = kwargs
            self.progress = _DummySignal()
            self.finished = _DummySignal()

        def moveToThread(self, *args, **kwargs):  # noqa: ANN001, ARG002
            return None

    monkeypatch.setattr(plot_gui, "_Worker", DummyWorker)
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

    kwargs = captured["kwargs"]
    assert kwargs["legend_custom_enabled"] is True
    assert kwargs["legend_condition_a"] == ""


@pytest.mark.qt
def test_reset_legend_defaults(qtbot, tmp_path, monkeypatch):
    win, _ = _configure_window(qtbot, tmp_path, monkeypatch)

    win.legend_custom_check.setChecked(True)
    win.legend_condition_a_edit.setText("Custom A")
    win.legend_condition_b_edit.setText("Custom B")
    win.legend_a_peaks_edit.setText("Custom A Peaks")
    win.legend_b_peaks_edit.setText("Custom B Peaks")

    win.legend_reset_btn.click()

    assert win.legend_custom_check.isChecked() is False
    assert win.legend_condition_a_edit.isEnabled() is False
    assert win.legend_condition_b_edit.isEnabled() is False
    assert win.legend_a_peaks_edit.isEnabled() is False
    assert win.legend_b_peaks_edit.isEnabled() is False
    assert win.legend_condition_a_edit.text() == "CondA"
    assert win.legend_condition_b_edit.text() == "CondB"
    assert win.legend_a_peaks_edit.text() == "A-Peaks"
    assert win.legend_b_peaks_edit.text() == "B-Peaks"


@pytest.mark.qt
def test_legend_group_visibility_retains_values(qtbot, tmp_path, monkeypatch):
    win, _ = _configure_window(qtbot, tmp_path, monkeypatch)

    win.legend_custom_check.setChecked(True)
    win.legend_condition_a_edit.setText("Custom A")
    win.legend_condition_b_edit.setText("Custom B")
    win.legend_a_peaks_edit.setText("Custom A Peaks")
    win.legend_b_peaks_edit.setText("Custom B Peaks")

    win.overlay_check.setChecked(False)
    assert win.legend_group.isVisible() is False

    win.overlay_check.setChecked(True)
    assert win.legend_group.isVisible() is True
    assert win.legend_condition_a_edit.text() == "Custom A"
    assert win.legend_condition_b_edit.text() == "Custom B"
