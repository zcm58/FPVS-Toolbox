"""Actual native values remain exact across the optional admission boundary."""

from pathlib import Path
from concurrent.futures import Future, ProcessPoolExecutor
from multiprocessing import get_context
import os
from threading import Event, Timer
from queue import Empty, Queue
import time
from types import SimpleNamespace

import pytest
import psutil
from threadpoolctl import threadpool_limits

from Main_App.processing import preprocess
from Main_App.processing.prepared_raw_codec import encode_state, raw_state
from Main_App.processing.kurtosis_review_scan import (
    KURTOSIS_REVIEW_FILE_STATUS_CLEAR,
    KurtosisReviewFileResult,
    KurtosisReviewScan,
)
from Main_App.workers import kurtosis_review_process as process_module
from Main_App.workers.review_resource_budget import (
    OwnedMemory, ReviewMemoryProbeError, ReviewMemorySnapshot,
)
from tests.processing.test_preprocess_kurtosis_gate import _params, _raw


def _source():
    raw = _raw()
    raw._data[-1, 0] = 1.0
    raw._data[-1, 100:601:50] = 55.0
    # Keep explicit signed zeros in the actual native source payload.
    raw._data[3, 47] = -0.0
    return raw


def _bits(value):
    arrays = {}
    encoded = encode_state(value, arrays)
    return encoded, {
        name: (array.dtype.str, array.shape, array.strides, array.tobytes())
        for name, array in arrays.items()
    }


def _capture(source: Path, *, callback=None, checkpoint=False):
    params = _params(source)
    params.update(
        downsample_rate=80.0,
        project_root=str(source.parent),
        enable_kurtosis_checkpoint_cache=checkpoint,
    )
    raw = _source()
    try:
        kwargs = {} if callback is None else {"before_kurtosis_scoring": callback}
        prepared = preprocess.prepare_kurtosis_review_evidence(
            raw, params, lambda *_: None, source.name, copy_raw=False, **kwargs,
        )
        return _bits({
            "prepared": prepared,
            "raw": {"state": raw_state(raw), "samples": raw._data},
        })
    finally:
        raw.close()


def test_permitted_admission_keeps_full_native_array_and_scientific_metadata_bits(tmp_path):
    source = tmp_path / "P001.bdf"
    source.write_bytes(b"Immutable in-memory native EEG fixture")
    requests = []
    with threadpool_limits(limits=1):
        before = _capture(source)
        after = _capture(source, callback=lambda *request: requests.append(request))
    assert after == before
    assert len(requests) == 1
    assert requests[0][:3] == (21, 800, 20)
    assert 0 < requests[0][3] <= 800
    assert requests[0][4:] == (False, 0)


def test_supported_resample_failure_requests_full_rate_credit_and_preserves_values(tmp_path, monkeypatch):
    source = tmp_path / "P001.bdf"
    source.write_bytes(b"Immutable source for the native resample-error route")

    def unavailable_resample(*_args, **_kwargs):
        raise MemoryError("Injected native allocation failure")

    monkeypatch.setattr(preprocess, "resample_raw", unavailable_resample)
    requests = []
    with threadpool_limits(limits=1):
        before = _capture(source)
        after = _capture(source, callback=lambda *request: requests.append(request))
    assert after == before
    assert len(requests) == 1
    assert requests[0][:3] == (21, 1000, 20)
    assert requests[0][3] > 0
    assert requests[0][4:] == (False, 0)


def test_warm_native_checkpoint_still_observes_admission_before_scoring_copy(tmp_path):
    source = tmp_path / "P001.bdf"
    source.write_bytes(b"Immutable source for actual native checkpoint reuse")
    cold_requests, warm_requests = [], []
    with threadpool_limits(limits=1):
        _capture(source, checkpoint=True, callback=lambda *request: cold_requests.append(request))
        baseline = _capture(source, checkpoint=True)
        actual = _capture(source, checkpoint=True, callback=lambda *request: warm_requests.append(request))
    assert actual == baseline
    assert len(cold_requests) == len(warm_requests) == 1
    assert cold_requests[0][4:] == (False, 0)
    assert warm_requests[0][:3] == (21, 800, 20)
    assert warm_requests[0][4:] == (True, 184_000)


