"""Independent resource/lifecycle controls; no EEG processing or Qt execution."""

from dataclasses import dataclass
from queue import Queue
from threading import Event
from types import SimpleNamespace

import pytest

from Main_App.workers import processing_admission as admission
from Main_App.workers.review_resource_budget import (
    GIB, OwnedMemory, ReviewMemoryProbeError, ReviewMemorySnapshot,
)


class ControlQueue(Queue):
    def close(self):
        self.closed = True

    def cancel_join_thread(self):
        pass


class Context:
    Queue = ControlQueue
    Event = Event

    @staticmethod
    def Array(_kind, count, **_kwargs):
        return [0] * count


@dataclass(frozen=True)
class Estimate:
    healthy_bytes: int = 2 * GIB
    emergency_extra_bytes: int = 0

    def tail_bytes(self, channels, samples, sfreq):
        assert (channels, samples, sfreq) == (65, 1000, 256.0)
        return self.healthy_bytes + self.emergency_extra_bytes


@pytest.fixture
def setup(monkeypatch):
    snapshot = [ReviewMemorySnapshot(16 * GIB, 10 * GIB, 10 * GIB, True)]
    monkeypatch.setattr(admission, "probe_memory_snapshot", lambda: snapshot[0])
    monkeypatch.setattr(admission, "probe_owned_memory", lambda *_: OwnedMemory())

    def build(estimates):
        remaining = iter(estimates)
        monkeypatch.setattr(admission, "build_processing_estimate", lambda *_: next(remaining))
        return admission.ProcessingAdmission(list(range(len(estimates))), {}, {}, Context())

    return snapshot, build


def test_worker_floors_and_file_credits_limit_concurrency(setup):
    snapshot, build = setup
    state = build([Estimate()] * 4)
    state.reset_pool(3)
    for index in range(3):
        assert state.fits(index)
        state.submitted(index)
    # 3x2GiB jobs + 3x1GiB runtime + 1GiB Windows reserve already use10GiB.
    assert not state.fits(3)
    state.completed(0)
    snapshot[0] = ReviewMemorySnapshot(16 * GIB, 6 * GIB, 6 * GIB, True)
    assert not state.fits(3)
    state.completed(1)
    state.completed(2)
    assert state.next_population([3], 7) == (1, None)


def test_actual_commit_can_block_despite_free_physical_ram(setup):
    snapshot, build = setup
    state = build([Estimate()])
    snapshot[0] = ReviewMemorySnapshot(16 * GIB, 14 * GIB, 3 * GIB, True)
    assert not state.fits(0, population=1)
    snapshot[0] = ReviewMemorySnapshot(16 * GIB, 14 * GIB, 4 * GIB, True)
    assert state.fits(0, population=1)


def test_joint_group_reserves_the_largest_fallback_once(setup):
    snapshot, build = setup
    state = build([Estimate(2 * GIB, 2 * GIB)] * 3)
    snapshot[0] = ReviewMemorySnapshot(16 * GIB, 9 * GIB, 9 * GIB, True)
    assert state.next_population([0, 1, 2], 3) == (2, None)


@pytest.mark.parametrize(("physical", "commit", "reason"), [
    (3, 8, "physical_ram"), (8, 3, "windows_commit"), (3, 3, "physical_and_commit"),
])
def test_recorded_idle_shortfalls_use_native_credit_arithmetic(setup, physical, commit, reason):
    snapshot, build = setup
    state = build([Estimate()])
    snapshot[0] = ReviewMemorySnapshot(16 * GIB, physical * GIB, commit * GIB, True)
    assert state.next_population([0], 1) == (0, None)
    assert state.last_wait == admission.AdmissionWait(
        reason, snapshot[0], GIB if physical == 3 else 0, GIB if commit == 3 else 0,
    )


