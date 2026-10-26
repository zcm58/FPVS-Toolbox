"""Source maps retain native event evidence through planning and execution."""
from __future__ import annotations

from dataclasses import replace
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import mne
import numpy as np
import pytest

from Main_App.io.eeg_geometry import attach_raw_biosemi64_geometry, biosemi64_geometry_identity, cached_biosemi64_montage
from Main_App.processing.analysis_spans import realize_target_analysis_span_plan, validate_source_analysis_span_context
from Main_App.processing.expected_processing_ledger import ExpectedRecordingConditionPlan, build_expected_recording_condition_plan
from Main_App.processing.preflight_qc_plan import plan_preflight_qc_events
from Main_App.processing.processing_controller import RawFileInfo
from Main_App.processing.processing_ledger import ProcessingInputState, ProcessingPlan
from Main_App.projects import EXPECTED_CYCLES_SOURCE_MANUAL, FrequencyProtocol
from Main_App.projects.condition_trigger_maps import resolve_recording_event_schema
from Main_App.workers import process_runner


@pytest.mark.parametrize("use_canonical_ids", [False, True])
def test_reused_worker_crop_logs_keep_independent_same_basename_sources(tmp_path, monkeypatch, use_canonical_ids):
    monkeypatch.setattr(process_runner.os, "getpid", lambda: 12345)
    paths = []
    for group, processing_id in (("Adults", "MCCTRP1"), ("Adolescents", "ACRP1")):
        crop_logger = process_runner._build_fft_crop_file_logger(
            tmp_path, tmp_path / "Input" / group / "p1.bdf",
            processing_id=processing_id if use_canonical_ids else None,
        )
        try:
            paths.append(Path(crop_logger.handlers[0].baseFilename))
            crop_logger.info("%s crop evidence", group)
        finally:
            process_runner._close_worker_logger(crop_logger)
    assert paths[0] != paths[1]
    assert "Adults crop evidence" in paths[0].read_text(encoding="utf-8")
    assert "Adolescents crop evidence" in paths[1].read_text(encoding="utf-8")
    assert all(path.parent == tmp_path / "logs" for path in paths)
    if use_canonical_ids:
        assert paths[0].name.startswith("fft_crop_MCCTRP1_")
        assert paths[1].name.startswith("fft_crop_ACRP1_")


def _protocol():
    return FrequencyProtocol.from_recurrence(
        6, 3, expected_analyzed_oddball_cycles=2,
        expected_analyzed_oddball_cycles_source=EXPECTED_CYCLES_SOURCE_MANUAL,
    ).with_condition_trigger_maps({
        "schema_version": "1.0",
        "canonical_conditions": {"faces": {"label": "Faces"}, "objects": {"label": "Objects"}},
        "profiles": {
            "acr": {"conditions": {"faces": {"onset_code": 11, "oddball_code": 55},
                                     "objects": {"onset_code": 12, "oddball_code": 55}},
                    "boundary_only_onset_codes": [99]},
            "adult": {"conditions": {"faces": {"onset_code": 12, "oddball_code": 56},
                                       "objects": {"onset_code": 11, "oddball_code": 56}},
                      "boundary_only_onset_codes": [88]},
        },
        "recording_assignments": {"ACRP1": "acr", "MCCTRP1": "adult"},
    })


def _events(recording):
    a, b, odd, boundary = (11, 12, 55, 99) if recording == "ACRP1" else (12, 11, 56, 88)
    return np.asarray([[0, 0, a], [2, 0, odd], [8, 0, odd], [14, 0, odd],
                       [20, 0, boundary], [22, 0, odd], [30, 0, b],
                       [32, 0, odd], [38, 0, odd], [44, 0, odd]], dtype=np.int64)


def _plan(protocol, recording):
    return plan_preflight_qc_events(events=_events(recording), event_map={}, sfreq=12,
                                    n_times=60, frequency_protocol=protocol, recording_id=recording)


