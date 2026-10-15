"""Independent public scheduling and real scalar IPC controls, without EEG I/O."""

from concurrent.futures import Future
from copy import deepcopy
from dataclasses import replace
from multiprocessing import get_context
from queue import Queue
from threading import Event
import time
from types import SimpleNamespace

import pytest

from Main_App.workers import process_runner as runner
from Main_App.workers import processing_admission as admission_module
from Main_App.workers.review_resource_budget import OwnedMemory, ReviewMemorySnapshot


GIB = 1024**3


class _Messages(Queue):
    closed = False

    def close(self):
        self.closed = True

    def cancel_join_thread(self):
        pass


class _Context:
    def __init__(self):
        self.messages = _Messages()

    def Queue(self):
        return self.messages

    def Event(self):
        return Event()

    def Array(self, _type, count, **_kwargs):
        return [0] * count


def _estimate():
    return SimpleNamespace(healthy_bytes=2 * GIB, emergency_extra_bytes=GIB)


def _controller(monkeypatch, tmp_path, *, snapshot, unknown=(), count=4):
    context, pools, submissions, lifecycle = _Context(), [], [], []
    params = runner.RunParams(
        tmp_path, [tmp_path / f"P{i}.bdf" for i in range(count)],
        {"sentinel": [1, -0.0, "unchanged"]}, {"A": 21, "B": 22}, tmp_path, 3,
    )

    class Pool:
        def __init__(self, **kwargs):
            assert all(pool.closed for pool in pools), "Resize must drain and close the former pool."
            self.population, self.closed, self._processes = kwargs["max_workers"], False, {}
            pools.append(self)
            lifecycle.append(("create", self.population))

        def submit(self, function, path, settings, event_map, save_folder, project_root, index):
            assert function is runner._process_admitted_file
            future = Future()
            future.path = path
            submissions.append((path, deepcopy(settings), deepcopy(event_map), self.population))
            lifecycle.append(("submit", path.name))
            return future

        def shutdown(self, **_kwargs):
            self.closed = True
            lifecycle.append(("shutdown", self.population))

    def complete(futures, **_kwargs):
        done = set(futures)
        for future in done:
            if not future.done():
                future.set_result({"file": str(future.path), "status": "ok", "audit": {}})
                lifecycle.append(("complete", future.path.name))
        return done, set()

    monkeypatch.setattr(admission_module, "build_processing_estimate", lambda path, *_:
                        None if path.name in unknown else _estimate())
    monkeypatch.setattr(admission_module, "probe_memory_snapshot", snapshot)
    monkeypatch.setattr(admission_module, "probe_owned_memory", lambda *_: OwnedMemory())
    monkeypatch.setattr(runner, "get_context", lambda _method: context)
    monkeypatch.setattr(runner, "compute_dynamic_worker_ceiling", lambda _: 3)
    monkeypatch.setattr(runner, "ProcessPoolExecutor", Pool)
    monkeypatch.setattr(runner, "wait", complete)
    monkeypatch.setattr(runner, "_memory_ok", lambda _: (True, 20.0))
    monkeypatch.setattr(runner, "_scavenge_stale_memmaps", lambda: None)
    monkeypatch.setattr(runner, "_condition_repair_sources_for_files", lambda *_: {})
    monkeypatch.setattr(runner, "reconcile_condition_interpolation_sources", lambda *_a, **_k: ({}, []))
    monkeypatch.setattr(runner, "_with_current_condition_repairs", lambda settings, *_a, **_k: dict(settings))
    return params, context, pools, submissions, lifecycle


@pytest.mark.parametrize("recover", [False, True])
def test_fresh_pressure_before_first_enqueue_recovers_or_cancels(monkeypatch, tmp_path, recover):
    probes = 0
    cancel = Event()

    def snapshot():
        nonlocal probes
        probes += 1
        if probes >= 8 and not recover:
            cancel.set()
        return ReviewMemorySnapshot(16 * GIB, (12 if recover and probes >= 8 else 1) * GIB,
                                    12 * GIB, True)

    params, context, pools, submissions, _ = _controller(monkeypatch, tmp_path, snapshot=snapshot)
    messages = Queue()
    outcome = runner.run_project_parallel(params, messages, cancel)
    assert probes >= 8
    assert context.messages.closed and all(pool.closed for pool in pools)
    assert [row for row in messages.queue if row["type"] == "done"] == [outcome]
    if recover:
        assert outcome["status"] == "success" and len(submissions) == 4
    else:
        assert outcome["status"] == "cancelled" and not submissions
        assert outcome["interrupted_files"] == [str(path) for path in params.data_files]


def test_public_scheduler_preserves_source_order_and_worker_payloads(monkeypatch, tmp_path):
    def snapshot():
        return ReviewMemorySnapshot(32 * GIB, 24 * GIB, 24 * GIB, True)
    params, context, pools, submissions, _ = _controller(monkeypatch, tmp_path, snapshot=snapshot)
    original_settings, original_events = deepcopy(params.settings), deepcopy(params.event_map)
    outcome = runner.run_project_parallel(params, Queue())
    assert outcome["status"] == "success" and outcome["count"] == 4
    assert [row[0] for row in submissions] == params.data_files
    assert all(row[1] == original_settings and row[2] == original_events for row in submissions)
    assert params.settings == original_settings and params.event_map == original_events
    assert context.messages.closed and all(pool.closed for pool in pools)


