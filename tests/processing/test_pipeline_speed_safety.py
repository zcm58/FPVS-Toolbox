from __future__ import annotations

import numpy as np

from Main_App.workers import process_runner


class _FakeFuture:
    def __init__(self, result_payload):
        self._result_payload = result_payload
        self._done = False
        self._cancelled = False

    def done(self):
        return self._done

    def result(self):
        return self._result_payload

    def cancel(self):
        self._cancelled = True


class _FakeExecutor:
    def __init__(self, *_, **__):
        self.submitted = []
        self._processes = {}
        self.shutdown_calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def submit(self, _fn, file_path, *_args, **_kwargs):
        fut = _FakeFuture({"status": "ok", "file": str(file_path), "audit": {"n_rejected": 0}})
        self.submitted.append(fut)
        return fut

    def shutdown(self, *, wait=True, cancel_futures=False):
        self.shutdown_calls.append({"wait": wait, "cancel_futures": cancel_futures})


class _FakeProcess:
    def __init__(self):
        self.terminated = False
        self.killed = False
        self.join_timeouts = []

    def is_alive(self):
        return not self.terminated and not self.killed

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True

    def join(self, timeout=None):
        self.join_timeouts.append(timeout)


class _ManualCancel:
    def __init__(self):
        self.cancelled = False

    def is_set(self):
        return self.cancelled


class _FakeQueue:
    def __init__(self):
        self.items = []

    def put(self, item):
        self.items.append(item)


def test_memory_throttle_does_not_block_harvest(monkeypatch, tmp_path):
    files = [tmp_path / "a.bdf", tmp_path / "b.bdf"]
    params = process_runner.RunParams(
        project_root=tmp_path,
        data_files=files,
        settings={},
        event_map={},
        save_folder=tmp_path,
        max_workers=2,
        memory_soft_limit_ratio=0.85,
        memory_check_interval_s=0.25,
    )

    fake_pool = _FakeExecutor()
    monkeypatch.setattr(process_runner, "ProcessPoolExecutor", lambda *a, **k: fake_pool)

    memory_reads = iter([(True, 40.0), (False, 96.0), (False, 95.0), (True, 50.0), (True, 51.0)])
    monkeypatch.setattr(process_runner, "_memory_ok", lambda _limit: next(memory_reads))

    wait_calls = {"count": 0}

    def _fake_wait(futures, return_when, timeout):
        wait_calls["count"] += 1
        if wait_calls["count"] == 1:
            return set(), set()
        for fut in futures:
            if not fut.done():
                fut._done = True
                return {fut}, set()
        return set(), set()

    monkeypatch.setattr(process_runner, "wait", _fake_wait)

    sleep_calls = []
    monkeypatch.setattr(process_runner.time, "sleep", lambda secs: sleep_calls.append(secs))

    process_runner.run_project_parallel(params)

    assert wait_calls["count"] >= 2
    # New behavior: memory gating is non-blocking; outer loop handles backoff.
    assert 0.25 not in sleep_calls
    assert all(s >= 0.01 for s in sleep_calls)


def test_cancel_event_terminates_active_workers_without_waiting(monkeypatch, tmp_path):
    files = [tmp_path / "a.bdf", tmp_path / "b.bdf"]
    params = process_runner.RunParams(
        project_root=tmp_path,
        data_files=files,
        settings={},
        event_map={},
        save_folder=tmp_path,
        max_workers=1,
    )

    fake_proc = _FakeProcess()
    fake_pool = _FakeExecutor()
    fake_pool._processes = {1234: fake_proc}
    monkeypatch.setattr(process_runner, "ProcessPoolExecutor", lambda *a, **k: fake_pool)
    monkeypatch.setattr(process_runner, "_memory_ok", lambda _limit: (True, 40.0))
    cancel_event = _ManualCancel()

    def _fake_wait(futures, return_when, timeout):
        cancel_event.cancelled = True
        return set(), set()

    monkeypatch.setattr(process_runner, "wait", _fake_wait)

    queue = _FakeQueue()

    process_runner.run_project_parallel(params, queue, cancel_event)

    assert fake_pool.submitted
    assert fake_pool.submitted[0]._cancelled
    assert fake_proc.terminated
    assert fake_pool.shutdown_calls == [{"wait": False, "cancel_futures": True}]
    assert queue.items[-1]["type"] == "done"
    assert queue.items[-1]["cancelled"] is True
    assert queue.items[-1]["count"] == 0
    assert queue.items[-1]["interrupted_files"] == [str(files[0]), str(files[1])]


def test_nan_to_num_inplace_equivalence_for_kurtosis_vector():
    k_values = np.array([np.nan, np.inf, -np.inf, 1.25, -2.5], dtype=np.float64)

    expected = np.nan_to_num(k_values.copy())

    actual_source = k_values.copy()
    actual = np.nan_to_num(actual_source, copy=False)

    np.testing.assert_allclose(actual, expected)
    # copy=False should still preserve shape/dtype semantics used downstream.
    assert actual.shape == expected.shape
    assert actual.dtype == expected.dtype
