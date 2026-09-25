"""Startup/manual scheduling checks with plain Python signals and deferred jobs."""

from types import SimpleNamespace
from threading import Event

import pytest

from Main_App.gui import update_manager
from Main_App.gui.update_lifecycle import UpdateTaskResult
from Main_App.updates.models import UpdateCheckResult


class FakeSignal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)

    def disconnect(self, callback):
        self.callbacks.remove(callback)

    def emit(self, *args):
        for callback in tuple(self.callbacks):
            callback(*args)


class DeferredJob:
    def __init__(self, callback):
        self.callback = callback
        self.finished = FakeSignal()
        self.cancelled = False

    def cancel(self):
        self.cancelled = True


@pytest.fixture
def startup(monkeypatch):
    jobs = []

    def start_task(callback):
        job = DeferredJob(callback)
        jobs.append(job)
        return job

    lifecycle = SimpleNamespace(
        manual_check_requested=FakeSignal(),
        is_shutting_down=False,
        start_task=start_task,
    )
    host = SimpleNamespace(destroyed=FakeSignal())
    shown = []
    monkeypatch.setattr(update_manager, "update_lifecycle", lambda: lifecycle)
    monkeypatch.setattr(update_manager, "_running_under_pytest", lambda: False)
    monkeypatch.setattr(update_manager, "_should_skip_update_check", lambda: False)
    monkeypatch.setattr(
        update_manager, "_show_update_dialog", lambda *args, **kwargs: shown.append(kwargs)
    )
    result = UpdateCheckResult("3.0.0", "3.0.0", False, None, "", None, False)
    return SimpleNamespace(host=host, lifecycle=lifecycle, jobs=jobs, shown=shown, result=result)


def test_manual_signal_before_launch_timer_suppresses_startup(startup):
    update_manager.prepare_startup_update_check(startup.host)
    startup.lifecycle.manual_check_requested.emit()

    update_manager.check_for_updates_on_launch(startup.host)

    assert startup.jobs == [startup.host._startup_update_check.cache_job]
    assert startup.host._startup_update_check.job is None


def test_manual_menu_before_launch_timer_suppresses_startup(startup):
    update_manager.check_for_updates_async(startup.host, silent=False, force=True)
    update_manager.check_for_updates_on_launch(startup.host)

    assert startup.jobs == [startup.host._startup_update_check.cache_job]
    assert startup.host._startup_update_check.job is None
    assert startup.shown == [{"auto_check": True}]


def test_startup_runs_once_and_releases_finished_job(startup, monkeypatch):
    results = []
    monkeypatch.setattr(update_manager, "_on_launch_result", lambda host, result: results.append(result))
    update_manager.check_for_updates_on_launch(startup.host)
    update_manager.check_for_updates_on_launch(startup.host)
    assert len(startup.jobs) == 2

    startup.host._startup_update_check.job.finished.emit(UpdateTaskResult(value=startup.result))
    update_manager.check_for_updates_on_launch(startup.host)

    assert results == [startup.result]
    assert startup.host._startup_update_check.job is None
    assert len(startup.jobs) == 2


@pytest.mark.parametrize("interrupt", ["manual_signal", "manual_menu", "destroyed", "shutdown"])
def test_late_startup_result_cannot_reopen_prompt(startup, monkeypatch, interrupt):
    results = []
    monkeypatch.setattr(update_manager, "_on_launch_result", lambda host, result: results.append(result))
    update_manager.check_for_updates_on_launch(startup.host)
    job = startup.host._startup_update_check.job
    if interrupt == "manual_signal":
        startup.lifecycle.manual_check_requested.emit()
    elif interrupt == "manual_menu":
        update_manager.check_for_updates_async(startup.host, silent=False, force=True)
    elif interrupt == "destroyed":
        startup.host.destroyed.emit()
        assert startup.lifecycle.manual_check_requested.callbacks == []
    else:
        startup.lifecycle.is_shutting_down = True

    # Also reject a result already queued before cancellation was observed.
    job.finished.emit(UpdateTaskResult(value=startup.result))

    assert results == []
    assert startup.host._startup_update_check.job is None
    if interrupt != "shutdown":
        assert job.cancelled


def test_shutdown_before_launch_timer_starts_no_worker(startup):
    update_manager.prepare_startup_update_check(startup.host)
    startup.lifecycle.is_shutting_down = True

    update_manager.check_for_updates_on_launch(startup.host)

    assert startup.jobs == []


def test_debounce_keeps_manual_force_available(startup, monkeypatch):
    monkeypatch.setattr(update_manager, "_should_skip_update_check", lambda: True)
    update_manager.check_for_updates_on_launch(startup.host)
    update_manager.check_for_updates_async(startup.host, silent=False, force=True)

    assert startup.jobs == [startup.host._startup_update_check.cache_job]
    assert startup.host._startup_update_check.job is None
    assert startup.shown == [{"auto_check": True}]


def test_startup_registration_is_idempotent(startup):
    first = update_manager.prepare_startup_update_check(startup.host)
    second = update_manager.prepare_startup_update_check(startup.host)

    assert first is second
    assert len(startup.lifecycle.manual_check_requested.callbacks) == 1
    assert len(startup.host.destroyed.callbacks) == 1


def test_cache_cleanup_is_deferred_and_receives_version_and_cancellation(startup, monkeypatch):
    calls = []
    monkeypatch.setattr(
        update_manager, "cleanup_update_cache",
        lambda version, **kwargs: calls.append((version, kwargs)),
    )
    update_manager.check_for_updates_on_launch(startup.host)
    state = startup.host._startup_update_check
    assert calls == []

    cancel = Event()
    state.cache_job.callback(lambda *_args: None, cancel)
    state.cache_job.finished.emit(UpdateTaskResult())
    update_manager.check_for_updates_on_launch(startup.host)

    assert calls == [(update_manager.APP_VERSION, {"cancel_event": cancel})]
    assert state.cache_job is None
    assert state.cache_started
    assert len(startup.jobs) == 2


def test_manual_check_does_not_cancel_independent_cache_housekeeping(startup):
    update_manager.check_for_updates_on_launch(startup.host)
    state = startup.host._startup_update_check

    startup.lifecycle.manual_check_requested.emit()

    assert state.job.cancelled
    assert not state.cache_job.cancelled


def test_destroyed_host_cancels_cache_housekeeping(startup):
    update_manager.check_for_updates_on_launch(startup.host)
    job = startup.host._startup_update_check.cache_job

    startup.host.destroyed.emit()

    assert job.cancelled


@pytest.mark.parametrize("cancelled", [False, True])
def test_cache_failure_is_only_logged_and_never_presented(startup, caplog, cancelled):
    update_manager.check_for_updates_on_launch(startup.host)
    state = startup.host._startup_update_check

    state.cache_job.finished.emit(UpdateTaskResult(error=OSError("cache unavailable"), cancelled=cancelled))

    assert state.cache_job is None
    assert startup.shown == []
    assert ("housekeeping could not complete" in caplog.text) is not cancelled


def test_pytest_startup_guard_does_not_schedule_cache_or_network(startup, monkeypatch):
    monkeypatch.setattr(update_manager, "_running_under_pytest", lambda: True)

    update_manager.check_for_updates_on_launch(startup.host)

    assert startup.jobs == []
