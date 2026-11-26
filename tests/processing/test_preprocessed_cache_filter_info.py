"""Real FIF-cache round trips must preserve the strict spectral-domain inputs."""

from __future__ import annotations

import json
import os

import mne
import numpy as np
import pytest

from Main_App.Performance import process_runner
from Main_App.io.pipeline_events import canonical_recording_events
from Main_App.processing.preprocessed_cache_info import snapshot_preprocessed_filter_info
from Main_App.processing.spectral_eligibility import (
    SpectralEligibilityError,
    resolve_spectral_eligibility,
)
from Main_App.projects.frequency_protocol import FrequencyProtocol


def _cache_case(tmp_path, *, high_pass=0.1, low_pass=50.0, sfreq=256.0):
    source = tmp_path / "P1.bdf"
    source.write_bytes(b"Synthetic source identity")
    project = tmp_path / "Project"
    settings = {
        "stim_channel": "Status", "max_idx_keep": 1,
        "high_pass": high_pass, "low_pass": low_pass, "downsample_rate": sfreq,
    }
    values = np.zeros((2, 256), dtype=np.float64)
    values[0] = np.linspace(-30e-6, 25e-6, values.shape[1])
    raw = mne.io.RawArray(
        values, mne.create_info(["Fp1", "Status"], sfreq, ["eeg", "stim"]), verbose=False,
    )
    raw.set_montage(mne.channels.make_standard_montage("biosemi64"))
    with raw.info._unlock():
        raw.info["highpass"] = high_pass
        raw.info["lowpass"] = low_pass
    kwargs = {"file_path": source, "settings": settings, "project_root": project, "mne_module": mne}
    assert process_runner._store_preprocessed_cache(
        raw=raw, audit_before={"original": True}, n_rejected=0, **kwargs,
    ) == "stored"
    payload = process_runner._preproc_cache_payload(source, settings, mne_version=mne.__version__)
    key = process_runner._preproc_cache_key(payload)
    fif_path, meta_path = process_runner._preproc_cache_paths(project, source, key)
    return raw, kwargs, key, fif_path, meta_path


def _eligibility(info, *, high_pass, low_pass):
    protocol = FrequencyProtocol.from_recurrence(
        6, 5, expected_analyzed_oddball_cycles=144,
        expected_analyzed_oddball_cycles_source="manual",
    )
    return resolve_spectral_eligibility(
        protocol=protocol, sampling_rate_hz=info["sfreq"],
        analyzed_samples=int(info["sfreq"] * 120),
        requested_high_pass_hz=high_pass, requested_low_pass_hz=low_pass,
        applied_high_pass_hz=info["highpass"], applied_low_pass_hz=info["lowpass"],
    )


@pytest.mark.parametrize("high_pass, low_pass, sfreq", [(0.1, 50.0, 256.0), (0.01, 37.3, 512.0), (0.3, 40.0, 2048.0)])
def test_cache_restores_exact_filter_edges_and_identical_spectral_eligibility(
    tmp_path, high_pass, low_pass, sfreq,
):
    raw, kwargs, _key, fif_path, _meta_path = _cache_case(
        tmp_path, high_pass=high_pass, low_pass=low_pass, sfreq=sfreq,
    )
    original = raw.get_data().tobytes()
    with mne.io.read_raw_fif(fif_path, preload=True, verbose=False) as direct:
        assert direct.orig_format == "double"
        assert direct.info["highpass"] == float(np.float32(high_pass))
        with pytest.raises(SpectralEligibilityError, match="Applied .*pass metadata"):
            _eligibility(direct.info, high_pass=high_pass, low_pass=low_pass)
        serialized_samples = direct.get_data().tobytes()
    loaded, audit, rejected, status = process_runner._load_preprocessed_cache(**kwargs)
    assert status == "hit"
    try:
        assert audit == {"original": True} and rejected == 0
        assert loaded.get_data().tobytes() == serialized_samples == original
        for field in ("sfreq", "highpass", "lowpass"):
            assert loaded.info[field].hex() == raw.info[field].hex()
        cold = _eligibility(raw.info, high_pass=high_pass, low_pass=low_pass)
        warm = _eligibility(loaded.info, high_pass=high_pass, low_pass=low_pass)
        assert warm.canonical_payload() == cold.canonical_payload()
        assert warm.fingerprint == cold.fingerprint
        assert warm.to_rows() == cold.to_rows()
    finally:
        loaded.close()


