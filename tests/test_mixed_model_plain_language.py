import pandas as pd

from Tools.Stats.PySide6.summary_utils import format_mixed_model_plain_language


def test_format_mixed_model_plain_language_describes_direction_and_interactions():
    df = pd.DataFrame(
        {
            "Term": [
                "Intercept",
                "C(condition, Sum)[S.Green Fruit vs Green Veg]",
                "C(roi, Sum)[S.Right Occipito Temporal]",
                "C(condition, Sum)[S.Green Fruit vs Green Veg]:C(roi, Sum)[S.Right Occipito Temporal]",
            ],
            "P>|z|": [0.0005, 0.001, 0.026, 0.02],
            "Estimate": [0.8, -0.4, 0.3, 0.1],
        }
    )

    lines = format_mixed_model_plain_language(df, alpha=0.05)
    summary = "\n".join(lines)

    assert "Overall response present" in summary
    assert "lower" in summary
    assert "higher" in summary
    assert "interaction" in summary
