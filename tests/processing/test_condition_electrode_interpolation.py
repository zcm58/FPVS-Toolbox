from __future__ import annotations

from copy import deepcopy
import hashlib
import json

import mne
import numpy as np
import pytest

from Main_App.io.eeg_geometry import (
    BIOSEMI64_CHANNELS, attach_raw_biosemi64_geometry, cached_biosemi64_montage,
    read_raw_biosemi64_geometry,
)
from Main_App.processing.analysis_spans import read_source_analysis_span_plan, realize_target_analysis_span_plan
from Main_App.processing.condition_electrode_interpolation import (
    apply_condition_repairs, condition_interpolation_export_provenance,
    prepare_condition_repairs, validate_condition_interpolation_provenance,
)
from Main_App.processing.preflight_qc_plan import plan_preflight_qc_events
from Main_App.processing.preprocess import _finish_preprocessing_at_kurtosis
from Main_App.projects import EXPECTED_CYCLES_SOURCE_MANUAL, FrequencyProtocol


def _case(first_samp=0):
    names = [*BIOSEMI64_CHANNELS, "Status"]
    data = np.random.default_rng(2468).normal(scale=1e-6, size=(65, 1600))
    events = np.array([[0, 0, 1], *[[100 + n * 50, 0, 55] for n in range(11)],
                       [800, 0, 2], *[[900 + n * 50, 0, 55] for n in range(11)]])
    data[-1] = 0
    data[-1, events[:, 0]] = events[:, 2]
    raw = mne.io.RawArray(data, mne.create_info(names, 100, ["eeg"] * 64 + ["stim"]), first_samp=first_samp, verbose=False)
    raw.set_montage(cached_biosemi64_montage(), verbose=False)
    attach_raw_biosemi64_geometry(raw, electrode_mapping_profile="anatomical_labels",
                                 retained_channels=BIOSEMI64_CHANNELS, stim_channel="Status")
    raw.info["bads"] = ["Fp1"]
    protocol = FrequencyProtocol.from_recurrence(10, 5, expected_analyzed_oddball_cycles=10,
                                               expected_analyzed_oddball_cycles_source=EXPECTED_CYCLES_SOURCE_MANUAL)
    event_plan = plan_preflight_qc_events(events=events + [first_samp, 0, 0], event_map={"A": 1, "B": 2}, sfreq=100,
                                        n_times=1600, first_samp=first_samp, frequency_protocol=protocol).to_payload()
    source = read_source_analysis_span_plan(event_plan)
    target = realize_target_analysis_span_plan(source, target_sfreq_hz=100, target_n_times=1600, target_first_samp=first_samp)
    return raw, {"reject_thresh": None, "stim_channel": "Status",
                 "_fpvs_source_analysis_span_plan": source, "_fpvs_realized_analysis_span_plan": target,
                 "_fpvs_condition_interpolation_requests": {"A": ["Oz"]}}


def _normal(raw):
    raw.interpolate_bads(reset_bads=True, mode="accurate", verbose=False)
    raw.set_eeg_reference(ref_channels="average", projection=True, verbose=False)
    raw.apply_proj(verbose=False)
    return raw


@pytest.mark.parametrize("first_samp", [0, 73])
def test_only_exact_condition_samples_change_and_reference_uses_joint_bad_set(first_samp):
    raw, params = _case(first_samp)
    original_stim = raw.get_data(picks="Status").tobytes()
    plan = deepcopy(params["_fpvs_realized_analysis_span_plan"])
    normal = _normal(raw.copy())
    coords = plan["spans"][0]["target_coordinates"]
    start, stop = coords["start_relative_sample"], coords["stop_relative_sample"]
    expected = mne.io.RawArray(raw.get_data(start=start, stop=stop), raw.info.copy(), first_samp=raw.first_samp + start, verbose=False)
    expected.info["bads"] = ["Fp1", "Oz"]
    _normal(expected)

    repairs = prepare_condition_repairs(raw, params)
    processed = _normal(raw.copy())
    provenance = apply_condition_repairs(processed, repairs)

    assert processed.get_data(start=0, stop=start).tobytes() == normal.get_data(start=0, stop=start).tobytes()
    assert processed.get_data(start=stop).tobytes() == normal.get_data(start=stop).tobytes()
    assert processed.get_data(start=start, stop=stop).tobytes() == expected.get_data().tobytes()
    assert processed.get_data(picks="Status").tobytes() == original_stim
    assert params["_fpvs_realized_analysis_span_plan"] == plan
    assert processed.first_samp == raw.first_samp and processed.n_times == raw.n_times
    assert provenance["spans"][0]["interpolated_channels"] == ["Fp1", "Oz"]
    assert provenance["spans"][0]["target_coordinates"] == coords
    assert provenance["status"] == "completed"


