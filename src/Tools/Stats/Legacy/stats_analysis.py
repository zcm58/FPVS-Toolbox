# -*- coding: utf-8 -*-
"""Utility functions for data processing used by the Stats UI.

Key changes:
- No DEFAULT_ROIS and no import-time caching.
- set_rois() stores a runtime override; otherwise we resolve from Settings on demand.
- All ROI consumers read from a fresh map at call-time (no stale globals).
"""

from __future__ import annotations

import logging
import os
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import scipy.stats as stats

from .repeated_m_anova import run_repeated_measures_anova
from Tools.Stats.roi_resolver import ROI, resolve_active_rois

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# ROI sourcing (no defaults, no import-time cache)
# -----------------------------------------------------------------------------

# Optional override pushed by callers (kept for backward compatibility)
_ROIS_OVERRIDE: Optional[Dict[str, List[str]]] = None


def set_rois(rois_dict: Dict[str, List[str]]) -> None:
    """
    Compatibility hook: store a runtime override of the ROI map.
    Callers (e.g., UI) may pass fresh ROIs right before long computations.

    Notes
    -----
    - ROI *names* remain case-sensitive.
    - Electrode labels are stored with whitespace trimmed; their case is preserved here.
      We upper-case only for DataFrame index matching where needed.
    """
    global _ROIS_OVERRIDE
    _ROIS_OVERRIDE = {
        str(name): [str(ch).strip() for ch in chans if str(ch).strip()]
        for name, chans in (rois_dict or {}).items()
        if str(name).strip()
    }


def _current_rois_map() -> Dict[str, List[str]]:
    """
    Return the active ROI map without using defaults or import-time cache.
    Prefers the override set via set_rois(); otherwise resolves from Settings.
    """
    if _ROIS_OVERRIDE:
        return _ROIS_OVERRIDE
    try:
        rois = resolve_active_rois()  # List[ROI]
        return {r.name: list(r.channels) for r in rois}
    except Exception:
        return {}


ALL_ROIS_OPTION = "(All ROIs)"
HARMONIC_CHECK_ALPHA = 0.05


# -----------------------------------------------------------------------------
# Frequency helpers
# -----------------------------------------------------------------------------
def get_included_freqs(
    base_freq: float, all_col_names, log_func, max_freq: Optional[float] = None
) -> List[float]:
    """
    Return candidate frequency bins from column names, excluding base-rate multiples
    (e.g., 6, 12, 18 Hz if base is 6 Hz). This is a coarse pre-filter; oddball-only
    harmonics are selected later by filter_to_oddball_harmonics.
    """
    try:
        base_freq_val = float(base_freq)
        if base_freq_val <= 0:
            raise ValueError("Base frequency must be positive.")
    except ValueError as e:
        log_func(f"Error: Invalid Base Frequency '{base_freq}': {e}")
        return []

    numeric_freqs: List[float] = []
    for col_name in all_col_names:
        if isinstance(col_name, str) and col_name.endswith("_Hz"):
            try:
                numeric_freqs.append(float(col_name[:-3]))
            except ValueError:
                log_func(f"Could not parse freq from col: {col_name}")

    if not numeric_freqs:
        return []

    freqs = sorted(set(numeric_freqs))
    if max_freq is not None:
        try:
            max_freq_val = float(max_freq)
            freqs = [f for f in freqs if f <= max_freq_val]
        except ValueError:
            log_func(f"Invalid max frequency '{max_freq}'. Using no upper limit.")

    # Exclude exact multiples of the base frequency (base, 2*base, 3*base, ...)
    excluded = {f for f in freqs if abs(f / base_freq_val - round(f / base_freq_val)) < 1e-6}
    return [f for f in freqs if f not in excluded]


def filter_to_oddball_harmonics(
    freq_list: List[float],
    base_freq: float,
    every_n: int = 5,
    tol: float = 1e-3,
    max_k: Optional[int] = None,
    max_freq: Optional[float] = None,
) -> List[Tuple[float, int]]:
    """
    Keep only frequencies that are (within tol) at k * (base_freq / every_n), i.e.,
    harmonics of the oddball frequency. Returns list of (frequency_hz, harmonic_k).
    """
    try:
        base = float(base_freq)
        if base <= 0:
            return []
    except Exception:
        return []

    fo = base / float(every_n)  # oddball frequency (e.g., 6/5 = 1.2 Hz)
    out: List[Tuple[float, int]] = []
    for f in sorted(set(freq_list)):
        if max_freq is not None and f > float(max_freq):
            continue
        k = int(round(f / fo))
        if k <= 0:
            continue
        if abs(f - k * fo) <= tol:
            out.append((float(f), int(k)))

    if isinstance(max_k, int) and max_k > 0:
        out = out[:max_k]
    return out


