#!/usr/bin/env python3
"""
ROI SNR/Z/BCA Aggregator for FPVS Excel Outputs (single-file pipeline)

PURPOSE:
Compute participant-level ROI means for Z, SNR, and BCA across significant oddball harmonics,
summarize group statistics, compute common-harmonic-set ratios/deltas, and generate plots/logs.

PIPELINE STEPS:
1. Batch read Excel outputs from two condition folders.
2. Compute participant-level ROI means for Z, SNR, and BCA across selected significant harmonics.
3. Exclude base-rate harmonics (6 Hz multiples) from significance selection.
4. Aggregate group-level metrics (Mean, SD, SEM, CV) with N_total and N_used.
5. Compute common-set metrics per participant/ROI using intersection of significant harmonics:
   - Z ratio = meanZ_sem_common / meanZ_col_common
   - SNR ratio = meanSNR_sem_common / meanSNR_col_common
   - delta_BCA = meanBCA_sem_common - meanBCA_col_common
6. Generate plots (PDF + PNG): RAW (Z/SNR/BCA) and COMMON-SET (Z ratio / SNR ratio / delta_BCA).
7. Diagnostic reporting:
   - base-rate harmonic exclusions
   - zero-significant participants
   - extremes (highest/lowest)
   - hard-threshold exclusions (auto)
   - soft QC flags (robust MAD-based) for review only (no auto exclusion)

OUTLIER / EXCLUSION POLICY:
A) HARD EXCLUSIONS (AUTO):
   - If any participant has mean_SNR_selected > HARD_EXCLUSION_SNR_THRESH (any condition/ROI), exclude globally.
   - If any participant has mean_BCA_selected > HARD_EXCLUSION_BCA_THRESH (any condition/ROI), exclude globally.

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

COMMON_LABEL = "Semantic/Color (common sig intersection)"

# CV can be unstable if mean is near 0. For such cases, return NaN.
CV_EPS = 1e-9

# For soft QC reporting (review only)
SOFT_QC_METRICS_RAW = [
    ("mean_Z_selected", "Z"),
    ("mean_SNR_selected", "SNR"),
    ("mean_BCA_selected", "BCA(uV)"),
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
      - any mean_SNR_selected > HARD_EXCLUSION_SNR_THRESH
      - any mean_BCA_selected > HARD_EXCLUSION_BCA_THRESH
    across any condition/ROI.

    Returns:
      df_excl_rows: rows that triggered exclusion (one per trigger)
      excluded_pids: participants to exclude globally
    """
    records: List[Dict[str, Any]] = []
    excluded: Set[str] = set()

    # SNR triggers
    if "mean_SNR_selected" in df_part.columns:
        snr_vals = pd.to_numeric(df_part["mean_SNR_selected"], errors="coerce")
        mask = snr_vals > HARD_EXCLUSION_SNR_THRESH
        for idx in df_part.index[mask.fillna(False)]:
            pid = str(df_part.loc[idx, "participant_id"])
            excluded.add(pid)
            records.append({
                "participant_id": pid,
                "participant_num": df_part.loc[idx, "participant_num"],
                "condition_label": df_part.loc[idx, "condition_label"],
                "ROI": df_part.loc[idx, "ROI"],
                "metric": "SNR (sel)",
                "value": df_part.loc[idx, "mean_SNR_selected"],
                "threshold": HARD_EXCLUSION_SNR_THRESH,
                "source_file": df_part.loc[idx, "source_file"],
            })

    # BCA triggers
    if "mean_BCA_selected" in df_part.columns:
        bca_vals = pd.to_numeric(df_part["mean_BCA_selected"], errors="coerce")
        mask = bca_vals > HARD_EXCLUSION_BCA_THRESH
        for idx in df_part.index[mask.fillna(False)]:
            pid = str(df_part.loc[idx, "participant_id"])
            excluded.add(pid)
            records.append({
                "participant_id": pid,
                "participant_num": df_part.loc[idx, "participant_num"],
                "condition_label": df_part.loc[idx, "condition_label"],
                "ROI": df_part.loc[idx, "ROI"],
                "metric": "BCA (uV; sel)",
                "value": df_part.loc[idx, "mean_BCA_selected"],
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
    log_fn(f"  Rule: exclude participant globally if any SNR(sel) > {HARD_EXCLUSION_SNR_THRESH} "
           f"or any BCA(sel) > {HARD_EXCLUSION_BCA_THRESH}")
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


def select_significant_harmonics(z_by_hz: Dict[float, float], cfg: RunConfig) -> Tuple[List[float], List[float]]:
    sig: List[float] = []
    excluded: List[float] = []
    for hz, zval in z_by_hz.items():
        if is_base_multiple(hz, cfg.base_freq, cfg.exclude_base_up_to_hz):
            excluded.append(hz)
            continue
        if hz <= cfg.max_hz and zval > cfg.z_threshold:
            sig.append(hz)
    return sorted(sig), sorted(list(set(excluded)))


def read_participant_file(xlsx_path: Path) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, List[str]]:
    df_snr = pd.read_excel(xlsx_path, sheet_name=SHEET_SNR)
    df_z = pd.read_excel(xlsx_path, sheet_name=SHEET_Z)
    df_bca = pd.read_excel(xlsx_path, sheet_name=SHEET_BCA)
    harm_cols = [c for c in df_z.columns if c != ELECTRODE_COL]
    return df_snr, df_z, df_bca, harm_cols


def summarize_participant_file(
    xlsx_path: Path,
    condition_label: str,
    cfg: RunConfig,
) -> Tuple[List[Dict], List[float]]:
    pid, pid_num = parse_participant_id(xlsx_path.name)
    df_snr, df_z, df_bca, harm_cols = read_participant_file(xlsx_path)

    rows: List[Dict] = []
    all_excluded: List[float] = []

    for roi_name, electrodes in ROI_DEFS.items():
        z_by_hz = compute_roi_harmonic_means(df_z, electrodes, harm_cols)
        sig_hz, excluded = select_significant_harmonics(z_by_hz, cfg)
        all_excluded.extend(excluded)

        snr_by_hz = compute_roi_harmonic_means(df_snr, electrodes, harm_cols)
        bca_by_hz = compute_roi_harmonic_means(df_bca, electrodes, harm_cols)

        mean_z = safe_mean(np.array([z_by_hz[hz] for hz in sig_hz], dtype=float))
        mean_snr = safe_mean(np.array([snr_by_hz[hz] for hz in sig_hz], dtype=float))
        mean_bca = safe_mean(np.array([bca_by_hz[hz] for hz in sig_hz], dtype=float))

        rows.append({
            "condition_label": condition_label,
            "participant_id": pid,
            "participant_num": pid_num,
            "ROI": roi_name,
            "n_significant_harmonics": int(len(sig_hz)),
            "significant_harmonics_hz": fmt_hz_list(sig_hz),
            "mean_Z_selected": mean_z,
            "mean_SNR_selected": mean_snr,
            "mean_BCA_selected": mean_bca,
            "source_file": str(xlsx_path),
        })

    return rows, sorted(list(set(all_excluded)))


def compute_common_set_metrics_for_participant(
    pid: str,
    roi_name: str,
    cfg: RunConfig,
    path_sem: Path,
    path_col: Path,
) -> Dict[str, Any]:
    df_snr_sem, df_z_sem, df_bca_sem, harm_cols = read_participant_file(path_sem)
    df_snr_col, df_z_col, df_bca_col, harm_cols2 = read_participant_file(path_col)

    electrodes = ROI_DEFS[roi_name]

    z_sem_by_hz = compute_roi_harmonic_means(df_z_sem, electrodes, harm_cols)
    z_col_by_hz = compute_roi_harmonic_means(df_z_col, electrodes, harm_cols2)

    sig_sem, _ = select_significant_harmonics(z_sem_by_hz, cfg)
    sig_col, _ = select_significant_harmonics(z_col_by_hz, cfg)

    common = sorted(list(set(sig_sem).intersection(set(sig_col))))

    snr_sem_by_hz = compute_roi_harmonic_means(df_snr_sem, electrodes, harm_cols)
    snr_col_by_hz = compute_roi_harmonic_means(df_snr_col, electrodes, harm_cols2)

    bca_sem_by_hz = compute_roi_harmonic_means(df_bca_sem, electrodes, harm_cols)
    bca_col_by_hz = compute_roi_harmonic_means(df_bca_col, electrodes, harm_cols2)

    mean_z_sem_common = safe_mean(np.array([z_sem_by_hz[hz] for hz in common], dtype=float))
    mean_z_col_common = safe_mean(np.array([z_col_by_hz[hz] for hz in common], dtype=float))

    mean_snr_sem_common = safe_mean(np.array([snr_sem_by_hz[hz] for hz in common], dtype=float))
    mean_snr_col_common = safe_mean(np.array([snr_col_by_hz[hz] for hz in common], dtype=float))

    mean_bca_sem_common = safe_mean(np.array([bca_sem_by_hz[hz] for hz in common], dtype=float))
    mean_bca_col_common = safe_mean(np.array([bca_col_by_hz[hz] for hz in common], dtype=float))

    notes: List[str] = []
    ratio_z = float("nan")
    ratio_snr = float("nan")
    delta_bca = float("nan")

    if len(common) == 0:
        notes.append("no_common_significant_harmonics")
    else:
        if not np.isfinite(mean_z_sem_common) or not np.isfinite(mean_z_col_common):
            notes.append("nan_common_mean_z")
        elif mean_z_col_common == 0:
            notes.append("zero_denominator_mean_z")
        else:
            ratio_z = mean_z_sem_common / mean_z_col_common

        if not np.isfinite(mean_snr_sem_common) or not np.isfinite(mean_snr_col_common):
            notes.append("nan_common_mean_snr")
        elif mean_snr_col_common == 0:
            notes.append("zero_denominator_mean_snr")
        else:
            ratio_snr = mean_snr_sem_common / mean_snr_col_common

        if not np.isfinite(mean_bca_sem_common) or not np.isfinite(mean_bca_col_common):
            notes.append("nan_common_mean_bca")
        else:
            delta_bca = mean_bca_sem_common - mean_bca_col_common

    return {
        "condition_label": COMMON_LABEL,
        "participant_id": pid,
        "ROI": roi_name,
        "n_sig_sem": int(len(sig_sem)),
        "n_sig_col": int(len(sig_col)),
        "n_common_sig": int(len(common)),
        "sig_sem_hz": fmt_hz_list(sig_sem),
        "sig_col_hz": fmt_hz_list(sig_col),
        "common_sig_hz": fmt_hz_list(common),
        "mean_Z_sem_common": mean_z_sem_common,
        "mean_Z_col_common": mean_z_col_common,
        "ratio_Z_common": ratio_z,
        "mean_SNR_sem_common": mean_snr_sem_common,
        "mean_SNR_col_common": mean_snr_col_common,
        "ratio_SNR_common": ratio_snr,
        "mean_BCA_sem_common": mean_bca_sem_common,
        "mean_BCA_col_common": mean_bca_col_common,
        "delta_BCA_common": delta_bca,
        "common_set_notes": ";".join(notes) if notes else "",
        "source_file_semantic": str(path_sem),
        "source_file_color": str(path_col),
    }


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
    for pref in [CONDITION_LABEL_A, CONDITION_LABEL_B, COMMON_LABEL]:
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
                f"({lo['participant_id']}, n_sig={int(lo['n_significant_harmonics'])})"
            )
            log_fn(
                f"  {cond} | ROI={roi} | HIGH {metric_label}: {fmt_float(hi[metric_col])} "
                f"({hi['participant_id']}, n_sig={int(hi['n_significant_harmonics'])})"
            )

    _log_metric("mean_Z_selected", "Z (sel)")
    _log_metric("mean_SNR_selected", "SNR (sel)")
    _log_metric("mean_BCA_selected", "BCA (uV; sel)")
    log_fn("-" * 110)


