"""
fpvs_individual_detectability.py

Generate “individual-level detectability” figures for each condition using *existing*
FPVS Toolbox Excel exports (no recomputation of FFT/BCA/SNR/Z).

Per participant (per condition), the figure shows:
  1) Scalp topomap of Stouffer-combined Z across a fixed set of oddball harmonics.
  2) Centered SNR mini-spectrum (±HALF_WINDOW_HZ) around each harmonic, averaged across
     significant electrodes and then averaged across harmonics.

Key behaviors:
  - Participant IDs parsed from filenames like:
        "SCP7_Fruit vs Veg_Results.xlsx" -> "P7"
    Only "P7" is shown on the plot.
  - Grid is flexible: fixed number of columns, rows added as needed.
  - SNR y-axis is fixed to [0, 2] for interpretability across all figures.
  - Reference lines: vertical at 0 Hz and horizontal at SNR=1.
  - Output: 600 DPI PNG, landscape-style figure sizing.
  - Output location: user selects an output folder; condition subfolders are created.
  - QOL: at completion, attempts to open the output folder in the OS file explorer.
  - UI: folder selection uses PySide6 only (no tkinter) to support later toolbox integration.
  - UI: after conditions are selected, a PySide6 popup lets you set per-condition:
        (a) the figure title (rendered in Times New Roman), and
        (b) the output filename stem (Windows-safe). This is intended for manuscripts/thesis use.

-------------------------------------------------------------------------------
CRITICAL NOTE ABOUT TOPO MAP PLOTTING (DO NOT MODIFY WITHOUT TESTING)
-------------------------------------------------------------------------------
MNE topomap interpolation can behave poorly (or silently fail) if the data vector
contains NaNs. A common failure mode is: "blank / all-white heads" even though
you have significant electrodes (n_sig > 0).

Therefore this script intentionally DOES NOT use NaNs to mask sub-threshold
electrodes. Instead it uses a thresholded colormap where the lowest color is
white, and it sets all non-significant electrodes to Z_THRESHOLD exactly. This
guarantees the data passed to mne.viz.plot_topomap() is fully finite and stable.

If you change any of these items, you must verify topomaps are non-blank on a
known dataset:
  1) `_make_thresholded_cmap()`
  2) `_build_topomap_vector_finite()`
  3) `plot_condition_grid()` topomap plotting scale and colormap usage
"""

from __future__ import annotations

import math
import os
import re
import subprocess
import sys
import traceback
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from scipy.stats import norm

try:
    from statsmodels.stats.multitest import multipletests  # type: ignore

    HAVE_STATSMODELS = True
except Exception:
    HAVE_STATSMODELS = False

if TYPE_CHECKING:
    import matplotlib as mpl
    import matplotlib.pyplot as plt
    import mne


# ----------------------------
# USER CONFIG (ONLY CHANGE HERE)
# ----------------------------

# Fixed-k oddball harmonics for individual detectability (do NOT include base freq)
ODDBALL_HARMONICS_HZ: List[float] = [1.2, 2.4, 3.6, 4.8, 7.2]
SKIP_BASE_FREQ_HZ: float = 6.0  # fail fast if accidentally included

# Significance / masking
Z_THRESHOLD: float = 1.64
USE_BH_FDR: bool = True
FDR_ALPHA: float = 0.05

# SNR mini-spectrum
HALF_WINDOW_HZ: float = 0.2
SNR_REF_LINE: float = 1.0

# FIXED SNR Y-AXIS (requested)
SNR_YMAX_FIXED: float = 2.0  # always set ylim to [0, 2]
SNR_YMIN_FIXED: float = 0.0  # set to 0.4 if you want the paper-like baseline

# Excel sheet + column names (must match your exports)
SHEET_Z: str = "Z Score"
SHEET_FULLSNR: str = "FullSNR"
ELECTRODE_COL: str = "Electrode"

# Montage for scalp plotting
MONTAGE_NAME: str = "biosemi64"

# Grid layout
GRID_NCOLS: int = 5
CELL_W_IN: float = 2.8
CELL_H_IN: float = 2.35
WSPACE: float = 0.25
HSPACE: float = 0.70  # increased vertical spacing (requested)

# Letter portrait layout (Word-friendly)
USE_LETTER_PORTRAIT: bool = True
LETTER_W_IN: float = 8.5
LETTER_H_IN: float = 11.0
PAGE_MARGIN_IN: float = 0.35
TITLE_BAND_IN: float = 0.55        # reserved space above grid
COLORBAR_BAND_IN: float = 0.75     # reserved space below grid (bar + labels)

# Colorbar (centered, not full-width)
COLORBAR_WIDTH_FRAC: float = 0.55
COLORBAR_HEIGHT_FRAC: float = 0.018
COLORBAR_BOTTOM_FRAC: float = 0.06

# Output format
FIG_DPI: int = 600
FIG_FORMAT: str = "png"

# Styling
TITLE_FONTSIZE: int = 14
PANEL_TITLE_FONTSIZE: int = 9
AXIS_LABEL_FONTSIZE: int = 9
TICK_FONTSIZE: int = 8

# Debugging
DEBUG: bool = True
DEBUG_MAX_LIST: int = 12


