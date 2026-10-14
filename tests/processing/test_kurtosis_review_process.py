"""Resource models and lifecycle checks for Qt-free spawned QC preparation."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import logging
import os
from pathlib import Path
from queue import Queue
from threading import Event, get_ident
import time
from types import SimpleNamespace

import pytest

from Main_App.processing.kurtosis_review_scan import (
    KURTOSIS_REVIEW_FILE_STATUS_CLEAR,
    KURTOSIS_REVIEW_FILE_STATUS_ERROR,
    KurtosisReviewFileResult,
    KurtosisReviewScan,
)
from Main_App.workers import kurtosis_review_process as process_module

GIB = 1024**3


def _info(index: int, directory: Path) -> SimpleNamespace:
    return SimpleNamespace(
        path=directory / f"P{index}.bdf", subject_id=f"P{index}",
        recording_id=f"P{index}__session", session_id="session",
        session_label="Session", visit_index=1,
    )


def _result(info: SimpleNamespace, *, evidence=None) -> KurtosisReviewFileResult:
    return KurtosisReviewFileResult(
        path=info.path, participant_id=info.subject_id,
        recording_id=info.recording_id, session_id=info.session_id,
        session_label=info.session_label, visit_index=info.visit_index,
        status=KURTOSIS_REVIEW_FILE_STATUS_CLEAR, evidence=evidence,
    )


def _resource_model(monkeypatch, *, cpu: int, total: int, available: int, sizes: list[int]):
    monkeypatch.setattr(process_module.os, "cpu_count", lambda: cpu)
    monkeypatch.setattr(process_module.psutil, "virtual_memory", lambda: SimpleNamespace(total=total, available=available))
    paths = [SimpleNamespace(stat=lambda size=size: SimpleNamespace(st_size=size)) for size in sizes]
    monkeypatch.setattr(process_module, "Path", lambda value: value)
    return [SimpleNamespace(path=path) for path in paths]


@pytest.mark.parametrize(("cpu", "total_gib", "available_gib", "override", "expected"), [
    (1, 128, 112, None, 1),
    (2, 128, 112, None, 1),
    (8, 64, 48, None, 7),
    (24, 128, 112, None, 16),
    (24, 16, 10, None, 4),
    (24, 32, 20, None, 4),
    (24, 64, 48, None, 7),
    (24, 192, 160, None, 20),
    (24, 128, 112, 3, 3),
    (24, 128, 112, 20, 16),
    (24, 128, 112, 1, 1),
])
def test_worker_count_shares_main_cpu_ram_and_override_policy(monkeypatch, cpu, total_gib, available_gib, override, expected):
    infos = _resource_model(monkeypatch, cpu=cpu, total=total_gib * GIB, available=available_gib * GIB, sizes=[20] * 30)
    assert process_module.review_process_worker_count(infos, override) == expected


def test_worker_count_uses_largest_sources_and_available_memory(monkeypatch):
    infos = _resource_model(monkeypatch, cpu=24, total=128 * GIB, available=80 * GIB, sizes=[1, GIB, GIB])
    # Two 24 GiB estimates cannot share the 40 GiB budget, regardless of order.
    assert process_module.review_process_worker_count(infos) == 1
    infos = _resource_model(monkeypatch, cpu=24, total=128 * GIB, available=8 * GIB, sizes=[1] * 10)
    assert process_module.review_process_worker_count(infos) == 4


def test_worker_count_caps_files_and_has_serial_fallback(monkeypatch, tmp_path):
    infos = _resource_model(monkeypatch, cpu=24, total=128 * GIB, available=100 * GIB, sizes=[1] * 2)
    assert process_module.review_process_worker_count(infos) == 2
    assert process_module.review_process_worker_count([]) == 0
    infos = _resource_model(monkeypatch, cpu=24, total=128 * GIB, available=GIB, sizes=[1] * 2)
    assert process_module.review_process_worker_count(infos) == 1


def test_same_stems_are_safe_in_distinct_worker_processes(monkeypatch, tmp_path):
    monkeypatch.setattr(process_module.psutil, "virtual_memory", lambda: SimpleNamespace(total=128 * GIB, available=100 * GIB))
    monkeypatch.setattr(process_module.os, "cpu_count", lambda: 24)
    infos = []
    for index in range(4):
        directory = tmp_path / str(index)
        directory.mkdir()
        path = directory / "P1.bdf"
        path.write_bytes(b"source")
        infos.append(SimpleNamespace(path=path))
    assert process_module.review_process_worker_count(infos) == 4
    assert process_module.review_process_worker_count([SimpleNamespace(path=tmp_path / "missing.bdf")]) == 1


class _Messages(Queue):
    closed = False
    joined = False

    def close(self):
        self.closed = True

    def join_thread(self):
        self.joined = True


class _ThreadContext:
    def __init__(self):
        self.messages = _Messages()
        self.event = Event()

    def Event(self):
        return self.event

    def Queue(self, **_kwargs):
        return self.messages


class _ThreadExecutor(ThreadPoolExecutor):
    def __init__(self, *, max_workers, mp_context, initializer, initargs):
        assert initializer is process_module._review_worker_init
        assert mp_context.event is initargs[0]
        assert mp_context.messages is initargs[1]
        process_module._WORKER_CANCEL, process_module._WORKER_MESSAGES = initargs
        super().__init__(max_workers=max_workers)


def _thread_runner(monkeypatch, worker, *, workers=2):
    context = _ThreadContext()
    monkeypatch.setattr(process_module, "get_context", lambda method: context if method == "spawn" else None)
    monkeypatch.setattr(process_module, "ProcessPoolExecutor", _ThreadExecutor)
    monkeypatch.setattr(process_module, "review_process_worker_count", lambda _infos, _maximum: workers)
    monkeypatch.setattr(process_module, "_run_one_review", worker)
    return context


def test_out_of_order_work_preserves_input_order_callbacks_and_timing_logs(monkeypatch, tmp_path, caplog):
    callback_threads = []
    callback_indices = []
    settings_seen = []
    settings = {"frequency_protocol": "protocol", "scientific_parameter": 9, "_fpvs_kurtosis_checkpoint_should_cancel": lambda: False}

    def worker(info, actual_settings, *_args):
        settings_seen.append(actual_settings)
        process_module._emit_worker_message({"type": "progress", "message": f"Preparing {info.subject_id}"})
        process_module._emit_worker_message({"type": "log", "name": "Main_App.processing.kurtosis_review_scan", "level": logging.INFO, "message": f"kurtosis_review_timing file={info.path.name} stage=load elapsed_ms=1"})
        time.sleep(0.1 if info.subject_id == "P0" else 0.01)
        return KurtosisReviewScan((_result(info),))

    context = _thread_runner(monkeypatch, worker)
    caplog.set_level(logging.INFO)
    infos = [_info(index, tmp_path) for index in range(4)]
    scan = process_module.run_process_review(
        infos, settings, event_map={"Condition": 11},
        progress=lambda *_args: callback_threads.append(get_ident()),
        result_progress=lambda index, _results: (callback_indices.append(index), callback_threads.append(get_ident())),
    )
    assert [result.path for result in scan.results] == [info.path for info in infos]
    assert callback_indices[0] == 1
    assert set(callback_threads) == {get_ident()}
    assert settings_seen and all(value == {"frequency_protocol": "protocol", "scientific_parameter": 9} for value in settings_seen)
    assert "_fpvs_kurtosis_checkpoint_should_cancel" in settings
    assert "kurtosis_review_timing file=P0.bdf" in caplog.text
    assert context.messages.closed and context.messages.joined


def test_cancel_before_start_creates_no_pool(monkeypatch, tmp_path):
    monkeypatch.setattr(process_module, "ProcessPoolExecutor", lambda **_kwargs: pytest.fail("A cancelled scan must not create workers"))
    scan = process_module.run_process_review([_info(0, tmp_path)], {}, event_map={}, should_cancel=lambda: True)
    assert scan.cancelled and not scan.results
    empty = process_module.run_process_review([], {}, event_map={})
    assert not empty.cancelled and not empty.results


def test_cancellation_stops_submissions_and_waits_for_active_cleanup(monkeypatch, tmp_path):
    requested = Event()
    second_started = Event()
    second_closed = Event()
    started = []

    def worker(info, *_args):
        started.append(info.subject_id)
        if info.subject_id == "P0":
            assert second_started.wait(2)
            return KurtosisReviewScan((_result(info),))
        second_started.set()
        try:
            assert process_module._WORKER_CANCEL.wait(2)
            return KurtosisReviewScan((), cancelled=True)
        finally:
            second_closed.set()

    context = _thread_runner(monkeypatch, worker)
    scan = process_module.run_process_review(
        [_info(index, tmp_path) for index in range(5)], {}, event_map={},
        should_cancel=requested.is_set,
        result_progress=lambda _index, _results: requested.set(),
    )
    assert scan.cancelled
    assert [result.participant_id for result in scan.results] == ["P0"]
    assert set(started) == {"P0", "P1"}
    assert second_closed.is_set() and context.messages.closed and context.messages.joined


def test_worker_error_remains_recording_local_and_other_results_survive(monkeypatch, tmp_path):
    def worker(info, *_args):
        if info.subject_id == "P1":
            raise RuntimeError("injected child failure")
        return KurtosisReviewScan((_result(info),))

    _thread_runner(monkeypatch, worker)
    scan = process_module.run_process_review([_info(index, tmp_path) for index in range(3)], {}, event_map={})
    assert [result.participant_id for result in scan.results] == ["P0", "P1", "P2"]
    assert [result.status for result in scan.results] == [KURTOSIS_REVIEW_FILE_STATUS_CLEAR, KURTOSIS_REVIEW_FILE_STATUS_ERROR, KURTOSIS_REVIEW_FILE_STATUS_CLEAR]
    assert "injected child failure" in scan.errors[0].error


def test_submission_failure_is_accounted_for_without_losing_other_files(monkeypatch, tmp_path):
    class FailingSubmit(_ThreadExecutor):
        def submit(self, fn, info, *args):
            if info.subject_id == "P1":
                raise RuntimeError("injected submission failure")
            return super().submit(fn, info, *args)

    _thread_runner(monkeypatch, lambda info, *_args: KurtosisReviewScan((_result(info),)))
    monkeypatch.setattr(process_module, "ProcessPoolExecutor", FailingSubmit)
    scan = process_module.run_process_review([_info(index, tmp_path) for index in range(3)], {}, event_map={})
    assert [result.participant_id for result in scan.results] == ["P0", "P1", "P2"]
    assert "injected submission failure" in scan.errors[0].error


def test_startup_failure_closes_transport(monkeypatch, tmp_path):
    context = _thread_runner(monkeypatch, lambda info, *_args: KurtosisReviewScan((_result(info),)))

    def fail_start(**_kwargs):
        raise RuntimeError("injected startup failure")

    monkeypatch.setattr(process_module, "ProcessPoolExecutor", fail_start)
    with pytest.raises(RuntimeError, match="startup failure"):
        process_module.run_process_review([_info(0, tmp_path)], {}, event_map={})
    assert context.event.is_set() and context.messages.closed and context.messages.joined


def test_project_worker_override_is_used_unless_explicit_argument_wins(monkeypatch, tmp_path):
    context = _thread_runner(monkeypatch, lambda info, *_args: KurtosisReviewScan((_result(info),)))
    seen = []
    monkeypatch.setattr(process_module, "review_process_worker_count", lambda _infos, maximum: seen.append(maximum) or 1)
    process_module.run_process_review([_info(0, tmp_path)], {"max_parallel_workers_override": 3}, event_map={})
    assert seen == [3]
    # A fresh transport is needed after the preceding runner closed its queue.
    monkeypatch.setattr(process_module, "get_context", lambda _method: _ThreadContext())
    process_module.run_process_review([_info(0, tmp_path)], {"max_parallel_workers_override": 3}, event_map={}, max_workers=2)
    assert seen == [3, 2]
    assert context.messages.closed


def _spawn_probe(info, settings, *_args):
    """Tiny real-spawn task checks initializer, transport and child identity."""
    from threadpoolctl import threadpool_info
    from Main_App.workers import process_runner

    process_module._emit_worker_message({"type": "progress", "message": "Spawned probe ready"})
    return KurtosisReviewScan((_result(info, evidence={
        "pid": os.getpid(), "pools": threadpool_info(),
        "cache_owned": process_runner._WORKER_FIR_CACHE is not None,
        "scientific_setting": settings["scientific_setting"],
    }),))


def test_real_spawn_applies_existing_initializer_without_qt_or_eeg(monkeypatch, tmp_path):
    from threadpoolctl import threadpool_info

    parent_pools = threadpool_info()
    monkeypatch.setattr(process_module, "_run_one_review", _spawn_probe)
    monkeypatch.setattr(process_module, "review_process_worker_count", lambda _infos, _maximum: 2)
    scan = process_module.run_process_review(
        [_info(index, tmp_path) for index in range(3)], {"scientific_setting": 19}, event_map={},
    )
    assert len(scan.results) == 3 and not scan.cancelled and not scan.errors
    for result in scan.results:
        assert result.evidence["pid"] != os.getpid()
        assert result.evidence["cache_owned"]
        assert result.evidence["scientific_setting"] == 19
        assert result.evidence["pools"]
        assert all(pool["num_threads"] == 1 for pool in result.evidence["pools"])
    assert threadpool_info() == parent_pools