def test_rejected_admission_never_enters_native_scoring_data_allocation(tmp_path, monkeypatch):
    source = tmp_path / "P001.bdf"
    source.write_bytes(b"Immutable source for cooperative admission cancellation")
    entered = []

    def no_scoring(*_args, **_kwargs):
        entered.append(True)
        pytest.fail("An interrupted grant must precede every analyzed-data allocation.")

    def interrupted(*_request):
        raise InterruptedError("Resource wait cancelled")

    monkeypatch.setattr(preprocess, "_kurtosis_scoring_data", no_scoring)
    with threadpool_limits(limits=1), pytest.raises(RuntimeError):
        _capture(source, callback=interrupted)
    assert entered == []


_SPAWN_CONFIGURATION = None
_SPAWN_BARRIER = None
_SPAWN_STARTED = None
_SPAWN_IN_SCORING = None
_SPAWN_PEAK = None
_SPAWN_FOLDER = None
_SPAWN_BORROW_HOLD = None
_OWNED_PROCESSES = []


def _initialize_transport_probe(cancel, messages, grants, status, credits, exclusive,
                                barrier, started, in_scoring, peak, folder, borrow_hold=None):
    global _SPAWN_BARRIER, _SPAWN_STARTED, _SPAWN_IN_SCORING, _SPAWN_PEAK, _SPAWN_FOLDER
    global _SPAWN_BORROW_HOLD
    process_module._review_worker_init(cancel, messages, grants, status, credits, exclusive)
    _SPAWN_BARRIER, _SPAWN_STARTED = barrier, started
    _SPAWN_IN_SCORING, _SPAWN_PEAK, _SPAWN_FOLDER = in_scoring, peak, Path(folder)
    _SPAWN_BORROW_HOLD = borrow_hold


class _TransportExecutor(ProcessPoolExecutor):
    def __init__(self, **kwargs):
        kwargs["initializer"] = _initialize_transport_probe
        kwargs["initargs"] = (*kwargs["initargs"], *_SPAWN_CONFIGURATION)
        super().__init__(**kwargs)

    def submit(self, *args, **kwargs):
        future = super().submit(*args, **kwargs)
        for process in self._processes.values():
            if process not in _OWNED_PROCESSES:
                _OWNED_PROCESSES.append(process)
        return future


def _transport_fallback_probe(info, settings, *_args, job_index=None):
    process = psutil.Process()
    process_module._send_control_message({
        "type": "worker_started", "job_index": job_index,
        "pid": process.pid, "created": process.create_time(),
    })
    with _SPAWN_STARTED.get_lock():
        _SPAWN_STARTED.value += 1
    (_SPAWN_FOLDER / f"started-{job_index}").write_text(str(os.getpid()))
    entered = False
    try:
        _SPAWN_BARRIER.wait(timeout=25)
        if settings.get("crash_job") == job_index:
            os._exit(27)
        process_module._request_scoring_admission(job_index, 1, 100, 1, 100, False, 0)
        with _SPAWN_IN_SCORING.get_lock():
            _SPAWN_IN_SCORING.value += 1
            _SPAWN_PEAK.value = max(_SPAWN_PEAK.value, _SPAWN_IN_SCORING.value)
            entered = True
        # This is only transport ownership, with no real EEG allocation.
        time.sleep(0.01)
        result = KurtosisReviewFileResult(
            path=info.path, participant_id=info.subject_id,
            recording_id=info.recording_id,
            session_id=info.session_id, session_label=info.session_label,
            visit_index=info.visit_index,
            status=KURTOSIS_REVIEW_FILE_STATUS_CLEAR,
            evidence={"pid": os.getpid(), "grant": int(process_module._WORKER_GRANT_STATUS[job_index])},
        )
        return KurtosisReviewScan((result,))
    except InterruptedError:
        return KurtosisReviewScan((), cancelled=True)
    finally:
        if entered:
            with _SPAWN_IN_SCORING.get_lock():
                _SPAWN_IN_SCORING.value -= 1
        (_SPAWN_FOLDER / f"closed-{job_index}").write_text("released")


