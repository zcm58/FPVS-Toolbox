from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import hashlib
import math
import re
import traceback
from typing import Callable, Sequence, TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np


SHEET_Z = "Z Score"
SHEET_FULLSNR = "FullSNR"
ELECTRODE_COL = "Electrode"

# Participant ID parsing
_PID_SCP_RE = re.compile(r"SCP0*(\d+)", re.IGNORECASE)
_PID_P_RE = re.compile(r"(?<![A-Z0-9])P0*(\d+)(?!\d)", re.IGNORECASE)

# Filename sanitization
_ILLEGAL_FILENAME = re.compile(r'[<>:"/\\\\|?*]+')

# Excel frequency columns (expects "1.2000_Hz" style)
_FREQ_COL_RE = re.compile(r"^\s*([0-9]*\.?[0-9]+)\s*_Hz\s*$", re.IGNORECASE)

# Montage
_MONTAGE_NAME = "biosemi64"

# Cached montage info (per-process)
_CACHED_INFO = None
_CACHED_NAME_TO_IDX = None

# -----------------------------------------------------------------------------
# Performance knobs
# -----------------------------------------------------------------------------
# Fixed worker count requested
_PARALLEL_WORKERS = 3

# Disk cache (persists next to the Excel inputs)
_CACHE_DIRNAME = "_individual_detectability_cache"
_CACHE_VERSION = "v1"  # bump if cache format changes

# -----------------------------------------------------------------------------
# Plot layout constants (tuned to improve alignment + reduce wasted vertical space)
# -----------------------------------------------------------------------------
LETTER_W_IN = 8.5
LETTER_H_IN = 11.0

# Move content up and reduce unused whitespace
PAGE_MARGIN_IN = 0.25

# Less reserved space at top (you are not using a big figure title currently)
TITLE_BAND_IN = 0.20

# More reserved space at bottom so x-labels never collide with the legend/colorbar
COLORBAR_BAND_IN = 1.15

COLORBAR_WIDTH_FRAC = 0.55
COLORBAR_HEIGHT_FRAC = 0.018

WSPACE = 0.25

# Reduce vertical spacing between topo/snr rows
HSPACE = 0.42

FIG_DPI = 600

# Colorbar placement tuning within the reserved bottom band
# (place it lower so it cannot overlap x-axis labels on the last row)
_CBAR_Y_FRAC_IN_BAND = 0.30  # 0..1, where 0 is band_bottom

# Text below colorbar (white/max) spacing
_CBAR_TEXT_PAD_FRAC = 0.020  # in figure fraction units (small downward offset)

# X-label pad (negative pulls label upward away from colorbar band)
_XLABEL_PAD = -1

# -----------------------------------------------------------------------------
# Plot policy / UX constraints
# -----------------------------------------------------------------------------
_MAX_GRID_NCOLS = 10  # 11+ forbidden

# Slightly larger legend text for clarity
_LEGEND_LABEL_FONTSIZE = 10
_LEGEND_SIDE_TEXT_FONTSIZE = 9


@dataclass(frozen=True)
class DetectabilitySettings:
    # IMPORTANT: do NOT include base frequency 6.0 in oddball harmonics
    oddball_harmonics_hz: list[float] = field(
        default_factory=lambda: [1.2, 2.4, 3.6, 4.8, 7.2]
    )
    z_threshold: float = 1.64

    # Match original behavior: one-tailed positive-direction BH-FDR
    use_bh_fdr: bool = True
    fdr_alpha: float = 0.05

    # Match original behavior
    half_window_hz: float = 0.2
    snr_ymin_fixed: float = 0.0
    snr_ymax_fixed: float = 2.0
    snr_show_mid_xtick: bool = False

    # Match original output (8 columns)
    grid_ncols: int = 8

    # Keep original Word-friendly page layout
    use_letter_portrait: bool = True


@dataclass(frozen=True)
class ConditionInfo:
    name: str
    path: Path
    files: list[Path]


