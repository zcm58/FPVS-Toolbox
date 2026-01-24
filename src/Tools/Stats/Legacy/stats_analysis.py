# -*- coding: utf-8 -*-
"""Utility functions for data processing used by the Stats UI.

Key changes:
- Added thread-safety guards to _current_rois_map
- aggregate_bca_sum and prepare_all_subject_summed_bca_data now accept explicit ROIs
"""

from __future__ import annotations

import logging
import os
import threading
import warnings
from typing import Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd
import scipy.stats as stats
from statsmodels.stats.multitest import multipletests

from Tools.Stats.Legacy.excel_io import safe_read_excel
from Tools.Stats.roi_resolver import ROI, resolve_active_rois
from .blas_limits import single_threaded_blas
from .repeated_m_anova import RM_ANOVA_DIAG, build_rm_anova_frames, run_repeated_measures_anova

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
        logger.warning(
            "CRITICAL: Attempted to resolve ROIs from a background thread. "
            "This would cause a crash. Returning empty ROIs."
        )
        return {}

    try:
        rois = resolve_active_rois()  # List[ROI]
        return {r.name: list(r.channels) for r in rois}
    except Exception:
        return {}


ALL_ROIS_OPTION = "(All ROIs)"
HARMONIC_CHECK_ALPHA = 0.05

# ---------------------------------------------------------------------
# Summed BCA harmonic selection (ROI-mean Z gating + consecutive stop)
# ---------------------------------------------------------------------
SUMMED_BCA_Z_THRESHOLD_DEFAULT = 1.64
SUMMED_BCA_ODDBALL_EVERY_N_DEFAULT = 5
SUMMED_BCA_STOP_AFTER_N_CONSEC_NONSIG_DEFAULT = 2


def _rm_anova_value_is_valid(value: object) -> bool:
    if pd.isna(value):
        return False
    try:
        return bool(np.isfinite(value))
    except Exception:
        return False


def _preview_values(values: list[object], limit: int = 50) -> str:
    sorted_vals = sorted(values, key=lambda v: repr(v))
    if len(sorted_vals) <= limit:
        return "[" + ", ".join(repr(v) for v in sorted_vals) + "]"
    head = ", ".join(repr(v) for v in sorted_vals[:30])
    return "[" + head + f", ... ({len(sorted_vals)} total)]"


def _rm_anova_expected_levels(
    all_subject_data: dict[str, dict[str, dict[str, object]]],
    *,
    subjects: Optional[list[str]] = None,
    conditions: Optional[list[str]] = None,
    rois: Optional[list[str]] = None,
) -> tuple[list[str], list[str], list[str]]:
    subject_list = list(subjects) if subjects else sorted(all_subject_data.keys(), key=repr)
    if conditions:
        condition_list = list(conditions)
    else:
        condition_set = {
            cond_name
            for cond_data in all_subject_data.values()
            for cond_name in (cond_data or {}).keys()
        }
        condition_list = sorted(condition_set, key=repr)
    if rois:
        roi_list = list(rois)
    else:
        roi_set = {
            roi_name
            for cond_data in all_subject_data.values()
            for roi_data in (cond_data or {}).values()
            for roi_name in (roi_data or {}).keys()
        }
        roi_list = sorted(roi_set, key=repr)
    return subject_list, condition_list, roi_list


