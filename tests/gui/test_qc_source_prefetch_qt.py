"""CI-only visible QC prefetch lifecycle checks without BDF or cache I/O."""

from __future__ import annotations

from threading import Event, get_ident
from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import QObject, QTimer, Qt, Slot  # noqa: E402
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget  # noqa: E402

from Main_App.gui import preprocessing_qc_workflow as workflow  # noqa: E402


class _ReviewHost(QWidget):
    def __init__(self, project_root):
        super().__init__()
        self.currentProject = SimpleNamespace(project_root=project_root)
        self.processing_current_file_label = QLabel("Review markers", self)
        self.continue_button = QPushButton("Continue", self)
        layout = QVBoxLayout(self)
        layout.addWidget(self.processing_current_file_label)
        layout.addWidget(self.continue_button)


class _ReviewProbe(QObject):
    def __init__(self, host, state):
        super().__init__(host)
        self.host = host
        self.state = state

    @Slot()
    def tick(self):
        state = self.state
        state.heartbeats.append((self.host.isVisible(), get_ident()))
        if not state.finishing:
            return
        state.finishing_ticks += 1
        if state.cancelled.is_set():
            state.release_load.set()
        if state.cleanup_entered.is_set():
            state.cleanup_ticks += 1
            if state.cleanup_ticks >= 3:
                state.release_cleanup.set()

    @Slot()
    def continue_review(self):
        self.state.continue_threads.append(get_ident())

    @Slot()
    def thread_finished(self):
        self.state.finished_threads.append(get_ident())


@pytest.fixture
def prefetch_review(qtbot, monkeypatch, tmp_path):
    host = _ReviewHost(tmp_path)
    qtbot.addWidget(host)
    state = SimpleNamespace(
        load_entered=Event(), release_load=Event(), producer_returned=Event(),
        cancelled=Event(), cleanup_entered=Event(), release_cleanup=Event(),
        cleanup_returned=Event(), timeouts=[], arguments=[], backend_threads=[],
        cancel_threads=[], continue_threads=[], finished_threads=[], heartbeats=[],
        finishing=False, finishing_ticks=0, cleanup_ticks=0,
    )

    class SyntheticPrefetch:
        def __init__(self, *args):
            state.arguments.append(args)

        def run(self):
            state.backend_threads.append(("load", get_ident()))
            state.load_entered.set()
            if not state.release_load.wait(5):
                state.timeouts.append("load")
            state.producer_returned.set()

        def cancel(self):
            state.cancel_threads.append(get_ident())
            state.cancelled.set()

        def close(self):
            state.backend_threads.append(("close", get_ident()))
            state.cleanup_entered.set()
            if not state.release_cleanup.wait(5):
                state.timeouts.append("cleanup")
            state.cleanup_returned.set()

    monkeypatch.setattr(workflow, "QcSourcePrefetch", SyntheticPrefetch)
    probe = _ReviewProbe(host, state)
    host.continue_button.clicked.connect(probe.continue_review)
    timer = QTimer(host)
    timer.setInterval(5)
    timer.timeout.connect(probe.tick)
    host.resize(560, 200)
    host.show()
    qtbot.waitExposed(host)
    timer.start()

    def begin():
        bridge = workflow._start_qc_source_prefetch(
            host, [SimpleNamespace(path="synthetic-recording.bdf")],
            {"reject_thresh": 4.0},
        )
        assert bridge is not None
        bridge.thread.finished.connect(probe.thread_finished)
        return bridge

    def finish(bridge):
        state.finishing = True
        workflow._finish_qc_source_prefetch(host, bridge)

    try:
        yield SimpleNamespace(host=host, state=state, begin=begin, finish=finish)
    finally:
        # Release synthetic waits before widget teardown can destroy its QThread.
        state.release_load.set()
        state.release_cleanup.set()
        bridge = getattr(host, "_qc_source_prefetch_bridge", None)
        if bridge is not None:
            finish(bridge)
        timer.stop()
        host.close()


def _assert_completed(qtbot, fixture):
    state = fixture.state
    qtbot.waitUntil(lambda: bool(state.finished_threads), timeout=3000)
    assert fixture.host._qc_source_prefetch_bridge is None
    assert state.cleanup_returned.is_set()
    assert not state.timeouts
    assert state.backend_threads[0][0] == "load"
    assert state.backend_threads[1][0] == "close"
    assert state.backend_threads[0][1] == state.backend_threads[1][1]
    assert state.backend_threads[1][1] != get_ident()
    assert state.cancel_threads == [get_ident()]
    assert state.finished_threads == [get_ident()]
    assert state.finishing_ticks >= 3
    assert state.cleanup_ticks >= 3
    assert all(visible and thread == get_ident() for visible, thread in state.heartbeats)
    assert fixture.host.processing_current_file_label.text() == "Finishing data quality checks..."


def test_review_and_finish_remain_responsive_while_source_load_is_active(qtbot, prefetch_review):
    fixture = prefetch_review
    bridge = fixture.begin()
    qtbot.waitUntil(fixture.state.load_entered.is_set, timeout=3000)
    initial_ticks = len(fixture.state.heartbeats)
    qtbot.waitUntil(lambda: len(fixture.state.heartbeats) >= initial_ticks + 3)

    qtbot.mouseClick(fixture.host.continue_button, Qt.LeftButton)

    assert fixture.state.continue_threads == [get_ident()]
    assert not fixture.state.producer_returned.is_set()
    assert not fixture.state.cleanup_entered.is_set()
    assert fixture.host._qc_source_prefetch_bridge is bridge
    fixture.finish(bridge)
    _assert_completed(qtbot, fixture)


def test_completed_preload_stays_available_until_review_finishes(qtbot, prefetch_review):
    fixture = prefetch_review
    fixture.state.release_load.set()
    bridge = fixture.begin()
    qtbot.waitUntil(fixture.state.producer_returned.is_set, timeout=3000)
    initial_ticks = len(fixture.state.heartbeats)
    qtbot.waitUntil(lambda: len(fixture.state.heartbeats) >= initial_ticks + 3)

    assert not bridge.finished
    assert bridge.thread.isRunning()
    assert not fixture.state.cleanup_entered.is_set()
    qtbot.mouseClick(fixture.host.continue_button, Qt.LeftButton)
    assert fixture.state.continue_threads == [get_ident()]

    fixture.finish(bridge)
    _assert_completed(qtbot, fixture)