def _transport_case(monkeypatch, tmp_path, count):
    global _SPAWN_CONFIGURATION
    _OWNED_PROCESSES.clear()
    context = get_context("spawn")
    started, in_scoring, peak = [context.Value("i", 0) for _ in range(3)]
    _SPAWN_CONFIGURATION = (context.Barrier(count), started, in_scoring, peak, str(tmp_path))
    credit = 1024**2
    plan = process_module._ReviewResourcePlan(
        count, 112 * 1024**3, (credit,) * count,
        estimates=(None,) * count, exclusive=(False,) * count,
        emergency_bytes=20 * 1024**2, dynamic=True,
    )
    monkeypatch.setattr(process_module, "_review_resource_plan", lambda *_a, **_kw: plan)
    monkeypatch.setattr(process_module, "ProcessPoolExecutor", _TransportExecutor)
    monkeypatch.setattr(process_module, "_run_one_review", _transport_fallback_probe)
    monkeypatch.setattr(process_module, "probe_memory_snapshot", lambda: ReviewMemorySnapshot(
        128 * 1024**3, 112 * 1024**3, 112 * 1024**3, True,
    ))
    monkeypatch.setattr(process_module, "probe_owned_memory", lambda *_a: OwnedMemory())
    infos = [SimpleNamespace(
        path=tmp_path / f"P{index}.bdf", subject_id=f"P{index}",
        recording_id=f"P{index}__session", session_id="session",
        session_label="Session", visit_index=1,
    ) for index in range(count)]
    return infos, started, in_scoring, peak


def _assert_transport_released():
    assert _OWNED_PROCESSES
    assert all(not process.is_alive() for process in _OWNED_PROCESSES)


def test_real_twelve_worker_all_fallback_transport_progresses_one_borrower_at_a_time(
    monkeypatch, tmp_path,
):
    infos, started, in_scoring, peak = _transport_case(monkeypatch, tmp_path, 12)
    watchdog_cancel = Event()
    watchdog = Timer(50, watchdog_cancel.set)
    watchdog.start()
    try:
        scan = process_module.run_process_review(
            infos, {}, event_map={}, max_workers=12,
            should_cancel=watchdog_cancel.is_set,
        )
    finally:
        watchdog.cancel()
    assert not watchdog_cancel.is_set(), "Emergency requests deadlocked."
    assert not scan.cancelled and not scan.errors
    assert started.value == 12
    assert peak.value == 1 and in_scoring.value == 0
    assert [result.recording_id for result in scan.results] == [info.recording_id for info in infos]
    assert len({result.evidence["pid"] for result in scan.results}) == 12
    assert all(result.evidence["grant"] == 1 for result in scan.results)
    assert len(list(tmp_path.glob("closed-*"))) == 12
    _assert_transport_released()


def test_real_waiting_resource_requests_cancel_and_release_all_owners(monkeypatch, tmp_path):
    infos, started, in_scoring, _peak = _transport_case(monkeypatch, tmp_path, 4)
    watchdog_cancel = Event()
    watchdog = Timer(40, watchdog_cancel.set)
    watchdog.start()
    try:
        scan = process_module.run_process_review(
            infos, {}, event_map={},
            should_cancel=lambda: started.value == 4 or watchdog_cancel.is_set(),
        )
    finally:
        watchdog.cancel()
    assert not watchdog_cancel.is_set()
    assert scan.cancelled and in_scoring.value == 0
    assert len(list(tmp_path.glob("closed-*"))) == 4
    _assert_transport_released()


def test_real_worker_crash_does_not_leave_other_grant_waiters_or_children_alive(monkeypatch, tmp_path):
    infos, started, _in_scoring, _peak = _transport_case(monkeypatch, tmp_path, 3)
    watchdog_cancel = Event()
    watchdog = Timer(40, watchdog_cancel.set)
    watchdog.start()
    try:
        scan = process_module.run_process_review(
            infos, {"crash_job": 0}, event_map={}, should_cancel=watchdog_cancel.is_set,
        )
    finally:
        watchdog.cancel()
    assert not watchdog_cancel.is_set()
    assert started.value == 3
    assert scan.errors
    # A terminated process cannot execute Python finally; process teardown
    # must still release the other queued grant waiters and their OS handles.
    _assert_transport_released()


def test_real_pool_admission_recovers_to_twelve_after_background_memory_pressure(
    monkeypatch, tmp_path,
):
    infos, started, _in_scoring, _peak = _transport_case(monkeypatch, tmp_path, 12)
    observed = []

    def changing_headroom():
        # Decline before any new Raw owner is created; recovery must use the
        # existing twelve-process ceiling instead of freezing a smaller pool.
        available = 4 * 1024**3 if len(observed) < 3 else 112 * 1024**3
        observed.append(available)
        return ReviewMemorySnapshot(128 * 1024**3, available, 112 * 1024**3, True)

    monkeypatch.setattr(process_module, "probe_memory_snapshot", changing_headroom)
    watchdog_cancel = Event()
    watchdog = Timer(50, watchdog_cancel.set)
    watchdog.start()
    try:
        scan = process_module.run_process_review(infos, {}, event_map={}, should_cancel=watchdog_cancel.is_set)
    finally:
        watchdog.cancel()
    assert not watchdog_cancel.is_set()
    assert observed[:3] == [4 * 1024**3] * 3
    assert len(scan.results) == started.value == 12
    assert not scan.errors and not scan.cancelled
    _assert_transport_released()