def _collect_rm_anova_diagnostics(
    all_subject_data: dict[str, dict[str, dict[str, object]]],
    df_all: pd.DataFrame,
    df_valid: pd.DataFrame,
    *,
    subjects: Optional[list[str]] = None,
    conditions: Optional[list[str]] = None,
    rois: Optional[list[str]] = None,
) -> dict[str, object]:
    subject_list, condition_list, roi_list = _rm_anova_expected_levels(
        all_subject_data,
        subjects=subjects,
        conditions=conditions,
        rois=rois,
    )

    missing_in_dict: list[tuple[str, str, str]] = []
    present_but_invalid: list[tuple[str, str, str, object]] = []
    for subject in subject_list:
        subject_data = all_subject_data.get(subject, {})
        for condition in condition_list:
            condition_data = subject_data.get(condition)
            if condition_data is None:
                for roi in roi_list:
                    missing_in_dict.append((subject, condition, roi))
                continue
            for roi in roi_list:
                if roi not in condition_data:
                    missing_in_dict.append((subject, condition, roi))
                    continue
                value = condition_data.get(roi)
                if not _rm_anova_value_is_valid(value):
                    present_but_invalid.append((subject, condition, roi, value))

    duplicate_cells = []
    if not df_all.empty:
        grouped = df_all.groupby(["subject", "condition", "roi"], dropna=False).size()
        duplicate_cells = [
            (subject, condition, roi, int(count))
            for (subject, condition, roi), count in grouped.items()
            if count > 1
        ]

    expected_rows = len(subject_list) * len(condition_list) * len(roi_list)
    return {
        "subjects": subject_list,
        "conditions": condition_list,
        "rois": roi_list,
        "expected_rows": expected_rows,
        "missing_in_dict": missing_in_dict,
        "present_but_invalid": present_but_invalid,
        "duplicate_cells": duplicate_cells,
        "df_all_shape": df_all.shape,
        "df_valid_shape": df_valid.shape,
    }


def _rm_anova_diag_summary(diag: dict[str, object]) -> str:
    missing_count = len(diag["missing_in_dict"])
    invalid_count = len(diag["present_but_invalid"])
    duplicate_count = len(diag["duplicate_cells"])
    expected_rows = diag["expected_rows"]
    df_all_shape = diag["df_all_shape"]
    df_valid_shape = diag["df_valid_shape"]
    return (
        "Unbalanced: "
        f"missing_in_dict={missing_count}, "
        f"present_but_invalid={invalid_count}, "
        f"duplicates={duplicate_count}; "
        f"expected={expected_rows}, "
        f"df_all={df_all_shape}, "
        f"df_valid={df_valid_shape}."
    )


def _log_rm_anova_diagnostics(
    all_subject_data: dict[str, dict[str, dict[str, object]]],
    df_all: pd.DataFrame,
    df_valid: pd.DataFrame,
    diag: dict[str, object],
    log_func,
    *,
    force: bool = False,
) -> None:
    if not log_func or (not RM_ANOVA_DIAG and not force):
        return

    subjects = diag["subjects"]
    log_func("[RM_ANOVA DIAG] RM-ANOVA imbalance diagnostics")
    log_func(f"[RM_ANOVA DIAG] expected_rows={diag['expected_rows']}")
    log_func(f"[RM_ANOVA DIAG] df_all shape={diag['df_all_shape']}")
    log_func(f"[RM_ANOVA DIAG] df_valid shape={diag['df_valid_shape']}")
    log_func(
        "[RM_ANOVA DIAG] unique subjects: "
        f"{_preview_values([s for s in pd.unique(df_all.get('subject', []))])}"
    )
    log_func(
        "[RM_ANOVA DIAG] unique conditions: "
        f"{_preview_values([c for c in pd.unique(df_all.get('condition', []))])}"
    )
    log_func(
        "[RM_ANOVA DIAG] unique rois: "
        f"{_preview_values([r for r in pd.unique(df_all.get('roi', []))])}"
    )

    df_all_counts = df_all.groupby("subject")["subject"].count().to_dict() if not df_all.empty else {}
    df_valid_counts = (
        df_valid.groupby("subject")["subject"].count().to_dict() if not df_valid.empty else {}
    )
    for subject in subjects:
        log_func(
            "[RM_ANOVA DIAG] subject count "
            f"{subject!r}: df_all={df_all_counts.get(subject, 0)} "
            f"df_valid={df_valid_counts.get(subject, 0)}"
        )

    log_func(
        "[RM_ANOVA DIAG] summary: "
        f"missing_in_dict={len(diag['missing_in_dict'])}, "
        f"present_but_invalid={len(diag['present_but_invalid'])}, "
        f"duplicates={len(diag['duplicate_cells'])}"
    )

    for subject, condition, roi in diag["missing_in_dict"]:
        subject_data = all_subject_data.get(subject, {})
        available_conditions = sorted(subject_data.keys(), key=repr)
        roi_keys = []
        if condition in subject_data:
            roi_keys = sorted(subject_data.get(condition, {}).keys(), key=repr)
        log_func(
            "[RM_ANOVA DIAG] missing_in_dict: "
            f"subject={subject!r} condition={condition!r} roi={roi!r} "
            f"available_conditions={available_conditions!r} "
            f"available_rois={roi_keys!r}"
        )

    for subject, condition, roi, value in diag["present_but_invalid"]:
        value_type = type(value).__name__
        finite_check = None
        try:
            finite_check = bool(np.isfinite(value))
        except Exception:
            finite_check = None
        conversion = None
        if isinstance(value, str):
            try:
                conversion = float(value)
            except Exception:
                conversion = None
        log_func(
            "[RM_ANOVA DIAG] present_but_invalid: "
            f"subject={subject!r} condition={condition!r} roi={roi!r} "
            f"value={value!r} type={value_type} isfinite={finite_check} "
            f"string_float={conversion!r}"
        )

    for subject, condition, roi, count in diag["duplicate_cells"]:
        log_func(
            "[RM_ANOVA DIAG] duplicate_cell: "
            f"subject={subject!r} condition={condition!r} roi={roi!r} count={count}"
        )
