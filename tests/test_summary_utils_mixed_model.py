import pandas as pd

from Tools.Stats.PySide6.summary_utils import (
    StatsSummaryFrames,
    SummaryConfig,
    build_summary_from_frames,
)


def test_mixed_model_summary_populates_when_terms_present():
    df = pd.DataFrame({
        "Effect": ["group", "condition"],
        "P>|z|": [0.01, 0.2],
    })

    frames = StatsSummaryFrames(mixed_model_terms=df)
    summary = build_summary_from_frames(frames, SummaryConfig())

    assert "Mixed model: significant group effect" in summary
    assert "no summary is available" not in summary
