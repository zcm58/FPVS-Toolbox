"""Mixed-model plain-language summary helpers."""

from __future__ import annotations

from typing import Optional
import re

import numpy as np
import pandas as pd

from Tools.Stats.reporting.summary.helpers import _pick_column
from Tools.Stats.reporting.summary.models import SummaryConfig


def _format_p_value(p_value: float) -> str:
    """Format p-values for mixed-model summary text."""

    try:
        value = float(p_value)
    except Exception:
        return "NOT AVAILABLE"
    if np.isnan(value):
        return "NOT AVAILABLE"
    if 0 < value < 0.001:
        return f"{value:.3e}"
    return f"{value:.4f}"


def _direction_word(coef: float) -> str:
    """Map a coefficient sign to plain-language direction."""

    if pd.isna(coef):
        return "equal"
    if coef < 0:
        return "lower"
    if coef > 0:
        return "higher"
    return "equal"


def _extract_sum_coded_label(term: str) -> str:
    """Extract the readable label from a sum-coded model term."""

    if "[S." in term:
        start = term.find("[S.") + 3
        end = term.find("]", start)
        if end > start:
            return term[start:end].strip()
    if "[" in term and "]" in term:
        start = term.find("[") + 1
        end = term.find("]", start)
        if end > start:
            return term[start:end].strip()
    return term


def _is_interaction_term(term: str) -> bool:
    """Return whether a raw term is a condition-by-ROI interaction."""

    lowered = term.lower()
    if any(sep in term for sep in ("×", ":")):
        return "condition" in lowered and "roi" in lowered
    return False


def _is_condition_main_effect(term: str) -> bool:
    """Return whether a raw term is a condition main effect."""

    lowered = term.lower()
    return "c(condition" in lowered and not _is_interaction_term(term)


def _is_roi_main_effect(term: str) -> bool:
    """Return whether a raw term is an ROI main effect."""

    lowered = term.lower()
    return "c(roi" in lowered and not _is_interaction_term(term)


def _is_intercept(term: str) -> bool:
    """Return whether a raw term is an intercept."""

    lowered = term.strip().lower()
    return lowered in {"intercept", "const"}


def format_mixed_model_plain_language(
    mixed_model_terms: pd.DataFrame,
    alpha: float,
) -> list[str]:
    """Build plain-language mixed-model bullets from an exported terms table."""

    p_col = _pick_column(mixed_model_terms, "p", ["P>|z|", "p", "pvalue", "p_value"])
    raw_term_col = _pick_column(mixed_model_terms, "term", ["Effect (raw)", "Effect", "Term"])
    readable_term_col = _pick_column(mixed_model_terms, "readable_term", ["Effect (readable)"])
    if raw_term_col is None and readable_term_col is not None:
        raw_term_col = readable_term_col
    estimate_col = _pick_column(mixed_model_terms, "Estimate", ["Coef.", "Estimate", "coef"])
    if p_col is None or raw_term_col is None:
        return ["- Mixed model: NOT AVAILABLE (not computed by this run)."]

    df = mixed_model_terms.copy()
    df["_term_raw"] = df[raw_term_col].astype(str)
    if readable_term_col is not None:
        df["_term_readable"] = df[readable_term_col].astype(str)
    else:
        df["_term_readable"] = df["_term_raw"]
    df["_p_val"] = pd.to_numeric(df[p_col], errors="coerce")
    df["_estimate"] = pd.to_numeric(df[estimate_col], errors="coerce") if estimate_col else np.nan

    bullets: list[str] = []
    bullets.append("- Inference for fixed effects: Wald z-tests (normal approximation).")
    sig = df[df["_p_val"] < alpha]
    if sig.empty:
        return bullets

    condition_pattern = re.compile(r"^C\(condition\s*,\s*Sum\)\[S\.(?P<level>.+)\]$")
    roi_pattern = re.compile(r"^C\(roi\s*,\s*Sum\)\[S\.(?P<level>.+)\]$")

    def _extract_level(row: pd.Series, match_obj: re.Match[str] | None) -> str:
        if readable_term_col is not None:
            readable = str(row.get("_term_readable", "")).strip()
            if readable and readable.lower() != str(row.get("_term_raw", "")).strip().lower():
                return readable
        if match_obj is not None:
            return match_obj.group("level").strip()
        return _extract_sum_coded_label(str(row.get("_term_raw", "")))

    intercept_rows = sig[sig["_term_raw"].astype(str).str.strip().str.lower() == "intercept"]
    if not intercept_rows.empty:
        row = intercept_rows.iloc[0]
        p_text = _format_p_value(row["_p_val"])
        bullets.append(
            "- Overall response present (p = "
            f"{p_text}): Across all selected conditions and ROIs, the grand-mean DV differs from zero."
        )

    condition_rows = sig[sig["_term_raw"].astype(str).str.match(condition_pattern, na=False)]
    for _, row in condition_rows.iterrows():
        p_text = _format_p_value(row["_p_val"])
        raw_term = str(row["_term_raw"])
        match = condition_pattern.match(raw_term)
        label = _extract_level(row, match)
        direction_word = _direction_word(row["_estimate"])
        bullets.append(
            "- Condition difference (p = "
            f"{p_text}): {label} is {direction_word} than the average of the other condition(s)."
        )

    roi_rows = sig[sig["_term_raw"].astype(str).str.match(roi_pattern, na=False)]
    for _, row in roi_rows.iterrows():
        p_text = _format_p_value(row["_p_val"])
        raw_term = str(row["_term_raw"])
        match = roi_pattern.match(raw_term)
        label = _extract_level(row, match)
        direction_word = _direction_word(row["_estimate"])
        bullets.append(
            "- ROI difference (p = "
            f"{p_text}): {label} is {direction_word} than the average of the other ROIs."
        )

    all_interaction_rows = df[
        df["_term_raw"].astype(str).str.contains(":", regex=False)
        & df["_term_raw"].astype(str).str.contains("C(condition", regex=False)
        & df["_term_raw"].astype(str).str.contains("C(roi", regex=False)
    ]
    interaction_sig = all_interaction_rows[all_interaction_rows["_p_val"] < alpha]
    if not interaction_sig.empty:
        min_p = all_interaction_rows["_p_val"].min()
        p_text = _format_p_value(min_p)
        bullets.append(
            "- Condition-by-ROI interaction (min coefficient p = "
            f"{p_text}): at least one interaction term differs from 0, consistent with condition effects varying by ROI."
        )

    return bullets


def _summarize_mixed_model(
    mixed_model_terms: Optional[pd.DataFrame],
    cfg: SummaryConfig,
) -> list[str]:
    """Return mixed-model summary bullets."""

    if mixed_model_terms is None or not isinstance(mixed_model_terms, pd.DataFrame) or mixed_model_terms.empty:
        return ["- Mixed model: NOT AVAILABLE (not computed by this run)."]

    return format_mixed_model_plain_language(
        mixed_model_terms,
        cfg.alpha,
    )
