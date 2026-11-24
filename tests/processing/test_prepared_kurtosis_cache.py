"""Exact prepared checkpoints reuse computation, never review authority."""

from copy import deepcopy
from dataclasses import dataclass, FrozenInstanceError
from datetime import datetime, timezone
import json
import hashlib
import os
import struct
import zipfile

import mne
import numpy as np
import pytest

from Main_App.io.acquisition_metadata import attach_recording_contract
from Main_App.processing import prepared_kurtosis_cache as cache
from Main_App.processing import preprocess
from Main_App.processing.prepared_raw_codec import encode_state, decode_state, raw_state, restore_raw
from tests.processing.test_preprocess_kurtosis_gate import _raw, _params, _approval


@pytest.fixture
def recording(tmp_path):
    source = tmp_path / "participant.bdf"
    source.write_bytes(b"Synthetic in-memory EEG source identity")
    params = _params(source)
    params["project_root"] = str(tmp_path)
    params["kurtosis_auto_interpolate_all"] = True
    raw = _raw()
    raw._data[-1, 0] = 1.
    raw._data[-1, 100:601:50] = 55.
    raw.set_meas_date(datetime(2026, 9, 5, tzinfo=timezone.utc))
    raw.set_annotations(mne.Annotations([.125], [.017], ["note"]))
    raw._fpvs_original_events = np.array([[0, 0, 1], [100, 0, 55]], dtype=np.int64)
    attach_recording_contract(raw, params)
    return raw, params, source


def _run(raw, params):
    actual = deepcopy(params)
    result, count = preprocess.perform_preprocessing(raw.copy(), actual, lambda *_: None)
    assert result is not None, actual.get("_fpvs_preprocessing_error")
    return result, count, actual


def _identity(raw, params):
    return cache.checkpoint_identity(raw, params, preprocess._build_preproc_fingerprint(params))


@pytest.mark.parametrize("changed_field,changed_value", [
    ("num_threads", 2),
    ("version", "changed-library-version"),
    ("filepath", "/other/library"),
])
def test_checkpoint_identity_distinguishes_native_reduction_policy(
    recording, monkeypatch, changed_field, changed_value,
):
    raw, params, _source = recording
    pool = {
        "user_api": "blas", "internal_api": "openblas", "prefix": "numpy_blas",
        "version": "1", "filepath": "/library", "architecture": "cpu",
        "threading_layer": "pthreads", "num_threads": 1,
    }
    monkeypatch.setattr(cache, "threadpool_info", lambda: [dict(pool)])
    before = _identity(raw, params)
    assert before is not None
    pool[changed_field] = changed_value
    after = _identity(raw, params)
    assert after is not None and after.key != before.key


@pytest.mark.parametrize("pools", [[], [{"user_api": "blas", "num_threads": 0}]])
def test_checkpoint_unknown_native_policy_disables_exact_reuse(recording, monkeypatch, pools):
    raw, params, _source = recording
    monkeypatch.setattr(cache, "threadpool_info", lambda: pools)
    assert _identity(raw, params) is None


def test_checkpoint_exposes_existing_source_digest_without_extra_hash_or_raw_state(recording, monkeypatch):
    raw, params, source = recording
    before = set(vars(raw))
    file_digest = hashlib.file_digest
    calls = []

    def digest(stream, algorithm):
        calls.append(stream.name)
        return file_digest(stream, algorithm)

    monkeypatch.setattr(hashlib, "file_digest", digest)
    identity = _identity(raw, params)
    assert identity.source_sha256 == hashlib.sha256(source.read_bytes()).hexdigest()
    assert calls == [str(source)]
    assert set(vars(raw)) == before
    compatible = cache.CheckpointIdentity(identity.project_root, identity.folder, identity.source,
                                           identity.source_stat, identity.key)
    assert compatible.key == identity.key and compatible.source_sha256 == ""


