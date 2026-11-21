from concurrent.futures import Future
import json
from types import SimpleNamespace

import pytest

from Tools.LORETA_Visualizer.source_producers import source_psd_workers as workers


def _record(number):
    return SimpleNamespace(fif_sha256=f"{number:064x}", channel_names=("Cz",), n_times=4096)


def _cells(records, callback):
    return workers.source_psd_cells(
        records, project=SimpleNamespace(preprocessing={"max_parallel_workers_override": 16}), root="unused",
        model=SimpleNamespace(forward_model=SimpleNamespace(source_points=(0,)), info={}, inverse_operator={}),
        config=SimpleNamespace(source_orientation_mode="cortical_normal"), numerical_metadata={"model": 1},
        method_metadata={"method": 1}, frequency_metadata={"bins": [1]}, before_record=callback,
    )


def test_source_cell_order_duplicate_cache_and_first_error(monkeypatch):
    first, second, third = [_record(index) for index in (1, 2, 3)]
    stored = set()
    submitted = []
    callbacks = []

    class FakePool:
        def __init__(self, **kwargs):
            assert kwargs["max_workers"] == 16

        def shutdown(self, *, wait, cancel_futures):
            assert wait and cancel_futures

        def submit(self, function, record):
            submitted.append(record.fif_sha256)
            future = Future()
            future.set_result((17, 0.5, 1.5, ({}, record.fif_sha256)))
            return future

    def lookup(*, project_root, prepared):
        if json.loads(prepared.payload)["derivative_checksum_sha256"] == third.fif_sha256:
            raise ValueError("unreadable third source")
        return SimpleNamespace(hit=prepared.digest in stored)

    monkeypatch.setattr(workers, "compute_dynamic_worker_ceiling", lambda requested: requested)
    monkeypatch.setattr(workers, "_batch_capacity", lambda ceiling, *args: ceiling)
    monkeypatch.setattr(workers, "ProcessPoolExecutor", FakePool)
    monkeypatch.setattr(workers, "_load_prepared_source_psd_entry", lookup)
    seen = []
    with _cells([first, second, first, third], lambda index, _record: callbacks.append(index)) as cells:
        with pytest.raises(ValueError, match="unreadable third"):
            for record, key, lookup_result, computed in cells:
                seen.append((record.fif_sha256, lookup_result.hit))
                if not lookup_result.hit:
                    assert computed[1] == record.fif_sha256
                    stored.add(key.cache_key)
    assert callbacks == [1, 2, 3, 4]
    assert submitted == [first.fif_sha256, second.fif_sha256]
    assert seen == [(first.fif_sha256, False), (second.fif_sha256, False), (first.fif_sha256, True)]


def test_source_cell_admission_keeps_commit_reserve(monkeypatch):
    from Main_App.workers.review_resource_budget import ReviewMemorySnapshot

    config = SimpleNamespace(source_orientation_mode="vector_norm")
    record = _record(1)
    for available, expected in [(None, 1), (9 * 1024**3, 1), (120 * 1024**3, 16)]:
        monkeypatch.setattr(
            workers, "probe_memory_snapshot",
            lambda available=available: ReviewMemorySnapshot(128 * 1024**3, 120 * 1024**3, available, True),
        )
        assert workers._batch_capacity(16, [record], 1024, config, {"required_bin_indices": [1]}, 0) == expected
    for snapshot in (
        ReviewMemorySnapshot(None, 1, 1, True),
        ReviewMemorySnapshot(128 * 1024**3, None, None, False),
    ):
        monkeypatch.setattr(workers, "probe_memory_snapshot", lambda snapshot=snapshot: snapshot)
        assert workers._batch_capacity(16, [record], 1024, config, {"required_bin_indices": [1]}, 0) == 1


def test_source_cell_admission_accounts_for_later_large_derivative(monkeypatch):
    from Main_App.workers.review_resource_budget import ReviewMemorySnapshot

    free = 20 * 1024**3
    monkeypatch.setattr(workers, "probe_memory_snapshot", lambda: ReviewMemorySnapshot(free, free, free, True))
    small = _record(1)
    large = SimpleNamespace(n_times=262144, channel_names=("Cz",))
    config = SimpleNamespace(source_orientation_mode="cortical_normal")
    assert workers._batch_capacity(16, [small], 2048, config, {}, 0) > 1
    assert workers._batch_capacity(16, [small, large], 2048, config, {}, 0) == 1
