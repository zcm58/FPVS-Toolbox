"""Baseline-vs-zero one-sample tests for condition×ROI cells."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable
from typing import Literal

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.multitest import multipletests

from Tools.Stats.reporting.stats_export import _auto_format_and_write_excel


def _one_sample_ttest(
    values: np.ndarray,
    *,
    alternative: Literal["greater", "two-sided"],
) -> tuple[float, float]:
    """Return t-statistic and p-value with SciPy compatibility fallback."""
    try:
        result = stats.ttest_1samp(values, popmean=0.0, alternative=alternative)
        return float(result.statistic), float(result.pvalue)
    except TypeError:
        t_stat, p_two_sided = stats.ttest_1samp(values, popmean=0.0)
        if alternative == "two-sided":
            return float(t_stat), float(p_two_sided)
        # Fallback when SciPy lacks `alternative`: convert two-sided p to one-sided.
        # For H1: mean > 0, p_one = p_two/2 if t>0, else 1 - p_two/2.
        p_one_sided = p_two_sided / 2.0 if t_stat > 0 else 1.0 - (p_two_sided / 2.0)
        return float(t_stat), float(p_one_sided)


def run_baseline_vs_zero_tests(
    data: pd.DataFrame,
    dv_col: str,
    subject_col: str,
    condition_col: str,
    roi_col: str,
    alpha: float = 0.05,
    alternative: Literal["greater", "two-sided"] = "greater",
    correction: str = "fdr_bh",
    correction_scope: Literal["global", "within_roi"] = "global",
) -> tuple[str, pd.DataFrame]:
    """Run one-sample t-tests versus zero for each condition×ROI cell."""
    required_cols = [dv_col, subject_col, condition_col, roi_col]
    missing_cols = [col for col in required_cols if col not in data.columns]
    if missing_cols:
        raise ValueError(f"Missing required columns: {missing_cols}")

    key_counts = (
        data.groupby([subject_col, condition_col, roi_col], dropna=False)
        .size()
        .reset_index(name="count")
    )
    dupes = key_counts[key_counts["count"] > 1]
    if not dupes.empty:
        lines = [
            f"({row[subject_col]!r}, {row[condition_col]!r}, {row[roi_col]!r}) -> {int(row['count'])}"
            for _, row in dupes.head(10).iterrows()
        ]
        raise ValueError(
            "Duplicate rows detected for participant-level keys; expected one row per "
            f"({subject_col}, {condition_col}, {roi_col}). Examples: " + "; ".join(lines)
        )

    rows: list[dict[str, object]] = []
    grouped = data.groupby([condition_col, roi_col], dropna=False, sort=True)
    for (condition, roi), sub_df in grouped:
        values = pd.to_numeric(sub_df[dv_col], errors="coerce").dropna().to_numpy(dtype=float)
        n = int(values.size)
        mean = float(np.mean(values)) if n else np.nan
        sd = float(np.std(values, ddof=1)) if n >= 2 else np.nan

        row: dict[str, object] = {
            "condition": condition,
            "roi": roi,
            "N": n,
            "mean": mean,
            "sd": sd,
            "t": np.nan,
            "df": np.nan,
            "p_raw": np.nan,
            "p_corr": np.nan,
            "reject": False,
            "cohens_d": np.nan,
            "ci_mean_low": np.nan,
            "ci_mean_high": np.nan,
            "note": "",
        }

        if n < 3:
            row["note"] = "insufficient_n"
            rows.append(row)
            continue

        t_stat, p_raw = _one_sample_ttest(values, alternative=alternative)
        row["t"] = t_stat
        row["df"] = float(n - 1)
        row["p_raw"] = p_raw

        if np.isfinite(sd) and sd > 0:
            row["cohens_d"] = mean / sd
            se = sd / np.sqrt(n)
            ci_low, ci_high = stats.t.interval(1 - alpha, df=n - 1, loc=mean, scale=se)
            row["ci_mean_low"] = float(ci_low)
            row["ci_mean_high"] = float(ci_high)
        else:
            row["note"] = "zero_variance"

        rows.append(row)

    results_df = pd.DataFrame(rows)

    if not results_df.empty:
        if correction_scope == "global":
            mask = pd.to_numeric(results_df["p_raw"], errors="coerce").map(np.isfinite)
            if mask.any():
                reject, p_corr, _, _ = multipletests(
                    results_df.loc[mask, "p_raw"].to_numpy(dtype=float),
                    alpha=alpha,
                    method=correction,
                )
                results_df.loc[mask, "p_corr"] = p_corr
                results_df.loc[mask, "reject"] = reject
        else:
            finite_mask = pd.to_numeric(results_df["p_raw"], errors="coerce").map(np.isfinite)
            for idx in results_df.groupby("roi", dropna=False).groups.values():
                roi_mask = results_df.index.isin(idx) & finite_mask
                if not roi_mask.any():
                    continue
                reject, p_corr, _, _ = multipletests(
                    results_df.loc[roi_mask, "p_raw"].to_numpy(dtype=float),
                    alpha=alpha,
                    method=correction,
                )
                results_df.loc[roi_mask, "p_corr"] = p_corr
                results_df.loc[roi_mask, "reject"] = reject

    results_df = results_df[
        [
            "condition",
            "roi",
            "N",
            "mean",
            "sd",
            "t",
            "df",
            "p_raw",
            "p_corr",
            "reject",
            "cohens_d",
            "ci_mean_low",
            "ci_mean_high",
            "note",
        ]
    ]

    sig = results_df[results_df["reject"].fillna(False)]
    sig_lines = [
        f"- condition={row['condition']}, roi={row['roi']}, p_corr={row['p_corr']:.6g}, mean={row['mean']:.6g}"
        for _, row in sig.iterrows()
        if pd.notna(row["p_corr"])
    ]
    sig_text = "\n".join(sig_lines) if sig_lines else "- none"

    log_text = (
        "Baseline vs Zero tests completed.\n"
        f"alpha={alpha}; alternative={alternative}; correction={correction}; "
        f"correction_scope={correction_scope}\n"
        f"Cells tested={len(results_df)}; valid_p={int(results_df['p_raw'].notna().sum())}; "
        f"significant={int(results_df['reject'].fillna(False).sum())}\n"
        "Significant findings:\n"
        f"{sig_text}"
    )
    return log_text, results_df


def export_baseline_vs_zero_results_to_excel(
    payload: dict[str, object],
    save_path: str | Path,
    log_func: Callable[[str], None],
) -> bool:
    """Write baseline-vs-zero results and metadata workbook."""
    if not isinstance(payload, dict):
        raise ValueError("Baseline-vs-zero export payload must be a dictionary.")
    results_df = payload.get("results_df")
    if not isinstance(results_df, pd.DataFrame):
        raise ValueError("Baseline-vs-zero export payload missing 'results_df' DataFrame.")

    metadata_obj = payload.get("metadata")
    metadata: dict[str, object] = metadata_obj if isinstance(metadata_obj, dict) else {}
    correction_method_raw = str(metadata.get("correction", "fdr_bh"))
    correction_scope = str(metadata.get("correction_scope", "global"))
    correction_method_label = (
        "fdr_bh (Benjamini–Hochberg FDR)"
        if correction_method_raw == "fdr_bh"
        else correction_method_raw
    )
    correction_scope_definition = (
        "Across all condition×ROI cells with finite raw p-values."
        if correction_scope == "global"
        else "Within each ROI across condition cells, using finite raw p-values only."
    )

    export_df = results_df.copy()
    if "p_raw" in export_df.columns:
        export_df = export_df.rename(columns={"p_raw": "p (raw)"})
    if "p_corr" in export_df.columns:
        export_df = export_df.rename(columns={"p_corr": "p (BH-FDR corrected)"})
    export_df["correction_method"] = "BH-FDR" if correction_method_raw == "fdr_bh" else correction_method_raw
    export_df["correction_scope"] = correction_scope

    n_by_cell = (
        export_df.loc[:, ["condition", "roi", "N"]]
        if {"condition", "roi", "N"}.issubset(export_df.columns)
        else pd.DataFrame(columns=["condition", "roi", "N"])
    )
    summary_rows = [
        {"field": "timestamp", "value": datetime.now().isoformat(timespec="seconds")},
        {"field": "dv_col", "value": metadata.get("dv_col", "value")},
        {"field": "alpha", "value": metadata.get("alpha", 0.05)},
        {"field": "alternative", "value": metadata.get("alternative", "greater")},
        {"field": "correction", "value": correction_method_raw},
        {"field": "correction_method", "value": correction_method_label},
        {
            "field": "correction_scope",
            "value": correction_scope,
        },
        {"field": "correction_scope_definition", "value": correction_scope_definition},
        {"field": "corrected_p_value_column", "value": "p_corr"},
        {"field": "corrected_p_value_column_in_sheet", "value": "p (BH-FDR corrected)"},
        {
            "field": "total_unique_subjects",
            "value": metadata.get("total_unique_subjects", np.nan),
        },
    ]
    metadata_df = pd.concat(
        [
            pd.DataFrame(summary_rows),
            pd.DataFrame(
                [
                    {
                        "field": "n_by_condition_roi",
                        "value": "",
                        "condition": row["condition"],
                        "roi": row["roi"],
                        "N": row["N"],
                    }
                    for _, row in n_by_cell.iterrows()
                ]
            ),
        ],
        ignore_index=True,
    )

    save_path = Path(save_path)
    with pd.ExcelWriter(save_path, engine="xlsxwriter") as writer:
        _auto_format_and_write_excel(writer, export_df, "Baseline_vs_Zero", log_func)
        _auto_format_and_write_excel(writer, metadata_df, "Metadata", log_func)
    return True