def test_mapped_plans_preserve_events_boundaries_and_canonical_cells(tmp_path):
    protocol = _protocol()
    states, plans = [], {}
    for recording in ("ACRP1", "MCCTRP1"):
        folder = tmp_path / recording
        folder.mkdir()
        path = folder / "P1.bdf"
        path.write_bytes(b"unchanged source")
        info = RawFileInfo(path, recording)
        states.append(ProcessingInputState(
            info=info, participant_id=recording, status="new", reason="test",
            expected_outputs=tuple(tmp_path / f"{recording}_{label}.xlsx" for label in ("Faces", "Objects")),
        ))
        events = _events(recording)
        original = events.copy()
        plan = plan_preflight_qc_events(events=events, event_map={}, sfreq=12, n_times=60,
                                        frequency_protocol=protocol, recording_id=recording)
        np.testing.assert_array_equal(events, original)
        first = plan.marker_integrity_plan["occurrences"][0]
        assert first["block_stop_sample"] == 20
        assert first["raw_marker_samples"] == [2, 8, 14]
        assert first["canonical_condition_id"] == "faces"
        assert first["condition_code"] == (11 if recording == "ACRP1" else 12)
        assert len(plan.spans) == 2
        plans[str(path.resolve())] = plan.to_payload()
        validate_source_analysis_span_context(event_plan_payload=plan.to_payload(), event_map={},
                                              protocol=protocol, recording_id=recording)
    processing = ProcessingPlan(states=tuple(states), fingerprint="shared-protocol", condition_labels=("Faces", "Objects"),
                                geometry_identity=biosemi64_geometry_identity())
    expected = build_expected_recording_condition_plan(processing_plan=processing, event_map={},
                                                       frequency_protocol=protocol, approved_event_plans=plans)
    assert expected.event_map == ()
    assert [recording.cells[0].cell_id for recording in expected.recordings] == ["ACRP1:faces", "MCCTRP1:faces"]
    assert [recording.cells[0].condition_code for recording in expected.recordings] == [11, 12]
    assert ExpectedRecordingConditionPlan.from_payload(expected.to_payload()) == expected
    with pytest.raises(ValueError, match="recording identity"):
        validate_source_analysis_span_context(event_plan_payload=plans[next(iter(plans))], event_map={},
                                              protocol=protocol, recording_id="MCCTRP1")
    with pytest.raises(ValueError, match="occurrence identity"):
        replace(expected.recordings[0].cells[0], condition_code=12)


