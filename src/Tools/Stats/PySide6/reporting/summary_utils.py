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
import re
from typing import Iterable, Optional

import numpy as np
import pandas as pd

from Tools.Stats.PySide6.common.stats_core import (
    ANOVA_XLS,
    GROUP_CONTRAST_XLS,
    LMM_BETWEEN_XLS,
    LMM_XLS,
    MULTIGROUP_GROUP_CONTRAST_LEGACY_SHEETS,
    MULTIGROUP_GROUP_CONTRAST_SHEET,
    MULTIGROUP_MIXED_MODEL_SHEET,
    POSTHOC_XLS,
    PipelineId,
)

logger = logging.getLogger("Tools.Stats")


@dataclass
class SummaryConfig:
    """Represent the SummaryConfig part of the Stats PySide6 tool."""
    alpha: float = 0.05
    min_effect: float = 0.50
    max_bullets: int = 3
    z_threshold: float = 1.64
    p_col: str = "p_fdr"
    effect_col: str = "effect_size"
    max_lines_per_direction: int = 5


@dataclass
class StatsSummaryFrames:
    """Represent the StatsSummaryFrames part of the Stats PySide6 tool."""
    single_posthoc: Optional[pd.DataFrame] = None
    between_contrasts: Optional[pd.DataFrame] = None
    harmonic_results: Optional[pd.DataFrame] = None
    anova_terms: Optional[pd.DataFrame] = None
    mixed_model_terms: Optional[pd.DataFrame] = None
    pipeline_id: Optional[PipelineId] = None


def build_summary_from_files(stats_folder: Path, config: SummaryConfig) -> str:
    """
    Read existing Excel outputs in `stats_folder` and return a short summary.

    The function is fail-safe: any file-read or parsing issues result in
    section-specific fallback messages rather than exceptions.
    """

    def _safe_read(path: Path, sheet: str) -> Optional[pd.DataFrame]:
        """Handle the safe read step for the Stats PySide6 workflow."""
        if not path.is_file():
            return None
        try:
            return pd.read_excel(path, sheet_name=sheet)
        except Exception:
            return None

    def _safe_read_any(path: Path, sheets: list[str]) -> Optional[pd.DataFrame]:
        """Handle the safe read any step for the Stats PySide6 workflow."""
        for sheet in sheets:
            df = _safe_read(path, sheet)
            if df is not None:
                return df
        return None

    single_posthoc = _safe_read_any(stats_folder / POSTHOC_XLS, ["Combined", "Post-hoc Results"])
    between_contrasts = _safe_read_any(
        stats_folder / GROUP_CONTRAST_XLS,
        [MULTIGROUP_GROUP_CONTRAST_SHEET, *MULTIGROUP_GROUP_CONTRAST_LEGACY_SHEETS],
    )
    single_lmm = _safe_read(stats_folder / LMM_XLS, MULTIGROUP_MIXED_MODEL_SHEET)
    frames = StatsSummaryFrames(
        single_posthoc=single_posthoc,
        between_contrasts=between_contrasts,
        mixed_model_terms=single_lmm,
    )

    frames.anova_terms = _safe_read(stats_folder / ANOVA_XLS, "RM-ANOVA Table")

    candidate_lmm_between = _safe_read(stats_folder / LMM_BETWEEN_XLS, MULTIGROUP_MIXED_MODEL_SHEET)
    single_sources_present = any(
        df is not None for df in (frames.single_posthoc, single_lmm, frames.anova_terms)
    )
    between_sources_present = any(
        df is not None for df in (frames.between_contrasts, candidate_lmm_between)
    )
    if between_sources_present and not single_sources_present:
        frames.pipeline_id = PipelineId.BETWEEN
        frames.mixed_model_terms = candidate_lmm_between
    elif single_sources_present:
        frames.pipeline_id = PipelineId.SINGLE
        frames.mixed_model_terms = single_lmm
    elif candidate_lmm_between is not None:
        frames.mixed_model_terms = candidate_lmm_between

    return build_summary_from_frames(frames, config)