SUMMED_BCA_ARM_STOP_AFTER_FIRST_SIG_DEFAULT = True
SUMMED_BCA_Z_SHEET_NAME = "Z Score"

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
    rois: Optional[Union[List[ROI], Dict[str, List[str]]]] = None,
) -> float:
    """
    Return summed BCA for an ROI across significant oddball harmonics.

    Selection rule (within this participant/file):
      1) Candidate freqs = all non-base-multiple freqs (via get_included_freqs)
      2) Restrict to oddball harmonics (via filter_to_oddball_harmonics)
      3) For each oddball harmonic in ascending order:
           - compute ROI-mean Z at that harmonic (same channel set used for BCA)
           - include harmonic if mean(Z_ROI) > Z_THRESHOLD
           - apply consecutive non-significant stop rule (optionally armed only after first sig)
      4) Sum BCA across selected harmonics per electrode (min_count=1), then mean across ROI electrodes.
    """
    try:
        # --- Read required sheets ---
        df_bca = safe_read_excel(file_path, sheet_name="BCA (uV)", index_col="Electrode")
        df_z = safe_read_excel(file_path, sheet_name=SUMMED_BCA_Z_SHEET_NAME, index_col="Electrode")

        # Normalize electrode labels
        df_bca.index = df_bca.index.astype(str).str.upper().str.strip()
        df_z.index = df_z.index.astype(str).str.upper().str.strip()

        # --- Resolve ROI map safely ---
        if rois is not None:
            if isinstance(rois, dict):
                roi_map: Dict[str, List[str]] = rois
            elif isinstance(rois, list):
                roi_map = {r.name: list(r.channels) for r in rois}
            else:
                roi_map = {}
        else:
            roi_map = _current_rois_map()

        roi_channels = [str(ch).strip().upper() for ch in roi_map.get(roi_name, [])]
        if not roi_channels:
            log_func(f"ROI {roi_name} not defined.")
            return np.nan

        # Use the SAME channel set for Z gating + BCA summation: intersection of available channels
        roi_chans = [ch for ch in roi_channels if (ch in df_bca.index and ch in df_z.index)]
        if not roi_chans:
            log_func(f"No overlapping BCA+Z data for ROI {roi_name} in {file_path}.")
            return np.nan

        df_bca_roi = df_bca.loc[roi_chans].dropna(how="all")
        df_z_roi = df_z.loc[roi_chans].dropna(how="all")
        if df_bca_roi.empty or df_z_roi.empty:
            log_func(f"No data for ROI {roi_name} in {file_path}.")
            return np.nan

        # --- Candidate freqs: exclude base-rate multiples, then restrict to oddball harmonics ---
        included_freq_values = get_included_freqs(base_freq, df_bca.columns, log_func)
        if not included_freq_values:
            log_func(f"No freqs to sum for BCA in {file_path}.")
            return np.nan

        oddball_list = filter_to_oddball_harmonics(
            included_freq_values,
            base_freq,
            every_n=SUMMED_BCA_ODDBALL_EVERY_N_DEFAULT,
            tol=1e-3,
        )
        if not oddball_list:
            log_func(f"No applicable oddball harmonics for ROI {roi_name} in {file_path}.")
            return np.nan

        # --- Select significant harmonics using ROI-mean Z with consecutive stop rule ---
        cols_to_sum: List[str] = []
        nonsig_run = 0
        seen_sig = False

        for (freq_val, _harm_k) in oddball_list:
            col_bca = _match_freq_column(df_bca_roi.columns, freq_val)
            col_z = _match_freq_column(df_z_roi.columns, freq_val)
            if not col_bca or not col_z:
                continue

            z_series = pd.to_numeric(df_z_roi[col_z], errors="coerce").replace([np.inf, -np.inf], np.nan)
            mean_z = float(z_series.mean(skipna=True)) if z_series.notna().any() else np.nan
            is_sig = bool(np.isfinite(mean_z) and (mean_z > SUMMED_BCA_Z_THRESHOLD_DEFAULT))

            if is_sig:
                cols_to_sum.append(col_bca)
                nonsig_run = 0
                seen_sig = True
            else:
                if SUMMED_BCA_ARM_STOP_AFTER_FIRST_SIG_DEFAULT and not seen_sig:
                    continue
                nonsig_run += 1
                if nonsig_run >= SUMMED_BCA_STOP_AFTER_N_CONSEC_NONSIG_DEFAULT:
                    break

        log_func(
            f"[DEBUG] {roi_name} {os.path.basename(file_path)}: "
            f"selected {len(cols_to_sum)} harmonics (threshold={SUMMED_BCA_Z_THRESHOLD_DEFAULT})."
        )

        if not cols_to_sum:
            log_func(f"No significant harmonics selected for ROI {roi_name} in {file_path}.")
            return np.nan

        # --- Sum BCA across selected harmonics per electrode, then average across electrodes ---
        bca_block = (
            df_bca_roi[cols_to_sum]
            .apply(pd.to_numeric, errors="coerce")
            .replace([np.inf, -np.inf], np.nan)
        )
        # min_count=1 prevents "all-NaN -> 0.0" behavior
        bca_vals = bca_block.sum(axis=1, min_count=1)

        # Mean across electrodes with at least one finite value
        bca_vals = pd.to_numeric(bca_vals, errors="coerce").replace([np.inf, -np.inf], np.nan)
        if not bca_vals.notna().any():
            log_func(
                f"Warning: All-NaN BCA values after summation for ROI {roi_name} "
                f"({os.path.basename(file_path)})."
            )
            return np.nan

        out = float(bca_vals.mean(skipna=True))
        return out if np.isfinite(out) else np.nan

    except Exception as e:
        log_func(f"Error aggregating BCA for {os.path.basename(file_path)}, ROI {roi_name}: {e}")
        return np.nan


