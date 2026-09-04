from __future__ import annotations

import json
from pathlib import Path

import pytest

from Main_App.processing.frequency_domain_qc import (
    FREQUENCY_DOMAIN_QC_REPORT_NAME,
    QUALITY_CHECK_FOLDER,
    WARNING_REASON_UNUSUAL_VALUES,
    apply_frequency_domain_qc_decision,
    clear_manual_frequency_domain_recording_exclusions,
)
from Main_App.processing.frequency_qc_identity import (
    FREQUENCY_QC_REVIEW_IDENTITY_VERSION,
    IDENTITY_SCOPE_PARTICIPANT,
    IDENTITY_SCOPE_RECORDING,
    FrequencyQcReviewIdentityError,
    frequency_qc_review_rows,
    resolve_frequency_qc_recording_decisions,
)


def test_recording_review_rows_join_canonical_assignment_identity() -> None:
    report = _recording_report()

    rows = frequency_qc_review_rows(report)

    assert rows == (
        {
            "recording_id": "P1__Visit_A",
            "participant_id": "P1",
            "pause_review": True,
            "review_identity_version": FREQUENCY_QC_REVIEW_IDENTITY_VERSION,
            "identity_scope": IDENTITY_SCOPE_RECORDING,
            "decision_key": "P1__Visit_A",
            "session_id": "visit_a",
            "session_label": "Follow-up",
            "visit_index": 2,
            "group_id": "treated",
            "source_id": "treated_visit_a",
            "days_from_baseline": 14.0,
        },
    )


def test_recording_decision_resolves_case_insensitively_to_exact_canonical_id() -> None:
    decisions = resolve_frequency_qc_recording_decisions(
        _recording_report(),
        {"p1__visit_a": WARNING_REASON_UNUSUAL_VALUES},
    )

    assert len(decisions) == 1
    assert decisions[0].identity.recording_id == "P1__Visit_A"
    assert decisions[0].identity.participant_id == "P1"
    assert decisions[0].identity.session_id == "visit_a"


def test_recordings_with_same_session_label_keep_distinct_decision_keys() -> None:
    report = _recording_report()
    report["recording_summaries"] = [
        *report["recording_summaries"],
        {
            "recording_id": "P1__Visit_B",
            "participant_id": "P1",
            "pause_review": True,
        },
    ]

    rows = frequency_qc_review_rows(report)

    assert [row["decision_key"] for row in rows] == [
        "P1__Visit_A",
        "P1__Visit_B",
    ]
    assert [row["session_label"] for row in rows] == ["Follow-up", "Follow-up"]


def test_participant_review_identity_remains_separate_from_recording_identity() -> None:
    rows = frequency_qc_review_rows(
        {
            "subjects": ["Participant_A"],
            "participant_summaries": [{"participant_id": "participant_a", "pause_review": True}],
        }
    )

    assert rows[0]["identity_scope"] == IDENTITY_SCOPE_PARTICIPANT
    assert rows[0]["decision_key"] == "Participant_A"
    assert rows[0]["participant_id"] == "Participant_A"
    assert rows[0]["recording_id"] is None

    with pytest.raises(FrequencyQcReviewIdentityError, match="recording-scoped"):
        resolve_frequency_qc_recording_decisions(
            {"subjects": ["Participant_A"]},
            {"Participant_A": WARNING_REASON_UNUSUAL_VALUES},
        )


def test_unknown_or_ambiguous_recording_decisions_are_rejected() -> None:
    with pytest.raises(FrequencyQcReviewIdentityError, match="unknown or stale"):
        resolve_frequency_qc_recording_decisions(
            _recording_report(),
            {"P1__Visit_OLD": WARNING_REASON_UNUSUAL_VALUES},
        )

    with pytest.raises(FrequencyQcReviewIdentityError, match="more than once"):
        resolve_frequency_qc_recording_decisions(
            _recording_report(),
            {
                "P1__Visit_A": WARNING_REASON_UNUSUAL_VALUES,
                "p1__visit_a": WARNING_REASON_UNUSUAL_VALUES,
            },
        )


