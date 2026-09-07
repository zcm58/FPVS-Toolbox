from __future__ import annotations

import ast
from pathlib import Path
from threading import Event, Thread, get_ident
from unittest.mock import Mock

import pytest


WORKER_PATH = (
    Path(__file__).resolve().parents[2]
    / "src" / "Main_App" / "workers" / "qc_source_prefetch_worker.py"
)


def _worker_without_qt(prefetch):
    """Execute the production lifecycle with signal doubles and no Qt runtime."""
    tree = ast.parse(WORKER_PATH.read_text(encoding="utf-8"))
    tree.body = [
        node for node in tree.body
        if not (isinstance(node, ast.ImportFrom) and node.module == "PySide6.QtCore")
    ]
    namespace = {
        "__name__": __name__, "QObject": object,
        "Signal": lambda *_args: None,
        "Slot": lambda *_args: lambda method: method,
    }
    exec(compile(tree, str(WORKER_PATH), "exec"), namespace)
    worker = namespace["QcSourcePrefetchWorker"](prefetch)
    worker.finished = Mock()
    return worker


class _ObservedEvent:
    """Expose when the production worker reaches its lifetime wait."""

    def __init__(self):
        self._event = Event()
        self.waiting = Event()

    def is_set(self):
        return self._event.is_set()

    def set(self):
        self._event.set()

    def wait(self):
        self.waiting.set()
        if not self._event.wait(timeout=5):
            raise TimeoutError("Worker did not receive its finish request")


@pytest.mark.parametrize("run_error", [None, OSError("Cannot preload recording")])
def test_cache_survives_producer_completion_and_cleans_up_on_worker_thread(run_error):
    calls = []

    def run():
        calls.append(("run", get_ident()))
        if run_error is not None:
            raise run_error

    prefetch = Mock()
    prefetch.run.side_effect = run
    prefetch.cancel.side_effect = lambda: calls.append(("cancel", get_ident()))
    prefetch.close.side_effect = lambda: calls.append(("close", get_ident()))
    worker = _worker_without_qt(prefetch)
    worker.finished.emit.side_effect = lambda: calls.append(("finished", get_ident()))
    lifetime = _ObservedEvent()
    worker._finish_requested = lifetime
    producer = Thread(target=worker.run, daemon=True)
    producer.start()
    try:
        assert lifetime.waiting.wait(timeout=5)
        assert producer.is_alive()
        prefetch.close.assert_not_called()
        worker.finished.emit.assert_not_called()
    finally:
        worker.request_finish()
        producer.join(timeout=5)

    assert not producer.is_alive()
    assert calls == [
        ("run", producer.ident), ("cancel", get_ident()),
        ("close", producer.ident), ("finished", producer.ident),
    ]


def test_finish_requested_before_start_skips_loading_and_still_cleans_up():
    prefetch = Mock()
    worker = _worker_without_qt(prefetch)

    worker.request_finish()
    prefetch.close.assert_not_called()
    worker.run()

    prefetch.run.assert_not_called()
    prefetch.cancel.assert_called_once_with()
    prefetch.close.assert_called_once_with()
    worker.finished.emit.assert_called_once_with()


def test_finish_request_does_not_wait_for_an_active_source_load():
    entered = Event()
    release = Event()

    def run():
        entered.set()
        if not release.wait(timeout=5):
            raise TimeoutError("Test did not release source load")

    prefetch = Mock()
    prefetch.run.side_effect = run
    worker = _worker_without_qt(prefetch)
    producer = Thread(target=worker.run, daemon=True)
    producer.start()
    try:
        assert entered.wait(timeout=5)
        worker.request_finish()
        assert producer.is_alive()
        prefetch.close.assert_not_called()
        worker.finished.emit.assert_not_called()
    finally:
        release.set()
        worker.request_finish()
        producer.join(timeout=5)

    assert not producer.is_alive()
    prefetch.close.assert_called_once_with()
    worker.finished.emit.assert_called_once_with()


@pytest.mark.parametrize("failed_method", ["cancel", "close"])
def test_lifecycle_failure_is_logged_and_does_not_strand_completion(failed_method, caplog):
    prefetch = Mock()
    getattr(prefetch, failed_method).side_effect = OSError("Cache unavailable")
    worker = _worker_without_qt(prefetch)

    worker.request_finish()
    worker.run()

    prefetch.close.assert_called_once_with()
    worker.finished.emit.assert_called_once_with()
    assert "Cache unavailable" in caplog.text


def test_worker_never_imports_widgets_or_gui_workflows():
    tree = ast.parse(WORKER_PATH.read_text(encoding="utf-8"))
    modules = {
        node.module for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert "PySide6.QtWidgets" not in modules
    assert not any("gui" in (module or "").split(".") for module in modules)
