import numpy as np
import pandas as pd

from Tools.Stats.PySide6.stats_outlier_exclusion import (
    OUTLIER_REASON_LIMIT,
    OUTLIER_REASON_NONFINITE,
    OutlierExclusionReport,
    OutlierExclusionSummary,
    OutlierParticipantReport,
    apply_hard_dv_exclusion,
    build_outlier_summary_text,
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