def _assert_exact_state(left, right):
    arrays_left, arrays_right = {}, {}
    assert encode_state(left, arrays_left) == encode_state(right, arrays_right)
    assert arrays_left.keys() == arrays_right.keys()
    for key in arrays_left:
        assert arrays_left[key].dtype == arrays_right[key].dtype
        assert arrays_left[key].shape == arrays_right[key].shape
        assert arrays_left[key].tobytes() == arrays_right[key].tobytes()


def test_disabled_checkpoint_preserves_existing_entry_for_reuse(recording):
    raw, params, _source = recording
    first, _, _ = _run(raw, params)
    identity = _identity(raw, params)
    entries = {path: path.read_bytes() for path in identity.folder.iterdir()}
    assert {path.suffix for path in entries} == {".npz", ".json"}

    disabled, _, off = _run(raw, {**params, "enable_kurtosis_checkpoint_cache": False})
    assert off["_fpvs_kurtosis_checkpoint_status"] == "disabled"
    assert {path: path.read_bytes() for path in identity.folder.iterdir()} == entries
    restored, _, on = _run(raw, params)
    assert on["_fpvs_kurtosis_checkpoint_status"] == "hit"
    assert first._data.tobytes() == disabled._data.tobytes() == restored._data.tobytes()


def test_temporary_bids_locations_do_not_block_checkpoint_reuse(recording):
    raw, params, source = recording

    def set_import(current, scratch_name):
        dataset_root = source.parent / scratch_name
        path = dataset_root / "recording.bdf"
        current._filenames = [path]
        current._fpvs_bids_import = {
            "version": "bids_import_v1", "representation": "raw_eeg_bids", "path": str(path),
            "dataset_root": str(dataset_root), "identity_seconds": 1.5, "conversion_seconds": 2.0,
            "reused": False, "temporary": True, "import_key": "a" * 64,
        }

    set_import(raw, "first-import")
    cold, _, _ = _run(raw, params)
    original = _identity(raw, params)
    current = raw.copy()
    set_import(current, "next-import")
    assert _identity(current, params).key == original.key

    warm, _, settings = _run(current, params)
    assert settings["_fpvs_kurtosis_checkpoint_status"] == "hit"
    assert warm._fpvs_bids_import == current._fpvs_bids_import
    assert warm.filenames == current.filenames
    assert warm._data.tobytes() == cold._data.tobytes()

    current._fpvs_bids_import["import_key"] = "b" * 64
    assert _identity(current, params).key != original.key


def test_current_import_diagnostics_reuse_exact_science_and_keep_original_receipt(recording, monkeypatch):
    raw, params, source = recording
    first_import = {
        "version": "bids_import_v1", "representation": "raw_eeg_bids", "path": str(source),
        "dataset_root": str(source.parent), "identity_seconds": 1.5, "conversion_seconds": 2.0,
        "reused": False, "future_scientific_provenance": {"channel_domain": "scalp"},
    }
    latest_import = {**first_import, "identity_seconds": 0.25, "conversion_seconds": 0.0, "reused": True}
    raw._fpvs_bids_import = deepcopy(first_import)
    first, _, cold_settings = _run(raw, params)
    original = _identity(raw, params)
    assert cold_settings["_fpvs_kurtosis_checkpoint_status"] == "miss"
    assert raw._fpvs_bids_import == first._fpvs_bids_import == first_import
    manifest = original.folder / "latest.json"
    initial_receipt = manifest.read_bytes()
    current = raw.copy()
    current._fpvs_bids_import = deepcopy(latest_import)
    expected, count, expected_settings = _run(current, {**params, "enable_kurtosis_checkpoint_cache": False})
    monkeypatch.setattr(preprocess, "evaluate_kurtosis_qc", lambda *_a, **_k: pytest.fail("Repeated evidence"))
    assert _identity(current, params).key == original.key
    reused, warm_count, warm_settings = _run(current, params)
    assert warm_settings["_fpvs_kurtosis_checkpoint_status"] == "hit" and warm_count == count
    assert current._fpvs_bids_import == reused._fpvs_bids_import == latest_import
    assert reused._data.dtype == expected._data.dtype and reused._data.tobytes() == expected._data.tobytes()
    _assert_exact_state(raw_state(reused), raw_state(expected))
    for key in ("_fpvs_kurtosis_qc_evidence", "_fpvs_kurtosis_decision_plan", "_fpvs_realized_analysis_span_plan"):
        assert expected_settings[key] == warm_settings[key] == cold_settings[key]
    assert manifest.read_bytes() == initial_receipt
    from_first_load = cache.load_checkpoint(original)
    assert from_first_load.raw._fpvs_bids_import == raw._fpvs_bids_import == first_import
    from_first_load.raw.close()


