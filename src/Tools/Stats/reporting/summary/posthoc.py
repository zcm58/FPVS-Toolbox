"""Post-hoc and group-contrast summary helpers."""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from Tools.Stats.reporting.summary.helpers import _pick_column
from Tools.Stats.reporting.summary.models import SummaryConfig


def _coerce_between_contrasts_for_summary(
    between_contrasts: Optional[pd.DataFrame],
) -> Optional[pd.DataFrame]:
    """Normalize multigroup contrast tables from raw or exported schemas."""

    if between_contrasts is None or not isinstance(between_contrasts, pd.DataFrame) or between_contrasts.empty:
        return None

    df = between_contrasts.copy()
    roi_col = _pick_column(df, "ROI", ["roi"])
    cond_col = _pick_column(df, "Condition", ["condition"])
    g1_col = _pick_column(df, "GroupA", ["group_1", "Group_1", "group1"])
    g2_col = _pick_column(df, "GroupB", ["group_2", "Group_2", "group2"])
    estimate_col = _pick_column(df, "Estimate", ["difference", "mean_diff", "mean_difference", "estimate"])
    effect_col = _pick_column(df, "effect_size", ["cohens_d", "d"])
    p_adj_col = _pick_column(df, "P_corrected", ["p_fdr_bh", "p_fdr", "p_corr", "p_adj"])
    p_raw_col = _pick_column(df, "P", ["p_value", "p_raw", "p"])
    if any(col is None for col in (roi_col, cond_col, g1_col, g2_col)):
        return None

    out = pd.DataFrame(
        {
            "roi": df[roi_col],
            "condition": df[cond_col],
            "group_1": df[g1_col],
            "group_2": df[g2_col],
            "estimate": pd.to_numeric(df[estimate_col], errors="coerce")
            if estimate_col is not None
            else np.nan,
            "effect_size": pd.to_numeric(df[effect_col], errors="coerce")
            if effect_col is not None
            else np.nan,
            "p_adjusted": pd.to_numeric(df[p_adj_col], errors="coerce")
            if p_adj_col is not None
            else np.nan,
            "p_raw": pd.to_numeric(df[p_raw_col], errors="coerce")
            if p_raw_col is not None
            else np.nan,
        }
    )
    out["roi"] = out["roi"].astype(str)
    out["condition"] = out["condition"].astype(str)
    out["group_1"] = out["group_1"].astype(str)
    out["group_2"] = out["group_2"].astype(str)
    return out


def _summarize_posthocs(
    single_posthoc: Optional[pd.DataFrame],
    between_contrasts: Optional[pd.DataFrame],
    cfg: SummaryConfig,
) -> list[str]:
    """Return post-hoc or group-contrast summary bullets."""

    if isinstance(single_posthoc, pd.DataFrame) and not single_posthoc.empty:
        return _summarize_single_posthocs_by_direction(single_posthoc, cfg)

    if isinstance(between_contrasts, pd.DataFrame) and not between_contrasts.empty:
        df = _coerce_between_contrasts_for_summary(between_contrasts)
        if df is None or df.empty:
            return ["- No group contrasts are available for summary."]
        try:
            sort_key = df["p_adjusted"].where(df["p_adjusted"].notna(), df["p_raw"])
            sig = df[sort_key < cfg.alpha].copy()
            sig["_sort_p"] = sort_key.loc[sig.index]
            sig["_sort_effect"] = sig["effect_size"].abs().where(
                sig["effect_size"].notna(), sig["estimate"].abs()
            )
            sig = sig.sort_values(by=["_sort_p", "_sort_effect"], ascending=[True, False])
        except Exception:
            return ["- No group contrasts are available for summary."]
        if sig.empty:
            return ["- No significant group contrasts after correction."]
        bullets = []
        for _, row in sig.head(cfg.max_bullets).iterrows():
            roi = row.get("roi", "ROI")
            cond = row.get("condition", "Condition")
            g1 = str(row.get("group_1", "Group 1"))
            g2 = str(row.get("group_2", "Group 2"))
            diff = row.get("estimate", np.nan)
            high, low = (g1, g2)
            if pd.notna(diff) and float(diff) < 0:
                high, low = (g2, g1)
            p_value = row.get("p_adjusted", np.nan)
            p_label = "p_adj"
            if pd.isna(p_value):
                p_value = row.get("p_raw", np.nan)
                p_label = "p"
            detail = f"{p_label} = {float(p_value):.3f}"
            effect_value = row.get("effect_size", np.nan)
            if pd.notna(effect_value):
                detail += f", d = {float(effect_value):.2f}"
            elif pd.notna(diff):
                detail += f", estimate = {float(diff):.2f}"
            bullets.append(f"- {roi} ({cond}): {high} > {low}, {detail}.")
        return bullets

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


def _summarize_between(between_contrasts: Optional[pd.DataFrame], cfg: SummaryConfig) -> list[str]:
    """Return between-group contrast summary bullets."""

    if between_contrasts is None or not isinstance(between_contrasts, pd.DataFrame):
        return ["- No between-group results are available for summary."]

    p_col = _pick_column(between_contrasts, cfg.p_col, ["p_fdr_bh", "p_fdr"])
    effect_col = _pick_column(between_contrasts, cfg.effect_col, ["effect_size", "cohens_d", "d"])
    cond_col = _pick_column(between_contrasts, "condition", ["Condition"])
    roi_col = _pick_column(between_contrasts, "roi", ["ROI"])
    g1_col = _pick_column(between_contrasts, "group_1", ["Group_1", "group1"])
    g2_col = _pick_column(between_contrasts, "group_2", ["Group_2", "group2"])
    required = [p_col, effect_col, cond_col, roi_col, g1_col, g2_col]
    if any(col is None for col in required):
        return ["- No between-group results are available for summary."]

    df = between_contrasts.copy()
    try:
        df["_abs_eff"] = df[effect_col].abs()
        mask = (df[p_col] < cfg.alpha) & (df["_abs_eff"] >= cfg.min_effect)
        filtered = df.loc[mask].sort_values("_abs_eff", ascending=False).head(cfg.max_bullets)
    except Exception:
        return ["- No between-group results are available for summary."]

    if filtered.empty:
        return ["- No between-group pairwise contrasts survived FDR correction at α = 0.05."]

    bullets: list[str] = []
    for _, row in filtered.iterrows():
        eff = float(row[effect_col]) if pd.notna(row[effect_col]) else 0.0
        g1, g2 = str(row.get(g1_col, "Group 1")), str(row.get(g2_col, "Group 2"))
        high, low = (g1, g2) if eff >= 0 else (g2, g1)
        roi = row.get(roi_col, "ROI")
        cond = row.get(cond_col, "Condition")
        bullets.append(
            f"- Between groups, {high} > {low} in {roi} for {cond}, p = {float(row[p_col]):.3f}, d = {eff:.2f}."
        )
    return bullets
