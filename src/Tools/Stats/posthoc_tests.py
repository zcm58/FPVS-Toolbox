# posthoc_tests.py
# -*- coding: utf-8 -*-
"""Utility functions for post-hoc comparisons after repeated measures ANOVA.

This module implements paired comparisons across levels of a factor
(e.g., conditions or ROIs) using paired t-tests with multiple comparison
corrections. It is designed to be called after an RM-ANOVA to pinpoint
which specific levels differ from each other.

The functions return a detailed text log explaining the results so that
the user can easily interpret the findings in a publication-ready format.
"""

from itertools import combinations

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.multitest import multipletests


def run_posthoc_pairwise_tests(data, dv_col, factor_col, subject_col,
                               correction="holm", alpha=0.05):
    """Run pairwise repeated-measures t-tests.

    Parameters
    ----------
    data : pandas.DataFrame
        Long-format data containing one row per observation with columns for
        subject ID, the dependent variable, and a within-subject factor.
    dv_col : str
        Name of the dependent variable column.
    factor_col : str
        Name of the column representing the factor to compare (e.g., ``condition``
        or ``roi``).
    subject_col : str
        Name of the subject identifier column.
    correction : str, optional
        Method for p-value correction. Any method accepted by
        ``statsmodels.stats.multitest.multipletests`` is valid. Default ``"holm"``.
    alpha : float, optional
        Significance level used when interpreting corrected p-values.

    Returns
    -------
    tuple
        (log_output: str, results_df: pandas.DataFrame)
    """
    output_lines = [
        "============================================================",
        "              Post-hoc Pairwise Comparisons",
        "============================================================",
        f"Factor analyzed: '{factor_col}'",
        f"Correction method: {correction}",
        f"Significance level: alpha = {alpha}\n",
    ]

    if factor_col not in data.columns or dv_col not in data.columns or subject_col not in data.columns:
        output_lines.append("Required columns missing from data. Cannot run post-hoc tests.")
        return "\n".join(output_lines), pd.DataFrame()

    levels = data[factor_col].dropna().unique()
    if len(levels) < 2:
        output_lines.append("Not enough levels for pairwise comparisons.")
        return "\n".join(output_lines), pd.DataFrame()

    comparisons = list(combinations(levels, 2))
    test_stats = []
    p_values = []
    n_pairs = []

    for level_a, level_b in comparisons:
        df_a = data[data[factor_col] == level_a]
        df_b = data[data[factor_col] == level_b]
        merged = pd.merge(
            df_a[[subject_col, dv_col]],
            df_b[[subject_col, dv_col]],
            on=subject_col,
            suffixes=("_a", "_b"),
        )
        pair_count = len(merged)
        if pair_count < 3:
            output_lines.append(f"Comparison {level_a} vs {level_b}: insufficient paired data (N={pair_count}).")
            test_stats.append(np.nan)
            p_values.append(np.nan)
            n_pairs.append(pair_count)
            continue
        t_stat, p_val = stats.ttest_rel(merged[f"{dv_col}_a"], merged[f"{dv_col}_b"])
        test_stats.append(t_stat)
        p_values.append(p_val)
        n_pairs.append(pair_count)

    # Correct for multiple comparisons (ignore NaNs)
    valid_idx = [i for i, p in enumerate(p_values) if not np.isnan(p)]
    corrected_p = [np.nan] * len(p_values)
    significant = [False] * len(p_values)
    if valid_idx:
        pvals = [p_values[i] for i in valid_idx]
        reject, pvals_corr, _, _ = multipletests(pvals, alpha=alpha, method=correction)
        for i, p_corr, rej in zip(valid_idx, pvals_corr, reject):
            corrected_p[i] = p_corr
            significant[i] = rej

    results_records = []
    for idx, (level_a, level_b) in enumerate(comparisons):
        t_stat = test_stats[idx]
        p_val = p_values[idx]
        p_corr = corrected_p[idx]
        sig = significant[idx]
        output_lines.append(f"--- {level_a} vs {level_b} ---")
        if np.isnan(p_val):
            output_lines.append("  Skipped: insufficient paired observations.\n")
            continue
        output_lines.append(f"  t({n_pairs[idx]-1}) = {t_stat:.3f}")
        output_lines.append(f"  Raw p-value = {p_val:.4f}")
        output_lines.append(f"  Corrected p-value = {p_corr:.4f}")
        if sig:
            output_lines.append("  FINDING: SIGNIFICANT DIFFERENCE after correction.\n")
        else:
            output_lines.append("  Finding: No significant difference after correction.\n")
        results_records.append({
            "Level_A": level_a,
            "Level_B": level_b,
            "N_Pairs": n_pairs[idx],
            "t_statistic": t_stat,
            "p_value": p_val,
            "p_value_corrected": p_corr,
            "Significant": sig,
        })

    output_lines.append("============================================================")
    results_df = pd.DataFrame(results_records)
    return "\n".join(output_lines), results_df


