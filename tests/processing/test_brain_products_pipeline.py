from __future__ import annotations

import copy

import mne
import numpy as np
import pytest

from Main_App.io.recorded_eeg_geometry import (
    attach_raw_recorded_geometry,
    validate_raw_recorded_geometry,
    validate_recorded_geometry_identity,
)
from Main_App.processing.acquisition_policy import brain_products_policy
from Main_App.processing.preprocess import _build_preproc_fingerprint, perform_preprocessing
from Main_App.processing.preflight_qc import _find_preflight_events, _preflight_scalp_picks
from Main_App.processing.raw_channel_qc import evaluate_raw_channel_qc


def _params(**updates):
    return {
        "hardware_platform": "brain_products", "hardware_confirmed": True,
        "electrode_montage": "recorded", "initial_reference": "recorded",
        "initial_reference_channels": [], "drop_reference_channels": False,
        "max_idx_keep": None, "stim_channel": "Status", "downsample_rate": None,
        "high_pass": None, "low_pass": None, "line_noise_filter_enabled": False,
        "kurtosis_screening_enabled": False, "raw_signal_screening_enabled": False,
        "removed_electrode_detection_mode": "off", "auto_detect_removed_electrodes": False,
        **updates,
    }


def _raw(names=("E1", "E2", "E3", "E4"), samples=1024):
    rng = np.random.default_rng(420)
    data = rng.normal(scale=1e-6, size=(len(names) + 1, samples))
    data[-1] = 0
    data[-1, [0, 100, 300]] = [21, 22, 21]
    raw = mne.io.RawArray(data, mne.create_info([*names, "Status"], 256, ["eeg"] * len(names) + ["stim"]), verbose=False)
    attach_raw_recorded_geometry(raw)
    return raw


def test_recorded_reference_arbitrary_channels_preserves_data_scale_and_events():
    raw = _raw()
    before = raw.get_data().copy()
    params = _params()
    result, rejected = perform_preprocessing(raw, params, lambda _: None, "recording.vhdr")
    assert result is not None, params.get("_fpvs_preprocessing_error")
    assert rejected == 0
    assert result.ch_names == ["E1", "E2", "E3", "E4", "Status"]
    np.testing.assert_allclose(result.get_data()[:-1], before[:-1] - before[:-1].mean(axis=0), atol=1e-20)
    np.testing.assert_array_equal(result.get_data()[-1], before[-1])
    assert params["_fpvs_initial_reference_mode"] == "recorded"
    assert params["_fpvs_geometry"]["geometry_status"] == "unavailable"
    assert params["_fpvs_interpolation_status"] == "not_needed"
    events, _ = _find_preflight_events(result, stim_channel="Status")
    assert events[:, 0].tolist() == [0, 100, 300]


def test_more_than_64_channels_are_not_truncated():
    names = tuple(f"E{i}" for i in range(80))
    raw = _raw(names)
    params = _params()
    result, _ = perform_preprocessing(raw, params, lambda _: None)
    assert result is not None
    assert result.ch_names == [*names, "Status"]
    picks, retained = _preflight_scalp_picks(result, settings=params)
    assert len(picks) == 80
    assert retained == names


def test_selected_reference_channel_is_only_dropped_when_explicitly_requested():
    raw = _raw()
    before = raw.get_data().copy()
    params = _params(initial_reference="channels", initial_reference_channels=["E2"], drop_reference_channels=True)
    result, _ = perform_preprocessing(raw, params, lambda _: None)
    assert result is not None, params.get("_fpvs_preprocessing_error")
    assert result.ch_names == ["E1", "E3", "E4", "Status"]
    expected = before[[0, 2, 3]]
    expected -= expected.mean(axis=0)
    np.testing.assert_allclose(result.get_data()[:-1], expected, atol=1e-20)
    assert params["_fpvs_initial_ref_pair"] == ("E2",)


def test_template_geometry_is_explicit_and_fingerprinted():
    raw = _raw(("Fp1", "Fp2", "O1", "O2"))
    before = validate_raw_recorded_geometry(raw)
    assert not before["interpolation_supported"]
    after = attach_raw_recorded_geometry(raw, template_montage="standard_1020")
    assert after["interpolation_supported"]
    assert after["coordinate_source"] == "explicit_project_template"
    assert after["coordinate_fingerprint"] != before["coordinate_fingerprint"]
    assert validate_recorded_geometry_identity(after) == after
    mutated = copy.deepcopy(after)
    mutated["channel_coordinates_m"]["Fp1"][0] += 0.001
    with pytest.raises(ValueError, match="inconsistent"):
        validate_recorded_geometry_identity(mutated)
    raw.info["chs"][0]["loc"][0] += 0.001
    with pytest.raises(ValueError, match="changed"):
        validate_raw_recorded_geometry(raw)


def test_template_never_silently_assigns_unknown_electrodes():
    raw = _raw()
    with pytest.raises(ValueError, match="subset"):
        attach_raw_recorded_geometry(raw, template_montage="standard_1020")


def test_no_geometry_bad_channel_stops_before_false_interpolation_success():
    raw = _raw()
    raw.info["bads"] = ["E1"]
    params = _params()
    result, _ = perform_preprocessing(raw, params, lambda _: None)
    assert result is None
    assert "head coordinates" in params["_fpvs_preprocessing_error"]
    assert params["_fpvs_interpolated_channels"] == []


