from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import mne
import numpy as np
import pytest

from Main_App.io.eeg_geometry import (
    BIOSEMI64_CHANNELS,
    attach_raw_biosemi64_geometry,
    cached_biosemi64_montage,
)
from Main_App.processing.analysis_spans import read_source_analysis_span_plan
from Main_App.processing.kurtosis_qc import (
    KURTOSIS_DECISION_APPROVE,
    build_kurtosis_review_decision,
    KURTOSIS_REVIEW_DECISION_SCHEMA_VERSION,
    KURTOSIS_REVIEWER_IDENTITY_STATUS_NOT_COLLECTED,
    KURTOSIS_REVIEWER_STATE_EXPLICIT_GUI,
    KURTOSIS_REVIEWER_STATE_EXPERIMENTAL_AUTO,
)
from Main_App.processing.preflight_qc_plan import plan_preflight_qc_events
from Main_App.processing.preprocess import (
    perform_preprocessing,
    prepare_kurtosis_review_evidence,
)
from Main_App.projects import EXPECTED_CYCLES_SOURCE_MANUAL, FrequencyProtocol


def _raw() -> mne.io.RawArray:
    sfreq = 100.0
    sample_count = 1_000
    scalp = list(BIOSEMI64_CHANNELS[:20])
    names = ["EXG1", "EXG2", *scalp, "Status"]
    types = ["eeg", "eeg", *("eeg" for _ in scalp), "stim"]
    rng = np.random.default_rng(1601)
    data = rng.normal(scale=1e-6, size=(len(names), sample_count))
    data[names.index(scalp[0])] = rng.normal(scale=0.02e-6, size=sample_count)
    data[names.index(scalp[0]), ::50] = 500e-6
    data[names.index("Status")] = 0.0
    raw = mne.io.RawArray(
        data,
        mne.create_info(names, sfreq=sfreq, ch_types=types),
        verbose=False,
    )
    raw.set_montage(cached_biosemi64_montage(), on_missing="ignore", verbose=False)
    attach_raw_biosemi64_geometry(
        raw,
        electrode_mapping_profile="anatomical_labels",
        retained_channels=scalp,
        reference_channels=("EXG1", "EXG2"),
        stim_channel="Status",
    )
    return raw


def _source_plan() -> dict[str, object]:
    protocol = FrequencyProtocol.from_recurrence(
        10,
        5,
        expected_analyzed_oddball_cycles=10,
        expected_analyzed_oddball_cycles_source=EXPECTED_CYCLES_SOURCE_MANUAL,
    )
    events = np.asarray(
        [[0, 0, 1], *[[100 + index * 50, 0, 55] for index in range(11)]],
        dtype=int,
    )
    event_plan = plan_preflight_qc_events(
        events=events,
        event_map={"Condition": 1},
        sfreq=100.0,
        n_times=1_000,
        first_samp=0,
        frequency_protocol=protocol,
    ).to_payload()
    return read_source_analysis_span_plan(event_plan)


def _params(source_path: Path) -> dict[str, object]:
    return {
        "downsample_rate": 100,
        "low_pass": None,
        "high_pass": None,
        "line_noise_filter_enabled": False,
        "reject_thresh": 5.0,
        "ref_channel1": "EXG1",
        "ref_channel2": "EXG2",
        "max_idx_keep": 20,
        "stim_channel": "Status",
        "_fpvs_source_analysis_span_plan": _source_plan(),
        "_fpvs_require_analysis_spans": True,
        "_fpvs_source_file_path": str(source_path.resolve()),
        "_fpvs_participant_id": "P001",
        "_fpvs_recording_id": "P001_session-1",
        "_fpvs_session_id": "session-1",
        "_fpvs_session_label": "Visit 1",
    }


def _approval(
    evidence: dict[str, object],
    channel: str,
    source_path: Path,
) -> dict[str, object]:
    channel_row = next(
        row
        for row in evidence["channels"]
        if isinstance(row, dict) and row["channel"] == channel
    )
    scope = evidence["scoring_scope"]
    return {
        "schema_version": KURTOSIS_REVIEW_DECISION_SCHEMA_VERSION,
        "decision": KURTOSIS_DECISION_APPROVE,
        "reason": "Reviewed the filtered analyzed signal in the QC dialog.",
        "reviewed_at_utc": "2026-09-04T18:22:00Z",
        "reviewer_state": KURTOSIS_REVIEWER_STATE_EXPLICIT_GUI,
        "reviewer_identity": None,
        "reviewer_identity_status": (
            KURTOSIS_REVIEWER_IDENTITY_STATUS_NOT_COLLECTED
        ),
        "source_file_path": str(source_path.resolve()),
        "participant_id": "P001",
        "recording_id": "P001_session-1",
        "session_id": "session-1",
        "session_label": "Visit 1",
        "channel": channel,
        "reviewed_method_version": evidence["method_version"],
        "reviewed_registry_version": evidence["corroborator_registry_version"],
        "reviewed_evidence_fingerprint": evidence["fingerprint"],
        "reviewed_channel_evidence_fingerprint": channel_row["fingerprint"],
        "reviewed_analysis_span_fingerprint": scope["analysis_span_fingerprint"],
        "reviewed_occurrence_keys": [
            row["occurrence_key"] for row in scope["occurrences"]
        ],
    }