def test_cache_restores_exact_fractional_sampling_rate_without_changing_samples(tmp_path):
    raw, kwargs, _key, fif_path, _meta_path = _cache_case(tmp_path, sfreq=256.1)
    with mne.io.read_raw_fif(fif_path, preload=False, verbose=False) as direct:
        assert direct.info["sfreq"] != raw.info["sfreq"]
    loaded, _audit, _rejected, status = process_runner._load_preprocessed_cache(**kwargs)
    assert status == "hit"
    try:
        assert loaded.info["sfreq"].hex() == raw.info["sfreq"].hex()
        assert loaded.first_samp == raw.first_samp and loaded.n_times == raw.n_times
        assert loaded.get_data().tobytes() == raw.get_data().tobytes()
    finally:
        loaded.close()


@pytest.mark.parametrize("mutation", ["missing", "checksum", "cache_key", "different_request", "different_fif"])
def test_missing_or_changed_exact_filter_evidence_is_a_cache_miss(tmp_path, mutation):
    raw, kwargs, key, _fif_path, meta_path = _cache_case(tmp_path)
    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    if mutation == "missing":
        metadata.pop("exact_filter_info")
    elif mutation == "checksum":
        metadata["exact_filter_info"]["values"]["highpass"] = (0.2).hex()
    elif mutation == "cache_key":
        metadata["exact_filter_info"] = snapshot_preprocessed_filter_info(raw.info, kwargs["settings"], cache_key="another-cache")
    else:
        values = dict(raw.info)
        settings = dict(kwargs["settings"])
        if mutation == "different_request":
            values["highpass"] = 0.2
            settings["high_pass"] = 0.2
        else:
            values["sfreq"] = 512.0
        metadata["exact_filter_info"] = snapshot_preprocessed_filter_info(values, settings, cache_key=key)
    meta_path.write_text(json.dumps(metadata), encoding="utf-8")
    loaded, _audit, _rejected, status = process_runner._load_preprocessed_cache(**kwargs)
    assert loaded is None
    assert status == ("miss_missing_filter_metadata" if mutation == "missing" else "miss_filter_metadata_mismatch")


def test_current_filter_change_invalidates_existing_cache_key(tmp_path):
    _raw, kwargs, _key, _fif_path, _meta_path = _cache_case(tmp_path)
    loaded, _audit, _rejected, status = process_runner._load_preprocessed_cache(
        **{**kwargs, "settings": {**kwargs["settings"], "high_pass": 0.2}},
    )
    assert loaded is None and status == "miss"


