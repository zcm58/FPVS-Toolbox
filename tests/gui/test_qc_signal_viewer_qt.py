"""CI-only visible signal-inspection lifecycle tests with bounded synthetic I/O."""

from dataclasses import replace
from threading import Event, get_ident

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import QTimer, Qt  # noqa: E402

from Main_App.gui.qc_signal_viewer import QcSignalViewer  # noqa: E402
from Main_App.processing.qc_signal_view import (  # noqa: E402
    QcSignalTrace, QcSignalViewResult, request_from_source,
)
from Main_App.workers import qc_signal_view_worker as worker_module  # noqa: E402


def _result():
    trace = QcSignalTrace("Fp1", (0.0, -1.0), (1.0, 2.0))
    return QcSignalViewResult(
        "Fp1", ("Fp1", "Fp2"), ("Condition A · occurrence 1",), ((5.0, 10.0),),
        0, 5.0, 10.0, (5.0, 9.0), trace, (5.0, 9.0), (trace,),
        "Raw acquisition", ("EXG1", "EXG2"),
    )


def test_loading_is_responsive_and_close_cancels_without_orphan_thread(qtbot, monkeypatch, tmp_path):
    entered, release = Event(), Event()
    threads = []

    def load(_request, *, should_cancel):
        threads.append(get_ident())
        entered.set()
        for _ in range(500):
            if should_cancel():
                raise InterruptedError()
            if release.wait(0.01):
                return _result()
        raise TimeoutError("Synthetic viewer read was not released")

    monkeypatch.setattr(worker_module, "load_qc_signal_view", load)
    viewer = QcSignalViewer(request_from_source(tmp_path / "synthetic.bdf", tmp_path, {}))
    qtbot.addWidget(viewer)
    timer = QTimer(viewer)
    ticks = []
    timer.timeout.connect(lambda: ticks.append(get_ident()))
    timer.start(5)
    viewer.show()
    try:
        qtbot.waitUntil(entered.is_set)
        qtbot.waitUntil(lambda: len(ticks) >= 3)
        assert threads[0] != get_ident()
        assert all(thread == get_ident() for thread in ticks)
        assert viewer.isVisible()
        viewer.reject()
        qtbot.waitUntil(lambda: viewer._thread is None)
        assert not viewer.isVisible()
    finally:
        release.set()
        viewer.reject()
        qtbot.waitUntil(lambda: viewer._thread is None, timeout=6000)
        timer.stop()


def test_failed_new_view_clears_previous_trace_and_keeps_retry_available(qtbot, monkeypatch, tmp_path):
    calls = []

    def load(_request, *, should_cancel):
        calls.append(True)
        if len(calls) > 1:
            raise OSError("Recording unavailable")
        return _result()

    monkeypatch.setattr(worker_module, "load_qc_signal_view", load)
    viewer = QcSignalViewer(request_from_source(tmp_path / "synthetic.bdf", tmp_path, {}))
    qtbot.addWidget(viewer)
    viewer.show()
    try:
        qtbot.waitUntil(lambda: viewer._result is not None and viewer._thread is None)
        assert viewer.plot._traces
        viewer._load()
        qtbot.waitUntil(lambda: len(calls) == 2 and viewer._thread is None)
        assert not viewer.plot._traces
        assert not viewer.overview._traces
        assert "Recording unavailable" in viewer.status.text()
        assert viewer.refresh.isEnabled()
    finally:
        viewer.reject()
        qtbot.waitUntil(lambda: viewer._thread is None, timeout=6000)


def test_event_navigation_uses_source_occurrence_and_spatial_request_excludes_bad_donors(qtbot, monkeypatch, tmp_path):
    requests = []
    spans = ((1.0, 2.0), (7.0, 9.0))
    report = {"localized_events": [{"channel": "EXG2", "kind": "raw_flatline",
                                    "start_s": 7.5, "stop_s": 7.7}]}

    def load(request, *, should_cancel):
        requests.append(request)
        return replace(_result(), spans=spans, span_labels=("Occurrence 1", "Occurrence 2"),
                       occurrence_index=request.occurrence_index, diagnostics=report)

    monkeypatch.setattr(worker_module, "load_qc_signal_view", load)
    request = replace(request_from_source(tmp_path / "synthetic.bdf", tmp_path, {}, spans=spans),
                      source_spans=spans, unusable_channels=("Fp2",))
    viewer = QcSignalViewer(request)
    qtbot.addWidget(viewer)
    viewer.show()
    try:
        qtbot.waitUntil(lambda: len(requests) == 1 and viewer._thread is None)
        viewer.tabs.setCurrentIndex(1)
        qtbot.mouseClick(viewer.event_jump, Qt.MouseButton.LeftButton)
        qtbot.waitUntil(lambda: len(requests) == 2 and viewer._thread is None)
        assert requests[-1].mode == "reference_comparison"
        assert requests[-1].occurrence_index == 1
        assert requests[-1].start_seconds == 7.0
        viewer.tabs.setCurrentIndex(1)
        qtbot.mouseClick(viewer.spatial_button, Qt.MouseButton.LeftButton)
        qtbot.waitUntil(lambda: len(requests) == 3 and viewer._thread is None)
        assert requests[-1].spatial_holdout is True
        assert requests[-1].unusable_channels == ("Fp2",)
    finally:
        viewer.reject()
        qtbot.waitUntil(lambda: viewer._thread is None, timeout=6000)
