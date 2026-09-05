from __future__ import annotations

from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
import pytest

from Main_App.processing.marker_integrity import (
    MARKER_DECISION_EXCLUDE,
    MARKER_DECISION_RETAIN_FULL,
    MARKER_DECISION_USE_CONTIGUOUS,
    MARKER_REVIEW_DECISION_SCHEMA_VERSION,
    MARKER_REVIEWER_IDENTITY_STATUS_NOT_COLLECTED,
    MARKER_REVIEWER_STATE_EXPLICIT_GUI,
    MARKER_STATUS_READY,
    MARKER_STATUS_REVIEW_REQUIRED,
    ApprovedOccurrenceSpan,
    MarkerIntegrityError,
    MarkerIntegrityPlan,
    MarkerOccurrencePlan,
    MarkerReviewDecision,
    apply_marker_review_decision,
    approve_clean_occurrence,
    build_marker_integrity_plan,
    validate_approved_event_plan,
)
from Main_App.processing.preflight_qc_plan import plan_preflight_qc_events
from Main_App.projects import (
    EXPECTED_CYCLES_SOURCE_MANUAL,
    FrequencyProtocol,
)

pytestmark = pytest.mark.processing


def _protocol(*, cycles: int = 4, marker_code: int = 55) -> FrequencyProtocol:
    return FrequencyProtocol.from_recurrence(
        6,
        3,
        expected_analyzed_oddball_cycles=cycles,
        expected_analyzed_oddball_cycles_source=EXPECTED_CYCLES_SOURCE_MANUAL,
        oddball_marker_code=marker_code,
    )


def _events(marker_samples: list[int], marker_code: int = 55) -> np.ndarray:
    rows = [[0, 0, 1], *[[sample, 0, marker_code] for sample in marker_samples]]
    return np.asarray(rows, dtype=int)


def _plan(marker_samples: list[int], *, cycles: int = 4, marker_code: int = 55):
    return build_marker_integrity_plan(
        events=_events(marker_samples, marker_code=marker_code),
        event_map={"Faces": 1},
        sampling_rate_hz=12,
        n_times=60,
        protocol=_protocol(cycles=cycles, marker_code=marker_code),
    )


def _review_scope() -> dict[str, object]:
    return {
        "source_file_path": str(Path("P01.bdf").resolve()),
        "participant_id": "P01",
        "recording_id": "P01_visit-1",
        "session_id": "visit-1",
        "session_label": "Pre at visit 1",
    }


def _review_decision(
    plan: MarkerIntegrityPlan,
    occurrence: MarkerOccurrencePlan,
    decision: str,
    **kwargs: object,
) -> MarkerReviewDecision:
    return MarkerReviewDecision(
        decision=decision,
        schema_version=MARKER_REVIEW_DECISION_SCHEMA_VERSION,
        reason=str(kwargs.pop("reason", "Reviewed marker occurrence.")),
        reviewed_at_utc="2026-09-04T12:30:00Z",
        reviewer_state=MARKER_REVIEWER_STATE_EXPLICIT_GUI,
        reviewer_identity=None,
        reviewer_identity_status=MARKER_REVIEWER_IDENTITY_STATUS_NOT_COLLECTED,
        source_file_path=str(_review_scope()["source_file_path"]),
        participant_id="P01",
        recording_id="P01_visit-1",
        session_id="visit-1",
        session_label="Pre at visit 1",
        condition_label=occurrence.condition_label,
        condition_code=occurrence.condition_code,
        repetition_index=occurrence.repetition_index,
        occurrence_key=occurrence.occurrence_key,
        reviewed_marker_plan_fingerprint=plan.fingerprint,
        reviewed_occurrence_fingerprint=occurrence.fingerprint,
        **kwargs,
    )


def _apply_review(
    plan: MarkerIntegrityPlan,
    occurrence: MarkerOccurrencePlan,
    decision: MarkerReviewDecision,
) -> ApprovedOccurrenceSpan:
    return apply_marker_review_decision(
        occurrence,
        decision,
        marker_plan_fingerprint=plan.fingerprint,
        review_scope=_review_scope(),
    )


def test_clean_occurrence_uses_declared_cycle_count_and_exact_project_code() -> None:
    plan = _plan([10, 16, 22, 28, 34])
    occurrence = plan.occurrences[0]

    assert occurrence.status == MARKER_STATUS_READY
    assert occurrence.raw_marker_count == 5
    assert occurrence.retained_marker_count == 5
    assert occurrence.expected_analyzed_cycles == 4
    assert occurrence.expected_analyzed_samples == 24
    assert (occurrence.proposed_start_sample, occurrence.proposed_stop_sample) == (
        10,
        34,
    )
    approved = approve_clean_occurrence(occurrence)
    assert (approved.start_sample, approved.stop_sample) == (10, 34)
    assert not approved.is_excluded


