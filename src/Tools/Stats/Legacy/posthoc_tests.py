# posthoc_tests.py
# -*- coding: utf-8 -*-
"""
Utility functions for post-hoc comparisons after repeated measures ANOVA or LME.

What’s new:
- Paired comparisons now report Cohen's dz and 95% CI of the mean difference.
- A normality check (Shapiro on paired differences) is logged (informational only).
- Interaction post-hocs keep Benjamini–Hochberg FDR control within each ROI.
- Planned contrasts helper: Category vs average(Color conditions) within ROI(s).

Functions
---------
run_posthoc_pairwise_tests(...)
run_interaction_posthocs(...)
run_planned_contrasts_category_vs_color(...)
"""

from itertools import combinations
from typing import Iterable, Tuple, Optional, Literal

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.multitest import multipletests


def _paired_effect_size_and_ci(diff: np.ndarray, alpha: float = 0.05) -> Tuple[float, float, float]:
    """Return (dz, ci_low, ci_high) for paired differences."""
    diff = np.asarray(diff, dtype=float)
    diff = diff[~np.isnan(diff)]
    if diff.size < 3:
        return np.nan, np.nan, np.nan
    dz = diff.mean() / diff.std(ddof=1)
    se = diff.std(ddof=1) / np.sqrt(diff.size)
    ci_low, ci_high = stats.t.interval(1 - alpha, df=diff.size - 1, loc=diff.mean(), scale=se)
    return dz, ci_low, ci_high


def run_posthoc_pairwise_tests(
    data: pd.DataFrame,
    dv_col: str,
    factor_col: str,
    subject_col: str,
    correction: str = "fdr_bh",
    alpha: float = 0.05,
):
    """Paired, within-subject t-tests across all level pairs of `factor_col`."""
    output_lines = [
        "============================================================",
        "              Post-hoc Pairwise Comparisons",
        "============================================================",
        f"Factor analyzed: '{factor_col}'",
        f"Correction method: {correction}",
        f"Significance level: alpha = {alpha}\n",
    ]

    for c in (factor_col, dv_col, subject_col):
        if c not in data.columns:
            output_lines.append(f"Required column '{c}' missing. Cannot run post-hoc tests.")
            return "\n".join(output_lines), pd.DataFrame()

    levels = list(data[factor_col].dropna().unique())
    if len(levels) < 2:
        output_lines.append("Not enough levels for pairwise comparisons.")
        return "\n".join(output_lines), pd.DataFrame()

    comparisons = list(combinations(levels, 2))
    test_stats, p_values, n_pairs = [], [], []
    dz_list, mdiff_list, ci_lo_list, ci_hi_list, norm_pvals = [], [], [], [], []

    for level_a, level_b in comparisons:
        df_a = data[data[factor_col] == level_a][[subject_col, dv_col]]
        df_b = data[data[factor_col] == level_b][[subject_col, dv_col]]
        merged = pd.merge(df_a, df_b, on=subject_col, suffixes=("_a", "_b"))
        pair_count = len(merged)

        if pair_count < 3:
            output_lines.append(f"Comparison {level_a} vs {level_b}: insufficient paired data (N={pair_count}).")
            test_stats.append(np.nan); p_values.append(np.nan); n_pairs.append(pair_count)
            dz_list.append(np.nan); mdiff_list.append(np.nan); ci_lo_list.append(np.nan); ci_hi_list.append(np.nan); norm_pvals.append(np.nan)
            continue

        # Paired t-test
        t_stat, p_val = stats.ttest_rel(merged[f"{dv_col}_a"], merged[f"{dv_col}_b"])
        test_stats.append(t_stat); p_values.append(p_val); n_pairs.append(pair_count)

        # Effect size + CI
        diff = merged[f"{dv_col}_a"] - merged[f"{dv_col}_b"]
        dz, ci_low, ci_high = _paired_effect_size_and_ci(diff, alpha=alpha)
        dz_list.append(dz); mdiff_list.append(float(diff.mean())); ci_lo_list.append(ci_low); ci_hi_list.append(ci_high)

        # Normality (report only)
        try:
            sh_W, sh_p = stats.shapiro(diff.astype(float))
        except Exception:
            sh_p = np.nan
        norm_pvals.append(sh_p)

    # Multiple-comparison correction across valid p's
    valid_idx = [i for i, p in enumerate(p_values) if np.isfinite(p)]
    corrected_p = [np.nan] * len(p_values)
    significant = [False] * len(p_values)
    if valid_idx:
        pvals = [p_values[i] for i in valid_idx]
        reject, pvals_corr, _, _ = multipletests(pvals, alpha=alpha, method=correction)
        for i, p_corr, rej in zip(valid_idx, pvals_corr, reject):
            corrected_p[i] = p_corr; significant[i] = bool(rej)

    # Build results
    records = []
    for idx, (level_a, level_b) in enumerate(comparisons):
        records.append({
            "Level_A": level_a,
            "Level_B": level_b,
            "N_Pairs": n_pairs[idx],
            "t_statistic": test_stats[idx],
            "p_value": p_values[idx],
            "p_fdr_bh": corrected_p[idx],
            "Significant": significant[idx],
            "mean_diff": mdiff_list[idx],
            "ci95_low": ci_lo_list[idx],
            "ci95_high": ci_hi_list[idx],
            "cohens_dz": dz_list[idx],
            "shapiro_p_diff": norm_pvals[idx],
        })

    results_df = pd.DataFrame.from_records(records)

    # Human-readable log
    for idx, (level_a, level_b) in enumerate(comparisons):
        output_lines.append(f"--- {level_a} vs {level_b} ---")
        if np.isnan(p_values[idx]):
            output_lines.append("  Skipped: insufficient paired observations.\n")
            continue
        output_lines.append(f"  t({n_pairs[idx]-1}) = {test_stats[idx]:.3f}")
        output_lines.append(f"  Raw p-value = {p_values[idx]:.4f}  |  FDR-adjusted p (BH) = {corrected_p[idx]:.4f}")
        output_lines.append(f"  Mean diff (A-B) = {mdiff_list[idx]:.4f}  "
                            f"95% CI [{ci_lo_list[idx]:.4f}, {ci_hi_list[idx]:.4f}]  "
                            f"Cohen's dz = {dz_list[idx]:.3f}")
        if np.isfinite(norm_pvals[idx]):
            output_lines.append(f"  Normality of paired diffs (Shapiro p) = {norm_pvals[idx]:.3f} (report only)")
        output_lines.append("  " + ("FINDING: SIGNIFICANT AFTER CORRECTION.\n" if significant[idx] else "Finding: Not significant after correction.\n"))

    output_lines.append("============================================================")
    return "\n".join(output_lines), results_df


