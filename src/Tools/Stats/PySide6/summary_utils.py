"""Rule-based summaries of exported statistical results.

This module reads existing Excel exports from the Stats tool and builds a short,
rule-based summary string suitable for display in the unified output window.
The summarizer is intentionally conservative: it only reports effects that
survive Benjamini–Hochberg FDR correction and meet minimum effect-size
thresholds. Any unexpected files or schemas are handled gracefully by returning
fallback messages instead of raising exceptions. It is part of the
model/service layer and remains GUI-agnostic.
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


@dataclass
class StatsSummaryFrames:
    single_posthoc: Optional[pd.DataFrame] = None
    between_contrasts: Optional[pd.DataFrame] = None
    harmonic_results: Optional[pd.DataFrame] = None
    anova_terms: Optional[pd.DataFrame] = None
    mixed_model_terms: Optional[pd.DataFrame] = None


POSTHOC_XLS = "Posthoc Results.xlsx"
GROUP_CONTRAST_XLS = "Group Contrasts.xlsx"
HARMONIC_XLS = "Harmonic Results.xlsx"
ANOVA_XLS = "RM-ANOVA Results.xlsx"
ANOVA_BETWEEN_XLS = "Mixed ANOVA Between Groups.xlsx"
LMM_XLS = "Mixed Model Results.xlsx"
LMM_BETWEEN_XLS = "Mixed Model Between Groups.xlsx"


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

    frames = StatsSummaryFrames(
        single_posthoc=_safe_read(stats_folder / POSTHOC_XLS, "Post-hoc Results"),
        between_contrasts=_safe_read(stats_folder / GROUP_CONTRAST_XLS, "Post-hoc Results"),
        harmonic_results=_safe_read(stats_folder / HARMONIC_XLS, "Significant Harmonics"),
        mixed_model_terms=_safe_read(stats_folder / LMM_XLS, "Mixed Model"),
    )

    for fname in (ANOVA_BETWEEN_XLS, ANOVA_XLS):
        candidate = _safe_read(stats_folder / fname, "RM-ANOVA Table")
        if candidate is not None:
            frames.anova_terms = candidate
            break

    candidate_lmm_between = _safe_read(stats_folder / LMM_BETWEEN_XLS, "Mixed Model")
    if candidate_lmm_between is not None:
        frames.mixed_model_terms = candidate_lmm_between

    return build_summary_from_frames(frames, config)


def build_summary_from_frames(frames: StatsSummaryFrames, config: SummaryConfig) -> str:
    """
    Produce a short, human-readable summary based on in-memory DataFrames.
    Never raises; on missing/invalid data it emits 'no results' lines for
    the affected sections.
    """

    try:
        single_lines = _summarize_single(frames.single_posthoc, config)
    except Exception:
        single_lines = ["- No within-group results are available for summary."]

    try:
        between_lines = _summarize_between(frames.between_contrasts, config)
    except Exception:
        between_lines = ["- No between-group results are available for summary."]

    try:
        mixed_lines = _summarize_mixed_model(frames.mixed_model_terms, config)
    except Exception:
        mixed_lines = ["- Mixed model: no summary is available."]

    try:
        harmonic_lines = _summarize_harmonics(frames.harmonic_results, config)
    except Exception:
        harmonic_lines = ["- No harmonic check results are available for summary."]

    try:
        interaction_lines = _summarize_interactions(frames.anova_terms, config)
    except Exception:
        interaction_lines = ["- No interaction summary is available."]

    parts = [
        f"--- Summary (α = {config.alpha:.2f}, FDR correction: Benjamini–Hochberg) ---",
        "",
        "Single Group:",
        *(single_lines or ["- No within-group results are available for summary."]),
        "",
        "Between-Group:",
        *(between_lines or ["- No between-group results are available for summary."]),
        "",
        "Mixed Model:",
        *(mixed_lines or ["- Mixed model: no summary is available."]),
        "",
        "Harmonic Check:",
        *(harmonic_lines or ["- No harmonic check results are available for summary."]),
        "",
        "Interactions:",
        *(interaction_lines or ["- No interaction summary is available."]),
        "",
        "Please see the newly generated Excel files in the '3 - Statistical Analysis' folder for complete results. Consult your",
        "favorite statistics expert (for example, ChatGPT) for help interpreting these findings.",
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
    cond_a_col = _pick_column(single_posthoc, "Level_A", ["condition_a"])
    cond_b_col = _pick_column(single_posthoc, "Level_B", ["condition_b"])
    required = [p_col, effect_col, cond_a_col, cond_b_col]
    if any(col is None for col in required):
        return ["- No within-group results are available for summary."]

    df = single_posthoc.copy()
    roi_col = _pick_column(df, "ROI", ["roi"])
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
        cond_a = str(row.get(cond_a_col, "A"))
        cond_b = str(row.get(cond_b_col, "B"))
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


def _summarize_mixed_model(mixed_model_terms: Optional[pd.DataFrame], cfg: SummaryConfig) -> list[str]:
    if mixed_model_terms is None or not isinstance(mixed_model_terms, pd.DataFrame):
        return ["- Mixed model: no summary is available."]

    p_col = _pick_column(mixed_model_terms, cfg.p_col, ["p_fdr_bh", "p_value_fdr", "p_value", "p_fdr"])
    term_col = _pick_column(mixed_model_terms, "term", ["Effect", "Term", "fixed_effect"])
    if p_col is None or term_col is None:
        return ["- Mixed model: no summary is available."]

    df = mixed_model_terms.copy()
    try:
        filtered = df[df[p_col] < cfg.alpha].sort_values(p_col).head(cfg.max_bullets)
    except Exception:
        return ["- Mixed model: no summary is available."]

    if filtered.empty:
        return ["- Mixed model: no fixed effects were significant after FDR correction."]

    bullets: list[str] = []
    for _, row in filtered.iterrows():
        term = str(row.get(term_col, "effect")).strip()
        bullets.append(f"- Mixed model: significant {term} effect (p = {float(row[p_col]):.3f}).")
    return bullets


def _summarize_harmonics(harmonic_results: Optional[pd.DataFrame], cfg: SummaryConfig) -> list[str]:
    if harmonic_results is None or not isinstance(harmonic_results, pd.DataFrame):
        return ["- No harmonic check results are available for summary."]

    roi_col = _pick_column(harmonic_results, "ROI", ["roi"])
    sig_col = _pick_column(harmonic_results, "Significant", ["is_significant"])
    z_col = _pick_column(
        harmonic_results,
        "Mean_Z_Score",
        ["Z", "z_score", "z", "Mean_Z", "mean"],
    )
    p_col = _pick_column(
        harmonic_results,
        cfg.p_col,
        ["P_Value_FDR_BH", "p_corr", "P_Value_HOLM", "P_Value", "p_fdr"],
    )

    if roi_col is None:
        return ["- No harmonic check results are available for summary."]

    df = harmonic_results.copy()
    sig_mask = None
    if sig_col and sig_col in df.columns:
        try:
            sig_mask = df[sig_col].astype(bool)
        except Exception:
            sig_mask = None
    if sig_mask is None and z_col and p_col and z_col in df.columns and p_col in df.columns:
        try:
            sig_mask = (df[z_col] >= cfg.z_threshold) & (df[p_col] < cfg.alpha)
        except Exception:
            sig_mask = None

    if sig_mask is None:
        return ["- No harmonic check results are available for summary."]

    sig_df = df[sig_mask]
    if sig_df.empty:
        return [
            f"- No harmonics met the significance criteria (Z ≥ {cfg.z_threshold}, FDR-corrected p < {cfg.alpha:.2f})."
        ]

    rois = sorted(set(sig_df[roi_col].dropna().astype(str)))
    if not rois:
        return [
            f"- No harmonics met the significance criteria (Z ≥ {cfg.z_threshold}, FDR-corrected p < {cfg.alpha:.2f})."
        ]

    rois_text = ", ".join(rois)
    return [
        "- Significant responses detected at oddball and harmonic frequencies in the following ROIs: "
        f"{rois_text}; see the harmonic check Excel file for full details."
    ]


def _summarize_interactions(interaction_anova: Optional[pd.DataFrame], cfg: SummaryConfig) -> list[str]:
    if interaction_anova is None or not isinstance(interaction_anova, pd.DataFrame):
        return ["- No interaction summary is available."]

    p_col = _pick_column(interaction_anova, cfg.p_col, ["p_fdr_bh", "p_fdr", "p_value", "p_value_fdr"])
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
        bullets.append(
            f"- A significant {term} interaction was detected (p = {float(row[p_col]):.3f}); inspect detailed tables and plots for the pattern."
        )
    return bullets
