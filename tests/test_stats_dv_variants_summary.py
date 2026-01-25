from __future__ import annotations

import pandas as pd

from Tools.Stats.PySide6.dv_policies import FIXED_K_POLICY_NAME, LEGACY_POLICY_NAME
from Tools.Stats.PySide6.dv_variants import build_dv_comparison_summary


def test_build_dv_comparison_summary():
    primary = pd.DataFrame(
        [
            {"subject": "S1", "condition": "A", "roi": "R1", "value": 1.0},
            {"subject": "S2", "condition": "A", "roi": "R1", "value": 3.0},
            {"subject": "S1", "condition": "B", "roi": "R1", "value": 2.0},
        ]
    )
    variant = pd.DataFrame(
        [
            {"subject": "S1", "condition": "A", "roi": "R1", "value": 2.0},
            {"subject": "S2", "condition": "A", "roi": "R1", "value": 4.0},
            {"subject": "S1", "condition": "B", "roi": "R1", "value": 6.0},
        ]
    )

    summary = build_dv_comparison_summary(
        {LEGACY_POLICY_NAME: primary, FIXED_K_POLICY_NAME: variant}
    )

    assert {"condition", "roi"}.issubset(summary.columns)
    assert "N__Legacy" in summary.columns
    assert "mean__Legacy" in summary.columns
    assert "sd__Legacy" in summary.columns
    assert "N__FixedK" in summary.columns

    row_a = summary.loc[(summary["condition"] == "A") & (summary["roi"] == "R1")].iloc[0]
    assert row_a["N__Legacy"] == 2
    assert row_a["mean__Legacy"] == 2.0
    assert row_a["mean__FixedK"] == 3.0
