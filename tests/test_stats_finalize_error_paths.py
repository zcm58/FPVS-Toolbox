import logging
import os

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pandas")
pytest.importorskip("statsmodels")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pandas as pd
from PySide6.QtCore import Qt

from Tools.Stats.PySide6 import stats_workers
from Tools.Stats.PySide6.stats_core import PipelineId
from Tools.Stats.PySide6.stats_ui_pyside6 import StatsWindow


@pytest.fixture(autouse=True)
def _stub_default_loader(monkeypatch):
    monkeypatch.setattr(StatsWindow, "_load_default_data_folder", lambda self: None, raising=False)


@pytest.fixture
def patched_workers(monkeypatch):
    dummy_df = pd.DataFrame({"Effect": ["roi"], "Pr > F": [0.5]})

    def fake_rm_anova(*_args, **_kwargs):
        return {"anova_df_results": dummy_df.copy(), "output_text": "rm"}

    def fake_lmm(*_args, **_kwargs):
        return {"mixed_results_df": dummy_df.copy(), "output_text": "lmm"}

    def fake_contrasts(*_args, **_kwargs):
        return {"results_df": dummy_df.copy(), "output_text": "contrasts"}

    monkeypatch.setattr(stats_workers, "run_rm_anova", fake_rm_anova, raising=False)
    monkeypatch.setattr(stats_workers, "run_lmm", fake_lmm, raising=False)
    monkeypatch.setattr(stats_workers, "run_between_group_anova", fake_rm_anova, raising=False)
    monkeypatch.setattr(stats_workers, "run_group_contrasts", fake_contrasts, raising=False)
    return dummy_df


@pytest.fixture
def fast_window(monkeypatch, qtbot, tmp_path, patched_workers):
    def ready_stub(self, pipeline_id, *, require_anova=False):
        self._current_base_freq = 6.0
        self._current_alpha = 0.05
        return True

    def start_immediate(self, pipeline_id, step, *, finished_cb, error_cb):
        finished_cb(pipeline_id, step.id, {})

    def fake_get_step_config(self, pipeline_id, step_id):  # noqa: ARG001
        return {}, lambda payload: None

    monkeypatch.setattr(StatsWindow, "ensure_pipeline_ready", ready_stub, raising=False)
    monkeypatch.setattr(StatsWindow, "start_step_worker", start_immediate, raising=False)
    monkeypatch.setattr(StatsWindow, "export_pipeline_results", lambda self, pid: True, raising=False)
    monkeypatch.setattr(StatsWindow, "build_and_render_summary", lambda self, pid: None, raising=False)
    monkeypatch.setattr(StatsWindow, "get_step_config", fake_get_step_config, raising=False)
    monkeypatch.setattr("PySide6.QtWidgets.QMessageBox.critical", lambda *_, **__: None, raising=False)

    win = StatsWindow(project_dir=str(tmp_path))
    qtbot.addWidget(win)
    return win


def _prime_between_inputs(window: StatsWindow) -> None:
    window.subjects = ["S1", "S2"]
    window.conditions = ["C1"]
    window.subject_groups = {"S1": "G1", "S2": "G2"}
    window.subject_data = {"S1": {"C1": {"ROI": 1.0}}, "S2": {"C1": {"ROI": 2.0}}}
    window.rois = {"ROI": ["Cz"]}


@pytest.mark.qt
def test_complete_pipeline_recovers_from_summary_error(qtbot, fast_window, monkeypatch):
    _prime_between_inputs(fast_window)

    def boom_summary(self, pid):
        raise RuntimeError("summary boom")

    monkeypatch.setattr(StatsWindow, "build_and_render_summary", boom_summary, raising=False)

    qtbot.mouseClick(fast_window.analyze_between_btn, Qt.LeftButton)

    qtbot.waitUntil(lambda: fast_window.analyze_between_btn.isEnabled(), timeout=2000)

    assert not fast_window._controller.is_running(PipelineId.BETWEEN)
    assert "Error during finalization" in fast_window.output_text.toPlainText()
    assert fast_window.analyze_between_btn.isEnabled()


@pytest.mark.qt
def test_finalize_handles_view_errors(qtbot, fast_window, monkeypatch, caplog):
    _prime_between_inputs(fast_window)

    def boom_finished(self, *args, **kwargs):  # noqa: ANN002, ANN003
        raise RuntimeError("view boom")

    monkeypatch.setattr(StatsWindow, "on_analysis_finished", boom_finished, raising=False)
    caplog.set_level(logging.ERROR)

    qtbot.mouseClick(fast_window.analyze_between_btn, Qt.LeftButton)

    qtbot.waitUntil(lambda: fast_window.analyze_between_btn.isEnabled(), timeout=2000)

    assert fast_window.analyze_between_btn.isEnabled()
    assert any("stats_finalize_view_error" in rec.message for rec in caplog.records)