@dataclass(frozen=True)
class _ParticipantResult:
    pid: str
    ok: bool
    n_sig: int = 0
    z_topo: "np.ndarray | None" = None
    snr_x: "np.ndarray | None" = None
    snr_y: "np.ndarray | None" = None
    err: str | None = None
    tb: str | None = None


def parse_participant_id(filename: str) -> str | None:
    match = _PID_SCP_RE.search(filename)
    if match:
        return f"P{int(match.group(1))}"
    match = _PID_P_RE.search(filename)
    if match:
        return f"P{int(match.group(1))}"
    return None


def _pid_sort_key(pid: str) -> tuple[int, str]:
    m = re.match(r"(?i)P(\d+)$", pid.strip())
    if m:
        return int(m.group(1)), pid
    return 10**9, pid


def sanitize_filename_stem(value: str) -> str:
    cleaned = _ILLEGAL_FILENAME.sub("_", value).strip().strip(".")
    return cleaned if cleaned else "output"


def discover_conditions(root: Path) -> list[ConditionInfo]:
    if not root.exists():
        return []
    subfolders = sorted([p for p in root.iterdir() if p.is_dir()])
    conditions: list[ConditionInfo] = []
    for sub in subfolders:
        files = sorted([p for p in sub.glob("*.xlsx") if p.is_file()])
        if files:
            conditions.append(ConditionInfo(name=sub.name, path=sub, files=files))
    if conditions:
        return conditions
    files = sorted([p for p in root.glob("*.xlsx") if p.is_file()])
    if files:
        return [ConditionInfo(name=root.name, path=root, files=files)]
    return []


def _normalize_electrode_name(name: str) -> str:
    s = str(name).strip().upper()
    s = s.replace(" ", "").replace(".", "").replace("-", "")
    return s


def _get_montage_info():
    """
    Create/cache MNE Info with montage and normalized channel-name -> index map.

    This avoids passing XYZ position arrays into plot_topomap (which caused your
    (n_channels, 3) error). We always call plot_topomap(data, info, ...).
    """
    global _CACHED_INFO, _CACHED_NAME_TO_IDX
    if _CACHED_INFO is not None and _CACHED_NAME_TO_IDX is not None:
        return _CACHED_INFO, _CACHED_NAME_TO_IDX

    import mne

    montage = mne.channels.make_standard_montage(_MONTAGE_NAME)
    info = mne.create_info(ch_names=montage.ch_names, sfreq=100.0, ch_types="eeg")
    info.set_montage(montage)
    name_to_idx = {_normalize_electrode_name(nm): i for i, nm in enumerate(info.ch_names)}

    _CACHED_INFO = info
    _CACHED_NAME_TO_IDX = name_to_idx
    return info, name_to_idx


def _parse_freq_columns(columns: Sequence[object]) -> dict[float, str]:
    out: dict[float, str] = {}
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


def _ensure_no_nan(values) -> None:
    import numpy as np

    arr = np.asarray(values, dtype=float)
    if np.isnan(arr).any():
        raise ValueError("Topomap values contain NaNs; cannot render.")


def _norm_cdf(x):
    """Normal(0,1) CDF via erf (SciPy-free)."""
    import numpy as np

    x_arr = np.asarray(x, dtype=float)
    try:
        erf = np.erf  # type: ignore[attr-defined]
    except Exception:
        import math as _math
        erf = np.vectorize(_math.erf, otypes=[float])
    return 0.5 * (1.0 + erf(x_arr / math.sqrt(2.0)))


def _bh_fdr_reject(pvals, alpha: float):
    """Benjamini–Hochberg FDR reject decisions for p-values."""
    import numpy as np

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


def _make_thresholded_cmap(base_name: str = "YlOrRd", white_frac: float = 0.08):
    """
    Colormap with a white floor at the minimum, so vmin==Z_THRESHOLD renders white.
    """
    import matplotlib as mpl
    import matplotlib.pyplot as plt
    import numpy as np

    base = plt.get_cmap(base_name)
    n = 256
    n_white = max(1, int(round(n * float(white_frac))))
    cols = base(np.linspace(0, 1, n))
    cols[:n_white, :3] = 1.0
    return mpl.colors.ListedColormap(cols)


