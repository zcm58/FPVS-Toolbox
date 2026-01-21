#!/usr/bin/env python3
"""
ROI SNR/Z/BCA Aggregator for FPVS Excel Outputs (single-file pipeline)

PURPOSE:
Compute participant-level ROI means for Z, SNR, and BCA across significant oddball harmonics,
summarize group statistics, compute per-condition global-harmonic-set ratios/deltas, and generate plots/logs.

PIPELINE STEPS:
1. Batch read Excel outputs from two condition folders.
2. Determine PER-CONDITION global significant harmonics (fixed list per condition), using Z scores and a stop rule.
3. Exclude base-rate harmonics (6 Hz multiples) from significance selection.
4. Compute participant-level ROI means for Z, SNR, and BCA across the PER-CONDITION global harmonic list.
5. Aggregate group-level metrics (Mean, SD, SEM, CV) with N_total and N_used.
6. Compute ratios/deltas per participant/ROI using PER-CONDITION global harmonic sets:
   - Z ratio = meanZ_sem_global / meanZ_col_global
   - SNR ratio = meanSNR_sem_global / meanSNR_col_global
   - BCA ratio (policy dependent; because BCA can be negative)
   - delta_BCA = meanBCA_sem_global - meanBCA_col_global
7. Generate plots (PDF + PNG): RAW (Z/SNR/BCA) and RATIOS (Z ratio / SNR ratio / BCA ratio / delta_BCA).
8. Diagnostic reporting:
   - base-rate harmonic exclusions
   - zero-global-harmonic participants
   - extremes (highest/lowest)
   - hard-threshold exclusions (auto)
   - soft QC flags (robust MAD-based) for review only (no auto exclusion)

OUTLIER / EXCLUSION POLICY:
A) HARD EXCLUSIONS (AUTO):
   - If any participant has mean_SNR_global > HARD_EXCLUSION_SNR_THRESH (any condition/ROI), exclude globally.
   - If any participant has mean_BCA_global > HARD_EXCLUSION_BCA_THRESH (any condition/ROI), exclude globally.

B) SOFT QC FLAGS (REVIEW ONLY; NOT AUTO-EXCLUDED):
   - Robust MAD z-score flags within each (condition x ROI x metric) group.
   - Logged + exported for manual review.

This is a personal script intended to run on a single PC; hard-coded paths are OK.
"""

from __future__ import annotations

import os
import math
import re
import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any, Set

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

from PySide6.QtWidgets import QApplication, QMessageBox

# =================================================================
# 1. USER INPUTS (EDIT THESE)
# =================================================================

INPUT_DIR_A = r"C:\Users\zcm58\OneDrive - Mississippi State University\Office Desktop\FPVS Toolbox Project Root\Semantic Categories 3\1 - Excel Data Files\Green Fruit vs Green Veg"
CONDITION_LABEL_A = "Semantic Response"

INPUT_DIR_B = r"C:\Users\zcm58\OneDrive - Mississippi State University\Office Desktop\FPVS Toolbox Project Root\Semantic Categories 3\1 - Excel Data Files\Green Veg vs Red Veg"
CONDITION_LABEL_B = "Color Response"

OUTPUT_DIR = r"C:\Users\zcm58\OneDrive - Mississippi State University\Office Desktop\FPVS Toolbox Project Root\Semantic Categories 3\5 - Avg SNR and Z-Scores"
RUN_LABEL = "R21_Preliminary_Data_Run"

ROI_DEFS = {
    "Occipital": ["O1", "O2", "Oz"],
    "LOT": ["P7", "P9", "PO7", "PO3", "O1"],
    "Left Central": ["C1", "C3", "C5"],
    "Right Central": ["C2", "C4", "C6"],
    "Left Parietal": ["P1", "P3", "P5"],
    "Right Parietal": ["P2", "P4", "P6"],
}

Z_THRESHOLD = 1.64
MAX_HZ = 20.4
BASE_FREQ = 6.0
EXCLUDE_BASE_UP_TO_HZ = 24.0

PALETTE_CHOICE = "vibrant"  # "vibrant", "muted", "colorblind_safe"
PNG_DPI = 300

# Hard auto-exclusion thresholds (requested)
HARD_EXCLUSION_SNR_THRESH = 5.0
HARD_EXCLUSION_BCA_THRESH = 4.0

# NEW: Manual Kill List

"""
Use the list below to manually exclude outliers from the dataset and all calculations.
"""
MANUAL_EXCLUDE = []  # Configure study exclusions privately.

# Soft QC (review-only) settings
SOFT_QC_ENABLED = True
SOFT_QC_ROBUST_Z_THRESH = 3.5
SOFT_QC_MIN_N = 6

# =================================================================
# 2. INTERNAL CONFIGURATION
# =================================================================

SHEET_SNR = "SNR"
SHEET_Z = "Z Score"
SHEET_BCA = "BCA (uV)"
ELECTRODE_COL = "Electrode"

PALETTES = {
    "vibrant": {"Occipital": "#2E86FF", "LOT": "#FF6B2E", "Default": "#7F8C8D"},
    "muted": {"Occipital": "#4C78A8", "LOT": "#F58518", "Default": "#95A5A6"},
    "colorblind_safe": {"Occipital": "#0072B2", "LOT": "#D55E00", "Default": "#CC79A7"},
}

PID_RE = re.compile(r"(P)(\d+)", re.IGNORECASE)

# CV can be unstable if mean is near 0. For such cases, return NaN.
CV_EPS = 1e-9

# GLOBAL HARMONIC SET (PER CONDITION; FIXED LIST)
USE_GLOBAL_HARMONIC_SET = True
GLOBAL_STOP_RULE = "two_consecutive_nonsig"  # "two_consecutive_nonsig" or "none"
GLOBAL_MIN_HARMONICS = 1

# CHANGE 1 (requested fix only): select per-condition harmonics once using an anchor ROI, apply to all ROIs.
GLOBAL_SELECTION_MODE = "anchor_roi"  # "anchor_roi" or "per_roi"
GLOBAL_SELECTION_ANCHOR_ROI = "Occipital"

# CHANGE 2 (requested fix only): do not arm the stop rule until at least one sig harmonic is seen.
STOP_RULE_ARM_AFTER_FIRST_SIG = True

# BCA ratio policy (because BCA can be negative):
#   "positive_only" -> ratio computed only if both semantic and color global-set BCA means are > 0
#   "abs"           -> ratio computed on abs(BCA) (always >= 0, but changes meaning)
#   "shift"         -> shift both by a constant to make them positive before ratio (constant logged)
BCA_RATIO_POLICY = "positive_only"
BCA_SHIFT_EPS = 1e-6  # used only for "shift"

# For soft QC reporting (review only)
SOFT_QC_METRICS_RAW = [
    ("mean_Z_global", "Z"),
    ("mean_SNR_global", "SNR"),
    ("mean_BCA_global", "BCA(uV)"),
]


# -----------------------------
# Utility / Parsing
# -----------------------------

def parse_participant_id(filename: str) -> Tuple[str, int]:
    m = PID_RE.search(filename)
    if not m:
        raise ValueError(f"Could not parse participant id from: {filename}")
    return f"P{m.group(2)}", int(m.group(2))


def harmonic_col_to_hz(col: str) -> float:
    s = str(col).strip()
    s = s.replace("HZ", "Hz").replace("hz", "Hz")
    s = s.replace("_Hz", "").replace("Hz", "")
    return float(s)


