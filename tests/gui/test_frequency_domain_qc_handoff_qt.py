"""CI-only handoff checks with a bounded synthetic save and no project I/O."""

from __future__ import annotations

from threading import Event
from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot  # noqa: E402
from PySide6.QtWidgets import QLabel, QPushButton, QWidget  # noqa: E402

from Main_App.gui import frequency_domain_qc_handoff as handoff  # noqa: E402
from Main_App.gui import processing_workflows  # noqa: E402


class _Host(QWidget):
    def __init__(self):
        super().__init__()
        self.processing_title_label = QLabel(self)
        self.processing_message_label = QLabel(self)
        self.btn_start = QPushButton("Stop Processing", self)
        self.btn_start.setToolTip("Original stop action")
        self.busy = False
        self.controls_enabled = True
        self.messages = []

    def _busy_start(self):
        self.busy = True

    def _set_controls_enabled(self, enabled):
        self.controls_enabled = enabled

    def log(self, message, *, level):
        self.messages.append((message, level))


class _Heartbeat(QObject):
    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.observations = []

    @Slot()
    def tick(self):
        self.observations.append((self.host.isVisible(), QThread.currentThread()))


@pytest.fixture
def save_handoff(qtbot, monkeypatch, tmp_path):
    host = _Host()
    qtbot.addWidget(host)
    state = SimpleNamespace(
        started=Event(), release_save=Event(), release_exit=Event(),
        returned=Event(), timed_out=False, worker_thread=None,
        result={"success": True, "tools": {"frequency_domain_qc": {"accepted": True}}},
        timeline=[], starts=[], finishes=[], resume=[], errors=[], arguments=[],
        start_result=True,
    )

    class TrackedManifest(dict):
        def __setitem__(self, key, value):
            if key == "tools":
                state.timeline.append(("tools", QThread.currentThread()))
            super().__setitem__(key, value)

    project = SimpleNamespace(
        project_root=tmp_path,
        manifest=TrackedManifest({"tools": {"before": True}, "title": "Test project"}),
    )
    host.currentProject = project

    class SlowSaveWorker(QObject):
        finished = Signal(dict)

        def __init__(self, *args, **kwargs):
            super().__init__()
            state.arguments.append((args, kwargs))

        @Slot()
        def run(self):
            state.worker_thread = QThread.currentThread()
            state.started.set()
            if not state.release_save.wait(5):
                state.timed_out = True
            self.finished.emit(dict(state.result))
            # A receipt alone must not resume processing while run() still runs.
            if not state.release_exit.wait(5):
                state.timed_out = True
            state.returned.set()

    def start_pipeline(owner, *, on_finished, completed_phase_floor):
        assert owner.btn_start.isEnabled()
        assert owner.btn_start.text() == "Stop Processing"
        assert owner.btn_start.toolTip() == "Original stop action"
        state.timeline.append(("start", QThread.currentThread()))
        state.starts.append({
            "owner": owner,
            "on_finished": on_finished,
            "phase": completed_phase_floor,
            "tools": dict(project.manifest["tools"]),
            "worker_returned": state.returned.is_set(),
            "thread_running": state.worker_thread.isRunning(),
            "save_thread": owner._frequency_domain_qc_save_thread,
        })
        return state.start_result

    def finish():
        state.timeline.append(("finish", QThread.currentThread()))
        state.finishes.append(True)
        host.busy = False
        host._set_controls_enabled(True)

    def set_resume(owner, pending):
        state.timeline.append(("resume", QThread.currentThread()))
        state.resume.append((owner, pending))

    monkeypatch.setattr(handoff, "FrequencyDomainQcDecisionWorker", SlowSaveWorker)
    monkeypatch.setattr(handoff.shell_status, "prepare_post_processing_activity", lambda *a, **kw: None)
    monkeypatch.setattr(processing_workflows, "_start_post_processing_pipeline_after_processing", start_pipeline)
    monkeypatch.setattr(processing_workflows, "_set_resume_post_processing_pending", set_resume)
    monkeypatch.setattr(handoff.QMessageBox, "critical", lambda *args: state.errors.append(args))
    heartbeat = _Heartbeat(host)
    timer = QTimer(host)
    timer.setInterval(5)
    timer.timeout.connect(heartbeat.tick)
    host.resize(640, 320)
    host.show()
    qtbot.waitExposed(host)
    timer.start()

    def begin():
        handoff.save_frequency_domain_qc_review(
            host, project, {"report_fingerprint": "synthetic-report"},
            review_decisions=[{"decision": "keep", "reason": ""}],
            manual_participant_reasons={}, manual_recording_reasons={},
            on_finished=finish,
        )

    try:
        yield SimpleNamespace(
            host=host, project=project, state=state, heartbeat=heartbeat,
            begin=begin, finish=finish,
        )
    finally:
        # Never leave a running QThread owned by a widget that pytest will delete.
        state.release_save.set()
        state.release_exit.set()
        thread = getattr(host, "_frequency_domain_qc_save_thread", None)
        if thread is not None:
            thread.quit()
            assert thread.wait(3000), "Synthetic save worker did not finish during cleanup."
            qtbot.waitUntil(lambda: host._frequency_domain_qc_save_thread is None, timeout=3000)
        timer.stop()
        host.close()


