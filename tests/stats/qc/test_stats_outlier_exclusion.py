import numpy as np
import pandas as pd

from Tools.Stats.qc.stats_outlier_exclusion import (
    OUTLIER_REASON_LIMIT,
    OUTLIER_REASON_NONFINITE,
    OutlierExclusionReport,
    OutlierExclusionSummary,
    OutlierParticipantReport,
    apply_hard_dv_exclusion,
    build_flagged_participants_tables,
    build_outlier_summary_text,
    merge_exclusion_reports,
)
from Tools.Stats.qc.stats_qc_exclusion import (
    QcExclusionReport,
    QcExclusionSummary,
    QcParticipantReport,
    QcViolation,
)


def test_apply_hard_dv_exclusion_filters_participants() -> None:
    df = pd.DataFrame(
        [
            {"subject": "P1", "condition": "A", "roi": "R1", "value": 51.0},
            {"subject": "P2", "condition": "A", "roi": "R1", "value": 49.0},
            {"subject": "P3", "condition": "A", "roi": "R1", "value": np.nan},
        ]
    )

    filtered, report = apply_hard_dv_exclusion(df, 50.0)

    assert set(filtered["subject"].unique()) == {"P1", "P2"}
    assert report.summary.n_subjects_before == 3
    assert report.summary.n_subjects_excluded == 1
    assert report.summary.n_subjects_after == 2

    reasons_by_pid = {item.participant_id: set(item.reasons) for item in report.participants}
    assert reasons_by_pid["P1"] == {OUTLIER_REASON_LIMIT}
    assert reasons_by_pid["P3"] == {OUTLIER_REASON_NONFINITE}


def test_outlier_summary_clarifies_flag_vs_exclusion() -> None:
    summary = OutlierExclusionSummary(
        n_subjects_before=2,
        n_subjects_excluded=1,
        n_subjects_after=1,
        abs_limit=50.0,
        n_subjects_flagged=1,
        n_subjects_required_excluded=1,
    )
    participants = [
        OutlierParticipantReport(
            participant_id="P1",
            reasons=[OUTLIER_REASON_LIMIT],
            n_violations=1,
            max_abs_dv=55.0,
            worst_value=55.0,
            worst_condition="CondA",
            worst_roi="ROI1",
            worst_metric=OUTLIER_REASON_LIMIT,
        )
    ]
    report = OutlierExclusionReport(summary=summary, participants=participants)

    text = build_outlier_summary_text(report)

    assert "Flagged for review does not automatically exclude participants." in text
    assert "Only non-finite DV values (NaN/Inf) are automatically excluded." in text


def test_merge_preserves_shared_qc17_audit_identity() -> None:
    dv_report = OutlierExclusionReport(
        summary=OutlierExclusionSummary(
            n_subjects_before=2,
            n_subjects_excluded=0,
            n_subjects_after=2,
            abs_limit=50.0,
        ),
        participants=[],
    )
    qc_report = QcExclusionReport(
        summary=QcExclusionSummary(
            n_subjects_before=2,
            n_subjects_flagged=0,
            n_subjects_after=2,
            warn_threshold=6.0,
            critical_threshold=10.0,
            warn_abs_floor_sumabs=5.0,
            critical_abs_floor_sumabs=10.0,
            warn_abs_floor_maxabs=1.0,
            critical_abs_floor_maxabs=2.0,
        ),
        participants=[],
        screened_conditions=["Faces"],
        screened_rois=["Right OT"],
        source="shared_project_qc17_review",
        source_fingerprint="source-fingerprint",
        decision_fingerprint="decision-fingerprint",
        evidence_fingerprint="evidence-fingerprint",
        harmonic_selection_fingerprint="harmonic-fingerprint",
        review_complete=True,
        screening_status="performed",
        authority="review_only",
    )

    merged = merge_exclusion_reports(dv_report, qc_report)

    assert merged.qc_metadata == {
        "source": "shared_project_qc17_review",
        "source_fingerprint": "source-fingerprint",
        "decision_fingerprint": "decision-fingerprint",
        "evidence_fingerprint": "evidence-fingerprint",
        "harmonic_selection_fingerprint": "harmonic-fingerprint",
        "review_complete": True,
        "screening_status": "performed",
        "authority": "review_only",
        "screened_conditions": ["Faces"],
        "screened_rois": ["Right OT"],
        "warn_threshold": 6.0,
        "critical_threshold": 10.0,
        "warn_abs_floor_sumabs": 5.0,
        "critical_abs_floor_sumabs": 10.0,
        "warn_abs_floor_maxabs": 1.0,
        "critical_abs_floor_maxabs": 2.0,
    }