def is_base_multiple(freq_hz: float, base_freq: float, up_to_hz: float, tol: float = 1e-6) -> bool:
    if freq_hz < base_freq - tol or freq_hz > up_to_hz + tol:
        return False
    k = round(freq_hz / base_freq)
    return abs(freq_hz - (k * base_freq)) <= tol and k >= 1


def safe_mean(x: np.ndarray) -> float:
    n = int(np.sum(~np.isnan(x)))
    return float(np.nanmean(x)) if n > 0 else float("nan")


def safe_sd(x: np.ndarray) -> float:
    n = int(np.sum(~np.isnan(x)))
    return float(np.nanstd(x, ddof=1)) if n >= 2 else float("nan")


def safe_sem(x: np.ndarray) -> float:
    n = int(np.sum(~np.isnan(x)))
    return float(np.nanstd(x, ddof=1) / math.sqrt(n)) if n >= 2 else float("nan")


def safe_cv(mean_val: float, sd_val: float, eps: float = CV_EPS) -> float:
    if not (np.isfinite(mean_val) and np.isfinite(sd_val)):
        return float("nan")
    if abs(mean_val) <= eps:
        return float("nan")
    return float(sd_val / mean_val)


def fmt_hz_list(hz_list: List[float]) -> str:
    if not hz_list:
        return ""
    return ", ".join([f"{hz:g}" for hz in hz_list])


def fmt_float(x: Any, ndigits: int = 4) -> str:
    try:
        v = float(x)
    except Exception:
        return "nan"
    return f"{v:.{ndigits}g}" if np.isfinite(v) else "nan"


# -----------------------------
# Soft QC (review-only)
# -----------------------------

def robust_z_mad(series: pd.Series, min_n: int) -> pd.Series:
    """
    Robust z using MAD:
      z = 0.6745 * (x - median) / MAD
    Returns NaN if finite n < min_n or MAD==0.
    """
    vals = pd.to_numeric(series, errors="coerce")
    finite = vals[np.isfinite(vals)]
    if finite.size < min_n:
        return pd.Series(np.full(len(vals), np.nan), index=vals.index)

    med = float(np.nanmedian(finite))
    mad = float(np.nanmedian(np.abs(finite - med)))
    if not np.isfinite(mad) or mad == 0:
        return pd.Series(np.full(len(vals), np.nan), index=vals.index)

    return 0.6745 * (vals - med) / mad


def detect_soft_qc_flags(df_part: pd.DataFrame, log_fn) -> pd.DataFrame:
    """
    Review-only robust outlier flags. Does NOT exclude.
    """
    if not SOFT_QC_ENABLED:
        log_fn("-" * 110)
        log_fn("SOFT QC FLAGS: disabled.")
        log_fn("-" * 110)
        return pd.DataFrame()

    records: List[Dict[str, Any]] = []

    for (cond, roi), sub in df_part.groupby(["condition_label", "ROI"], sort=True):
        for metric_col, metric_name in SOFT_QC_METRICS_RAW:
            if metric_col not in sub.columns:
                continue
            z = robust_z_mad(sub[metric_col], min_n=SOFT_QC_MIN_N)
            mask = z.abs() > SOFT_QC_ROBUST_Z_THRESH
            for idx in sub.index[mask.fillna(False)]:
                records.append({
                    "participant_id": df_part.loc[idx, "participant_id"],
                    "participant_num": df_part.loc[idx, "participant_num"],
                    "condition_label": cond,
                    "ROI": roi,
                    "metric": metric_name,
                    "value": df_part.loc[idx, metric_col],
                    "robust_z_mad": float(z.loc[idx]) if np.isfinite(z.loc[idx]) else np.nan,
                    "source_file": df_part.loc[idx, "source_file"],
                })

    df_out = pd.DataFrame(records)
    if not df_out.empty:
        df_out = df_out.sort_values(
            ["participant_num", "condition_label", "ROI", "metric"],
            kind="stable",
        ).reset_index(drop=True)

    log_fn("-" * 110)
    log_fn("SOFT QC FLAGS (review-only; NOT excluded)")
    log_fn(f"  Rule: robust MAD z>|{SOFT_QC_ROBUST_Z_THRESH}| per (condition x ROI x metric); min_n={SOFT_QC_MIN_N}")
    if df_out.empty:
        log_fn("  No soft QC flags.")
    else:
        log_fn(f"  Flags: {len(df_out)} rows across {df_out['participant_id'].nunique()} participants.")
        for pid in sorted(df_out["participant_id"].unique().tolist(),
                          key=lambda s: int(s[1:]) if s[1:].isdigit() else 999999):
            rows = df_out[df_out["participant_id"] == pid]
            log_fn(f"  FLAG {pid}:")
            for _, r in rows.iterrows():
                log_fn(
                    f"    {r['condition_label']} | ROI={r['ROI']} | {r['metric']}="
                    f"{fmt_float(r['value'])} | robust_z={fmt_float(r['robust_z_mad'])}"
                )
    log_fn("-" * 110)

    return df_out


# -----------------------------
# Hard exclusions (auto)
# -----------------------------

def detect_hard_exclusions(df_part: pd.DataFrame, log_fn) -> Tuple[pd.DataFrame, Set[str]]:
    """
    Auto-exclude participants if:
      - any mean_SNR_global > HARD_EXCLUSION_SNR_THRESH
      - any mean_BCA_global > HARD_EXCLUSION_BCA_THRESH
    across any condition/ROI.

    Returns:
      df_excl_rows: rows that triggered exclusion (one per trigger)
      excluded_pids: participants to exclude globally
    """
    records: List[Dict[str, Any]] = []
    excluded: Set[str] = set()

    if "mean_SNR_global" in df_part.columns:
        snr_vals = pd.to_numeric(df_part["mean_SNR_global"], errors="coerce")
        mask = snr_vals > HARD_EXCLUSION_SNR_THRESH
        for idx in df_part.index[mask.fillna(False)]:
            pid = str(df_part.loc[idx, "participant_id"])
            excluded.add(pid)
            records.append({
                "participant_id": pid,
                "participant_num": df_part.loc[idx, "participant_num"],
                "condition_label": df_part.loc[idx, "condition_label"],
                "ROI": df_part.loc[idx, "ROI"],
                "metric": "SNR (global)",
                "value": df_part.loc[idx, "mean_SNR_global"],
                "threshold": HARD_EXCLUSION_SNR_THRESH,
                "source_file": df_part.loc[idx, "source_file"],
            })

    if "mean_BCA_global" in df_part.columns:
        bca_vals = pd.to_numeric(df_part["mean_BCA_global"], errors="coerce")
        mask = bca_vals > HARD_EXCLUSION_BCA_THRESH
        for idx in df_part.index[mask.fillna(False)]:
            pid = str(df_part.loc[idx, "participant_id"])
            excluded.add(pid)
            records.append({
                "participant_id": pid,
                "participant_num": df_part.loc[idx, "participant_num"],
                "condition_label": df_part.loc[idx, "condition_label"],
                "ROI": df_part.loc[idx, "ROI"],
                "metric": "BCA (uV; global)",
                "value": df_part.loc[idx, "mean_BCA_global"],
                "threshold": HARD_EXCLUSION_BCA_THRESH,
                "source_file": df_part.loc[idx, "source_file"],
            })

    df_excl = pd.DataFrame(records)
    if not df_excl.empty:
        df_excl = df_excl.sort_values(
            ["participant_num", "participant_id", "metric", "condition_label", "ROI"],
            kind="stable",
        ).reset_index(drop=True)

    log_fn("-" * 110)
    log_fn("HARD EXCLUSIONS (auto)")
    log_fn(f"  Rule: exclude participant globally if any SNR(global) > {HARD_EXCLUSION_SNR_THRESH} "
           f"or any BCA(global) > {HARD_EXCLUSION_BCA_THRESH}")
    if df_excl.empty:
        log_fn("  No hard exclusions triggered.")
    else:
        log_fn(f"  Excluded participants: {sorted(list(excluded), key=lambda s: int(s[1:]) if s[1:].isdigit() else 999999)}")
        log_fn("  Triggers:")
        for _, r in df_excl.iterrows():
            log_fn(
                f"    {r['participant_id']} | {r['condition_label']} | ROI={r['ROI']} | {r['metric']}="
                f"{fmt_float(r['value'])} > {r['threshold']}"
            )
    log_fn("-" * 110)

    return df_excl, excluded


