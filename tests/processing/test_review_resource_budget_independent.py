"""Independent allocation and host-headroom controls for review admission.

Expected byte counts below are hand-calculated from fixed native array shapes.
They intentionally do not call a production estimator to derive expectations.
"""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from Main_App.workers.mp_env import compute_effective_max_workers
from Main_App.workers.review_resource_budget import (
    OwnedMemory,
    ReviewGeometry,
    ReviewMemorySnapshot,
    actual_scoring_bytes,
    estimate_review_memory,
    memory_admission_fits,
    probe_owned_memory,
    read_review_geometry,
)


GIB = 1024**3


def _geometry(**changes):
    return replace(
        ReviewGeometry(
            loaded_channels=67,
            retained_channels=65,
            scored_channels=64,
            source_n_times=2_097_152,
            source_rate_hz=2048.0,
            target_rate_hz=256.0,
            packed_record_bytes=454_656,
            source_record_samples=2048,
        ),
        **changes,
    )


def _estimate(geometry=None):
    return estimate_review_memory(
        _geometry() if geometry is None else geometry,
        filter_enabled=False,
        notch_enabled=False,
        raw_qc_enabled=False,
    )


def _snapshot(available, commit=112 * GIB, *, required=True):
    return ReviewMemorySnapshot(
        total_bytes=128 * GIB,
        physical_available_bytes=available,
        commit_available_bytes=commit,
        commit_required=required,
    )


def _fits(snapshot, **changes):
    arguments = {
        "active_credits": {},
        "active_owned": {},
        "idle_owned": (),
        "worker_count": 1,
        "candidate_credit": 0,
        "emergency_reserve": 0,
        "worker_floor_bytes": GIB,
        "host_margin_bytes": 0,
    }
    arguments.update(changes)
    return memory_admission_fits(snapshot, **arguments)


def test_scoring_bytes_include_native_canonical_wrapper_and_fourth_moment_copies():
    estimate = _estimate()
    # Target Raw: 65*262144*8 = 136314880. Six 64-row analyzed arrays:
    # 6*134217728 = 805306368. The full-rate case uses eight times both.
    assert estimate.healthy_qc_bytes >= 941_621_248
    assert estimate.fullrate_qc_bytes >= 7_532_969_984
    assert estimate.healthy_qc_bytes < estimate.fullrate_qc_bytes


def test_loader_bound_covers_destination_ones_and_previous_decoded_chunk():
    estimate = _estimate()
    # Two native 67-row float64 matrices = 2248146944 bytes. The record-
    # rounded 23-record chunk plus previous decoded chunk is 97599488 bytes.
    assert estimate.prefix_bytes >= 2_345_746_432
    assert estimate.healthy_bytes >= estimate.prefix_bytes
    assert estimate.healthy_bytes >= estimate.healthy_qc_bytes
    assert estimate.healthy_bytes + estimate.emergency_extra_bytes >= estimate.fullrate_qc_bytes


def test_source_rate_and_noop_downsampling_cannot_assume_eight_to_one_reduction():
    half_rate = _estimate(_geometry(source_rate_hz=512.0, target_rate_hz=256.0))
    same_rate = _estimate(_geometry(target_rate_hz=2048.0))
    assert half_rate.healthy_qc_bytes >= 3_766_484_992
    assert same_rate.healthy_qc_bytes >= 7_532_969_984
    assert same_rate.healthy_qc_bytes == same_rate.fullrate_qc_bytes
    assert half_rate.healthy_bytes > _estimate().healthy_bytes


@pytest.mark.parametrize("target", [None, False, 0.0, 2048.0, 4096.0])
def test_supported_disabled_or_higher_target_never_invents_native_upsampling(target):
    actual = _estimate(_geometry(target_rate_hz=target))
    source_rate = _estimate(_geometry(target_rate_hz=2048.0))
    assert actual.healthy_qc_bytes == source_rate.healthy_qc_bytes
    assert actual.fullrate_qc_bytes == source_rate.fullrate_qc_bytes


def test_loaded_extra_channels_are_counted_even_when_scored_scalp_set_is_unchanged():
    selected = _estimate()
    all_channels = _estimate(_geometry(loaded_channels=74, retained_channels=72))
    assert all_channels.prefix_bytes > selected.prefix_bytes
    assert all_channels.healthy_qc_bytes > selected.healthy_qc_bytes
    assert all_channels.fullrate_qc_bytes > selected.fullrate_qc_bytes