def test_import_science_and_unknown_or_incomplete_diagnostics_keep_their_exact_identity(recording):
    raw, params, source = recording
    known = {"version": "bids_import_v1", "representation": "raw_eeg_bids", "path": str(source),
             "identity_seconds": 1., "conversion_seconds": 0., "reused": True}
    raw._fpvs_bids_import = known
    valid = _identity(raw, params)
    assert valid is not None and valid.bids_import_diagnostics is not None
    for change in ({"path": str(source.with_suffix(".fif"))}, {"representation": "another_format"},
                   {"acquisition_metadata": {"variant": 2}}):
        raw._fpvs_bids_import = {**known, **change}
        assert _identity(raw, params).key != valid.key
    for change in ({"version": "future_import_v2"}, {"reused": 1}, {"conversion_seconds": -2.},
                   {"identity_seconds": None}, {"path": ""}):
        raw._fpvs_bids_import = {**known, **change}
        malformed = _identity(raw, params)
        assert malformed.bids_import_diagnostics is None and malformed.key != valid.key
        raw._fpvs_bids_import = {**raw._fpvs_bids_import, "conversion_seconds": -3.}
        assert _identity(raw, params).key != malformed.key
    raw._fpvs_bids_import = {k: v for k, v in known.items() if k not in valid.bids_import_diagnostics._fields}
    missing = _identity(raw, params)
    assert missing.bids_import_diagnostics is None and missing.key != valid.key


@pytest.mark.parametrize("rate", [100., 80.])
def test_prepared_checkpoint_exact_filtered_signal_events_evidence_and_metadata(recording, monkeypatch, rate):
    raw, params, _source = recording
    params.update(high_pass=.5, low_pass=30., downsample_rate=rate)
    reference, reference_count, expected = _run(raw, {**params, "enable_kurtosis_checkpoint_cache": False})
    cold, cold_count, first = _run(raw, params)
    assert first["_fpvs_kurtosis_checkpoint_status"] == "miss"

    def must_not_repeat(*_args, **_kwargs):
        pytest.fail("A hit repeated preparation or kurtosis arithmetic")

    monkeypatch.setattr(mne.io.BaseRaw, "filter", must_not_repeat)
    monkeypatch.setattr(mne.io.BaseRaw, "resample", must_not_repeat)
    monkeypatch.setattr(preprocess, "evaluate_kurtosis_qc", must_not_repeat)
    warm, warm_count, second = _run(raw, params)
    assert second["_fpvs_kurtosis_checkpoint_status"] == "hit"
    assert reference_count == cold_count == warm_count
    for candidate, settings in [(cold, first), (warm, second)]:
        assert reference._data.tobytes() == candidate._data.tobytes()
        _assert_exact_state(raw_state(reference), raw_state(candidate))
        for key in ("_fpvs_kurtosis_qc_evidence", "_fpvs_kurtosis_decision_plan", "_fpvs_realized_analysis_span_plan"):
            assert expected[key] == settings[key]
    archive_path = next(_identity(raw, params).folder.glob("*.npz"))
    with zipfile.ZipFile(archive_path) as archive:
        assert all(item.compress_type == zipfile.ZIP_STORED for item in archive.infolist())
    # Final interpolation mutated only its freshly restored data.
    prepared = cache.load_checkpoint(_identity(raw, params))
    assert prepared.raw._data.tobytes() != warm._data.tobytes()
    warm._data[:] = 0.
    again = cache.load_checkpoint(_identity(raw, params))
    assert prepared.raw._data.tobytes() == again.raw._data.tobytes()


