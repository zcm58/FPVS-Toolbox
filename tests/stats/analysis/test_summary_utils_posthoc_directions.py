import pandas as pd

from Tools.Stats.reporting.summary import SummaryConfig
from Tools.Stats.reporting.summary.posthoc import _summarize_posthocs


def test_posthoc_summary_includes_both_directions_when_significant():
    posthoc_df = pd.DataFrame(
        {
            "Direction": ["roi_within_condition", "condition_within_roi"],
            "Condition": ["Face", "Face"],
            "ROI": ["ROI1", "ROI1"],
            "Level_A": ["ROI_A", "Cond_A"],
            "Level_B": ["ROI_B", "Cond_B"],
            "mean_diff": [0.3, -0.2],
            "cohens_dz": [0.9, -0.7],
            "p_fdr": [0.01, 0.02],
            "Significant": [True, True],
        }
    )

    lines = _summarize_posthocs(posthoc_df, SummaryConfig())
    summary = "\n".join(lines)

    assert "[roi_within_condition]" in summary
    assert "[condition_within_roi]" in summary
    assert "Condition Face [roi_within_condition]" in summary
    assert "ROI ROI1 [condition_within_roi]" in summary


def test_posthoc_summary_reports_none_found_for_empty_direction():
    posthoc_df = pd.DataFrame(
        {
            "Direction": ["roi_within_condition"],
            "Condition": ["Face"],
            "ROI": ["ROI1"],
            "Level_A": ["ROI_A"],
            "Level_B": ["ROI_B"],
            "mean_diff": [0.3],
            "cohens_dz": [0.9],
            "p_fdr": [0.01],
            "Significant": [True],
        }
    )

    lines = _summarize_posthocs(posthoc_df, SummaryConfig())
    summary = "\n".join(lines)

    assert "Condition Face [roi_within_condition]" in summary
    assert "[condition_within_roi] No significant differences found for this direction." in summary
