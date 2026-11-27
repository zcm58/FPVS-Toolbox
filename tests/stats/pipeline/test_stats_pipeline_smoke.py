import threading
from types import SimpleNamespace

import pytest

pd = pytest.importorskip("pandas")

try:
    from PySide6.QtCore import Qt, QThreadPool, QTimer
    from PySide6.QtWidgets import QProgressDialog, QPushButton, QWidget
    from Tools.Stats.ui import stats_window_exclusions
    from Tools.Stats.ui.stats_window_exclusions import StatsWindowExclusionsMixin
    from Tools.Stats.analysis.prepared_analysis import prepare_analysis_payload
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

    def fake_prepare(*_args, **kwargs):
        prepared = prepare_analysis_payload(
            pd.DataFrame(
                [
                    {
                        "subject": "S1",
                        "condition": "C1",
                        "roi": "ROI",
                        "value": 1.0,
                    }
                ]
            ),
            mode=kwargs["mode"],
            run_spec=kwargs["run_spec"],
            dv_col="value",
            subject_col="subject",
            condition_col="condition",
            roi_col="roi",
            frozen_participants=("S1",),
            selected_conditions=("C1",),
            selected_rois=("ROI",),
            analysis_scope=kwargs["analysis_scope"],
            preparation_id="single-pipeline-smoke",
        )
        return {"prepared_payload": prepared}

    def fake_report(*_args, **_kwargs):
        return {"exported": True, "report_text": "screening complete"}

    monkeypatch.setattr(stats_workers, "run_rm_anova", fake_rm_anova, raising=False)
    monkeypatch.setattr(stats_workers, "run_lmm", fake_lmm, raising=False)
    monkeypatch.setattr(stats_workers, "run_posthoc", fake_posthoc, raising=False)
    monkeypatch.setattr(stats_workers, "run_baseline_vs_zero", fake_baseline, raising=False)
    monkeypatch.setitem(WORKER_FN_BY_STEP, StepId.RM_ANOVA, fake_rm_anova)
    monkeypatch.setitem(WORKER_FN_BY_STEP, StepId.MIXED_MODEL, fake_lmm)
    monkeypatch.setitem(WORKER_FN_BY_STEP, StepId.INTERACTION_POSTHOCS, fake_posthoc)
    monkeypatch.setitem(WORKER_FN_BY_STEP, StepId.BASELINE_VS_ZERO, fake_baseline)
    monkeypatch.setitem(WORKER_FN_BY_STEP, StepId.PREPARE_ANALYSIS, fake_prepare)
    monkeypatch.setitem(WORKER_FN_BY_STEP, StepId.REPORT_BUNDLE, fake_report)
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


@pytest.mark.qt
@pytest.mark.parametrize("outcome", ["success", "failure", "cancel"])
def test_screening_harmonic_check_keeps_events_running(
    outcome, qtbot, tmp_path, monkeypatch
) -> None:
    (tmp_path / "project.json").write_text("{}", encoding="utf-8")
    selection = object()
    gui_thread = threading.get_ident()
    checking = threading.Event()
    release = threading.Event()
    event_ticks = []
    reads = []

    class Host(QWidget, StatsWindowExclusionsMixin):
        project_dir = tmp_path

        def _apply_canonical_harmonic_selection(self, result):
            assert threading.get_ident() == gui_thread
            assert result is selection
            return {"accepted": True}

    def validate(path):
        assert path == tmp_path
        assert threading.get_ident() != gui_thread
        reads.append(path)
        checking.set()
        if not release.wait(4):
            raise RuntimeError("GUI failed to process events during validation")
        if outcome == "failure":
            raise ValueError("changed source")
        return selection

    win = Host()
    qtbot.addWidget(win)
    win.pool = QThreadPool(win)
    monkeypatch.setattr(stats_window_exclusions, "_load_project_selection", validate)
    win._refresh_canonical_harmonic_summary()

    def tick():
        if checking.is_set():
            event_ticks.append(True)
            timer.stop()
            if outcome == "cancel":
                win.findChild(QProgressDialog).findChild(QPushButton).click()
            else:
                release.set()

    timer = QTimer(win)
    timer.timeout.connect(tick)
    timer.start(10)
    try:
        if outcome == "failure":
            with pytest.raises(RuntimeError, match="changed source"):
                win._check_run_dv_policy()
        elif outcome == "success":
            assert win._check_run_dv_policy() == {"accepted": True}
        else:
            assert win._check_run_dv_policy() is None
        assert event_ticks
        assert reads == [tmp_path]
    finally:
        release.set()
        assert win.pool.waitForDone(5000)


@pytest.mark.qt
def test_late_harmonic_previews_ignore_project_switch_and_close(qtbot, tmp_path, monkeypatch):
    roots = [tmp_path / name for name in ("first", "second")]
    for path in roots:
        path.mkdir()
        (path / "project.json").write_text("{}", encoding="utf-8")
    win = StatsWindow(project_dir=str(roots[0]))
    qtbot.addWidget(win)
    queued = []
    applied = []
    win.pool = SimpleNamespace(start=queued.append)
    monkeypatch.setattr(win, "_apply_canonical_harmonic_selection", applied.append)

    win.show()
    first = win._harmonic_check
    win.rebind_project_context(roots[1])
    second = win._harmonic_check
    assert len(queued) == 2
    with qtbot.waitSignal(first.finished):
        queued[0].signals.finished.emit({"selection": "old project"})
    win.close()
    with qtbot.waitSignal(second.finished):
        queued[1].signals.finished.emit({"selection": "closed window"})
    assert applied == []

    win.show()
    assert len(queued) == 3
    with qtbot.waitSignal(win._harmonic_check.finished):
        queued[2].signals.finished.emit({"selection": "current project"})
    assert applied == ["current project"]
