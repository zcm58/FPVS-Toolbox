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

    monkeypatch.setattr(mp_env, "cgroup_limits", lambda: (None, None, None))
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


def _run(tmp_path, count, *, workers=6, cancel=None, progress=None, settings=None):
    return module.scan_preprocessing_qc(
        _infos(tmp_path, count), settings or {}, project_root=tmp_path, event_map={"A": 1},
        max_workers=workers, should_cancel=cancel, progress=progress,
    )


@pytest.mark.parametrize(("available", "commit", "transitions", "bounded", "probed", "admitted"), [
    (12, 12, 40, True, False, True),
    (8, 8, 40, False, True, True),
    (4, 4, 40, True, True, True),
    (4, 4, 40, False, False, False),
    (8, 4, 40, False, False, False),
    (8, 8, 1_000_000, True, True, False),
])
def test_status_bound_only_admits_verified_low_memory_work(
    monkeypatch, tmp_path, available, commit, transitions, bounded, probed, admitted,
):
    from Main_App.io import bdf_preload

    for info in _infos(tmp_path, 2):
        info.path.write_bytes(b"pinned source")
    monkeypatch.setattr(bdf_preload, "supports_bounded_bdf_status", lambda *_a, **_k: bounded)
    monkeypatch.setattr(module, "read_review_geometry", lambda *_: ReviewGeometry(
        67, 65, 64, 2_048_000, 2048, 256, 448_512, 2048,
    ))
    counted = []
    received = []
    cancelled = False

    def status_probe(path, **_kwargs):
        counted.append(path)
        return transitions

    def credit(_info, _settings, *, event_rows=None, bounded_status=False, **_kwargs):
        if event_rows is None:
            return 10 * GIB
        if event_rows >= 100:
            return 9 * GIB
        return (3 if bounded_status else 5) * GIB

    def scan(info, *_args, status_bound, **_kwargs):
        received.append(status_bound)
        return _result(info)

    def progress(message, *_):
        nonlocal cancelled
        if message == "Waiting for preflight memory headroom" and not admitted:
            cancelled = True

    monkeypatch.setattr(module, "count_bdf_status_transitions", status_probe)
    _install(monkeypatch, snapshot=lambda: _snapshot(16, available, commit), credit=credit, scan=scan)
    result = _run(
        tmp_path, 2, workers=4, cancel=lambda: cancelled, progress=progress,
        settings={"hardware_platform": "biosemi", "hardware_confirmed": True,
                  "electrode_montage": "biosemi64", "raw_spectral_screening": {"enabled": False}},
    )

    assert len(counted) == (2 if probed else 0)
    assert result.cancelled is not admitted
    assert [item.participant_id for item in result.results] == (["P0", "P1"] if admitted else [])
    if admitted and probed:
        assert [bound.event_rows for bound in received] == [transitions + 2] * 2
        assert [bound.bounded_status for bound in received] == [bounded] * 2
        assert [bound.source_stamp for bound in received] == [
            module._status_source_stamp(info.path) for info in _infos(tmp_path, 2)
        ]
    elif admitted:
        assert received == [None, None]