def test_restored_preview_size_preserves_invalid_and_out_of_bounds_span_handling(recording):
    raw, _, _ = recording
    spans = [[2, 8], [10, 16]]
    plan = {"target_grid": {"n_times": raw.n_times}, "unique_relative_spans": spans, "unique_sample_count": 12}
    assert preprocess._restored_kurtosis_sample_count(raw, plan) == 12
    with pytest.raises(preprocess.AnalysisSpanPlanError, match="sample count is stale"):
        preprocess._restored_kurtosis_sample_count(raw, {**plan, "unique_sample_count": 11})
    longer = raw.n_times + 7
    outside = {"target_grid": {"n_times": longer}, "unique_relative_spans": [[0, longer]],
               "unique_sample_count": longer}
    assert preprocess._restored_kurtosis_sample_count(raw, outside) is None
    empty = {**plan, "unique_relative_spans": [], "unique_sample_count": 0}
    assert preprocess._restored_kurtosis_sample_count(raw, empty) is None
    with pytest.raises(preprocess.AnalysisSpanPlanError, match="union is empty"):
        preprocess._kurtosis_scoring_data(raw, picks=[0], params={"_fpvs_realized_analysis_span_plan": empty})


def test_scan_handoff_rebuilds_current_permissions_and_manual_receipts(recording, monkeypatch):
    raw, params, source = recording
    scanned = preprocess.prepare_kurtosis_review_evidence(raw, params, lambda *_: None)
    assert scanned["decision_plan"]["ready_for_interpolation"]
    monkeypatch.setattr(preprocess, "evaluate_kurtosis_qc", lambda *_a, **_k: pytest.fail("Repeated evidence"))
    manual = {**params, "kurtosis_auto_interpolate_all": False}
    with monkeypatch.context() as reference:
        reference.setattr(preprocess, "_restored_kurtosis_sample_count", lambda *_: None)
        full = preprocess.prepare_kurtosis_review_evidence(raw, manual, lambda *_: None)
    read_channels = []
    collect = preprocess._kurtosis_scoring_data

    def track_channels(restored, *, picks, params):
        read_channels.append([restored.ch_names[i] for i in picks])
        return collect(restored, picks=picks, params=params)

    monkeypatch.setattr(preprocess, "_kurtosis_scoring_data", track_channels)
    pending = preprocess.prepare_kurtosis_review_evidence(raw, manual, lambda *_: None)
    assert not pending["decision_plan"]["ready_for_interpolation"]
    assert pending["evidence"] == scanned["evidence"]
    assert pending["signal_preview"]["channels"]
    _assert_exact_state(pending, full)
    assert read_channels == [list(pending["signal_preview"]["channels"])]
    finish = preprocess._finish_preprocessing_at_kurtosis
    with monkeypatch.context() as no_handle:
        def finish_without_checkpoint(*args, **kwargs):
            assert kwargs["cached_evidence"] is not None
            return finish(*args, **{**kwargs, "checkpoint": None})

        no_handle.setattr(preprocess, "_finish_preprocessing_at_kurtosis", finish_without_checkpoint)
        no_handle.setattr(preprocess, "_restored_kurtosis_sample_count", lambda *_: pytest.fail("Missing handle"))
        read_channels.clear()
        standalone = preprocess.prepare_kurtosis_review_evidence(raw, manual, lambda *_: None)
    assert len(read_channels) == 1 and len(read_channels[0]) > len(pending["signal_preview"]["channels"])
    assert standalone["signal_preview"]["channels"] == pending["signal_preview"]["channels"]
    result, _ = preprocess.perform_preprocessing(raw.copy(), manual, lambda *_: None)
    assert result is None
    assert manual["_fpvs_kurtosis_checkpoint_status"] == "hit"
    channel = next(row["channel"] for row in pending["decision_plan"]["channel_decisions"] if row["state"] == "review_required")
    manual["_fpvs_kurtosis_review_decisions"] = {channel: _approval(pending["evidence"], channel, source)}
    read_channels.clear()
    approved, _count, final = _run(raw, manual)
    assert final["_fpvs_interpolated_channels"] == [channel]
    assert read_channels == []
    clear = final["_fpvs_kurtosis_signal_preview"]
    assert clear["channels"] == {} and clear["source_sample_count"] == full["signal_preview"]["source_sample_count"]
    assert approved is not None
    checkpoint = cache.load_checkpoint(_identity(raw, params))
    assert not any("decision" in key or "approved" in key for key in checkpoint.params)
    invalid_receipt = deepcopy(manual["_fpvs_kurtosis_review_decisions"])
    invalid_receipt[channel]["reviewer_state"] = "non_gui_script"
    invalid = {**params, "kurtosis_auto_interpolate_all": False,
               "_fpvs_kurtosis_review_decisions": invalid_receipt}
    result, _ = preprocess.perform_preprocessing(raw.copy(), invalid, lambda *_: None)
    assert result is None
    assert invalid["_fpvs_kurtosis_checkpoint_status"] == "hit"