def _plot_topomap_compat(
    data,
    info,
    ax,
    cmap,
    vmin: float,
    vmax: float,
) -> None:
    """
    Call mne.viz.plot_topomap across MNE versions.

    Uses the Info signature (NOT pos arrays) to avoid the (n,3) XYZ error.
    """
    import mne

    sensor_kwargs = {
        "marker": ".",
        "markersize": 2,
        "markerfacecolor": "0.0",
        "markeredgecolor": "0.0",
    }

    # Newer MNE: vlim=(vmin, vmax)
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

    # Some versions: vlim exists but sensor_kwargs not accepted
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

    # Older MNE: vmin/vmax
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


# -----------------------------------------------------------------------------
# Caching helpers
# -----------------------------------------------------------------------------
def _settings_fingerprint(settings: DetectabilitySettings) -> str:
    # Stable, explicit token (don’t rely on Python hash randomization)
    parts = [
        _CACHE_VERSION,
        "harm=" + ",".join([f"{float(h):.4f}" for h in settings.oddball_harmonics_hz]),
        f"zthr={float(settings.z_threshold):.6f}",
        f"bh={int(bool(settings.use_bh_fdr))}",
        f"alpha={float(settings.fdr_alpha):.6f}",
        f"hw={float(settings.half_window_hz):.6f}",
    ]
    s = "|".join(parts).encode("utf-8")
    return hashlib.sha1(s).hexdigest()[:16]


def _source_fingerprint(path: Path) -> str:
    st = path.stat()
    token = f"{st.st_mtime_ns}-{st.st_size}".encode("utf-8")
    return hashlib.sha1(token).hexdigest()[:16]


def _cache_path_for(excel_path: Path, settings: DetectabilitySettings, cache_dir: Path) -> Path:
    key = f"{excel_path.stem}__{_source_fingerprint(excel_path)}__{_settings_fingerprint(settings)}.npz"
    return cache_dir / key


def _load_cache_npz(cache_path: Path) -> _ParticipantResult:
    import numpy as np

    data = np.load(cache_path, allow_pickle=False)
    pid = str(data["pid"])
    n_sig = int(data["n_sig"])
    z_topo = data["z_topo"].astype(float)
    has_snr = int(data["has_snr"]) == 1
    if has_snr:
        snr_x = data["snr_x"].astype(float)
        snr_y = data["snr_y"].astype(float)
    else:
        snr_x = None
        snr_y = None

    return _ParticipantResult(
        pid=pid,
        ok=True,
        n_sig=n_sig,
        z_topo=z_topo,
        snr_x=snr_x,
        snr_y=snr_y,
    )


def _save_cache_npz(
    cache_path: Path,
    *,
    pid: str,
    n_sig: int,
    z_topo,
    snr_x,
    snr_y,
) -> None:
    import numpy as np

    cache_path.parent.mkdir(parents=True, exist_ok=True)

    has_snr = 1 if (snr_x is not None and snr_y is not None) else 0
    if has_snr == 0:
        snr_x_arr = np.asarray([], dtype=float)
        snr_y_arr = np.asarray([], dtype=float)
    else:
        snr_x_arr = np.asarray(snr_x, dtype=float)
        snr_y_arr = np.asarray(snr_y, dtype=float)

    tmp = cache_path.with_suffix(cache_path.suffix + ".tmp")
    np.savez_compressed(
        tmp,
        pid=np.asarray(pid),
        n_sig=np.asarray(int(n_sig)),
        z_topo=np.asarray(z_topo, dtype=float),
        has_snr=np.asarray(int(has_snr)),
        snr_x=snr_x_arr,
        snr_y=snr_y_arr,
    )
    try:
        tmp.replace(cache_path)
    except Exception:
        try:
            if cache_path.exists():
                cache_path.unlink()
        except Exception:
            pass
        tmp.replace(cache_path)