def test_only_exact_same_sample_duplicates_are_collapsed_and_reported() -> None:
    plan = _plan([10, 10, 16, 22, 28, 34])
    occurrence = plan.occurrences[0]

    assert occurrence.status == MARKER_STATUS_READY
    assert occurrence.raw_marker_samples == (10, 10, 16, 22, 28, 34)
    assert occurrence.retained_marker_samples == (10, 16, 22, 28, 34)
    assert occurrence.collapsed_duplicate_count == 1
    assert occurrence.duplicate_groups[0].sample == 10
    assert occurrence.duplicate_groups[0].collapsed_count == 1


def test_nonsimultaneous_early_marker_is_preserved_and_requires_review() -> None:
    plan = _plan([10, 12, 16, 22, 28, 34])
    occurrence = plan.occurrences[0]

    assert occurrence.status == MARKER_STATUS_REVIEW_REQUIRED
    assert occurrence.retained_marker_samples == (10, 12, 16, 22, 28, 34)
    assert "early_or_extra_marker" in occurrence.review_reasons
    assert occurrence.intervals[0].early_or_extra_marker is True


def test_missing_marker_gap_requires_occurrence_local_review() -> None:
    plan = _plan([10, 16, 28, 34, 40])
    occurrence = plan.occurrences[0]

    assert plan.unresolved_occurrences == (occurrence,)
    assert "missing_marker_gap" in occurrence.review_reasons
    gap = next(item for item in occurrence.intervals if item.missing_marker_gap)
    assert gap.interval_cycles == 2
    assert gap.estimated_missing_markers == 1
    with pytest.raises(MarkerIntegrityError, match="GUI review"):
        approve_clean_occurrence(occurrence)


def test_half_and_one_and_a_half_cycle_boundaries_are_not_crossed() -> None:
    plan = _plan([10, 13, 22], cycles=1)
    occurrence = plan.occurrences[0]

    assert [item.interval_cycles for item in occurrence.intervals] == [0.5, 1.5]
    assert not any(item.early_or_extra_marker for item in occurrence.intervals)
    assert not any(item.missing_marker_gap for item in occurrence.intervals)


def test_condition_specific_code_is_never_guessed_from_observed_events() -> None:
    plan = build_marker_integrity_plan(
        events=_events([10, 16, 22, 28, 34], marker_code=51),
        event_map={"Faces": 1},
        sampling_rate_hz=12,
        n_times=60,
        protocol=_protocol(marker_code=55),
    )
    occurrence = plan.occurrences[0]

    assert occurrence.oddball_marker_code == 55
    assert occurrence.raw_marker_count == 0
    assert occurrence.review_reasons == (
        "insufficient_project_oddball_markers",
    )


def test_long_occurrence_is_capped_to_project_target() -> None:
    occurrence = _plan([10, 16, 22, 28, 34, 40, 46]).occurrences[0]

    assert occurrence.status == MARKER_STATUS_READY
    assert occurrence.available_span_samples == 36
    assert (occurrence.proposed_start_sample, occurrence.proposed_stop_sample) == (
        10,
        34,
    )


def test_short_occurrence_is_reviewed_and_never_padded() -> None:
    plan = _plan([10, 16, 22, 28])
    occurrence = plan.occurrences[0]

    assert "shorter_than_expected_analyzed_cycles" in occurrence.review_reasons
    assert occurrence.proposed_stop_sample is None
    with pytest.raises(MarkerIntegrityError, match="cannot be retained without padding"):
        _apply_review(
            plan,
            occurrence,
            _review_decision(
                plan,
                occurrence,
                MARKER_DECISION_RETAIN_FULL,
                evidence_type="presentation_log",
                evidence_reference="log.json",
            ),
        )


def test_retain_full_requires_external_evidence_for_gap() -> None:
    plan = _plan([10, 16, 28, 34, 40])
    occurrence = plan.occurrences[0]

    with pytest.raises(MarkerIntegrityError, match="evidence type"):
        _apply_review(
            plan,
            occurrence,
            _review_decision(
                plan,
                occurrence,
                MARKER_DECISION_RETAIN_FULL,
            ),
        )

    approved = _apply_review(
        plan,
        occurrence,
        _review_decision(
            plan,
            occurrence,
            MARKER_DECISION_RETAIN_FULL,
            evidence_type="photodiode",
            evidence_note="Continuous and phase-correct through the missing trigger.",
        ),
    )
    assert (approved.start_sample, approved.stop_sample) == (10, 34)


