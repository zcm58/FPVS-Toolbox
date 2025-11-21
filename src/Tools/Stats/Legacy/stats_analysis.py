# -*- coding: utf-8 -*-
"""Utility functions for data processing used by the Stats UI.

Key changes:
- Added thread-safety guards to _current_rois_map
- aggregate_bca_sum and prepare_all_subject_summed_bca_data now accept explicit ROIs
"""

from __future__ import annotations

import logging
import os
import warnings
import threading  # <--- Added for thread safety check
from typing import Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd
import scipy.stats as stats
from statsmodels.stats.multitest import multipletests

from Tools.Stats.Legacy.excel_io import safe_read_excel
from .repeated_m_anova import run_repeated_measures_anova
from .blas_limits import single_threaded_blas
from Tools.Stats.roi_resolver import ROI, resolve_active_rois

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# ROI sourcing (no defaults, no import-time cache)
# -----------------------------------------------------------------------------

_ROIS_OVERRIDE: Optional[Dict[str, List[str]]] = None


def set_rois(rois_dict: Dict[str, List[str]]) -> None:
    """
    Compatibility hook: store a runtime override of the ROI map.
    """
    global _ROIS_OVERRIDE
    _ROIS_OVERRIDE = {
        str(name): [str(ch).strip() for ch in chans if str(ch).strip()]
        for name, chans in (rois_dict or {}).items()
        if str(name).strip()
    }


def _current_rois_map() -> Dict[str, List[str]]:
    """
    Return the active ROI map.
    SAFETY UPDATE: If called from a background thread without an override,
    it returns empty instead of crashing the app (0xC0000005).
    """
    if _ROIS_OVERRIDE:
        return _ROIS_OVERRIDE

    # GUARD: If we are in a worker thread, we CANNOT access resolve_active_rois (QSettings)
    if threading.current_thread() is not threading.main_thread():
        logger.warning("CRITICAL: Attempted to resolve ROIs from a background thread. "
                       "This would cause a crash. Returning empty ROIs.")
        return {}

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
    """Return candidate frequency bins from column names."""
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
    try:
        base = float(base_freq)
        if base <= 0:
            return []
    except Exception:
        return []

    fo = base / float(every_n)
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
        rois: Optional[Union[List[ROI], Dict[str, List[str]]]] = None,  # <--- Updated Type Hint
) -> float:
    """Return summed BCA for an ROI across included harmonics."""
    try:
        df = safe_read_excel(file_path, sheet_name="BCA (uV)", index_col="Electrode")
        df.index = df.index.str.upper()

        # -------------------------------------------------------
        # FIX: Handle both List[ROI] and Dict[str, List[str]]
        # to avoid calling _current_rois_map in threads.
        # -------------------------------------------------------
        roi_map = {}
        if rois is not None:
            if isinstance(rois, dict):
                roi_map = rois
            elif isinstance(rois, list):
                roi_map = {r.name: r.channels for r in rois}
        else:
            # Fallback to global (unsafe in threads unless override set)
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

        vals = df_roi[cols_to_sum].sum(axis=1)
        if not np.isfinite(vals).all():
            log_func(f"Warning: Infinite values detected in ROI {roi_name} for {os.path.basename(file_path)}")
            return np.nan

        return float(vals.mean())
    except Exception as e:
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
        rois: Optional[Dict[str, List[str]]] = None,  # <--- NEW ARGUMENT
) -> Optional[Dict[str, Dict[str, Dict[str, float]]]]:
    """Prepare summed BCA data for all subjects and conditions."""
    all_subject_data: Dict[str, Dict[str, Dict[str, float]]] = {}
    if not subjects or not subject_data:
        log_func("No subject data. Scan folder first.")
        return None

    # -------------------------------------------------------
    # FIX: Use passed ROIs if available, avoid unsafe lookup
    # -------------------------------------------------------
    if rois is not None:
        rois_map = rois
    else:
        rois_map = _current_rois_map()

    if roi_filter:
        rois_map = {name: chans for name, chans in rois_map.items() if name in roi_filter}

    logger.info(
        "stats_rois",
        extra={
            "roi_names": list(rois_map.keys()),
            "roi_counts": [len(ch) for ch in rois_map.values()],
        },
    )

    if not rois_map:
        log_func("No ROIs defined or available.")
        return None

    if rois_map:
        log_func(
            "Using "
            f"{len(rois_map)} ROIs: {', '.join(rois_map.keys())}"
        )

    # Build the subject × condition × ROI table
    for pid in subjects:
        all_subject_data[pid] = {}
        for cond_name in conditions:
            file_path = subject_data.get(pid, {}).get(cond_name)
            all_subject_data[pid].setdefault(cond_name, {})
            for roi_name in rois_map.keys():
                sum_val = np.nan
                if file_path and os.path.exists(file_path):
                    try:
                        # FIX: Pass the rois_map down to the aggregator!
                        sum_val = aggregate_bca_sum(file_path, roi_name, base_freq, log_func, rois=rois_map)
                    except Exception as e:
                        log_func(f"Failed to read {os.path.basename(file_path)} for {pid}: {e}")

                all_subject_data[pid][cond_name][roi_name] = sum_val

    log_func("Summed BCA data prep complete.")
    return all_subject_data


