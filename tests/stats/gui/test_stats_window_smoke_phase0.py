from __future__ import annotations

from pathlib import Path

import pytest
pytest.importorskip("PySide6")
from PySide6.QtCore import Qt

from Tools.Stats.ui import stats_window as stats_mod
from Tools.Stats.ui.stats_window import StatsWindow
from Tools.Stats.workers.stats_workers import StatsWorker


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


def _project_dir(name: str) -> Path:
    path = Path.cwd() / ".codex-tmp" / name
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.mark.qt
def test_single_group_run_smoke(qtbot, monkeypatch, app):
    win = StatsWindow(project_dir=str(_project_dir("single-group-run-smoke")))
    qtbot.addWidget(win)
    _prepare_window(win, monkeypatch)
    captured: list[dict] = []

    monkeypatch.setattr(
        win._controller,
        "run_single_group_analysis",
        lambda **kwargs: captured.append(kwargs),
        raising=False,
    )

    qtbot.mouseClick(win.analyze_single_btn, Qt.LeftButton)

    assert captured == [{}]


@pytest.mark.qt
def test_single_group_advanced_actions_keep_anova_and_lmm(qtbot, monkeypatch, app):
    win = StatsWindow(project_dir=str(_project_dir("single-group-advanced-actions")))
    qtbot.addWidget(win)
    _prepare_window(win, monkeypatch)
    captured = {}

    monkeypatch.setattr(
        StatsWindow,
        "_open_advanced_dialog",
        lambda self, title, actions: captured.update(title=title, actions=actions),
        raising=False,
    )

    win.on_single_advanced_clicked()

    labels = [label for label, _cb, _enabled in captured["actions"]]
    assert "Run RM-ANOVA" in labels
    assert "Run Mixed Model" in labels