# -----------------------------------------------------------------------------
# Minimal Excel I/O (read only needed columns)
# -----------------------------------------------------------------------------
def _excel_minimal_read(excel_path: Path, settings: DetectabilitySettings):
    """
    Returns:
      df_z (Electrode + required harmonic cols)
      df_snr (Electrode + freq cols within ±half_window around each harmonic)
    """
    import pandas as pd

    xl = pd.ExcelFile(excel_path)

    if SHEET_Z not in xl.sheet_names:
        raise ValueError(f"Missing required sheet '{SHEET_Z}'.")
    if SHEET_FULLSNR not in xl.sheet_names:
        raise ValueError(f"Missing required sheet '{SHEET_FULLSNR}'.")

    z_head = xl.parse(SHEET_Z, nrows=0)
    if ELECTRODE_COL not in z_head.columns:
        raise ValueError(f"Missing column '{ELECTRODE_COL}' in '{SHEET_Z}'.")

    freq_cols = _parse_freq_columns(z_head.columns)
    needed = [round(float(f), 4) for f in settings.oddball_harmonics_hz]
    missing = [f for f in needed if f not in freq_cols]
    if missing:
        miss_str = ", ".join([f"{f:.4f}_Hz" for f in missing])
        raise ValueError(f"Missing harmonic column(s) in '{SHEET_Z}': {miss_str}")

    z_cols = [freq_cols[round(float(f), 4)] for f in settings.oddball_harmonics_hz]
    z_usecols = [ELECTRODE_COL] + z_cols
    df_z = xl.parse(SHEET_Z, usecols=z_usecols)

    snr_head = xl.parse(SHEET_FULLSNR, nrows=0)
    if ELECTRODE_COL not in snr_head.columns:
        raise ValueError(f"Missing column '{ELECTRODE_COL}' in '{SHEET_FULLSNR}'.")

    keep = [ELECTRODE_COL]
    half = float(settings.half_window_hz)
    harmonics = [float(h) for h in settings.oddball_harmonics_hz]
    for col in snr_head.columns:
        if col == ELECTRODE_COL:
            continue
        if not isinstance(col, str):
            continue
        m = _FREQ_COL_RE.match(col)
        if not m:
            continue
        f = float(m.group(1))
        for h in harmonics:
            if (h - half - 1e-12) <= f <= (h + half + 1e-12):
                keep.append(col)
                break

    seen = set()
    keep2 = []
    for c in keep:
        if c in seen:
            continue
        seen.add(c)
        keep2.append(c)

    df_snr = xl.parse(SHEET_FULLSNR, usecols=keep2)
    return df_z, df_snr


def _load_combined_z_from_df(df, settings: DetectabilitySettings):
    """
    Returns:
      electrodes_raw: list[str]
      z_comb: np.ndarray (per electrode)
      sig_mask: np.ndarray (bool per electrode)
    """
    import numpy as np
    import pandas as pd

    if ELECTRODE_COL not in df.columns:
        raise ValueError(f"Missing column '{ELECTRODE_COL}' in '{SHEET_Z}'.")

    freq_cols = _parse_freq_columns(df.columns)
    needed = [round(float(f), 4) for f in settings.oddball_harmonics_hz]
    missing = [f for f in needed if f not in freq_cols]
    if missing:
        miss_str = ", ".join([f"{f:.4f}_Hz" for f in missing])
        raise ValueError(f"Missing harmonic column(s) in '{SHEET_Z}': {miss_str}")

    z_cols = [freq_cols[round(float(f), 4)] for f in settings.oddball_harmonics_hz]
    electrodes_raw = df[ELECTRODE_COL].astype(str).tolist()

    z_mat = df[z_cols].apply(pd.to_numeric, errors="raise").to_numpy(dtype=float)
    if np.isnan(z_mat).any():
        raise ValueError(f"Found NaNs in '{SHEET_Z}' harmonic columns.")

    k = int(z_mat.shape[1])
    z_comb = z_mat.sum(axis=1) / math.sqrt(k) if k > 0 else np.full((z_mat.shape[0],), np.nan, dtype=float)

    sig = z_comb >= float(settings.z_threshold)

    if settings.use_bh_fdr:
        p_one = 1.0 - _norm_cdf(z_comb)  # one-tailed, positive direction
        reject = _bh_fdr_reject(p_one, alpha=float(settings.fdr_alpha))
        sig = sig & reject.astype(bool)

    return electrodes_raw, z_comb.astype(float), sig.astype(bool)