# -----------------------------
# Core Computation
# -----------------------------

@dataclass(frozen=True)
class RunConfig:
    z_threshold: float
    max_hz: float
    base_freq: float
    exclude_base_up_to_hz: float


def compute_roi_harmonic_means(
    df: pd.DataFrame,
    roi_electrodes: List[str],
    harmonic_cols: List[str],
) -> Dict[float, float]:
    roi_df = df[df[ELECTRODE_COL].isin(roi_electrodes)].copy()
    if roi_df.empty:
        raise ValueError(f"Target electrodes {roi_electrodes} not found in Excel data.")
    out: Dict[float, float] = {}
    for col in harmonic_cols:
        hz = harmonic_col_to_hz(col)
        vals = pd.to_numeric(roi_df[col], errors="raise").to_numpy(dtype=float)
        out[hz] = safe_mean(vals)
    return out


def read_participant_file(xlsx_path: Path) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, List[str]]:
    df_snr = pd.read_excel(xlsx_path, sheet_name=SHEET_SNR)
    df_z = pd.read_excel(xlsx_path, sheet_name=SHEET_Z)
    df_bca = pd.read_excel(xlsx_path, sheet_name=SHEET_BCA)
    harm_cols = [c for c in df_z.columns if c != ELECTRODE_COL]
    return df_snr, df_z, df_bca, harm_cols


def _candidate_harmonics_from_cols(harm_cols: List[str], cfg: RunConfig) -> List[float]:
    hz_all = []
    for c in harm_cols:
        try:
            hz_all.append(harmonic_col_to_hz(c))
        except Exception:
            continue
    hz_all = sorted(list(set(hz_all)))
    cand: List[float] = []
    for hz in hz_all:
        if hz > cfg.max_hz:
            continue
        if is_base_multiple(hz, cfg.base_freq, cfg.exclude_base_up_to_hz):
            continue
        cand.append(hz)
    return cand


def _select_global_harmonics_for_condition_roi(
    cond_label: str,
    roi_name: str,
    cfg: RunConfig,
    pids_used: List[str],
    pid_to_path: Dict[str, Path],
    log_fn,
) -> Tuple[List[float], List[Dict[str, Any]]]:
    """
    Computes group-mean ROI Z per harmonic across participants, then scans harmonics in ascending order.
    Stops with two consecutive non-significant harmonics (if configured).
    """
    debug_rows: List[Dict[str, Any]] = []

    any_pid = pids_used[0]
    _, df_z_any, _, harm_cols = read_participant_file(pid_to_path[any_pid])
    cand = _candidate_harmonics_from_cols(harm_cols, cfg)

    log_fn(f"  CONDITION={cond_label} | ROI={roi_name}")
    log_fn(f"    Threshold: Z > {cfg.z_threshold} | MAX_HZ={cfg.max_hz} | stop_rule={GLOBAL_STOP_RULE}")

    selected: List[float] = []
    nonsig_run = 0
    seen_sig = False
    stop_at: Optional[float] = None
    stop_pair: Optional[Tuple[float, float]] = None

    for idx, hz in enumerate(cand):
        z_vals: List[float] = []
        for pid in pids_used:
            _, df_z, _, harm_cols_pid = read_participant_file(pid_to_path[pid])
            electrodes = ROI_DEFS[roi_name]
            z_by_hz = compute_roi_harmonic_means(df_z, electrodes, harm_cols_pid)
            if hz in z_by_hz and np.isfinite(z_by_hz[hz]):
                z_vals.append(float(z_by_hz[hz]))

        arr = np.array(z_vals, dtype=float)
        n_used = int(np.sum(np.isfinite(arr)))
        mean_z = float(np.nanmean(arr)) if n_used > 0 else float("nan")
        is_sig = bool(np.isfinite(mean_z) and (mean_z > cfg.z_threshold))

        action = ""
        if is_sig:
            selected.append(hz)
            nonsig_run = 0
            seen_sig = True
            action = "KEEP(sig)"
        else:
            # CHANGE 2 (requested fix only): do not arm stop rule until first sig harmonic is seen.
            if STOP_RULE_ARM_AFTER_FIRST_SIG and not seen_sig and GLOBAL_STOP_RULE == "two_consecutive_nonsig":
                action = "FAIL(pre-sig; stop-not-armed)"
            else:
                nonsig_run += 1
                action = f"FAIL(nonsig_run={nonsig_run})"
                if GLOBAL_STOP_RULE == "two_consecutive_nonsig" and nonsig_run >= 2:
                    stop_at = hz
                    stop_pair = (cand[idx - 1], cand[idx]) if idx >= 1 else (hz, hz)
                    action = "STOP(two_consecutive_nonsig)"

        debug_rows.append({
            "condition_label": cond_label,
            "ROI": roi_name,
            "hz": hz,
            "n_used": n_used,
            "meanZ": mean_z,
            "is_sig": int(is_sig),
            "nonsig_run": nonsig_run,
            "action": action,
        })

        if action.startswith("STOP("):
            break

    if stop_at is not None and stop_pair is not None:
        log_fn(
            f"    STOP TRIGGERED: two consecutive non-significant harmonics at {stop_pair[0]:g}Hz and {stop_pair[1]:g}Hz; "
            f"scanning stopped at {stop_at:g}Hz."
        )

    if len(selected) < GLOBAL_MIN_HARMONICS:
        log_fn(f"    Selected n={len(selected)} < GLOBAL_MIN_HARMONICS={GLOBAL_MIN_HARMONICS} -> forcing empty set.")
        selected = []

    log_fn(f"    Selected harmonics (n={len(selected)}): [{fmt_hz_list(selected)}]")

    log_fn("    Scan table (hz | n_used | meanZ | sig | action):")
    for r in debug_rows:
        log_fn(
            f"      {r['hz']:g} | n={r['n_used']} | meanZ={fmt_float(r['meanZ'])} | "
            f"sig={r['is_sig']} | {r['action']}"
        )

    return selected, debug_rows


