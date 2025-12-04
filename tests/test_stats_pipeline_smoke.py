import pytest

pd = pytest.importorskip("pandas")

try:
    from PySide6.QtCore import Qt
    from Tools.Stats.PySide6.stats_controller import PipelineId
    from Tools.Stats.PySide6.stats_ui_pyside6 import StatsWindow
    from Tools.Stats.PySide6 import stats_workers
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    pytest.skip("PySide6 is required for Stats pipeline smoke tests", allow_module_level=True)


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

    def fake_posthoc(*_args, **_kwargs):
        return {"results_df": dummy_df.copy(), "output_text": "posthoc"}

    def fake_contrasts(*_args, **_kwargs):
        return {"results_df": dummy_df.copy(), "output_text": "contrasts"}

    monkeypatch.setattr(stats_workers, "run_rm_anova", fake_rm_anova, raising=False)
    monkeypatch.setattr(stats_workers, "run_lmm", fake_lmm, raising=False)
    monkeypatch.setattr(stats_workers, "run_posthoc", fake_posthoc, raising=False)
    monkeypatch.setattr(stats_workers, "run_between_group_anova", fake_rm_anova, raising=False)
    monkeypatch.setattr(stats_workers, "run_group_contrasts", fake_contrasts, raising=False)
    return dummy_df


@pytest.fixture
def synced_window(monkeypatch, qtbot, tmp_path, patched_workers):
    def ready_stub(self, pipeline_id, *, require_anova=False):
        self._current_base_freq = 6.0
        self._current_alpha = 0.05
        return True

    def start_immediate(self, pipeline_id, step, *, finished_cb, error_cb):
        try:
            payload = step.worker_fn(lambda *_a, **_k: None, lambda *_a, **_k: None, **step.kwargs)
        except Exception as exc:  # noqa: BLE001
            error_cb(pipeline_id, step.id, str(exc))
        else:
            finished_cb(pipeline_id, step.id, payload or {})

    monkeypatch.setattr(StatsWindow, "ensure_pipeline_ready", ready_stub, raising=False)
    monkeypatch.setattr(StatsWindow, "start_step_worker", start_immediate, raising=False)
    monkeypatch.setattr(StatsWindow, "export_pipeline_results", lambda self, pid: True, raising=False)
    monkeypatch.setattr(StatsWindow, "build_and_render_summary", lambda self, pid: None, raising=False)

    win = StatsWindow(project_dir=str(tmp_path))
    qtbot.addWidget(win)
    return win


@pytest.mark.qt
def test_single_pipeline_completes_and_logs(qtbot, synced_window):
    synced_window.subjects = ["S1"]
    synced_window.conditions = ["C1"]
    synced_window.subject_groups = {"S1": "G1"}
    synced_window.subject_data = {"S1": {"C1": {"ROI": 1.0}}}
    synced_window.rois = {"ROI": ["Cz"]}

    qtbot.mouseClick(synced_window.analyze_single_btn, Qt.LeftButton)

    qtbot.waitUntil(lambda: synced_window.analyze_single_btn.isEnabled(), timeout=2000)
    qtbot.waitUntil(
        lambda: "Single-Group Analysis finished" in synced_window.output_text.toPlainText(), timeout=2000
    )
    assert not synced_window._controller.is_running(PipelineId.SINGLE)


@pytest.mark.qt
def test_between_pipeline_completes_and_logs(qtbot, synced_window):
    synced_window.subjects = ["S1", "S2"]
    synced_window.conditions = ["C1"]
    synced_window.subject_groups = {"S1": "G1", "S2": "G2"}
    synced_window.subject_data = {
        "S1": {"C1": {"ROI": 1.0}},
        "S2": {"C1": {"ROI": 2.0}},
    }
    synced_window.rois = {"ROI": ["Cz"]}

    qtbot.mouseClick(synced_window.analyze_between_btn, Qt.LeftButton)

    qtbot.waitUntil(lambda: synced_window.analyze_between_btn.isEnabled(), timeout=2000)
    qtbot.waitUntil(
        lambda: "Between-Group Analysis finished" in synced_window.output_text.toPlainText(), timeout=2000
    )
    assert not synced_window._controller.is_running(PipelineId.BETWEEN)