def run_interaction_posthocs(
    data: pd.DataFrame,
    dv_col: str,
    roi_col: str,
    condition_col: str,
    subject_col: str,
    correction: str = "fdr_bh",
    alpha: float = 0.05,
    direction: Literal["condition_within_roi", "roi_within_condition", "both"] = "both",
):
    """
    Run simple-effects post-hocs for a Condition×ROI interaction.

    Direction modes:
      - condition_within_roi: pairwise condition comparisons within each ROI
      - roi_within_condition: pairwise ROI comparisons within each condition
      - both (default): run and concatenate both directions

    Benjamini–Hochberg FDR correction is applied within each slice family.
    """
    header = [
        "============================================================",
        "         Post-hoc Comparisons: Condition by ROI",
        "============================================================\n",
    ]
    lines = []
    results_list = []

    for col in (dv_col, roi_col, condition_col, subject_col):
        if col not in data.columns:
            lines.append(f"Required column '{col}' missing. Cannot run interaction post-hocs.")
            return "\n".join(header + lines), pd.DataFrame()

    rois = list(data[roi_col].dropna().unique())
    if direction not in {"condition_within_roi", "roi_within_condition", "both"}:
        lines.append(f"Invalid direction '{direction}'.")
        return "\n".join(header + lines), pd.DataFrame()

    conditions = list(data[condition_col].dropna().unique())
    summary: list[str] = []

    if direction in ("condition_within_roi", "both"):
        lines.extend([
            "",
            "Conditions within each ROI",
            "------------------------------------------------------------",
        ])
        for roi in rois:
            lines.append(f"=== ROI: {roi} ===")
            roi_subset = data[data[roi_col] == roi]
            txt, df_res = run_posthoc_pairwise_tests(
                data=roi_subset,
                dv_col=dv_col,
                factor_col=condition_col,
                subject_col=subject_col,
                correction=correction,
                alpha=alpha,
            )
            lines.extend(["  " + ln for ln in txt.splitlines()])
            if df_res is not None and not df_res.empty:
                df_res = df_res.assign(
                    Direction="condition_within_roi",
                    Slice=roi,
                    Factor=condition_col,
                    ROI=roi,
                    Condition=np.nan,
                )
                results_list.append(df_res)
                for _, row in df_res[df_res["Significant"]].iterrows():
                    summary.append(
                        "[Conditions within ROI] "
                        f"ROI {roi}: {row['Level_A']} vs {row['Level_B']} "
                        f"(t={row['t_statistic']:.3f}, p={row['p_fdr_bh']:.4f}, dz={row['cohens_dz']:.2f})"
                    )

    if direction in ("roi_within_condition", "both"):
        lines.extend([
            "",
            "ROIs within each condition",
            "------------------------------------------------------------",
        ])
        for cond in conditions:
            lines.append(f"=== Condition: {cond} ===")
            cond_subset = data[data[condition_col] == cond]
            txt, df_res = run_posthoc_pairwise_tests(
                data=cond_subset,
                dv_col=dv_col,
                factor_col=roi_col,
                subject_col=subject_col,
                correction=correction,
                alpha=alpha,
            )
            lines.extend(["  " + ln for ln in txt.splitlines()])
            if df_res is not None and not df_res.empty:
                df_res = df_res.assign(
                    Direction="roi_within_condition",
                    Slice=cond,
                    Factor=roi_col,
                    ROI=np.nan,
                    Condition=cond,
                )
                results_list.append(df_res)
                for _, row in df_res[df_res["Significant"]].iterrows():
                    summary.append(
                        "[ROIs within condition] "
                        f"Condition {cond}: {row['Level_A']} vs {row['Level_B']} "
                        f"(t={row['t_statistic']:.3f}, p={row['p_fdr_bh']:.4f}, dz={row['cohens_dz']:.2f})"
                    )

    # Build final outputs
    results_df = pd.concat(results_list, ignore_index=True) if results_list else pd.DataFrame()
    lines.append("============================================================")

    # Summary block (family-wise correction already applied within each ROI)
    summary_block = [
        "============================================================",
        "        SUMMARY OF SIGNIFICANT FINDINGS",
        "============================================================",
    ]
    summary_block.extend(summary if summary else ["No significant differences found.", ""])
    report = "\n".join(summary_block + header + lines)
    return report, results_df