@pytest.mark.parametrize("kind", ["missing_commit", "os_failure"])
def test_failed_live_memory_probe_is_a_bounded_technical_failure_with_transport_closed(
    monkeypatch, tmp_path, kind,
):
    infos, _started, _in_scoring, _peak = _transport_case(monkeypatch, tmp_path, 1)

    def unavailable():
        if kind == "os_failure":
            raise OSError("Injected live OS probe failure")
        return ReviewMemorySnapshot(128 * 1024**3, 112 * 1024**3, None, True)

    monkeypatch.setattr(process_module, "probe_memory_snapshot", unavailable)
    with pytest.raises(ReviewMemoryProbeError):
        process_module.run_process_review(infos, {}, event_map={})
    # Admission fails before spawn; no owners or grant waiters may escape.
    assert not _OWNED_PROCESSES


def _partial_reserve_probe(info, _settings, *_args, job_index=None):
    process = psutil.Process()
    process_module._send_control_message({
        "type": "worker_started", "job_index": job_index,
        "pid": process.pid, "created": process.create_time(),
    })
    entered = False
    try:
        if job_index < 3:
            _SPAWN_BARRIER.wait(timeout=25)
        if job_index == 0 or job_index >= 3:
            samples = 100 if job_index == 0 else 4_000_000
            process_module._request_scoring_admission(job_index, 1, samples, 1, samples, False, 0)
            with _SPAWN_IN_SCORING.get_lock():
                _SPAWN_IN_SCORING.value += 1
                _SPAWN_PEAK.value = max(_SPAWN_PEAK.value, _SPAWN_IN_SCORING.value)
                entered = True
            if job_index == 0:
                while not _SPAWN_BORROW_HOLD.wait(0.1):
                    if process_module._WORKER_CANCEL.is_set():
                        raise InterruptedError("Partial borrower cancelled")
            else:
                time.sleep(0.01)
        result = KurtosisReviewFileResult(
            path=info.path, participant_id=info.subject_id,
            recording_id=info.recording_id,
            session_id=info.session_id, session_label=info.session_label,
            visit_index=info.visit_index,
            status=KURTOSIS_REVIEW_FILE_STATUS_CLEAR,
        )
        return KurtosisReviewScan((result,))
    except InterruptedError:
        return KurtosisReviewScan((), cancelled=True)
    finally:
        if entered:
            with _SPAWN_IN_SCORING.get_lock():
                _SPAWN_IN_SCORING.value -= 1
        (_SPAWN_FOLDER / f"closed-{job_index}").write_text("released")