def test_kurtosis_only_candidate_stops_before_interpolation(tmp_path: Path) -> None:
    source_path = tmp_path / "P001.bdf"
    source_path.touch()
    params = _params(source_path)

    prepared = prepare_kurtosis_review_evidence(
        _raw(),
        params,
        lambda _message: None,
        source_path.name,
    )

    plan = prepared["decision_plan"]
    assert isinstance(plan, dict)
    assert plan["ready_for_interpolation"] is False
    pending = [
        row["channel"]
        for row in plan["channel_decisions"]
        if row["state"] == "review_required"
    ]
    assert pending == [BIOSEMI64_CHANNELS[0]]
    assert prepared["signal_preview"]["channels"][pending[0]]

    final_params = deepcopy(params)
    processed, _rejected = perform_preprocessing(
        _raw(),
        final_params,
        lambda _message: None,
        source_path.name,
    )
    assert processed is None
    assert final_params["_fpvs_interpolated_channels"] == []


@pytest.mark.parametrize("experimental", [False, True])
def test_current_gui_approval_authorizes_fixed_interpolation(tmp_path: Path, experimental: bool) -> None:
    source_path = tmp_path / "P001.bdf"
    source_path.touch()
    params = _params(source_path)
    prepared = prepare_kurtosis_review_evidence(
        _raw(),
        params,
        lambda _message: None,
        source_path.name,
    )
    evidence = prepared["evidence"]
    plan = prepared["decision_plan"]
    assert isinstance(evidence, dict) and isinstance(plan, dict)
    candidate = next(
        row["channel"]
        for row in plan["channel_decisions"]
        if row["state"] == "review_required"
    )
    params["_fpvs_kurtosis_review_decisions"] = {
        candidate: _approval(evidence, candidate, source_path)
    }

    if experimental:
        receipt = params["_fpvs_kurtosis_review_decisions"][candidate]
        receipt["reviewer_state"] = KURTOSIS_REVIEWER_STATE_EXPERIMENTAL_AUTO
        receipt["reason"] = "Experimental |z| > 10.0 rule enabled in the GUI."

    processed, rejected = perform_preprocessing(
        _raw(),
        params,
        lambda _message: None,
        source_path.name,
    )

    assert processed is not None
    assert rejected == 1
    assert params["_fpvs_kurtosis_user_approved_channels"] == ([] if experimental else [candidate])
    decision = next(row for row in params["_fpvs_kurtosis_decision_plan"]["channel_decisions"] if row["channel"] == candidate)
    assert decision["state"] == ("experimental_automatic" if experimental else "user_approved")
    assert decision["review_receipt"]["reviewer_state"] == (KURTOSIS_REVIEWER_STATE_EXPERIMENTAL_AUTO if experimental else KURTOSIS_REVIEWER_STATE_EXPLICIT_GUI)
    assert params["_fpvs_interpolated_channels"] == [candidate]


def test_unscoped_compatibility_call_cannot_auto_interpolate_kurtosis() -> None:
    params = _params(Path("unscoped.bdf"))
    params.pop("_fpvs_source_analysis_span_plan")
    params.pop("_fpvs_require_analysis_spans")

    processed, rejected = perform_preprocessing(
        _raw(),
        params,
        lambda _message: None,
        "unscoped.bdf",
    )

    assert processed is not None
    assert rejected == 0
    assert params["_fpvs_interpolated_channels"] == []
    assert params["_fpvs_kurtosis_qc_evidence"]["evaluation_status"] == (
        "not_evaluated"
    )


