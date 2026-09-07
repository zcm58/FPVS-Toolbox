"""Real FIF-cache round trips must preserve the strict spectral-domain inputs."""

from __future__ import annotations

import json

import mne
import numpy as np
import pytest

from Main_App.Performance import process_runner
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
    # Binary fractions preserve the sample values through the existing FIF format.
    values = np.arange(512, dtype=np.float64).reshape(2, 256) / 1024.0
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


def test_cache_does_not_certify_mismatched_cold_filter_info(tmp_path):
    raw, kwargs, _key, _fif_path, _meta_path = _cache_case(tmp_path)
    with raw.info._unlock():
        raw.info["highpass"] = 0.2
    assert process_runner._store_preprocessed_cache(
        raw=raw, audit_before={}, n_rejected=0, **kwargs,
    ) == "write_error"
