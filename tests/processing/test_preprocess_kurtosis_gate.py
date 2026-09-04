from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import mne
import numpy as np

from Main_App.io.eeg_geometry import (
    BIOSEMI64_CHANNELS,
    attach_raw_biosemi64_geometry,
    cached_biosemi64_montage,
)
from Main_App.processing.analysis_spans import read_source_analysis_span_plan
from Main_App.processing.kurtosis_qc import (
    KURTOSIS_DECISION_APPROVE,
    KURTOSIS_REVIEW_DECISION_SCHEMA_VERSION,
    KURTOSIS_REVIEWER_IDENTITY_STATUS_NOT_COLLECTED,
    KURTOSIS_REVIEWER_STATE_EXPLICIT_GUI,
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


def test_current_gui_approval_authorizes_fixed_interpolation(tmp_path: Path) -> None:
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

    processed, rejected = perform_preprocessing(
        _raw(),
        params,
        lambda _message: None,
        source_path.name,
    )

    assert processed is not None
    assert rejected == 1
    assert params["_fpvs_kurtosis_user_approved_channels"] == [candidate]
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