# ----------------------------
# Internal helpers
# ----------------------------

_FREQ_COL_RE = re.compile(r"^\s*([0-9]*\.?[0-9]+)\s*_Hz\s*$", re.IGNORECASE)
_PID_FROM_SCP_RE = re.compile(r"(?i)SCP\s*(\d+)")

_ODDBALL_SET_4DP = {round(f, 4) for f in ODDBALL_HARMONICS_HZ}
_SNR_WINDOWS = [(h - HALF_WINDOW_HZ - 1e-12, h + HALF_WINDOW_HZ + 1e-12) for h in ODDBALL_HARMONICS_HZ]

_WORKER_NAME_TO_IDX: Optional[Dict[str, int]] = None
_WORKER_N_CHANNELS: Optional[int] = None


def _sanitize_filename(name: str) -> str:
    """Remove characters invalid in Windows filenames."""
    bad = '<>:"/\\|?*'
    out = "".join("_" if c in bad else c for c in name)
    return out.strip().rstrip(".")


def _parse_pid_from_stem(stem: str) -> str:
    """Parse participant ID from stem like 'SCP7_...' -> 'P7'."""
    m = _PID_FROM_SCP_RE.search(stem)
    if not m:
        raise ValueError(f"Could not parse PID from filename stem: '{stem}' (expected 'SCP<number>...').")
    return f"P{int(m.group(1))}"


def _pid_sort_key(pid: str) -> Tuple[int, str]:
    """Sort PIDs numerically when possible (P7 before P10)."""
    m = re.match(r"(?i)P(\d+)$", pid.strip())
    if m:
        return int(m.group(1)), pid
    return 10**9, pid


def _parse_freq_columns(columns: Sequence[object]) -> Dict[float, str]:
    """
    Map numeric frequency -> column name for columns like "1.2000_Hz".
    Keys are rounded to 4 decimals for stable matching.
    """
    out: Dict[float, str] = {}
    for c in columns:
        if not isinstance(c, str):
            continue
        m = _FREQ_COL_RE.match(c)
        if not m:
            continue
        try:
            f = float(m.group(1))
        except ValueError:
            continue
        out[round(f, 4)] = c
    return out


def _bh_fdr_reject(pvals: np.ndarray, alpha: float) -> np.ndarray:
    """Benjamini–Hochberg FDR reject decisions for p-values."""
    p = np.asarray(pvals, dtype=float)
    n = p.size
    if n == 0:
        return np.zeros((0,), dtype=bool)

    order = np.argsort(p)
    ranked = p[order]
    thresh = alpha * (np.arange(1, n + 1) / n)

    passed = ranked <= thresh
    if not np.any(passed):
        return np.zeros((n,), dtype=bool)

    kmax = int(np.max(np.where(passed)[0]))
    cutoff = float(ranked[kmax])
    return p <= cutoff


def _normalize_electrode_name(name: str) -> str:
    """
    Conservative normalization for electrode name matching.
    Keeps behavior stable across minor formatting differences.
    """
    s = str(name).strip().upper()
    s = s.replace(" ", "").replace(".", "").replace("-", "")
    return s


def _build_montage_info() -> Tuple["mne.io.Info", Dict[str, int]]:
    """Create MNE Info with montage and a normalized channel-name -> index map."""
    import mne

    montage = mne.channels.make_standard_montage(MONTAGE_NAME)
    info = mne.create_info(ch_names=montage.ch_names, sfreq=100.0, ch_types="eeg")
    info.set_montage(montage)
    name_to_idx = {_normalize_electrode_name(nm): i for i, nm in enumerate(info.ch_names)}
    return info, name_to_idx


def _usecols_z(col: object) -> bool:
    s = str(col)
    if s == ELECTRODE_COL:
        return True
    m = _FREQ_COL_RE.match(s)
    if not m:
        return False
    try:
        f = round(float(m.group(1)), 4)
    except ValueError:
        return False
    return f in _ODDBALL_SET_4DP


def _usecols_fullsnr(col: object) -> bool:
    s = str(col)
    if s == ELECTRODE_COL:
        return True
    m = _FREQ_COL_RE.match(s)
    if not m:
        return False
    try:
        f = float(m.group(1))
    except ValueError:
        return False
    for lo, hi in _SNR_WINDOWS:
        if lo <= f <= hi:
            return True
    return False