def compute_global_harmonics_per_condition(
    cond_label: str,
    cfg: RunConfig,
    pids_used: List[str],
    pid_to_path: Dict[str, Path],
    log_fn,
) -> Tuple[Dict[str, List[float]], pd.DataFrame]:
    global_hz_by_roi: Dict[str, List[float]] = {}
    all_debug: List[Dict[str, Any]] = []

    log_fn("-" * 110)
    log_fn(f"GLOBAL HARMONIC SELECTION (PER CONDITION; FIXED LIST) :: {cond_label}")
    log_fn(f"Participants used for selection: {len(pids_used)}")
    log_fn("Stop rule: two_consecutive_nonsig (explicitly logged per ROI)")
    log_fn("-" * 110)

    # CHANGE 1 (requested fix only): anchor ROI selection applied to all ROIs within condition.
    if GLOBAL_SELECTION_MODE == "anchor_roi":
        anchor = GLOBAL_SELECTION_ANCHOR_ROI
        if anchor not in ROI_DEFS:
            raise ValueError(f"GLOBAL_SELECTION_ANCHOR_ROI='{anchor}' not in ROI_DEFS keys: {list(ROI_DEFS.keys())}")

        selected, debug_rows = _select_global_harmonics_for_condition_roi(
            cond_label=cond_label,
            roi_name=anchor,
            cfg=cfg,
            pids_used=pids_used,
            pid_to_path=pid_to_path,
            log_fn=log_fn,
        )
        for roi_name in ROI_DEFS.keys():
            global_hz_by_roi[roi_name] = list(selected)
        all_debug.extend(debug_rows)

    elif GLOBAL_SELECTION_MODE == "per_roi":
        for roi_name in ROI_DEFS.keys():
            selected, debug_rows = _select_global_harmonics_for_condition_roi(
                cond_label=cond_label,
                roi_name=roi_name,
                cfg=cfg,
                pids_used=pids_used,
                pid_to_path=pid_to_path,
                log_fn=log_fn,
            )
            global_hz_by_roi[roi_name] = selected
            all_debug.extend(debug_rows)
    else:
        raise ValueError(f"Unknown GLOBAL_SELECTION_MODE: {GLOBAL_SELECTION_MODE}")

    log_fn("-" * 110)

    df_debug = pd.DataFrame(all_debug)
    if not df_debug.empty:
        df_debug = df_debug.sort_values(["ROI", "hz"], kind="stable").reset_index(drop=True)

    return global_hz_by_roi, df_debug


def summarize_participant_file_global(
    xlsx_path: Path,
    condition_label: str,
    global_hz_by_roi: Dict[str, List[float]],
) -> List[Dict]:
    pid, pid_num = parse_participant_id(xlsx_path.name)
    df_snr, df_z, df_bca, harm_cols = read_participant_file(xlsx_path)

    rows: List[Dict] = []

    for roi_name, electrodes in ROI_DEFS.items():
        z_by_hz = compute_roi_harmonic_means(df_z, electrodes, harm_cols)
        snr_by_hz = compute_roi_harmonic_means(df_snr, electrodes, harm_cols)
        bca_by_hz = compute_roi_harmonic_means(df_bca, electrodes, harm_cols)

        use_hz = global_hz_by_roi.get(roi_name, [])
        mean_z = safe_mean(np.array([z_by_hz[hz] for hz in use_hz if hz in z_by_hz], dtype=float))
        mean_snr = safe_mean(np.array([snr_by_hz[hz] for hz in use_hz if hz in snr_by_hz], dtype=float))
        mean_bca = safe_mean(np.array([bca_by_hz[hz] for hz in use_hz if hz in bca_by_hz], dtype=float))

        rows.append({
            "condition_label": condition_label,
            "participant_id": pid,
            "participant_num": pid_num,
            "ROI": roi_name,
            "n_global_harmonics": int(len(use_hz)),
            "global_harmonics_hz": fmt_hz_list(use_hz),
            "mean_Z_global": mean_z,
            "mean_SNR_global": mean_snr,
            "mean_BCA_global": mean_bca,
            "source_file": str(xlsx_path),
        })

    return rows