def _run_partial_reserve_case(monkeypatch, tmp_path, *, restore_old_zeroing):
    global _SPAWN_CONFIGURATION
    context = get_context("spawn")
    _OWNED_PROCESSES.clear()
    started, in_scoring, peak = [context.Value("i", 0) for _ in range(3)]
    borrow_hold = context.Event()
    _SPAWN_CONFIGURATION = (
        context.Barrier(3), started, in_scoring, peak, str(tmp_path), borrow_hold,
    )
    small_credit, large_credit, full_reserve = 1024**2, 120 * 1024**2, 100 * 1024**2
    credits = (small_credit, small_credit, small_credit, large_credit, large_credit)
    plan = process_module._ReviewResourcePlan(
        3, 3 * 1024**3 + 145 * 1024**2, credits,
        estimates=(None,) * 5, exclusive=(False,) * 5,
        emergency_bytes=full_reserve, dynamic=True,
    )
    monkeypatch.setattr(process_module, "_review_resource_plan", lambda *_a, **_kw: plan)
    monkeypatch.setattr(process_module, "ProcessPoolExecutor", _TransportExecutor)
    monkeypatch.setattr(process_module, "_run_one_review", _partial_reserve_probe)
    monkeypatch.setattr(process_module, "probe_owned_memory", lambda *_a: OwnedMemory())

    def live_snapshot():
        # Host margin is1GiB and the created pool's three floors total3GiB.
        # Only145MiB of additional allocations fit while the small owner is
        # active. External headroom recovers after that owner closes.
        payload = 512 if (tmp_path / "closed-0").exists() else 145
        return ReviewMemorySnapshot(8 * 1024**3, 4 * 1024**3 + payload * 1024**2,
                                    8 * 1024**3, True)

    monkeypatch.setattr(process_module, "probe_memory_snapshot", live_snapshot)
    native_fits = process_module.memory_admission_fits
    partial_reserves, restored_reserves, premature_admissions = [], [], []
    candidate_checks = 0

    def observe_admission(snapshot, **arguments):
        nonlocal candidate_checks
        partial = arguments["active_credits"].get(0, 0) == 17_827_392
        candidate = arguments["candidate_credit"] == large_credit
        if partial:
            if restore_old_zeroing:
                # Exact old bug: a partial emergency borrower/prospective
                # grant made the entire global reserve available to others.
                arguments["emergency_reserve"] = 0
            partial_reserves.append(arguments["emergency_reserve"])
        if candidate and 0 not in arguments["active_credits"] and (tmp_path / "closed-0").exists():
            restored_reserves.append(arguments["emergency_reserve"])
        admitted = native_fits(snapshot, **arguments)
        constrained = snapshot.physical_available_bytes == 4 * 1024**3 + 145 * 1024**2
        if candidate and partial and constrained:
            # Recovery can precede Future delivery: admission with the full
            # residual reservation is legitimate once physical RAM returns.
            # Only the declared constrained snapshot tests the reserve loan.
            premature_admissions.append(admitted)
            candidate_checks += 1
            # Keep two rejecting observations for the repaired implementation.
            # The intentional old bug can fill the pool after one erroneous
            # admission, so release on that causal defect observation rather
            # than waiting for a second check the full pool cannot make.
            if candidate_checks >= 2 or (restore_old_zeroing and admitted):
                borrow_hold.set()
        return admitted

    monkeypatch.setattr(process_module, "memory_admission_fits", observe_admission)
    infos = [SimpleNamespace(
        path=tmp_path / f"P{index}.bdf", subject_id=f"P{index}",
        recording_id=f"P{index}__session", session_id="session",
        session_label="Session", visit_index=1,
    ) for index in range(5)]
    watchdog_cancel = Event()
    watchdog = Timer(40, watchdog_cancel.set)
    watchdog.start()
    try:
        scan = process_module.run_process_review(infos, {}, event_map={},
                                                  should_cancel=watchdog_cancel.is_set)
    finally:
        watchdog.cancel()
        borrow_hold.set()
    assert not watchdog_cancel.is_set(), "Unequal fallback reservations deadlocked."
    assert not scan.cancelled and not scan.errors
    assert [result.recording_id for result in scan.results] == [info.recording_id for info in infos]
    assert len(list(tmp_path.glob("closed-*"))) == 5
    assert peak.value == 1 and in_scoring.value == 0
    _assert_transport_released()
    return partial_reserves, restored_reserves, premature_admissions


def test_unequal_emergency_delta_retains_unused_reserve_then_restores_it_after_cleanup(monkeypatch, tmp_path):
    partial, restored, admitted = _run_partial_reserve_case(
        monkeypatch, tmp_path, restore_old_zeroing=False,
    )
    # Global100MiB reserve minus(17,827,392 -1,048,576) borrowed bytes.
    # This literal expectation is independent of production accounting.
    assert partial and set(partial) == {88_078_784}
    assert admitted and not any(admitted)
    assert restored and 100 * 1024**2 in restored


def test_old_zero_reserve_negative_control_exposes_premature_healthy_admission(monkeypatch, tmp_path):
    partial, _restored, admitted = _run_partial_reserve_case(
        monkeypatch, tmp_path, restore_old_zeroing=True,
    )
    assert partial and set(partial) == {0}
    assert any(admitted), "The regression must detect the historical unused-reserve loan."
    # The injected defect may admit both later jobs before owner 0 closes, or
    # let a new borrower claim the reserve before the next candidate check.
    # Exact restoration is asserted by the repaired positive control above;
    # this negative control asserts the causal premature admission and cleanup.


