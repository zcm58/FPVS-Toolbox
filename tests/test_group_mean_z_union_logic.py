from __future__ import annotations

import pandas as pd

from Tools.Stats.PySide6.dv_policies import (
    EMPTY_LIST_FALLBACK_FIXED_K,
    apply_empty_union_policy,
)
from Tools.Stats.PySide6.group_harmonics import compute_union_harmonics_by_roi


def test_group_mean_z_union_logic_and_fallback():
    mean_z_table = pd.DataFrame(
        [
            {"condition": "CondA", "roi": "ROI1", "harmonic_hz": 1.2, "mean_z": 2.0},
            {"condition": "CondA", "roi": "ROI1", "harmonic_hz": 2.4, "mean_z": 1.0},
            {"condition": "CondB", "roi": "ROI1", "harmonic_hz": 2.4, "mean_z": 2.1},
            {"condition": "CondA", "roi": "ROI2", "harmonic_hz": 1.2, "mean_z": 0.5},
            {"condition": "CondB", "roi": "ROI2", "harmonic_hz": 3.6, "mean_z": 0.2},
        ]
    )

    union_map = compute_union_harmonics_by_roi(
        mean_z_table,
        conditions=["CondA", "CondB"],
        z_threshold=1.5,
    )

    assert union_map["ROI1"] == [1.2, 2.4]
    assert union_map["ROI2"] == []

    final_map, fallback_info = apply_empty_union_policy(
        union_map,
        policy=EMPTY_LIST_FALLBACK_FIXED_K,
        fallback_freqs=[1.2, 2.4, 3.6],
    )

    assert final_map["ROI2"] == [1.2, 2.4, 3.6]
    assert fallback_info["ROI2"]["fallback_used"] is True
