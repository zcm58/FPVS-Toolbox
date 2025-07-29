# -*- coding: utf-8 -*-
"""Helper functions to create simplified summaries of statistical results."""

from __future__ import annotations

import pandas as pd
from typing import List


def generate_lme_summary(results_df: pd.DataFrame, alpha: float = 0.05) -> str:
    """Return a human readable summary of LME fixed effect results.

    Parameters
    ----------
    results_df : pd.DataFrame
        DataFrame returned by ``run_mixed_effects_model`` containing at least
        an ``Effect`` column and a p-value column (``P>|z|`` or ``P>|t|``).
    alpha : float, optional
        Significance threshold for determining noteworthy effects, by default 0.05.

    Notes
    -----
    The summary is intentionally simple. It highlights significant interactions
    first and then main effects. Effect names are interpreted in a basic way and
    should not replace a full statistical report.
    """
    if results_df is None or results_df.empty:
        return "No results available to summarise.\n"

    p_val_col = "P>|z|" if "P>|z|" in results_df.columns else "P>|t|" if "P>|t|" in results_df.columns else None
    if not p_val_col or "Effect" not in results_df.columns:
        return "Results table missing required columns for summary.\n"

    significant_interactions: List[str] = []
    significant_condition: List[str] = []
    significant_roi: List[str] = []

    for _, row in results_df.iterrows():
        effect = str(row["Effect"]).strip()
        try:
            p_val = float(row[p_val_col])
        except Exception:
            continue

        is_significant = p_val < alpha
        p_display = "< .0001" if p_val < 0.0001 else f"{p_val:.4f}"
        effect_lower = effect.lower()

        if ":" in effect and is_significant:
            significant_interactions.append(f"Effect '{effect}' was significant (p = {p_display}).")
        elif effect_lower.startswith("condition") and is_significant:
            significant_condition.append(f"Effect '{effect}' was significant relative to baseline (p = {p_display}).")
        elif effect_lower.startswith("roi") and is_significant:
            significant_roi.append(f"Effect '{effect}' was significant relative to baseline (p = {p_display}).")

    parts: List[str] = []
    parts.append("--------------------------------------------")
    parts.append("            KEY FINDINGS")
    parts.append("--------------------------------------------")
    parts.append(
        "Effects are interpreted relative to reference groups automatically\n"
        "chosen by statsmodels (typically the first level alphabetically)."
    )

    if significant_interactions:
        parts.append("\nSignificant interaction effects were detected:")
        for line in significant_interactions:
            parts.append(f"  - {line}")

    if significant_condition:
        header = "\nMain effects of Condition:" if not significant_interactions else "\nMain effects of Condition (interpret with caution due to interaction):"
        parts.append(header)
        for line in significant_condition:
            parts.append(f"  - {line}")

    if significant_roi:
        header = "\nMain effects of ROI:" if not significant_interactions else "\nMain effects of ROI (interpret with caution due to interaction):"
        parts.append(header)
        for line in significant_roi:
            parts.append(f"  - {line}")

    if not (significant_interactions or significant_condition or significant_roi):
        parts.append("\nNo effects reached the significance threshold.")

    parts.append("--------------------------------------------")
    parts.append(
        "This simplified interpretation is a guide. Please refer to the\n"
        "statistical table above for full details."
    )
    parts.append("--------------------------------------------")
    return "\n".join(parts) + "\n"
