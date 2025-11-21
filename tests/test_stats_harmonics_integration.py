"""Integration coverage for harmonic checks within the Stats pipelines."""

import pytest

import pandas as pd

try:
    from PySide6.QtCore import Qt
    from Tools.Stats.PySide6.stats_main_window import HarmonicConfig
    from Tools.Stats.PySide6.stats_ui_pyside6 import StatsWindow
    from Tools.Stats.PySide6 import stats_workers
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    pytest.skip("PySide6 is required for harmonic integration tests", allow_module_level=True)


@pytest.fixture(autouse=True)
def _stub_default_loader(monkeypatch):
    monkeypatch.setattr(StatsWindow, "_load_default_data_folder", lambda self: None, raising=False)


@pytest.fixture
def harmonic_calls():
    return []


@pytest.fixture
def patched_workers(monkeypatch, harmonic_calls):
    dummy_df = pd.DataFrame({"Effect": ["roi"], "Pr > F": [0.5]})

    def fake_rm_anova(*_args, **_kwargs):
        return {"anova_df_results": dummy_df.copy(), "output_text": "rm"}

    def fake_lmm(*_args, **_kwargs):
        return {"mixed_results_df": dummy_df.copy(), "output_text": "lmm"}

    def fake_posthoc(*_args, **_kwargs):
        return {"results_df": dummy_df.copy(), "output_text": "posthoc"}

    def fake_contrasts(*_args, **_kwargs):
        return {"results_df": dummy_df.copy(), "output_text": "contrasts"}

    def fake_harmonic(_progress_cb, _message_cb, **kwargs):
        harmonic_calls.append(kwargs)
        return {
            "output_text": "harmonic output",
            "findings": [
                {
                    "ROI": "O1",
                    "Condition": "C1",
                    "is_significant": True,
                    "p_fdr": 0.01,
                    "effect_size": 0.6,
                }
            ],
        }

    monkeypatch.setattr(stats_workers, "run_rm_anova", fake_rm_anova, raising=False)
    monkeypatch.setattr(stats_workers, "run_lmm", fake_lmm, raising=False)
    monkeypatch.setattr(stats_workers, "run_posthoc", fake_posthoc, raising=False)
    monkeypatch.setattr(stats_workers, "run_between_group_anova", fake_rm_anova, raising=False)
    monkeypatch.setattr(stats_workers, "run_group_contrasts", fake_contrasts, raising=False)
    monkeypatch.setattr(stats_workers, "run_harmonic_check", fake_harmonic, raising=False)
    return dummy_df


@pytest.fixture
def synced_window(monkeypatch, qtbot, tmp_path, patched_workers, harmonic_calls):
    export_calls: list[str] = []

    def ready_stub(self, pipeline_id, *, require_anova=False):
        self._current_base_freq = 6.0
        self._current_alpha = 0.05
        self._harmonic_config = HarmonicConfig("Z Score", 1.64)
        return True

    def start_immediate(self, pipeline_id, step, *, finished_cb, error_cb):
        try:
            payload = step.worker_fn(lambda *_a, **_k: None, lambda *_a, **_k: None, **step.kwargs)
        except Exception as exc:  # noqa: BLE001
            error_cb(pipeline_id, step.id, str(exc))
        else:
            finished_cb(pipeline_id, step.id, payload or {})

    def export_stub(self, kind, data, out_dir):
        export_calls.append(kind)

    monkeypatch.setattr(StatsWindow, "ensure_pipeline_ready", ready_stub, raising=False)
    monkeypatch.setattr(StatsWindow, "start_step_worker", start_immediate, raising=False)
    monkeypatch.setattr(StatsWindow, "export_results", export_stub, raising=False)

    win = StatsWindow(project_dir=str(tmp_path))
    qtbot.addWidget(win)
    return win, export_calls, harmonic_calls


@pytest.mark.qt
def test_single_pipeline_runs_harmonics_and_exports(qtbot, synced_window):
    win, export_calls, harmonic_calls = synced_window
    win.subjects = ["S1"]
    win.conditions = ["C1"]
    win.subject_groups = {"S1": "G1"}
    win.subject_data = {"S1": {"C1": {"ROI": 1.0}}}
    win.rois = {"ROI": ["Cz"]}

    qtbot.mouseClick(win.analyze_single_btn, Qt.LeftButton)

    qtbot.waitUntil(lambda: win.analyze_single_btn.isEnabled(), timeout=2000)
    qtbot.waitUntil(
        lambda: "Single-Group Analysis finished" in win.output_text.toPlainText(), timeout=2000
    )

    assert any(call.get("selected_metric") == "Z Score" for call in harmonic_calls)
    assert "harmonic" in export_calls
    text = win.output_text.toPlainText()
    assert "Harmonic Check completed" in text
    assert "Significant responses" in text


@pytest.mark.qt
def test_between_pipeline_runs_harmonics_and_exports(qtbot, synced_window):
    win, export_calls, harmonic_calls = synced_window
    win.subjects = ["S1", "S2"]
    win.conditions = ["C1"]
    win.subject_groups = {"S1": "G1", "S2": "G2"}
    win.subject_data = {"S1": {"C1": {"ROI": 1.0}}, "S2": {"C1": {"ROI": 2.0}}}
    win.rois = {"ROI": ["Cz"]}

    qtbot.mouseClick(win.analyze_between_btn, Qt.LeftButton)

    qtbot.waitUntil(lambda: win.analyze_between_btn.isEnabled(), timeout=2000)
    qtbot.waitUntil(
        lambda: "Between-Group Analysis finished" in win.output_text.toPlainText(), timeout=2000
    )

    assert any(call.get("selected_metric") == "Z Score" for call in harmonic_calls)
    assert export_calls.count("harmonic") >= 1
    text = win.output_text.toPlainText()
    assert "Harmonic Check completed" in text
