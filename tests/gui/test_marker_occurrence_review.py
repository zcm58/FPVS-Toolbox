from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace

import pytest

from Main_App.gui.marker_occurrence_review import (
    MARKER_DECISION_EXCLUDE,
    MARKER_DECISION_RETAIN_FULL,
    MARKER_DECISION_USE_CONTIGUOUS,
    MarkerOccurrenceReviewError,
    build_marker_review_decision,
    canonical_event_plans_by_file,
    collect_marker_occurrence_reviews,
    marker_occurrence_review_rows,
    marker_occurrence_review_summary,
    merge_marker_review_decision,
    merge_rescanned_results,
    resolved_path_text,
)
from Main_App.processing.marker_integrity import (
    MARKER_INTEGRITY_METHOD_VERSION,
    MARKER_REVIEW_DECISION_SCHEMA_VERSION,
    MARKER_REVIEWER_IDENTITY_STATUS_NOT_COLLECTED,
    MARKER_REVIEWER_STATE_EXPLICIT_GUI,
)


REVIEWED_AT_UTC = "2026-09-04T12:30:00Z"
MARKER_PLAN_FINGERPRINT = "a" * 64
OCCURRENCE_FINGERPRINT = "b" * 64


def _occurrence_payload() -> dict[str, object]:
    return {
        "condition_label": "Faces",
        "condition_code": 1,
        "repetition_index": 0,
        "onset_sample": 10,
        "block_stop_sample": 50,
        "oddball_marker_code": 55,
        "raw_marker_samples": [10, 10, 12, 18, 30, 36],
        "retained_marker_samples": [10, 12, 18, 30, 36],
        "duplicate_groups": [
            {"sample": 10, "raw_count": 2, "collapsed_count": 1}
        ],
        "intervals": [
            {
                "start_sample": 10,
                "stop_sample": 12,
                "interval_samples": 2,
                "interval_seconds": "1/6",
                "interval_cycles": "1/3",
                "phase_residual_cycles": "1/3",
                "early_or_extra_marker": True,
                "missing_marker_gap": False,
                "estimated_missing_markers": 0,
            },
            {
                "start_sample": 18,
                "stop_sample": 30,
                "interval_samples": 12,
                "interval_seconds": "1",
                "interval_cycles": "2",
                "phase_residual_cycles": "0",
                "early_or_extra_marker": False,
                "missing_marker_gap": True,
                "estimated_missing_markers": 1,
            },
        ],
        "expected_interval_samples": "6",
        "expected_analyzed_cycles": 4,
        "expected_analyzed_samples": 24,
        "available_span_samples": 40,
        "proposed_start_sample": 10,
        "proposed_stop_sample": 34,
        "contiguous_candidate_spans": [[12, 36]],
        "status": "review_required",
        "review_reasons": ["early_or_extra_marker", "missing_marker_gap"],
        "fingerprint": OCCURRENCE_FINGERPRINT,
    }


def _event_plan(*, unresolved: bool = True) -> dict[str, object]:
    occurrence = _occurrence_payload()
    return {
        "sfreq": 12.0,
        "first_samp": 0,
        "n_times": 60,
        "event_count": 8,
        "event_digest": "event-digest",
        "n_step": 24,
        "spans": [],
        "warnings": [],
        "marker_integrity_plan": {
            "method_version": MARKER_INTEGRITY_METHOD_VERSION,
            "sampling_rate_hz": "12",
            "first_samp": 0,
            "fingerprint": MARKER_PLAN_FINGERPRINT,
            "occurrences": [occurrence],
        },
        "approved_occurrences": [],
        "unresolved_occurrences": [occurrence] if unresolved else [],
    }


def _result(path: Path, *, unresolved: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        path=path,
        participant_id="P01",
        recording_id="P01_visit-1",
        session_id="visit-1",
        session_label="Pre at visit 1",
        condition_qc={"event_plan": _event_plan(unresolved=unresolved)},
    )


