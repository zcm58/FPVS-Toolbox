import pytest

pd = pytest.importorskip("pandas")

try:
    from PySide6.QtCore import Qt
    from Tools.Stats.controller.stats_controller import PipelineId, StepId, WORKER_FN_BY_STEP
    from Tools.Stats.ui.stats_window import StatsWindow
    from Tools.Stats.workers import stats_workers
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    pytest.skip("PySide6 is required for Stats pipeline smoke tests", allow_module_level=True)


@pytest.fixture(autouse=True)
def _stub_default_loader(monkeypatch):
    monkeypatch.setattr(StatsWindow, "_load_default_data_folder", lambda self: None, raising=False)
    monkeypatch.setattr(StatsWindow, "refresh_rois", lambda self: setattr(self, "rois", {"ROI": ["Cz"]}), raising=False)
    monkeypatch.setattr(
        "Tools.Stats.ui.stats_window_pipeline.load_rois_from_settings",
        lambda: {"ROI": ["Cz"]},
        raising=False,
    )


@pytest.fixture
def patched_workers(monkeypatch):
    dummy_df = pd.DataFrame({"Effect": ["roi"], "Pr > F": [0.5]})

    def fake_rm_anova(*_args, **_kwargs):
        return {"anova_df_results": dummy_df.copy(), "output_text": "rm"}

    def fake_lmm(*_args, **_kwargs):
        return {"mixed_results_df": dummy_df.copy(), "output_text": "lmm"}

    def fake_posthoc(*_args, **_kwargs):
        return {"results_df": dummy_df.copy(), "output_text": "posthoc"}

    def fake_baseline(*_args, **_kwargs):
        return {"results_df": dummy_df.copy(), "output_text": "baseline"}

    def fake_harmonic(*_args, **_kwargs):
        return {"harmonic_results": [], "output_text": "harmonic"}

    monkeypatch.setattr(stats_workers, "run_rm_anova", fake_rm_anova, raising=False)
    monkeypatch.setattr(stats_workers, "run_lmm", fake_lmm, raising=False)
    monkeypatch.setattr(stats_workers, "run_posthoc", fake_posthoc, raising=False)
    monkeypatch.setattr(stats_workers, "run_baseline_vs_zero", fake_baseline, raising=False)
    monkeypatch.setattr(stats_workers, "run_harmonic_check", fake_harmonic, raising=False)
    monkeypatch.setitem(WORKER_FN_BY_STEP, StepId.RM_ANOVA, fake_rm_anova)
    monkeypatch.setitem(WORKER_FN_BY_STEP, StepId.MIXED_MODEL, fake_lmm)
    monkeypatch.setitem(WORKER_FN_BY_STEP, StepId.INTERACTION_POSTHOCS, fake_posthoc)
    monkeypatch.setitem(WORKER_FN_BY_STEP, StepId.BASELINE_VS_ZERO, fake_baseline)
    monkeypatch.setitem(WORKER_FN_BY_STEP, StepId.HARMONIC_CHECK, fake_harmonic)
    return dummy_df


@pytest.fixture
def synced_window(monkeypatch, qtbot, tmp_path, patched_workers):
    def ready_stub(self, pipeline_id, *, require_anova=False):
        self._current_base_freq = 6.0
        self._current_alpha = 0.05
        return True

    def start_immediate(self, pipeline_id, step, *, finished_cb, error_cb, message_cb=None):
        try:
            payload = step.worker_fn(
                lambda *_a, **_k: None,
                message_cb or (lambda *_a, **_k: None),
                **step.kwargs,
            )
        except Exception as exc:  # noqa: BLE001
            error_cb(pipeline_id, step.id, str(exc))
        else:
            finished_cb(pipeline_id, step.id, payload or {})

    monkeypatch.setattr(StatsWindow, "ensure_pipeline_ready", ready_stub, raising=False)
    monkeypatch.setattr(StatsWindow, "start_step_worker", start_immediate, raising=False)
    monkeypatch.setattr(StatsWindow, "export_pipeline_results", lambda self, pid: True, raising=False)
    monkeypatch.setattr(StatsWindow, "build_and_render_summary", lambda self, pid: None, raising=False)
    monkeypatch.setattr(StatsWindow, "_start_reporting_summary_worker", lambda self, pid, elapsed_ms: None, raising=False)
    monkeypatch.setattr(StatsWindow, "_show_outlier_exclusion_dialog", lambda self, pid: None, raising=False)

    win = StatsWindow(project_dir=str(tmp_path))
    qtbot.addWidget(win)
    return win


@pytest.mark.qt
def test_single_pipeline_completes_and_logs(qtbot, synced_window):
    synced_window.subjects = ["S1"]
    synced_window.conditions = ["C1"]
    synced_window.subject_data = {"S1": {"C1": {"ROI": 1.0}}}
    synced_window.rois = {"ROI": ["Cz"]}

    qtbot.mouseClick(synced_window.analyze_single_btn, Qt.LeftButton)

    qtbot.waitUntil(lambda: synced_window.analyze_single_btn.isEnabled(), timeout=2000)
    qtbot.waitUntil(
        lambda: "Single-Group Analysis finished" in synced_window.output_text.toPlainText(), timeout=2000
    )
    assert not synced_window._controller.is_running(PipelineId.SINGLE)
