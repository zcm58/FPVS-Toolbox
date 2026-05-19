"""Post-hoc summary helpers."""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from Tools.Stats.reporting.summary.helpers import _pick_column
from Tools.Stats.reporting.summary.models import SummaryConfig


def _summarize_posthocs(
    single_posthoc: Optional[pd.DataFrame],
    cfg: SummaryConfig,
) -> list[str]:
    """Return single-pipeline post-hoc summary bullets."""

    if isinstance(single_posthoc, pd.DataFrame) and not single_posthoc.empty:
        return _summarize_single_posthocs_by_direction(single_posthoc, cfg)
    return ["- No post-hoc results are available for summary."]


def _summarize_single_posthocs_by_direction(df: pd.DataFrame, cfg: SummaryConfig) -> list[str]:
    """Return single-pipeline post-hoc summary bullets for both directions."""

    p_col = _pick_column(df, cfg.p_col, ["p_fdr_bh", "p_value_fdr", "p_fdr"])
    eff_col = _pick_column(df, "cohens_dz", ["dz", cfg.effect_col, "effect_size"])
    diff_col = _pick_column(df, "mean_diff", ["diff", "mean_difference"])
    level_a_col = _pick_column(df, "Level_A", ["condition_a"])
    level_b_col = _pick_column(df, "Level_B", ["condition_b"])
    direction_col = _pick_column(df, "Direction", ["direction"])
    condition_col = _pick_column(df, "Condition", ["condition"])
    roi_col = _pick_column(df, "ROI", ["roi"])
    slice_col = _pick_column(df, "Slice", ["slice"])
    significant_col = _pick_column(df, "Significant", ["significant"])
    required = [p_col, eff_col, level_a_col, level_b_col, direction_col]
    if any(col is None for col in required):
        return ["- No post-hoc results are available for summary."]

    direction_order = ("roi_within_condition", "condition_within_roi")
    bullets: list[str] = []
    work = df.copy()
    try:
        if significant_col is not None:
            work = work[work[significant_col].fillna(False).astype(bool)]
        else:
            work = work[work[p_col] < cfg.alpha]
        work["_abs_effect"] = work[eff_col].abs()
    except Exception:
        return ["- No post-hoc results are available for summary."]

    if work.empty:
        return ["- No significant post-hoc comparisons after correction."]

    for direction in direction_order:
        per_direction = work[work[direction_col] == direction].copy()
        if per_direction.empty:
            bullets.append(f"- [{direction}] No significant differences found for this direction.")
            continue

        per_direction = per_direction.sort_values([p_col, "_abs_effect"], ascending=[True, False])
        for _, row in per_direction.head(cfg.max_lines_per_direction).iterrows():
            level_a = str(row.get(level_a_col, "A"))
            level_b = str(row.get(level_b_col, "B"))
            diff = row.get(diff_col, np.nan) if diff_col else np.nan
            dz = float(row[eff_col]) if pd.notna(row[eff_col]) else np.nan
            comparator = ">"
            if pd.notna(diff) and float(diff) < 0:
                comparator = "<"
            if direction == "roi_within_condition":
                stratum = row.get(condition_col, row.get(slice_col, "Condition"))
                context_label = f"Condition {stratum}"
            else:
                stratum = row.get(roi_col, row.get(slice_col, "ROI"))
                context_label = f"ROI {stratum}"
            bullets.append(
                f"- {context_label} [{direction}]: {level_a} {comparator} {level_b} ({level_a} vs {level_b}), "
                f"p = {float(row[p_col]):.3f}, |dz| = {abs(dz):.2f}."
            )

    return bullets
