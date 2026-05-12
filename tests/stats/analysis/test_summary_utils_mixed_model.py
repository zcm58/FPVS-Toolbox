import pandas as pd

from Tools.Stats.common.stats_core import PipelineId
from Tools.Stats.reporting.summary import (
    StatsSummaryFrames,
    SummaryConfig,
    build_summary_from_frames,
    format_mixed_model_plain_language,
)
from Tools.Stats.reporting.summary.mixed_model import _format_p_value


def test_mixed_model_summary_populates_when_terms_present():
    df = pd.DataFrame({
        "Effect": ["Intercept", "C(condition, Sum)[S.Test Condition]"],
        "P>|z|": [0.01, 0.2],
        "Estimate": [1.2, -0.5],
    })

    frames = StatsSummaryFrames(mixed_model_terms=df)
    summary = build_summary_from_frames(frames, SummaryConfig())

    assert "Overall response present" in summary
    assert "no summary is available" not in summary


def test_lmm_summary_includes_intercept_and_mains():
    lmm_df = pd.DataFrame({
        "Effect (raw)": [
            "Intercept",
            "C(condition, Sum)[S.Face]",
            "C(roi, Sum)[S.Occipital]",
            "C(condition, Sum)[S.Face]:C(roi, Sum)[S.Occipital]",
        ],
        "Coef.": [1.1, -0.3, 0.4, 0.2],
        "P>|z|": [1.2e-24, 0.0049, 0.03, 7.91e-08],
    })

    lines = format_mixed_model_plain_language(lmm_df, alpha=0.05)
    summary = "\n".join(lines)

    assert "Overall response present" in summary
    assert "Condition difference" in summary
    assert "ROI difference" in summary
    assert "Condition-by-ROI interaction" in summary


def test_fmt_p_scientific_under_0_001():
    assert "e-" in _format_p_value(1.2e-24)
    assert _format_p_value(0.0049) == "0.0049"


def test_no_summary_when_missing_df():
    frames = StatsSummaryFrames(mixed_model_terms=None)
    summary = build_summary_from_frames(frames, SummaryConfig())

    assert "NOT AVAILABLE" in summary
    assert "Wald z-tests" not in summary


def test_between_summary_omits_rm_anova_section():
    contrasts_df = pd.DataFrame(
        {
            "group_1": ["G1"],
            "group_2": ["G2"],
            "condition": ["Face"],
            "roi": ["Occipital"],
            "difference": [0.6],
            "effect_size": [0.7],
            "p_fdr": [0.02],
        }
    )
    lmm_df = pd.DataFrame(
        {
            "Effect": ["group"],
            "Estimate": [0.5],
            "P>|z|": [0.03],
        }
    )

    frames = StatsSummaryFrames(
        between_contrasts=contrasts_df,
        mixed_model_terms=lmm_df,
        pipeline_id=PipelineId.BETWEEN,
    )
    summary = build_summary_from_frames(frames, SummaryConfig())

    assert "RM-ANOVA:" not in summary
    assert "Group contrasts:" in summary


def test_between_summary_accepts_supported_multigroup_export_schema():
    contrasts_df = pd.DataFrame(
        {
            "ROI": ["Occipital"],
            "Condition": ["Face"],
            "GroupA": ["G1"],
            "GroupB": ["G2"],
            "Estimate": [0.6],
            "P": [0.01],
            "P_corrected": [0.02],
            "Method": ["fdr_bh"],
        }
    )
    lmm_df = pd.DataFrame(
        {
            "Effect": ["Intercept"],
            "Estimate": [0.5],
            "P>|z|": [0.03],
        }
    )

    frames = StatsSummaryFrames(
        between_contrasts=contrasts_df,
        mixed_model_terms=lmm_df,
        pipeline_id=PipelineId.BETWEEN,
    )
    summary = build_summary_from_frames(frames, SummaryConfig())

    assert "RM-ANOVA:" not in summary
    assert "Group contrasts:" in summary
    assert "Occipital (Face): G1 > G2, p_adj = 0.020" in summary
    assert "post-hoc" not in summary.lower()
