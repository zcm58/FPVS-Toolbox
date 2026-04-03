import pytest

try:
    import pandas as pd
    from PySide6.QtCore import Qt

    from Tools.Stats.PySide6 import stats_workers
    from Tools.Stats.PySide6.stats_controller import (
        PipelineId,
        StepId,
        WORKER_FN_BY_STEP,
    )
    from Tools.Stats.PySide6.stats_ui_pyside6 import StatsWindow
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    pytest.skip("PySide6 is required for Stats mixed model tests", allow_module_level=True)


@pytest.fixture(autouse=True)
def _stub_default_loader(monkeypatch):
    monkeypatch.setattr(StatsWindow, "_load_default_data_folder", lambda self: None, raising=False)


def _make_immediate_worker(monkeypatch, seen_steps=None):
    def ready_stub(self, pipeline_id, *, require_anova=False):
        self._current_base_freq = 6.0
        self._current_alpha = 0.05
        return True

    def start_immediate(self, pipeline_id, step, *, finished_cb, error_cb):
        if isinstance(seen_steps, list):
            seen_steps.append(step.id)
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


def _prime_between_subjects(window: StatsWindow) -> None:
    window.subjects = ["S1", "S2"]
    window.conditions = ["C1"]
    window.subject_groups = {"S1": "G1", "S2": "G2"}
    window.subject_data = {"S1": {"C1": {"ROI": 1.0}}, "S2": {"C1": {"ROI": 2.0}}}
    window.rois = {"ROI": ["Cz"]}


def _patch_between_workers(monkeypatch, *, lmm_fn, contrasts_fn) -> None:
    monkeypatch.setattr(stats_workers, "run_lmm", lmm_fn, raising=False)
    monkeypatch.setattr(stats_workers, "run_group_contrasts", contrasts_fn, raising=False)
    monkeypatch.setitem(WORKER_FN_BY_STEP, StepId.BETWEEN_GROUP_MIXED_MODEL, lmm_fn)
    monkeypatch.setitem(WORKER_FN_BY_STEP, StepId.GROUP_CONTRASTS, contrasts_fn)


@pytest.mark.qt
def test_between_mixed_model_valid_payload_advances(monkeypatch, qtbot, tmp_path):
    seen_steps = []
    _make_immediate_worker(monkeypatch, seen_steps)

    dummy_df = pd.DataFrame({"value": [1.0, 2.0, 3.0]})

    _patch_between_workers(
        monkeypatch,
        lmm_fn=lambda *_a, **_k: {
            "mixed_results_df": dummy_df.copy(),
            "output_text": "ok",
        },
        contrasts_fn=lambda *_a, **_k: {"results_df": dummy_df.copy(), "output_text": "contrasts"},
    )

    win = StatsWindow(project_dir=str(tmp_path))
    qtbot.addWidget(win)
    _prime_between_subjects(win)

    qtbot.mouseClick(win.analyze_between_btn, Qt.LeftButton)

    qtbot.waitUntil(lambda: win.analyze_between_btn.isEnabled(), timeout=2000)
    qtbot.waitUntil(
        lambda: "Between-Group Analysis finished" in win.output_text.toPlainText(), timeout=2000
    )
    assert "Between-Group Mixed Model completed" in win.output_text.toPlainText()
    assert seen_steps == [
        StepId.BETWEEN_GROUP_MIXED_MODEL,
        StepId.GROUP_CONTRASTS,
    ]
    assert not win._controller.is_running(PipelineId.BETWEEN)


@pytest.mark.qt
def test_between_mixed_model_invalid_payload_finalizes(monkeypatch, qtbot, tmp_path):
    seen_steps = []
    _make_immediate_worker(monkeypatch, seen_steps)

    dummy_df = pd.DataFrame({"value": [1.0, 2.0]})

    _patch_between_workers(
        monkeypatch,
        lmm_fn=lambda *_a, **_k: {},
        contrasts_fn=lambda *_a, **_k: {"results_df": dummy_df.copy(), "output_text": "contrasts"},
    )

    win = StatsWindow(project_dir=str(tmp_path))
    qtbot.addWidget(win)
    _prime_between_subjects(win)

    qtbot.mouseClick(win.analyze_between_btn, Qt.LeftButton)

    qtbot.waitUntil(lambda: win.analyze_between_btn.isEnabled(), timeout=2000)
    assert "Step handler failed" in win.output_text.toPlainText()
    assert seen_steps == [StepId.BETWEEN_GROUP_MIXED_MODEL]
    assert not win._controller.is_running(PipelineId.BETWEEN)


@pytest.mark.qt
def test_between_group_analysis_blocks_paused_and_unsupported_steps(monkeypatch, qtbot, tmp_path):
    blocked_messages: list[tuple[str, str, str]] = []
    finished_calls: list[tuple[PipelineId, bool, str | None, bool]] = []

    def capture_log(_self, section, message, level="info"):
        blocked_messages.append((section, message, level))

    def capture_finished(_self, pipeline_id, success, error_message, *, exports_ran):
        finished_calls.append((pipeline_id, success, error_message, exports_ran))

    monkeypatch.setattr(StatsWindow, "append_log", capture_log, raising=False)
    monkeypatch.setattr(StatsWindow, "on_analysis_finished", capture_finished, raising=False)

    win = StatsWindow(project_dir=str(tmp_path))
    qtbot.addWidget(win)
    _prime_between_subjects(win)

    win._controller.run_between_group_analysis(step_ids=(StepId.BETWEEN_GROUP_ANOVA,))
    assert finished_calls
    assert finished_calls[-1][0] is PipelineId.BETWEEN
    assert finished_calls[-1][1] is False
    assert finished_calls[-1][3] is False
    assert "blocked" in (finished_calls[-1][2] or "").lower()
    assert "anova is paused" in (finished_calls[-1][2] or "").lower()

    finished_calls.clear()
    win._controller.run_between_group_analysis(step_ids=(StepId.HARMONIC_CHECK,))
    assert finished_calls
    assert finished_calls[-1][1] is False
    assert "blocked" in (finished_calls[-1][2] or "").lower()
    assert "not part of the supported multigroup workflow" in (finished_calls[-1][2] or "").lower()

    assert any("blocked" in message.lower() for _section, message, _level in blocked_messages)


@pytest.mark.qt
def test_between_process_mode_is_explicitly_fail_closed(monkeypatch, qtbot, tmp_path):
    finished_calls: list[tuple[PipelineId, bool, str | None, bool]] = []
    logs: list[tuple[str, str, str]] = []

    def capture_log(_self, section, message, level="info"):
        logs.append((section, message, level))

    def capture_finished(_self, pipeline_id, success, error_message, *, exports_ran):
        finished_calls.append((pipeline_id, success, error_message, exports_ran))

    monkeypatch.setattr(StatsWindow, "append_log", capture_log, raising=False)
    monkeypatch.setattr(StatsWindow, "on_analysis_finished", capture_finished, raising=False)

    win = StatsWindow(project_dir=str(tmp_path))
    qtbot.addWidget(win)

    win._controller._start_between_process_pipeline()  # noqa: SLF001 - explicit fail-closed check

    assert finished_calls
    pipeline_id, success, error_message, exports_ran = finished_calls[-1]
    assert pipeline_id is PipelineId.BETWEEN
    assert success is False
    assert exports_ran is False
    assert "blocked" in (error_message or "").lower()
    assert "process mode is unavailable" in (error_message or "").lower()
    assert any("process mode is unavailable" in message.lower() for _section, message, _level in logs)
