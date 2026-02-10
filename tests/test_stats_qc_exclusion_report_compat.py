from Tools.Stats.PySide6.stats_qc_exclusion import (
    QcExclusionReport,
    QcExclusionSummary,
    QcParticipantReport,
)


def _summary() -> QcExclusionSummary:
    return QcExclusionSummary(
        n_subjects_before=0,
        n_subjects_flagged=0,
        n_subjects_after=0,
        warn_threshold=6.0,
        critical_threshold=10.0,
        warn_abs_floor_sumabs=5.0,
        critical_abs_floor_sumabs=10.0,
        warn_abs_floor_maxabs=1.0,
        critical_abs_floor_maxabs=2.0,
    )


def test_qc_exclusion_report_compat_excluded_pids_empty() -> None:
    report = QcExclusionReport(
        summary=_summary(),
        participants=[],
        screened_conditions=[],
        screened_rois=[],
    )

    assert hasattr(report, "excluded_pids") is True
    assert report.excluded_pids == set()


def test_qc_exclusion_report_compat_excluded_pids_non_empty() -> None:
    participant = QcParticipantReport(
        participant_id="P01",
        reasons=[],
        n_violations=0,
        worst_value=0.0,
        worst_condition="",
        worst_roi="",
        worst_metric="",
        robust_center=0.0,
        robust_spread=0.0,
        robust_score=0.0,
        threshold_used=0.0,
        trigger_harmonic_hz=None,
        roi_mean_bca_at_trigger=None,
        violations=[],
    )
    report = QcExclusionReport(
        summary=_summary(),
        participants=[participant],
        screened_conditions=["CondA"],
        screened_rois=["ROI1"],
    )

    assert hasattr(report, "excluded_pids") is True
    assert report.excluded_pids == {"P01"}