def test_flagged_tables_export_exact_shared_qc17_audit_fields() -> None:
    violation = QcViolation(
        condition="Faces",
        roi="Right OT",
        metric="QC_SUMABS",
        severity="EXTREME",
        value=12.0,
        robust_center=2.0,
        robust_spread=1.0,
        robust_score=10.0,
        threshold_used=10.0,
        abs_floor_used=10.0,
        recording_id="P1__V1",
        participant_id="P1",
        decision="retain",
        decision_reason="",
        evidence_fingerprint="finding-fingerprint",
        source="shared_project_qc17_review",
        shared_decision_fingerprint="decision-fingerprint",
        shared_source_fingerprint="source-fingerprint",
        shared_evidence_fingerprint="evidence-fingerprint",
        harmonic_selection_fingerprint="harmonic-fingerprint",
        authority="review_only",
    )
    participant = QcParticipantReport(
        participant_id="P1__V1",
        reasons=[violation.metric],
        n_violations=1,
        worst_value=violation.value,
        worst_condition=violation.condition,
        worst_roi=violation.roi,
        worst_metric=violation.metric,
        robust_center=violation.robust_center,
        robust_spread=violation.robust_spread,
        robust_score=violation.robust_score,
        threshold_used=violation.threshold_used,
        trigger_harmonic_hz=None,
        roi_mean_bca_at_trigger=None,
        violations=[violation],
    )
    qc_report = QcExclusionReport(
        summary=QcExclusionSummary(
            n_subjects_before=1,
            n_subjects_flagged=1,
            n_subjects_after=1,
            warn_threshold=6.0,
            critical_threshold=10.0,
            warn_abs_floor_sumabs=5.0,
            critical_abs_floor_sumabs=10.0,
            warn_abs_floor_maxabs=1.0,
            critical_abs_floor_maxabs=2.0,
        ),
        participants=[participant],
        screened_conditions=["Faces"],
        screened_rois=["Right OT"],
        source="shared_project_qc17_review",
        source_fingerprint="source-fingerprint",
        decision_fingerprint="decision-fingerprint",
        evidence_fingerprint="evidence-fingerprint",
        harmonic_selection_fingerprint="harmonic-fingerprint",
        review_complete=True,
        screening_status="performed",
        authority="review_only",
        technical_statuses=(
            {
                "category": "cohort_context",
                "recording_id": "P1__V2",
                "participant_id": "P1",
                "condition": "Faces",
                "roi": "Right OT",
                "status": "technical_input_unavailable",
                "reason_codes": ["source_workbook_missing"],
                "fingerprint": "technical-fingerprint",
            },
        ),
    )

    summary, details = build_flagged_participants_tables(qc_report, None)

    assert qc_report.excluded_pids == set()
    detail = details.iloc[0].to_dict()
    assert detail["participant_id"] == "P1__V1"
    assert detail["original_participant_id"] == "P1"
    assert detail["recording_id"] == "P1__V1"
    assert detail["saved_decision"] == "retain"
    assert detail["decision_reason"] == ""
    assert detail["evidence_fingerprint"] == "finding-fingerprint"
    assert detail["source"] == "shared_project_qc17_review"
    assert detail["shared_decision_fingerprint"] == "decision-fingerprint"
    assert detail["shared_source_fingerprint"] == "source-fingerprint"
    assert detail["authority"] == "review_only"
    assert detail["harmonic_selection_fingerprint"] == "harmonic-fingerprint"
    assert summary.iloc[0]["qc_source"] == "shared_project_qc17_review"
    assert summary.iloc[0]["qc_source_fingerprint"] == "source-fingerprint"
    assert summary.iloc[0]["qc_decision_fingerprint"] == "decision-fingerprint"
    assert summary.iloc[0]["qc_evidence_fingerprint"] == "evidence-fingerprint"
    assert summary.iloc[0]["qc_screening_status"] == "performed"
    assert summary.iloc[0]["n_flags"] == 1
    technical = details.iloc[1].to_dict()
    assert technical["participant_id"] == "P1__V2"
    assert technical["original_participant_id"] == "P1"
    assert technical["recording_id"] == "P1__V2"
    assert technical["condition"] == "Faces"
    assert technical["roi"] == "Right OT"
    assert technical["flag_type"] == "QC_TECHNICAL_STATUS"
    assert technical["severity"] == "TECHNICAL_INPUT_UNAVAILABLE"
    assert technical["technical_status_category"] == "cohort_context"
    assert technical["technical_status_reason_codes"] == "source_workbook_missing"
    assert technical["evidence_fingerprint"] == "technical-fingerprint"
    assert technical["shared_decision_fingerprint"] == "decision-fingerprint"
    assert technical["shared_source_fingerprint"] == "source-fingerprint"
    assert technical["shared_evidence_fingerprint"] == "evidence-fingerprint"
    assert technical["harmonic_selection_fingerprint"] == "harmonic-fingerprint"
    assert technical["authority"] == "technical_context"
