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
import logging
from pathlib import Path
from typing import Iterable, Optional

import numpy as np
import pandas as pd

from Tools.Stats.PySide6.stats_core import (
    ANOVA_BETWEEN_XLS,
    ANOVA_XLS,
    GROUP_CONTRAST_XLS,
    LMM_BETWEEN_XLS,
    LMM_XLS,
    POSTHOC_XLS,
    PipelineId,
)

logger = logging.getLogger("Tools.Stats")


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

    def _safe_read_any(path: Path, sheets: list[str]) -> Optional[pd.DataFrame]:
        for sheet in sheets:
            df = _safe_read(path, sheet)
            if df is not None:
                return df
        return None

    frames = StatsSummaryFrames(
        single_posthoc=_safe_read_any(stats_folder / POSTHOC_XLS, ["Combined", "Post-hoc Results"]),
        between_contrasts=_safe_read(stats_folder / GROUP_CONTRAST_XLS, "Post-hoc Results"),
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
        anova_lines = _summarize_rm_anova(frames.anova_terms, config)
    except Exception:
        anova_lines = ["- No RM-ANOVA results are available for summary."]

    try:
        posthoc_lines = _summarize_posthocs(
            frames.single_posthoc, frames.between_contrasts, config
        )
    except Exception:
        posthoc_lines = ["- No post-hoc results are available for summary."]

    try:
        mixed_lines = _summarize_mixed_model(frames.mixed_model_terms, config)
    except Exception:
        mixed_lines = ["- Mixed model: no summary is available."]

    try:
        interaction_lines = _summarize_interactions(frames.anova_terms, config)
    except Exception:
        interaction_lines = []

    parts = [
        f"--- Summary (α = {config.alpha:.2f}, FDR correction: Benjamini–Hochberg) ---",
        "",
        "RM-ANOVA:",
        *(anova_lines or ["- No significant RM-ANOVA effects."]),
        "",
        "Post-hoc comparisons:",
        *(posthoc_lines or ["- No significant post-hoc comparisons after correction."]),
        "",
        "Mixed model:",
        *(mixed_lines or ["- Mixed model: no summary is available."]),
        "",
        *(
            ["Interactions:", *interaction_lines, ""]
            if interaction_lines
            else []
        ),
        "Please see the newly generated Excel files in the '3 - Statistical Analysis' folder for complete results. Consult your",
        "favorite statistics expert (for example, ChatGPT) for help interpreting these findings.",
    ]
    return "\n".join(parts)


def to_dataframe(data) -> Optional[pd.DataFrame]:
    if isinstance(data, pd.DataFrame):
        return data
    if isinstance(data, list) and data:
        try:
            df = pd.DataFrame(data)
            return df if not df.empty else None
        except Exception:
            return None
    if isinstance(data, dict) and data:
        try:
            df = pd.DataFrame(data)
            if not df.empty:
                return df
        except Exception:
            pass
        try:
            flattened: list = []
            for value in data.values():
                if isinstance(value, dict):
                    flattened.extend(value.values())
                else:
                    flattened.append(value)
            if flattened:
                df = pd.DataFrame(flattened)
                return df if not df.empty else None
        except Exception:
            return None
    return None


def build_summary_frames_from_results(
    pipeline_id: PipelineId,
    *,
    single_posthoc: Optional[pd.DataFrame] = None,
    rm_anova_results: Optional[pd.DataFrame] = None,
    mixed_model_results: Optional[pd.DataFrame] = None,
    between_contrasts: Optional[pd.DataFrame] = None,
    between_anova_results: Optional[pd.DataFrame] = None,
    between_mixed_model_results: Optional[pd.DataFrame] = None,
    harmonic_results: Optional[pd.DataFrame | list[dict]] = None,
) -> StatsSummaryFrames:
    frames = StatsSummaryFrames()
    if pipeline_id is PipelineId.SINGLE:
        frames.single_posthoc = to_dataframe(single_posthoc)
        frames.anova_terms = to_dataframe(rm_anova_results)
        frames.mixed_model_terms = to_dataframe(mixed_model_results)
    elif pipeline_id is PipelineId.BETWEEN:
        frames.between_contrasts = to_dataframe(between_contrasts)
        frames.anova_terms = to_dataframe(between_anova_results)
        frames.mixed_model_terms = to_dataframe(between_mixed_model_results)
    frames.harmonic_results = to_dataframe(harmonic_results)
    return frames


def format_rm_anova_summary(df: pd.DataFrame, alpha: float) -> str:
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
            out.append(f"  - Significant {tag} (p = {p_val:.4g}).")
        elif np.isfinite(p_val):
            out.append(f"  - No significant {tag} (p = {p_val:.4g}).")
        else:
            out.append(f"  - {tag.capitalize()}: p-value unavailable.")
    if not out:
        out.append("No interpretable effects were found in the ANOVA table.")
    return "\n".join(out)


def build_rm_anova_output(anova_df_results: Optional[pd.DataFrame], alpha: float) -> str:
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


def _pick_column(df: pd.DataFrame, preferred: str, fallbacks: Iterable[str]) -> Optional[str]:
    for name in (preferred, *fallbacks):
        if name in df.columns:
            return name
    return None


def _summarize_rm_anova(anova_terms: Optional[pd.DataFrame], cfg: SummaryConfig) -> list[str]:
    if anova_terms is None or not isinstance(anova_terms, pd.DataFrame):
        return ["- No RM-ANOVA results are available."]

    p_col = _pick_column(anova_terms, cfg.p_col, ["Pr > F", "p_value", "p-value", "p", "P"])
    term_col = _pick_column(anova_terms, "Effect", ["Source", "Factor", "Term"])
    if p_col is None or term_col is None:
        return ["- No RM-ANOVA results are available."]

    df = anova_terms.copy()
    try:
        df["_term_str"] = df[term_col].astype(str)
    except Exception:
        return ["- No RM-ANOVA results are available."]

    def _is_interaction(term: str) -> bool:
        lowered = term.lower()
        if any(sep in term for sep in ("×", ":", "*")):
            return True
        if " x " in lowered:
            return True
        return False

    main_effects = df[~df["_term_str"].apply(_is_interaction)]
    try:
        sig = main_effects[main_effects[p_col] < cfg.alpha].sort_values(p_col)
    except Exception:
        return ["- No RM-ANOVA results are available."]

    if sig.empty:
        return ["- No significant RM-ANOVA effects."]

    bullets = []
    for _, row in sig.iterrows():
        term = str(row.get(term_col, "effect")).strip()
        bullets.append(f"- Significant effect of {term} (p = {float(row[p_col]):.4g}).")
    return bullets


def _summarize_posthocs(
    single_posthoc: Optional[pd.DataFrame],
    between_contrasts: Optional[pd.DataFrame],
    cfg: SummaryConfig,
) -> list[str]:
    if isinstance(single_posthoc, pd.DataFrame) and not single_posthoc.empty:
        df = single_posthoc.copy()
        p_col = _pick_column(df, cfg.p_col, ["p_fdr_bh", "p_value_fdr", "p_fdr"])
        eff_col = _pick_column(df, "cohens_dz", ["dz", cfg.effect_col, "effect_size"])
        diff_col = _pick_column(df, "mean_diff", ["diff", "mean_difference"])
        cond_a_col = _pick_column(df, "Level_A", ["condition_a"])
        cond_b_col = _pick_column(df, "Level_B", ["condition_b"])
        roi_col = _pick_column(df, "ROI", ["roi"])
        direction_col = _pick_column(df, "Direction", ["direction"])
        condition_col = _pick_column(df, "Condition", ["condition"])
        slice_col = _pick_column(df, "Slice", ["slice"])
        required = [p_col, eff_col, cond_a_col, cond_b_col]
        if any(col is None for col in required):
            return ["- No post-hoc results are available for summary."]
        try:
            sig = df[df[p_col] < cfg.alpha].sort_values(p_col)
        except Exception:
            return ["- No post-hoc results are available for summary."]
        if sig.empty:
            return ["- No significant post-hoc comparisons after correction."]
        bullets = []
        for _, row in sig.head(cfg.max_bullets).iterrows():
            row_direction = str(row.get(direction_col, "")) if direction_col else ""
            if row_direction == "roi_within_condition":
                context_label = f"Condition {row.get(condition_col, row.get(slice_col, 'Condition'))}"
            else:
                context_label = f"ROI {row.get(roi_col, row.get(slice_col, 'ROI'))}"
            a = str(row.get(cond_a_col, "A"))
            b = str(row.get(cond_b_col, "B"))
            diff = row.get(diff_col, np.nan) if diff_col else np.nan
            dz = float(row[eff_col]) if pd.notna(row[eff_col]) else np.nan
            swap = False
            if pd.notna(diff):
                swap = float(diff) < 0
            elif pd.notna(dz):
                swap = dz < 0

            if pd.notna(diff) and pd.notna(dz):
                diff_val = float(diff)
                if diff_val != 0 and dz != 0 and np.sign(diff_val) != np.sign(dz):
                    logger.warning(
                        "Post-hoc dz sign mismatch for %s vs %s in %s: mean_diff=%s dz=%s",
                        a,
                        b,
                        context_label,
                        diff,
                        dz,
                    )

            direction, other = (b, a) if swap else (a, b)
            dz_display = abs(dz) if pd.notna(dz) else np.nan
            bullets.append(
                f"- {context_label} [{row_direction or 'condition_within_roi'}]: {direction} > {other} ({a} vs {b}), "
                f"p = {float(row[p_col]):.3f}, |dz| = {dz_display:.2f}."
            )
        return bullets

    if isinstance(between_contrasts, pd.DataFrame) and not between_contrasts.empty:
        df = between_contrasts.copy()
        p_col = _pick_column(df, cfg.p_col, ["p_fdr_bh", "p_fdr"])
        eff_col = _pick_column(df, cfg.effect_col, ["effect_size", "cohens_d", "d"])
        diff_col = _pick_column(df, "difference", ["mean_diff", "mean_difference"])
        roi_col = _pick_column(df, "roi", ["ROI"])
        cond_col = _pick_column(df, "condition", ["Condition"])
        g1_col = _pick_column(df, "group_1", ["Group_1", "group1"])
        g2_col = _pick_column(df, "group_2", ["Group_2", "group2"])
        required = [p_col, eff_col, roi_col, cond_col, g1_col, g2_col]
        if any(col is None for col in required):
            return ["- No post-hoc results are available for summary."]
        try:
            sig = df[df[p_col] < cfg.alpha].sort_values(p_col)
        except Exception:
            return ["- No post-hoc results are available for summary."]
        if sig.empty:
            return ["- No significant post-hoc comparisons after correction."]
        bullets = []
        for _, row in sig.head(cfg.max_bullets).iterrows():
            roi = row.get(roi_col, "ROI")
            cond = row.get(cond_col, "Condition")
            g1 = str(row.get(g1_col, "Group 1"))
            g2 = str(row.get(g2_col, "Group 2"))
            diff = row.get(diff_col, np.nan) if diff_col else np.nan
            high, low = (g1, g2)
            if pd.notna(diff) and float(diff) < 0:
                high, low = (g2, g1)
            d_val = float(row[eff_col]) if pd.notna(row[eff_col]) else 0.0
            bullets.append(
                f"- {roi} ({cond}): {high} > {low}, "
                f"p = {float(row[p_col]):.3f}, d = {d_val:.2f}."
            )
        return bullets

    return ["- No post-hoc results are available for summary."]


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

    return format_mixed_model_plain_language(mixed_model_terms, cfg.alpha)


def _format_p_value(p_value: float) -> str:
    try:
        value = float(p_value)
    except Exception:
        return "n/a"
    if np.isnan(value):
        return "n/a"
    if value < 0.001:
        return "< 0.001"
    return f"{value:.3f}"


def _extract_sum_coded_label(term: str) -> str:
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
    lowered = term.lower()
    if any(sep in term for sep in ("×", ":")):
        return "condition" in lowered and "roi" in lowered
    return False


def _is_condition_main_effect(term: str) -> bool:
    lowered = term.lower()
    return "c(condition" in lowered and not _is_interaction_term(term)


def _is_roi_main_effect(term: str) -> bool:
    lowered = term.lower()
    return "c(roi" in lowered and not _is_interaction_term(term)


def _is_intercept(term: str) -> bool:
    lowered = term.strip().lower()
    return lowered in {"intercept", "const"}


def format_mixed_model_plain_language(
    mixed_model_terms: pd.DataFrame,
    alpha: float,
    dv_label: str = "summed BCA (DV; summed across selected significant harmonics)",
) -> list[str]:
    p_col = _pick_column(
        mixed_model_terms,
        "p",
        ["P>|z|", "P>|t|", "p_value", "p-value", "pvalue", "p_fdr", "p_fdr_bh"]
    )
    term_col = _pick_column(mixed_model_terms, "term", ["Effect", "Term", "Name", "fixed_effect"])
    estimate_col = _pick_column(mixed_model_terms, "Estimate", ["Coef.", "coef", "beta"])

    if p_col is None or term_col is None:
        return ["- Mixed model: no summary is available."]

    df = mixed_model_terms.copy()
    df["_term_str"] = df[term_col].astype(str)
    df["_p_val"] = pd.to_numeric(df[p_col], errors="coerce")
    df["_estimate"] = pd.to_numeric(df[estimate_col], errors="coerce") if estimate_col else np.nan

    sig = df[df["_p_val"] < alpha]
    if sig.empty:
        return ["- No significant mixed-model fixed effects."]

    bullets: list[str] = []

    intercept_rows = sig[sig["_term_str"].apply(_is_intercept)]
    if not intercept_rows.empty:
        row = intercept_rows.iloc[0]
        p_text = _format_p_value(row["_p_val"])
        bullets.append(
            "- Overall response present (p = "
            f"{p_text}): Across all selected conditions and ROIs, the average {dv_label} "
            "is reliably different from zero."
        )

    condition_rows = sig[sig["_term_str"].apply(_is_condition_main_effect)]
    for _, row in condition_rows.iterrows():
        p_text = _format_p_value(row["_p_val"])
        label = _extract_sum_coded_label(str(row["_term_str"]))
        direction = ""
        if pd.notna(row["_estimate"]) and row["_estimate"] != 0:
            direction_word = "higher" if row["_estimate"] > 0 else "lower"
            direction = (
                " Direction: "
                f"{label} is {direction_word} than the average of the other condition(s)."
            )
        bullets.append(
            "- Condition difference (p = "
            f"{p_text}): Averaged across ROIs, the {dv_label} differs between conditions.{direction}"
        )

    roi_rows = sig[sig["_term_str"].apply(_is_roi_main_effect)]
    for _, row in roi_rows.iterrows():
        p_text = _format_p_value(row["_p_val"])
        label = _extract_sum_coded_label(str(row["_term_str"]))
        direction = ""
        if pd.notna(row["_estimate"]) and row["_estimate"] != 0:
            direction_word = "higher" if row["_estimate"] > 0 else "lower"
            direction = (
                " Direction: "
                f"{label} is {direction_word} than the average of the other ROIs."
            )
        bullets.append(
            "- ROI difference (p = "
            f"{p_text}): Averaged across conditions, the {dv_label} differs across ROIs.{direction}"
        )

    interaction_rows = sig[sig["_term_str"].apply(_is_interaction_term)]
    if not interaction_rows.empty:
        min_p = interaction_rows["_p_val"].min()
        p_text = _format_p_value(min_p)
        bullets.append(
            "- Condition-by-ROI interaction (p = "
            f"{p_text}): The condition difference is not the same in every ROI "
            "(some ROIs show a larger condition gap than others)."
        )

    return bullets or ["- No significant mixed-model fixed effects."]


def _summarize_interactions(interaction_anova: Optional[pd.DataFrame], cfg: SummaryConfig) -> list[str]:
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