def test_occurrence_adapter_exposes_complete_review_evidence(tmp_path: Path) -> None:
    result = _result(tmp_path / "P01.bdf")
    scan = SimpleNamespace(results=(result,))

    (item,) = collect_marker_occurrence_reviews(scan)

    assert item.occurrence_key == "1:0"
    assert item.marker_plan_fingerprint == MARKER_PLAN_FINGERPRINT
    assert item.occurrence_fingerprint == OCCURRENCE_FINGERPRINT
    assert item.sampling_rate_hz == 12
    assert item.first_samp == 0
    assert item.oddball_rate_hz == Fraction(2)
    assert item.raw_marker_samples == (10, 10, 12, 18, 30, 36)
    assert item.retained_marker_samples == (10, 12, 18, 30, 36)
    assert item.exact_duplicate_count == 1
    assert item.missing_gap_count == 1
    assert item.estimated_missing_markers == 1
    assert item.early_or_extra_count == 1
    assert item.maximum_phase_residual_cycles == Fraction(1, 3)
    assert item.contiguous_candidate_spans == ((12, 36),)

    rows = dict(marker_occurrence_review_rows(item))
    assert rows["Participant"] == "P01"
    assert rows["Recording"] == "P01_visit-1"
    assert "Faces (code 1), repetition 1 (index 0)" == rows[
        "Condition occurrence"
    ]
    assert rows["Oddball marker code"] == "55"
    assert rows["Expected analysis"] == "4 oddball cycles at 2 Hz"
    assert rows["Marker counts"] == "6 raw; 5 retained"
    assert rows["Exact same-sample duplicates collapsed"] == "1"
    assert "1 gap(s)" in rows["Gaps and early/extra markers"]
    assert rows["Maximum phase residual"] == "0.333333 oddball cycles"
    assert rows["Proposed full crop"].startswith("[10, 34) samples")
    assert "0.833333 to 2.83333 s" in rows["Proposed full crop"]
    assert rows["Verified contiguous candidates"].startswith("[12, 36) samples")
    assert rows["Raw marker samples"] == "10, 10, 12, 18, 30, 36"
    assert rows["Raw marker times from recording start"].startswith(
        "0.833333 s, 0.833333 s, 1 s"
    )
    assert "samples 18-30" in rows["Flagged interval evidence"]
    assert "1.5 to 2.5 seconds from recording start" in rows[
        "Flagged interval evidence"
    ]
    assert "1 seconds" in rows["Flagged interval evidence"]


def test_review_times_are_relative_to_the_raw_sample_origin(tmp_path: Path) -> None:
    result = _result(tmp_path / "P01.bdf")
    result.condition_qc["event_plan"]["first_samp"] = 10
    result.condition_qc["event_plan"]["marker_integrity_plan"]["first_samp"] = 10

    item = collect_marker_occurrence_reviews(
        SimpleNamespace(results=(result,))
    )[0]
    rows = dict(marker_occurrence_review_rows(item))

    assert item.first_samp == 10
    assert rows["Raw marker times from recording start"].startswith("0 s, 0 s")
    assert "0.666667 to 1.66667 seconds from recording start" in rows[
        "Flagged interval evidence"
    ]


def _review_item(tmp_path: Path):
    return collect_marker_occurrence_reviews(
        SimpleNamespace(results=(_result(tmp_path / "P01.bdf"),))
    )[0]


def test_summary_keeps_identity_required_duration_and_scientific_action_keys(tmp_path: Path) -> None:
    item = replace(
        _review_item(tmp_path), expected_analyzed_cycles=140,
        oddball_rate_hz=Fraction(7, 6), repetition_index=2,
    )
    summary = marker_occurrence_review_summary(item)

    assert summary.context == "P01 · Pre at visit 1 · Faces · Repetition 3"
    assert summary.source == "P01.bdf · P01_visit-1"
    assert summary.required_analysis == "Each retained window must contain 140 oddball cycles (120 seconds)."
    assert tuple(choice.decision for choice in summary.choices) == (
        MARKER_DECISION_USE_CONTIGUOUS, MARKER_DECISION_RETAIN_FULL, MARKER_DECISION_EXCLUDE,
    )
    assert all(choice.enabled for choice in summary.choices)
    verified, planned, excluded = summary.choices
    assert "120 seconds" in verified.description
    assert "marker-spacing check" in verified.description
    assert "120-second window" in planned.description
    assert "independent evidence" in planned.description
    assert "Other repetitions remain eligible" in excluded.description
    assert "raw file is kept" in excluded.description