def test_verified_contiguous_span_must_match_declared_exact_length() -> None:
    plan = _plan([10, 12, 18, 24, 30, 36])
    occurrence = plan.occurrences[0]

    assert occurrence.contiguous_candidate_spans == ((12, 36),)

    with pytest.raises(MarkerIntegrityError, match="exactly"):
        _apply_review(
            plan,
            occurrence,
            _review_decision(
                plan,
                occurrence,
                MARKER_DECISION_USE_CONTIGUOUS,
                verified_start_sample=12,
                verified_stop_sample=35,
            ),
        )

    approved = _apply_review(
        plan,
        occurrence,
        _review_decision(
            plan,
            occurrence,
            MARKER_DECISION_USE_CONTIGUOUS,
            verified_start_sample=12,
            verified_stop_sample=36,
        ),
    )
    assert approved.disposition == MARKER_DECISION_USE_CONTIGUOUS


def test_exclusion_records_no_analysis_span() -> None:
    plan = _plan([10, 16])
    occurrence = plan.occurrences[0]
    approved = _apply_review(
        plan,
        occurrence,
        _review_decision(
            plan,
            occurrence,
            MARKER_DECISION_EXCLUDE,
            reason="Presentation stopped before the requested cycles completed.",
        ),
    )

    assert approved.is_excluded
    assert approved.start_sample is None
    assert approved.stop_sample is None


def test_manual_decision_requires_current_evidence_and_exact_scope() -> None:
    plan = _plan([10, 16])
    occurrence = plan.occurrences[0]
    decision = _review_decision(
        plan,
        occurrence,
        MARKER_DECISION_EXCLUDE,
        reason="Presentation stopped early.",
    )

    with pytest.raises(MarkerIntegrityError, match="different marker plan"):
        apply_marker_review_decision(
            occurrence,
            decision,
            marker_plan_fingerprint="c" * 64,
            review_scope=_review_scope(),
        )

    with pytest.raises(MarkerIntegrityError, match="different occurrence evidence"):
        _apply_review(
            plan,
            occurrence,
            replace(decision, reviewed_occurrence_fingerprint="c" * 64),
        )

    stale_scope = {**_review_scope(), "recording_id": "P01_visit-2"}
    with pytest.raises(MarkerIntegrityError, match="recording_id scope is stale"):
        apply_marker_review_decision(
            occurrence,
            decision,
            marker_plan_fingerprint=plan.fingerprint,
            review_scope=stale_scope,
        )


def test_manual_decision_allows_blank_reason_but_requires_time_and_reviewer_state() -> None:
    plan = _plan([10, 16])
    occurrence = plan.occurrences[0]
    decision = _review_decision(
        plan,
        occurrence,
        MARKER_DECISION_EXCLUDE,
        reason="Presentation stopped early.",
    )

    with pytest.raises(MarkerIntegrityError, match="schema is missing or stale"):
        _apply_review(plan, occurrence, replace(decision, schema_version=None))
    blank = _apply_review(plan, occurrence, replace(decision, reason=""))
    assert blank.decision_payload["reason"] == "No reason provided"
    assert blank.start_sample is None and blank.stop_sample is None
    explicit = _apply_review(plan, occurrence, replace(decision, reason="No reason provided"))
    assert explicit.fingerprint == blank.fingerprint
    with pytest.raises(MarkerIntegrityError, match="UTC timestamp"):
        _apply_review(
            plan,
            occurrence,
            replace(decision, reviewed_at_utc="2026-09-04T12:30:00-05:00"),
        )
    with pytest.raises(MarkerIntegrityError, match="cannot name a reviewer"):
        _apply_review(
            plan,
            occurrence,
            replace(decision, reviewer_identity="Invented User"),
        )


@pytest.mark.parametrize("blank_reason", [None, "", "  \t"])
def test_marker_comment_is_optional_without_relaxing_correction_evidence(blank_reason) -> None:
    plan = _plan([10, 16, 28, 34, 40])
    occurrence = plan.occurrences[0]
    decision = _review_decision(plan, occurrence, MARKER_DECISION_RETAIN_FULL)
    decision = replace(decision, reason=blank_reason)
    with pytest.raises(MarkerIntegrityError, match="evidence type"):
        _apply_review(plan, occurrence, decision)
    approved = _apply_review(plan, occurrence, replace(
        decision, evidence_type="presentation_log", evidence_reference="log.json#trial-4",
    ))
    assert approved.decision_payload["reason"] == "No reason provided"
    assert approved.decision_payload["evidence_reference"] == "log.json#trial-4"
    assert (approved.start_sample, approved.stop_sample) == (
        occurrence.proposed_start_sample, occurrence.proposed_stop_sample,
    )
    with pytest.raises(MarkerIntegrityError, match="explicit start and stop"):
        _apply_review(plan, occurrence, replace(decision, decision=MARKER_DECISION_USE_CONTIGUOUS))


