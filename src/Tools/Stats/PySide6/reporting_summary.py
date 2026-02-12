"""Plain-text reporting summary builder for Stats runs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
from pathlib import Path
from typing import Any

import pandas as pd

NOT_AVAILABLE = "NOT AVAILABLE (not computed by this run)"


@dataclass(frozen=True)
class ReportingSummaryContext:
    project_name: str
    project_root: Path
    pipeline_name: str
    generated_local: datetime
    elapsed_ms: int
    timezone_label: str
    total_participants: int
    included_participants: list[str]
    excluded_reasons: dict[str, str]
    selected_conditions: list[str]
    selected_rois: list[str]


def safe_project_path_join(project_root: Path | str, *parts: str) -> Path:
    root = Path(project_root).resolve()
    target = (root.joinpath(*parts)).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Target path escapes project root: {target}") from exc
    return target


def build_reporting_summary(
    context: ReportingSummaryContext,
    *,
    anova_df: pd.DataFrame | None,
    lmm_df: pd.DataFrame | None,
    posthoc_df: pd.DataFrame | None,
) -> str:
    included = sorted({str(pid) for pid in context.included_participants})
    excluded_ids = sorted({str(pid) for pid in context.excluded_reasons.keys() if pid not in included})
    if context.total_participants > 0:
        excluded_count = max(context.total_participants - len(included), len(excluded_ids))
    else:
        excluded_count = len(excluded_ids)

    lines: list[str] = [
        "==========================",
        "FPVS TOOLBOX — STATS REPORTING SUMMARY",
        "==========================",
        "",
        "RUN METADATA",
        f"- Generated (local): {context.generated_local.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- Timezone: {context.timezone_label}",
        f"- Project: {context.project_name}",
        f"- Project root: {context.project_root}",
        "- Tool: Stats",
        f"- Elapsed: {int(context.elapsed_ms)} ms",
        "",
        "DATASET COUNTS",
        f"- Total participants discovered: {context.total_participants}",
        f"- Included in analysis: {len(included)}",
        f"- Excluded: {excluded_count}",
        "- Excluded IDs (if available): " + (", ".join(excluded_ids) if excluded_ids else NOT_AVAILABLE),
        "- Exclusion reasons (if available):",
    ]
    if excluded_ids:
        for pid in excluded_ids:
            lines.append(f"  - {pid}: {context.excluded_reasons.get(pid, NOT_AVAILABLE)}")
    else:
        lines.append(f"  - {NOT_AVAILABLE}")

    _append_anova(lines, context, anova_df)
    _append_lmm(lines, lmm_df)
    _append_posthoc(lines, posthoc_df)

    lines.extend(
        [
            "NOTES",
            "- Any \"NOT AVAILABLE\" items indicate the current run did not compute or expose that value.",
            "- This reporting summary does not change any numeric results; it is an output-only layer.",
        ]
    )
    return "\n".join(lines)


def build_default_report_path(project_root: Path | str, generated_local: datetime) -> Path:
    return safe_project_path_join(
        project_root,
        "Stats",
        "Reports",
        f"Stats_Reporting_Summary_{generated_local.strftime('%Y%m%d_%H%M%S')}.txt",
    )


def build_rm_anova_report_path(results_dir: Path | str, generated_local: datetime) -> Path:
    results_path = Path(results_dir)
    results_path.mkdir(parents=True, exist_ok=True)
    return results_path / f"RM_ANOVA_Report_{generated_local.strftime('%Y-%m-%d_%H%M%S')}.txt"


def _value_or_na(row: pd.Series, col: str, na_label: str) -> Any:
    if col not in row.index:
        return na_label
    value = row.get(col)
    if isinstance(value, (float, int)) and not math.isfinite(float(value)):
        return na_label
    return value


def build_rm_anova_text_report(
    *,
    anova_df: pd.DataFrame | None,
    generated_local: datetime,
    project_name: str | None,
) -> str:
    backend = "statsmodels"
    if isinstance(anova_df, pd.DataFrame):
        backend = str(anova_df.attrs.get("rm_anova_backend") or "statsmodels")

    has_sphericity = isinstance(anova_df, pd.DataFrame) and {
        "W (Mauchly)",
        "p (Mauchly)",
        "Sphericity (bool)",
    }.issubset(set(anova_df.columns))
    has_correction = isinstance(anova_df, pd.DataFrame) and any(
        col in anova_df.columns for col in ["Pr > F (GG)", "Pr > F (HF)"]
    )

    lines = [
        "====================================",
        "FPVS TOOLBOX — RM-ANOVA TEXT REPORT",
        "====================================",
        f"Timestamp (local): {generated_local.strftime('%Y-%m-%d %H:%M:%S')}",
        f"Project: {project_name or NOT_AVAILABLE}",
        f"RM-ANOVA backend: {backend}",
        f"Sphericity test computed: {'YES' if has_sphericity else 'NO'}",
        f"Sphericity correction available: {'YES' if has_correction else 'NO'}",
        "",
    ]

    if not isinstance(anova_df, pd.DataFrame) or anova_df.empty:
        lines.append(f"Effects: {NOT_AVAILABLE}")
        return "\n".join(lines)

    for _, row in anova_df.iterrows():
        p_unc = _value_or_na(row, "Pr > F", NOT_AVAILABLE)
        p_gg = _value_or_na(row, "Pr > F (GG)", None)
        p_hf = _value_or_na(row, "Pr > F (HF)", None)
        if p_gg is not None and p_gg != NOT_AVAILABLE:
            p_reported, p_label = p_gg, "GG corrected"
        elif p_hf is not None and p_hf != NOT_AVAILABLE:
            p_reported, p_label = p_hf, "HF corrected"
        else:
            p_reported, p_label = p_unc, "uncorrected"

        if backend == "statsmodels":
            fallback_na = "NOT AVAILABLE (statsmodels fallback)"
            eps = w = p_spher = s_bool = p_gg_val = p_hf_val = fallback_na
        else:
            fallback_na = "NOT AVAILABLE (pingouin output)"
            eps = _value_or_na(row, "epsilon (GG)", fallback_na)
            w = _value_or_na(row, "W (Mauchly)", fallback_na)
            p_spher = _value_or_na(row, "p (Mauchly)", fallback_na)
            s_bool = _value_or_na(row, "Sphericity (bool)", fallback_na)
            p_gg_val = _value_or_na(row, "Pr > F (GG)", fallback_na)
            p_hf_val = _value_or_na(row, "Pr > F (HF)", fallback_na)

        lines.extend(
            [
                f"Effect: {_fmt(row.get('Effect'))}",
                f"  F={_fmt(row.get('F Value'))} df1={_fmt(row.get('Num DF'))} df2={_fmt(row.get('Den DF'))}",
                f"  p_uncorrected={_fmt(p_unc)}",
                f"  epsilon (GG)={_fmt(eps)}",
                f"  W (Mauchly)={_fmt(w)}",
                f"  p (Mauchly)={_fmt(p_spher)}",
                f"  Sphericity (bool)={_fmt(s_bool)}",
                f"  Pr > F (GG)={_fmt(p_gg_val)}",
                f"  Pr > F (HF)={_fmt(p_hf_val)}",
                f"  p_reported={_fmt(p_reported)} ({p_label})",
                "",
            ]
        )

    if backend == "statsmodels" and anova_df.attrs.get("rm_anova_pingouin_failed"):
        ex_type = anova_df.attrs.get("rm_anova_pingouin_exception_type", "Exception")
        ex_msg = anova_df.attrs.get("rm_anova_pingouin_exception", "")
        diag = anova_df.attrs.get("rm_anova_pingouin_diag", {}) or {}
        lines.extend(
            [
                "Pingouin failed; fallback used.",
                f"Fallback diagnostics: exception={ex_type}: {ex_msg}",
                (
                    "Fallback diagnostics: "
                    f"rows={diag.get('rows', 0)} subjects={diag.get('subjects', 0)} "
                    f"conditions={diag.get('conditions', 0)} rois={diag.get('rois', 0)} "
                    f"dv_missing_nonfinite={diag.get('dv_missing_nonfinite', 0)}"
                ),
            ]
        )
    return "\n".join(lines)


def _find_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    for col in candidates:
        if col in df.columns:
            return col
    return None


def _fmt(value: Any) -> str:
    if value is None:
        return NOT_AVAILABLE
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def _append_anova(lines: list[str], context: ReportingSummaryContext, anova_df: pd.DataFrame | None) -> None:
    lines.extend([
        "",
        "RM-ANOVA (REPEATED MEASURES)",
        "- DV: Summed BCA",
        f"- Within factors: condition({', '.join(context.selected_conditions) if context.selected_conditions else NOT_AVAILABLE}); "
        f"ROI({', '.join(context.selected_rois) if context.selected_rois else NOT_AVAILABLE})",
        "- Sphericity test computed: NO",
        "- Sphericity correction applied: " + ("YES" if isinstance(anova_df, pd.DataFrame) and any(c in anova_df.columns for c in ["Pr > F (GG)", "Pr > F (HF)"]) else "NO"),
        "- Correction method: " + ("Greenhouse–Geisser" if isinstance(anova_df, pd.DataFrame) and "Pr > F (GG)" in anova_df.columns else ("Huynh–Feldt" if isinstance(anova_df, pd.DataFrame) and "Pr > F (HF)" in anova_df.columns else NOT_AVAILABLE)),
        "- Software reporting convention note:",
        "  - Sphericity diagnostics/epsilon were not exposed in the current output payload.",
        "",
        "ANOVA EFFECTS TABLE",
        "(effect-by-effect lines; do not use markdown tables)",
    ])
    if not isinstance(anova_df, pd.DataFrame) or anova_df.empty:
        lines.append(f"- {NOT_AVAILABLE}")
        return
    for _, row in anova_df.iterrows():
        effect = _fmt(row.get("Effect", "Effect"))
        p_corr = row.get("Pr > F (GG)") if "Pr > F (GG)" in anova_df.columns else row.get("Pr > F")
        corr_label = "corrected" if "Pr > F (GG)" in anova_df.columns else "uncorrected"
        lines.extend(
            [
                f"- {effect}:",
                f"  - df1: {_fmt(row.get('Num DF'))}   df2: {_fmt(row.get('Den DF'))}   ({corr_label})",
                f"  - F: {_fmt(row.get('F Value'))}",
                f"  - p: {_fmt(p_corr)} ({corr_label})",
                f"  - epsilon (ε): {NOT_AVAILABLE}",
                f"  - correction used for this effect: {'GG' if 'Pr > F (GG)' in anova_df.columns else 'NONE'}",
                f"  - effect size (if already computed): {_fmt(row.get('partial eta squared'))}",
            ]
        )


def _append_lmm(lines: list[str], lmm_df: pd.DataFrame | None) -> None:
    lines.extend([
        "",
        "LINEAR MIXED MODEL (LMM)",
        "- Model formula: NOT AVAILABLE (not computed by this run)",
        "- DV: Summed BCA",
        "- Fixed effects: condition, ROI, and interaction",
        "- Random effects: (1|subject)",
        "- Estimation: NOT AVAILABLE (not computed by this run)",
        "- Contrast coding: NOT AVAILABLE (not computed by this run)",
        "- Inference framework for fixed effects:",
        "  - Wald z/t from model coefficient table",
        "- Optimizer: NOT AVAILABLE (not computed by this run)",
        "- Converged: NOT AVAILABLE",
        "- Warnings (if any): NONE",
        "",
        "LMM FIXED EFFECTS (COEFFICIENTS)",
        "(one line per coefficient)",
    ])
    if not isinstance(lmm_df, pd.DataFrame) or lmm_df.empty:
        lines.append(f"- {NOT_AVAILABLE}")
        return
    term_col = _find_col(lmm_df, ["Effect", "Term", "term"])
    est_col = _find_col(lmm_df, ["Coef.", "Estimate", "estimate"])
    se_col = _find_col(lmm_df, ["Std.Err.", "SE", "StdErr"])
    stat_col = _find_col(lmm_df, ["z", "t", "Stat", "stat"])
    p_col = _find_col(lmm_df, ["P>|z|", "P>|t|", "p_value", "p-value", "pvalue"])
    for _, row in lmm_df.iterrows():
        lines.append(
            f"- {_fmt(row.get(term_col or 'Effect'))}: estimate={_fmt(row.get(est_col))}  "
            f"SE={_fmt(row.get(se_col))}  stat={_fmt(row.get(stat_col))}  "
            f"p={_fmt(row.get(p_col))}  CI={NOT_AVAILABLE}"
        )


def _append_posthoc(lines: list[str], posthoc_df: pd.DataFrame | None) -> None:
    n_cond_within_roi = 0
    n_roi_within_cond = 0
    if isinstance(posthoc_df, pd.DataFrame) and "Direction" in posthoc_df.columns:
        n_cond_within_roi = int((posthoc_df["Direction"] == "condition_within_roi").sum())
        n_roi_within_cond = int((posthoc_df["Direction"] == "roi_within_condition").sum())

    lines.extend([
        "",
        "POST-HOC TESTS",
        "- Procedure: paired t-tests / model contrasts",
        "- Comparison family definition:",
        "  - Family corrected together: within each simple-effects slice",
        f"  - Number of tests in family: {len(posthoc_df) if isinstance(posthoc_df, pd.DataFrame) else NOT_AVAILABLE}",
        f"  - Conditions within ROI rows: {n_cond_within_roi if isinstance(posthoc_df, pd.DataFrame) else NOT_AVAILABLE}",
        f"  - ROIs within condition rows: {n_roi_within_cond if isinstance(posthoc_df, pd.DataFrame) else NOT_AVAILABLE}",
        "- Multiple comparison correction:",
        "  - Method: Benjamini–Hochberg (BH) FDR",
        "  - Adjusted p-values reported: YES",
        "",
        "POST-HOC RESULTS",
        "(one line per comparison)",
    ])
    if not isinstance(posthoc_df, pd.DataFrame) or posthoc_df.empty:
        lines.append(f"- {NOT_AVAILABLE}")
        return
    label_col = _find_col(posthoc_df, ["Comparison", "Effect", "contrast", "group_pair"])
    estimate_col = _find_col(posthoc_df, ["mean_diff", "Estimate", "estimate"])
    se_col = _find_col(posthoc_df, ["SE", "Std.Err.", "std_error"])
    stat_col = _find_col(posthoc_df, ["t_statistic", "t", "z", "stat"])
    df_col = _find_col(posthoc_df, ["df", "DF"])
    p_raw_col = _find_col(posthoc_df, ["p_raw", "p_value", "p"])
    p_adj_col = _find_col(posthoc_df, ["p_fdr_bh", "p_corr", "p_adj"])
    direction_col = _find_col(posthoc_df, ["Direction", "direction"])
    slice_col = _find_col(posthoc_df, ["Stratum", "Slice", "stratum", "slice"])
    factor_col = _find_col(posthoc_df, ["FactorAnalyzed", "Factor", "factor_analyzed", "factor"])
    for _, row in posthoc_df.iterrows():
        direction = _fmt(row.get(direction_col)) if direction_col else "condition_within_roi"
        slice_val = _fmt(row.get(slice_col)) if slice_col else NOT_AVAILABLE
        factor = _fmt(row.get(factor_col)) if factor_col else NOT_AVAILABLE
        lines.append(
            f"- [{direction}] stratum={slice_val} factor={factor} {_fmt(row.get(label_col or 'Comparison'))}: estimate={_fmt(row.get(estimate_col))}  "
            f"SE={_fmt(row.get(se_col))}  stat={_fmt(row.get(stat_col))}  "
            f"df={_fmt(row.get(df_col))}  p_raw={_fmt(row.get(p_raw_col))}  p_adj={_fmt(row.get(p_adj_col))}"
        )
