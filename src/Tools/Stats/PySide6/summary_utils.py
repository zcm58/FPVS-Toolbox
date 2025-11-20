"""Rule-based summaries of exported statistical results.

This module reads existing Excel exports from the Stats tool and builds a short,
deterministic summary string suitable for display in the unified output window.
The summarizer is intentionally conservative: it only reports effects that
survive Benjamini–Hochberg FDR correction and meet minimum effect-size
thresholds. Any unexpected files or schemas are handled gracefully by returning
fallback messages instead of raising exceptions.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd


@dataclass
class SummaryConfig:
    alpha: float = 0.05
    min_effect: float = 0.50
    max_bullets: int = 3
    z_threshold: float = 1.64
    p_col: str = "p_fdr"
    effect_col: str = "effect_size"


POSTHOC_XLS = "Posthoc Results.xlsx"
GROUP_CONTRAST_XLS = "Group Contrasts.xlsx"
HARMONIC_XLS = "Harmonic Results.xlsx"
ANOVA_XLS = "RM-ANOVA Results.xlsx"
ANOVA_BETWEEN_XLS = "Mixed ANOVA Between Groups.xlsx"


def build_summary_from_files(stats_folder: Path, config: SummaryConfig) -> str:
    """
    Read existing Excel outputs in `stats_folder` and return a short summary.

    The function is fail-safe: any file-read or parsing issues result in
    section-specific fallback messages rather than exceptions.
    """

    def _safe_read(path: Path, sheet: str) -> Optional[pd.DataFrame]:
        if not path.is_file():
            return None
        try:
            return pd.read_excel(path, sheet_name=sheet)
        except Exception:
            return None

    single_df = _safe_read(stats_folder / POSTHOC_XLS, "Post-hoc Results")
    between_df = _safe_read(stats_folder / GROUP_CONTRAST_XLS, "Post-hoc Results")
    harmonic_df = _safe_read(stats_folder / HARMONIC_XLS, "Significant Harmonics")

    interaction_df: Optional[pd.DataFrame] = None
    for fname in (ANOVA_BETWEEN_XLS, ANOVA_XLS):
        candidate = _safe_read(stats_folder / fname, "RM-ANOVA Table")
        if candidate is not None:
            interaction_df = candidate
            break

    parts = [
        f"--- Summary (α = {config.alpha:.2f}, FDR correction: Benjamini–Hochberg) ---",
        "",
        "Single Group:",
        *(_summarize_single(single_df, config) or ["- No within-group results are available for summary."]),
        "",
        "Between-Group:",
        *(_summarize_between(between_df, config) or ["- No between-group results are available for summary."]),
        "",
        "Harmonic Check:",
        *(_summarize_harmonics(harmonic_df, config) or ["- No harmonic check results are available for summary."]),
        "",
        "Interactions:",
        *(_summarize_interactions(interaction_df, config) or ["- No interaction summary is available."]),
        "",
        "Please see the newly generated Excel files in the '3 - Statistical Analysis' folder for complete results. Consult your favorite statistics expert (for example, ChatGPT) for help interpreting these findings.",
    ]
    return "\n".join(parts)


def _pick_column(df: pd.DataFrame, preferred: str, fallbacks: Iterable[str]) -> Optional[str]:
    for name in (preferred, *fallbacks):
        if name in df.columns:
            return name
    return None


def _summarize_single(single_posthoc: Optional[pd.DataFrame], cfg: SummaryConfig) -> list[str]:
    if single_posthoc is None or not isinstance(single_posthoc, pd.DataFrame):
        return ["- No within-group results are available for summary."]

    p_col = _pick_column(single_posthoc, cfg.p_col, ["p_fdr_bh", "p_value_fdr", "p_fdr"])
    effect_col = _pick_column(single_posthoc, cfg.effect_col, ["cohens_dz", "dz", "effect_size"])
    required = [p_col, effect_col, "Level_A", "Level_B"]
    if any(col is None for col in required):
        return ["- No within-group results are available for summary."]

    df = single_posthoc.copy()
    roi_col = "ROI" if "ROI" in df.columns else None
    try:
        df["_abs_eff"] = df[effect_col].abs()
        mask = (df[p_col] < cfg.alpha) & (df["_abs_eff"] >= cfg.min_effect)
        filtered = df.loc[mask].sort_values("_abs_eff", ascending=False).head(cfg.max_bullets)
    except Exception:
        return ["- No within-group results are available for summary."]

    if filtered.empty:
        return ["- No within-group condition effects survived FDR correction at α = 0.05."]

    bullets: list[str] = []
    for _, row in filtered.iterrows():
        roi = row.get(roi_col) if roi_col else "ROI"
        eff = float(row[effect_col]) if pd.notna(row[effect_col]) else 0.0
        cond_a = str(row.get("Level_A", "A"))
        cond_b = str(row.get("Level_B", "B"))
        high, low = (cond_a, cond_b) if eff >= 0 else (cond_b, cond_a)
        bullets.append(
            f"- In {roi}, {high} > {low}, p = {float(row[p_col]):.3f}, dz = {eff:.2f}."
        )
    return bullets


def _summarize_between(between_contrasts: Optional[pd.DataFrame], cfg: SummaryConfig) -> list[str]:
    if between_contrasts is None or not isinstance(between_contrasts, pd.DataFrame):
        return ["- No between-group results are available for summary."]

    p_col = _pick_column(between_contrasts, cfg.p_col, ["p_fdr_bh", "p_fdr"])
    effect_col = _pick_column(between_contrasts, cfg.effect_col, ["effect_size", "cohens_d", "d"])
    required = [p_col, effect_col, "condition", "roi", "group_1", "group_2"]
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
        return ["- No between-group differences survived FDR correction at α = 0.05."]

    bullets: list[str] = []
    for _, row in filtered.iterrows():
        eff = float(row[effect_col]) if pd.notna(row[effect_col]) else 0.0
        g1, g2 = str(row.get("group_1", "Group 1")), str(row.get("group_2", "Group 2"))
        high, low = (g1, g2) if eff >= 0 else (g2, g1)
        roi = row.get("roi", "ROI")
        cond = row.get("condition", "Condition")
        bullets.append(
            f"- Between groups, {high} > {low} in {roi} for {cond}, p = {float(row[p_col]):.3f}, d = {eff:.2f}."
        )
    return bullets


def _summarize_harmonics(harmonic_results: Optional[pd.DataFrame], cfg: SummaryConfig) -> list[str]:
    if harmonic_results is None or not isinstance(harmonic_results, pd.DataFrame):
        return ["- No harmonic check results are available for summary."]

    roi_col = _pick_column(harmonic_results, "ROI", [])
    freq_col = _pick_column(harmonic_results, "Frequency_Hz", ["Frequency", "freq_hz"])
    condition_col = _pick_column(harmonic_results, "Condition", [])
    sig_col = _pick_column(harmonic_results, "Significant", ["is_significant"])

    if roi_col is None or freq_col is None:
        return ["- No harmonic check results are available for summary."]

    df = harmonic_results.copy()
    if sig_col in df.columns:
        df = df[df[sig_col] == True]  # noqa: E712

    if df.empty:
        return [f"- No harmonics met the significance criteria (Z ≥ {cfg.z_threshold}, FDR-corrected p < 0.05)."]

    groups = {}
    for _, row in df.iterrows():
        roi = row.get(roi_col, "ROI")
        freq = row.get(freq_col)
        if pd.notna(freq):
            freq_val = f"{float(freq):.2f}" if isinstance(freq, (int, float)) else str(freq)
            groups.setdefault(roi, []).append(freq_val)

    if not groups:
        return [f"- No harmonics met the significance criteria (Z ≥ {cfg.z_threshold}, FDR-corrected p < 0.05)."]

    sorted_rois = sorted(groups.items(), key=lambda kv: len(kv[1]), reverse=True)[: cfg.max_bullets]
    segments = []
    for roi, freqs in sorted_rois:
        unique_freqs = sorted(set(freqs), key=lambda v: float(v.split()[0]) if str(v).replace('.', '', 1).isdigit() else v)
        cond_prefix = ""
        if condition_col and condition_col in df.columns:
            conds = sorted(set(df.loc[df[roi_col] == roi, condition_col].dropna().astype(str)))
            if conds:
                cond_prefix = f" ({', '.join(conds)})"
        segments.append(f"{roi}{cond_prefix} at {', '.join(unique_freqs)} Hz")

    return [f"- Significant harmonics in " + "; ".join(segments) + "."]


def _summarize_interactions(interaction_anova: Optional[pd.DataFrame], cfg: SummaryConfig) -> list[str]:
    if interaction_anova is None or not isinstance(interaction_anova, pd.DataFrame):
        return ["- No interaction summary is available."]

    p_col = _pick_column(interaction_anova, cfg.p_col, ["p_fdr_bh", "p_fdr"])
    term_col = _pick_column(interaction_anova, "Effect", ["term", "Term"])
    if p_col is None or term_col is None:
        return ["- No interaction summary is available."]

    try:
        tracked = interaction_anova[
            interaction_anova[term_col].astype(str).str.contains("×|x|:", regex=True)
        ]
        significant = tracked[tracked[p_col] < cfg.alpha].sort_values(p_col).head(cfg.max_bullets)
    except Exception:
        return ["- No interaction summary is available."]

    if significant.empty:
        return ["- No tracked interaction terms were significant after FDR correction."]

    bullets = []
    for _, row in significant.iterrows():
        term = str(row.get(term_col, "interaction")).strip()
        bullets.append(f"- A significant {term} interaction was detected (p = {float(row[p_col]):.3f}); inspect detailed tables and plots for the pattern.")
    return bullets