@pytest.mark.parametrize("reader", ["bvcdf", "bvrf"])
def test_reviewed_source_cache_requires_current_approval_and_admission_evidence(tmp_path, monkeypatch, reader):
    from Main_App.io.recording_sources import recording_content_identity, source_hashes_by_file
    from Main_App.projects.studio_recording_identity import STUDIO_SOURCE_APPROVALS_KEY, studio_source_path_key
    from tests.test_brain_products_reader import _write_bvcdf, _write_bvrf

    raw, kwargs, *_ = _cache_case(tmp_path)
    source, _ = (_write_bvcdf if reader == "bvcdf" else _write_bvrf)(tmp_path)
    kwargs["file_path"] = source
    base_settings = dict(kwargs["settings"])
    hashes = source_hashes_by_file(recording_content_identity(source))
    key = studio_source_path_key(source)
    unrelated = studio_source_path_key(tmp_path / "unused.vhdr")
    approvals = {key: hashes, unrelated: {}}
    settings = {**base_settings, STUDIO_SOURCE_APPROVALS_KEY: approvals}
    kwargs["settings"] = settings
    assert process_runner._recording_job_settings(source, settings)[STUDIO_SOURCE_APPROVALS_KEY] == {key: hashes}
    ordinary = process_runner._preproc_cache_payload(source, base_settings, mne_version=mne.__version__)
    other_approval = {**base_settings, STUDIO_SOURCE_APPROVALS_KEY: {unrelated: {}}}
    assert ordinary == process_runner._preproc_cache_payload(source, other_approval, mne_version=mne.__version__)
    stored = {"source_sha256_by_file": hashes}
    payload = process_runner._preproc_cache_payload(source, settings, mne_version=mne.__version__)
    assert payload == {**ordinary, **stored}
    assert process_runner._store_preprocessed_cache(raw=raw, audit_before={}, n_rejected=0, **kwargs) != "stored"
    assert process_runner._store_preprocessed_cache(raw=raw, audit_before=stored, n_rejected=0, **kwargs) == "stored"
    loaded, audit, _, status = process_runner._load_preprocessed_cache(**kwargs)
    assert status == "hit" and audit == stored
    with loaded:
        assert loaded.get_data().tobytes() == raw.get_data().tobytes()

    monkeypatch.setattr(mne.io, "read_raw_fif", lambda *_args, **_kwargs: pytest.fail("opened an unverified cache"))
    changed = {**hashes, str(source): "0" * 64}
    changed_settings = {**settings, STUDIO_SOURCE_APPROVALS_KEY: {key: changed}}
    assert process_runner._load_preprocessed_cache(**{**kwargs, "settings": changed_settings})[-1] == "miss"
    _, meta_path = process_runner._preproc_cache_paths(kwargs["project_root"], source, process_runner._preproc_cache_key(payload))
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    for evidence in [{}, {"source_sha256_by_file": changed}]:
        meta["audit_before"] = evidence
        meta_path.write_text(json.dumps(meta), encoding="utf-8")
        assert process_runner._load_preprocessed_cache(**kwargs)[-1] == "miss_studio_source_evidence"


def test_disabling_preprocessed_cache_preserves_entries_for_reuse(tmp_path):
    raw, kwargs, _key, fif_path, meta_path = _cache_case(tmp_path)
    original = fif_path.read_bytes(), meta_path.read_bytes()
    disabled = {**kwargs, "settings": {**kwargs["settings"], "enable_preprocessed_cache": False}}

    loaded, _audit, _rejected, status = process_runner._load_preprocessed_cache(**disabled)
    assert loaded is None and status == "disabled"
    assert process_runner._store_preprocessed_cache(
        raw=raw, audit_before={}, n_rejected=0, **disabled,
    ) == "disabled"
    assert (fif_path.read_bytes(), meta_path.read_bytes()) == original

    loaded, _audit, _rejected, status = process_runner._load_preprocessed_cache(**kwargs)
    assert status == "hit"
    loaded.close()


def test_legacy_single_precision_cache_misses_before_float64_rebuild(tmp_path, monkeypatch):
    save = process_runner.save_raw_fif

    def save_legacy(raw, path, **kwargs):
        return save(raw, path, **{**kwargs, "fmt": "single", "buffer_size_sec": None})

    with monkeypatch.context() as legacy:
        legacy.setattr(process_runner, "PREPROC_CACHE_VERSION", "preprocessed-raw-v13-v3-trigger-alignment")
        legacy.setattr(process_runner, "save_raw_fif", save_legacy)
        raw, kwargs, _key, legacy_fif, legacy_meta = _cache_case(tmp_path)

    loaded, _audit, _rejected, status = process_runner._load_preprocessed_cache(**kwargs)
    assert loaded is None and status == "miss"
    assert legacy_fif.is_file() and legacy_meta.is_file()

    assert process_runner._store_preprocessed_cache(
        raw=raw, audit_before={"original": True}, n_rejected=0, **kwargs,
    ) == "stored"
    assert not legacy_fif.exists() and not legacy_meta.exists()
    loaded, _audit, _rejected, status = process_runner._load_preprocessed_cache(**kwargs)
    assert status == "hit"
    try:
        assert loaded.orig_format == "double"
        assert loaded.get_data().tobytes() == raw.get_data().tobytes()
    finally:
        loaded.close()