def _build_topomap_vector_finite(
    electrodes_raw: Sequence[str],
    z_comb,
    sig_mask,
    *,
    z_threshold: float,
):
    """
    Build montage-aligned vector with NO NaNs:
      - significant: Z_comb
      - non-significant/missing: Z_THRESHOLD (renders white)
    """
    import numpy as np

    info, name_to_idx = _get_montage_info()
    n_channels = len(info.ch_names)

    vec = np.full((n_channels,), float(z_threshold), dtype=float)

    for el, zc, ok in zip(electrodes_raw, z_comb, sig_mask):
        idx = name_to_idx.get(_normalize_electrode_name(el))
        if idx is None:
            continue
        vec[idx] = float(zc) if bool(ok) else float(z_threshold)

    _ensure_no_nan(vec)
    return vec


def _snr_freq_columns(df):
    import numpy as np

    freq_cols: list[str] = []
    freqs: list[float] = []
    for col in df.columns:
        if col == ELECTRODE_COL:
            continue
        if not isinstance(col, str):
            raise ValueError(f"Invalid frequency column '{col}'.")
        m = _FREQ_COL_RE.match(col)
        if not m:
            raise ValueError(f"Invalid frequency column '{col}'. Expected '*_Hz'.")
        freqs.append(float(m.group(1)))
        freq_cols.append(col)

    if not freq_cols:
        raise ValueError("No frequency columns found in FullSNR sheet.")
    return freq_cols, np.asarray(freqs, dtype=float)


def _load_snr_spectrum_from_df(
    df,
    settings: DetectabilitySettings,
    sig_mask,
    electrodes_raw: Sequence[str],
):
    """
    Returns:
      rel_freqs, snr_avg
    If n_sig == 0, returns (None, None) to match original behavior (blank SNR panel).
    """
    import numpy as np

    if ELECTRODE_COL not in df.columns:
        raise ValueError(f"Missing column '{ELECTRODE_COL}' in '{SHEET_FULLSNR}'.")

    df_electrodes = df[ELECTRODE_COL].astype(str).tolist()
    if [str(e).strip() for e in electrodes_raw] != [str(e).strip() for e in df_electrodes]:
        raise ValueError("Electrode ordering mismatch between Z Score and FullSNR sheets.")

    sig_indices = np.where(np.asarray(sig_mask, dtype=bool))[0]
    if sig_indices.size == 0:
        return None, None

    freq_cols, freqs = _snr_freq_columns(df)
    snr_data = df[freq_cols].to_numpy(dtype=float)

    base_rel = None
    harmonic_curves: list[np.ndarray] = []

    for harmonic in settings.oddball_harmonics_hz:
        lo = float(harmonic) - float(settings.half_window_hz)
        hi = float(harmonic) + float(settings.half_window_hz)
        mask = (freqs >= (lo - 1e-12)) & (freqs <= (hi + 1e-12))
        if not mask.any():
            raise ValueError(f"No SNR points within ±{settings.half_window_hz} Hz of {harmonic} Hz.")

        rel = freqs[mask] - float(harmonic)
        rel = np.round(rel, 4)
        mean_snr = snr_data[sig_indices][:, mask].mean(axis=0)

        if base_rel is None:
            base_rel = rel
            harmonic_curves.append(mean_snr)
        else:
            if rel.shape != base_rel.shape or not np.allclose(rel, base_rel):
                mean_snr = np.interp(base_rel, rel, mean_snr)
            harmonic_curves.append(mean_snr)

    if base_rel is None:
        return None, None

    snr_avg = np.mean(np.vstack(harmonic_curves), axis=0)
    return base_rel.astype(float), snr_avg.astype(float)


def _figure_size(ncols: int, nrows: int, use_letter: bool) -> tuple[float, float]:
    if use_letter:
        return (LETTER_W_IN, LETTER_H_IN)
    width = max(6.0, ncols * 3.0)
    height = max(4.5, nrows * 3.0)
    return (width, height)