@pytest.mark.parametrize("session_label, session_id, expected", [
    ("Luteal", "visit-1", "P01 · Luteal · Faces · Repetition 1"),
    (None, "visit-1", "P01 · visit-1 · Faces · Repetition 1"),
    (None, None, "P01 · Faces · Repetition 1"),
])
def test_summary_uses_session_identity_without_exposing_empty_fields(
    tmp_path: Path, session_label: str | None, session_id: str | None, expected: str,
) -> None:
    item = replace(_review_item(tmp_path), session_label=session_label, session_id=session_id)
    assert marker_occurrence_review_summary(item).context == expected
    legacy = replace(item, participant_id="", recording_id=None)
    summary = marker_occurrence_review_summary(legacy)
    assert summary.context.startswith("Unknown participant · ")
    assert summary.source == "P01.bdf"


@pytest.mark.parametrize("reason, gaps, missing, early, expected", [
    ("insufficient_project_oddball_markers", 0, 0, 0,
     "Fewer than two distinct markers with the project's code 55 were found."),
    ("shorter_than_expected_analyzed_cycles", 0, 0, 0,
     "The markers cover less than the required 2 seconds of data."),
    ("missing_marker_gap", 2, 3, 0,
     "Long marker gaps: 2; about 3 markers may be missing."),
    ("early_or_extra_marker", 0, 0, 4,
     "4 marker intervals were unusually short."),
    ("future_marker_finding", 0, 0, 0,
     "The marker timing needs review before this repetition can be analyzed."),
])
def test_summary_explains_actual_finding_without_claiming_stimulation_stopped(
    tmp_path: Path, reason: str, gaps: int, missing: int, early: int, expected: str,
) -> None:
    item = replace(
        _review_item(tmp_path), review_reasons=(reason,), missing_gap_count=gaps,
        estimated_missing_markers=missing, early_or_extra_count=early,
    )
    summary = marker_occurrence_review_summary(item)
    assert summary.finding == (
        expected + " Markers alone cannot tell whether the visual stimulation was interrupted."
    )
    assert reason not in summary.finding


@pytest.mark.parametrize("start, stop, expected_enabled", [
    (None, None, False), (10, None, False), (None, 34, False), (0, 24, True),
])
@pytest.mark.parametrize("has_candidates", [False, True])
def test_summary_disables_only_unavailable_retention_actions(
    tmp_path: Path, start: int | None, stop: int | None,
    expected_enabled: bool, has_candidates: bool,
) -> None:
    item = replace(
        _review_item(tmp_path), proposed_start_sample=start, proposed_stop_sample=stop,
        contiguous_candidate_spans=((12, 36),) if has_candidates else (),
    )
    choices = {choice.decision: choice for choice in marker_occurrence_review_summary(item).choices}
    assert choices[MARKER_DECISION_USE_CONTIGUOUS].enabled is has_candidates
    assert choices[MARKER_DECISION_RETAIN_FULL].enabled is expected_enabled
    assert choices[MARKER_DECISION_EXCLUDE].enabled is True
    for decision, enabled in (
        (MARKER_DECISION_USE_CONTIGUOUS, has_candidates),
        (MARKER_DECISION_RETAIN_FULL, expected_enabled),
    ):
        assert choices[decision].description.startswith("Unavailable:") is not enabled
    if not has_candidates:
        with pytest.raises(MarkerOccurrenceReviewError, match="not supplied"):
            build_marker_review_decision(item, MARKER_DECISION_USE_CONTIGUOUS, selected_span=(12, 36))
    if not expected_enabled:
        with pytest.raises(MarkerOccurrenceReviewError, match="too short"):
            build_marker_review_decision(
                item, MARKER_DECISION_RETAIN_FULL,
                evidence_type="presentation_log", evidence_note="Reviewed presentation timing.",
            )
    assert build_marker_review_decision(item, MARKER_DECISION_EXCLUDE)["decision"] == MARKER_DECISION_EXCLUDE


