"""Qt-free scheduling controls: no EEG source, preprocessing, or benchmark."""

from dataclasses import replace
from pathlib import Path
from threading import Barrier, Lock
import time
from types import SimpleNamespace

import pytest

from Main_App.processing import preflight_qc as module
from Main_App.processing.processing_controller import RawFileInfo
from Main_App.projects import FrequencyProtocol
from Main_App.projects.experimental_qc_settings import RawSpectralScreeningSettings
from Main_App.workers.review_resource_budget import ReviewGeometry, ReviewMemorySnapshot


GIB = 1024**3


def test_preflight_uses_effective_affinity_instead_of_machine_logical_count(monkeypatch):
    from Main_App.workers import mp_env

    monkeypatch.setattr(mp_env.os, "process_cpu_count", lambda: 24, raising=False)
    monkeypatch.setattr(mp_env.psutil, "Process", lambda: SimpleNamespace(cpu_affinity=lambda: [0, 1, 2, 3]))
    assert module.preflight_worker_count(30, 12) == 3


def _snapshot(total=16, available=10, commit=10):
    return ReviewMemorySnapshot(total * GIB, available * GIB,
                                None if commit is None else commit * GIB, True)


def _infos(tmp_path, count):
    return [RawFileInfo(tmp_path / f"P{index}.bdf", f"P{index}", "group")
            for index in range(count)]


def _result(info):
    return module.PreflightQcFileResult(
        path=Path(info.path), participant_id=info.subject_id, group_id=info.group,
        load_error=None, raw_channel_qc=None, raw_spectral_qc=None,
    )


def _install(monkeypatch, *, snapshot, credit, scan):
    monkeypatch.setattr(module, "compute_dynamic_worker_ceiling", lambda requested: requested or 23)
    monkeypatch.setattr(module, "probe_memory_snapshot", snapshot)
    monkeypatch.setattr(module, "_preflight_memory_credit", credit)
    monkeypatch.setattr(module, "_scan_one_preflight_file", scan)


def _run(tmp_path, count, *, workers=6, cancel=None, progress=None):
    return module.scan_preprocessing_qc(
        _infos(tmp_path, count), {}, project_root=tmp_path, event_map={"A": 1},
        max_workers=workers, should_cancel=cancel, progress=progress,
    )


@pytest.mark.parametrize("total,available,expected", [(16, 10, 2), (32, 24, 5)])
def test_live_memory_sizes_six_cpu_slots_without_a_ram_tier(monkeypatch, tmp_path, total, available, expected):
    lock, barrier = Lock(), Barrier(expected, timeout=3)
    active = peak = starts = 0

    def scan(info, *_args, **_kwargs):
        nonlocal active, peak, starts
        with lock:
            active += 1
            peak = max(peak, active)
            starts += 1
            first_wave = starts <= expected
        try:
            if first_wave:
                barrier.wait()
            time.sleep(0.005)
            return _result(info)
        finally:
            with lock:
                active -= 1

    _install(monkeypatch, snapshot=lambda: _snapshot(total, available, available),
             credit=lambda *_a, **_k: 4 * GIB, scan=scan)
    result = _run(tmp_path, 6)
    assert not result.cancelled and len(result.results) == 6
    assert peak == expected
    assert [row.participant_id for row in result.results] == [f"P{i}" for i in range(6)]


def test_windows_commit_can_reduce_admissions_with_physical_ram_available(monkeypatch, tmp_path):
    active = peak = 0
    lock = Lock()

    def scan(info, *_args, **_kwargs):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        try:
            time.sleep(0.005)
            return _result(info)
        finally:
            with lock:
                active -= 1

    _install(monkeypatch, snapshot=lambda: _snapshot(32, 28, 7),
             credit=lambda *_a, **_k: 4 * GIB, scan=scan)
    result = _run(tmp_path, 3)
    assert peak == 1 and len(result.results) == 3


def test_pressure_before_first_enqueue_recovers_without_dropping_pending_work(monkeypatch, tmp_path):
    probes, calls, messages = 0, [], []

    def snapshot():
        nonlocal probes
        probes += 1
        return _snapshot(16, 2 if probes < 3 else 12, 12)

    def scan(info, *_args, **_kwargs):
        assert probes >= 3
        calls.append(info.subject_id)
        return _result(info)

    _install(monkeypatch, snapshot=snapshot, credit=lambda *_a, **_k: 4 * GIB, scan=scan)
    result = _run(tmp_path, 2, progress=lambda message, *_: messages.append(message))
    assert not result.cancelled and len(result.results) == 2
    assert sorted(calls) == ["P0", "P1"]
    assert messages.count("Waiting for preflight memory headroom") == 1


@pytest.mark.parametrize("unknown", [None, 100 * GIB])
def test_unknown_or_over_host_bound_runs_alone_between_known_jobs(monkeypatch, tmp_path, unknown):
    lock = Lock()
    active = set()
    visits = []

    def scan(info, *_args, **_kwargs):
        with lock:
            active.add(info.subject_id)
            if "P1" in active:
                assert active == {"P1"}
            visits.append(info.subject_id)
        try:
            time.sleep(0.005)
            return _result(info)
        finally:
            with lock:
                active.remove(info.subject_id)

    _install(monkeypatch, snapshot=lambda: _snapshot(16, 12, 12),
             credit=lambda info, *_a, **_k: unknown if info.subject_id == "P1" else 4 * GIB,
             scan=scan)
    result = _run(tmp_path, 4)
    assert len(result.results) == 4 and not result.cancelled
    assert visits.index("P0") < visits.index("P1") < visits.index("P2")


