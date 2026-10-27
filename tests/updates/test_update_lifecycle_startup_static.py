"""Exercise updater launch failures with the real methods and no Qt runtime."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from types import MethodType, SimpleNamespace
from unittest.mock import Mock

import pytest

from Main_App.updates.models import UpdateCancelled


SOURCE = Path(__file__).resolve().parents[2] / "src/Main_App/gui/update_lifecycle.py"


class _Signal:
    def __init__(self):
        self.callbacks = []
        self.values = []

    def connect(self, callback, *_args):
        self.callbacks.append(callback)

    def emit(self, *args):
        self.values.append(args)
        for callback in self.callbacks:
            callback(*args)


@dataclass
class _Result:
    value: object = None
    error: Exception | None = None
    cancelled: bool = False


class _Job:
    """Identity-hashable stand-in for the QObject-owned job."""


def _bind_method(instance, owner, name, namespace):
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == owner)
    method = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == name)
    method.decorator_list = []
    module = ast.Module(body=[
        ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
        method,
    ], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(SOURCE), "exec"), namespace)
    setattr(instance, name, MethodType(namespace[name], instance))


def _job_double(*, fail_at=None, shutting_down=False, finishes_immediately=False):
    failure = RuntimeError(f"Could not launch: {fail_at}")
    threads = []
    workers = []
    deleted_workers = []

    def make_thread(_parent):
        if fail_at == "thread":
            raise failure
        state = SimpleNamespace(running=False, finished=False)

        def start():
            if fail_at == "start":
                raise failure
            state.running = fail_at != "native" and not finishes_immediately
            state.finished = finishes_immediately
            if fail_at == "after_launch":
                raise failure

        thread = SimpleNamespace(
            setObjectName=Mock(), started=_Signal(), finished=_Signal(),
            start=start, quit=Mock(), deleteLater=Mock(),
            isRunning=lambda: state.running,
            isFinished=lambda: state.finished,
        )
        threads.append(thread)
        return thread

    def make_worker(*_args):
        if fail_at == "worker":
            raise failure
        worker = SimpleNamespace(
            moveToThread=Mock(), run=Mock(), progress_changed=_Signal(),
            finished=_Signal(), deleteLater=Mock(),
        )
        workers.append(worker)
        return worker

    namespace = {
        "QThread": make_thread, "_UpdateWorker": make_worker,
        "Qt": SimpleNamespace(ConnectionType=SimpleNamespace(DirectConnection=object())),
        "UpdateCancelled": UpdateCancelled, "UpdateTaskResult": _Result,
        "cast": lambda _kind, value: value,
        "UpdateJob": _Job,
        "delete_qobject": deleted_workers.append,
    }
    job = _Job()
    job._started = job._running = False
    job._thread = job._worker = None
    job._outcome = SimpleNamespace(value=None, error=None)
    job.callback = Mock()
    job.cancel_event = Event()
    job.keep_success_on_cancel = False
    job.finished = _Signal()
    job.progress_changed = _Signal()
    job.deleteLater = Mock()
    job.deleted_workers = deleted_workers
    _bind_method(job, "UpdateJob", "start", namespace)
    _bind_method(job, "UpdateJob", "_finish", namespace)

    lifecycle = SimpleNamespace(
        _jobs={job}, _committed_callbacks={job: Mock()}, sender=lambda: job,
        _startup_pending=False, _restore_quit_on_last_window_closed=True,
        _app=SimpleNamespace(setQuitOnLastWindowClosed=Mock()), idle=_Signal(),
        _shutdown_requested=shutting_down, _schedule_quit=Mock(),
    )
    _bind_method(lifecycle, "UpdateLifecycle", "_restore_auto_quit_if_idle", namespace)
    _bind_method(lifecycle, "UpdateLifecycle", "_job_finished", namespace)
    job.finished.connect(lifecycle._job_finished)
    return job, lifecycle, threads, workers, failure


@pytest.mark.parametrize("fail_at", ["thread", "worker", "start", "native"])
@pytest.mark.parametrize("shutting_down", [False, True])
def test_startup_failure_releases_lifecycle_and_reports_error(fail_at, shutting_down):
    job, lifecycle, threads, workers, failure = _job_double(
        fail_at=fail_at, shutting_down=shutting_down,
    )

    job.start()

    assert not job._running
    assert job._thread is job._worker is None
    assert not lifecycle._jobs
    assert not lifecycle._committed_callbacks
    assert len(job.finished.values) == 1
    result = job.finished.values[0][0]
    assert result.value is None and not result.cancelled
    if fail_at == "native":
        assert isinstance(result.error, RuntimeError)
        assert str(result.error) == "The updater background task could not start."
    else:
        assert result.error is failure
    job.callback.assert_not_called()
    job.deleteLater.assert_called_once()
    lifecycle._app.setQuitOnLastWindowClosed.assert_called_once_with(True)
    assert lifecycle.idle.values == [()]
    assert lifecycle._schedule_quit.call_count == int(shutting_down)
    for obj in threads:
        obj.deleteLater.assert_called_once()
    assert job.deleted_workers == workers
    for obj in workers:
        obj.deleteLater.assert_not_called()

    # Failed one-shot jobs cannot be reused or publish duplicate terminal results.
    with pytest.raises(RuntimeError, match="only be started once"):
        job.start()
    assert len(job.finished.values) == 1


@pytest.mark.parametrize("finishes_immediately", [False, True])
def test_successful_start_retains_job_until_thread_finished_delivery(finishes_immediately):
    job, lifecycle, threads, workers, _failure = _job_double(
        finishes_immediately=finishes_immediately,
    )
    # No committed install callback is needed for a successful metadata check.
    lifecycle._committed_callbacks.clear()

    job.start()

    assert job._running
    assert job._thread is threads[0]
    assert job._worker is workers[0]
    assert lifecycle._jobs == {job}
    assert not job.finished.values
    lifecycle._app.setQuitOnLastWindowClosed.assert_not_called()

    job._outcome.value = "checked"
    workers[0].finished.emit()
    assert job._running
    assert not job.finished.values
    threads[0].quit.assert_called_once()

    threads[0].finished.emit()

    assert job.finished.values == [(_Result(value="checked"),)]
    assert not lifecycle._jobs
    assert not job._running
    assert job._thread is job._worker is None
    assert not job.deleted_workers
    workers[0].deleteLater.assert_called_once()
    threads[0].deleteLater.assert_called_once()


@pytest.mark.parametrize("finishes_immediately", [False, True])
def test_exception_after_launch_waits_for_finished_delivery(finishes_immediately):
    job, lifecycle, threads, workers, failure = _job_double(
        fail_at="after_launch", finishes_immediately=finishes_immediately,
    )

    job.start()

    assert job._running
    assert job._thread is threads[0] and job._worker is workers[0]
    assert lifecycle._jobs == {job}
    assert not job.finished.values and not job.deleted_workers
    threads[0].quit.assert_called_once()
    threads[0].deleteLater.assert_not_called()
    workers[0].deleteLater.assert_not_called()

    workers[0].finished.emit()
    threads[0].finished.emit()

    assert job.finished.values == [(_Result(error=failure),)]
    assert not lifecycle._jobs and not job._running
    assert not job.deleted_workers