def test_unqualified_kurtosis_setting_is_rejected():
    params = _params(kurtosis_screening_enabled=True, reject_thresh=5)
    result, _ = perform_preprocessing(_raw(), params, lambda _: None)
    assert result is None
    assert "not qualified" in params["_fpvs_preprocessing_error"]


def test_raw_qc_reports_unavailable_without_biosemi_channel_denominator():
    result = evaluate_raw_channel_qc(_raw(), _params(), filename="recording.vhdr")
    assert result.n_channels == 4
    payload = result.to_payload()
    assert payload["evaluation_status"] == "not_evaluated"
    assert payload["reason"] == "unsupported_hardware_profile"
    assert not result.channels_to_interpolate


def test_hardware_confirmation_and_reference_policy_invalidate_identity():
    with pytest.raises(ValueError, match="Confirm Brain Products"):
        brain_products_policy(_params(hardware_confirmed=False))
    base = _build_preproc_fingerprint(_params())
    changed = _build_preproc_fingerprint(_params(initial_reference="channels", initial_reference_channels=["E1"]))
    assert base != changed
    assert "geometry=recorded_eeg_geometry_v1" in base
    assert "biosemi64" not in base


def test_recorded_source_coverage_round_trip_and_missing_roi_are_explicit():
    from Main_App.processing.roi_coverage import (
        RoiSourceCoverageError, _roi_memberships, _source_evidence_from_payload,
        freeze_retained_scalp_identity, validate_roi_source_rows,
    )
    from Main_App.processing.roi_settings import build_roi_definition_snapshot

    geometry = validate_raw_recorded_geometry(_raw())
    retained = freeze_retained_scalp_identity(geometry)
    rows = [{"Electrode": name, "1.2000_Hz": 2.5} for name in retained.channels]
    evidence = validate_roi_source_rows(rows, retained_scalp=retained, required_columns=["1.2000_Hz"])
    restored = _source_evidence_from_payload(evidence.to_payload())
    assert restored.to_payload() == evidence.to_payload()
    assert restored.expected_scalp_channels == ("E1", "E2", "E3", "E4")
    with pytest.raises(RoiSourceCoverageError, match="missing retained"):
        validate_roi_source_rows(rows[:-1], retained_scalp=retained, required_columns=["1.2000_Hz"])
    snapshot = build_roi_definition_snapshot({"Posterior": ["O1", "O2"]})
    coverage = _roi_memberships(snapshot, evidence)[0]
    assert coverage.status == "unavailable"
    assert coverage.reason_codes == ("required_electrodes_not_recorded",)
    assert coverage.used_channels == ()


def test_declining_adjacent_marker_codes_are_preserved_without_annotation_fallback():
    raw = _raw()
    raw._data[-1, :3] = [22, 21, 0]
    events, source = _find_preflight_events(raw, stim_channel="Status")
    assert source == "stim"
    assert events[:2, [0, 2]].tolist() == [[0, 22], [1, 21]]


def test_channel_roles_are_bound_into_pipeline_fingerprint():
    assert _build_preproc_fingerprint(_params()) != _build_preproc_fingerprint(_params(channel_types={"E1": "eog"}))


def test_brain_products_filter_downsample_reference_matches_mne_reference():
    raw = _raw(samples=20000)
    expected = raw.copy()
    expected.filter(
        0.1, 40.0, method="fir", phase="zero-double", fir_window="hamming",
        fir_design="firwin", l_trans_bandwidth=0.1, h_trans_bandwidth=0.1,
        filter_length=16897, skip_by_annotation="edge", verbose=False,
    )
    expected.resample(128, npad="auto", window="hann", verbose=False)
    expected.set_eeg_reference(ref_channels="average", projection=True, verbose=False)
    expected.apply_proj(verbose=False)
    params = _params(high_pass=0.1, low_pass=40.0, downsample_rate=128)
    processed, _ = perform_preprocessing(raw, params, lambda _: None)
    assert processed is not None, params.get("_fpvs_preprocessing_error")
    assert processed.info["sfreq"] == 128
    np.testing.assert_array_equal(processed.get_data(), expected.get_data())


def test_brain_products_does_not_publish_success_after_filter_failure(monkeypatch):
    from Main_App.processing import preprocess

    def fail(*_args, **_kwargs):
        raise ValueError("invalid recording cutoff")

    monkeypatch.setattr(preprocess, "filter_raw_with_prepared_fir", fail)
    params = _params(high_pass=0.1, low_pass=40.0)
    result, _ = perform_preprocessing(_raw(), params, lambda _: None)
    assert result is None
    assert "Brain Products filtering failed" in params["_fpvs_preprocessing_error"]


@pytest.mark.parametrize("references", [[], ["E1", "E2"]])
def test_brain_products_audit_records_actual_reference_without_exg_assumptions(references):
    from Main_App.diagnostics.audit import compare_preproc, end_preproc_audit, start_preproc_audit

    params = _params(
        initial_reference="channels" if references else "recorded",
        initial_reference_channels=references,
        ref_channel1="EXG1", ref_channel2="EXG2",
    )
    raw = _raw()
    before = start_preproc_audit(raw, params)
    processed, _ = perform_preprocessing(raw, params, lambda _: None)
    assert processed is not None
    after = end_preproc_audit(processed, params, filename="recording.vhdr")
    assert after["initial_reference_mode"] == params["initial_reference"]
    assert after["initial_reference_channels"] == references
    assert after["ref_chans"] == (references or None)
    assert after["ref_applied"] is bool(references)
    assert after["reference_requested"] is bool(references)
    assert not any("reference" in value for value in compare_preproc(before, after, params))
