"""CI-only checks for the persistent project processing-history line."""

from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

if importlib.util.find_spec("PySide6") is None or importlib.util.find_spec("pytestqt") is None:
    pytest.skip("PySide6 or pytest-qt not available", allow_module_level=True)

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAccessible

from Main_App.gui import processing_history_label as label_module
from Main_App.gui.processing_history_model import format_processing_history
from Main_App.processing.processing_history import CompletedProcessingRun, ProcessingHistoryStatus


def _completed(count: int | None = 17) -> ProcessingHistoryStatus:
    return ProcessingHistoryStatus(
        state="completed",
        latest_completed_run=CompletedProcessingRun(
            timestamp=datetime(2026, 11, 4, 14, 30, tzinfo=timezone.utc),
            participant_count=count,
            successful_recording_count=20,
        ),
    )


def _label(qtbot):
    label = label_module.ProcessingHistoryLabel()
    qtbot.addWidget(label)
    label.resize(900, 60)
    label.show()
    return label


@pytest.mark.parametrize(
    "status",
    [
        ProcessingHistoryStatus(state="missing"),
        ProcessingHistoryStatus(state="unavailable"),
        _completed(),
        _completed(None),
    ],
    ids=["no-completed-run", "unavailable-history", "completed-run", "unknown-participant-count"],
)
def test_history_status_remains_visible(qtbot, monkeypatch, tmp_path: Path, status) -> None:
    monkeypatch.setattr(label_module, "load_processing_history", lambda _root: status)
    label = _label(qtbot)

    label.refresh(tmp_path)
    qtbot.waitUntil(lambda: label.text() == format_processing_history(status))

    assert label.isVisible()
    assert label.wordWrap()
    assert label.objectName() == "project_processing_history"
    interface = QAccessible.queryAccessibleInterface(label)
    assert interface is not None
    assert interface.text(QAccessible.Text.Name) == format_processing_history(status)


def test_loading_history_keeps_event_loop_responsive(qtbot, monkeypatch, tmp_path: Path) -> None:
    entered = threading.Event()
    release = threading.Event()
    gui_thread = threading.get_ident()
    loader_threads = []
    status = _completed()

    def load(root: Path):
        assert Path(root) == tmp_path.resolve()
        loader_threads.append(threading.get_ident())
        entered.set()
        if not release.wait(5):
            raise TimeoutError("Test did not release the history loader")
        return status

    monkeypatch.setattr(label_module, "load_processing_history", load)
    label = _label(qtbot)
    label.refresh(tmp_path)
    try:
        qtbot.waitUntil(entered.is_set)
        assert label.isVisible()
        assert "Checking" in label.text()
        heartbeat = []
        QTimer.singleShot(0, lambda: heartbeat.append(True))
        qtbot.waitUntil(lambda: bool(heartbeat))
        assert len(loader_threads) == 1
        assert loader_threads[0] != gui_thread
    finally:
        release.set()

    qtbot.waitUntil(lambda: label.text() == format_processing_history(status))


def test_history_read_failure_is_visible(qtbot, monkeypatch, tmp_path: Path) -> None:
    def unavailable(_root):
        raise OSError("Read permission unavailable")

    monkeypatch.setattr(label_module, "load_processing_history", unavailable)
    label = _label(qtbot)

    label.refresh(tmp_path)
    qtbot.waitUntil(lambda: "Processing history unavailable" in label.text())

    assert label.isVisible()


def test_old_project_and_old_request_results_do_not_replace_current_history(
    qtbot, monkeypatch, tmp_path: Path,
) -> None:
    requests = []
    pool = SimpleNamespace(start=requests.append)
    monkeypatch.setattr(label_module, "QThreadPool", SimpleNamespace(globalInstance=lambda: pool))
    label = _label(qtbot)
    first = (tmp_path / "first").resolve()
    second = (tmp_path / "second").resolve()
    first.mkdir()
    second.mkdir()

    label.refresh(first)
    first_request = label._request_id
    label.refresh(second)
    second_request = label._request_id
    loading = label.text()
    assert len(requests) == 2
    assert second_request > first_request

    label._on_loaded(str(first), first_request, _completed(99))
    label._on_loaded(str(first), second_request, _completed(99))
    label._on_loaded(str(second), first_request, _completed(99))
    assert label.text() == loading

    current = _completed(7)
    label._on_loaded(str(second), second_request, current)
    assert label.text() == format_processing_history(current)

    label.refresh(None)
    label._on_loaded(str(second), second_request, _completed(99))
    assert label.text() == "No project open"
    assert label.isVisible()


def test_reopened_home_loads_saved_history_again(qtbot, monkeypatch, tmp_path: Path) -> None:
    status = _completed()
    reads = []

    def load(root):
        reads.append(Path(root))
        return status

    monkeypatch.setattr(label_module, "load_processing_history", load)
    first = _label(qtbot)
    first.refresh(tmp_path)
    qtbot.waitUntil(lambda: first.text() == format_processing_history(status))
    first.close()

    reopened = _label(qtbot)
    reopened.refresh(tmp_path)
    qtbot.waitUntil(lambda: reopened.text() == format_processing_history(status))

    assert reads == [tmp_path.resolve(), tmp_path.resolve()]
    assert reopened.isVisible()


def test_refresh_during_load_reads_again_after_the_inflight_snapshot(qtbot, monkeypatch, tmp_path):
    requests = []
    pool = SimpleNamespace(start=requests.append)
    monkeypatch.setattr(label_module, "QThreadPool", SimpleNamespace(globalInstance=lambda: pool))
    label = _label(qtbot)
    label.refresh(tmp_path)
    first_request = label._request_id
    label.refresh(tmp_path)
    label.refresh(tmp_path)
    assert len(requests) == 1

    label._on_loaded(str(tmp_path.resolve()), first_request, _completed(7))
    assert len(requests) == 2
    label._on_loaded(str(tmp_path.resolve()), label._request_id, _completed(17))
    assert label.text() == format_processing_history(_completed(17))


def test_destroyed_history_label_disconnects_inflight_result(qtbot, monkeypatch, tmp_path):
    entered, release = threading.Event(), threading.Event()

    def load(_root):
        entered.set()
        if not release.wait(5):
            raise TimeoutError("Test did not release the history loader")
        return _completed()

    monkeypatch.setattr(label_module, "load_processing_history", load)
    # This test owns deletion; do not ask qtbot to close the deleted C++ widget.
    label = label_module.ProcessingHistoryLabel()
    label.show()
    label.refresh(tmp_path)
    worker = label._worker
    delivered, destroyed = [], []
    worker.signals.finished.connect(lambda *_: delivered.append(True))
    label.destroyed.connect(lambda *_: destroyed.append(True))
    try:
        qtbot.waitUntil(entered.is_set)
        label.deleteLater()
        qtbot.waitUntil(lambda: bool(destroyed))
    finally:
        release.set()
        if not destroyed:
            label.deleteLater()
    # The runnable owns its signals, while Qt drops the deleted widget's slot.
    qtbot.waitUntil(lambda: bool(delivered))
