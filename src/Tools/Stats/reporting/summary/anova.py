"""RM-ANOVA and interaction summary helpers."""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from Tools.Stats.reporting.summary.helpers import _pick_column
from Tools.Stats.reporting.summary.models import SummaryConfig


def _fmt_p(value: float) -> str:
    """Format p-values for ANOVA text output."""

    if value != 0.0 and abs(value) < 0.001:
        return f"{value:.3e}"
    return f"{value:.6g}"


def format_rm_anova_summary(df: pd.DataFrame, alpha: float) -> str:
    """Summarize interpretable RM/mixed ANOVA terms."""

    out = []
    p_candidates = ["Pr > F", "p-value", "p_value", "p", "P", "pvalue"]
    eff_candidates = ["Effect", "Source", "Factor", "Term"]
    p_col = next((c for c in p_candidates if c in df.columns), None)
    eff_col = next((c for c in eff_candidates if c in df.columns), None)

    if p_col is None:
        out.append("No interpretable effects were found in the ANOVA table.")
        return "\n".join(out)

    for idx, row in df.iterrows():
        effect_source = row.get(eff_col, idx) if eff_col is not None else idx
        effect_name = str(effect_source).strip()
        effect_lower = effect_name.lower()
        effect_compact = effect_lower.replace(" ", "").replace("×", "x")
        p_raw = row.get(p_col, np.nan)
        try:
            p_val = float(p_raw)
        except Exception:
            p_val = np.nan

        if (
            "group" in effect_lower
            and "condition" in effect_lower
            and "roi" in effect_lower
        ):
            tag = "group by condition by ROI interaction"
        elif "group" in effect_lower and "condition" in effect_lower:
            tag = "group-by-condition interaction"
        elif "group" in effect_lower and "roi" in effect_lower:
            tag = "group-by-ROI interaction"
        elif effect_lower.startswith("group") or effect_lower == "group":
            tag = "difference between groups"
        elif effect_compact in {
            "condition*roi",
            "condition:roi",
            "conditionxroi",
            "roi*condition",
            "roi:condition",
            "roixcondition",
        }:
            tag = "condition-by-ROI interaction"
        elif "condition" == effect_lower or effect_lower.startswith("conditions"):
            tag = "difference between conditions"
        elif effect_lower == "roi" or "region" in effect_lower:
            tag = "difference between ROIs"
        else:
            continue

        if np.isfinite(p_val) and p_val < alpha:
            out.append(f"  - Significant {tag} (p = {_fmt_p(p_val)}).")
        elif np.isfinite(p_val):
            out.append(f"  - No significant {tag} (p = {_fmt_p(p_val)}).")
        else:
            out.append(f"  - {tag.capitalize()}: p-value unavailable.")
    if not out:
        out.append("No interpretable effects were found in the ANOVA table.")
    return "\n".join(out)


def build_rm_anova_output(anova_df_results: Optional[pd.DataFrame], alpha: float) -> str:
    """Build the RM-ANOVA console/report text block."""

    output_text = "============================================================\n"
    output_text += "       Repeated Measures ANOVA (RM-ANOVA) Results\n"
    output_text += "       Analysis conducted on: Summed BCA Data\n"
    output_text += "============================================================\n\n"
    output_text += (
        "This test examines the overall effects of your experimental conditions (e.g., different stimuli),\n"
        "the different brain regions (ROIs) you analyzed, and whether the\n"
        "effect of the conditions changes depending on the brain region (interaction effect).\n\n"
    )

    if isinstance(anova_df_results, pd.DataFrame) and not anova_df_results.empty:
        output_text += format_rm_anova_summary(anova_df_results, alpha) + "\n"
        output_text += "--------------------------------------------\n"
        output_text += "NOTE: For detailed reporting and post-hoc tests, refer to the tables above.\n"
        output_text += "--------------------------------------------\n"
    else:
        output_text += "RM-ANOVA returned no results.\n"
    return output_text