def run_rm_anova(all_subject_data, log_func):
    """Run RM-ANOVA on summed BCA data."""
    long_format_data = []
    for pid, cond_data in all_subject_data.items():
        for cond_name, roi_data in cond_data.items():
            for roi_name, value in roi_data.items():
                if not pd.isna(value) and np.isfinite(value):
                    long_format_data.append(
                        {"subject": pid, "condition": cond_name, "roi": roi_name, "value": value}
                    )

    if not long_format_data:
        return "No valid data available for RM-ANOVA after filtering NaNs.", None

    df_long = pd.DataFrame(long_format_data)
    if df_long["condition"].nunique() < 2 or df_long["roi"].nunique() < 1:
        return "RM-ANOVA requires at least two conditions and at least one ROI with valid data.", None

    try:
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=UserWarning, message=".*Covariance.*")
            warnings.filterwarnings("ignore", message=".*Random effects covariance is singular.*")

            log_func(f"Calling run_repeated_measures_anova with DataFrame of shape: {df_long.shape}")
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
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    if x.size < min_n:
        return np.nan, np.nan

    if np.std(x, ddof=1) < 1e-9:
        return 0.0, 1.0

    try:
        res = stats.ttest_1samp(x, popmean=popmean, alternative=tail)
        return float(res.statistic), float(res.pvalue)
    except TypeError:
        t_stat, p_two = stats.ttest_1samp(x, popmean=popmean)
        if not np.isfinite(t_stat):
            return float(t_stat), np.nan
        if tail == "two-sided":
            return float(t_stat), float(p_two)
        p_one = p_two / 2.0
        if (tail == "greater" and x.mean() < popmean) or (tail == "less" and x.mean() > popmean):
            p_one = 1.0 - p_one
        return float(t_stat), float(p_one)
    except Exception:
        return np.nan, np.nan


def _dz_ci(x: np.ndarray, alpha: float = 0.05, min_n: int = 3):
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    if x.size < min_n:
        return np.nan, np.nan, np.nan, np.nan
    m = float(np.mean(x))
    s = float(np.std(x, ddof=1))

    if s < 1e-9:
        return np.nan, m, m, m

    dz = m / s
    se = s / np.sqrt(x.size)
    try:
        ci_low, ci_high = stats.t.interval(1 - alpha, df=x.size - 1, loc=m, scale=se)
    except Exception:
        ci_low, ci_high = np.nan, np.nan
    return dz, m, float(ci_low), float(ci_high)


def _passes_threshold(mean_val: float, threshold: float, tail: str = "greater") -> bool:
    if not np.isfinite(mean_val):
        return False
    if tail == "greater":
        return mean_val >= threshold
    elif tail == "less":
        return mean_val <= -abs(threshold)
    else:
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
        correction_method: str = "holm",
        tail: str = "greater",
        min_subjects: int = 3,
        do_wilcoxon_sensitivity: bool = True,
        oddball_every_n: int = 5,
        limit_n_harmonics: Optional[int] = None,
        rois: Optional[Dict[str, List[str]]] = None,  # <--- ADDED ARGUMENT
):
    with single_threaded_blas():
        return _run_harmonic_check_impl(
            subject_data,
            subjects,
            conditions,
            selected_metric,
            mean_value_threshold,
            base_freq,
            log_func,
            max_freq,
            correction_method,
            tail,
            min_subjects,
            do_wilcoxon_sensitivity,
            oddball_every_n,
            limit_n_harmonics,
            rois,
        )


