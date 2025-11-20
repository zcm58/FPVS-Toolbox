from __future__ import annotations

import pytest
pytest.importorskip("PySide6")
from PySide6.QtCore import Qt

from Tools.Stats.PySide6 import stats_ui_pyside6 as stats_mod
from Tools.Stats.PySide6.stats_ui_pyside6 import StatsWindow
from Tools.Stats.PySide6.stats_worker import StatsWorker


@pytest.fixture
def app(qapp):
    """Ensure a QApplication exists for qtbot interactions."""
    return qapp


@pytest.fixture(autouse=True)
def patch_pipeline_workers(monkeypatch):
    def stub_worker(_progress_emit, _message_emit, *args, **kwargs):
        return {}

    for name in [
        "_rm_anova_calc",
        "_lmm_calc",
        "_posthoc_calc",
        "_between_group_anova_calc",
        "_group_contrasts_calc",
    ]:
        monkeypatch.setattr(stats_mod, name, stub_worker)

    def fast_run(self):  # pragma: no cover - invoked by Qt thread pool
        self.signals.progress.emit(100)
        self.signals.finished.emit({})

    monkeypatch.setattr(StatsWorker, "run", fast_run, raising=False)


def _prepare_window(win: StatsWindow, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(win, "refresh_rois", lambda: setattr(win, "rois", {"ROI": ["Cz"]}), raising=False)
    monkeypatch.setattr(win, "_get_analysis_settings", lambda: (6.0, 0.05), raising=False)
    monkeypatch.setattr(win, "_check_for_open_excel_files", lambda _folder: False, raising=False)


@pytest.mark.qt
def test_single_group_run_smoke(qtbot, tmp_path, monkeypatch, app):
    win = StatsWindow(project_dir=str(tmp_path))
    qtbot.addWidget(win)
    win.show()

    _prepare_window(win, monkeypatch)
    win.subject_data = {"S1": {"CondA": {"ROI": 1.0}}}
    win.subjects = ["S1"]
    win.conditions = ["CondA"]
    win.subject_groups = {"S1": None}

    qtbot.mouseClick(win.analyze_single_btn, Qt.LeftButton)

    qtbot.waitUntil(lambda: win.analyze_single_btn.isEnabled(), timeout=5000)
    qtbot.waitUntil(lambda: not win.spinner.isVisible(), timeout=5000)

    log_text = win.output_text.toPlainText()
    assert "Single Group Analysis" in log_text or "Single" in log_text


@pytest.mark.qt
def test_between_group_run_smoke(qtbot, tmp_path, monkeypatch, app):
    win = StatsWindow(project_dir=str(tmp_path))
    qtbot.addWidget(win)
    win.show()

    _prepare_window(win, monkeypatch)
    win.subject_data = {
        "S1": {"CondA": {"ROI": 1.0}},
        "S2": {"CondA": {"ROI": 2.0}},
    }
    win.subjects = ["S1", "S2"]
    win.conditions = ["CondA"]
    win.subject_groups = {"S1": "G1", "S2": "G2"}

    qtbot.mouseClick(win.analyze_between_btn, Qt.LeftButton)

    qtbot.waitUntil(lambda: win.analyze_between_btn.isEnabled(), timeout=5000)
    qtbot.waitUntil(lambda: not win.spinner.isVisible(), timeout=5000)

    log_text = win.output_text.toPlainText()
    assert "Between-Group" in log_text or "Between" in log_text