def compute_ratio_rows_global_sets(
    pids_paired: List[str],
    pid_map_sem: Dict[str, Path],
    pid_map_col: Dict[str, Path],
    global_sem: Dict[str, List[float]],
    global_col: Dict[str, List[float]],
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []

    for pid in pids_paired:
        path_sem = pid_map_sem[pid]
        path_col = pid_map_col[pid]

        df_snr_sem, df_z_sem, df_bca_sem, harm_cols_sem = read_participant_file(path_sem)
        df_snr_col, df_z_col, df_bca_col, harm_cols_col = read_participant_file(path_col)

        for roi_name, electrodes in ROI_DEFS.items():
            z_sem = compute_roi_harmonic_means(df_z_sem, electrodes, harm_cols_sem)
            z_col = compute_roi_harmonic_means(df_z_col, electrodes, harm_cols_col)
            snr_sem = compute_roi_harmonic_means(df_snr_sem, electrodes, harm_cols_sem)
            snr_col = compute_roi_harmonic_means(df_snr_col, electrodes, harm_cols_col)
            bca_sem = compute_roi_harmonic_means(df_bca_sem, electrodes, harm_cols_sem)
            bca_col = compute_roi_harmonic_means(df_bca_col, electrodes, harm_cols_col)

            hz_sem = global_sem.get(roi_name, [])
            hz_col = global_col.get(roi_name, [])

            mean_z_sem = safe_mean(np.array([z_sem[h] for h in hz_sem if h in z_sem], dtype=float))
            mean_z_col = safe_mean(np.array([z_col[h] for h in hz_col if h in z_col], dtype=float))

            mean_snr_sem = safe_mean(np.array([snr_sem[h] for h in hz_sem if h in snr_sem], dtype=float))
            mean_snr_col = safe_mean(np.array([snr_col[h] for h in hz_col if h in snr_col], dtype=float))

            mean_bca_sem = safe_mean(np.array([bca_sem[h] for h in hz_sem if h in bca_sem], dtype=float))
            mean_bca_col = safe_mean(np.array([bca_col[h] for h in hz_col if h in bca_col], dtype=float))

            notes: List[str] = []
            ratio_z = float("nan")
            ratio_snr = float("nan")
            ratio_bca = float("nan")
            delta_bca = float("nan")

            if not (np.isfinite(mean_z_sem) and np.isfinite(mean_z_col)) or mean_z_col == 0:
                notes.append("bad_ratio_z")
            else:
                ratio_z = mean_z_sem / mean_z_col

            if not (np.isfinite(mean_snr_sem) and np.isfinite(mean_snr_col)) or mean_snr_col == 0:
                notes.append("bad_ratio_snr")
            else:
                ratio_snr = mean_snr_sem / mean_snr_col

            if not (np.isfinite(mean_bca_sem) and np.isfinite(mean_bca_col)):
                notes.append("nan_bca_ratio")
            else:
                if BCA_RATIO_POLICY == "positive_only":
                    if mean_bca_sem <= 0 or mean_bca_col <= 0:
                        notes.append("bca_nonpositive_positive_only")
                    elif mean_bca_col == 0:
                        notes.append("bca_zero_den")
                    else:
                        ratio_bca = mean_bca_sem / mean_bca_col
                elif BCA_RATIO_POLICY == "abs":
                    if abs(mean_bca_col) <= 0:
                        notes.append("bca_abs_zero_den")
                    else:
                        ratio_bca = abs(mean_bca_sem) / abs(mean_bca_col)
                elif BCA_RATIO_POLICY == "shift":
                    mn = min(mean_bca_sem, mean_bca_col)
                    shift = (-mn + BCA_SHIFT_EPS) if mn <= 0 else 0.0
                    denom = mean_bca_col + shift
                    if denom == 0:
                        notes.append("bca_shift_zero_den")
                    else:
                        ratio_bca = (mean_bca_sem + shift) / denom
                else:
                    notes.append("unknown_bca_ratio_policy")

            if not (np.isfinite(mean_bca_sem) and np.isfinite(mean_bca_col)):
                notes.append("nan_delta_bca")
            else:
                delta_bca = mean_bca_sem - mean_bca_col

            rows.append({
                "participant_id": pid,
                "ROI": roi_name,
                "n_sem_global": int(len(hz_sem)),
                "n_col_global": int(len(hz_col)),
                "sem_global_hz": fmt_hz_list(hz_sem),
                "col_global_hz": fmt_hz_list(hz_col),
                "mean_Z_sem_global": mean_z_sem,
                "mean_Z_col_global": mean_z_col,
                "ratio_Z": ratio_z,
                "mean_SNR_sem_global": mean_snr_sem,
                "mean_SNR_col_global": mean_snr_col,
                "ratio_SNR": ratio_snr,
                "mean_BCA_sem_global": mean_bca_sem,
                "mean_BCA_col_global": mean_bca_col,
                "ratio_BCA": ratio_bca,
                "delta_BCA": delta_bca,
                "ratio_notes": ";".join(notes) if notes else "",
                "source_file_semantic": str(path_sem),
                "source_file_color": str(path_col),
            })

    return rows


# -----------------------------
# Plotting
# -----------------------------

@dataclass(frozen=True)
class PlotPanel:
    val_col: str
    mean_col: str
    sem_col: str
    ylabel: str
    hline_y: Optional[float] = None


def _ordered_conditions(df: pd.DataFrame) -> List[str]:
    present = df["condition_label"].dropna().tolist()
    uniq: List[str] = []
    for x in present:
        if x not in uniq:
            uniq.append(x)

    ordered: List[str] = []
    for pref in [CONDITION_LABEL_A, CONDITION_LABEL_B]:
        if pref in uniq:
            ordered.append(pref)
    for x in uniq:
        if x not in ordered:
            ordered.append(x)
    return ordered


def make_raincloud_figure(
    df_part: pd.DataFrame,
    df_group: pd.DataFrame,
    panel: PlotPanel,
    out_path_no_ext: Path,
):
    palette = PALETTES.get(PALETTE_CHOICE, PALETTES["vibrant"])
    rois = list(ROI_DEFS.keys())
    conds = _ordered_conditions(df_part)

    seed = abs(hash(RUN_LABEL)) % (2**32)
    rng = np.random.default_rng(seed)

    fig, ax = plt.subplots(1, 1, figsize=(10, 6))
    plt.subplots_adjust(bottom=0.18)

    n_rois = max(len(rois), 1)
    cluster_width = 0.70
    step = cluster_width / n_rois
    roi_offsets = (np.arange(n_rois) - (n_rois - 1) / 2.0) * step
    violin_width = min(0.32, step * 0.85)

    for i, cond in enumerate(conds):
        for j, roi in enumerate(rois):
            pos = float(i + roi_offsets[j])
            color = palette.get(roi, palette["Default"])

            data = df_part[
                (df_part["condition_label"] == cond) & (df_part["ROI"] == roi)
            ][panel.val_col].dropna().to_numpy(dtype=float)
            if data.size == 0:
                continue

            v = ax.violinplot(data, positions=[pos], showextrema=False, widths=violin_width)
            for pc in v["bodies"]:
                pc.set_facecolor(color)
                pc.set_edgecolor("none")
                pc.set_alpha(0.30)
                clip_rect = Rectangle((-1e9, -1e9), 1e9 + pos, 2e9, transform=ax.transData)
                pc.set_clip_path(clip_rect)

            jitter = (rng.random(len(data)) - 0.5) * (step * 0.30)
            x_pts = np.full(len(data), pos + (violin_width * 0.22)) + jitter
            ax.scatter(x_pts, data, color=color, alpha=0.60, s=20, zorder=3)

            ax.boxplot(
                data,
                positions=[pos],
                widths=max(0.06, violin_width * 0.22),
                showfliers=False,
                patch_artist=True,
                boxprops=dict(facecolor="white", edgecolor=color, linewidth=1.5),
                whiskerprops=dict(color=color, linewidth=1.5),
                capprops=dict(color=color, linewidth=1.5),
                medianprops=dict(color="black", linewidth=2),
            )

            g = df_group[(df_group["condition_label"] == cond) & (df_group["ROI"] == roi)]
            if not g.empty:
                m = float(g.iloc[0][panel.mean_col])
                se = float(g.iloc[0][panel.sem_col])
                if np.isfinite(m):
                    if np.isfinite(se) and se > 0:
                        ax.errorbar(
                            [pos],
                            [m],
                            yerr=[se],
                            fmt="o",
                            color=color,
                            capsize=4,
                            elinewidth=2,
                            markersize=7,
                            zorder=6,
                        )
                    else:
                        ax.plot([pos], [m], marker="o", color=color, markersize=7, zorder=6)

    if panel.hline_y is not None:
        ax.axhline(panel.hline_y, color="red", linestyle=":", linewidth=2, alpha=0.8)

    ax.set_ylabel(panel.ylabel, fontsize=12, fontweight="bold")
    ax.grid(axis="y", linestyle="--", alpha=0.4)

    ax.set_xticks(np.arange(len(conds)))
    ax.set_xticklabels(conds, fontsize=11, fontweight="bold")

    handles = [
        plt.Line2D([0], [0], marker="o", color="w",
                   markerfacecolor=palette.get(r, "#777"), markersize=10, label=r)
        for r in rois
    ]
    ax.legend(handles=handles, loc="upper right", frameon=True)

    fig.savefig(out_path_no_ext.with_suffix(".pdf"), bbox_inches="tight")
    fig.savefig(out_path_no_ext.with_suffix(".png"), dpi=PNG_DPI, bbox_inches="tight")
    plt.close(fig)


# -----------------------------
# QOL: GUI Completion Dialog (Windows only)
# -----------------------------

def show_completion_dialog(output_path: Path):
    _app = QApplication.instance() or QApplication([])

    msg = QMessageBox()
    msg.setWindowTitle("Processing Complete")
    msg.setText("Aggregation finished successfully.")
    msg.setInformativeText("Would you like to open the output folder?")
    msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
    msg.setIcon(QMessageBox.Information)

    if msg.exec() == QMessageBox.Yes:
        os.startfile(str(output_path))


# -----------------------------
# Logging helpers (extremes)
# -----------------------------

def log_extremes_raw(df_part_used: pd.DataFrame, log_fn) -> None:
    def _log_metric(metric_col: str, metric_label: str) -> None:
        sub_all = df_part_used.dropna(subset=[metric_col]).copy()
        log_fn("-" * 110)
        log_fn(f"EXTREMES (RAW): {metric_label}")
        if sub_all.empty:
            log_fn(f"  No non-NaN values for {metric_col}.")
            return
        for (cond, roi), sub in sub_all.groupby(["condition_label", "ROI"], sort=True):
            sub = sub.sort_values(metric_col, kind="stable")
            lo = sub.iloc[0]
            hi = sub.iloc[-1]
            log_fn(
                f"  {cond} | ROI={roi} | LOW  {metric_label}: {fmt_float(lo[metric_col])} "
                f"({lo['participant_id']}, n_global={int(lo['n_global_harmonics'])})"
            )
            log_fn(
                f"  {cond} | ROI={roi} | HIGH {metric_label}: {fmt_float(hi[metric_col])} "
                f"({hi['participant_id']}, n_global={int(hi['n_global_harmonics'])})"
            )

    _log_metric("mean_Z_global", "Z (global)")
    _log_metric("mean_SNR_global", "SNR (global)")
    _log_metric("mean_BCA_global", "BCA (uV; global)")
    log_fn("-" * 110)


def log_extremes_ratios(df_ratio_used: pd.DataFrame, log_fn) -> None:
    def _log_metric(metric_col: str, metric_label: str) -> None:
        sub_all = df_ratio_used.dropna(subset=[metric_col]).copy()
        log_fn("-" * 110)
        log_fn(f"EXTREMES (RATIOS): {metric_label}")
        if sub_all.empty:
            log_fn(f"  No non-NaN values for {metric_col}.")
            return
        for roi, sub in sub_all.groupby("ROI", sort=True):
            sub = sub.sort_values(metric_col, kind="stable")
            lo = sub.iloc[0]
            hi = sub.iloc[-1]
            log_fn(
                f"  ROI={roi} | LOW  {metric_label}: {fmt_float(lo[metric_col])} "
                f"({lo['participant_id']})"
            )
            log_fn(
                f"  ROI={roi} | HIGH {metric_label}: {fmt_float(hi[metric_col])} "
                f"({hi['participant_id']})"
            )

    _log_metric("ratio_Z", "Z ratio")
    _log_metric("ratio_SNR", "SNR ratio")
    _log_metric("ratio_BCA", "BCA ratio")
    _log_metric("delta_BCA", "ΔBCA (uV)")
    log_fn("-" * 110)


# -----------------------------
# Main Execution
# -----------------------------

def main():
    cfg = RunConfig(Z_THRESHOLD, MAX_HZ, BASE_FREQ, EXCLUDE_BASE_UP_TO_HZ)
    out_dir = Path(OUTPUT_DIR).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    log_lines: List[str] = []

    def log(msg: str) -> None:
        print(msg)
        log_lines.append(msg)

    log("=" * 110)
    log(f"RUN_LABEL: {RUN_LABEL}")
    log(f"Timestamp: {dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log(f"Output Dir:  {str(out_dir)}")
    log("-" * 110)
    log("PARAMETERS")
    log(f"  Z_THRESHOLD: {Z_THRESHOLD}")
    log(f"  MAX_HZ: {MAX_HZ}")
    log(f"  BASE_FREQ: {BASE_FREQ}")
    log(f"  EXCLUDE_BASE_UP_TO_HZ: {EXCLUDE_BASE_UP_TO_HZ}")
    log(f"  CV_EPS: {CV_EPS} (CV = SD/Mean; NaN if |Mean|<=CV_EPS)")
    log(f"  ROIs: {list(ROI_DEFS.keys())}")
    log("GLOBAL HARMONIC SET (PER CONDITION; FIXED LIST)")
    log(f"  USE_GLOBAL_HARMONIC_SET: {USE_GLOBAL_HARMONIC_SET}")
    log(f"  GLOBAL_STOP_RULE: {GLOBAL_STOP_RULE}")
    log(f"  GLOBAL_MIN_HARMONICS: {GLOBAL_MIN_HARMONICS}")
    log(f"  GLOBAL_SELECTION_MODE: {GLOBAL_SELECTION_MODE}")
    log(f"  GLOBAL_SELECTION_ANCHOR_ROI: {GLOBAL_SELECTION_ANCHOR_ROI}")
    log(f"  STOP_RULE_ARM_AFTER_FIRST_SIG: {STOP_RULE_ARM_AFTER_FIRST_SIG}")
    log(f"  BCA_RATIO_POLICY: {BCA_RATIO_POLICY}")
    log("HARD EXCLUSION THRESHOLDS (AUTO)")
    log(f"  HARD_EXCLUSION_SNR_THRESH: {HARD_EXCLUSION_SNR_THRESH} (mean_SNR_global)")
    log(f"  HARD_EXCLUSION_BCA_THRESH: {HARD_EXCLUSION_BCA_THRESH} (mean_BCA_global; uV)")
    log("SOFT QC (REVIEW ONLY)")
    log(f"  SOFT_QC_ENABLED: {SOFT_QC_ENABLED}")
    log(f"  SOFT_QC_ROBUST_Z_THRESH: {SOFT_QC_ROBUST_Z_THRESH}")
    log(f"  SOFT_QC_MIN_N: {SOFT_QC_MIN_N}")
    log("=" * 110)

    def index_folder(path: str, label: str) -> Tuple[List[Path], Dict[str, Path]]:
        xlsx_files = sorted(Path(path).expanduser().glob("*.xlsx"))
        log(f"[{label}] Found {len(xlsx_files)} .xlsx files.")
        pid_to_path: Dict[str, Path] = {}
        for f in xlsx_files:
            pid, _ = parse_participant_id(f.name)
            pid_to_path[pid] = f
        return xlsx_files, pid_to_path

    files_a, pid_map_a = index_folder(INPUT_DIR_A, CONDITION_LABEL_A)
    files_b, pid_map_b = index_folder(INPUT_DIR_B, CONDITION_LABEL_B)

    # --- MANUAL EXCLUSION LOGIC ---
    if MANUAL_EXCLUDE:
        log("-" * 110)
        log(f"APPLYING MANUAL KILL LIST: {MANUAL_EXCLUDE}")

        # Filter Map A
        killed_a = [p for p in pid_map_a if p in MANUAL_EXCLUDE]
        for p in killed_a:
            del pid_map_a[p]

        # Filter Map B
        killed_b = [p for p in pid_map_b if p in MANUAL_EXCLUDE]
        for p in killed_b:
            del pid_map_b[p]

        log(f"  Dropped from {CONDITION_LABEL_A}: {killed_a}")
        log(f"  Dropped from {CONDITION_LABEL_B}: {killed_b}")
        log("-" * 110)
    # ------------------------------

    pids_a = sorted(list(pid_map_a.keys()), key=lambda s: int(s[1:]) if s[1:].isdigit() else 999999)
    pids_b = sorted(list(pid_map_b.keys()), key=lambda s: int(s[1:]) if s[1:].isdigit() else 999999)
    pids_paired = sorted(list(set(pids_a).intersection(set(pids_b))),
                         key=lambda s: int(s[1:]) if s[1:].isdigit() else 999999)

    log("-" * 110)
    log(f"Participants in {CONDITION_LABEL_A}: {len(pids_a)}")
    log(f"Participants in {CONDITION_LABEL_B}: {len(pids_b)}")
    log(f"Participants paired (present in BOTH folders): {len(pids_paired)}")
    log("-" * 110)

    # Base-rate exclusion report (limited)
    log("-" * 110)
    log(f"BASE-RATE EXCLUSION REPORT (Base Rate: {BASE_FREQ}Hz; up_to={EXCLUDE_BASE_UP_TO_HZ}Hz; report limited to <=MAX_HZ)")
    base_excluded = [BASE_FREQ, BASE_FREQ * 2]
    base_excluded = [x for x in base_excluded if x <= MAX_HZ]
    log(f"Excluded base-multiple frequencies (unique): {base_excluded}")
    log("-" * 110)

    if not pids_paired:
        raise RuntimeError("No paired participants found between the two folders.")

    # Global harmonic selection (per condition)
    global_a, df_debug_a = compute_global_harmonics_per_condition(
        cond_label=CONDITION_LABEL_A,
        cfg=cfg,
        pids_used=pids_paired,
        pid_to_path=pid_map_a,
        log_fn=log,
    )
    global_b, df_debug_b = compute_global_harmonics_per_condition(
        cond_label=CONDITION_LABEL_B,
        cfg=cfg,
        pids_used=pids_paired,
        pid_to_path=pid_map_b,
        log_fn=log,
    )

    # Participant-level summaries using per-condition global sets
    part_rows: List[Dict[str, Any]] = []
    for pid in pids_paired:
        part_rows.extend(summarize_participant_file_global(pid_map_a[pid], CONDITION_LABEL_A, global_a))
        part_rows.extend(summarize_participant_file_global(pid_map_b[pid], CONDITION_LABEL_B, global_b))

        # per participant logging (kept simple)
        for r in part_rows[-(len(ROI_DEFS) * 2):]:
            log(
                f"{r['participant_id']} | {r['condition_label']} | ROI={r['ROI']} | n_global={r['n_global_harmonics']} "
                f"| global=[{r['global_harmonics_hz']}] "
                f"| Z={fmt_float(r['mean_Z_global'])} "
                f"| SNR={fmt_float(r['mean_SNR_global'])} "
                f"| BCA(uV)={fmt_float(r['mean_BCA_global'])}"
            )

    df_part = pd.DataFrame(part_rows)

    # Soft QC flags (review-only)
    df_soft_qc = detect_soft_qc_flags(df_part, log)

    # Hard exclusions (auto)
    df_hard_excl, excluded_pids = detect_hard_exclusions(df_part, log)

    df_part["is_hard_excluded"] = df_part["participant_id"].isin(excluded_pids)
    df_part_used = df_part[~df_part["is_hard_excluded"]].copy()

    log(f"Participants paired total: {len(pids_paired)} | used after HARD exclusions: {df_part_used['participant_id'].nunique()}")
    log("-" * 110)

    # ZERO-GLOBAL-HARMONICS REPORT (after HARD exclusions)
    df_zero = df_part_used[df_part_used["n_global_harmonics"] == 0].copy()
    df_zero = df_zero[
        ["condition_label", "ROI", "participant_id", "participant_num", "source_file"]
    ].sort_values(["condition_label", "ROI", "participant_num"], kind="stable")

    log("ZERO-GLOBAL-HARMONICS REPORT (after HARD exclusions)")
    if df_zero.empty:
        log("  No participants with zero global harmonics.")
    else:
        counts = df_zero.groupby(["condition_label", "ROI"]).size().reset_index(name="n_zero_global")
        for _, row in counts.iterrows():
            log(f"  {row['condition_label']} | ROI={row['ROI']} | n_zero_global={int(row['n_zero_global'])}")
        log("  Participant list (condition | ROI | participant_id):")
        for _, r in df_zero.iterrows():
            log(f"  {r['condition_label']} | {r['ROI']} | {r['participant_id']}")

    # Group summary (RAW; USED) + CV
    raw_group_rows: List[Dict[str, Any]] = []
    for (cond, roi), sub in df_part_used.groupby(["condition_label", "ROI"], sort=True):
        n_total = int(len(sub))

        z_arr = pd.to_numeric(sub["mean_Z_global"], errors="coerce").to_numpy(dtype=float)
        snr_arr = pd.to_numeric(sub["mean_SNR_global"], errors="coerce").to_numpy(dtype=float)
        bca_arr = pd.to_numeric(sub["mean_BCA_global"], errors="coerce").to_numpy(dtype=float)

        m_z, sd_z, se_z = safe_mean(z_arr), safe_sd(z_arr), safe_sem(z_arr)
        m_s, sd_s, se_s = safe_mean(snr_arr), safe_sd(snr_arr), safe_sem(snr_arr)
        m_b, sd_b, se_b = safe_mean(bca_arr), safe_sd(bca_arr), safe_sem(bca_arr)

        raw_group_rows.append({
            "condition_label": cond,
            "ROI": roi,
            "n_total_participants": n_total,
            "n_used_Z": int(np.sum(np.isfinite(z_arr))),
            "mean_Z": m_z,
            "sd_Z": sd_z,
            "sem_Z": se_z,
            "cv_Z": safe_cv(m_z, sd_z),
            "n_used_SNR": int(np.sum(np.isfinite(snr_arr))),
            "mean_SNR": m_s,
            "sd_SNR": sd_s,
            "sem_SNR": se_s,
            "cv_SNR": safe_cv(m_s, sd_s),
            "n_used_BCA": int(np.sum(np.isfinite(bca_arr))),
            "mean_BCA_uV": m_b,
            "sd_BCA_uV": sd_b,
            "sem_BCA_uV": se_b,
            "cv_BCA": safe_cv(m_b, sd_b),
        })

    df_group_raw = pd.DataFrame(raw_group_rows).sort_values(["condition_label", "ROI"], kind="stable").reset_index(drop=True)

    log("-" * 110)
    log("GROUP SUMMARY (RAW; USED; Mean / SD / SEM / CV) [global harmonics applied per condition]")
    log(df_group_raw.to_string(index=False))
    log("-" * 110)
    log("CV NOTE: CV = SD/Mean; CV is NaN when |Mean| is near 0 (unstable).")
    log("-" * 110)

    # Extremes (RAW; USED)
    log_extremes_raw(df_part_used, log)

    # Ratio table (Semantic/Color) using per-condition global sets
    pids_used_for_ratio = [pid for pid in pids_paired if pid not in excluded_pids]
    log("-" * 110)
    log("RATIO TABLE (Semantic/Color) using PER-CONDITION global harmonic sets")
    log(f"  Semantic condition label: {CONDITION_LABEL_A}")
    log(f"  Color condition label:    {CONDITION_LABEL_B}")
    log(f"  Paired participants used: {len(pids_used_for_ratio)}")
    log(f"  BCA_RATIO_POLICY: {BCA_RATIO_POLICY}")
    log("-" * 110)

    ratio_rows = compute_ratio_rows_global_sets(
        pids_paired=pids_used_for_ratio,
        pid_map_sem=pid_map_a,
        pid_map_col=pid_map_b,
        global_sem=global_a,
        global_col=global_b,
    )
    df_ratio = pd.DataFrame(ratio_rows)

    for _, rr in df_ratio.iterrows():
        log(
            f"{rr['participant_id']} | ROI={rr['ROI']} | ratioZ={fmt_float(rr['ratio_Z'])} | "
            f"ratioSNR={fmt_float(rr['ratio_SNR'])} | ratioBCA={fmt_float(rr['ratio_BCA'])} | "
            f"dBCA={fmt_float(rr['delta_BCA'])} | notes={rr['ratio_notes']}"
        )

    # Ratio group summary
    ratio_group_rows: List[Dict[str, Any]] = []
    for roi, sub in df_ratio.groupby("ROI", sort=True):
        rz = pd.to_numeric(sub["ratio_Z"], errors="coerce").to_numpy(dtype=float)
        rs = pd.to_numeric(sub["ratio_SNR"], errors="coerce").to_numpy(dtype=float)
        rb = pd.to_numeric(sub["ratio_BCA"], errors="coerce").to_numpy(dtype=float)
        db = pd.to_numeric(sub["delta_BCA"], errors="coerce").to_numpy(dtype=float)

        ratio_group_rows.append({
            "condition_label": "Semantic/Color (global per-condition harmonic sets)",
            "ROI": roi,
            "n_total_paired": int(len(sub)),
            "n_used_ratio_Z": int(np.sum(np.isfinite(rz))),
            "mean_ratio_Z": safe_mean(rz),
            "sd_ratio_Z": safe_sd(rz),
            "sem_ratio_Z": safe_sem(rz),
            "cv_ratio_Z": safe_cv(safe_mean(rz), safe_sd(rz)),
            "n_used_ratio_SNR": int(np.sum(np.isfinite(rs))),
            "mean_ratio_SNR": safe_mean(rs),
            "sd_ratio_SNR": safe_sd(rs),
            "sem_ratio_SNR": safe_sem(rs),
            "cv_ratio_SNR": safe_cv(safe_mean(rs), safe_sd(rs)),
            "n_used_ratio_BCA": int(np.sum(np.isfinite(rb))),
            "mean_ratio_BCA": safe_mean(rb),
            "sd_ratio_BCA": safe_sd(rb),
            "sem_ratio_BCA": safe_sem(rb),
            "cv_ratio_BCA": safe_cv(safe_mean(rb), safe_sd(rb)),
            "n_used_delta_BCA": int(np.sum(np.isfinite(db))),
            "mean_delta_BCA_uV": safe_mean(db),
            "sd_delta_BCA_uV": safe_sd(db),
            "sem_delta_BCA_uV": safe_sem(db),
            "cv_delta_BCA": float("nan"),
        })

    df_ratio_group = pd.DataFrame(ratio_group_rows).sort_values(["ROI"], kind="stable").reset_index(drop=True)

    log("-" * 110)
    log("RATIO GROUP SUMMARY (USED; Semantic/Color) [per-condition global harmonic sets]")
    log(df_ratio_group.to_string(index=False))
    log("-" * 110)

    # Extremes (RATIOS)
    log_extremes_ratios(df_ratio, log)

    # Plotting (RAW; USED)
    make_raincloud_figure(
        df_part_used,
        df_group_raw,
        PlotPanel(val_col="mean_Z_global", mean_col="mean_Z", sem_col="sem_Z", ylabel="Z (global)", hline_y=Z_THRESHOLD),
        out_dir / f"Plot_{RUN_LABEL}_RAW_Z",
    )
    make_raincloud_figure(
        df_part_used,
        df_group_raw,
        PlotPanel(val_col="mean_SNR_global", mean_col="mean_SNR", sem_col="sem_SNR", ylabel="SNR (global)"),
        out_dir / f"Plot_{RUN_LABEL}_RAW_SNR",
    )
    make_raincloud_figure(
        df_part_used,
        df_group_raw,
        PlotPanel(val_col="mean_BCA_global", mean_col="mean_BCA_uV", sem_col="sem_BCA_uV", ylabel="BCA (µV; global)"),
        out_dir / f"Plot_{RUN_LABEL}_RAW_BCA",
    )

    # Plotting (RATIOS)
    # Reuse raincloud by treating ratio as "condition_label" single group is not needed; plot as two conditions is not applicable.
    # Keep plots simple by writing per-ROI distributions in a single "condition".
    df_ratio_plot = df_ratio.copy()
    df_ratio_plot["condition_label"] = "Semantic/Color"
    df_ratio_group_plot = df_ratio_group.copy()
    df_ratio_group_plot["condition_label"] = "Semantic/Color"

    make_raincloud_figure(
        df_ratio_plot.rename(columns={"ratio_Z": "val"}),
        df_ratio_group_plot.rename(columns={"mean_ratio_Z": "mean", "sem_ratio_Z": "sem"}),
        PlotPanel(val_col="val", mean_col="mean", sem_col="sem", ylabel="Z ratio"),
        out_dir / f"Plot_{RUN_LABEL}_RATIO_Z",
    )
    make_raincloud_figure(
        df_ratio_plot.rename(columns={"ratio_SNR": "val"}),
        df_ratio_group_plot.rename(columns={"mean_ratio_SNR": "mean", "sem_ratio_SNR": "sem"}),
        PlotPanel(val_col="val", mean_col="mean", sem_col="sem", ylabel="SNR ratio"),
        out_dir / f"Plot_{RUN_LABEL}_RATIO_SNR",
    )
    make_raincloud_figure(
        df_ratio_plot.rename(columns={"ratio_BCA": "val"}),
        df_ratio_group_plot.rename(columns={"mean_ratio_BCA": "mean", "sem_ratio_BCA": "sem"}),
        PlotPanel(val_col="val", mean_col="mean", sem_col="sem", ylabel="BCA ratio"),
        out_dir / f"Plot_{RUN_LABEL}_RATIO_BCA",
    )
    make_raincloud_figure(
        df_ratio_plot.rename(columns={"delta_BCA": "val"}),
        df_ratio_group_plot.rename(columns={"mean_delta_BCA_uV": "mean", "sem_delta_BCA_uV": "sem"}),
        PlotPanel(val_col="val", mean_col="mean", sem_col="sem", ylabel="ΔBCA (µV)"),
        out_dir / f"Plot_{RUN_LABEL}_RATIO_DBCA",
    )

    # Excel + log outputs
    out_xlsx = out_dir / f"Metrics_{RUN_LABEL}.xlsx"
    with pd.ExcelWriter(out_xlsx) as writer:
        df_part.to_excel(writer, sheet_name="Participant_Data_ALL", index=False)
        df_part_used.to_excel(writer, sheet_name="Participant_Data_USED", index=False)
        df_hard_excl.to_excel(writer, sheet_name="Hard_Exclusions", index=False)
        df_soft_qc.to_excel(writer, sheet_name="Soft_QC_Flags", index=False)
        df_group_raw.to_excel(writer, sheet_name="Group_Summary_RAW_USED", index=False)
        df_zero.to_excel(writer, sheet_name="Zero_Global_USED", index=False)
        df_debug_a.to_excel(writer, sheet_name="GlobalSelect_Debug_Sem", index=False)
        df_debug_b.to_excel(writer, sheet_name="GlobalSelect_Debug_Col", index=False)
        df_ratio.to_excel(writer, sheet_name="Ratios_Participant_USED", index=False)
        df_ratio_group.to_excel(writer, sheet_name="Ratios_Group_USED", index=False)

    out_log = out_dir / f"Log_{RUN_LABEL}.txt"
    out_log.write_text("\n".join(log_lines) + "\n", encoding="utf-8")

    log("=" * 110)
    log(f"Success! Outputs saved to: {out_dir}")
    log(f"Excel: {out_xlsx.name}")
    log(f"Log:   {out_log.name}")
    log("=" * 110)

    show_completion_dialog(out_dir)


if __name__ == "__main__":
    main()