def build_summary_from_frames(frames: StatsSummaryFrames, config: SummaryConfig) -> str:
    """
    Produce a short, human-readable summary based on in-memory DataFrames.
    Never raises; on missing/invalid data it emits 'no results' lines for
    the affected sections.
    """

    between_mode = frames.pipeline_id is PipelineId.BETWEEN
    posthoc_empty_line = (
        "- No group contrasts are available for summary."
        if between_mode
        else "- No post-hoc results are available for summary."
    )

    try:
        anova_lines = _summarize_rm_anova(frames.anova_terms, config)
    except Exception:
        anova_lines = ["- No RM-ANOVA results are available for summary."]

    try:
        posthoc_lines = _summarize_posthocs(
            frames.single_posthoc, frames.between_contrasts, config
        )
    except Exception:
        posthoc_lines = [posthoc_empty_line]
    if between_mode and posthoc_lines == ["- No post-hoc results are available for summary."]:
        posthoc_lines = [posthoc_empty_line]

    try:
        mixed_lines = _summarize_mixed_model(
            frames.mixed_model_terms,
            config,
            between_mode=between_mode,
        )
    except Exception:
        mixed_lines = ["- Mixed model: NOT AVAILABLE (not computed by this run)."]

    try:
        interaction_lines = _summarize_interactions(frames.anova_terms, config)
    except Exception:
        interaction_lines = []

    if between_mode:
        parts = [
            f"--- Summary (\u03b1 = {config.alpha:.2f}, FDR correction: Benjamini-Hochberg) ---",
            "",
            "Mixed model:",
            *(mixed_lines or ["- Mixed model: NOT AVAILABLE (not computed by this run)."]),
            "",
            "Group contrasts:",
            *(posthoc_lines or ["- No significant group contrasts after correction."]),
            "",
            "Please see the newly generated Excel files in the '3 - Statistical Analysis' folder for complete results. Consult your",
            "favorite statistics expert (for example, ChatGPT) for help interpreting these findings.",
        ]
        return "\n".join(parts)

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
        *(mixed_lines or ["- Mixed model: NOT AVAILABLE (not computed by this run)."]),
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
    """Handle the to dataframe step for the Stats PySide6 workflow."""
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
    """Handle the build summary frames from results step for the Stats PySide6 workflow."""
    frames = StatsSummaryFrames(pipeline_id=pipeline_id)
    if pipeline_id is PipelineId.SINGLE:
        frames.single_posthoc = to_dataframe(single_posthoc)
        frames.anova_terms = to_dataframe(rm_anova_results)
        frames.mixed_model_terms = to_dataframe(mixed_model_results)
    elif pipeline_id is PipelineId.BETWEEN:
        frames.between_contrasts = to_dataframe(between_contrasts)
        frames.mixed_model_terms = to_dataframe(between_mixed_model_results)
    frames.harmonic_results = to_dataframe(harmonic_results)
    return frames


def _fmt_p(value: float) -> str:
    """Handle the fmt p step for the Stats PySide6 workflow."""
    if value != 0.0 and abs(value) < 0.001:
        return f"{value:.3e}"
    return f"{value:.6g}"


def format_rm_anova_summary(df: pd.DataFrame, alpha: float) -> str:
    """Handle the format rm anova summary step for the Stats PySide6 workflow."""
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
    """Handle the build rm anova output step for the Stats PySide6 workflow."""
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
    """Handle the build between anova output step for the Stats PySide6 workflow."""
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
    """Handle the pick column step for the Stats PySide6 workflow."""
    for name in (preferred, *fallbacks):
        if name in df.columns:
            return name
    return None


def _select_rm_anova_p(row: pd.Series) -> tuple[float, str] | None:
    """Handle the select rm anova p step for the Stats PySide6 workflow."""
    for col, label in (("Pr > F (GG)", "GG corrected"), ("Pr > F (HF)", "HF corrected"), ("Pr > F", "uncorrected")):
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
    """Handle the normalize effect name step for the Stats PySide6 workflow."""
    return " ".join(str(raw).strip().lower().split())


def _summarize_rm_anova(anova_terms: Optional[pd.DataFrame], cfg: SummaryConfig) -> list[str]:
    """Handle the summarize rm anova step for the Stats PySide6 workflow."""
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
    """Handle the summarize posthocs step for the Stats PySide6 workflow."""
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
    """Handle the summarize single posthocs by direction step for the Stats PySide6 workflow."""
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

    # Historically the GUI summary only emitted `roi_within_condition`, which made
    # the text log incomplete vs the Excel export. We now report both directions.
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
    """Handle the summarize between step for the Stats PySide6 workflow."""
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


def _summarize_mixed_model(
    mixed_model_terms: Optional[pd.DataFrame],
    cfg: SummaryConfig,
    *,
    between_mode: bool = False,
) -> list[str]:
    """Handle the summarize mixed model step for the Stats PySide6 workflow."""
    if mixed_model_terms is None or not isinstance(mixed_model_terms, pd.DataFrame) or mixed_model_terms.empty:
        return ["- Mixed model: NOT AVAILABLE (not computed by this run)."]

    return format_mixed_model_plain_language(
        mixed_model_terms,
        cfg.alpha,
        between_mode=between_mode,
    )