def _match_freq_column(columns, freq_value: float) -> Optional[str]:
    """Return the column name that corresponds to ``freq_value`` (e.g., '6.0_Hz')."""
    patterns = [
        f"{freq_value:.1f}_Hz",
        f"{freq_value:.2f}_Hz",
        f"{freq_value:.3f}_Hz",
        f"{freq_value:.4f}_Hz",
    ]
    for pattern in patterns:
        if pattern in columns:
            return pattern
    for col in columns:
        if isinstance(col, str) and col.endswith("_Hz"):
            try:
                if abs(float(col[:-3]) - freq_value) < 1e-4:
                    return col
            except ValueError:
                continue
    return None


# -----------------------------------------------------------------------------
# BCA aggregation and ANOVA
# -----------------------------------------------------------------------------
def aggregate_bca_sum(
    file_path: str,
    roi_name: str,
    base_freq: float,
    log_func,
    rois: Optional[List[ROI]] = None,
) -> float:
    """Return summed BCA for an ROI across included harmonics.

    ROIs are taken from current Settings at runtime via resolve_active_rois()
    unless a list of ROI objects is provided.
    """
    try:
        df = pd.read_excel(file_path, sheet_name="BCA (uV)", index_col="Electrode")
        # For matching, upper-case the index; ROI channel labels will be upper-cased to match.
        df.index = df.index.str.upper()

        # Prefer provided ROIs (List[ROI]); else use current map
        if rois is not None:
            roi_map = {r.name: r.channels for r in rois}
        else:
            roi_map = _current_rois_map()

        roi_channels = [str(ch).strip().upper() for ch in roi_map.get(roi_name, [])]
        if not roi_channels:
            log_func(f"ROI {roi_name} not defined.")
            return np.nan

        df_roi = df.reindex(roi_channels).dropna(how="all")
        if df_roi.empty:
            log_func(f"No data for ROI {roi_name} in {file_path}.")
            return np.nan

        included_freq_values = get_included_freqs(base_freq, df.columns, log_func)
        if not included_freq_values:
            log_func(f"No freqs to sum for BCA in {file_path}.")
            return np.nan

        cols_to_sum: List[str] = []
        for f_val in included_freq_values:
            col_name = _match_freq_column(df_roi.columns, f_val)
            if col_name:
                cols_to_sum.append(col_name)
        if not cols_to_sum:
            log_func(f"No matching BCA freq columns for ROI {roi_name} in {file_path}.")
            return np.nan

        return float(df_roi[cols_to_sum].sum(axis=1).mean())
    except Exception as e:  # pragma: no cover
        log_func(
            f"Error aggregating BCA for {os.path.basename(file_path)}, ROI {roi_name}: {e}"
        )
        return np.nan


def prepare_all_subject_summed_bca_data(
    subjects: List[str],
    conditions: List[str],
    subject_data: Dict[str, Dict[str, str]],
    base_freq: float,
    log_func,
    roi_filter: Optional[List[str]] = None,
) -> Optional[Dict[str, Dict[str, Dict[str, float]]]]:
    """Prepare summed BCA data for all subjects and conditions.

    Always uses the current ROI map (override via set_rois or live Settings),
    with no defaults and no calls to resolve_active_rois().
    """
    all_subject_data: Dict[str, Dict[str, Dict[str, float]]] = {}
    if not subjects or not subject_data:
        log_func("No subject data. Scan folder first.")
        return None

    # Pull the active ROI map right now (respects set_rois override)
    rois_map = _current_rois_map()
    if roi_filter:
        rois_map = {name: chans for name, chans in rois_map.items() if name in roi_filter}

    # Log what we are about to use
    logger.info(
        "stats_rois",
        extra={
            "roi_names": list(rois_map.keys()),
            "roi_counts": [len(ch) for ch in rois_map.values()],
        },
    )
    if rois_map:
        log_func(
            "Using "
            f"{len(rois_map)} ROIs from Settings: {', '.join(rois_map.keys())}"
        )
    else:
        log_func("No ROIs defined in Settings.")
        return None

    # Build the subject × condition × ROI table
    for pid in subjects:
        all_subject_data[pid] = {}
        for cond_name in conditions:
            file_path = subject_data.get(pid, {}).get(cond_name)
            all_subject_data[pid].setdefault(cond_name, {})
            for roi_name in rois_map.keys():
                if file_path and os.path.exists(file_path):
                    # aggregate_bca_sum will look up channels via _current_rois_map()
                    sum_val = aggregate_bca_sum(file_path, roi_name, base_freq, log_func)
                else:
                    sum_val = np.nan
                all_subject_data[pid][cond_name][roi_name] = sum_val

    log_func("Summed BCA data prep complete.")
    return all_subject_data