def test_unknown_middle_file_drains_and_runs_exclusively_then_pool_recovers(monkeypatch, tmp_path):
    def snapshot():
        return ReviewMemorySnapshot(32 * GIB, 24 * GIB, 24 * GIB, True)
    params, context, pools, submissions, lifecycle = _controller(
        monkeypatch, tmp_path, snapshot=snapshot, unknown={"P1.bdf"},
    )
    outcome = runner.run_project_parallel(params, Queue())
    assert outcome["status"] == "success"
    assert [row[0] for row in submissions] == params.data_files
    assert [row[3] for row in submissions] == [3, 1, 3, 3]
    assert lifecycle.index(("complete", "P0.bdf")) < lifecycle.index(("submit", "P1.bdf"))
    assert lifecycle.index(("complete", "P1.bdf")) < lifecycle.index(("submit", "P2.bdf"))
    assert context.messages.closed and all(pool.closed for pool in pools)


@pytest.mark.parametrize("recovered_available,expected_population", [
    (28 * GIB, 12),
    (11 * GIB // 2, 3),
])
def test_staggered_completions_drain_reduced_pool_after_full_or_partial_recovery(
    monkeypatch, tmp_path, recovered_available, expected_population,
):
    def snapshot():
        # With a 2-GiB host margin and 1-GiB runtime floors, 4.5 GiB
        # supports two 128-MiB jobs but cannot create a three-worker pool.
        available = 9 * GIB // 2 if len(submissions) < 2 else recovered_available
        return ReviewMemorySnapshot(32 * GIB, available, available, True)

    params, context, pools, submissions, lifecycle = _controller(
        monkeypatch, tmp_path, snapshot=snapshot, count=14,
    )
    params = replace(params, max_workers=12)
    monkeypatch.setattr(runner, "compute_dynamic_worker_ceiling", lambda _: 12)
    monkeypatch.setattr(admission_module, "build_processing_estimate", lambda *_:
                        SimpleNamespace(healthy_bytes=GIB // 8, emergency_extra_bytes=0))

    def complete_one(futures, **_kwargs):
        # Completing every future together hides the starvation: the former
        # controller refilled a small pool after each staggered completion.
        pending = list(futures)
        future = pending[0]
        future.set_result({"file": str(future.path), "status": "ok", "audit": {}})
        lifecycle.append(("complete", future.path.name))
        return {future}, set(pending[1:])

    monkeypatch.setattr(runner, "wait", complete_one)
    original_settings, original_events = deepcopy(params.settings), deepcopy(params.event_map)
    messages = Queue()
    outcome = runner.run_project_parallel(params, messages)

    assert outcome["status"] == "success" and outcome["count"] == 14
    assert [pool.population for pool in pools] == [2, expected_population]
    third_submission = lifecycle.index(("submit", "P2.bdf"))
    assert lifecycle.index(("complete", "P0.bdf")) < third_submission
    assert lifecycle.index(("complete", "P1.bdf")) < third_submission
    assert lifecycle.index(("shutdown", 2)) < lifecycle.index(("create", expected_population))
    assert [row[3] for row in submissions] == [2, 2] + [expected_population] * 12
    assert [row[0] for row in submissions] == params.data_files
    assert all(row[1] == original_settings and row[2] == original_events for row in submissions)
    assert params.settings == original_settings and params.event_map == original_events
    assert [row for row in messages.queue if row["type"] == "done"] == [outcome]
    assert context.messages.closed and all(pool.closed for pool in pools)


def _request_in_spawned_child(arguments, result_queue):
    worker = admission_module.ProcessingWorkerAdmission(*arguments)
    worker.start(0)
    worker.request(3 * GIB)
    result_queue.put(("granted", worker.credit))


def test_real_spawn_queue_event_and_shared_status_grant_then_release_child(monkeypatch, tmp_path):
    context = get_context("spawn")
    monkeypatch.setattr(admission_module, "build_processing_estimate", lambda *_: _estimate())
    monkeypatch.setattr(admission_module, "probe_memory_snapshot", lambda:
                        ReviewMemorySnapshot(16 * GIB, 12 * GIB, 12 * GIB, True))
    monkeypatch.setattr(admission_module, "probe_owned_memory", lambda *_: OwnedMemory())
    admission = admission_module.ProcessingAdmission([tmp_path / "synthetic.bdf"], {}, {}, context)
    result_queue = context.Queue()
    child = context.Process(target=_request_in_spawned_child,
                            args=(admission.initializer_args(), result_queue))
    admission.population = 1
    admission.submitted(0)
    try:
        child.start()
        deadline = time.monotonic() + 20
        while child.is_alive() and time.monotonic() < deadline:
            admission.grant_waiting()
            child.join(timeout=0.01)
        assert not child.is_alive(), "Synthetic grant transport failed to make progress."
        assert child.exitcode == 0
        assert result_queue.get(timeout=2) == ("granted", 3 * GIB)
        assert admission.grant_status[0] == 1 and admission.grant_events[0].is_set()
    finally:
        admission.cancel_event.set()
        if child.pid is not None:
            child.join(timeout=1)
            if child.is_alive():
                child.terminate()
                child.join(timeout=2)
        admission.close()
        result_queue.close()
        result_queue.join_thread()
    assert not child.is_alive()