def log_extremes_common(df_common_used: pd.DataFrame, log_fn) -> None:
    def _log_metric(metric_col: str, metric_label: str) -> None:
        sub_all = df_common_used.dropna(subset=[metric_col]).copy()
        log_fn("-" * 110)
        log_fn(f"EXTREMES (COMMON-SET): {metric_label}")
        if sub_all.empty:
            log_fn(f"  No non-NaN values for {metric_col}.")
            return
        for roi, sub in sub_all.groupby("ROI", sort=True):
            sub = sub.sort_values(metric_col, kind="stable")
            lo = sub.iloc[0]
            hi = sub.iloc[-1]
            log_fn(
                f"  ROI={roi} | LOW  {metric_label}: {fmt_float(lo[metric_col])} "
                f"({lo['participant_id']}, n_common={int(lo['n_common_sig'])}, common=[{lo['common_sig_hz']}])"
            )
            log_fn(
                f"  ROI={roi} | HIGH {metric_label}: {fmt_float(hi[metric_col])} "
                f"({hi['participant_id']}, n_common={int(hi['n_common_sig'])}, common=[{hi['common_sig_hz']}])"
            )

    _log_metric("ratio_Z_common", "Z ratio")
    _log_metric("ratio_SNR_common", "SNR ratio")
    _log_metric("delta_BCA_common", "ΔBCA (uV)")
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
    log("HARD EXCLUSION THRESHOLDS (AUTO)")
    log(f"  HARD_EXCLUSION_SNR_THRESH: {HARD_EXCLUSION_SNR_THRESH} (mean_SNR_selected)")
    log(f"  HARD_EXCLUSION_BCA_THRESH: {HARD_EXCLUSION_BCA_THRESH} (mean_BCA_selected; uV)")
    log("SOFT QC (REVIEW ONLY)")
    log(f"  SOFT_QC_ENABLED: {SOFT_QC_ENABLED}")
    log(f"  SOFT_QC_ROBUST_Z_THRESH: {SOFT_QC_ROBUST_Z_THRESH}")
    log(f"  SOFT_QC_MIN_N: {SOFT_QC_MIN_N}")
    log("=" * 110)

    def process_folder(path: str, label: str) -> Tuple[pd.DataFrame, List[float], Dict[str, Path]]:
        xlsx_files = sorted(Path(path).expanduser().glob("*.xlsx"))
        log(f"[{label}] Found {len(xlsx_files)} .xlsx files.")
        all_rows: List[Dict] = []
        total_excluded: List[float] = []
        pid_to_path: Dict[str, Path] = {}

        for f in xlsx_files:
            rows, exc = summarize_participant_file(f, label, cfg)
            all_rows.extend(rows)
            total_excluded.extend(exc)

            pid, _ = parse_participant_id(f.name)
            pid_to_path[pid] = f

            for r in rows:
                log(
                    f"{pid} | {label} | ROI={r['ROI']} | n_sig={r['n_significant_harmonics']} "
                    f"| sig=[{r['significant_harmonics_hz']}] "
                    f"| Z={fmt_float(r['mean_Z_selected'])} "
                    f"| SNR={fmt_float(r['mean_SNR_selected'])} "
                    f"| BCA(uV)={fmt_float(r['mean_BCA_selected'])}"
                )

        return pd.DataFrame(all_rows), sorted(list(set(total_excluded))), pid_to_path

    df_a, exc_a, pid_map_a = process_folder(INPUT_DIR_A, CONDITION_LABEL_A)
    df_b, exc_b, pid_map_b = process_folder(INPUT_DIR_B, CONDITION_LABEL_B)

    excluded_all = sorted(list(set(exc_a + exc_b)))
    log("-" * 110)
    log(f"HARMONIC EXCLUSION REPORT (Base Rate: {BASE_FREQ}Hz)")
    log(f"Excluded Frequencies (unique): {excluded_all}")
    log("-" * 110)

    df_part = pd.concat([df_a, df_b], ignore_index=True)

    # Soft QC flags (review-only)
    df_soft_qc = detect_soft_qc_flags(df_part, log)

    # Hard exclusions (auto)
    df_hard_excl, excluded_pids = detect_hard_exclusions(df_part, log)

    df_part["is_hard_excluded"] = df_part["participant_id"].isin(excluded_pids)
    df_part_used = df_part[~df_part["is_hard_excluded"]].copy()

    log(f"Participants total (RAW rows): {df_part['participant_id'].nunique()} | "
        f"Participants used after HARD exclusions: {df_part_used['participant_id'].nunique()}")

    # Zero-significant report (USED)
    df_zero = df_part_used[df_part_used["n_significant_harmonics"] == 0].copy()
    df_zero = df_zero[
        ["condition_label", "ROI", "participant_id", "participant_num", "source_file"]
    ].sort_values(["condition_label", "ROI", "participant_num"], kind="stable")

    log("ZERO-SIGNIFICANT-HARMONICS REPORT (after HARD exclusions)")
    if df_zero.empty:
        log("  No participants with zero significant harmonics.")
    else:
        counts = df_zero.groupby(["condition_label", "ROI"]).size().reset_index(name="n_zero_sig")
        for _, row in counts.iterrows():
            log(f"  {row['condition_label']} | ROI={row['ROI']} | n_zero_sig={int(row['n_zero_sig'])}")
        log("  Participant list (condition | ROI | participant_id):")
        for _, r in df_zero.iterrows():
            log(f"  {r['condition_label']} | {r['ROI']} | {r['participant_id']}")

    # Group summary (RAW; USED) + CV
    raw_group_rows: List[Dict] = []
    for (cond, roi), sub in df_part_used.groupby(["condition_label", "ROI"], sort=True):
        n_total = int(len(sub))

        z_arr = pd.to_numeric(sub["mean_Z_selected"], errors="coerce").to_numpy(dtype=float)
        snr_arr = pd.to_numeric(sub["mean_SNR_selected"], errors="coerce").to_numpy(dtype=float)
        bca_arr = pd.to_numeric(sub["mean_BCA_selected"], errors="coerce").to_numpy(dtype=float)

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
    log("GROUP SUMMARY (RAW; USED; Mean / SD / SEM / CV)")
    log(df_group_raw.to_string(index=False))
    log("-" * 110)
    log("CV NOTE: CV = SD/Mean; CV is NaN when |Mean| is near 0 (unstable).")
    log("-" * 110)

    # Extremes (RAW; USED)
    log_extremes_raw(df_part_used, log)

    # Common-set computation (USED participants only)
    log("COMMON-SET METRICS (INTERSECTION; after HARD exclusions)")

    pids_paired = sorted(list(set(pid_map_a.keys()).intersection(set(pid_map_b.keys()))))
    if excluded_pids:
        pids_paired = [pid for pid in pids_paired if pid not in excluded_pids]

    log(f"Paired participants (present in BOTH folders, used): {len(pids_paired)}")

    common_rows: List[Dict[str, Any]] = []
    for pid in pids_paired:
        path_sem = pid_map_a[pid]
        path_col = pid_map_b[pid]
        for roi_name in ROI_DEFS.keys():
            rr = compute_common_set_metrics_for_participant(pid, roi_name, cfg, path_sem, path_col)
            common_rows.append(rr)
            log(
                f"{pid} | ROI={roi_name} | common(n={rr['n_common_sig']}):[{rr['common_sig_hz']}] "
                f"| ratioZ={fmt_float(rr['ratio_Z_common'])} "
                f"| ratioSNR={fmt_float(rr['ratio_SNR_common'])} "
                f"| dBCA(uV)={fmt_float(rr['delta_BCA_common'])} "
                f"| notes={rr['common_set_notes']}"
            )

    df_common_part = pd.DataFrame(common_rows)

    # participant_num mapping for stable sorting (USED only)
    pid_to_num: Dict[str, int] = {}
    for _, r in df_part_used[["participant_id", "participant_num"]].dropna().drop_duplicates().iterrows():
        pid_to_num[str(r["participant_id"])] = int(r["participant_num"])
    if not df_common_part.empty:
        df_common_part["participant_num"] = df_common_part["participant_id"].map(pid_to_num)

    # Common-set group summary + CV (ratios only; delta_BCA CV suppressed)
    common_group_rows: List[Dict[str, Any]] = []
    if not df_common_part.empty:
        for roi, sub in df_common_part.groupby("ROI", sort=True):
            rz = pd.to_numeric(sub["ratio_Z_common"], errors="coerce").to_numpy(dtype=float)
            rs = pd.to_numeric(sub["ratio_SNR_common"], errors="coerce").to_numpy(dtype=float)
            db = pd.to_numeric(sub["delta_BCA_common"], errors="coerce").to_numpy(dtype=float)

            m_rz, sd_rz, se_rz = safe_mean(rz), safe_sd(rz), safe_sem(rz)
            m_rs, sd_rs, se_rs = safe_mean(rs), safe_sd(rs), safe_sem(rs)
            m_db, sd_db, se_db = safe_mean(db), safe_sd(db), safe_sem(db)

            common_group_rows.append({
                "condition_label": COMMON_LABEL,
                "ROI": roi,
                "n_total_paired": int(len(sub)),
                "n_with_common_sig_gt0": int(np.sum(sub["n_common_sig"].to_numpy(dtype=int) > 0)),
                "n_used_ratio_Z": int(np.sum(np.isfinite(rz))),
                "mean_ratio_Z": m_rz,
                "sd_ratio_Z": sd_rz,
                "sem_ratio_Z": se_rz,
                "cv_ratio_Z": safe_cv(m_rz, sd_rz),
                "n_used_ratio_SNR": int(np.sum(np.isfinite(rs))),
                "mean_ratio_SNR": m_rs,
                "sd_ratio_SNR": sd_rs,
                "sem_ratio_SNR": se_rs,
                "cv_ratio_SNR": safe_cv(m_rs, sd_rs),
                "n_used_delta_BCA": int(np.sum(np.isfinite(db))),
                "mean_delta_BCA_uV": m_db,
                "sd_delta_BCA_uV": sd_db,
                "sem_delta_BCA_uV": se_db,
                "cv_delta_BCA": float("nan"),
            })

    df_common_group = pd.DataFrame(common_group_rows).sort_values(["ROI"], kind="stable").reset_index(drop=True)

    log("-" * 110)
    log("COMMON-SET GROUP SUMMARY (USED; ratios for Z/SNR; delta for BCA; CV_delta_BCA suppressed)")
    log(df_common_group.to_string(index=False) if not df_common_group.empty else "  (no common-set rows)")
    log("-" * 110)

    # Extremes (COMMON-SET; USED)
    if not df_common_part.empty:
        log_extremes_common(df_common_part, log)

    # Plotting (short y-labels; separate plots; USED)
    make_raincloud_figure(
        df_part_used,
        df_group_raw.rename(columns={"mean_Z": "mean_Z", "sem_Z": "sem_Z"}),
        PlotPanel(val_col="mean_Z_selected", mean_col="mean_Z", sem_col="sem_Z", ylabel="Z (sel)", hline_y=Z_THRESHOLD),
        out_dir / f"Plot_{RUN_LABEL}_RAW_Z",
    )
    make_raincloud_figure(
        df_part_used,
        df_group_raw.rename(columns={"mean_SNR": "mean_SNR", "sem_SNR": "sem_SNR"}),
        PlotPanel(val_col="mean_SNR_selected", mean_col="mean_SNR", sem_col="sem_SNR", ylabel="SNR (sel)"),
        out_dir / f"Plot_{RUN_LABEL}_RAW_SNR",
    )
    make_raincloud_figure(
        df_part_used,
        df_group_raw.rename(columns={"mean_BCA_uV": "mean_BCA_uV", "sem_BCA_uV": "sem_BCA_uV"}),
        PlotPanel(val_col="mean_BCA_selected", mean_col="mean_BCA_uV", sem_col="sem_BCA_uV", ylabel="BCA (µV; sel)"),
        out_dir / f"Plot_{RUN_LABEL}_RAW_BCA",
    )

    if not df_common_part.empty and not df_common_group.empty:
        make_raincloud_figure(
            df_common_part,
            df_common_group,
            PlotPanel(val_col="ratio_Z_common", mean_col="mean_ratio_Z", sem_col="sem_ratio_Z", ylabel="Z ratio"),
            out_dir / f"Plot_{RUN_LABEL}_COMMON_ZRATIO",
        )
        make_raincloud_figure(
            df_common_part,
            df_common_group,
            PlotPanel(val_col="ratio_SNR_common", mean_col="mean_ratio_SNR", sem_col="sem_ratio_SNR", ylabel="SNR ratio"),
            out_dir / f"Plot_{RUN_LABEL}_COMMON_SNRRATIO",
        )
        make_raincloud_figure(
            df_common_part,
            df_common_group,
            PlotPanel(val_col="delta_BCA_common", mean_col="mean_delta_BCA_uV", sem_col="sem_delta_BCA_uV", ylabel="ΔBCA (µV)"),
            out_dir / f"Plot_{RUN_LABEL}_COMMON_DBCA",
        )

    # Excel + log outputs
    out_xlsx = out_dir / f"Metrics_{RUN_LABEL}.xlsx"
    with pd.ExcelWriter(out_xlsx) as writer:
        df_part.to_excel(writer, sheet_name="Participant_Data_ALL", index=False)
        df_part_used.to_excel(writer, sheet_name="Participant_Data_USED", index=False)
        df_hard_excl.to_excel(writer, sheet_name="Hard_Exclusions", index=False)
        df_soft_qc.to_excel(writer, sheet_name="Soft_QC_Flags", index=False)
        df_group_raw.to_excel(writer, sheet_name="Group_Summary_RAW_USED", index=False)
        df_zero.to_excel(writer, sheet_name="Zero_Sig_USED", index=False)
        if not df_common_part.empty:
            df_common_part.sort_values(["ROI", "participant_num"], kind="stable").to_excel(
                writer, sheet_name="CommonSet_Participant_USED", index=False
            )
        if not df_common_group.empty:
            df_common_group.to_excel(writer, sheet_name="CommonSet_Group_USED", index=False)

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