def build_between_anova_output(anova_df_results: Optional[pd.DataFrame], alpha: float) -> str:
    """Build the between-group ANOVA console/report text block."""

    output_text = "============================================================\n"
    output_text += "       Between-Group Mixed ANOVA Results\n"
    output_text += "============================================================\n\n"
    output_text += (
        "Group was treated as a between-subject factor with Condition and ROI as\n"
        "within-subject factors. Only subjects with known group assignments were\n"
        "included in this analysis.\n\n"
    )
    if isinstance(anova_df_results, pd.DataFrame) and not anova_df_results.empty:
        output_text += format_rm_anova_summary(anova_df_results, alpha) + "\n"
        output_text += "--------------------------------------------\n"
        output_text += "Refer to the exported table for all Group main and interaction effects.\n"
        output_text += "--------------------------------------------\n"
    else:
        output_text += "Between-group ANOVA returned no results.\n"
    return output_text


def _select_rm_anova_p(row: pd.Series) -> tuple[float, str] | None:
    """Select the preferred RM-ANOVA p-value column for a term."""

    for col, label in (
        ("Pr > F (GG)", "GG corrected"),
        ("Pr > F (HF)", "HF corrected"),
        ("Pr > F", "uncorrected"),
    ):
        if col not in row.index:
            continue
        try:
            value = float(row.get(col))
        except Exception:
            continue
        if np.isfinite(value):
            return value, label
    return None


def _normalize_effect_name(raw: object) -> str:
    """Normalize ANOVA effect labels for summary matching."""

    return " ".join(str(raw).strip().lower().split())


def _summarize_rm_anova(anova_terms: Optional[pd.DataFrame], cfg: SummaryConfig) -> list[str]:
    """Return concise bullets for significant RM-ANOVA effects."""

    if anova_terms is None or not isinstance(anova_terms, pd.DataFrame):
        return ["- No RM-ANOVA results are available."]

    term_col = _pick_column(anova_terms, "Effect", ["Source", "Factor", "Term"])
    if term_col is None:
        return ["- No RM-ANOVA results are available."]

    targets = {
        "condition": "condition",
        "roi": "roi",
        "condition * roi": "condition * roi",
        "condition:roi": "condition * roi",
        "condition*roi": "condition * roi",
    }
    picked: dict[str, tuple[float, str]] = {}
    for _, row in anova_terms.iterrows():
        normalized = _normalize_effect_name(row.get(term_col, ""))
        canonical = targets.get(normalized)
        if canonical is None:
            compact = normalized.replace(" ", "")
            canonical = targets.get(compact)
        if canonical is None:
            continue
        selected = _select_rm_anova_p(row)
        if selected is None:
            continue
        picked[canonical] = selected

    bullets: list[str] = []
    for effect in ("condition", "roi", "condition * roi"):
        selected = picked.get(effect)
        if selected is None:
            continue
        p_value, p_label = selected
        if p_value < cfg.alpha:
            bullets.append(f"- Significant effect of {effect} (p = {_fmt_p(p_value)}, {p_label}).")
    return bullets


def _summarize_interactions(interaction_anova: Optional[pd.DataFrame], cfg: SummaryConfig) -> list[str]:
    """Return concise bullets for significant interaction rows."""

    if interaction_anova is None or not isinstance(interaction_anova, pd.DataFrame):
        return []

    p_col = _pick_column(interaction_anova, cfg.p_col, ["p_fdr_bh", "p_fdr", "p_value", "p_value_fdr"])
    term_col = _pick_column(interaction_anova, "Effect", ["term", "Term"])
    if p_col is None or term_col is None:
        return []

    try:
        tracked = interaction_anova[
            interaction_anova[term_col].astype(str).str.contains("×|x|:", regex=True)
        ]
        significant = tracked[tracked[p_col] < cfg.alpha].sort_values(p_col).head(cfg.max_bullets)
    except Exception:
        return []

    if significant.empty:
        return []

    bullets = []
    for _, row in significant.iterrows():
        term = str(row.get(term_col, "interaction")).strip()
        bullets.append(
            f"- A significant {term} interaction was detected (p = {float(row[p_col]):.3f}); inspect detailed tables and plots for the pattern."
        )
    return bullets