# -----------------------------------------------------------------------------
# Worker (process-safe, picklable)
# -----------------------------------------------------------------------------
def _process_one_participant(
    excel_path_str: str,
    pid: str,
    settings: DetectabilitySettings,
    cache_dir_str: str,
) -> _ParticipantResult:
    import numpy as np

    excel_path = Path(excel_path_str)
    cache_dir = Path(cache_dir_str)
    cache_path = _cache_path_for(excel_path, settings, cache_dir)

    try:
        if cache_path.exists():
            return _load_cache_npz(cache_path)
    except Exception:
        try:
            cache_path.unlink()
        except Exception:
            pass

    try:
        df_z, df_snr = _excel_minimal_read(excel_path, settings)

        electrodes_raw, z_comb, sig_mask = _load_combined_z_from_df(df_z, settings)
        n_sig = int(np.sum(sig_mask))

        z_topo = _build_topomap_vector_finite(
            electrodes_raw=electrodes_raw,
            z_comb=z_comb,
            sig_mask=sig_mask,
            z_threshold=float(settings.z_threshold),
        )

        snr_x, snr_y = _load_snr_spectrum_from_df(
            df=df_snr,
            settings=settings,
            sig_mask=sig_mask,
            electrodes_raw=electrodes_raw,
        )

        try:
            _save_cache_npz(
                cache_path,
                pid=pid,
                n_sig=n_sig,
                z_topo=z_topo,
                snr_x=snr_x,
                snr_y=snr_y,
            )
        except Exception:
            pass

        return _ParticipantResult(
            pid=pid,
            ok=True,
            n_sig=n_sig,
            z_topo=z_topo,
            snr_x=snr_x,
            snr_y=snr_y,
        )
    except Exception as e:
        return _ParticipantResult(
            pid=pid,
            ok=False,
            err=str(e),
            tb=traceback.format_exc(),
        )