def _finish_save(qtbot, fixture):
    fixture.state.release_save.set()
    fixture.state.release_exit.set()
    qtbot.waitUntil(lambda: fixture.host._frequency_domain_qc_save_thread is None, timeout=3000)
    assert not fixture.state.timed_out


def test_slow_save_keeps_window_visible_and_gui_responsive(qtbot, save_handoff):
    fixture = save_handoff
    fixture.begin()
    qtbot.waitUntil(fixture.state.started.is_set)
    initial_ticks = len(fixture.heartbeat.observations)
    qtbot.waitUntil(lambda: len(fixture.heartbeat.observations) >= initial_ticks + 3)

    assert fixture.state.worker_thread is not fixture.host.thread()
    assert fixture.host.isVisible()
    assert fixture.host.busy
    assert not fixture.host.controls_enabled
    assert not fixture.host.btn_start.isEnabled()
    assert fixture.host.btn_start.text() == "Saving QC…"
    assert fixture.host.processing_title_label.text() == "Saving QC Decisions"
    assert "Saving your review" in fixture.host.processing_message_label.text()
    assert all(visible for visible, _thread in fixture.heartbeat.observations)
    assert all(thread is fixture.host.thread() for _visible, thread in fixture.heartbeat.observations)
    assert fixture.state.starts == []
    assert fixture.state.finishes == []
    assert fixture.project.manifest["tools"] == {"before": True}
    _finish_save(qtbot, fixture)


def test_metadata_and_pipeline_handoff_wait_for_thread_exit(qtbot, save_handoff):
    fixture = save_handoff
    fixture.begin()
    qtbot.waitUntil(fixture.state.started.is_set)
    fixture.state.release_save.set()
    qtbot.waitUntil(lambda: fixture.host._frequency_domain_qc_save_bridge.result is not None)

    assert fixture.host._frequency_domain_qc_save_thread.isRunning()
    assert not fixture.state.returned.is_set()
    assert fixture.state.starts == []
    assert fixture.project.manifest["tools"] == {"before": True}
    fixture.state.release_exit.set()
    qtbot.waitUntil(lambda: len(fixture.state.starts) == 1)

    start = fixture.state.starts[0]
    assert start["owner"] is fixture.host
    assert start["on_finished"] is fixture.finish
    assert start["phase"] == 1
    assert start["tools"] == fixture.state.result["tools"]
    assert start["worker_returned"]
    assert not start["thread_running"]
    assert start["save_thread"] is None
    assert [item[0] for item in fixture.state.timeline] == ["tools", "start"]
    assert all(thread is fixture.host.thread() for _event, thread in fixture.state.timeline)
    assert fixture.project.manifest["title"] == "Test project"
    assert fixture.host._frequency_domain_qc_save_worker is None
    assert fixture.host._frequency_domain_qc_save_bridge is None
    assert fixture.state.finishes == []
    assert fixture.state.resume == []
    assert not fixture.state.timed_out


@pytest.mark.parametrize("stale_error", ["", "The stale-status write also failed."])
def test_save_failure_releases_controls_and_retains_resume(qtbot, save_handoff, stale_error):
    fixture = save_handoff
    fixture.state.result = {
        "success": False, "tools": None,
        "error": "The decision file could not be saved.", "stale_error": stale_error,
    }
    fixture.begin()
    _finish_save(qtbot, fixture)

    assert fixture.state.starts == []
    assert fixture.state.finishes == [True]
    assert fixture.state.resume == [(fixture.host, True)]
    assert [item[0] for item in fixture.state.timeline] == ["finish", "resume"]
    assert all(thread is fixture.host.thread() for _event, thread in fixture.state.timeline)
    assert fixture.host.controls_enabled
    assert fixture.host.btn_start.isEnabled()
    assert fixture.host.btn_start.text() == "Stop Processing"
    assert not fixture.host.busy
    assert fixture.host.isVisible()
    assert fixture.project.manifest["tools"] == {"before": True}
    assert len(fixture.state.errors) == 1
    owner, title, reason = fixture.state.errors[0]
    assert owner is fixture.host
    assert title == "Frequency-Domain QC Error"
    assert fixture.state.result["error"] in reason
    if stale_error:
        assert stale_error in reason
    assert fixture.host._post_processing_failure_reason == reason


def test_no_downstream_work_releases_controls_after_success(qtbot, save_handoff):
    fixture = save_handoff
    fixture.state.start_result = False
    fixture.begin()
    _finish_save(qtbot, fixture)

    assert len(fixture.state.starts) == 1
    assert fixture.state.finishes == [True]
    assert [item[0] for item in fixture.state.timeline] == ["tools", "start", "finish"]
    assert fixture.host.controls_enabled
    assert not fixture.host.busy
    assert fixture.state.resume == []
    assert fixture.state.errors == []