def run_rm_anova(all_subject_data, log_func):
    """Run RM-ANOVA on summed BCA data.

    ROIs are taken from current Settings at runtime via resolve_active_rois().
    """
    long_format_data = []
    for pid, cond_data in all_subject_data.items():
        for cond_name, roi_data in cond_data.items():
            for roi_name, value in roi_data.items():
                if not pd.isna(value):
                    long_format_data.append(
                        {"subject": pid, "condition": cond_name, "roi": roi_name, "value": value}
                    )

    if not long_format_data:
        return "No valid data available for RM-ANOVA after filtering NaNs.", None

    df_long = pd.DataFrame(long_format_data)
    if df_long["condition"].nunique() < 2 or df_long["roi"].nunique() < 1:
        return "RM-ANOVA requires at least two conditions and at least one ROI with valid data.", None

    try:
        log_func(
            f"Calling run_repeated_measures_anova with DataFrame of shape: {df_long.shape}"
        )
        anova_df_results = run_repeated_measures_anova(
            data=df_long,
            dv_col="value",
            within_cols=["condition", "roi"],
            subject_col="subject",
        )
    except Exception as e:
        log_func(f"!!! RM-ANOVA Error: {e}")
        return f"RM-ANOVA analysis failed unexpectedly: {e}", None

    if anova_df_results is None or anova_df_results.empty:
        return "RM-ANOVA did not return any results or the result was empty.", None

    return anova_df_results.to_string(index=False), anova_df_results


# -----------------------------------------------------------------------------
# Harmonic significance check (Z/SNR)
# -----------------------------------------------------------------------------
def _ttest_onesample_tail(
    x: np.ndarray, popmean: float = 0.0, tail: str = "greater", min_n: int = 3
):
    """One-sample t with tail handling; falls back if SciPy lacks 'alternative' arg."""
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    if x.size < min_n:
        return np.nan, np.nan
    try:
        res = stats.ttest_1samp(x, popmean=popmean, alternative=tail)
        return float(res.statistic), float(res.pvalue)
    except TypeError:
        # Older SciPy: compute two-sided and convert
        t_stat, p_two = stats.ttest_1samp(x, popmean=popmean)
        if not np.isfinite(t_stat):
            return float(t_stat), np.nan
        if tail == "two-sided":
            return float(t_stat), float(p_two)
        p_one = p_two / 2.0
        if (tail == "greater" and x.mean() < popmean) or (tail == "less" and x.mean() > popmean):
            p_one = 1.0 - p_one
        return float(t_stat), float(p_one)


def _dz_ci(x: np.ndarray, alpha: float = 0.05, min_n: int = 3):
    """Cohen's dz and 95% CI for the one-sample mean."""
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    if x.size < min_n:
        return np.nan, np.nan, np.nan, np.nan
    m = float(np.mean(x))
    s = float(np.std(x, ddof=1))
    dz = m / s if s > 0 else np.nan
    se = s / np.sqrt(x.size) if x.size > 0 else np.nan
    try:
        ci_low, ci_high = stats.t.interval(1 - alpha, df=x.size - 1, loc=m, scale=se)
    except Exception:
        ci_low, ci_high = np.nan, np.nan
    return dz, m, float(ci_low), float(ci_high)