def test_marker_plan_payload_carries_its_predecision_fingerprint() -> None:
    plan = _plan([10, 16])

    payload = plan.to_payload()

    assert payload["fingerprint"] == plan.fingerprint
    assert len(str(payload["fingerprint"])) == 64


def test_preflight_applies_only_a_receipt_bound_to_its_current_plan() -> None:
    protocol = _protocol()
    events = _events([10, 16, 28, 34, 40])
    marker_plan = build_marker_integrity_plan(
        events=events,
        event_map={"Faces": 1},
        sampling_rate_hz=12,
        n_times=60,
        protocol=protocol,
    )
    occurrence = marker_plan.occurrences[0]
    decision = _review_decision(
        marker_plan,
        occurrence,
        MARKER_DECISION_EXCLUDE,
        reason="Presentation timing could not be verified.",
    )

    event_plan = plan_preflight_qc_events(
        events=events,
        event_map={"Faces": 1},
        sfreq=12,
        n_times=60,
        frequency_protocol=protocol,
        marker_review_decisions={"1:0": asdict(decision)},
        marker_review_scope=_review_scope(),
    )

    assert event_plan.unresolved_occurrences == ()
    assert event_plan.approved_occurrences[0]["decision_payload"] == asdict(
        decision
    )
    validated = validate_approved_event_plan(
        event_plan_payload=event_plan.to_payload(),
        events=events,
        sampling_rate_hz=12,
        n_times=60,
        event_map={"Faces": 1},
        protocol=protocol,
    )
    assert validated[0].is_excluded

    changed_events = _events([10, 16, 29, 34, 40])
    with pytest.raises(MarkerIntegrityError, match="different marker plan"):
        plan_preflight_qc_events(
            events=changed_events,
            event_map={"Faces": 1},
            sfreq=12,
            n_times=60,
            frequency_protocol=protocol,
            marker_review_decisions={"1:0": asdict(decision)},
            marker_review_scope=_review_scope(),
        )


def test_plan_fingerprint_changes_with_raw_event_evidence() -> None:
    first = _plan([10, 16, 22, 28, 34])
    second = _plan([10, 16, 22, 29, 34])

    assert first.event_digest != second.event_digest
    assert first.fingerprint != second.fingerprint


def test_marker_code_must_be_distinct_from_condition_onset() -> None:
    protocol = _protocol(marker_code=1)

    with pytest.raises(MarkerIntegrityError, match="condition-onset"):
        build_marker_integrity_plan(
            events=_events([10, 16], marker_code=1),
            event_map={"Faces": 1},
            sampling_rate_hz=12,
            n_times=60,
            protocol=protocol,
        )


def test_runner_validation_accepts_only_current_fully_approved_preflight_plan() -> None:
    protocol = _protocol()
    events = _events([10, 16, 22, 28, 34])
    preflight_plan = plan_preflight_qc_events(
        events=events,
        event_map={"Faces": 1},
        sfreq=12.0,
        n_times=60,
        frequency_protocol=protocol,
    )

    approved = validate_approved_event_plan(
        event_plan_payload=preflight_plan.to_payload(),
        events=events,
        sampling_rate_hz=12,
        n_times=60,
        event_map={"Faces": 1},
        protocol=protocol,
    )

    assert len(approved) == 1
    assert (approved[0].start_sample, approved[0].stop_sample) == (10, 34)


def test_runner_validation_rejects_changed_event_stream() -> None:
    protocol = _protocol()
    original_events = _events([10, 16, 22, 28, 34])
    preflight_plan = plan_preflight_qc_events(
        events=original_events,
        event_map={"Faces": 1},
        sfreq=12.0,
        n_times=60,
        frequency_protocol=protocol,
    )

    with pytest.raises(MarkerIntegrityError, match="digest is stale"):
        validate_approved_event_plan(
            event_plan_payload=preflight_plan.to_payload(),
            events=_events([10, 16, 22, 29, 34]),
            sampling_rate_hz=12,
            n_times=60,
            event_map={"Faces": 1},
            protocol=protocol,
        )
