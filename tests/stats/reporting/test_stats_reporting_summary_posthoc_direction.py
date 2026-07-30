from datetime import datetime
from pathlib import Path

import pandas as pd

from Tools.Stats.reporting.reporting_summary import ReportingSummaryContext, build_reporting_summary


def test_reporting_summary_includes_posthoc_direction_and_slice_labels():
    context = ReportingSummaryContext(
        project_name="Demo",
        project_root=Path("/tmp/demo"),
        pipeline_name="Single",
        generated_local=datetime(2025, 1, 1, 12, 0, 0),
        elapsed_ms=1234,
        timezone_label="UTC",
        total_participants=6,
        included_participants=["S1", "S2", "S3", "S4", "S5", "S6"],
        excluded_reasons={},
        selected_conditions=["C1", "C2"],
        selected_rois=["R1", "R2", "R3"],
    )
    posthoc_df = pd.DataFrame(
        [
            {
                "Direction": "condition_within_roi",
                "Stratum": "R1",
                "FactorAnalyzed": "condition",
                "Level_A": "C1",
                "Level_B": "C2",
                "mean_diff": 1.2,
                "t_statistic": 3.4,
                "p_value": 0.02,
                "p_adjusted": 0.03,
                "method_label": "LMM-derived model-estimated contrast",
                "adjustment_method": "holm",
                "family_id": "planned_contrasts",
            },
            {
                "Direction": "roi_within_condition",
                "Stratum": "C1",
                "FactorAnalyzed": "roi",
                "Level_A": "R1",
                "Level_B": "R2",
                "mean_diff": -0.8,
                "t_statistic": -2.9,
                "p_value": 0.04,
                "p_adjusted": 0.05,
                "method_label": "LMM-derived model-estimated contrast",
                "adjustment_method": "holm",
                "family_id": "planned_contrasts",
            },
        ]
    )

    summary = build_reporting_summary(
        context,
        anova_df=None,
        lmm_df=None,
        posthoc_df=posthoc_df,
    )

    assert "Conditions within ROI rows: 1" in summary
    assert "ROIs within condition rows: 1" in summary
    assert "Tool: Standard FPVS Screening" in summary
    assert "Procedure: LMM-derived model-estimated contrasts" in summary
    assert "LMM FOLLOW-UP CONTRASTS" in summary
    assert "paired t-tests / model contrasts" not in summary
    assert "Family corrected together: planned_contrasts" in summary
    assert "Method: holm" in summary
    assert "[condition_within_roi] stratum=R1 factor=condition" in summary
    assert "[roi_within_condition] stratum=C1 factor=roi" in summary


def test_reporting_summary_keeps_legacy_paired_frames_explicit() -> None:
    context = ReportingSummaryContext(
        project_name="Legacy",
        project_root=Path("/tmp/legacy"),
        pipeline_name="Single",
        generated_local=datetime(2025, 1, 1, 12, 0, 0),
        elapsed_ms=1234,
        timezone_label="UTC",
        total_participants=2,
        included_participants=["S1", "S2"],
        excluded_reasons={},
        selected_conditions=["C1", "C2"],
        selected_rois=["R1"],
    )
    legacy = pd.DataFrame(
        [
            {
                "Direction": "condition_within_roi",
                "Stratum": "R1",
                "FactorAnalyzed": "condition",
                "t_statistic": 2.0,
                "p_value": 0.04,
                "p_fdr_bh": 0.05,
            }
        ]
    )

    summary = build_reporting_summary(
        context,
        anova_df=None,
        lmm_df=None,
        posthoc_df=legacy,
    )

    assert "Procedure: paired t-tests (legacy compatibility results)" in summary
    assert "POST-HOC TESTS (LEGACY)" in summary
    assert "Method: Benjamini-Hochberg (BH) FDR" in summary
    assert "Procedure: LMM-derived model-estimated contrasts" not in summary