def _passes_threshold(mean_val: float, threshold: float, tail: str = "greater") -> bool:
    """Tail-aware threshold rule (e.g., mean Z ≥ 1.64 for 'greater')."""
    if not np.isfinite(mean_val):
        return False
    if tail == "greater":
        return mean_val >= threshold
    elif tail == "less":
        return mean_val <= -abs(threshold)
    else:  # two-sided
        return abs(mean_val) >= abs(threshold)


def run_harmonic_check(
    subject_data: Dict[str, Dict[str, str]],
    subjects: List[str],
    conditions: List[str],
    selected_metric: str,
    mean_value_threshold: float,
    base_freq: float,
    log_func,
    max_freq: Optional[float] = None,
    correction_method: str = "holm",  # 'holm' or 'fdr_bh'
    tail: str = "greater",  # 'greater' is appropriate for Z/SNR
    min_subjects: int = 3,
    do_wilcoxon_sensitivity: bool = True,
    oddball_every_n: int = 5,  # enforce k * (base/every_n) harmonics
    limit_n_harmonics: Optional[int] = None,  # cap to first k harmonics (e.g., 8)
):
    """
    Per-harmonic group detectability with multiple-comparisons correction.

    A harmonic within an ROI×Condition is called 'Significant' if BOTH hold:
      (1) One-tailed group test vs 0 (p < alpha, corrected across harmonics within ROI×Condition);
      (2) Group mean meets the tail-aware threshold (e.g., Z >= 1.64 for 'greater').

    Returns
    -------
    report_text : str
    findings    : list of dicts (wide, plot-friendly)
    """
    from statsmodels.stats.multitest import multipletests

    alpha = globals().get("HARMONIC_CHECK_ALPHA", 0.05)
    rois_map = _current_rois_map()

    findings: List[Dict] = []
    output_lines: List[str] = [f"===== Per-Harmonic Significance Check ({selected_metric}) ====="]
    output_lines.append("A harmonic is flagged as 'Significant' if:")
    output_lines.append(
        f"1) One-tailed group test vs 0 (p < {alpha}, {correction_method} across harmonics within ROI×Condition), and"
    )
    output_lines.append(
        f"2) Group mean {selected_metric} meets the threshold ({mean_value_threshold}, tail='{tail}')."
    )
    output_lines.append("(N = number of subjects contributing to that harmonic.)\n")

    any_significant_found = False
    loaded_dataframes: Dict[str, pd.DataFrame] = {}

    for cond_name in conditions:
        output_lines.append(f"\n=== Condition: {cond_name} ===")
        # Find a sample file for column names
        sample_file = None
        for pid_s in subjects:
            if subject_data.get(pid_s, {}).get(cond_name):
                sample_file = subject_data[pid_s][cond_name]
                break

        for roi_name in rois_map.keys():
            if not sample_file:
                output_lines.append(f"  --- ROI: {roi_name} ---")
                output_lines.append(
                    "      Could not determine checkable frequencies (no sample data file found for this condition).\n"
                )
                continue

            # Determine which harmonics to test
            try:
                if sample_file not in loaded_dataframes:
                    df_tmp = pd.read_excel(sample_file, sheet_name=selected_metric, index_col="Electrode")
                    df_tmp.index = df_tmp.index.str.upper()
                    loaded_dataframes[sample_file] = df_tmp
                sample_df_cols = loaded_dataframes[sample_file].columns

                # Coarse prefilter to drop base multiples, then restrict to oddball harmonics
                included_freq_values = get_included_freqs(base_freq, sample_df_cols, log_func, max_freq)
                oddball_list = filter_to_oddball_harmonics(
                    included_freq_values,
                    base_freq,
                    every_n=oddball_every_n,
                    tol=1e-3,
                    max_k=limit_n_harmonics,
                    max_freq=max_freq,
                )  # list of (f_hz, k)
            except Exception as e:
                log_func(f"Error reading columns for ROI '{roi_name}', Cond '{cond_name}': {e}")
                output_lines.append(f"  --- ROI: {roi_name} ---")
                output_lines.append("      Error determining checkable frequencies for this ROI.\n")
                continue

            if not oddball_list:
                output_lines.append(f"  --- ROI: {roi_name} ---")
                output_lines.append("      No applicable oddball harmonics after frequency exclusions.\n")
                continue

            roi_records: List[Dict] = []
            roi_channels = rois_map.get(roi_name, [])

            # Collect per-harmonic stats (we'll correct across them, then print)
            for (freq_val, harm_k) in oddball_list:
                display_col = _match_freq_column(sample_df_cols, freq_val) or f"{freq_val:.1f}_Hz"
                subj_vals: List[float] = []

                for pid in subjects:
                    f_path = subject_data.get(pid, {}).get(cond_name)
                    if not (f_path and os.path.exists(f_path)):
                        continue

                    df_cur = loaded_dataframes.get(f_path)
                    if df_cur is None:
                        try:
                            df_cur = pd.read_excel(f_path, sheet_name=selected_metric, index_col="Electrode")
                            df_cur.index = df_cur.index.str.upper()
                            loaded_dataframes[f_path] = df_cur
                        except FileNotFoundError:
                            log_func(f"Error: File not found {f_path} for PID {pid}, Cond {cond_name}.")
                            continue

                    col_name = _match_freq_column(df_cur.columns, freq_val)
                    if not col_name:
                        continue

                    # Mean over ROI channels for this participant & harmonic (match index in upper-case)
                    mean_val = df_cur.reindex([str(ch).strip().upper() for ch in roi_channels])[col_name].dropna().mean()
                    if pd.notna(mean_val):
                        subj_vals.append(float(mean_val))

                n_subj = len(subj_vals)
                if n_subj < min_subjects:
                    roi_records.append(
                        {
                            "Condition": cond_name,
                            "ROI": roi_name,
                            "Frequency": display_col,
                            "Frequency_Hz": float(freq_val),
                            "Harmonic_k": int(harm_k),
                            "N_Subjects": n_subj,
                            "mean": np.nan,
                            "t_stat": np.nan,
                            "p_raw": np.nan,
                            "p_corr": np.nan,
                            "Significant": False,
                            "cohens_dz": np.nan,
                            "ci95_low": np.nan,
                            "ci95_high": np.nan,
                            "shapiro_p": np.nan,
                            "wilcoxon_p": np.nan,
                        }
                    )
                    continue

                # One-sample t (tail-aware)
                t_stat, p_raw = _ttest_onesample_tail(
                    np.asarray(subj_vals), popmean=0.0, tail=tail, min_n=min_subjects
                )
                dz, m, ci_l, ci_h = _dz_ci(np.asarray(subj_vals), alpha=alpha, min_n=min_subjects)

                # Normality (info)
                try:
                    _, sh_p = stats.shapiro(np.asarray(subj_vals, dtype=float))
                except Exception:
                    sh_p = np.nan

                # Optional Wilcoxon sensitivity (one-tailed ~ 'greater' if requested)
                if do_wilcoxon_sensitivity and n_subj >= min_subjects:
                    try:
                        alt = "greater" if tail == "greater" else ("less" if tail == "less" else "two-sided")
                        _, p_w = stats.wilcoxon(
                            np.asarray(subj_vals), zero_method="wilcox", correction=False, alternative=alt
                        )
                    except TypeError:
                        # Fallback for very old SciPy: two-sided then halve if mean>0
                        _, p_two = stats.wilcoxon(
                            np.asarray(subj_vals), zero_method="wilcox", correction=False
                        )
                        p_w = float(p_two / 2.0 if np.nanmean(subj_vals) > 0 else 1 - p_two / 2.0)
                else:
                    p_w = np.nan

                roi_records.append(
                    {
                        "Condition": cond_name,
                        "ROI": roi_name,
                        "Frequency": display_col,
                        "Frequency_Hz": float(freq_val),
                        "Harmonic_k": int(harm_k),
                        "N_Subjects": n_subj,
                        "mean": m,
                        "t_stat": t_stat,
                        "p_raw": p_raw,
                        "cohens_dz": dz,
                        "ci95_low": ci_l,
                        "ci95_high": ci_h,
                        "shapiro_p": sh_p,
                        "wilcoxon_p": p_w,
                    }
                )

            # Multiple-comparisons correction across harmonics for this ROI×Condition
            valid_idx = [i for i, r in enumerate(roi_records) if np.isfinite(r.get("p_raw", np.nan))]
            if valid_idx:
                from statsmodels.stats.multitest import multipletests

                pvals = [roi_records[i]["p_raw"] for i in valid_idx]
                rej, p_corr, _, _ = multipletests(pvals, alpha=alpha, method=correction_method)
                for i, pc, rj in zip(valid_idx, p_corr, rej):
                    roi_records[i]["p_corr"] = float(pc)
                    roi_records[i]["Significant"] = bool(
                        rj and _passes_threshold(roi_records[i]["mean"], mean_value_threshold, tail=tail)
                    )
            else:
                for r in roi_records:
                    r["p_corr"] = np.nan
                    r["Significant"] = False

            # --- Print block ---
            sig_rows = [r for r in roi_records if r.get("Significant", False)]
            if sig_rows:
                output_lines.append(f"  --- ROI: {roi_name} ---")
                for r in sig_rows:
                    any_significant_found = True
                    p_str = (
                        "< .0001"
                        if (r["p_raw"] is not None and np.isfinite(r["p_raw"]) and r["p_raw"] < 1e-4)
                        else f"{r['p_raw']:.4f}"
                    )
                    pc_str = (
                        "< .0001"
                        if (r["p_corr"] is not None and np.isfinite(r["p_corr"]) and r["p_corr"] < 1e-4)
                        else f"{r['p_corr']:.4f}"
                    )
                    output_lines.append("    -------------------------------------------")
                    output_lines.append(
                        f"    Harmonic: {r['Frequency']} (k={r['Harmonic_k']}) -> SIGNIFICANT RESPONSE"
                    )
                    output_lines.append(
                        f"        Average {selected_metric}: {r['mean']:.3f} (N={r['N_Subjects']})  "
                        f"dz={r['cohens_dz']:.2f}  95% CI [{r['ci95_low']:.3f}, {r['ci95_high']:.3f}]"
                    )
                    output_lines.append(
                        f"        t({r['N_Subjects']-1}) = {r['t_stat']:.2f},  p_raw = {p_str},  p_{correction_method} = {pc_str}"
                    )
                    if do_wilcoxon_sensitivity and np.isfinite(r.get("wilcoxon_p", np.nan)):
                        output_lines.append(
                            f"        Wilcoxon (one-tailed) p = {r['wilcoxon_p']:.4f}  |  Shapiro p = {r['shapiro_p']:.3f} (info)"
                        )
                    output_lines.append("    -------------------------------------------")
                if len(sig_rows) > 1:
                    output_lines.append(
                        f"    Summary for {roi_name}: Found {len(sig_rows)} significant harmonics (details above).\n"
                    )
            else:
                output_lines.append(f"  --- ROI: {roi_name} ---")
                output_lines.append("      No significant harmonics met criteria for this ROI.\n")

            # Append to global findings (plot-friendly)
            for r in roi_records:
                findings.append(
                    {
                        "Condition": r["Condition"],
                        "ROI": r["ROI"],
                        "Frequency": r["Frequency"],
                        "Frequency_Hz": r.get("Frequency_Hz", np.nan),
                        "Harmonic_k": r.get("Harmonic_k", np.nan),
                        "N_Subjects": r["N_Subjects"],
                        f"Mean_{selected_metric.replace(' ', '_')}": r.get("mean", np.nan),
                        "Cohens_dz": r.get("cohens_dz", np.nan),
                        "CI95_Low": r.get("ci95_low", np.nan),
                        "CI95_High": r.get("ci95_high", np.nan),
                        "T_Statistic": r.get("t_stat", np.nan),
                        "P_Value_Raw": r.get("p_raw", np.nan),
                        f"P_Value_{correction_method.upper()}": r.get("p_corr", np.nan),
                        "Wilcoxon_p": r.get("wilcoxon_p", np.nan),
                        "Shapiro_p": r.get("shapiro_p", np.nan),
                        "Meets_Mean_Threshold": _passes_threshold(
                            r.get("mean", np.nan), mean_value_threshold, tail=tail
                        ),
                        "Significant": bool(r.get("Significant", False)),
                        "Alpha": alpha,
                        "Tail": tail,
                        "Correction": correction_method,
                    }
                )

        output_lines.append("")

    if not any_significant_found:
        output_lines.append("Overall: No harmonics met the significance criteria across all conditions and ROIs.")
    else:
        output_lines.append("\n--- End of Report ---")
        output_lines.append("Tip: p-values are Holm/FDR-corrected across harmonics within each ROI×Condition.")
        output_lines.append("     Use the returned table for summary stats and figure annotations.\n")

    return "\n".join(output_lines), findings