def run_planned_contrasts_category_vs_color(
    data: pd.DataFrame,
    dv_col: str,
    roi_col: str,
    condition_col: str,
    subject_col: str,
    category_condition: str = "Green Fruit vs Green Veg",
    color_conditions: Iterable[str] = ("Green Veg vs Red Veg", "Red Fruit vs Green Fruit"),
    rois: Optional[Iterable[str]] = None,
    alpha: float = 0.05,
    correction: str = "holm",
    one_tailed_greater: bool = False,
):
    """
    Planned contrast: Category minus the average of Color (within ROI).

    Returns (text_log, results_df) where results_df has columns:
    ['ROI','N','mean_diff','ci95_low','ci95_high','cohens_dz','t','p_raw','p_corr','Significant']
    """
    lines = [
        "============================================================",
        "      Planned Contrast: Category vs Average(Color) by ROI",
        "============================================================",
        f"Category = '{category_condition}' | Colors = {tuple(color_conditions)}",
    ]
    needed = {dv_col, roi_col, condition_col, subject_col}
    if not needed.issubset(set(data.columns)):
        lines.append("Required columns missing. Cannot run planned contrasts.")
        return "\n".join(lines), pd.DataFrame()

    all_rois = list(data[roi_col].dropna().unique()) if rois is None else list(rois)
    out_rows = []

    for roi in all_rois:
        d = data[data[roi_col] == roi]
        wide = d.pivot_table(index=subject_col, columns=condition_col, values=dv_col, aggfunc="mean")
        needed_cols = [category_condition, *color_conditions]
        if not set(needed_cols).issubset(set(wide.columns)):
            lines.append(f"ROI {roi}: Missing required conditions; skipping.")
            continue

        delta = wide[category_condition] - wide[list(color_conditions)].mean(axis=1)
        delta = delta.dropna()
        if delta.size < 3:
            lines.append(f"ROI {roi}: insufficient paired data (N={delta.size}); skipping.")
            continue

        # One-sample t-test against 0 (paired by construction)
        alt = "greater" if one_tailed_greater else "two-sided"
        t, p = stats.ttest_1samp(delta, popmean=0.0, alternative=alt)
        dz, ci_low, ci_high = _paired_effect_size_and_ci(delta.values, alpha=alpha)

        out_rows.append({
            "ROI": roi,
            "N": int(delta.size),
            "mean_diff": float(delta.mean()),
            "ci95_low": ci_low,
            "ci95_high": ci_high,
            "cohens_dz": dz,
            "t": float(t),
            "p_raw": float(p),
        })

    res = pd.DataFrame(out_rows)
    if res.empty:
        lines.append("No ROI produced analyzable data for the planned contrast.")
        return "\n".join(lines), res

    # Holm correction across ROIs (small family)
    rej, p_corr, _, _ = multipletests(res["p_raw"].values, alpha=alpha, method=correction)
    res["p_corr"] = p_corr
    res["Significant"] = rej

    # Log
    for _, r in res.iterrows():
        lines.append(
            f"ROI {r['ROI']}: Δ=Category−Color_avg = {r['mean_diff']:.4f} "
            f"[95% CI {r['ci95_low']:.4f}, {r['ci95_high']:.4f}], dz={r['cohens_dz']:.2f}, "
            f"t({int(r['N'])-1})={r['t']:.3f}, p_corr={r['p_corr']:.4f} "
            + ("**SIGNIFICANT**" if r['Significant'] else "ns")
        )
    lines.append("============================================================")
    return "\n".join(lines), res