def test_required_commit_probe_failure_is_actionable(setup):
    snapshot, build = setup
    snapshot[0] = ReviewMemorySnapshot(16 * GIB, 10 * GIB, None, True)
    with pytest.raises(ReviewMemoryProbeError, match="headroom"):
        build([Estimate()])


def test_physical_owned_pages_do_not_earn_private_commit_credit(monkeypatch, setup):
    snapshot, build = setup
    state = build([Estimate()])
    state.reset_pool(1)
    state.submitted(0)
    state.workers[123] = (100.0, 0)
    monkeypatch.setattr(admission, "probe_owned_memory", lambda *_: OwnedMemory(3 * GIB, 0))
    snapshot[0] = ReviewMemorySnapshot(16 * GIB, GIB, GIB, True)
    assert not state.fits()
    monkeypatch.setattr(admission, "probe_owned_memory", lambda *_: OwnedMemory(3 * GIB, 3 * GIB))
    assert state.fits()


def test_idle_workers_retain_floor_without_borrowing_old_file_credit(monkeypatch, setup):
    snapshot, build = setup
    state = build([Estimate(), Estimate()])
    state.reset_pool(2)
    state.workers[123] = (100.0, 0)
    monkeypatch.setattr(admission, "probe_owned_memory", lambda *_: OwnedMemory(8 * GIB, 8 * GIB))
    snapshot[0] = ReviewMemorySnapshot(16 * GIB, 3 * GIB, 3 * GIB, True)
    assert not state.fits(1)  # idle excess cannot finance the next worker's arrays


@pytest.mark.parametrize("estimate", [None, Estimate(20 * GIB)])
def test_unknown_or_overconservative_file_retains_exclusive_native_path(setup, estimate):
    _, build = setup
    state = build([estimate, Estimate()])
    assert state.exclusive[0]
    assert state.next_population([0, 1], 7) == (1, 0)
    state.reset_pool(1, 0)
    state.submitted(0)
    assert not state.fits(1, population=2)
    state.completed(0)
    state.reset_pool(1)
    assert state.fits(1)


def test_healthy_singleton_does_not_require_hypothetical_source_rate_tail(setup):
    snapshot, build = setup
    state = build([Estimate(2 * GIB, 6 * GIB)])
    snapshot[0] = ReviewMemorySnapshot(16 * GIB, 8 * GIB, 8 * GIB, True)
    assert state.next_population([0], 7) == (1, 0)


def test_only_one_source_rate_borrower_runs_until_its_file_completes(setup):
    snapshot, build = setup
    snapshot[0] = ReviewMemorySnapshot(32 * GIB, 30 * GIB, 30 * GIB, True)
    state = build([Estimate(2 * GIB, 4 * GIB)] * 2)
    state.reset_pool(2)
    state.submitted(0)
    state.submitted(1)
    for index in range(2):
        state.events.put({"type": "request", "index": index, "required_bytes": 6 * GIB})
    state.grant_waiting()
    assert state.emergency_owner == 0
    assert state.grant_status == [1, 0]
    assert state.requests == {1: 6 * GIB}
    state.completed(0)
    state.grant_waiting()
    assert state.emergency_owner == 1
    assert state.grant_status == [1, 1]


def test_existing_borrower_can_top_up_for_later_export_phase(setup):
    snapshot, build = setup
    snapshot[0] = ReviewMemorySnapshot(32 * GIB, 30 * GIB, 30 * GIB, True)
    state = build([Estimate(2 * GIB, 6 * GIB)])
    state.reset_pool(1)
    state.submitted(0)
    for required in (4 * GIB, 8 * GIB):
        state.events.put({"type": "request", "index": 0, "required_bytes": required})
        state.grant_waiting()
        assert state.active[0] == required
        assert state.emergency_owner == 0