@pytest.mark.parametrize("change", [
    "eeg_sample", "stim_sample", "annotations", "projection", "direct_bad", "max_idx_keep",
    "source_plan", "threshold", "filter", "rate", "source_bytes", "numpy_version", "scipy_version",
])
def test_checkpoint_identity_invalidates_every_scientific_input(recording, monkeypatch, change):
    raw, params, source = recording
    before = _identity(raw, params)
    assert before is not None
    if change == "eeg_sample":
        raw._data[2, 4] += .001
    elif change == "stim_sample":
        raw._data[-1, 20] = 55.
    elif change == "annotations":
        raw.set_annotations(mne.Annotations([1.], [.2], ["BAD_ACQ_SKIP"]))
    elif change == "projection":
        raw.set_eeg_reference(projection=True, verbose=False)
    elif change == "direct_bad":
        raw.info["bads"] = [raw.ch_names[3]]
    elif change == "max_idx_keep":
        params["max_idx_keep"] = 10
    elif change == "source_plan":
        params["_fpvs_source_analysis_span_plan"]["unique_sample_count"] += 1
    elif change == "threshold":
        params["reject_thresh"] = 6.
    elif change == "filter":
        params["high_pass"] = .5
    elif change == "rate":
        params["downsample_rate"] = 80.
    elif change == "source_bytes":
        source.write_bytes(b"Different signal, same source path")
    else:
        module = cache.np if change == "numpy_version" else cache.scipy
        monkeypatch.setattr(module, "__version__", "changed-version")
    assert _identity(raw, params).key != before.key


def test_stale_plan_rejected_instead_of_reusing_previous_checkpoint(recording):
    raw, params, _ = recording
    _run(raw, params)
    params["_fpvs_source_analysis_span_plan"]["unique_sample_count"] += 1
    result, _ = preprocess.perform_preprocessing(raw.copy(), params, lambda *_: None)
    assert result is None
    assert params["_fpvs_kurtosis_checkpoint_status"] == "miss"


@pytest.mark.parametrize("damage", ["missing", "corrupt", "manifest"])
def test_missing_or_corrupt_checkpoint_recomputes_exactly(recording, damage):
    raw, params, _ = recording
    expected, _, _ = _run(raw, params)
    identity = _identity(raw, params)
    archive = next(identity.folder.glob("*.npz"))
    if damage == "missing":
        archive.unlink()
    elif damage == "corrupt":
        archive.write_bytes(b"damaged archive")
    else:
        (identity.folder / "latest.json").write_text("{broken", encoding="utf-8")
    actual, _, settings = _run(raw, params)
    assert settings["_fpvs_kurtosis_checkpoint_status"] == "miss"
    assert expected._data.tobytes() == actual._data.tobytes()
    assert cache.load_checkpoint(identity) is not None