def _read_excel_sheets(xlsx_path: Path) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Read required sheets from an FPVS Toolbox Excel export (open workbook once)."""
    xl = pd.ExcelFile(xlsx_path)
    if SHEET_Z not in xl.sheet_names or SHEET_FULLSNR not in xl.sheet_names:
        raise ValueError(f"Missing required sheets in {xlsx_path.name}. Need '{SHEET_Z}' and '{SHEET_FULLSNR}'.")
    df_z = pd.read_excel(xl, sheet_name=SHEET_Z, usecols=_usecols_z)
    df_snr = pd.read_excel(xl, sheet_name=SHEET_FULLSNR, usecols=_usecols_fullsnr)
    return df_z, df_snr


@dataclass
class ParticipantResult:
    pid: str
    n_sig: int
    z_topo: np.ndarray  # fully finite; non-sig encoded at Z_THRESHOLD to render white
    snr_rel_x: Optional[np.ndarray]
    snr_rel_y: Optional[np.ndarray]


def _compute_electrode_zcomb_and_mask(df_z: pd.DataFrame) -> Tuple[List[str], np.ndarray, np.ndarray]:
    """
    Compute per-electrode Z_comb across ODDBALL_HARMONICS_HZ and return:
      electrodes_raw, z_comb, sig_mask
    """
    if ELECTRODE_COL not in df_z.columns:
        raise ValueError(f"'{ELECTRODE_COL}' column not found in '{SHEET_Z}' sheet.")

    freq_cols = _parse_freq_columns(df_z.columns)
    needed = [round(f, 4) for f in ODDBALL_HARMONICS_HZ]
    missing = [f for f in needed if f not in freq_cols]
    if missing:
        miss_str = ", ".join([f"{f:.4f}_Hz" for f in missing])
        raise ValueError(f"Missing harmonic column(s) in '{SHEET_Z}': {miss_str}")

    z_cols = [freq_cols[round(f, 4)] for f in ODDBALL_HARMONICS_HZ]
    electrodes_raw = df_z[ELECTRODE_COL].astype(str).tolist()

    z_mat = df_z[z_cols].apply(pd.to_numeric, errors="raise").to_numpy(dtype=float)
    k = int(z_mat.shape[1])
    if k == 0:
        z_comb = np.full((z_mat.shape[0],), float("nan"), dtype=float)
    else:
        z_comb = z_mat.sum(axis=1) / math.sqrt(k)

    sig = z_comb >= Z_THRESHOLD

    if USE_BH_FDR:
        p_one = 1.0 - norm.cdf(z_comb)  # one-tailed positive direction
        if HAVE_STATSMODELS:
            reject, _, _, _ = multipletests(p_one, alpha=FDR_ALPHA, method="fdr_bh")
            sig = sig & reject.astype(bool)
        else:
            reject = _bh_fdr_reject(p_one, alpha=FDR_ALPHA)
            sig = sig & reject.astype(bool)

    return electrodes_raw, z_comb.astype(float), sig.astype(bool)


def _build_topomap_vector_finite(
    electrodes_raw: Sequence[str],
    z_comb: np.ndarray,
    sig_mask: np.ndarray,
    name_to_idx: Dict[str, int],
    n_channels: int,
    *,
    debug_tag: str = "",
) -> np.ndarray:
    """
    Build montage-aligned topomap vector with NO NaNs.

    DO NOT CHANGE THIS TO NaN MASKING.
    ----------------------------------
    MNE topomap interpolation can produce blank plots if NaNs are present.
    We encode non-significant electrodes as exactly Z_THRESHOLD, and we use
    a colormap whose lowest color is white. This makes non-significant regions
    appear white while keeping the array fully finite and stable for MNE.

    Behavior:
      - Significant electrodes: value = Z_comb (>= Z_THRESHOLD)
      - Non-significant electrodes: value = Z_THRESHOLD (renders as white)
      - Missing electrodes (should not occur for you): value = Z_THRESHOLD
    """
    vec = np.full((n_channels,), float(Z_THRESHOLD), dtype=float)

    mapped_total = 0
    mapped_sig = 0
    missing_labels: List[str] = []

    for el, zc, ok in zip(electrodes_raw, z_comb, sig_mask):
        key = _normalize_electrode_name(el)
        idx = name_to_idx.get(key)
        if idx is None:
            missing_labels.append(el)
            continue
        mapped_total += 1
        if bool(ok):
            vec[idx] = float(zc)
            mapped_sig += 1
        else:
            vec[idx] = float(Z_THRESHOLD)

    if DEBUG:
        if missing_labels:
            prev = missing_labels[:DEBUG_MAX_LIST]
            raise RuntimeError(
                "Electrode mapping failure (labels not found in montage).\n"
                f"  debug_tag: {debug_tag}\n"
                f"  missing_count: {len(missing_labels)}\n"
                f"  examples: {prev}\n"
            )

        # If you have sig electrodes but none mapped (shouldn't happen if labels match)
        if int(np.sum(sig_mask)) > 0 and mapped_sig == 0:
            raise RuntimeError(
                "Topomap mapping failure: n_sig > 0 but mapped_sig == 0.\n"
                f"  debug_tag: {debug_tag}\n"
                f"  n_sig: {int(np.sum(sig_mask))}\n"
                "This indicates an electrode-name normalization/matching issue."
            )

    return vec


def _compute_centered_snr_curve(
    df_fullsnr: pd.DataFrame,
    sig_electrodes_raw: Sequence[str],
) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
    """Compute centered SNR curve averaged across sig electrodes and harmonics."""
    if ELECTRODE_COL not in df_fullsnr.columns:
        raise ValueError(f"'{ELECTRODE_COL}' column not found in '{SHEET_FULLSNR}' sheet.")

    if not sig_electrodes_raw:
        return None, None

    freq_cols = _parse_freq_columns(df_fullsnr.columns)
    if not freq_cols:
        raise ValueError(f"No '*_Hz' frequency columns found in '{SHEET_FULLSNR}' sheet.")

    el_norm = df_fullsnr[ELECTRODE_COL].astype(str).map(_normalize_electrode_name)
    sig_set = {_normalize_electrode_name(e) for e in sig_electrodes_raw}
    sub = df_fullsnr.loc[el_norm.isin(sig_set)]
    if sub.empty:
        return None, None

    freqs_avail = np.array(sorted(freq_cols.keys()), dtype=float)
    cols_all = [freq_cols[f] for f in freqs_avail]
    sub_mat = sub[cols_all].to_numpy(dtype=float)  # (n_sig_elec, n_freqs)

    per_harmonic: List[Tuple[np.ndarray, np.ndarray]] = []

    for f in ODDBALL_HARMONICS_HZ:
        lo = f - HALF_WINDOW_HZ
        hi = f + HALF_WINDOW_HZ
        mask = (freqs_avail >= (lo - 1e-12)) & (freqs_avail <= (hi + 1e-12))
        if not np.any(mask):
            continue

        idx = np.nonzero(mask)[0]
        in_win = freqs_avail[idx]
        col_mean = np.mean(sub_mat[:, idx], axis=0)

        rel = in_win - f
        rel_round = np.round(rel, 4)

        # Match pandas behavior: duplicate index would later fail during reindex.
        if rel_round.size != np.unique(rel_round).size:
            raise ValueError("Duplicate relative-frequency bins after rounding; cannot reindex reliably.")

        per_harmonic.append((rel_round.astype(float), col_mean.astype(float)))

    if not per_harmonic:
        return None, None

    rel_set: set[float] = set()
    for rel_round, _ in per_harmonic:
        rel_set.update(rel_round.tolist())

    rel_index = np.array(sorted(rel_set), dtype=float)
    pos = {float(v): i for i, v in enumerate(rel_index)}

    stacked = np.full((len(per_harmonic), rel_index.size), np.nan, dtype=float)
    for r, (rel_round, yvals) in enumerate(per_harmonic):
        for x, yv in zip(rel_round.tolist(), yvals.tolist()):
            stacked[r, pos[float(x)]] = float(yv)

    y = np.mean(stacked, axis=0)
    return rel_index, y


def _discover_conditions(root: Path) -> Dict[str, List[Path]]:
    """Detect condition groups from subfolders or treat root as a single condition."""
    cond_map: Dict[str, List[Path]] = {}
    subfolders = [p for p in root.iterdir() if p.is_dir()]
    found = False
    for sf in subfolders:
        files = sorted([f for f in sf.glob("*.xlsx") if f.is_file()])
        if files:
            cond_map[sf.name] = files
            found = True
    if found:
        return cond_map

    files = sorted([f for f in root.glob("*.xlsx") if f.is_file()])
    if files:
        cond_map[root.name] = files
    return cond_map


def _make_thresholded_cmap(base_name: str = "YlOrRd", white_frac: float = 0.08) -> "mpl.colors.Colormap":
    """
    Colormap with a white floor at the minimum.

    Rationale:
      Some MNE/matplotlib pathways clip values below vmin to vmin. If the vmin color
      is not white, "masked" electrodes appear pale yellow instead of white. This
      colormap makes the lowest part of the scale white so that vmin (and any clipping
      to vmin) renders as white reliably.
    """
    import matplotlib as mpl
    import matplotlib.pyplot as plt

    base = plt.get_cmap(base_name)
    n = 256
    n_white = max(1, int(round(n * float(white_frac))))
    cols = base(np.linspace(0, 1, n))
    cols[:n_white, :3] = 1.0  # RGB -> white
    return mpl.colors.ListedColormap(cols)


def _plot_topomap_compat(
    data: np.ndarray,
    info: "mne.io.Info",
    ax: "plt.Axes",
    cmap: "mpl.colors.Colormap",
    vmin: float,
    vmax: float,
) -> None:
    """MNE topomap wrapper compatible with multiple MNE versions."""
    import mne

    # Show faint sensor dots when supported (paper-like appearance).
    sensor_kwargs = {
        "marker": ".",
        "markersize": 2,
        "markerfacecolor": "0.75",
        "markeredgecolor": "0.75",
    }

    try:
        mne.viz.plot_topomap(
            data,
            info,
            axes=ax,
            show=False,
            contours=0,
            sensors=True,
            sensor_kwargs=sensor_kwargs,
            cmap=cmap,
            vlim=(vmin, vmax),
            outlines="head",
        )
        return
    except TypeError:
        pass

    try:
        mne.viz.plot_topomap(
            data,
            info,
            axes=ax,
            show=False,
            contours=0,
            sensors=True,
            cmap=cmap,
            vlim=(vmin, vmax),
            outlines="head",
        )
        return
    except TypeError:
        pass

    try:
        mne.viz.plot_topomap(
            data,
            info,
            axes=ax,
            show=False,
            contours=0,
            sensors=True,
            sensor_kwargs=sensor_kwargs,
            cmap=cmap,
            vmin=vmin,
            vmax=vmax,
            outlines="head",
        )
        return
    except TypeError:
        pass

    mne.viz.plot_topomap(
        data,
        info,
        axes=ax,
        show=False,
        contours=0,
        sensors=True,
        cmap=cmap,
        vmin=vmin,
        vmax=vmax,
        outlines="head",
    )


def plot_condition_grid(
    condition: str,
    results: List["ParticipantResult"],
    info: "mne.io.Info",
    out_file: Path,
    *,
    fig_title: Optional[str] = None,
) -> None:
    """
    Save a landscape grid figure for one condition.

    fig_title behavior:
      - None: use legacy default "{condition}: Individual-level detectability"
      - "" (or whitespace): omit the suptitle entirely (useful for manuscripts)
      - otherwise: use provided title (rendered in Times New Roman)
    """
    if not results:
        return

    import matplotlib as mpl
    import matplotlib.pyplot as plt

    results_sorted = sorted(results, key=lambda r: _pid_sort_key(r.pid))
    n = len(results_sorted)
    ncols = max(1, int(GRID_NCOLS))
    nrows = int(math.ceil(n / ncols))

    plt.rcParams.update(
        {
            # Manuscript-friendly typography on Windows (fallbacks included).
            "font.family": "serif",
            "font.serif": ["Times New Roman", "Times", "DejaVu Serif"],
            "font.size": 10,
            "axes.linewidth": 1.0,
            "xtick.major.size": 4,
            "ytick.major.size": 4,
        }
    )

    if USE_LETTER_PORTRAIT:
        fig_w = float(LETTER_W_IN)
        fig_h = float(LETTER_H_IN)
        fig = plt.figure(figsize=(fig_w, fig_h))

        left = float(PAGE_MARGIN_IN) / fig_w
        right = 1.0 - (float(PAGE_MARGIN_IN) / fig_w)
        bottom = (float(PAGE_MARGIN_IN) + float(COLORBAR_BAND_IN)) / fig_h
        top = 1.0 - ((float(PAGE_MARGIN_IN) + float(TITLE_BAND_IN)) / fig_h)

        gs = fig.add_gridspec(
            nrows=2 * nrows,
            ncols=ncols,
            left=left,
            right=right,
            bottom=bottom,
            top=top,
            hspace=HSPACE,
            wspace=WSPACE,
        )
        suptitle_y = top + (1.0 - top) * 0.72
    else:
        fig_w = ncols * CELL_W_IN
        fig_h = nrows * CELL_H_IN
        fig = plt.figure(figsize=(fig_w, fig_h))
        gs = fig.add_gridspec(nrows=2 * nrows, ncols=ncols, hspace=HSPACE, wspace=WSPACE)
        suptitle_y = 0.985

    # Thresholded colormap so vmin renders as white (robust to clipping)
    cmap = _make_thresholded_cmap("YlOrRd", white_frac=0.08)

    # Shared topomap scale
    vmax = float(max(np.max(r.z_topo) for r in results_sorted))
    vmin = float(Z_THRESHOLD)
    if not np.isfinite(vmax) or vmax <= vmin:
        vmax = vmin + 1.0

    snr_ymax = float(SNR_YMAX_FIXED)

    # Place the "SNR" ylabel on the first visible SNR axis per row (even if col 0 is n=0)
    row_ylabel_set: List[bool] = [False for _ in range(nrows)]

    for i in range(nrows * ncols):
        rr = i // ncols
        cc = i % ncols

        ax_topo = fig.add_subplot(gs[2 * rr, cc])
        ax_snr = fig.add_subplot(gs[2 * rr + 1, cc])

        if i >= n:
            ax_topo.axis("off")
            ax_snr.axis("off")
            continue

        r = results_sorted[i]

        _plot_topomap_compat(r.z_topo, info, ax_topo, cmap, vmin=vmin, vmax=vmax)

        # Paper-like labeling: subject above head; n below head
        ax_topo.set_title(f"{r.pid}", fontsize=PANEL_TITLE_FONTSIZE, pad=2)
        ax_topo.text(
            0.5,
            -0.10,
            f"n={r.n_sig}",
            transform=ax_topo.transAxes,
            ha="center",
            va="top",
            fontsize=PANEL_TITLE_FONTSIZE,
        )

        # Hide the entire SNR panel when no significant electrodes (matches published style)
        if r.n_sig <= 0 or r.snr_rel_x is None or r.snr_rel_y is None:
            ax_snr.axis("off")
            continue

        ax_snr.axvline(0.0, linewidth=0.9, color="0.55")
        ax_snr.axhline(SNR_REF_LINE, linewidth=0.9, linestyle="--", color="0.70")
        ax_snr.plot(r.snr_rel_x, r.snr_rel_y, linewidth=0.9, color="0.35")

        ax_snr.set_xlim(-HALF_WINDOW_HZ, HALF_WINDOW_HZ)
        ax_snr.set_ylim(float(SNR_YMIN_FIXED), snr_ymax)
        ax_snr.set_xticks(
            [
                -HALF_WINDOW_HZ,
                -HALF_WINDOW_HZ / 2.0,
                0.0,
                HALF_WINDOW_HZ / 2.0,
                HALF_WINDOW_HZ,
            ]
        )
        ax_snr.tick_params(labelsize=TICK_FONTSIZE)

        for spine in ["top", "right"]:
            ax_snr.spines[spine].set_visible(False)

        if not row_ylabel_set[rr]:
            ax_snr.set_ylabel("SNR", fontsize=AXIS_LABEL_FONTSIZE)
            row_ylabel_set[rr] = True
        else:
            ax_snr.set_ylabel("")
            ax_snr.set_yticklabels([])

        if rr == nrows - 1:
            ax_snr.set_xlabel("Relative frequency (Hz)", fontsize=AXIS_LABEL_FONTSIZE)
        else:
            ax_snr.set_xlabel("")
            ax_snr.set_xticklabels([])

    # Figure title (Times New Roman)
    if fig_title is None:
        title_text = f"{condition}: Individual-level detectability"
    else:
        title_text = str(fig_title)

    if title_text.strip():
        fig.suptitle(
            title_text,
            fontsize=TITLE_FONTSIZE,
            y=float(suptitle_y),
            fontname="Times New Roman",
        )

    # NOTE: In Letter mode we use gridspec bounds (left/right/top/bottom).
    # In non-letter mode we keep the legacy layout.
    if not USE_LETTER_PORTRAIT:
        fig.subplots_adjust(left=0.04, right=0.99, top=0.90, bottom=0.18)

    # Centered colorbar
    cbar_w = float(COLORBAR_WIDTH_FRAC)
    cbar_h = float(COLORBAR_HEIGHT_FRAC)
    cbar_left = (1.0 - cbar_w) / 2.0
    if USE_LETTER_PORTRAIT:
        band_bottom = float(PAGE_MARGIN_IN) / float(LETTER_H_IN)
        band_top = (float(PAGE_MARGIN_IN) + float(COLORBAR_BAND_IN)) / float(LETTER_H_IN)
        cbar_bottom = band_bottom + (band_top - band_bottom - cbar_h) / 2.0
    else:
        cbar_bottom = float(COLORBAR_BOTTOM_FRAC)

    cax = fig.add_axes([cbar_left, cbar_bottom, cbar_w, cbar_h])
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=mpl.colors.Normalize(vmin=vmin, vmax=vmax))
    sm.set_array([])
    cb = fig.colorbar(sm, cax=cax, orientation="horizontal")
    cb.ax.tick_params(labelsize=TICK_FONTSIZE)
    cb.set_label(
        f"Z_comb (Stouffer); white: Z < {Z_THRESHOLD:.2f}",
        fontsize=AXIS_LABEL_FONTSIZE,
        labelpad=4,
    )

    out_file.parent.mkdir(parents=True, exist_ok=True)

    # In Letter mode, avoid bbox_inches="tight" so the physical size remains 8.5x11 inches at save time.
    if USE_LETTER_PORTRAIT:
        fig.savefig(out_file, dpi=FIG_DPI, format=FIG_FORMAT)
    else:
        fig.savefig(out_file, dpi=FIG_DPI, format=FIG_FORMAT, bbox_inches="tight", pad_inches=0.04)
    plt.close(fig)


def _ensure_qapplication():
    """Ensure a QApplication exists (required for QFileDialog/QDesktopServices)."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def _select_directory_pyside6(title: str) -> Optional[Path]:
    """Folder selection dialog using PySide6. Returns None if cancelled."""
    _ensure_qapplication()
    from PySide6.QtWidgets import QFileDialog

    directory = QFileDialog.getExistingDirectory(None, title)
    if not directory:
        return None
    return Path(directory)


