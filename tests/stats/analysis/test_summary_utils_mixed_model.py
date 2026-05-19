import pandas as pd

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