def test_cache_retains_latest_settings_only_and_preserves_unowned_files(recording):
    raw, params, _ = recording
    _run(raw, params)
    identity = _identity(raw, params)
    unrelated = identity.folder / "user-note.npz"
    unrelated.write_bytes(b"keep")
    _run(raw, {**params, "reject_thresh": 6.})
    assert len(list(identity.folder.glob("*.npz"))) == 2
    assert unrelated.read_bytes() == b"keep"
    assert cache.load_checkpoint(identity) is None


@pytest.mark.parametrize("mode", [
    "snapshot", "buffer_pressure", "read_error", "decoder_pressure", "compressed", "compressed_buffer_pressure",
])
def test_admitted_checkpoint_and_streaming_fallback_restore_identical_bits(recording, monkeypatch, mode):
    from Main_App.io import numpy_companion

    raw, params, _ = recording
    if mode.startswith("compressed"):
        monkeypatch.setattr(cache.np, "savez", np.savez_compressed)
    _run(raw, params)
    identity = _identity(raw, params)
    pointer = identity.folder / "latest.json"
    receipt = pointer.read_bytes()
    reference = cache.load_checkpoint(identity)
    original_buffer = numpy_companion._read_buffer
    original_restore = cache.restore_raw
    buffers, restorations, disk_hashes = [], [], []
    file_digest = hashlib.file_digest

    def digest(stream, algorithm):
        if getattr(stream, "name", None):
            disk_hashes.append(True)
        return file_digest(stream, algorithm)

    def buffer(*args):
        buffers.append(True)
        if mode in ("buffer_pressure", "compressed_buffer_pressure"):
            args[0].read(7)
            raise MemoryError
        if mode == "read_error":
            args[0].read(7)
            raise OSError("Large read unavailable")
        return original_buffer(*args)

    def restore(*args):
        restorations.append(True)
        if mode == "decoder_pressure" and len(restorations) == 1:
            raise MemoryError
        return original_restore(*args)

    monkeypatch.setattr(cache, "admitted_checkpoint_snapshot", lambda size, *_: size)
    monkeypatch.setattr(numpy_companion, "_read_buffer", buffer)
    monkeypatch.setattr(cache, "restore_raw", restore)
    monkeypatch.setattr(hashlib, "file_digest", digest)
    actual = cache.load_checkpoint(identity)
    assert len(buffers) == 1 and len(restorations) == (2 if mode == "decoder_pressure" else 1)
    assert len(disk_hashes) == (0 if mode == "snapshot" else 1)
    assert actual.raw._data.tobytes() == reference.raw._data.tobytes()
    _assert_exact_state(raw_state(actual.raw), raw_state(reference.raw))
    _assert_exact_state((actual.evidence, actual.params, actual.original_sfreq),
                        (reference.evidence, reference.params, reference.original_sfreq))
    assert actual.raw._data.flags.writeable
    assert pointer.read_bytes() == receipt


def test_bad_checksum_is_rejected_before_parsing_any_snapshot(recording, monkeypatch):
    raw, params, _ = recording
    _run(raw, params)
    identity = _identity(raw, params)
    path = next(identity.folder.glob("*.npz"))
    with path.open("r+b") as stream:
        stream.seek(-1, 2)
        value = stream.read(1)[0]
        stream.seek(-1, 2)
        stream.write(bytes([value ^ 1]))
    monkeypatch.setattr(cache, "admitted_checkpoint_snapshot", lambda size, *_: size)
    monkeypatch.setattr(cache.np, "load", lambda *_a, **_k: pytest.fail("Unverified checkpoint parsed"))
    assert cache.load_checkpoint(identity) is None


