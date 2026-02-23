from __future__ import annotations

import numpy as np

from Main_App.Performance import process_runner


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

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def submit(self, _fn, file_path, *_args, **_kwargs):
        fut = _FakeFuture({"status": "ok", "file": str(file_path), "audit": {"n_rejected": 0}})
        self.submitted.append(fut)
        return fut


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


def test_nan_to_num_inplace_equivalence_for_kurtosis_vector():
    k_values = np.array([np.nan, np.inf, -np.inf, 1.25, -2.5], dtype=np.float64)

    expected = np.nan_to_num(k_values.copy())

    actual_source = k_values.copy()
    actual = np.nan_to_num(actual_source, copy=False)

    np.testing.assert_allclose(actual, expected)
    # copy=False should still preserve shape/dtype semantics used downstream.
    assert actual.shape == expected.shape
    assert actual.dtype == expected.dtype