@pytest.mark.parametrize("gib,cpus,workers", [
    (8, 24, 2), (16, 24, 4), (32, 24, 4), (64, 24, 7),
    (128, 24, 16), (192, 12, 11), (128, 4, 3),
])
def test_automatic_ram_tiers_reach_scanner_threads(monkeypatch, tmp_path, gib, cpus, workers):
    from Main_App.workers import mp_env

    monkeypatch.setattr(mp_env, "cgroup_limits", lambda: (None, None, None))
    monkeypatch.setattr(mp_env.os, "process_cpu_count", lambda: cpus, raising=False)
    monkeypatch.setattr(mp_env.psutil, "Process", lambda: SimpleNamespace(cpu_affinity=lambda: range(cpus)))
    monkeypatch.setattr(mp_env.psutil, "virtual_memory", lambda: SimpleNamespace(total=gib * GIB))
    monkeypatch.setattr(module, "probe_memory_snapshot", lambda: _snapshot(gib, gib - 2, gib - 2))
    monkeypatch.setattr(module, "_preflight_memory_credit", lambda *a, **k: GIB // 8)
    barrier = Barrier(workers, timeout=5)
    pool_sizes = []
    native_executor = module.ThreadPoolExecutor

    def executor(**kwargs):
        pool_sizes.append(kwargs["max_workers"])
        return native_executor(**kwargs)

    def scan(info, *args, **kwargs):
        if int(info.subject_id[1:]) < workers:
            barrier.wait()
        return _result(info)

    monkeypatch.setattr(module, "ThreadPoolExecutor", executor)
    monkeypatch.setattr(module, "_scan_one_preflight_file", scan)
    result = _run(tmp_path, workers + 1, workers=None)
    assert pool_sizes == [workers]
    assert [row.participant_id for row in result.results] == [f"P{i}" for i in range(workers + 1)]


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


def test_smaller_preflight_can_start_while_next_recording_needs_more_ram(monkeypatch, tmp_path):
    barrier = Barrier(2, timeout=3)
    sizes = {"P0": 4 * GIB, "P1": 8 * GIB, "P2": 3 * GIB}

    def scan(info, *_args, **_kwargs):
        if info.subject_id in {"P0", "P2"}:
            barrier.wait()
        return _result(info)

    _install(monkeypatch, snapshot=_snapshot, credit=lambda info, *a, **k: sizes[info.subject_id], scan=scan)
    result = _run(tmp_path, 3, workers=2)
    assert [row.participant_id for row in result.results] == ["P0", "P1", "P2"]


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


def test_condition_credit_keeps_decoder_overlapping_picks_and_spatial_scratch():
    geometry = ReviewGeometry(67, 65, 64, 1_949_696, 2048.0, 256.0, 73 * 2048 * 3, 2048)
    for interval in (128, 10_240, 15_361, 245_760, geometry.source_n_times):
        samples = min(interval, geometry.source_n_times)
        bounds = module._transient_window_bounds(samples, sfreq=geometry.source_rate_hz)
        # Even every manual/advanced-indexed block (including a tail-aligned
        # overlap) can be retained until the unique occurrence is assembled.
        copied = sum(stop - start for start, stop, _ in bounds) * 8 * geometry.scored_channels
        raw = geometry.scored_channels * 8 * samples
        credit = module._condition_signal_array_bytes(geometry, interval)
        assert credit >= module.bdf_reader_peak_bytes(geometry)
        assert credit >= raw + module.bdf_reader_peak_bytes(replace(geometry, source_n_times=samples))
        assert credit >= copied + 8 * raw
    historical = module.estimate_review_memory(
        replace(geometry, target_rate_hz=geometry.source_rate_hz),
        filter_enabled=False, notch_enabled=False, raw_qc_enabled=True,
    ).healthy_bytes
    assert module._condition_signal_array_bytes(geometry, 245_760) < historical // 2


def test_confirmed_signal_only_route_limits_only_the_waveform_credit(monkeypatch, tmp_path):
    geometry = ReviewGeometry(67, 65, 64, 2_000_000, 2048.0, 256.0, 73 * 2048 * 3, 2048)
    monkeypatch.setattr(module, "read_review_geometry", lambda *_: geometry)
    monkeypatch.setattr(module.np, "__version__", "2.3.1")
    monkeypatch.setattr(module, "plain_metadata_bytes", lambda _: 77)
    protocol = FrequencyProtocol.from_recurrence(
        6, 5, expected_analyzed_oddball_cycles=144, expected_analyzed_oddball_cycles_source="manual",
    )
    settings = {
        "hardware_platform": "biosemi", "hardware_confirmed": True, "electrode_montage": "biosemi64",
        "raw_spectral_screening": RawSpectralScreeningSettings(enabled=False).to_manifest(),
        "frequency_protocol": protocol, "_fpvs_manual_removed_electrodes": ["Fp1", "Fz"],
    }
    info = _infos(tmp_path, 1)[0]
    interval = protocol.expected_analyzed_samples(geometry.source_rate_hz)
    windows = 2 * geometry.source_n_times // 5120 + 2 * (geometry.source_n_times // interval)
    fixed = module._PREFLIGHT_THREAD_BYTES + 16 * 77 + 2048 * geometry.source_n_times + 4096 * 64 * windows
    expected = fixed + module._condition_signal_array_bytes(geometry, interval)
    assert module._preflight_memory_credit(info, settings, signal_context=True) == expected

    review = module.estimate_review_memory(
        replace(geometry, target_rate_hz=geometry.source_rate_hz),
        filter_enabled=False, notch_enabled=False, raw_qc_enabled=True,
    ).healthy_bytes
    for unsupported in ({"hardware_confirmed": False}, {"hardware_platform": "unknown"}, {"electrode_montage": "custom"}):
        assert module._preflight_memory_credit(info, {**settings, **unsupported}, signal_context=True) == fixed + review
    monkeypatch.setattr(module.np, "__version__", "different")
    assert module._preflight_memory_credit(info, settings, signal_context=True) == fixed + review


def test_bounded_status_keeps_full_condition_and_dense_event_scratch(tmp_path):
    geometry = ReviewGeometry(67, 65, 64, 4_177_920, 2048.0, 256.0, 73 * 2048 * 3, 2048)
    protocol = FrequencyProtocol.from_recurrence(
        6, 5, expected_analyzed_oddball_cycles=144, expected_analyzed_oddball_cycles_source="manual",
    )
    settings = {
        "hardware_platform": "biosemi", "hardware_confirmed": True, "electrode_montage": "biosemi64",
        "raw_spectral_screening": RawSpectralScreeningSettings(enabled=False).to_manifest(),
        "frequency_protocol": protocol,
    }
    info = _infos(tmp_path, 1)[0]
    options = {"signal_context": True, "geometry": geometry, "event_rows": 1767}
    unrestricted = module._preflight_memory_credit(info, settings, **options)
    bounded = module._preflight_memory_credit(info, settings, bounded_status=True, **options)

    physical = replace(geometry, loaded_channels=73)
    interval = protocol.expected_analyzed_samples(geometry.source_rate_hz)
    assert bounded >= module._condition_signal_array_bytes(physical, interval, bounded_status=True)
    assert bounded >= module.bdf_reader_peak_bytes(replace(geometry, loaded_channels=1)) + 256 * geometry.source_n_times
    assert bounded + GIB < 4 * GIB < unrestricted + GIB
    assert module._preflight_memory_credit(
        info, {**settings, "hardware_confirmed": False}, bounded_status=True, **options,
    ) is None