def _run_harmonic_check_impl(
        subject_data: Dict[str, Dict[str, str]],
        subjects: List[str],
        conditions: List[str],
        selected_metric: str,
        mean_value_threshold: float,
        base_freq: float,
        log_func,
        max_freq: Optional[float] = None,
        correction_method: str = "holm",
        tail: str = "greater",
        min_subjects: int = 3,
        do_wilcoxon_sensitivity: bool = True,
        oddball_every_n: int = 5,
        limit_n_harmonics: Optional[int] = None,
        rois: Optional[Dict[str, List[str]]] = None,  # <--- ADDED ARGUMENT
):
    alpha = globals().get("HARMONIC_CHECK_ALPHA", 0.05)

    # Safe ROI resolution
    if rois is not None:
        rois_map = rois
    else:
        rois_map = _current_rois_map()

    findings: List[Dict] = []
    output_lines: List[str] = [f"===== Per-Harmonic Significance Check ({selected_metric}) ====="]

    if not rois_map:
        output_lines.append("Error: No ROIs available.")
        return "\n".join(output_lines), []

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
        sample_file = None
        for pid_s in subjects:
            if subject_data.get(pid_s, {}).get(cond_name):
                sample_file = subject_data[pid_s][cond_name]
                break

        for roi_name in rois_map.keys():
            if not sample_file:
                output_lines.append(f"  --- ROI: {roi_name} ---")
                output_lines.append(
                    "      Could not determine checkable frequencies (no sample data file found).\n"
                )
                continue

            try:
                if sample_file not in loaded_dataframes:
                    df_tmp = safe_read_excel(
                        sample_file, sheet_name=selected_metric, index_col="Electrode"
                    )
                    df_tmp.index = df_tmp.index.str.upper()
                    loaded_dataframes[sample_file] = df_tmp
                sample_df_cols = loaded_dataframes[sample_file].columns

                included_freq_values = get_included_freqs(base_freq, sample_df_cols, log_func, max_freq)
                oddball_list = filter_to_oddball_harmonics(
                    included_freq_values,
                    base_freq,
                    every_n=oddball_every_n,
                    tol=1e-3,
                    max_k=limit_n_harmonics,
                    max_freq=max_freq,
                )
            except Exception as e:
                log_func(f"Error reading columns for ROI '{roi_name}': {e}")
                continue

            if not oddball_list:
                output_lines.append(f"  --- ROI: {roi_name} ---")
                output_lines.append("      No applicable oddball harmonics found.\n")
                continue

            roi_records: List[Dict] = []
            roi_channels = rois_map.get(roi_name, [])

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
                            df_cur = safe_read_excel(
                                f_path, sheet_name=selected_metric, index_col="Electrode"
                            )
                            df_cur.index = df_cur.index.str.upper()
                            loaded_dataframes[f_path] = df_cur
                        except FileNotFoundError:
                            continue

                    col_name = _match_freq_column(df_cur.columns, freq_val)
                    if not col_name:
                        continue

                    try:
                        # Ensure channels exist in index
                        valid_chans = [c for c in [str(ch).strip().upper() for ch in roi_channels] if c in df_cur.index]
                        if not valid_chans:
                            continue
                        vals = df_cur.loc[valid_chans, col_name]
                        mean_val = vals.mean()
                        if pd.notna(mean_val) and np.isfinite(mean_val):
                            subj_vals.append(float(mean_val))
                    except Exception:
                        pass

                n_subj = len(subj_vals)
                if n_subj < min_subjects:
                    continue

                t_stat, p_raw = _ttest_onesample_tail(
                    np.asarray(subj_vals), popmean=0.0, tail=tail, min_n=min_subjects
                )
                dz, m, ci_l, ci_h = _dz_ci(np.asarray(subj_vals), alpha=alpha, min_n=min_subjects)

                sh_p = np.nan
                try:
                    if len(set(subj_vals)) > 1:
                        _, sh_p = stats.shapiro(np.asarray(subj_vals, dtype=float))
                    else:
                        sh_p = 1.0
                except Exception:
                    pass

                p_w = np.nan
                if do_wilcoxon_sensitivity and n_subj >= min_subjects:
                    try:
                        alt = "greater" if tail == "greater" else ("less" if tail == "less" else "two-sided")
                        _, p_w = stats.wilcoxon(
                            np.asarray(subj_vals), zero_method="wilcox", correction=False, alternative=alt
                        )
                    except Exception:
                        pass

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

            valid_idx = [i for i, r in enumerate(roi_records) if np.isfinite(r.get("p_raw", np.nan))]
            if valid_idx:
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

            sig_rows = [r for r in roi_records if r.get("Significant", False)]
            if sig_rows:
                output_lines.append(f"  --- ROI: {roi_name} ---")
                for r in sig_rows:
                    any_significant_found = True
                    p_str = f"{r['p_raw']:.4f}"
                    pc_str = f"{r.get('p_corr', np.nan):.4f}"
                    output_lines.append("    -------------------------------------------")
                    output_lines.append(
                        f"    Harmonic: {r['Frequency']} (k={r['Harmonic_k']}) -> SIGNIFICANT RESPONSE"
                    )
                    output_lines.append(
                        f"        Mean: {r['mean']:.3f} (N={r['N_Subjects']}) dz={r['cohens_dz']:.2f}"
                    )
                    output_lines.append(
                        f"        p_raw = {p_str},  p_{correction_method} = {pc_str}"
                    )
                    output_lines.append("    -------------------------------------------")
            else:
                output_lines.append(f"  --- ROI: {roi_name} ---")
                output_lines.append("      No significant harmonics met criteria for this ROI.\n")

            for r in roi_records:
                findings.append(r)

    if not any_significant_found:
        output_lines.append("Overall: No harmonics met the significance criteria.")

    return "\n".join(output_lines), findings

# Lela mode is in full effect