def test_lazy_input_with_existing_identity_uses_streaming_checkpoint(recording, monkeypatch, tmp_path):
    raw, params, _ = recording
    expected, count, _ = _run(raw, params)
    identity = _identity(raw, params)
    path = tmp_path / "lazy_raw.fif"
    raw.save(path, fmt="double", verbose=False)
    with mne.io.read_raw_fif(path, preload=False, verbose=False) as lazy:
        assert not lazy.preload
        assert _identity(lazy, params) is None
        monkeypatch.setattr(preprocess, "checkpoint_identity", lambda *_: identity)
        sizes = []

        def observe(_size, source_bytes, _workers):
            sizes.append(source_bytes)
            return 0

        monkeypatch.setattr(cache, "admitted_checkpoint_snapshot", observe)
        actual, actual_count, settings = _run(lazy, params)
    assert sizes == [0]
    assert settings["_fpvs_kurtosis_checkpoint_status"] == "hit"
    assert count == actual_count and expected._data.tobytes() == actual._data.tobytes()
    _assert_exact_state(raw_state(expected), raw_state(actual))


@pytest.mark.parametrize("touch_only", [True, False])
def test_in_place_archive_change_during_snapshot_rechecks_current_bytes(recording, monkeypatch, touch_only):
    from Main_App.io import numpy_companion

    raw, params, _ = recording
    _run(raw, params)
    identity = _identity(raw, params)
    path = next(identity.folder.glob("*.npz"))
    read_buffer = numpy_companion._read_buffer

    def mutate_after_read(*args):
        buffer = read_buffer(*args)
        if touch_only:
            stat = path.stat()
            os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
        else:
            with path.open("ab") as handle:
                handle.write(b"changed in place")
        return buffer

    monkeypatch.setattr(cache, "admitted_checkpoint_snapshot", lambda size, *_: size)
    monkeypatch.setattr(numpy_companion, "_read_buffer", mutate_after_read)
    assert (cache.load_checkpoint(identity) is not None) == touch_only