def _collect_figure_naming_pyside6(
    cond_names: Sequence[str],
) -> Optional[Dict[str, Tuple[str, str]]]:
    """
    Show a PySide6 dialog to set per-condition:
      - figure title (printed on the figure in Times New Roman)
      - output filename stem (extension added later; sanitized for Windows)

    Returns:
      dict: condition -> (fig_title, file_stem)
      None if cancelled.
    """
    _ensure_qapplication()

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (
        QAbstractItemView,
        QDialog,
        QDialogButtonBox,
        QHeaderView,
        QLabel,
        QTableWidget,
        QTableWidgetItem,
        QVBoxLayout,
    )

    class _Dlg(QDialog):
        def __init__(self, names: Sequence[str]) -> None:
            super().__init__(None)
            self.setWindowTitle("Figure titles & filenames")

            lay = QVBoxLayout(self)
            msg = QLabel(
                "Set the title and output filename for each condition.\n"
                "• Title renders in Times New Roman on the exported figure.\n"
                "• Leave Title blank to omit a title (useful for manuscripts).\n"
                "• Filename is sanitized for Windows; extension is added automatically."
            )
            msg.setWordWrap(True)
            lay.addWidget(msg)

            self.table = QTableWidget(len(names), 3, self)
            self.table.setHorizontalHeaderLabels(["Condition", "Figure title", "Output filename (no extension)"])
            self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
            self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
            self.table.setEditTriggers(
                QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed
            )

            hdr = self.table.horizontalHeader()
            hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
            hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)

            for r, c in enumerate(names):
                it0 = QTableWidgetItem(str(c))
                it0.setFlags(it0.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(r, 0, it0)

                default_title = f"{c}: Individual-level detectability"
                self.table.setItem(r, 1, QTableWidgetItem(default_title))

                default_stem = f"{_sanitize_filename(str(c))}_individual_detectability_grid"
                self.table.setItem(r, 2, QTableWidgetItem(default_stem))

            lay.addWidget(self.table)

            bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
            bb.accepted.connect(self.accept)
            bb.rejected.connect(self.reject)
            lay.addWidget(bb)

        def values(self) -> Dict[str, Tuple[str, str]]:
            out: Dict[str, Tuple[str, str]] = {}
            for r in range(self.table.rowCount()):
                cond = (self.table.item(r, 0).text() if self.table.item(r, 0) else "").strip()
                title = (self.table.item(r, 1).text() if self.table.item(r, 1) else "").strip()
                stem = (self.table.item(r, 2).text() if self.table.item(r, 2) else "").strip()

                # Allow blank title to mean "no suptitle".
                # If stem is blank, fall back to a stable default.
                if stem.strip():
                    stem_clean = _sanitize_filename(stem)
                else:
                    stem_clean = f"{_sanitize_filename(cond)}_individual_detectability_grid"

                out[cond] = (title, stem_clean)
            return out

    names_list = [str(x) for x in cond_names]
    dlg = _Dlg(names_list)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return None
    return dlg.values()


def _open_folder_in_explorer(folder: Path) -> None:
    """Attempt to open a folder in the OS file explorer."""
    try:
        _ensure_qapplication()
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
        return
    except Exception:
        pass

    # fallback (no tkinter; acceptable OS-level behavior)
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(folder))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.run(["open", str(folder)], check=False)
        else:
            subprocess.run(["xdg-open", str(folder)], check=False)
    except Exception:
        return