def test_summary_stays_compact_with_large_diagnostic_evidence(tmp_path: Path) -> None:
    item = _review_item(tmp_path)
    baseline = marker_occurrence_review_summary(item)
    expanded = replace(
        item, interval_evidence=tuple(f"diagnostic-interval-{i}: " + "x" * 1000 for i in range(1000)),
        raw_marker_samples=tuple(range(10000)), retained_marker_samples=tuple(range(10000)),
    )
    assert marker_occurrence_review_summary(expanded) == baseline
    many_candidates = replace(expanded, contiguous_candidate_spans=tuple((i, i + 24) for i in range(10000)))
    summary = marker_occurrence_review_summary(many_candidates)
    assert "10000 windows" in summary.choices[0].description
    assert len(summary.finding) + sum(len(choice.description) for choice in summary.choices) < 1000
    assert "diagnostic-interval" not in repr(summary)
    assert expanded.interval_evidence[-1].startswith("diagnostic-interval-999:")


def test_summary_leaves_detailed_evidence_and_decision_receipts_unchanged(tmp_path: Path) -> None:
    item = _review_item(tmp_path)
    original_item = deepcopy(item)
    original_rows = marker_occurrence_review_rows(item)
    decision_inputs = (
        (MARKER_DECISION_USE_CONTIGUOUS, {"selected_span": (12, 36)}),
        (MARKER_DECISION_RETAIN_FULL, {"evidence_type": "photodiode_trace", "evidence_reference": "trace.csv"}),
        (MARKER_DECISION_EXCLUDE, {"reason": "Presentation stopped."}),
    )
    before = tuple(build_marker_review_decision(item, decision, reviewed_at_utc=REVIEWED_AT_UTC, **values)
                   for decision, values in decision_inputs)

    marker_occurrence_review_summary(item)

    assert item == original_item
    assert marker_occurrence_review_rows(item) == original_rows
    assert dict(original_rows)["Raw marker samples"] == "10, 10, 12, 18, 30, 36"
    assert "samples 18-30" in dict(original_rows)["Flagged interval evidence"]
    assert tuple(build_marker_review_decision(item, decision, reviewed_at_utc=REVIEWED_AT_UTC, **values)
                 for decision, values in decision_inputs) == before


def test_retain_full_requires_evidence_type_and_note_or_reference(
    tmp_path: Path,
) -> None:
    item = collect_marker_occurrence_reviews(
        SimpleNamespace(results=(_result(tmp_path / "P01.bdf"),))
    )[0]

    with pytest.raises(MarkerOccurrenceReviewError, match="evidence type"):
        build_marker_review_decision(item, MARKER_DECISION_RETAIN_FULL)

    decision = build_marker_review_decision(
        item,
        MARKER_DECISION_RETAIN_FULL,
        evidence_type="presentation_log",
        evidence_reference="presentation_log.json#trial-4",
        reviewed_at_utc=REVIEWED_AT_UTC,
    )

    assert decision["schema_version"] == MARKER_REVIEW_DECISION_SCHEMA_VERSION
    assert decision["decision"] == MARKER_DECISION_RETAIN_FULL
    assert decision["reason"] == "No reason provided"
    assert decision["reviewed_at_utc"] == REVIEWED_AT_UTC
    assert decision["reviewer_state"] == MARKER_REVIEWER_STATE_EXPLICIT_GUI
    assert decision["reviewer_identity"] is None
    assert (
        decision["reviewer_identity_status"]
        == MARKER_REVIEWER_IDENTITY_STATUS_NOT_COLLECTED
    )
    assert decision["source_file_path"] == resolved_path_text(item.path)
    assert decision["participant_id"] == "P01"
    assert decision["recording_id"] == "P01_visit-1"
    assert decision["session_id"] == "visit-1"
    assert decision["condition_label"] == "Faces"
    assert decision["condition_code"] == 1
    assert decision["repetition_index"] == 0
    assert decision["occurrence_key"] == "1:0"
    assert decision["reviewed_marker_plan_fingerprint"] == MARKER_PLAN_FINGERPRINT
    assert decision["reviewed_occurrence_fingerprint"] == OCCURRENCE_FINGERPRINT
    assert decision["evidence_type"] == "presentation_log"
    assert decision["evidence_note"] is None
    assert decision["evidence_reference"] == "presentation_log.json#trial-4"


