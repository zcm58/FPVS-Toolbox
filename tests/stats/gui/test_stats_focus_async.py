from __future__ import annotations

import time
from pathlib import Path

from Tools.Stats.common.stats_core import PipelineId, PipelineStep, StepId
from Tools.Stats.ui.stats_window import StatsWindow
from Tools.Stats.workers.stats_workers import StatsWorker


def test_stats_focus_async(qtbot, monkeypatch):
    win = StatsWindow(project_dir=str(Path.cwd()))
    qtbot.addWidget(win)
    win.show()
    def fake_run(self):
        self.signals.message.emit("start")
        self.signals.progress.emit(55)
        time.sleep(0.01)
        self.signals.finished.emit({})

    monkeypatch.setattr(StatsWorker, "run", fake_run, raising=False)

    completed: list[tuple[PipelineId, StepId]] = []
    errors: list[str] = []

    def finish(pipeline_id, step_id, _payload):
        completed.append((pipeline_id, step_id))
        win.set_busy(False)
        win.on_analysis_finished(
            pipeline_id,
            True,
            None,
            exports_ran=False,
        )

    step = PipelineStep(
        id=StepId.MIXED_MODEL,
        name="Mixed Model",
        worker_fn=lambda *_args, **_kwargs: {},
        kwargs={},
        handler=lambda _payload: None,
    )
    win.set_busy(True)
    win.on_pipeline_started(PipelineId.SINGLE)
    assert not win.analyze_single_btn.isEnabled()

    win.start_step_worker(
        PipelineId.SINGLE,
        step,
        finished_cb=finish,
        error_cb=lambda _pipeline_id, _step_id, message: errors.append(message),
    )

    qtbot.waitUntil(lambda: win.analyze_single_btn.isEnabled(), timeout=1000)
    qtbot.waitUntil(lambda: not win._active_workers, timeout=1000)
    assert completed == [(PipelineId.SINGLE, StepId.MIXED_MODEL)]
    assert errors == []
    assert win._progress_updates
    assert win._focus_calls >= 1