def test_cancellation_while_no_job_can_fit_returns_without_scanning(monkeypatch, tmp_path):
    probes = 0

    def snapshot():
        nonlocal probes
        probes += 1
        return _snapshot(16, 1, 1)

    _install(monkeypatch, snapshot=snapshot, credit=lambda *_a, **_k: 4 * GIB,
             scan=lambda *_a, **_k: pytest.fail("A blocked file must not be enqueued."))
    result = _run(tmp_path, 2, cancel=lambda: probes >= 3)
    assert result.cancelled and not result.results and probes == 3


def test_missing_required_commit_fails_actionably_even_for_one_worker(monkeypatch, tmp_path):
    _install(monkeypatch, snapshot=lambda: _snapshot(16, 12, None),
             credit=lambda *_a, **_k: GIB,
             scan=lambda *_a, **_k: pytest.fail("No Windows commit evidence was available."))
    with pytest.raises(module.ReviewMemoryProbeError, match="Windows commit"):
        _run(tmp_path, 1, workers=1)


def test_unavailable_live_probe_fails_without_entering_a_wait_loop(monkeypatch, tmp_path):
    def unavailable():
        raise OSError("No current memory information")

    _install(monkeypatch, snapshot=unavailable, credit=lambda *_a, **_k: GIB,
             scan=lambda *_a, **_k: pytest.fail("Probe failed before enqueue."))
    with pytest.raises(module.ReviewMemoryProbeError, match="current host memory"):
        _run(tmp_path, 1, workers=1)


def test_impossible_minimum_floor_fails_instead_of_waiting_forever(monkeypatch, tmp_path):
    _install(monkeypatch, snapshot=lambda: ReviewMemorySnapshot(GIB // 2, GIB // 2, GIB, True),
             credit=lambda *_a, **_k: None,
             scan=lambda *_a, **_k: pytest.fail("Minimum floor exceeds this synthetic host."))
    with pytest.raises(module.ReviewMemoryProbeError, match="minimum scheduling reserve"):
        _run(tmp_path, 1, workers=1)


def test_thread_admission_does_not_add_back_parent_or_idle_memory(monkeypatch, tmp_path):
    requests = []
    native = module.memory_admission_fits

    def fits(snapshot, **kwargs):
        requests.append(kwargs)
        return native(snapshot, **kwargs)

    _install(monkeypatch, snapshot=lambda: _snapshot(16, 12, 12),
             credit=lambda *_a, **_k: GIB, scan=lambda info, *_a, **_k: _result(info))
    monkeypatch.setattr(module, "memory_admission_fits", fits)
    assert len(_run(tmp_path, 3).results) == 3
    assert requests
    assert all(row["active_owned"] == {} and row["idle_owned"] == ()
               and row["worker_floor_bytes"] == 0 for row in requests)


def test_header_credit_uses_source_rate_and_counts_event_and_spectral_evidence(monkeypatch, tmp_path):
    geometry = ReviewGeometry(67, 65, 64, 1024, 512.0, 64.0, 67 * 512 * 3, 512)
    seen = []
    monkeypatch.setattr(module, "read_review_geometry", lambda *_: geometry)

    def estimate(value, **kwargs):
        seen.append((value, kwargs))
        return SimpleNamespace(healthy_bytes=123)

    monkeypatch.setattr(module, "estimate_review_memory", estimate)
    monkeypatch.setattr(module, "plain_metadata_bytes", lambda _: 77)
    info = _infos(tmp_path, 1)[0]
    protocol = FrequencyProtocol.from_recurrence(
        8, 2, expected_analyzed_oddball_cycles=1,
        expected_analyzed_oddball_cycles_source="manual",
    ).to_manifest()
    off = {"raw_spectral_screening": RawSpectralScreeningSettings(enabled=False).to_manifest(),
           "frequency_protocol": protocol}
    on = {"raw_spectral_screening": RawSpectralScreeningSettings(enabled=True).to_manifest(),
          "low_pass": 40.0, "frequency_protocol": protocol}
    base = module._preflight_memory_credit(info, off, signal_context=True)
    spectral = module._preflight_memory_credit(info, on, signal_context=True)
    assert base == module._PREFLIGHT_THREAD_BYTES + 16 * 77 + 123 + 2048 * 1024 + 4096 * 64 * 17
    assert spectral == base + 2048 * 64 * (8 * 42)
    assert all(value == replace(geometry, target_rate_hz=512.0) for value, _ in seen)
    assert all(kwargs == {"filter_enabled": False, "notch_enabled": False, "raw_qc_enabled": True}
               for _, kwargs in seen)


def test_unknown_geometry_stays_exclusive_without_materializing_signal(monkeypatch, tmp_path):
    monkeypatch.setattr(module, "read_review_geometry", lambda *_: None)
    monkeypatch.setattr(module, "estimate_review_memory", lambda *_a, **_k: pytest.fail("Unknown route."))
    assert module._preflight_memory_credit(_infos(tmp_path, 1)[0], {}, signal_context=True) is None
