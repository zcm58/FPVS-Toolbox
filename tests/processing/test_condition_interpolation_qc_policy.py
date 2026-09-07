"""A review may request a repair, but may never remove an electrode or ROI."""

from __future__ import annotations

import pytest

from Main_App.processing import frequency_domain_qc as qc


def _report(*, enabled=False, roi=False, recording=False):
    return {
        "identity_scope": "recording" if recording else "participant",
        "screening_enabled": True,
        "condition_specific_interpolation_enabled": enabled,
        "analysis_fingerprint": "current-analysis",
        "review_findings": [{
            "finding_fingerprint": "finding-1",
            "participant_id": "P1", "recording_id": "P1_visit2" if recording else "",
            "condition": "Faces", "electrode": "" if roi else "O2",
            "roi": "Posterior" if roi else "",
        }],
    }


def _decision(action=qc.DECISION_INTERPOLATE_CONDITION_ELECTRODE, **kwargs):
    return {"finding-1": {"decision": action, **kwargs}}


@pytest.mark.parametrize("enabled", [False, None, "true", 1])
def test_repair_requires_explicit_enabled_capability(enabled):
    with pytest.raises(ValueError, match="Enable experimental"):
        qc.validate_frequency_domain_qc_review_decisions(
            _report(enabled=enabled), _decision(artifact_confirmed=True),
        )


@pytest.mark.parametrize("confirmed", [False, None, "yes", 1])
def test_repair_requires_artifact_confirmation(confirmed):
    with pytest.raises(ValueError, match="Confirm an electrode artifact"):
        qc.validate_frequency_domain_qc_review_decisions(
            _report(enabled=True), _decision(artifact_confirmed=confirmed),
        )


@pytest.mark.parametrize("recording", [False, True])
def test_repair_is_scoped_and_optional_reason_is_preserved(recording):
    rows = qc.validate_frequency_domain_qc_review_decisions(
        _report(enabled=True, recording=recording), _decision(artifact_confirmed=True),
    )
    row, = rows
    assert row["participant_id"] == "P1"
    assert row["recording_id"] == ("P1_VISIT2" if recording else "")
    assert row["condition"] == "Faces"
    assert row["electrode"] == "O2"
    assert row["artifact_confirmed"] is True
    assert row["reason"] == "No reason provided"
    assert row["outcome_informed"] is True
    exclusions = qc._frequency_domain_exclusions_from_rows(
        state={}, decisions=rows, manual_entries=[], manual_recording_entries=[],
    )
    assert not exclusions.excluded_electrodes_by_participant_condition
    assert not exclusions.excluded_electrodes_by_recording_condition
    assert not exclusions.excluded_participant_conditions
    assert not exclusions.excluded_recording_conditions


@pytest.mark.parametrize("action", [
    qc.DECISION_EXCLUDE_CONDITION_ELECTRODE, "exclude_condition_roi", "exclude_roi",
])
@pytest.mark.parametrize("enabled", [False, True])
def test_narrow_exclusions_are_not_accepted(action, enabled):
    with pytest.raises(ValueError, match="no longer supported"):
        qc.validate_frequency_domain_qc_review_decisions(
            _report(enabled=enabled), _decision(action),
        )


def test_roi_cannot_be_interpolated_as_a_group():
    with pytest.raises(ValueError, match="not an ROI"):
        qc.validate_frequency_domain_qc_review_decisions(
            _report(enabled=True, roi=True), _decision(artifact_confirmed=True),
        )


def test_repeated_session_repair_cannot_fall_back_to_participant():
    report = _report(enabled=True, recording=True)
    report["review_findings"][0]["recording_id"] = ""
    with pytest.raises(ValueError, match="exact recording ID"):
        qc.validate_frequency_domain_qc_review_decisions(
            report, _decision(artifact_confirmed=True),
        )


def test_two_findings_for_same_electrode_cannot_conflict():
    report = _report(enabled=True)
    report["review_findings"].append({
        **report["review_findings"][0], "finding_fingerprint": "prior-finding",
    })
    decisions = _decision(artifact_confirmed=True)
    decisions["prior-finding"] = {"decision": qc.DECISION_RETAIN}
    with pytest.raises(ValueError, match="Conflicting repair decisions"):
        qc.validate_frequency_domain_qc_review_decisions(report, decisions)


def test_legacy_electrode_exclusion_is_inactive_even_before_review():
    exclusions = qc._frequency_domain_exclusions_from_rows(
        state={}, decisions=[{
            "decision": qc.DECISION_EXCLUDE_CONDITION_ELECTRODE,
            "participant_id": "P1", "condition": "Faces", "electrode": "O2",
        }], manual_entries=[], manual_recording_entries=[],
    )
    assert not exclusions.excluded_electrodes_by_participant_condition


def test_roi_finding_can_still_exclude_the_whole_condition():
    rows = qc.validate_frequency_domain_qc_review_decisions(
        _report(roi=True), _decision(qc.DECISION_EXCLUDE_CONDITION),
    )
    exclusions = qc._frequency_domain_exclusions_from_rows(
        state={}, decisions=rows, manual_entries=[], manual_recording_entries=[],
    )
    assert exclusions.excluded_participant_conditions == {("P1", "Faces")}
    assert not exclusions.excluded_electrodes_by_participant_condition