def test_duplicate_casefolded_assignments_are_rejected() -> None:
    report = _recording_report()
    report["recording_assignments"] = [
        *report["recording_assignments"],
        {
            "recording_id": "p1__visit_a",
            "participant_id": "P1",
            "session_id": "visit_a",
        },
    ]

    with pytest.raises(FrequencyQcReviewIdentityError, match="duplicated"):
        frequency_qc_review_rows(report)


def test_apply_rejects_stale_recording_before_any_write(tmp_path: Path) -> None:
    project_root = tmp_path / "Project"
    project_root.mkdir()
    manifest_path = project_root / "project.json"
    original = {"name": "Identity Test"}
    manifest_path.write_text(json.dumps(original, indent=2), encoding="utf-8")

    with pytest.raises(FrequencyQcReviewIdentityError, match="unknown or stale"):
        apply_frequency_domain_qc_decision(
            project_root,
            _recording_report(),
            manual_recording_reasons={"P1__Visit_OLD": WARNING_REASON_UNUSUAL_VALUES},
        )

    assert json.loads(manifest_path.read_text(encoding="utf-8")) == original
    assert not (project_root / QUALITY_CHECK_FOLDER / FREQUENCY_DOMAIN_QC_REPORT_NAME).exists()


def test_apply_persists_exact_canonical_recording_assignment(tmp_path: Path) -> None:
    project_root = tmp_path / "Project"
    project_root.mkdir()
    manifest_path = project_root / "project.json"
    manifest_path.write_text(json.dumps({"name": "Identity Test"}), encoding="utf-8")

    state = apply_frequency_domain_qc_decision(
        project_root,
        _recording_report(),
        manual_recording_reasons={
            "p1__visit_a": WARNING_REASON_UNUSUAL_VALUES,
        },
    )

    assert state["manual_recording_exclusions"][0]["recording_id"] == "P1__Visit_A"
    assert state["manual_recording_exclusions"][0]["participant_id"] == "P1"
    assert state["manual_recording_exclusions"][0]["session_id"] == "visit_a"
    saved = json.loads(manifest_path.read_text(encoding="utf-8"))
    saved_entry = saved["tools"]["frequency_domain_qc"]["manual_recording_exclusions"][0]
    assert saved_entry["recording_id"] == "P1__Visit_A"

    reopened_state = apply_frequency_domain_qc_decision(project_root, _recording_report())
    assert reopened_state["manual_recording_exclusions"][0]["recording_id"] == ("P1__Visit_A")

    assert clear_manual_frequency_domain_recording_exclusions(
        project_root,
        ["p1__visit_a"],
    ) == ["P1__Visit_A"]


def _recording_report() -> dict[str, object]:
    return {
        "identity_scope": "recording",
        "analysis_fingerprint": "analysis-v1",
        "recordings": ["P1__Visit_A", "P1__Visit_B"],
        "recording_assignments": [
            {
                "recording_id": "P1__Visit_A",
                "participant_id": "P1",
                "group_id": "treated",
                "session_id": "visit_a",
                "session_label": "Follow-up",
                "source_id": "treated_visit_a",
                "visit_index": 2,
                "days_from_baseline": 14.0,
            },
            {
                "recording_id": "P1__Visit_B",
                "participant_id": "P1",
                "group_id": "treated",
                "session_id": "visit_b",
                "session_label": "Follow-up",
                "source_id": "treated_visit_b",
                "visit_index": 3,
                "days_from_baseline": 28.0,
            },
        ],
        "recording_summaries": [
            {
                "recording_id": "p1__visit_a",
                "participant_id": "wrong-summary-value",
                "pause_review": True,
            }
        ],
        "participant_summaries": [],
        "auto_participant_electrode_exclusions": [],
        "auto_participant_exclusions": [],
        "auto_recording_electrode_exclusions": [],
        "auto_recording_exclusions": [],
        "selected_harmonics_hz": [],
    }