def prepare_all_subject_summed_bca_data(
    subjects: List[str],
    conditions: List[str],
    subject_data: Dict[str, Dict[str, str]],
    base_freq: float,
    log_func,
    roi_filter: Optional[List[str]] = None,
    rois: Optional[Dict[str, List[str]]] = None,
) -> Optional[Dict[str, Dict[str, Dict[str, float]]]]:
    """Prepare summed BCA data for all subjects and conditions."""
    all_subject_data: Dict[str, Dict[str, Dict[str, float]]] = {}
    if not subjects or not subject_data:
        log_func("No subject data. Scan folder first.")
        return None

    # Use passed ROIs if available, avoid unsafe lookup
    rois_map = rois if rois is not None else _current_rois_map()

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

    log_func(f"Using {len(rois_map)} ROIs: {', '.join(rois_map.keys())}")

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
                        sum_val = aggregate_bca_sum(file_path, roi_name, base_freq, log_func, rois=rois_map)
                    except Exception as e:
                        log_func(f"Failed to read {os.path.basename(file_path)} for {pid}: {e}")
                all_subject_data[pid][cond_name][roi_name] = sum_val

    # Debug summary: how much usable data did we generate?
    total = 0
    finite = 0
    for pid, conds in all_subject_data.items():
        for _cond, rois_dict in conds.items():
            for _roi, val in rois_dict.items():
                total += 1
                if val is not None and np.isfinite(val):
                    finite += 1
    log_func(f"[DEBUG] Summed BCA finite cells: {finite}/{total}")

    log_func("Summed BCA data prep complete.")
    return all_subject_data