def test_finish_stage_records_completed_local_repair_separately_from_global():
    raw, params = _case()
    processed, rejected = _finish_preprocessing_at_kurtosis(
        raw, params, lambda _: None, filename_for_log="synthetic.bdf", orig_sfreq=100,
        debug_enabled=False, geometry_identity=read_raw_biosemi64_geometry(raw),
    )
    assert processed is raw and rejected == 0
    assert params["_fpvs_interpolated_channels"] == ["Fp1"]
    proof = params["_fpvs_condition_interpolation_provenance"]
    assert proof["status"] == "completed" and proof["requests"] == {"A": ["Oz"]}
    assert condition_interpolation_export_provenance(params, "B") == {}
    assert condition_interpolation_export_provenance(params, "A")["requested_channels"] == ["Oz"]


def test_no_requests_leaves_existing_preprocessing_bit_identical():
    raw, params = _case()
    params.pop("_fpvs_condition_interpolation_requests")
    expected = _normal(raw.copy())
    processed, _ = _finish_preprocessing_at_kurtosis(raw, params, lambda _: None,
        filename_for_log="synthetic.bdf", orig_sfreq=100, debug_enabled=False,
        geometry_identity=read_raw_biosemi64_geometry(raw))
    assert processed.get_data().tobytes() == expected.get_data().tobytes()
    assert "_fpvs_condition_interpolation_provenance" not in params


@pytest.mark.parametrize("case", ["missing_condition", "missing_channel", "nonfinite_donor", "stale_timing"])
def test_unsafe_request_fails_before_any_raw_mutation(case):
    raw, params = _case()
    if case == "missing_condition":
        params["_fpvs_condition_interpolation_requests"] = {"Absent": ["Oz"]}
    elif case == "missing_channel":
        params["_fpvs_condition_interpolation_requests"] = {"A": ["EXG1"]}
    elif case == "nonfinite_donor":
        raw._data[raw.ch_names.index("Cz"), 150] = np.nan
    else:
        params["_fpvs_realized_analysis_span_plan"]["spans"][0]["target_coordinates"]["start_relative_sample"] += 1
    before = raw.get_data().tobytes()
    with pytest.raises((ValueError, RuntimeError)):
        prepare_condition_repairs(raw, params)
    assert raw.get_data().tobytes() == before


def test_cached_provenance_must_match_exact_requests_and_spans():
    raw, params = _case()
    proof = prepare_condition_repairs(raw, params).provenance
    kwargs = {"requests": params["_fpvs_condition_interpolation_requests"],
              "analysis_span_plan": params["_fpvs_realized_analysis_span_plan"],
              "geometry": read_raw_biosemi64_geometry(raw)}
    assert validate_condition_interpolation_provenance(json.loads(json.dumps(proof)), **kwargs) == proof
    for invalid in (None, {**proof, "status": "pending"}, {**proof, "requests": {"A": ["Cz"]}},
                    {**proof, "analysis_span_fingerprint": "old"}):
        with pytest.raises(ValueError):
            validate_condition_interpolation_provenance(invalid, **kwargs)