@dataclass
class _FileOutcome:
    xlsx_name: str
    pid: Optional[str]
    ok: bool
    n_sig: int = 0
    z_topo: Optional[np.ndarray] = None
    snr_x: Optional[np.ndarray] = None
    snr_y: Optional[np.ndarray] = None
    dbg_zmin: Optional[float] = None
    dbg_zmax: Optional[float] = None
    err: Optional[str] = None
    tb: Optional[str] = None


def _init_worker(name_to_idx: Dict[str, int], n_channels: int) -> None:
    global _WORKER_NAME_TO_IDX, _WORKER_N_CHANNELS
    _WORKER_NAME_TO_IDX = name_to_idx
    _WORKER_N_CHANNELS = int(n_channels)


def _process_xlsx_worker(xlsx_path_str: str, condition: str) -> _FileOutcome:
    xlsx_path = Path(xlsx_path_str)
    try:
        pid = _parse_pid_from_stem(xlsx_path.stem)
        df_z, df_snr = _read_excel_sheets(xlsx_path)

        electrodes_raw, z_comb, sig_mask = _compute_electrode_zcomb_and_mask(df_z)
        n_sig = int(np.sum(sig_mask))
        sig_electrodes_raw = [e for e, ok in zip(electrodes_raw, sig_mask) if bool(ok)]

        if _WORKER_NAME_TO_IDX is None or _WORKER_N_CHANNELS is None:
            raise RuntimeError("Worker not initialized (missing montage mapping).")

        z_topo = _build_topomap_vector_finite(
            electrodes_raw=electrodes_raw,
            z_comb=z_comb,
            sig_mask=sig_mask,
            name_to_idx=_WORKER_NAME_TO_IDX,
            n_channels=_WORKER_N_CHANNELS,
            debug_tag=f"{condition} | {xlsx_path.name} | {pid}",
        )

        snr_x, snr_y = _compute_centered_snr_curve(df_snr, sig_electrodes_raw)

        dbg_zmin = float(np.min(z_topo)) if DEBUG else None
        dbg_zmax = float(np.max(z_topo)) if DEBUG else None

        return _FileOutcome(
            xlsx_name=xlsx_path.name,
            pid=pid,
            ok=True,
            n_sig=n_sig,
            z_topo=z_topo,
            snr_x=snr_x,
            snr_y=snr_y,
            dbg_zmin=dbg_zmin,
            dbg_zmax=dbg_zmax,
        )
    except Exception as e:
        return _FileOutcome(
            xlsx_name=xlsx_path.name,
            pid=None,
            ok=False,
            err=str(e),
            tb=traceback.format_exc(),
        )