def run_rm_anova(
    all_subject_data,
    log_func,
    *,
    subjects: Optional[list[str]] = None,
    conditions: Optional[list[str]] = None,
    rois: Optional[list[str]] = None,
):
    """Run RM-ANOVA on summed BCA data."""
    df_all, df_long = build_rm_anova_frames(all_subject_data)
    if df_long.empty:
        return "No valid data available for RM-ANOVA after filtering NaNs.", None

    if df_long["condition"].nunique() < 2 or df_long["roi"].nunique() < 1:
        return "RM-ANOVA requires at least two conditions and at least one ROI with valid data.", None

    diag = _collect_rm_anova_diagnostics(
        all_subject_data,
        df_all,
        df_long,
        subjects=subjects,
        conditions=conditions,
        rois=rois,
    )
    diag_summary = _rm_anova_diag_summary(diag)
    if RM_ANOVA_DIAG:
        _log_rm_anova_diagnostics(all_subject_data, df_all, df_long, diag, log_func)

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
                raw_df=df_all,
                log_func=log_func,
                diag_summary=diag_summary,
            )
    except Exception as e:
        if "Data is unbalanced" in str(e):
            _log_rm_anova_diagnostics(all_subject_data, df_all, df_long, diag, log_func, force=True)
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
    rois: Optional[Dict[str, List[str]]] = None,
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
    rois: Optional[Dict[str, List[str]]] = None,
):
    alpha = globals().get("HARMONIC_CHECK_ALPHA", 0.05)

    # Safe ROI resolution
    rois_map = rois if rois is not None else _current_rois_map()

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
                output_lines.append("      Could not determine checkable frequencies (no sample data file found).\n")
                continue

            try:
                if sample_file not in loaded_dataframes:
                    df_tmp = safe_read_excel(sample_file, sheet_name=selected_metric, index_col="Electrode")
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
                            df_cur = safe_read_excel(f_path, sheet_name=selected_metric, index_col="Electrode")
                            df_cur.index = df_cur.index.str.upper()
                            loaded_dataframes[f_path] = df_cur
                        except FileNotFoundError:
                            continue

                    col_name = _match_freq_column(df_cur.columns, freq_val)
                    if not col_name:
                        continue

                    try:
                        valid_chans = [
                            c for c in [str(ch).strip().upper() for ch in roi_channels] if c in df_cur.index
                        ]
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
                    output_lines.append(f"    Harmonic: {r['Frequency']} (k={r['Harmonic_k']}) -> SIGNIFICANT RESPONSE")
                    output_lines.append(f"        Mean: {r['mean']:.3f} (N={r['N_Subjects']}) dz={r['cohens_dz']:.2f}")
                    output_lines.append(f"        p_raw = {p_str},  p_{correction_method} = {pc_str}")
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