@pytest.mark.parametrize("gib", [8, 16, 32, 64, 128, 256])
def test_checkpoint_snapshot_respects_job_slack_and_ram_tier(gib, monkeypatch):
    from Main_App.workers import review_resource_budget as budget
    from Main_App.workers.mp_env import compute_dynamic_worker_ceiling

    host = gib * budget.GIB
    size = 100 * 1024**2
    source = 4 * size
    expected_workers = compute_dynamic_worker_ceiling(total_ram_bytes=host)
    margin = max(budget.GIB, host // 16)
    minimum = 2 * size * expected_workers + margin

    def probe(free, commit):
        return lambda: budget.ReviewMemorySnapshot(host, free, commit, True)

    monkeypatch.setattr(budget, "probe_memory_snapshot", probe(minimum, minimum))
    assert budget.admitted_checkpoint_snapshot(size, source, None) == size
    assert budget.admitted_checkpoint_snapshot(size, 2 * size, None) == 0
    assert budget.admitted_checkpoint_snapshot(budget.GIB, 4 * budget.GIB, None) == 0
    for free, commit in ((minimum - 1, host), (host, minimum - 1), (host, None)):
        monkeypatch.setattr(budget, "probe_memory_snapshot", probe(free, commit))
        assert budget.admitted_checkpoint_snapshot(size, source, None) == 0


def test_cancelled_write_keeps_previous_complete_checkpoint_and_cleans_temporary_files(recording, monkeypatch):
    raw, params, _ = recording
    _run(raw, params)
    identity = _identity(raw, params)
    previous_manifest = (identity.folder / "latest.json").read_bytes()
    original_savez = np.savez
    cancelled = False

    def cancel_after_write(*args, **kwargs):
        nonlocal cancelled
        original_savez(*args, **kwargs)
        cancelled = True

    monkeypatch.setattr(np, "savez", cancel_after_write)
    changed = {**params, "reject_thresh": 6., "_fpvs_kurtosis_checkpoint_should_cancel": lambda: cancelled}
    preprocess.perform_preprocessing(raw.copy(), changed, lambda *_: None)
    assert (identity.folder / "latest.json").read_bytes() == previous_manifest
    assert not list(identity.folder.glob("*.tmp"))
    assert len(list(identity.folder.glob("*.npz"))) == 1
    assert cache.load_checkpoint(identity) is not None


def test_no_project_root_or_unsupported_input_disables_checkpoint(recording):
    raw, params, _ = recording
    assert _identity(raw, {**params, "project_root": None}) is None
    assert _identity(raw, {**params, "enable_kurtosis_checkpoint_cache": False}) is None
    raw._fpvs_unknown_metadata = object()
    assert _identity(raw, params) is None
    del raw._fpvs_unknown_metadata
    raw._data = raw._data.astype(np.complex128)
    assert _identity(raw, params) is None


@pytest.mark.parametrize("stage", ["reference", "filter", "resample"])
def test_failed_preparation_is_not_published_under_successful_settings(recording, monkeypatch, stage):
    raw, params, _ = recording
    if stage == "filter":
        params.update(high_pass=.5, low_pass=30.)
    if stage == "resample":
        params["downsample_rate"] = 80.
    method = {"reference": "set_eeg_reference", "filter": "filter", "resample": "resample"}[stage]
    original = getattr(mne.io.BaseRaw, method)

    def fail_initial_stage(self, *args, **kwargs):
        if stage != "reference" or kwargs.get("ref_channels") != "average":
            raise RuntimeError("temporary preparation failure")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(mne.io.BaseRaw, method, fail_initial_stage)
    preprocess.perform_preprocessing(raw.copy(), params, lambda *_: None)
    assert cache.load_checkpoint(_identity(raw, params)) is None
    assert not list(_identity(raw, params).folder.glob("*.npz"))


def test_codec_preserves_nan_bits_projection_geometry_and_nonzero_first_sample(recording):
    raw, _params_value, _ = recording
    raw.crop(tmin=1.23)
    raw._fpvs_float_bits = struct.unpack("!d", bytes.fromhex("fff8000000000001"))[0]
    raw.set_eeg_reference(projection=True, verbose=False)
    arrays = {}
    encoded = encode_state(raw_state(raw), arrays)
    decoded = decode_state(json.loads(json.dumps(encoded)), arrays)
    restored = restore_raw(raw.get_data(), decoded)
    assert restored.first_samp == 123
    assert restored._data.tobytes() == raw._data.tobytes()
    _assert_exact_state(raw_state(raw), raw_state(restored))


@pytest.mark.parametrize("settings", [
    {},
    {"hardware_platform": "brain_products", "hardware_confirmed": True,
     "initial_reference": "channels", "initial_reference_channels": ["Fp1"],
     "drop_reference_channels": False, "max_idx_keep": 8},
])
def test_codec_preserves_immutable_recording_contract(recording, settings):
    raw, _params_value, _source = recording
    expected = attach_recording_contract(raw, settings)
    arrays = {}
    encoded = encode_state(raw_state(raw), arrays)
    restored = restore_raw(raw.get_data(), decode_state(json.loads(json.dumps(encoded)), arrays))
    try:
        assert restored._fpvs_recording_contract == expected
        assert restored._fpvs_resolved_acquisition_policy == expected
        assert restored._data.tobytes() == raw._data.tobytes()
        with pytest.raises(FrozenInstanceError):
            restored._fpvs_recording_contract.stim_channel = "changed"
    finally:
        restored.close()


def test_codec_keeps_unknown_dataclasses_outside_checkpoint_allowlist():
    @dataclass
    class UnregisteredMetadata:
        value: str = "unrecognized"

    with pytest.raises(ValueError, match="Unsupported prepared-checkpoint metadata"):
        encode_state(UnregisteredMetadata(), {})