def test_contiguous_decision_accepts_only_a_supplied_candidate(tmp_path: Path) -> None:
    item = collect_marker_occurrence_reviews(
        SimpleNamespace(results=(_result(tmp_path / "P01.bdf"),))
    )[0]

    with pytest.raises(MarkerOccurrenceReviewError, match="was not supplied"):
        build_marker_review_decision(
            item,
            MARKER_DECISION_USE_CONTIGUOUS,
            selected_span=(10, 34),
        )

    decision = build_marker_review_decision(
        item,
        MARKER_DECISION_USE_CONTIGUOUS,
        selected_span=(12, 36),
        reviewed_at_utc=REVIEWED_AT_UTC,
    )
    assert decision["decision"] == MARKER_DECISION_USE_CONTIGUOUS
    assert decision["verified_start_sample"] == 12
    assert decision["verified_stop_sample"] == 36
    assert decision["reviewed_marker_plan_fingerprint"] == MARKER_PLAN_FINGERPRINT

    assert decision["reason"] == "No reason provided"
    blank_exclusion = build_marker_review_decision(item, MARKER_DECISION_EXCLUDE)
    assert blank_exclusion["reason"] == "No reason provided"
    exclusion = build_marker_review_decision(
        item,
        MARKER_DECISION_EXCLUDE,
        reason="Presentation stopped before the expected cycles completed.",
        reviewed_at_utc=REVIEWED_AT_UTC,
    )
    assert exclusion["decision"] == MARKER_DECISION_EXCLUDE
    assert exclusion["reason"] == (
        "Presentation stopped before the expected cycles completed."
    )


def test_decisions_use_resolved_file_and_occurrence_keys(tmp_path: Path) -> None:
    source = tmp_path / "subfolder" / "P01.bdf"
    existing = {
        str(source).swapcase(): {
            "1:0": {"decision": MARKER_DECISION_EXCLUDE},
        }
    }

    merged = merge_marker_review_decision(
        existing,
        file_path=source,
        occurrence_key="2:1",
        decision={"decision": MARKER_DECISION_USE_CONTIGUOUS},
    )

    assert list(merged) == [resolved_path_text(source)]
    assert set(merged[resolved_path_text(source)]) == {"1:0", "2:1"}


def test_rescan_replaces_only_affected_results_in_original_order(tmp_path: Path) -> None:
    first = _result(tmp_path / "P01.bdf")
    second = _result(tmp_path / "P02.bdf")
    replacement = _result(tmp_path / "P02.bdf", unresolved=False)

    merged = merge_rescanned_results(
        (first, second),
        (replacement,),
        affected_paths=(second.path,),
    )

    assert merged == (first, replacement)

    with pytest.raises(MarkerOccurrenceReviewError, match="every affected file"):
        merge_rescanned_results(
            (first, second),
            (),
            affected_paths=(second.path,),
        )


def test_event_plan_handoff_is_complete_resolved_and_fails_closed(
    tmp_path: Path,
) -> None:
    path = tmp_path / "P01.bdf"
    clean = _result(path, unresolved=False)

    plans = canonical_event_plans_by_file(SimpleNamespace(results=(clean,)))

    assert list(plans) == [resolved_path_text(path)]
    assert plans[resolved_path_text(path)] == clean.condition_qc["event_plan"]

    unresolved = _result(path, unresolved=True)
    with pytest.raises(MarkerOccurrenceReviewError, match="still unresolved"):
        canonical_event_plans_by_file(SimpleNamespace(results=(unresolved,)))

    missing = SimpleNamespace(path=path, condition_qc=None)
    with pytest.raises(MarkerOccurrenceReviewError, match="No canonical"):
        canonical_event_plans_by_file(SimpleNamespace(results=(missing,)))
