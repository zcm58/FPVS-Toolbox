from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib
import json

import numpy as np
import pytest

from Main_App.io.eeg_geometry import BIOSEMI64_CHANNELS, biosemi64_geometry_identity
from Main_App.processing.analysis_spans import (
    ANALYSIS_SPAN_COORDINATE_VERSION,
    ANALYSIS_SPAN_PLAN_VERSION,
    TARGET_SPAN_ROUNDING_VERSION,
)
from Main_App.processing.kurtosis_qc import (
    CHANNEL_DECISION_CORROBORATED_AUTO,
    CHANNEL_DECISION_EXPERIMENTAL_AUTO,
    CHANNEL_DECISION_DIRECT,
    CHANNEL_DECISION_EVALUATION_UNAVAILABLE,
    CHANNEL_DECISION_REVIEW_REQUIRED,
    CHANNEL_DECISION_USER_APPROVED,
    CHANNEL_DECISION_USER_REJECTED,
    CHANNEL_VALIDITY_NONFINITE_INPUT,
    CHANNEL_VALIDITY_REFERENCE_UNAVAILABLE,
    CHANNEL_VALIDITY_UNDEFINED_STATISTIC,
    CORROBORATOR_AUTHORITY_ELIGIBLE,
    CORROBORATOR_AUTHORITY_REVIEW_ONLY,
    CORROBORATOR_SCOPE_RECORDING_UNION,
    CURRENT_KURTOSIS_CORROBORATOR_REGISTRY,
    ELIGIBLE_KURTOSIS_CORROBORATORS,
    EVIDENCE_STATUS_PARTIAL,
    EVIDENCE_STATUS_UNAVAILABLE,
    EVIDENCE_STATUS_VALID,
    KURTOSIS_CORROBORATOR_REGISTRY_VERSION,
    KURTOSIS_DECISION_APPROVE,
    KURTOSIS_DECISION_REJECT,
    KURTOSIS_QC_METHOD_VERSION,
    KURTOSIS_REVIEW_DECISION_SCHEMA_VERSION,
    KURTOSIS_REVIEWER_IDENTITY_STATUS_NOT_COLLECTED,
    KURTOSIS_REVIEWER_STATE_EXPLICIT_GUI,
    KURTOSIS_REVIEWER_STATE_EXPERIMENTAL_AUTO,
    KurtosisCorroboratorFinding,
    KurtosisCorroboratorMethod,
    KurtosisCorroboratorRegistry,
    KurtosisQCError,
    build_kurtosis_decision_plan,
    build_kurtosis_review_decision,
    evaluate_kurtosis_qc,
    legacy_kurtosis_audit_payload,
    normalize_kurtosis_review_decisions_by_recording,
    qualifies_for_experimental_kurtosis_auto,
    validate_kurtosis_review_decision_payload,
)