@pytest.mark.parametrize("required,extra,status", [(9 * GIB, 0, -1), (16 * GIB, 20 * GIB, -2)])
def test_uncovered_or_physically_impossible_actual_phase_is_signalled(setup, required, extra, status):
    _, build = setup
    state = build([Estimate(2 * GIB, extra)])
    state.reset_pool(1)
    state.submitted(0)
    state.events.put({"type": "request", "index": 0, "required_bytes": required})
    state.grant_waiting()
    assert state.grant_status[0] == status
    assert state.grant_events[0].is_set()
    assert state.requests == {}


def test_stale_worker_identity_does_not_earn_memory_credit(setup):
    snapshot, build = setup
    state = build([Estimate()])
    state.reset_pool(1)
    state.submitted(0)
    state.workers[123] = (100.0, 0)
    snapshot[0] = ReviewMemorySnapshot(16 * GIB, 2 * GIB, 2 * GIB, True)
    assert not state.fits()  # probe_owned_memory returns no matching ownership


def test_first_fit_skips_a_large_file_without_crossing_exclusive_work(setup):
    _, build = setup
    state = build([Estimate(2 * GIB), Estimate(7 * GIB), Estimate(GIB), None, Estimate(GIB)])
    state.reset_pool(3)
    state.submitted(0)
    assert state.first_fitting([1, 2, 3, 4]) == 1
    assert state.first_fitting([1, 3, 4]) is None
    state.completed(0)
    state.reset_pool(1)
    assert state.first_fitting([1, 3, 4]) == 0


def test_final_tail_releases_prefix_and_keeps_resident_memory_charged(monkeypatch, setup):
    snapshot, build = setup
    state = build([Estimate(5 * GIB, 2 * GIB), Estimate(3 * GIB)])
    state.reset_pool(2)
    state.submitted(0)
    state.workers[123] = (100.0, 0)
    snapshot[0] = ReviewMemorySnapshot(16 * GIB, 9 * GIB, 9 * GIB, True)
    monkeypatch.setattr(admission, "probe_owned_memory", lambda *_: OwnedMemory(GIB, GIB))
    assert not state.fits(1)
    monkeypatch.setattr(Estimate, "tail_bytes", lambda _, *shape: 2 * GIB)
    child = admission.ProcessingWorkerAdmission(*state.initializer_args())
    child.index, child.credit = 0, 5 * GIB
    child.before_tail(SimpleNamespace(ch_names=["Cz"], n_times=250, info={"sfreq": 250.}))
    state.drain()
    assert state.active[0] == child.credit == 2 * GIB and state.final_tails == {0}
    assert state.fits(1)
    snapshot[0] = ReviewMemorySnapshot(16 * GIB, 7 * GIB, 7 * GIB, True)
    assert not state.fits(1)  # credit left from the prefix cannot subsidize another file
    state.completed(0)
    state.events.put({"type": "tail", "index": 0, "shape": (1, 250, 250.)})
    state.drain()
    assert not state.active and not state.final_tails


def test_delayed_reused_worker_start_reserves_unresolved_floors(monkeypatch, setup):
    snapshot, build = setup
    state = build([Estimate()] * 4)
    state.reset_pool(2)
    state.workers = {123: (100.0, 0), 456: (101.0, 1)}
    monkeypatch.setattr(admission, "probe_owned_memory", lambda *_: OwnedMemory(GIB, GIB))
    state.submitted(2)  # no started message yet; both old identities look idle
    snapshot[0] = ReviewMemorySnapshot(16 * GIB, 6 * GIB, 6 * GIB, True)
    assert not state.fits(3)  # 2x2GiB + 2floors + 1reserve exceeds6GiB
    state.events.put({"type": "started", "index": 2, "pid": 123, "created": 100.0})
    assert state.fits(3)


def test_cancelled_child_stops_waiting_and_close_releases_control_queue(setup):
    _, build = setup
    state = build([Estimate(2 * GIB, GIB)])
    child = admission.ProcessingWorkerAdmission(*state.initializer_args())
    child.index, child.credit = 0, 2 * GIB
    state.close()
    with pytest.raises(InterruptedError, match="cancelled"):
        child.request(3 * GIB)
    assert state.events.closed