@pytest.mark.parametrize("defect", ["missing_occurrence", "shifted_samples", "wrong_channels", "wrong_geometry"])
def test_self_consistent_proof_hash_does_not_override_real_repair_requirements(defect):
    raw, params = _case()
    proof = deepcopy(prepare_condition_repairs(raw, params).provenance)
    if defect == "missing_occurrence":
        proof["spans"] = []
    elif defect == "shifted_samples":
        proof["spans"][0]["target_coordinates"]["start_relative_sample"] += 1
    elif defect == "wrong_channels":
        proof["spans"][0]["interpolated_channels"] = ["Fp1", "Cz"]
    else:
        proof["geometry_fingerprint"] = "another geometry"
    proof.pop("fingerprint")
    proof["fingerprint"] = hashlib.sha256(json.dumps(proof, sort_keys=True, separators=(",", ":"),
                                                    allow_nan=False).encode()).hexdigest()
    with pytest.raises(ValueError):
        validate_condition_interpolation_provenance(proof,
            requests=params["_fpvs_condition_interpolation_requests"],
            analysis_span_plan=params["_fpvs_realized_analysis_span_plan"],
            geometry=read_raw_biosemi64_geometry(raw))


def test_explicitly_excluded_condition_does_not_apply_its_persisted_repair():
    raw, params = _case()
    params["_fpvs_excluded_condition_labels"] = ["a"]
    original_requests = deepcopy(params["_fpvs_condition_interpolation_requests"])
    expected = _normal(raw.copy())
    processed, _ = _finish_preprocessing_at_kurtosis(raw, params, lambda _: None,
        filename_for_log="synthetic.bdf", orig_sfreq=100, debug_enabled=False,
        geometry_identity=read_raw_biosemi64_geometry(raw))
    assert processed.get_data().tobytes() == expected.get_data().tobytes()
    assert params["_fpvs_condition_interpolation_requests"] == original_requests
    assert "_fpvs_condition_interpolation_provenance" not in params


def test_overlapping_conditions_with_different_repairs_fail_closed():
    raw, params = _case()
    source = deepcopy(params["_fpvs_source_analysis_span_plan"])
    source["spans"][1]["source_coordinates"] = deepcopy(source["spans"][0]["source_coordinates"])
    for value in [source["spans"][1], source]:
        value.pop("fingerprint", None)
        value["fingerprint"] = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                                        ensure_ascii=False, allow_nan=False).encode()).hexdigest()
    params["_fpvs_source_analysis_span_plan"] = source
    params["_fpvs_realized_analysis_span_plan"] = realize_target_analysis_span_plan(
        source, target_sfreq_hz=100, target_n_times=1600, target_first_samp=0,
    )
    original = raw.get_data().tobytes()
    with pytest.raises(ValueError, match="Overlapping analyzed intervals"):
        prepare_condition_repairs(raw, params)
    assert raw.get_data().tobytes() == original


def test_repaired_raw_cache_preserves_float64_samples_and_proof(tmp_path):
    from Main_App.Performance import process_runner
    raw, params = _case()
    source = tmp_path / "P1.bdf"
    source.write_bytes(b"synthetic source identity")
    params.update({"high_pass": 0.1, "low_pass": 50.0, "max_idx_keep": 64})
    with raw.info._unlock():
        raw.info["highpass"] = 0.1
    raw, _ = _finish_preprocessing_at_kurtosis(raw, params, lambda _: None,
        filename_for_log=source.name, orig_sfreq=100, debug_enabled=False,
        geometry_identity=read_raw_biosemi64_geometry(raw))
    original = raw.get_data().tobytes()
    kwargs = {"file_path": source, "settings": params, "project_root": tmp_path, "mne_module": mne}
    assert process_runner._store_preprocessed_cache(raw=raw, audit_before={}, n_rejected=0, **kwargs) == "stored"
    expected_proof = deepcopy(params.pop("_fpvs_condition_interpolation_provenance"))
    loaded, _, _, status = process_runner._load_preprocessed_cache(**kwargs)
    assert status == "hit"
    try:
        assert loaded.get_data().tobytes() == original
        assert params["_fpvs_condition_interpolation_provenance"] == expected_proof
    finally:
        loaded.close()