def _fingerprint(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _realized_plan(n_samples: int, *, occurrence_count: int = 2) -> dict[str, object]:
    boundaries = np.linspace(0, n_samples, occurrence_count + 1, dtype=int)
    spans: list[dict[str, object]] = []
    for index in range(occurrence_count):
        start = int(boundaries[index])
        stop = int(boundaries[index + 1])
        span: dict[str, object] = {
            "condition_label": f"Condition {index + 1}",
            "condition_code": index + 1,
            "repetition_index": 0,
            "occurrence_key": f"{index + 1}:0",
            "marker_plan_fingerprint": "1" * 64,
            "approved_span_fingerprint": "2" * 64,
            "marker_disposition": "automatic_clean",
            "source_span_fingerprint": f"{index + 3:x}" * 64,
            "source_coordinates": {
                "first_samp": 100,
                "start_sample": 100 + start,
                "stop_sample": 100 + stop,
                "start_relative_sample": start,
                "stop_relative_sample": stop,
            },
            "target_coordinates": {
                "first_samp": 20,
                "start_sample": 20 + start,
                "stop_sample": 20 + stop,
                "start_relative_sample": start,
                "stop_relative_sample": stop,
            },
        }
        span["fingerprint"] = _fingerprint(span)
        spans.append(span)
    plan: dict[str, object] = {
        "version": ANALYSIS_SPAN_PLAN_VERSION,
        "coordinate_version": ANALYSIS_SPAN_COORDINATE_VERSION,
        "rounding_version": TARGET_SPAN_ROUNDING_VERSION,
        "source_plan_fingerprint": "a" * 64,
        "event_plan_fingerprint": "b" * 64,
        "protocol_fingerprint": "c" * 64,
        "target_grid": {
            "sfreq_hz": 256.0,
            "n_times": n_samples,
            "first_samp": 20,
            "sample_origin": "raw.first_samp",
        },
        "spans": spans,
        "unique_relative_spans": [[0, n_samples]],
        "unique_sample_count": n_samples,
    }
    plan["fingerprint"] = _fingerprint(plan)
    return plan


def _data(
    channel_count: int = 20,
    sample_count: int = 2_000,
    *,
    outlier: bool = True,
) -> np.ndarray:
    rng = np.random.default_rng(908)
    data = rng.normal(size=(channel_count, sample_count))
    if outlier:
        data[0] = rng.normal(scale=0.05, size=sample_count)
        data[0, ::200] = 30.0
    return data


def _evidence(
    *,
    data: np.ndarray | None = None,
    channel_names: tuple[str, ...] | None = None,
    geometry_channels: tuple[str, ...] | None = None,
    registry: KurtosisCorroboratorRegistry = CURRENT_KURTOSIS_CORROBORATOR_REGISTRY,
):
    array = _data() if data is None else data
    names = (
        tuple(BIOSEMI64_CHANNELS[: array.shape[0]])
        if channel_names is None
        else channel_names
    )
    retained = names if geometry_channels is None else geometry_channels
    return evaluate_kurtosis_qc(
        array,
        names,
        threshold=5.0,
        realized_analysis_span_plan=_realized_plan(array.shape[1]),
        filter_identity={
            "method_version": "mne_fir_zero_double_hamming_firwin_v1",
            "high_pass_hz": 0.1,
            "low_pass_hz": 50.0,
        },
        downsample_identity={
            "method_version": "mne_resample_hann_v1",
            "target_hz": 256.0,
            "realized_hz": 256.0,
        },
        geometry_identity=biosemi64_geometry_identity(retained_channels=retained),
        registry=registry,
    )


def _receipt(evidence, channel: str, path, *, decision=KURTOSIS_DECISION_APPROVE):
    channel_evidence = evidence.channel(channel)
    assert channel_evidence is not None
    return {
        "schema_version": KURTOSIS_REVIEW_DECISION_SCHEMA_VERSION,
        "decision": decision,
        "reason": "Reviewed the analyzed signal and channel evidence.",
        "reviewed_at_utc": "2026-09-04T18:22:00Z",
        "reviewer_state": KURTOSIS_REVIEWER_STATE_EXPLICIT_GUI,
        "reviewer_identity": None,
        "reviewer_identity_status": KURTOSIS_REVIEWER_IDENTITY_STATUS_NOT_COLLECTED,
        "source_file_path": str(path),
        "participant_id": "P001",
        "recording_id": "P001_session-1",
        "session_id": "session-1",
        "session_label": "Visit 1",
        "channel": channel,
        "reviewed_method_version": evidence.method_version,
        "reviewed_registry_version": evidence.corroborator_registry_version,
        "reviewed_evidence_fingerprint": evidence.fingerprint,
        "reviewed_channel_evidence_fingerprint": channel_evidence.fingerprint,
        "reviewed_analysis_span_fingerprint": (
            evidence.scoring_scope.analysis_span_fingerprint
        ),
        "reviewed_occurrence_keys": list(evidence.scoring_scope.occurrence_keys),
    }


def _scope(path) -> dict[str, object]:
    return {
        "source_file_path": str(path),
        "participant_id": "P001",
        "recording_id": "P001_session-1",
        "session_id": "session-1",
        "session_label": "Visit 1",
    }


def _future_registry() -> KurtosisCorroboratorRegistry:
    return KurtosisCorroboratorRegistry(
        version="test_future_registry_v2",
        methods=(
            KurtosisCorroboratorMethod(
                method_id="independent_channel_health",
                method_version="jointly_calibrated_v1",
                approval_reference="test-only future approval",
            ),
        ),
    )


def _finding(evidence, channel: str, **overrides) -> KurtosisCorroboratorFinding:
    values = {
        "method_id": "independent_channel_health",
        "method_version": "jointly_calibrated_v1",
        "channel": channel,
        "scope": CORROBORATOR_SCOPE_RECORDING_UNION,
        "analysis_span_fingerprint": evidence.scoring_scope.analysis_span_fingerprint,
        "occurrence_keys": evidence.scoring_scope.occurrence_keys,
        "authority": CORROBORATOR_AUTHORITY_ELIGIBLE,
        "evidence_fingerprint": "d" * 64,
        "valid": True,
    }
    values.update(overrides)
    return KurtosisCorroboratorFinding(**values)


def test_current_registry_is_versioned_and_empty() -> None:
    assert KURTOSIS_QC_METHOD_VERSION == "eeglab_inspired_trimmed_kurtosis_v1"
    assert KURTOSIS_CORROBORATOR_REGISTRY_VERSION.endswith("_empty")
    assert CURRENT_KURTOSIS_CORROBORATOR_REGISTRY.methods == ()
    assert ELIGIBLE_KURTOSIS_CORROBORATORS == ()


def test_evidence_preserves_signed_statistics_reference_and_scope() -> None:
    evidence = _evidence()

    assert evidence.status == EVIDENCE_STATUS_VALID
    assert evidence.candidate_channels == (BIOSEMI64_CHANNELS[0],)
    candidate = evidence.channel(BIOSEMI64_CHANNELS[0])
    assert candidate is not None
    assert candidate.raw_kurtosis is not None
    assert candidate.signed_z is not None and candidate.signed_z > 5.0
    assert candidate.threshold == 5.0
    assert evidence.reference_distribution.finite_channel_count == 20
    assert evidence.reference_distribution.trim_count_per_tail == 2
    assert len(evidence.reference_distribution.included_raw_kurtosis) == 16
    assert evidence.scoring_scope.unique_sample_count == 2_000
    assert evidence.scoring_scope.occurrence_keys == ("1:0", "2:0")
    assert len(evidence.fingerprint) == 64
    assert evidence.to_payload()["fingerprint"] == evidence.fingerprint


@pytest.mark.parametrize("threshold", [0, -1, float("nan"), float("inf"), True, "bad"])
def test_threshold_must_be_positive_and_finite(threshold) -> None:
    data = _data()
    channels = BIOSEMI64_CHANNELS[:20]
    with pytest.raises(KurtosisQCError, match="positive finite"):
        evaluate_kurtosis_qc(
            data,
            channels,
            threshold=threshold,
            realized_analysis_span_plan=_realized_plan(data.shape[1]),
            filter_identity={"method_version": "filter_v1"},
            downsample_identity={"method_version": "resample_v1"},
            geometry_identity=biosemi64_geometry_identity(retained_channels=channels),
        )


def test_nonfinite_input_is_not_converted_to_zero_or_candidate() -> None:
    data = _data(outlier=False)
    data[0, 10] = np.nan
    evidence = _evidence(data=data)
    row = evidence.channel(BIOSEMI64_CHANNELS[0])

    assert evidence.status == EVIDENCE_STATUS_PARTIAL
    assert row is not None
    assert row.validity == CHANNEL_VALIDITY_NONFINITE_INPUT
    assert row.raw_kurtosis is None
    assert row.signed_z is None
    assert not row.exceeds_threshold


def test_constant_channel_retains_undefined_state() -> None:
    data = _data(outlier=False)
    data[0] = 0.0
    evidence = _evidence(data=data)
    row = evidence.channel(BIOSEMI64_CHANNELS[0])

    assert evidence.status == EVIDENCE_STATUS_PARTIAL
    assert row is not None
    assert row.validity == CHANNEL_VALIDITY_UNDEFINED_STATISTIC
    assert row.raw_kurtosis is None
    assert row.signed_z is None


def test_small_or_degenerate_reference_is_unavailable() -> None:
    small = _data(channel_count=15, outlier=False)
    insufficient = _evidence(data=small)
    assert insufficient.status == EVIDENCE_STATUS_UNAVAILABLE
    assert not insufficient.candidate_channels
    assert all(
        item.validity == CHANNEL_VALIDITY_REFERENCE_UNAVAILABLE
        for item in insufficient.channels
    )

    repeated = np.tile(_data(channel_count=1, outlier=False), (20, 1))
    degenerate = _evidence(data=repeated)
    assert degenerate.status == EVIDENCE_STATUS_UNAVAILABLE
    assert "degenerate scale" in str(degenerate.unavailable_reason)


def test_empty_registry_keeps_kurtosis_candidate_pending_even_with_other_flag() -> None:
    evidence = _evidence()
    candidate = evidence.candidate_channels[0]
    unapproved = _finding(evidence, candidate)

    plan = build_kurtosis_decision_plan(
        evidence,
        corroborator_findings=(unapproved,),
    )

    row = next(item for item in plan.channel_decisions if item.channel == candidate)
    assert row.state == CHANNEL_DECISION_REVIEW_REQUIRED
    assert not row.interpolation_authorized
    assert row.corroborator_assessments[0].reason == "method_not_registered"
    assert plan.pending_review_channels == (candidate,)
    assert not plan.ready_for_interpolation


@pytest.mark.parametrize(
    ("finding_overrides", "expected_reason"),
    [
        (
            {"occurrence_keys": ("1:0",)},
            "occurrence_scope_does_not_match",
        ),
        (
            {"analysis_span_fingerprint": "e" * 64},
            "analysis_spans_do_not_match",
        ),
        (
            {"authority": CORROBORATOR_AUTHORITY_REVIEW_ONLY},
            "finding_is_review_only",
        ),
    ],
)
def test_future_corroborator_requires_same_full_scope_and_authority(
    finding_overrides,
    expected_reason,
) -> None:
    registry = _future_registry()
    evidence = _evidence(registry=registry)
    candidate = evidence.candidate_channels[0]
    finding = _finding(evidence, candidate, **finding_overrides)

    plan = build_kurtosis_decision_plan(
        evidence,
        corroborator_findings=(finding,),
        registry=registry,
    )

    row = next(item for item in plan.channel_decisions if item.channel == candidate)
    assert row.state == CHANNEL_DECISION_REVIEW_REQUIRED
    assert row.corroborator_assessments[0].reason == expected_reason


def test_future_eligible_same_channel_same_scope_can_authorize_automatic() -> None:
    registry = _future_registry()
    evidence = _evidence(registry=registry)
    candidate = evidence.candidate_channels[0]

    plan = build_kurtosis_decision_plan(
        evidence,
        corroborator_findings=(_finding(evidence, candidate),),
        registry=registry,
    )

    row = next(item for item in plan.channel_decisions if item.channel == candidate)
    assert row.state == CHANNEL_DECISION_CORROBORATED_AUTO
    assert row.interpolation_authorized
    assert plan.corroborated_automatic_channels == (candidate,)
    assert plan.ready_for_interpolation


def test_different_channel_finding_does_not_corroborate_candidate() -> None:
    registry = _future_registry()
    evidence = _evidence(registry=registry)
    candidate = evidence.candidate_channels[0]
    other_channel = BIOSEMI64_CHANNELS[1]

    plan = build_kurtosis_decision_plan(
        evidence,
        corroborator_findings=(_finding(evidence, other_channel),),
        registry=registry,
    )

    candidate_row = next(
        item for item in plan.channel_decisions if item.channel == candidate
    )
    other_row = next(
        item for item in plan.channel_decisions if item.channel == other_channel
    )
    assert candidate_row.state == CHANNEL_DECISION_REVIEW_REQUIRED
    assert other_row.corroborator_assessments[0].eligible
    assert not other_row.interpolation_authorized


@pytest.mark.parametrize(
    ("decision", "expected_state", "authorized"),
    [
        (KURTOSIS_DECISION_APPROVE, CHANNEL_DECISION_USER_APPROVED, True),
        (KURTOSIS_DECISION_REJECT, CHANNEL_DECISION_USER_REJECTED, False),
    ],
)
def test_current_gui_receipt_approves_or_rejects_candidate(
    tmp_path,
    decision,
    expected_state,
    authorized,
) -> None:
    evidence = _evidence()
    candidate = evidence.candidate_channels[0]
    source_path = tmp_path / "recording.bdf"
    source_path.touch()

    plan = build_kurtosis_decision_plan(
        evidence,
        review_decisions={
            candidate: _receipt(evidence, candidate, source_path, decision=decision)
        },
        review_scope=_scope(source_path),
    )

    row = next(item for item in plan.channel_decisions if item.channel == candidate)
    assert row.state == expected_state
    assert row.interpolation_authorized is authorized
    assert plan.ready_for_interpolation


def test_gui_receipt_builder_binds_cached_evidence_and_scope(tmp_path) -> None:
    evidence = _evidence()
    candidate = evidence.candidate_channels[0]
    source_path = tmp_path / "recording.bdf"
    source_path.touch()

    receipt = build_kurtosis_review_decision(
        evidence.to_payload(),
        channel=candidate,
        decision=KURTOSIS_DECISION_APPROVE,
        reason="Reviewed the filtered analyzed signal.",
        review_scope=_scope(source_path),
        reviewed_at_utc="2026-09-04T18:22:00Z",
    )
    plan = build_kurtosis_decision_plan(
        evidence,
        review_decisions={candidate: receipt},
        review_scope=_scope(source_path),
    )

    assert plan.user_approved_channels == (candidate,)
    assert receipt.reviewed_evidence_fingerprint == evidence.fingerprint
    assert receipt.reviewer_identity_status == (
        KURTOSIS_REVIEWER_IDENTITY_STATUS_NOT_COLLECTED
    )

    validated = validate_kurtosis_review_decision_payload(
        receipt,
        evidence=evidence.to_payload(),
        channel=candidate,
        review_scope=_scope(source_path),
    )
    assert validated == receipt


def test_serialized_receipt_validation_rejects_changed_evidence(tmp_path) -> None:
    evidence = _evidence()
    candidate = evidence.candidate_channels[0]
    source_path = tmp_path / "recording.bdf"
    source_path.touch()
    receipt = _receipt(evidence, candidate, source_path)
    changed = evidence.to_payload()
    changed["threshold"] = float(changed["threshold"]) + 1.0

    with pytest.raises(KurtosisQCError, match="fingerprint"):
        validate_kurtosis_review_decision_payload(
            receipt,
            evidence=changed,
            channel=candidate,
            review_scope=_scope(source_path),
        )


def test_gui_receipt_builder_rejects_tampered_or_clear_evidence(tmp_path) -> None:
    evidence = _evidence()
    candidate = evidence.candidate_channels[0]
    source_path = tmp_path / "recording.bdf"
    source_path.touch()
    tampered = evidence.to_payload()
    tampered["threshold"] = 99.0

    with pytest.raises(KurtosisQCError, match="fingerprint"):
        build_kurtosis_review_decision(
            tampered,
            channel=candidate,
            decision=KURTOSIS_DECISION_APPROVE,
            reason="Reviewed.",
            review_scope=_scope(source_path),
        )


def test_persisted_receipts_normalize_by_recording_and_channel(tmp_path) -> None:
    evidence = _evidence()
    candidate = evidence.candidate_channels[0]
    source_path = tmp_path / "recording.bdf"
    source_path.touch()
    receipt = build_kurtosis_review_decision(
        evidence.to_payload(),
        channel=candidate,
        decision=KURTOSIS_DECISION_APPROVE,
        reason="Reviewed.",
        review_scope=_scope(source_path),
        reviewed_at_utc="2026-09-04T18:22:00Z",
    )

    normalized = normalize_kurtosis_review_decisions_by_recording(
        {"p001_SESSION-1": {candidate: receipt.to_payload()}}
    )

    assert list(normalized) == ["P001_session-1"]
    assert normalized["P001_session-1"][candidate] == receipt.to_payload()

    wrong_key = receipt.to_payload()
    wrong_key["channel"] = BIOSEMI64_CHANNELS[1]
    with pytest.raises(KurtosisQCError, match="channel key"):
        normalize_kurtosis_review_decisions_by_recording(
            {"P001_session-1": {candidate: wrong_key}}
        )

    clear = next(
        item.channel for item in evidence.channels if not item.exceeds_threshold
    )
    with pytest.raises(KurtosisQCError, match="not required"):
        build_kurtosis_review_decision(
            evidence.to_payload(),
            channel=clear,
            decision=KURTOSIS_DECISION_APPROVE,
            reason="Reviewed.",
            review_scope=_scope(source_path),
        )


def test_stale_or_non_gui_receipt_is_rejected(tmp_path) -> None:
    evidence = _evidence()
    candidate = evidence.candidate_channels[0]
    source_path = tmp_path / "recording.bdf"
    source_path.touch()
    receipt = _receipt(evidence, candidate, source_path)
    receipt["reviewed_evidence_fingerprint"] = "f" * 64

    with pytest.raises(KurtosisQCError, match="evidence changed"):
        build_kurtosis_decision_plan(
            evidence,
            review_decisions={candidate: receipt},
            review_scope=_scope(source_path),
        )

    receipt = _receipt(evidence, candidate, source_path)
    receipt["reviewer_state"] = "dialog_closed"
    with pytest.raises(KurtosisQCError, match="explicit GUI"):
        build_kurtosis_decision_plan(
            evidence,
            review_decisions={candidate: receipt},
            review_scope=_scope(source_path),
        )


def test_nonfinite_channel_requires_review_and_unavailable_evidence_blocks(tmp_path) -> None:
    data = _data(outlier=False)
    data[0, 0] = np.inf
    evidence = _evidence(data=data)
    source_path = tmp_path / "recording.bdf"
    source_path.touch()

    pending = build_kurtosis_decision_plan(evidence)
    row = next(
        item for item in pending.channel_decisions if item.channel == BIOSEMI64_CHANNELS[0]
    )
    assert row.state == CHANNEL_DECISION_REVIEW_REQUIRED

    small = _evidence(data=_data(channel_count=15, outlier=False))
    unavailable = build_kurtosis_decision_plan(small)
    assert not unavailable.ready_for_interpolation
    assert unavailable.blocking_reasons == ("kurtosis_evidence_unavailable",)
    assert all(
        item.state == CHANNEL_DECISION_EVALUATION_UNAVAILABLE
        for item in unavailable.channel_decisions
    )


def test_confirmed_manual_channel_has_direct_authority_without_kurtosis_row() -> None:
    retained = tuple(BIOSEMI64_CHANNELS[:20])
    missing_manual = retained[0]
    evaluated = retained[1:]
    evidence = _evidence(
        data=_data(channel_count=len(evaluated)),
        channel_names=evaluated,
        geometry_channels=retained,
    )

    plan = build_kurtosis_decision_plan(
        evidence,
        direct_bad_channels={missing_manual: "User confirmed a disconnected electrode."},
    )

    row = next(item for item in plan.channel_decisions if item.channel == missing_manual)
    assert row.state == CHANNEL_DECISION_DIRECT
    assert row.interpolation_authorized
    assert missing_manual in plan.authorized_interpolation_channels


def test_scope_and_geometry_changes_invalidate_evidence() -> None:
    data = _data()
    channels = tuple(BIOSEMI64_CHANNELS[:20])
    stale_plan = _realized_plan(data.shape[1])
    stale_plan["unique_sample_count"] = data.shape[1] - 1
    with pytest.raises(KurtosisQCError, match="fingerprint"):
        evaluate_kurtosis_qc(
            data,
            channels,
            threshold=5.0,
            realized_analysis_span_plan=stale_plan,
            filter_identity={"method_version": "filter_v1"},
            downsample_identity={"method_version": "resample_v1"},
            geometry_identity=biosemi64_geometry_identity(retained_channels=channels),
        )

    stale_geometry = deepcopy(biosemi64_geometry_identity(retained_channels=channels))
    stale_geometry["coordinate_fingerprint"] = "sha256:wrong"
    with pytest.raises(KurtosisQCError, match="coordinate_fingerprint"):
        evaluate_kurtosis_qc(
            data,
            channels,
            threshold=5.0,
            realized_analysis_span_plan=_realized_plan(data.shape[1]),
            filter_identity={"method_version": "filter_v1"},
            downsample_identity={"method_version": "resample_v1"},
            geometry_identity=stale_geometry,
        )


def test_legacy_automatic_result_remains_stale_audit_only() -> None:
    payload = legacy_kurtosis_audit_payload(["Cz", "P8"])

    assert payload["method_version"] == "legacy_fpvs_kurtosis_auto_v0"
    assert payload["evidence_status"] == "legacy_unknown"
    assert payload["review_status"] == "not_recorded"
    assert payload["reuse_status"] == "stale_requires_reprocessing"
    assert len(str(payload["fingerprint"])) == 64


@pytest.mark.parametrize("score", [5.01, -5.01, 9.999, -9.999, 10.0, -10.0, 10.001, -10.001])
def test_experimental_cutoff_uses_strict_absolute_normalized_score(score, tmp_path) -> None:
    original = _evidence()
    channel = replace(original.channels[0], signed_z=score, absolute_z=abs(score), raw_kurtosis=1000.0)
    evidence = replace(original, channels=(channel, *original.channels[1:]))
    qualifies = abs(score) > 10.0
    assert qualifies_for_experimental_kurtosis_auto(channel.to_payload()) is qualifies
    # High raw kurtosis alone still has no automatic authority.
    assert build_kurtosis_decision_plan(evidence).pending_review_channels == (channel.channel,)
    kwargs = dict(
        channel=channel.channel,
        decision=KURTOSIS_DECISION_APPROVE,
        reason="Experimental automatic |z| > 10.0 rule enabled in the GUI.",
        review_scope=_scope(tmp_path / "P001.bdf"),
        experimental_auto=True,
    )
    if not qualifies:
        with pytest.raises(KurtosisQCError, match="experimental"):
            build_kurtosis_review_decision(evidence.to_payload(), **kwargs)
        return
    receipt = build_kurtosis_review_decision(evidence.to_payload(), **kwargs)
    assert receipt.reviewer_state == KURTOSIS_REVIEWER_STATE_EXPERIMENTAL_AUTO
    normalized = normalize_kurtosis_review_decisions_by_recording({receipt.recording_id: {channel.channel: receipt.to_payload()}})
    persisted = normalized[receipt.recording_id][channel.channel]
    assert validate_kurtosis_review_decision_payload(
        persisted, evidence=evidence.to_payload(), channel=channel.channel, review_scope=kwargs["review_scope"],
    ) == receipt
    plan = build_kurtosis_decision_plan(
        evidence, review_decisions={channel.channel: persisted}, review_scope=kwargs["review_scope"],
    )
    assert plan.ready_for_interpolation
    assert plan.authorized_interpolation_channels == (channel.channel,)
    assert plan.channel_decisions[0].state == CHANNEL_DECISION_EXPERIMENTAL_AUTO
    assert plan.user_approved_channels == ()
    assert plan.corroborated_automatic_channels == ()
    assert plan.channel_decisions[0].review_receipt == receipt


@pytest.mark.parametrize("overrides", [
    {"signed_z": None}, {"signed_z": float("nan")}, {"signed_z": float("inf")},
    {"signed_z": -float("inf")}, {"validity": CHANNEL_VALIDITY_UNDEFINED_STATISTIC},
    {"exceeds_threshold": False},
])
def test_experimental_auto_does_not_authorize_invalid_or_unflagged_evidence(overrides) -> None:
    row = {"signed_z": 20.0, "validity": "valid", "exceeds_threshold": True, **overrides}
    assert not qualifies_for_experimental_kurtosis_auto(row)


def test_experimental_receipt_cannot_bypass_rule_by_changing_reviewer_state(tmp_path) -> None:
    original = _evidence()
    channel = replace(original.channels[0], signed_z=8.0, absolute_z=8.0)
    evidence = replace(original, channels=(channel, *original.channels[1:]))
    scope = _scope(tmp_path / "P001.bdf")
    receipt = build_kurtosis_review_decision(
        evidence.to_payload(), channel=channel.channel, decision=KURTOSIS_DECISION_APPROVE,
        reason="Manually inspected", review_scope=scope,
    ).to_payload()
    receipt["reviewer_state"] = KURTOSIS_REVIEWER_STATE_EXPERIMENTAL_AUTO
    with pytest.raises(KurtosisQCError, match="experimental"):
        validate_kurtosis_review_decision_payload(receipt, evidence=evidence.to_payload(), channel=channel.channel, review_scope=scope)
    with pytest.raises(KurtosisQCError, match="experimental"):
        build_kurtosis_decision_plan(evidence, review_decisions={channel.channel: receipt}, review_scope=scope)