def test_child_phase_checks_leave_exclusive_native_file_unmodified(setup):
    _, build = setup
    state = build([None])
    child = admission.ProcessingWorkerAdmission(*state.initializer_args())
    child.index = 0
    child.before_notch(0, 0, 0.0)
    child.before_kurtosis(1, 10, 1, 10)
    child.before_tail(object())  # no Raw reads at all on an unbounded native path
    assert state.events.empty()


def test_deferred_notch_requests_credit_before_scoring_and_checks_actual_grid(monkeypatch):
    estimate = SimpleNamespace(
        deferred_notch_bytes=8 * GIB,
        geometry=SimpleNamespace(loaded_channels=67, source_n_times=8000, source_rate_hz=2048.0),
    )
    child = admission.ProcessingWorkerAdmission(ControlQueue(), (Event(),), [0], Event(), (estimate,), (False,))
    child.index = 0
    requested = []
    monkeypatch.setattr(child, "request", requested.append)
    child.before_notch(65, 8000, 2048.0)
    with pytest.raises(MemoryError, match="validated memory reservation"):
        child.before_notch(65, 8001, 2048.0)
    assert requested == [8 * GIB]


@pytest.mark.parametrize("samples,expected", [(8000, 20 * GIB), (1000, 10 * GIB)])
def test_source_scoring_reserves_later_cache_and_repairs_before_tail(monkeypatch, samples, expected):
    estimate = SimpleNamespace(
        healthy_bytes=10 * GIB, source_rate_phase_bytes=20 * GIB,
        builtin_kurtosis=True,
        geometry=SimpleNamespace(source_n_times=8000, source_rate_hz=2048.0, target_rate_hz=256.0),
    )
    child = admission.ProcessingWorkerAdmission(ControlQueue(), (Event(),), [0], Event(), (estimate,), (False,))
    child.index, child.credit = 0, 10 * GIB
    requested = []
    monkeypatch.setattr(child, "request", requested.append)
    child.before_kurtosis(65, samples, 64, samples, False, 0)
    assert requested == [expected]


@pytest.mark.parametrize("rate,expected", [(2048.0, 20 * GIB), (256.0, 10 * GIB)])
def test_unconditional_finish_checks_shape_and_whole_file_credit(monkeypatch, rate, expected):
    checked = []

    def tail(channels, samples, sfreq):
        checked.append((channels, samples, sfreq))
        return 5 * GIB

    estimate = SimpleNamespace(healthy_bytes=10 * GIB, source_rate_phase_bytes=20 * GIB,
                               geometry=SimpleNamespace(source_rate_hz=2048.0), tail_bytes=tail)
    child = admission.ProcessingWorkerAdmission(ControlQueue(), (Event(),), [0], Event(), (estimate,), (False,))
    child.index, child.credit = 0, 10 * GIB
    requested = []
    monkeypatch.setattr(child, "request", requested.append)
    raw = SimpleNamespace(ch_names=list(range(65)), n_times=8000, info={"sfreq": rate})
    child.before_finish(raw)
    assert checked == [(65, 8000, rate)]
    assert requested == [expected]


def test_finish_rejects_uncharacterized_shape_before_repair_or_cache(monkeypatch):
    def invalid(*_shape):
        raise ValueError("uncharacterized shape")

    estimate = SimpleNamespace(healthy_bytes=10 * GIB, source_rate_phase_bytes=20 * GIB,
                               geometry=SimpleNamespace(source_rate_hz=2048.0), tail_bytes=invalid)
    child = admission.ProcessingWorkerAdmission(ControlQueue(), (Event(),), [0], Event(), (estimate,), (False,))
    child.index = 0
    requested = []
    monkeypatch.setattr(child, "request", requested.append)
    with pytest.raises(ValueError, match="uncharacterized"):
        child.before_finish(SimpleNamespace(ch_names=["A"], n_times=1, info={"sfreq": 128.0}))
    assert not requested