@pytest.mark.parametrize("single_session,auto_detector", [(False, False), (True, False), (True, True)])
@pytest.mark.parametrize("exclude_objects", [False, True])
@pytest.mark.parametrize("filtered", [False, True])
@pytest.mark.parametrize("changed_threshold", [False, True])
def test_scanner_receipts_match_actual_runner_preprocessing(
    tmp_path, monkeypatch, exclude_objects, filtered, changed_threshold, single_session, auto_detector,
) -> None:
    """Exercise both real span planners: metadata-only drift broke every file."""
    from Main_App.processing.kurtosis_review_scan import scan_kurtosis_review
    from Main_App.workers import process_runner

    path = (tmp_path / "P001.bdf").resolve()
    path.write_bytes(b"synthetic BDF loaded via RawArray")
    protocol = FrequencyProtocol.from_recurrence(
        20, 5, expected_analyzed_oddball_cycles=10,
        expected_analyzed_oddball_cycles_source=EXPECTED_CYCLES_SOURCE_MANUAL,
    )
    events = np.asarray([
        [1, 0, 1], *[[100 + index * 25, 0, 55] for index in range(11)],
        [500, 0, 2], *[[600 + index * 25, 0, 55] for index in range(11)],
    ], dtype=int)
    event_map = {"Faces": 1, "Objects": 2}
    event_plan = plan_preflight_qc_events(
        events=events, event_map=event_map, sfreq=100.0, n_times=1000,
        first_samp=0, frequency_protocol=protocol,
    ).to_payload()
    settings = {
        **_params(path),
        "frequency_protocol": protocol,
        "removed_electrode_detection_mode": "off",
        "auto_detect_removed_electrodes": False,
        "enable_preprocessed_cache": False,
        "_fpvs_preflight_event_plans_by_file": {str(path): event_plan},
        "_fpvs_participant_id_by_file": {str(path): "P001"},
        "_fpvs_recording_id_by_file": {str(path): "P001_session-1"},
        "_fpvs_session_id_by_file": {str(path): "session-1"},
        "_fpvs_session_label_by_file": {str(path): "Visit 1"},
        "manual_excluded_recording_conditions": (
            {"P001_session-1": ["Objects"]} if exclude_objects else {}
        ),
    }
    if filtered:
        settings.update(high_pass=1.0, low_pass=20.0, downsample_rate=50)
    def _load_synthetic(*_args, **_kwargs):
        raw = _raw()
        # Let MNE resample the real stim pulses; returning source-grid events
        # from a global find_events mock conceals target-grid timing mistakes.
        raw._data[-1, events[:, 0]] = events[:, 2]
        if auto_detector:
            raw._data[:-1] *= 20.0
            # A flat channel is independently authorized upstream in auto mode;
            # it must be omitted from BOTH kurtosis reference distributions.
            raw._data[raw.ch_names.index("AF7")] = 0.0
        return raw

    if auto_detector:
        settings.update(removed_electrode_detection_mode="auto", auto_detect_removed_electrodes=True)
    monkeypatch.setattr("Main_App.io.load_utils.load_eeg_file", _load_synthetic)
    monkeypatch.setattr(process_runner, "inspect_bdf_header", lambda _path: None)
    if single_session:
        for key in ("_fpvs_recording_id", "_fpvs_session_id", "_fpvs_session_label",
                    "_fpvs_recording_id_by_file", "_fpvs_session_id_by_file", "_fpvs_session_label_by_file"):
            settings.pop(key, None)
        settings["manual_excluded_recording_conditions"] = {}
        settings["manual_excluded_participant_conditions"] = {"P001": ["Objects"]} if exclude_objects else {}
    scan = scan_kurtosis_review(
        [SimpleNamespace(path=path, subject_id="P001", recording_id=None if single_session else "P001_session-1",
                         session_id=None if single_session else "session-1",
                         session_label=None if single_session else "Visit 1", visit_index=None if single_session else 1)],
        settings, event_map=event_map,
    )
    assert not scan.errors
    assert scan.review_items
    receipts = {
        item.channel: build_kurtosis_review_decision(
            item.evidence, channel=item.channel, decision=KURTOSIS_DECISION_APPROVE,
            reason="User auto mark", review_scope=item.review_scope,
        ).to_payload()
        for item in scan.review_items
    }
    settings["kurtosis_review_decisions_by_recording"] = {"P001" if single_session else "P001_session-1": receipts}
    if changed_threshold:
        settings["reject_thresh"] = 6.0

    captured = {}
    real_preprocess = perform_preprocessing

    def _run_to_preprocessed_boundary(raw_input, params, log_func, filename_for_log):
        processed, count = real_preprocess(raw_input, params, log_func, filename_for_log)
        captured.update(processed=processed, params=deepcopy(params), count=count)
        if processed is not None:
            # Export is outside this regression: the actual shared preprocessing
            # and receipt validation must finish before this sentinel is raised.
            raise RuntimeError("TEST reached completed preprocessing")
        return processed, count

    monkeypatch.setattr(process_runner.backend_preprocess, "perform_preprocessing", _run_to_preprocessed_boundary)
    result = process_runner._run_full_pipeline_for_file(
        file_path=path, settings=settings, event_map=event_map,
        save_folder=tmp_path / "out", project_root=tmp_path / "project",
    )
    assert result["stage"] == "preprocess"
    if changed_threshold:
        assert captured["processed"] is None
        assert "Kurtosis review evidence changed" in result["error"]
        assert captured["params"]["_fpvs_interpolated_channels"] == []
    else:
        assert result["error"] == "TEST reached completed preprocessing"
        assert captured["processed"] is not None
        assert captured["params"]["_fpvs_kurtosis_qc_evidence"] == scan.review_items[0].evidence
        assert set(captured["params"]["_fpvs_interpolated_channels"]) == (set(receipts) | ({"AF7"} if auto_detector else set()))
        assert "_fpvs_preprocessing_error" not in captured["params"]