@pytest.mark.parametrize("restore_old_transient_floor", [False, True])
def test_future_completion_before_delayed_worker_identity_keeps_pool_floors_reserved(
    monkeypatch, tmp_path, restore_old_transient_floor,
):
    # Futures and the separate reliable queue have no shared delivery order.
    # This context delays worker_started until all three Futures have already
    # been accepted, reproducing that ordering without timing assumptions.
    class DelayedMessages(Queue):
        release = False
        closed = False
        joined = False
        delivered = 0

        def get_nowait(self):
            if not self.release:
                raise Empty
            value = super().get_nowait()
            self.delivered += 1
            return value

        def close(self):
            self.closed = True

        def join_thread(self):
            self.joined = True

    class Context:
        def __init__(self):
            self.messages = DelayedMessages()

        def Event(self):
            return Event()

        def Queue(self, **_kwargs):
            return self.messages

        def Array(self, _type, values):
            return list(values)

    context = Context()
    pools = []

    class CompletedExecutor:
        closed = False

        def __init__(self, **_kwargs):
            pools.append(self)

        def submit(self, _function, info, *_args, job_index=None):
            context.messages.put({
                "type": "worker_started", "job_index": job_index,
                "pid": 12340 + job_index, "created": 10.0,
            })
            result = KurtosisReviewFileResult(
                path=info.path, participant_id=info.subject_id,
                recording_id=info.recording_id,
                session_id=info.session_id, session_label=info.session_label,
                visit_index=info.visit_index,
                status=KURTOSIS_REVIEW_FILE_STATUS_CLEAR,
            )
            future = Future()
            future.set_result(KurtosisReviewScan((result,)))
            return future

        def shutdown(self, **_kwargs):
            self.closed = True

    small, large, emergency = 1024**2, 120 * 1024**2, 100 * 1024**2
    plan = process_module._ReviewResourcePlan(
        3, 3 * 1024**3 + 145 * 1024**2, (small, small, small, large),
        estimates=(None,) * 4, exclusive=(False,) * 4,
        emergency_bytes=emergency, dynamic=True,
    )
    monkeypatch.setattr(process_module, "_review_resource_plan", lambda *_a, **_kw: plan)
    monkeypatch.setattr(process_module, "get_context", lambda _method: context)
    monkeypatch.setattr(process_module, "ProcessPoolExecutor", CompletedExecutor)
    monkeypatch.setattr(process_module, "probe_owned_memory", lambda *_a: pytest.fail("Completed jobs' delayed identity must not earn owned-memory credit."))
    native_wait = process_module.wait

    def complete_before_messages(*args, **kwargs):
        completed = native_wait(*args, **kwargs)
        context.messages.release = True
        return completed

    monkeypatch.setattr(process_module, "wait", complete_before_messages)
    recovered = False

    def snapshot():
        payload = 512 if recovered else 145
        return ReviewMemorySnapshot(8 * 1024**3, 4 * 1024**3 + payload * 1024**2,
                                    8 * 1024**3, True)

    monkeypatch.setattr(process_module, "probe_memory_snapshot", snapshot)
    native_fits = process_module.memory_admission_fits
    first_after_completion = []

    def observe(snapshot, **arguments):
        nonlocal recovered
        late_pending = not arguments["active_credits"] and arguments["candidate_credit"] == large
        if late_pending and restore_old_transient_floor:
            # Historical race had no known workers and no current credits;
            # only the prospective one-worker floor was counted.
            arguments["worker_count"] = 1
        admitted = native_fits(snapshot, **arguments)
        if late_pending and not first_after_completion:
            first_after_completion.append((arguments["worker_count"], admitted))
            recovered = True
        return admitted

    monkeypatch.setattr(process_module, "memory_admission_fits", observe)
    infos = [SimpleNamespace(
        path=tmp_path / f"P{index}.bdf", subject_id=f"P{index}",
        recording_id=f"P{index}__session", session_id="session",
        session_label="Session", visit_index=1,
    ) for index in range(4)]
    watchdog_cancel = Event()
    watchdog = Timer(5, watchdog_cancel.set)
    watchdog.start()
    try:
        scan = process_module.run_process_review(infos, {}, event_map={},
                                                  should_cancel=watchdog_cancel.is_set)
    finally:
        watchdog.cancel()
    assert not watchdog_cancel.is_set()
    assert not scan.cancelled and not scan.errors and len(scan.results) == 4
    assert context.messages.delivered == 4
    assert context.messages.closed and context.messages.joined
    assert pools and all(pool.closed for pool in pools)
    assert first_after_completion == ([(1, True)] if restore_old_transient_floor else [(3, False)])