def run_interaction_posthocs(data, dv_col, roi_col, condition_col, subject_col,
                             correction="holm", alpha=0.05):
    """Run condition-wise post-hoc tests separately for each ROI.

    This helper performs pairwise comparisons of the ``condition`` factor
    within each ROI level. It simply calls :func:`run_posthoc_pairwise_tests`
    on subsets of ``data`` corresponding to each ROI so that activity from
    different brain regions is never combined during a comparison.

    Parameters
    ----------
    data : pandas.DataFrame
        Long-format table with columns for the dependent variable, ROI,
        condition and subject identifier.
    dv_col : str
        Name of the dependent variable column.
    roi_col : str
        Column name indicating the ROI/brain region.
    condition_col : str
        Column name for the experimental condition factor.
    subject_col : str
        Column identifying subjects.
    correction : str, optional
        Method for p-value correction. Passed through to
        :func:`run_posthoc_pairwise_tests`.
    alpha : float, optional
        Significance level used when interpreting corrected p-values.

    Returns
    -------
    tuple
        (log_output: str, results_df: pandas.DataFrame)
    """

    summary_lines = []
    output_lines = []

    header_main = [
        "============================================================",
        "         Post-hoc Comparisons: Condition by ROI",
        "============================================================\n",
    ]

    if any(col not in data.columns for col in [dv_col, roi_col, condition_col, subject_col]):
        output_lines.append("Required columns missing from data. Cannot run interaction post-hocs.")
        output_lines = header_main + output_lines
        return "\n".join(output_lines), pd.DataFrame()

    unique_rois = data[roi_col].dropna().unique()
    results_list = []

    for roi in unique_rois:
        output_lines.append(f"=== ROI: {roi} ===")
        roi_subset = data[data[roi_col] == roi]
        roi_text, roi_df = run_posthoc_pairwise_tests(
            data=roi_subset,
            dv_col=dv_col,
            factor_col=condition_col,
            subject_col=subject_col,
            correction=correction,
            alpha=alpha,
        )
        roi_text_indented = "\n".join([f"  {line}" for line in roi_text.splitlines()])
        output_lines.append(roi_text_indented)
        if roi_df is not None and not roi_df.empty:
            roi_df = roi_df.assign(ROI=roi)
            results_list.append(roi_df)
            sig_rows = roi_df[roi_df["Significant"]]
            for _, row in sig_rows.iterrows():
                summary_lines.append(
                    f"ROI {roi}: {row['Level_A']} vs {row['Level_B']} "
                    f"(t={row['t_statistic']:.3f}, p={row['p_value_corrected']:.4f})"
                )

    results_df = pd.concat(results_list, ignore_index=True) if results_list else pd.DataFrame()
    output_lines.append("============================================================")

    summary_section = [
        "============================================================",
        "        SUMMARY OF SIGNIFICANT FINDINGS",
        "============================================================",
    ]
    if summary_lines:
        summary_section.extend(summary_lines)
    else:
        summary_section.append("No significant differences found.")
    summary_section.append("")

    output_lines = summary_section + header_main + output_lines
    return "\n".join(output_lines), results_df