def test_live_requests_override_stale_settings_and_select_recording(tmp_path):
    from Main_App.Performance import process_runner
    source = tmp_path / "P1.bdf"
    source.write_bytes(b"original recording")
    stat = source.stat()
    (tmp_path / "project.json").write_text(json.dumps({"tools": {"condition_electrode_interpolation": {
        "version": "condition_electrode_interpolation_v1", "requests": {"P1": {"A": ["Oz"]}},
        "source_identities": {"P1": {"raw_file": str(source), "raw_size": stat.st_size, "raw_mtime_ns": stat.st_mtime_ns}},
    }}}))
    current = process_runner._with_current_condition_repairs({
        "condition_electrode_interpolation_requests": {"P2": {"B": ["Cz"]}},
        "_fpvs_condition_interpolation_requests": {"Old": ["Cz"]},
    }, tmp_path)
    settings = process_runner._settings_for_file(tmp_path / "P1.bdf", current)
    assert settings["_fpvs_condition_interpolation_requests"] == {"A": ["Oz"]}
    other = process_runner._settings_for_file(tmp_path / "P2.bdf", current)
    assert other["_fpvs_condition_interpolation_requests"] == {}
    source.write_bytes(b"a different recording")
    assert "condition_electrode_interpolation_requests" not in process_runner._with_current_condition_repairs(current, tmp_path)


def test_requests_change_only_final_raw_cache_identity(tmp_path):
    from Main_App.Performance import process_runner
    from Main_App.processing.preprocess import _build_preproc_fingerprint
    source = tmp_path / "P1.bdf"
    source.write_bytes(b"synthetic source identity")
    settings = {"stim_channel": "Status", "high_pass": 0.1, "low_pass": 50}
    repaired = {**settings, "_fpvs_condition_interpolation_requests": {"A": ["Oz"]}}
    original_key = process_runner._preproc_cache_key(process_runner._preproc_cache_payload(source, settings, mne_version=mne.__version__))
    repaired_key = process_runner._preproc_cache_key(process_runner._preproc_cache_payload(source, repaired, mne_version=mne.__version__))
    assert original_key != repaired_key
    assert _build_preproc_fingerprint(settings) == _build_preproc_fingerprint(repaired)


@pytest.mark.parametrize("recording_id", [None, "P1_visit2"])
def test_worker_does_not_apply_approval_from_another_source_path(tmp_path, monkeypatch, recording_id):
    from Main_App.Performance import process_runner
    old = tmp_path / "old.bdf"
    new = tmp_path / "new.bdf"
    old.write_bytes(b"original recording")
    new.write_bytes(b"replacement recording")
    stat = old.stat()
    identity = recording_id or "P1"
    state = {"version": "condition_electrode_interpolation_v1",
        "requests": {identity: {"A": ["Oz"]}},
        "source_identities": {identity: {"raw_file": str(old), "raw_size": stat.st_size,
                                         "raw_mtime_ns": stat.st_mtime_ns}}}
    (tmp_path / "project.json").write_text(json.dumps({"tools": {"condition_electrode_interpolation": state}}))
    settings = {"_fpvs_participant_id_by_file": {str(new.resolve()): "P1"}}
    if recording_id:
        settings["_fpvs_recording_id_by_file"] = {str(new.resolve()): recording_id}
    observed = {}
    def capture_pipeline(file_path, effective, *args):
        observed.update(effective)
        return {"status": "captured"}
    monkeypatch.setattr(process_runner, "_run_full_pipeline_for_file", capture_pipeline)
    result = process_runner._process_one_file(new, settings, {"A": 1}, tmp_path, tmp_path)
    assert result["status"] == "captured"
    assert "condition_electrode_interpolation_requests" not in observed
    assert old.exists()
    assert json.loads((tmp_path / "project.json").read_text())["tools"]["condition_electrode_interpolation"] == state


def test_parent_reconciles_approvals_against_canonical_active_source_paths(tmp_path, monkeypatch):
    from Main_App.Performance import process_runner
    source = tmp_path / "recording.bdf"
    settings = {"_fpvs_participant_id_by_file": {str(source.resolve()): "P1"},
                "_fpvs_recording_id_by_file": {str(source.resolve()): "P1_visit2"}}
    observed = {}
    def capture_reconcile(root, *, current_sources):
        observed.update(current_sources)
        raise RuntimeError("stop before launching processing")
    monkeypatch.setattr(process_runner, "reconcile_condition_interpolation_sources", capture_reconcile)
    params = process_runner.RunParams(project_root=tmp_path, data_files=[source], settings=settings,
                                     event_map={"A": 1}, save_folder=tmp_path)
    with pytest.raises(RuntimeError, match="stop before launching processing"):
        process_runner.run_project_parallel(params)
    assert observed == {"P1_visit2": str(source.resolve())}
