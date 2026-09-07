"""Exact prepared checkpoints reuse computation, never review authority."""

from copy import deepcopy
from datetime import datetime, timezone
import json
import hashlib
import struct
import zipfile

import mne
import numpy as np
import pytest

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
    return raw, params, source


def _run(raw, params):
    actual = deepcopy(params)
    result, count = preprocess.perform_preprocessing(raw.copy(), actual, lambda *_: None)
    assert result is not None, actual.get("_fpvs_preprocessing_error")
    return result, count, actual


def _identity(raw, params):
    return cache.checkpoint_identity(raw, params, preprocess._build_preproc_fingerprint(params))


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


def test_scan_handoff_rebuilds_current_permissions_and_manual_receipts(recording, monkeypatch):
    raw, params, source = recording
    scanned = preprocess.prepare_kurtosis_review_evidence(raw, params, lambda *_: None)
    assert scanned["decision_plan"]["ready_for_interpolation"]
    monkeypatch.setattr(preprocess, "evaluate_kurtosis_qc", lambda *_a, **_k: pytest.fail("Repeated evidence"))
    manual = {**params, "kurtosis_auto_interpolate_all": False}
    pending = preprocess.prepare_kurtosis_review_evidence(raw, manual, lambda *_: None)
    assert not pending["decision_plan"]["ready_for_interpolation"]
    assert pending["evidence"] == scanned["evidence"]
    assert pending["signal_preview"]["channels"]
    result, _ = preprocess.perform_preprocessing(raw.copy(), manual, lambda *_: None)
    assert result is None
    assert manual["_fpvs_kurtosis_checkpoint_status"] == "hit"
    channel = next(row["channel"] for row in pending["decision_plan"]["channel_decisions"] if row["state"] == "review_required")
    manual["_fpvs_kurtosis_review_decisions"] = {channel: _approval(pending["evidence"], channel, source)}
    approved, _count, final = _run(raw, manual)
    assert final["_fpvs_interpolated_channels"] == [channel]
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