def generate_condition_figure(
    condition: ConditionInfo,
    output_dir: Path,
    output_stem: str,
    excluded: set[str],
    settings: DetectabilitySettings,
    export_png: bool,
    log: Callable[[str], None],
) -> tuple[int, int]:
    """
    Generates the grid figure for a condition, matching the original output style:
      - PID numeric ordering (P7 before P10)
      - Thresholded YlOrRd colormap (white below z_threshold)
      - Shared colorbar legend at bottom
      - Each topo shows "n=<sig electrodes>"
      - SNR panel is hidden when n=0 (blank)
      - Fixed SNR y-axis [0, 2], ref lines at x=0 and y=1
      - Y-label only once per row; X-label only on last row

    Performance:
      - Per-file processing runs in a 3-process pool
      - Disk cache avoids re-reading Excel on reruns
      - Excel reads are minimized via usecols on both sheets
    """
    import numpy as np
    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt
    import matplotlib as mpl

    # Times New Roman everywhere (fallbacks included)
    plt.rcParams.update(
        {
            "font.family": "serif",
            "font.serif": ["Times New Roman", "Times", "DejaVu Serif"],
            "font.size": 9,
            "axes.titlesize": 9,
            "axes.labelsize": 9,
            "xtick.labelsize": 8,
            "ytick.labelsize": 8,
            "svg.fonttype": "none",  # keep text as text in SVG when possible
        }
    )

    # Enforce the "max 10 columns" rule here (GUI should also enforce upstream)
    try:
        requested_cols = int(settings.grid_ncols)
    except Exception:
        requested_cols = 8
    if requested_cols > _MAX_GRID_NCOLS:
        raise ValueError(
            f"grid_ncols={requested_cols} is not allowed. "
            f"Maximum supported columns is {_MAX_GRID_NCOLS}."
        )
    if requested_cols < 1:
        requested_cols = 1

    output_dir.mkdir(parents=True, exist_ok=True)
    total = len(condition.files)

    cache_dir = condition.path / _CACHE_DIRNAME
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        cache_dir = output_dir / _CACHE_DIRNAME
        cache_dir.mkdir(parents=True, exist_ok=True)

    tasks: list[tuple[Path, str]] = []
    records: list[tuple[str, int, np.ndarray, np.ndarray | None, np.ndarray | None]] = []

    for excel_path in condition.files:
        pid = parse_participant_id(excel_path.stem)
        if not pid:
            log(f"Skipping {excel_path.name}: could not parse participant ID.")
            continue
        if pid in excluded:
            log(f"Skipping {excel_path.name}: excluded participant {pid}.")
            continue

        cache_path = _cache_path_for(excel_path, settings, cache_dir)
        if cache_path.exists():
            try:
                cached = _load_cache_npz(cache_path)
                if cached.ok and cached.z_topo is not None:
                    records.append((cached.pid, cached.n_sig, cached.z_topo, cached.snr_x, cached.snr_y))
                    continue
            except Exception:
                try:
                    cache_path.unlink()
                except Exception:
                    pass

        tasks.append((excel_path, pid))

    if tasks:
        try:
            from concurrent.futures import ProcessPoolExecutor, as_completed

            max_workers = max(1, int(_PARALLEL_WORKERS))
            max_workers = min(max_workers, 3)  # hard cap requested

            with ProcessPoolExecutor(max_workers=max_workers) as ex:
                futs = [
                    ex.submit(_process_one_participant, str(p), pid, settings, str(cache_dir))
                    for (p, pid) in tasks
                ]
                for fut in as_completed(futs):
                    res = fut.result()
                    if not res.ok:
                        log(f"Error processing participant file: {res.pid} | {res.err}")
                        continue
                    if res.z_topo is None:
                        log(f"Error processing participant file: {res.pid} | Missing z_topo")
                        continue
                    records.append((res.pid, res.n_sig, res.z_topo, res.snr_x, res.snr_y))
        except Exception as e:
            log(f"Parallel processing unavailable; falling back to sequential. Reason: {e}")
            for p, pid in tasks:
                res = _process_one_participant(str(p), pid, settings, str(cache_dir))
                if not res.ok:
                    log(f"Error processing participant file: {res.pid} | {res.err}")
                    continue
                if res.z_topo is None:
                    log(f"Error processing participant file: {res.pid} | Missing z_topo")
                    continue
                records.append((res.pid, res.n_sig, res.z_topo, res.snr_x, res.snr_y))

    if not records:
        log(f"No participants to plot for {condition.name}.")
        return 0, total

    records.sort(key=lambda r: _pid_sort_key(r[0]))

    n = len(records)
    ncols = requested_cols
    nrows = int(math.ceil(n / ncols))

    fig_w, fig_h = _figure_size(ncols, nrows, settings.use_letter_portrait)
    fig = plt.figure(figsize=(fig_w, fig_h))

    if settings.use_letter_portrait:
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
    else:
        gs = fig.add_gridspec(
            nrows=2 * nrows,
            ncols=ncols,
            hspace=HSPACE,
            wspace=WSPACE,
        )

    cmap = _make_thresholded_cmap("YlOrRd", white_frac=0.08)
    vmin = float(settings.z_threshold)
    vmax = float(max(np.max(r[2]) for r in records))
    if not np.isfinite(vmax) or vmax <= vmin:
        vmax = vmin + 1.0

    info, _ = _get_montage_info()

    row_ylabel_set = [False for _ in range(nrows)]

    for i in range(nrows * ncols):
        rr = i // ncols
        cc = i % ncols

        ax_topo = fig.add_subplot(gs[2 * rr, cc])
        ax_snr = fig.add_subplot(gs[2 * rr + 1, cc])

        if i >= n:
            ax_topo.axis("off")
            ax_snr.axis("off")
            continue

        pid, n_sig, z_topo, snr_x, snr_y = records[i]

        _plot_topomap_compat(z_topo, info, ax_topo, cmap, vmin=vmin, vmax=vmax)
        ax_topo.set_title(f"{pid}", fontsize=9, pad=1)
        ax_topo.text(
            0.5,
            -0.10,
            f"n={n_sig}",
            transform=ax_topo.transAxes,
            ha="center",
            va="top",
            fontsize=8,
        )

        if n_sig <= 0 or snr_x is None or snr_y is None:
            ax_snr.axis("off")
            continue

        ax_snr.axvline(0.0, linewidth=0.9, color="0.55")
        ax_snr.axhline(1.0, linewidth=0.9, linestyle="--", color="0.70")
        ax_snr.plot(snr_x, snr_y, linewidth=0.9, color="0.35")

        ax_snr.set_xlim(-float(settings.half_window_hz), float(settings.half_window_hz))
        ax_snr.set_ylim(float(settings.snr_ymin_fixed), float(settings.snr_ymax_fixed))

        if settings.snr_show_mid_xtick:
            ax_snr.set_xticks(
                [
                    -float(settings.half_window_hz),
                    -float(settings.half_window_hz) / 2.0,
                    0.0,
                    float(settings.half_window_hz) / 2.0,
                    float(settings.half_window_hz),
                ]
            )
        else:
            ax_snr.set_xticks([-float(settings.half_window_hz), 0.0, float(settings.half_window_hz)])
            ax_snr.set_xticklabels(
                [f"{-float(settings.half_window_hz):.1f}", "0", f"{float(settings.half_window_hz):.1f}"]
            )

        ax_snr.tick_params(labelsize=8)
        for spine in ["top", "right"]:
            ax_snr.spines[spine].set_visible(False)

        if not row_ylabel_set[rr]:
            ax_snr.set_ylabel("SNR", fontsize=9)
            row_ylabel_set[rr] = True
        else:
            ax_snr.set_ylabel("")
            ax_snr.set_yticklabels([])

        if rr == nrows - 1:
            ax_snr.set_xlabel("Rel. freq (Hz)", fontsize=9, labelpad=_XLABEL_PAD)
        else:
            ax_snr.set_xlabel("")
            ax_snr.set_xticklabels([])

    cbar_w = float(COLORBAR_WIDTH_FRAC)
    cbar_h = float(COLORBAR_HEIGHT_FRAC)
    cbar_left = (1.0 - cbar_w) / 2.0

    if settings.use_letter_portrait:
        band_bottom = float(PAGE_MARGIN_IN) / float(LETTER_H_IN)
        band_top = (float(PAGE_MARGIN_IN) + float(COLORBAR_BAND_IN)) / float(LETTER_H_IN)
        band_h = max(1e-6, (band_top - band_bottom))
        cbar_bottom = band_bottom + _CBAR_Y_FRAC_IN_BAND * (band_h - cbar_h)
    else:
        cbar_bottom = 0.06

    cax = fig.add_axes([cbar_left, cbar_bottom, cbar_w, cbar_h])
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=mpl.colors.Normalize(vmin=vmin, vmax=vmax))
    sm.set_array([])
    cb = fig.colorbar(sm, cax=cax, orientation="horizontal")
    cb.set_ticks([])
    cb.ax.tick_params(length=0)
    cb.set_label("Z-Score", fontsize=_LEGEND_LABEL_FONTSIZE, labelpad=3)

    y_text = max(0.0, cbar_bottom - _CBAR_TEXT_PAD_FRAC)
    fig.text(
        cbar_left,
        y_text,
        f"White = z < {settings.z_threshold:g}",
        ha="left",
        va="top",
        fontsize=_LEGEND_SIDE_TEXT_FONTSIZE,
    )
    fig.text(
        cbar_left + cbar_w,
        y_text,
        "Max",
        ha="right",
        va="top",
        fontsize=_LEGEND_SIDE_TEXT_FONTSIZE,
    )

    svg_path = output_dir / f"{sanitize_filename_stem(output_stem)}.svg"
    fig.savefig(svg_path, format="svg", dpi=FIG_DPI)

    if export_png:
        png_path = output_dir / f"{sanitize_filename_stem(output_stem)}.png"
        fig.savefig(png_path, format="png", dpi=FIG_DPI)

    plt.close(fig)
    return n, total