def test_acquisition_skip_keeps_default_fif_buffer(tmp_path, monkeypatch):
    raw, kwargs, _key, _fif_path, _meta_path = _cache_case(tmp_path)
    raw.set_annotations(mne.Annotations([0.25], [0.125], ["Bad_Acq_Skip"]))
    save = process_runner.save_raw_fif
    buffer_sizes = []

    def observe_save(raw, path, *, buffer_size_sec=None, **kwargs):
        buffer_sizes.append(buffer_size_sec)
        return save(raw, path, buffer_size_sec=buffer_size_sec, **kwargs)

    monkeypatch.setattr(process_runner, "save_raw_fif", observe_save)
    with pytest.warns(RuntimeWarning, match="Acquisition skips"):
        assert process_runner._store_preprocessed_cache(
            raw=raw, audit_before={}, n_rejected=0, **kwargs,
        ) == "stored"
    assert buffer_sizes == [None]


def test_cache_does_not_certify_mismatched_cold_filter_info(tmp_path):
    raw, kwargs, _key, _fif_path, _meta_path = _cache_case(tmp_path)
    with raw.info._unlock():
        raw.info["highpass"] = 0.2
    assert process_runner._store_preprocessed_cache(
        raw=raw, audit_before={}, n_rejected=0, **kwargs,
    ) == "write_error"


def test_preprocessed_metadata_does_not_follow_predictable_staging_hardlink(tmp_path):
    raw, kwargs, _key, _fif_path, meta_path = _cache_case(tmp_path)
    victim = tmp_path / "outside.txt"
    victim.write_bytes(b"outside content")
    staging = meta_path.with_suffix(".json.tmp")
    os.link(victim, staging)

    assert process_runner._store_preprocessed_cache(
        raw=raw, audit_before={"updated": True}, n_rejected=0, **kwargs,
    ) == "stored"

    assert victim.read_bytes() == b"outside content"
    assert staging.read_bytes() == b"outside content"
    assert json.loads(meta_path.read_text(encoding="utf-8"))["audit_before"] == {"updated": True}


def test_preprocessed_fif_cache_preserves_linked_outside_file(tmp_path):
    raw, kwargs, _key, fif_path, _meta_path = _cache_case(tmp_path)
    fif_path.unlink()
    victim = tmp_path / "outside.txt"
    victim.write_bytes(b"outside content")
    os.link(victim, fif_path)

    assert process_runner._store_preprocessed_cache(raw=raw, audit_before={}, n_rejected=0, **kwargs) == "write_error"

    assert victim.read_bytes() == b"outside content"


@pytest.mark.parametrize("corrupt_metadata", [False, True])
def test_real_fif_cache_preserves_canonical_marker_authority(tmp_path, corrupt_metadata):
    raw, kwargs, _key, _fif_path, meta_path = _cache_case(tmp_path)
    events = np.array([[0, 0, 3], [1, 0, 3], [25, 0, 55], [26, 0, 55]], dtype=np.int64)
    raw._fpvs_canonical_events = events
    raw._fpvs_canonical_events_sfreq = float(raw.info["sfreq"])
    assert process_runner._store_preprocessed_cache(
        raw=raw, audit_before={"original": True}, n_rejected=0, **kwargs,
    ) == "stored"
    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    assert metadata["canonical_events"]["events"] == events.tolist()
    if corrupt_metadata:
        metadata["canonical_events"]["events"][1][2] = 99
        meta_path.write_text(json.dumps(metadata), encoding="utf-8")
    loaded, _audit, _rejected, status = process_runner._load_preprocessed_cache(**kwargs)
    if corrupt_metadata:
        assert loaded is None and status == "miss_event_metadata_mismatch"
    else:
        assert status == "hit"
        try:
            np.testing.assert_array_equal(canonical_recording_events(loaded), events)
        finally:
            loaded.close()