@pytest.mark.parametrize("recording", ["ACRP1", "MCCTRP1"])
def test_runner_resolves_native_codes_before_epochs_and_export(tmp_path, monkeypatch, recording):
    protocol = _protocol()
    events = _events(recording)
    path = tmp_path / "P1.bdf"
    path.write_bytes(b"raw fixture")
    raw = mne.io.RawArray(np.zeros((2, 60)), mne.create_info(["Cz", "Status"], 12, ["eeg", "stim"]), verbose=False)
    raw.set_montage(cached_biosemi64_montage(), on_missing="raise")
    attach_raw_biosemi64_geometry(raw, electrode_mapping_profile="anatomical_labels",
                                retained_channels=["Cz"], stim_channel="Status")
    captured = {}
    preprocess_calls = []

    def preprocess(raw_input, params, *_args, **_kwargs):
        preprocess_calls.append(True)
        params["_fpvs_realized_analysis_span_plan"] = realize_target_analysis_span_plan(
            params["_fpvs_source_analysis_span_plan"], target_sfreq_hz=12,
            target_n_times=60, target_first_samp=0,
        )
        return raw_input, 0

    def export(ctx, labels):
        captured.update(labels=labels, epochs=ctx.preprocessed_data)
        return 1

    monkeypatch.setattr("Main_App.io.load_utils.load_eeg_file", lambda *_args, **_kwargs: raw.copy())
    monkeypatch.setattr(mne, "find_events", lambda *_args, **_kwargs: events.copy())
    monkeypatch.setattr(process_runner.backend_preprocess, "begin_preproc_audit", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(process_runner.backend_preprocess, "perform_preprocessing", preprocess)
    monkeypatch.setattr(process_runner.backend_preprocess, "finalize_preproc_audit", lambda *_args, **_kwargs: ({}, []))
    monkeypatch.setattr("Main_App.exports.post_export_adapter.LegacyCtx", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr("Main_App.exports.post_export_adapter.run_post_export", export)
    settings = {"frequency_protocol": protocol, "stim_channel": "Status", "enable_preprocessed_cache": True,
                "ref_channel1": "EXG1", "ref_channel2": "EXG2",
                "_fpvs_participant_id_by_file": {str(path.resolve()): recording},
                "_fpvs_preflight_event_plans_by_file": {str(path.resolve()): _plan(protocol, recording).to_payload()}}
    result = process_runner._run_full_pipeline_for_file(path, settings, {}, tmp_path / "out", tmp_path / "project")
    assert result["status"] == "ok", result
    assert captured["labels"] == ["Faces", "Objects"]
    assert captured["epochs"]["Faces"][0].events[0, 2] == (11 if recording == "ACRP1" else 12)
    assert captured["epochs"]["Objects"][0].events[0, 2] == (12 if recording == "ACRP1" else 11)
    assert captured["epochs"]["Faces"][0].get_data().shape[-1] == 12
    warm = process_runner._run_full_pipeline_for_file(path, settings, {}, tmp_path / "out", tmp_path / "project")
    assert warm["status"] == "ok", warm
    assert warm["preproc_cache_status"] == "hit"
    assert len(preprocess_calls) == 1
    assert path.read_bytes() == b"raw fixture"


def test_interpreted_caches_invalidate_all_profiles_but_preserve_cosmetic_edits(tmp_path):
    protocol = _protocol()
    path = tmp_path / "P1.bdf"
    path.write_bytes(b"source identity")
    payload = protocol.condition_trigger_maps.to_manifest()
    cosmetic = deepcopy(payload)
    cosmetic["profiles"]["acr"]["label"] = "Adolescent acquisition"
    cosmetic["registration_group_defaults"] = {"adolescents": "acr"}
    scientific = deepcopy(payload)
    scientific["profiles"]["acr"]["boundary_only_onset_codes"] = [100]
    same = protocol.with_condition_trigger_maps(cosmetic)
    changed = protocol.with_condition_trigger_maps(scientific)

    def cache_key(candidate):
        schema = resolve_recording_event_schema(candidate, "MCCTRP1")
        cache = process_runner._preproc_cache_payload(
            path, {"stim_channel": "Status", "max_idx_keep": 64}, mne_version=mne.__version__,
            frequency_protocol=candidate, event_map=schema.event_map,
        )
        return process_runner._preproc_cache_key(cache)

    assert cache_key(protocol) == cache_key(same)
    assert cache_key(protocol) != cache_key(changed)
    from Main_App.processing.preflight_qc import _preflight_cache_settings
    from Main_App.processing.processing_ledger import build_processing_fingerprint

    def settings_for(candidate):
        return {"frequency_protocol": candidate, "analysis": {"frequency_protocol": candidate.to_manifest()}}

    assert _preflight_cache_settings(settings_for(protocol)) == _preflight_cache_settings(settings_for(same))
    assert _preflight_cache_settings(settings_for(protocol)) != _preflight_cache_settings(settings_for(changed))
    project = SimpleNamespace(frequency_protocol=protocol)
    assert build_processing_fingerprint(project, settings_for(protocol), {}) == build_processing_fingerprint(
        project, settings_for(same), {},
    )
    prior = _plan(protocol, "MCCTRP1").to_payload()
    with pytest.raises(ValueError, match="protocol is stale"):
        validate_source_analysis_span_context(event_plan_payload=prior, event_map={},
                                              protocol=changed, recording_id="MCCTRP1")


def test_mapped_export_receipt_identifies_source_and_rejects_wrong_interpretation(tmp_path):
    from Main_App.exports.post_process import _trigger_interpretation_payload
    from Main_App.processing.recording_condition_outcomes import _validate_written_receipt
    protocol = _protocol()
    schema = resolve_recording_event_schema(protocol, "ACRP1")
    receipt = _trigger_interpretation_payload(protocol, {"_fpvs_participant_id": "ACRP1"}, "Faces")
    assert receipt["canonical_condition_id"] == "faces"
    assert receipt["source_onset_code"] == 11
    assert receipt["source_oddball_code"] == 55
    assert receipt["source_trigger_profile_id"] == "acr"
    plan = SimpleNamespace(run_id="run", processing_fingerprint="processing", processing_fingerprint_version="v",
                           protocol_fingerprint=protocol.fingerprint, geometry_identity=biosemi64_geometry_identity())
    cell = SimpleNamespace(condition_label="Faces", canonical_condition_id="faces", condition_code=11,
                           trigger_map_fingerprint=schema.interpretation_fingerprint,
                           expected_workbook=str(tmp_path / "output.xlsx"))
    good = _validate_written_receipt(plan=plan, recording=SimpleNamespace(processing_id="ACRP1"),
                                    cell=cell, receipt=receipt, validate_artifacts=False)
    bad = _validate_written_receipt(plan=plan, recording=SimpleNamespace(processing_id="ACRP1"),
                                   cell=cell, receipt={**receipt, "source_onset_code": 12}, validate_artifacts=False)
    assert "source_onset_code_mismatch" not in good
    assert "trigger_map_fingerprint_mismatch" not in good
    assert "source_onset_code_mismatch" in bad