def test_one_large_record_is_not_mistaken_for_a_ten_mib_decoder_ceiling():
    ordinary = _estimate()
    large_record = _estimate(
        _geometry(packed_record_bytes=32 * 1024**2, source_record_samples=131_072)
    )
    assert large_record.prefix_bytes > ordinary.prefix_bytes


def test_actual_union_is_used_before_any_scoring_arrays_are_materialized():
    assert actual_scoring_bytes(65, 262_144, 64, 100_000) == 443_514_880


def test_cached_evidence_uses_concat_bound_and_keeps_original_input_accounted_for():
    assert actual_scoring_bytes(
        65, 262_144, 64, 100_000,
        evidence_cached=True, original_input_live_bytes=1_124_073_472,
    ) == 1_362_788_352


def test_auto_raw_qc_full_rate_arrays_are_reserved_before_the_scoring_callback():
    enabled = estimate_review_memory(
        _geometry(), filter_enabled=False, notch_enabled=False,
        raw_qc_enabled=True,
    )
    bounded = estimate_review_memory(
        _geometry(), filter_enabled=False, notch_enabled=False,
        raw_qc_enabled=True, raw_union_samples=100_000,
    )
    # Raw input plus retained chunks, pooled data, centered data and variance
    # scratch already require 1124073472 + 4*1073741824 bytes.
    assert enabled.prefix_bytes >= 5_419_040_768
    assert enabled.prefix_bytes > bounded.prefix_bytes
    assert bounded.prefix_bytes >= _estimate().prefix_bytes


@pytest.mark.parametrize("changes", [
    {"source_n_times": 0},
    {"source_n_times": -1},
    {"loaded_channels": 0},
    {"scored_channels": 68},
    {"source_rate_hz": 0.0},
    {"source_rate_hz": float("nan")},
])
def test_invalid_geometry_never_creates_an_affordable_credit(changes):
    with pytest.raises((ValueError, TypeError)):
        _estimate(_geometry(**changes))


def test_twelve_healthy_geometrically_fitting_jobs_are_actually_admissible():
    estimate = _estimate()
    credits = {}
    for index in range(12):
        assert _fits(
            _snapshot(112 * GIB),
            worker_count=12,
            active_credits=credits,
            candidate_credit=estimate.healthy_bytes,
            emergency_reserve=estimate.emergency_extra_bytes,
        ), f"The {index + 1}th healthy job was held despite the declared headroom."
        credits[index] = estimate.healthy_bytes


def test_background_ram_decline_pauses_admission_and_recovery_resumes_it():
    estimate = _estimate()
    arguments = {
        "worker_count": 12,
        "active_credits": {index: estimate.healthy_bytes for index in range(3)},
        "candidate_credit": estimate.healthy_bytes,
        "emergency_reserve": estimate.emergency_extra_bytes,
    }
    assert _fits(_snapshot(112 * GIB), **arguments)
    assert not _fits(_snapshot(4 * GIB), **arguments)
    assert _fits(_snapshot(112 * GIB), **arguments)


def test_windows_private_commit_is_not_credited_as_physical_residency():
    arguments = {
        "active_credits": {0: 8 * GIB},
        "active_owned": {0: OwnedMemory(uss_bytes=3 * GIB, private_commit_bytes=7 * GIB)},
        "candidate_credit": 3 * GIB,
        "emergency_reserve": GIB,
    }
    assert not _fits(_snapshot(8 * GIB), **arguments)
    assert _fits(_snapshot(32 * GIB), **arguments)


def test_windows_commit_pressure_blocks_jobs_despite_ample_physical_ram():
    assert not _fits(
        _snapshot(112 * GIB, commit=GIB),
        candidate_credit=2 * GIB,
    )
    assert _fits(_snapshot(112 * GIB, commit=16 * GIB), candidate_credit=2 * GIB)


def test_required_unknown_commit_is_not_treated_as_unlimited():
    assert not _fits(_snapshot(112 * GIB, commit=None), candidate_credit=GIB)


def test_unknown_owned_memory_has_no_addback():
    arguments = {"active_credits": {0: 8 * GIB}, "candidate_credit": 3 * GIB}
    assert not _fits(_snapshot(8 * GIB), **arguments)
    assert not _fits(
        _snapshot(8 * GIB), active_owned={0: OwnedMemory()}, **arguments
    )