def _format_p_value(p_value: float) -> str:
    """Handle the format p value step for the Stats PySide6 workflow."""
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
    """Handle the direction word step for the Stats PySide6 workflow."""
    if pd.isna(coef):
        return "equal"
    if coef < 0:
        return "lower"
    if coef > 0:
        return "higher"
    return "equal"


def _extract_sum_coded_label(term: str) -> str:
    """Handle the extract sum coded label step for the Stats PySide6 workflow."""
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
    """Handle the is interaction term step for the Stats PySide6 workflow."""
    lowered = term.lower()
    if any(sep in term for sep in ("×", ":")):
        return "condition" in lowered and "roi" in lowered
    return False


def _is_condition_main_effect(term: str) -> bool:
    """Handle the is condition main effect step for the Stats PySide6 workflow."""
    lowered = term.lower()
    return "c(condition" in lowered and not _is_interaction_term(term)


def _is_roi_main_effect(term: str) -> bool:
    """Handle the is roi main effect step for the Stats PySide6 workflow."""
    lowered = term.lower()
    return "c(roi" in lowered and not _is_interaction_term(term)


def _is_intercept(term: str) -> bool:
    """Handle the is intercept step for the Stats PySide6 workflow."""
    lowered = term.strip().lower()
    return lowered in {"intercept", "const"}


def format_mixed_model_plain_language(
    mixed_model_terms: pd.DataFrame,
    alpha: float,
    *,
    between_mode: bool = False,
) -> list[str]:
    """Handle the format mixed model plain language step for the Stats PySide6 workflow."""
    p_col = _pick_column(mixed_model_terms, "p", ["P>|z|", "p", "pvalue", "p_value"])
    raw_term_col = _pick_column(mixed_model_terms, "term", ["Effect (raw)", "Effect", "Term"])
    readable_term_col = _pick_column(mixed_model_terms, "readable_term", ["Effect (readable)"])
    if raw_term_col is None and readable_term_col is not None:
        raw_term_col = readable_term_col
    estimate_col = _pick_column(mixed_model_terms, "Estimate", ["Coef.", "Estimate", "coef"])
    attrs = mixed_model_terms.attrs if isinstance(mixed_model_terms, pd.DataFrame) else {}

    if between_mode and attrs.get("lmm_fit_supported") is False:
        status_message = attrs.get("lmm_fit_status_message", "Supported multigroup LMM blocked.")
        contract_bits = [
            attrs.get("lmm_fixed_effects_summary"),
            attrs.get("lmm_random_effects_summary"),
            attrs.get("lmm_estimation_summary"),
            attrs.get("lmm_coding_summary"),
        ]
        bullets = [f"- {status_message}"]
        contract_text = "; ".join(str(bit) for bit in contract_bits if bit)
        if contract_text:
            bullets.append(f"- Attempted contract: {contract_text}.")
        return bullets

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
    if between_mode:
        status_label = attrs.get("lmm_fit_status_label")
        status_message = attrs.get("lmm_fit_status_message")
        contract_bits = [
            attrs.get("lmm_fixed_effects_summary"),
            attrs.get("lmm_random_effects_summary"),
            attrs.get("lmm_estimation_summary"),
            attrs.get("lmm_coding_summary"),
        ]
        if status_label or status_message:
            bullets.append(
                "- Fit status: "
                f"{status_label or 'NOT AVAILABLE'}"
                f" ({status_message or 'NOT AVAILABLE'})."
            )
        contract_text = "; ".join(str(bit) for bit in contract_bits if bit)
        if contract_text:
            bullets.append(f"- Contract: {contract_text}.")
    bullets.append("- Inference for fixed effects: Wald z-tests (normal approximation).")
    sig = df[df["_p_val"] < alpha]
    if sig.empty:
        return bullets

    condition_pattern = re.compile(r"^C\(condition\s*,\s*Sum\)\[S\.(?P<level>.+)\]$")
    roi_pattern = re.compile(r"^C\(roi\s*,\s*Sum\)\[S\.(?P<level>.+)\]$")

    def _extract_level(row: pd.Series, match_obj: re.Match[str] | None) -> str:
        """Handle the extract level step for the Stats PySide6 workflow."""
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


def _summarize_interactions(interaction_anova: Optional[pd.DataFrame], cfg: SummaryConfig) -> list[str]:
    """Handle the summarize interactions step for the Stats PySide6 workflow."""
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