def main() -> None:
    for f in ODDBALL_HARMONICS_HZ:
        if abs(f - SKIP_BASE_FREQ_HZ) < 1e-9:
            raise RuntimeError("ODDBALL_HARMONICS_HZ includes the base frequency. Remove 6.0 Hz.")

    print("\nFPVS Individual Detectability Script (Excel-only)\n")

    in_root = _select_directory_pyside6("Select folder containing condition folders (or .xlsx files)")
    if in_root is None:
        print("No input folder selected. Exiting.")
        return

    out_root = _select_directory_pyside6("Select an output folder for figures")
    if out_root is None:
        print("No output folder selected. Exiting.")
        return
    out_root.mkdir(parents=True, exist_ok=True)

    log_path = out_root / "individual_detectability_log.txt"

    info, name_to_idx = _build_montage_info()

    cond_map = _discover_conditions(in_root)
    if not cond_map:
        print("No .xlsx files found in the selected folder (or its immediate subfolders).")
        return

    cond_names_all = sorted(cond_map.keys())
    print("Detected conditions:")
    for c in cond_names_all:
        print(f"  - {c}  ({len(cond_map[c])} files)")
    subset = input("\nEnter comma-separated condition names to run (or press Enter for ALL): ").strip()
    if subset:
        chosen = {s.strip() for s in subset.split(",") if s.strip()}
        cond_map = {c: cond_map[c] for c in cond_names_all if c in chosen}
        if not cond_map:
            print("None of the entered condition names matched. Exiting.")
            return

    # Per-condition figure naming (PySide6)
    chosen_names = list(cond_map.keys())
    naming = _collect_figure_naming_pyside6(chosen_names)
    if naming is None:
        print("Figure naming cancelled. Exiting.")
        return

    with open(log_path, "w", encoding="utf-8") as log:
        log.write("FPVS Individual Detectability Log\n")
        log.write(f"Input root: {in_root}\nOutput root: {out_root}\n")
        log.write(f"Harmonics: {ODDBALL_HARMONICS_HZ}\n")
        log.write(f"Z threshold: {Z_THRESHOLD}\n")
        log.write(f"USE_BH_FDR: {USE_BH_FDR} (alpha={FDR_ALPHA if USE_BH_FDR else 'n/a'})\n")
        log.write(f"SNR window: ±{HALF_WINDOW_HZ} Hz\n")
        log.write(f"SNR_YMAX_FIXED: {SNR_YMAX_FIXED}\n")
        log.write(f"Statsmodels available: {HAVE_STATSMODELS}\n")
        log.write(f"Output: {FIG_FORMAT.upper()} @ {FIG_DPI} dpi\n")
        log.write("Figure naming: PySide6 per-condition titles + filenames\n")
        for cond in chosen_names:
            title, stem = naming.get(cond, ("", ""))
            log.write(f"  - {cond} | title='{title}' | stem='{stem}'\n")
        log.write(f"DEBUG: {DEBUG}\n\n")

        with ProcessPoolExecutor(initializer=_init_worker, initargs=(name_to_idx, len(info.ch_names))) as ex:
            for condition, files in cond_map.items():
                print(f"\nProcessing condition: {condition} ({len(files)} files)")

                cond_log_lines: List[str] = [f"\n=== CONDITION: {condition} ===\n"]
                cond_results: List[ParticipantResult] = []
                cond_out_dir = out_root / _sanitize_filename(condition)
                cond_out_dir.mkdir(parents=True, exist_ok=True)

                futures_by_name: Dict[str, object] = {}
                for xlsx in files:
                    fut = ex.submit(_process_xlsx_worker, str(xlsx), condition)
                    futures_by_name[xlsx.name] = fut

                outcomes_by_name: Dict[str, _FileOutcome] = {}
                for name, fut in futures_by_name.items():
                    try:
                        outcomes_by_name[name] = fut.result()
                    except Exception as e:
                        outcomes_by_name[name] = _FileOutcome(
                            xlsx_name=name,
                            pid=None,
                            ok=False,
                            err=str(e),
                            tb=traceback.format_exc(),
                        )

                # Preserve existing behavior: handle in filename-sorted order
                for xlsx in files:
                    outcome = outcomes_by_name.get(xlsx.name)
                    if outcome is None:
                        print(f"  [ERROR] {xlsx.name}: Missing worker outcome")
                        cond_log_lines.append(f"FAIL: {xlsx.name} | Missing worker outcome\n")
                        continue

                    if outcome.ok and outcome.pid is not None and outcome.z_topo is not None:
                        pid = outcome.pid
                        n_sig = int(outcome.n_sig)

                        if DEBUG and outcome.dbg_zmin is not None and outcome.dbg_zmax is not None:
                            cond_log_lines.append(
                                f"DBG: {pid} | n_sig={n_sig} | z_topo[min,max]=[{outcome.dbg_zmin:.3f},{outcome.dbg_zmax:.3f}]\n"
                            )

                        cond_results.append(
                            ParticipantResult(
                                pid=pid,
                                n_sig=n_sig,
                                z_topo=outcome.z_topo,
                                snr_rel_x=outcome.snr_x,
                                snr_rel_y=outcome.snr_y,
                            )
                        )
                        cond_log_lines.append(f"OK: {xlsx.name} | {pid} | n_sig={n_sig}\n")
                    else:
                        err = outcome.err or "Unknown error"
                        print(f"  [ERROR] {xlsx.name}: {err}")
                        tb = outcome.tb or ""
                        cond_log_lines.append(f"FAIL: {xlsx.name} | {err}\n{tb}\n")

                if cond_results:
                    fig_title, stem = naming.get(
                        condition,
                        ("", f"{_sanitize_filename(condition)}_individual_detectability_grid"),
                    )
                    if not stem.strip():
                        stem = f"{_sanitize_filename(condition)}_individual_detectability_grid"

                    out_name = f"{_sanitize_filename(stem)}.{FIG_FORMAT}"
                    out_file = cond_out_dir / out_name
                    plot_condition_grid(condition, cond_results, info, out_file, fig_title=fig_title)
                    print(f"  Saved: {out_file}")
                else:
                    print("  No usable files for this condition.")

                log.writelines(cond_log_lines)
                log.flush()

    print(f"\nDone. Outputs saved under: {out_root}")
    print(f"Log: {log_path}")
    _open_folder_in_explorer(out_root)


if __name__ == "__main__":
    main()