def test_idle_process_floor_remains_reserved_after_jobs_finish():
    assert not _fits(_snapshot(8 * GIB), worker_count=12)
    assert not _fits(
        _snapshot(8 * GIB),
        worker_count=12,
        idle_owned=[OwnedMemory(uss_bytes=GIB // 4, private_commit_bytes=2 * GIB)] * 12,
    )


@pytest.mark.parametrize("cpu_count,total_gib,requested,expected", [
    (1, 128, 12, 1),
    (2, 128, 12, 1),
    (8, 128, 12, 7),
    (24, 128, 12, 12),
    (24, 16, 12, 4),
    (24, 64, 12, 7),
    (24, 128, 1, 1),
])
def test_resource_admission_preserves_modular_cpu_ram_and_user_ceiling(
    cpu_count, total_gib, requested, expected,
):
    assert compute_effective_max_workers(total_gib * GIB, cpu_count, requested) == expected


@pytest.mark.parametrize("target,expected", [(None, 16.0), (False, 16.0), (0.0, 16.0), (32.0, 16.0), (8.0, 8.0)])
def test_actual_bdf_geometry_probe_reads_no_signal_payload_and_normalizes_native_target(
    tmp_path, monkeypatch, target, expected,
):
    from mne.io.edf.edf import RawEDF
    from Main_App.io.eeg_geometry import BIOSEMI64_CHANNELS
    from tests.processing.test_shared_load_utils import _write_sampling_bdf

    source = tmp_path / "geometry.bdf"
    labels = ("EXG1", "EXG2", *BIOSEMI64_CHANNELS, "Status")
    _write_sampling_bdf(source, labels=labels, samples=(16,) * len(labels))
    before = source.read_bytes()
    monkeypatch.setattr(RawEDF, "_read_segment_file", lambda *_a, **_kw: pytest.fail("Geometry read EEG samples."))
    geometry = read_review_geometry(source, {
        "ref_channel1": "EXG1", "ref_channel2": "EXG2",
        "stim_channel": "Status", "max_idx_keep": 64,
        "downsample_rate": target,
    })
    assert geometry is not None
    assert (geometry.loaded_channels, geometry.retained_channels, geometry.scored_channels) == (67, 65, 64)
    assert geometry.source_n_times == 16 and geometry.source_rate_hz == 16.0
    assert geometry.target_rate_hz == expected
    assert source.read_bytes() == before


def test_declared_annotation_header_is_rejected_before_mne_can_read_its_payload(tmp_path, monkeypatch):
    from Main_App.io import load_utils
    from Main_App.io.eeg_geometry import BIOSEMI64_CHANNELS
    from tests.processing.test_shared_load_utils import _write_sampling_bdf

    source = tmp_path / "annotations.bdf"
    labels = ("EXG1", "EXG2", *BIOSEMI64_CHANNELS, "Status", "BDF Annotations")
    _write_sampling_bdf(source, labels=labels, samples=(16,) * len(labels))
    monkeypatch.setattr(load_utils, "open_preflight_eeg_file", lambda *_a, **_kw: pytest.fail("MNE annotation constructor was opened."))
    assert read_review_geometry(source, {"max_idx_keep": 64}) is None


def test_source_change_during_header_probe_cannot_publish_old_geometry(tmp_path, monkeypatch):
    from contextlib import contextmanager
    from Main_App.io import load_utils
    from Main_App.io.eeg_geometry import BIOSEMI64_CHANNELS
    from tests.processing.test_shared_load_utils import _write_sampling_bdf

    source = tmp_path / "changed.bdf"
    labels = ("EXG1", "EXG2", *BIOSEMI64_CHANNELS, "Status")
    _write_sampling_bdf(source, labels=labels, samples=(16,) * len(labels))
    original_open = load_utils.open_preflight_eeg_file

    @contextmanager
    def changed_after_close(*args, **kwargs):
        with original_open(*args, **kwargs) as raw:
            yield raw
        with source.open("ab") as stream:
            stream.write(b"changed")

    monkeypatch.setattr(load_utils, "open_preflight_eeg_file", changed_after_close)
    assert read_review_geometry(source, {"max_idx_keep": 64}) is None


def test_fractional_record_duration_binds_to_actual_mne_sampling_grid(tmp_path):
    import mne
    from Main_App.io.eeg_geometry import BIOSEMI64_CHANNELS
    from tests.processing.test_shared_load_utils import _write_sampling_bdf

    source = tmp_path / "fractional-duration.bdf"
    labels = ("EXG1", "EXG2", *BIOSEMI64_CHANNELS, "Status")
    _write_sampling_bdf(source, labels=labels, samples=(10,) * len(labels), duration="0.3")
    native = mne.io.read_raw_bdf(str(source), preload=False, stim_channel="Status", verbose=False)
    try:
        actual_source_rate = float(native.info["sfreq"])
    finally:
        native.close()
    geometry = read_review_geometry(source, {"max_idx_keep": 64, "downsample_rate": None})
    assert geometry is not None
    assert geometry.source_rate_hz == actual_source_rate
    assert geometry.target_rate_hz == actual_source_rate


def test_none_channel_limit_uses_native_review_default_without_loading_extra_auxiliaries(tmp_path):
    from Main_App.io.eeg_geometry import BIOSEMI64_CHANNELS
    from tests.processing.test_shared_load_utils import _write_sampling_bdf

    source = tmp_path / "all-auxiliaries.bdf"
    labels = ("EXG1", "EXG2", "EXG3", *BIOSEMI64_CHANNELS, "Status")
    _write_sampling_bdf(source, labels=labels, samples=(16,) * len(labels))
    geometry = read_review_geometry(source, {"max_idx_keep": None, "downsample_rate": None})
    assert geometry is not None
    # The serial review's supported None setting resolves to its native64
    # scalp default; the extra EXG3 remains outside the include set.
    assert (geometry.loaded_channels, geometry.retained_channels, geometry.scored_channels) == (67, 65, 64)


def test_casefold_duplicate_reference_names_do_not_produce_underestimated_geometry(tmp_path):
    from Main_App.io.eeg_geometry import BIOSEMI64_CHANNELS
    from tests.processing.test_shared_load_utils import _write_sampling_bdf

    source = tmp_path / "duplicate-reference.bdf"
    labels = ("EXG1", "EXG2", *BIOSEMI64_CHANNELS, "Status")
    _write_sampling_bdf(source, labels=labels, samples=(16,) * len(labels))
    assert read_review_geometry(source, {
        "max_idx_keep": 64, "ref_channel1": "EXG1", "ref_channel2": "exg1",
    }) is None


def test_mixed_sampling_header_fails_before_mne_can_infer_a_resampled_geometry(tmp_path, monkeypatch):
    from Main_App.io import load_utils
    from Main_App.io.eeg_geometry import BIOSEMI64_CHANNELS
    from tests.processing.test_shared_load_utils import _write_sampling_bdf

    source = tmp_path / "mixed-rates.bdf"
    labels = ("EXG1", "EXG2", *BIOSEMI64_CHANNELS, "Status")
    _write_sampling_bdf(source, labels=labels, samples=(8, *((16,) * (len(labels) - 1))))
    monkeypatch.setattr(load_utils, "open_preflight_eeg_file", lambda *_a, **_kw: pytest.fail("Mixed-rate MNE constructor was opened."))
    with pytest.raises(ValueError, match="share one sampling rate"):
        read_review_geometry(source, {"max_idx_keep": 64})


@pytest.mark.parametrize("creation_times", [(11.0,), (10.0, 11.0)])
def test_pid_reuse_before_or_during_owned_memory_probe_has_no_addback(monkeypatch, creation_times):
    from Main_App.workers import review_resource_budget as budget

    times = iter(creation_times)
    fake = SimpleNamespace(
        create_time=lambda: next(times),
        memory_full_info=lambda: SimpleNamespace(uss=3 * GIB, private=7 * GIB, rss=32 * GIB),
    )
    monkeypatch.setattr(budget.psutil, "Process", lambda _pid: fake)
    assert probe_owned_memory(12345, 10.0) == OwnedMemory()


def test_current_pid_probe_returns_unique_residence_and_commit_without_shared_rss(monkeypatch):
    from Main_App.workers import review_resource_budget as budget

    fake = SimpleNamespace(
        create_time=lambda: 10.0,
        memory_full_info=lambda: SimpleNamespace(uss=3 * GIB, private=7 * GIB, rss=32 * GIB),
    )
    monkeypatch.setattr(budget.psutil, "Process", lambda _pid: fake)
    assert probe_owned_memory(12345, 10.0) == OwnedMemory(3 * GIB, 7 * GIB)
