"""Fault injection at the public controller boundary, without Qt or EEG I/O."""

from concurrent.futures import Future
from queue import Queue
from threading import Event

import pytest

from Main_App.workers import process_runner as runner


class Executor:
    def __init__(self, *, fail_submit=None, fail_shutdown=False, pending=False):
        self.fail_submit = fail_submit
        self.fail_shutdown = fail_shutdown
        self.pending = pending
        self.submitted = []
        self.shutdown_calls = []
        self._processes = {}

    def submit(self, function, path, *args):
        if len(self.submitted) == self.fail_submit:
            raise RuntimeError("submit failed")
        future = Future()
        if not self.pending:
            future.set_result({"file": str(path), "status": "ok", "audit": {}})
        self.submitted.append(future)
        return future

    def shutdown(self, **kwargs):
        self.shutdown_calls.append(kwargs)
        if self.fail_shutdown:
            raise RuntimeError("shutdown failed")


@pytest.fixture
def run(monkeypatch, tmp_path):
    params = runner.RunParams(tmp_path, [tmp_path / f"p{i}.bdf" for i in range(3)], {}, {}, tmp_path, 2)
    monkeypatch.setattr(runner, "_memory_ok", lambda _: (True, 20.0))
    monkeypatch.setattr(runner, "_scavenge_stale_memmaps", lambda: None)

    def invoke(pool=None, cancel_event=None):
        if pool is not None:
            monkeypatch.setattr(runner, "ProcessPoolExecutor", lambda **_: pool)
        queue = Queue()
        outcome = runner.run_project_parallel(params, queue, cancel_event)
        messages = list(queue.queue)
        terminal = [msg for msg in messages if msg["type"] == "done"]
        assert terminal == [outcome]
        assert messages[-1] is outcome
        return outcome

    return params, invoke


@pytest.mark.parametrize("stage", ["setup", "pool", "shutdown", "cleanup"])
def test_controller_failures_always_emit_one_terminal_outcome(monkeypatch, run, stage):
    params, invoke = run
    pool = Executor(fail_shutdown=stage == "shutdown")
    monkeypatch.setattr(runner, "ProcessPoolExecutor", lambda **_: pool)

    def fail(*args, **kwargs):
        raise RuntimeError(f"{stage} failed")

    if stage == "setup":
        monkeypatch.setattr(runner, "reconcile_condition_interpolation_sources", fail)
    elif stage == "pool":
        monkeypatch.setattr(runner, "ProcessPoolExecutor", fail)
    elif stage == "cleanup":
        monkeypatch.setattr(runner, "_scavenge_stale_memmaps", fail)
    outcome = invoke()
    assert outcome["status"] == "error"
    assert f"{stage} failed" in outcome["controller_error"]
    expected_completed = 3 if stage in {"shutdown", "cleanup"} else 0
    assert outcome["count"] == len(outcome["results"]) == expected_completed
    assert len(outcome["interrupted_files"]) == 3 - expected_completed
    assert not outcome["cancelled"]


@pytest.mark.parametrize("fail_submit", [0, 1, 2])
def test_submit_failure_preserves_completed_futures_and_unsubmitted_files(run, fail_submit):
    params, invoke = run
    pool = Executor(fail_submit=fail_submit)
    outcome = invoke(pool)
    assert outcome["status"] == "error"
    assert outcome["count"] == fail_submit
    assert {result["file"] for result in outcome["results"]} == {str(path) for path in params.data_files[:fail_submit]}
    assert outcome["interrupted_files"] == [str(path) for path in params.data_files[fail_submit:]]
    assert [result["file"] for result in outcome["errors"]] == outcome["interrupted_files"]
    assert pool.shutdown_calls == [{"wait": False, "cancel_futures": True}]


def test_worker_failure_keeps_other_results_and_completes_once(run):
    _, invoke = run
    pool = Executor()
    submit = pool.submit

    def failing_file(function, path, *args):
        future = submit(function, path, *args)
        if len(pool.submitted) == 1:
            future = Future()
            future.set_exception(RuntimeError("worker failed"))
        return future

    pool.submit = failing_file
    outcome = invoke(pool)
    assert outcome["status"] == "error"
    assert outcome["controller_error"] == ""
    assert len(outcome["results"]) == 2
    assert outcome["errors"][0]["error"] == "worker failed"
    assert outcome["interrupted_files"] == []


def test_cancel_retains_completed_results_and_identifies_interrupted_files(monkeypatch, run):
    params, invoke = run
    pool = Executor(pending=True)
    event = Event()

    def cancel_during_wait(futures, **kwargs):
        future = next(iter(futures))
        future.set_result({"file": str(params.data_files[0]), "status": "ok"})
        event.set()
        return set(), set()

    monkeypatch.setattr(runner, "wait", cancel_during_wait)
    outcome = invoke(pool, event)
    assert outcome["status"] == "cancelled"
    assert outcome["count"] == 1
    assert outcome["results"][0]["file"] == str(params.data_files[0])
    assert outcome["interrupted_files"] == [str(path) for path in params.data_files[1:]]
    assert pool.shutdown_calls == [{"wait": False, "cancel_futures": True}]


def test_success_has_one_terminal_snapshot(run):
    _, invoke = run
    outcome = invoke(Executor())
    assert outcome["status"] == "success"
    assert outcome["count"] == 3
    assert outcome["errors"] == outcome["interrupted_files"] == []


def test_system_exit_is_an_error_for_queued_controller(monkeypatch, run):
    _, invoke = run

    def exit_controller(**kwargs):
        raise SystemExit("unexpected exit")

    monkeypatch.setattr(runner, "ProcessPoolExecutor", exit_controller)
    outcome = invoke()
    assert outcome["status"] == "error"
    assert "SystemExit" in outcome["controller_error"]
