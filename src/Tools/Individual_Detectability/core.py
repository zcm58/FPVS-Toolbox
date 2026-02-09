from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import math
import re
from typing import Callable, Iterable, Sequence, TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np


SHEET_Z = "Z Score"
SHEET_FULLSNR = "FullSNR"
ELECTRODE_COL = "Electrode"

_PID_SCP_RE = re.compile(r"SCP0*(\d+)", re.IGNORECASE)
_PID_P_RE = re.compile(r"\bP0*(\d+)\b", re.IGNORECASE)
_ILLEGAL_FILENAME = re.compile(r'[<>:"/\\\\|?*]+')


@dataclass(frozen=True)
class DetectabilitySettings:
    oddball_harmonics_hz: list[float] = field(
        default_factory=lambda: [1.2, 2.4, 3.6, 4.8, 6.0]
    )
    z_threshold: float = 1.64
    use_bh_fdr: bool = True
    fdr_alpha: float = 0.05
    half_window_hz: float = 0.4
    snr_ymin_fixed: float = 0.0
    snr_ymax_fixed: float = 2.0
    snr_show_mid_xtick: bool = True
    grid_ncols: int = 4
    use_letter_portrait: bool = True


@dataclass(frozen=True)
class ConditionInfo:
    name: str
    path: Path
    files: list[Path]


def parse_participant_id(filename: str) -> str | None:
    match = _PID_SCP_RE.search(filename)
    if match:
        return f"P{int(match.group(1))}"
    match = _PID_P_RE.search(filename)
    if match:
        return f"P{int(match.group(1))}"
    return None


def sanitize_filename_stem(value: str) -> str:
    cleaned = _ILLEGAL_FILENAME.sub("_", value).strip().strip(".")
    return cleaned if cleaned else "output"


def discover_conditions(root: Path) -> list[ConditionInfo]:
    if not root.exists():
        return []
    subfolders = sorted([p for p in root.iterdir() if p.is_dir()])
    conditions: list[ConditionInfo] = []
    for sub in subfolders:
        files = sorted(sub.glob("*.xlsx"))
        if files:
            conditions.append(ConditionInfo(name=sub.name, path=sub, files=files))
    if conditions:
        return conditions
    files = sorted(root.glob("*.xlsx"))
    if files:
        return [ConditionInfo(name=root.name, path=root, files=files)]
    return []


def render_topomap_svg(
    z_values: Sequence[float],
    electrodes: Sequence[str],
    z_threshold: float,
    output_path: Path,
) -> None:
    _ensure_no_nan(z_values)
    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap
    import numpy as np

    z_array = np.asarray(z_values, dtype=float)
    z_display = np.where(z_array >= z_threshold, z_array, z_threshold)
    pos = _resolve_biosemi_positions(electrodes)
    cmap = LinearSegmentedColormap.from_list(
        "detectability_z",
        ["#ffffff", "#2166ac", "#b2182b"],
    )
    vmax = float(max(float(z_display.max()), z_threshold + 1e-6))
    fig, ax = plt.subplots(figsize=(2.4, 2.2))
    _plot_topomap_compat(
        z_display,
        pos,
        axes=ax,
        vmin=z_threshold,
        vmax=vmax,
        contours=0,
        cmap=cmap,
    )
    fig.savefig(output_path, format="svg")
    plt.close(fig)


def generate_condition_figure(
    condition: ConditionInfo,
    output_dir: Path,
    output_stem: str,
    excluded: set[str],
    settings: DetectabilitySettings,
    export_png: bool,
    log: Callable[[str], None],
) -> tuple[int, int]:
    import numpy as np
    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt

    output_dir.mkdir(parents=True, exist_ok=True)
    participants: list[str] = []
    topo_values: list[np.ndarray] = []
    spectra: list[tuple[np.ndarray, np.ndarray]] = []

    for excel_path in condition.files:
        pid = parse_participant_id(excel_path.stem)
        if not pid:
            log(f"Skipping {excel_path.name}: could not parse participant ID.")
            continue
        if pid in excluded:
            log(f"Skipping {excel_path.name}: excluded participant {pid}.")
            continue
        try:
            combined_z, sig_mask, electrodes = _load_combined_z(
                excel_path,
                settings,
            )
            freqs, snr_avg = _load_snr_spectrum(
                excel_path,
                settings,
                sig_mask,
                electrodes,
                log,
            )
        except Exception as exc:
            log(f"Error processing {excel_path.name}: {exc}")
            continue
        participants.append(pid)
        topo_values.append(combined_z)
        spectra.append((freqs, snr_avg))

    if not participants:
        log(f"No participants to plot for {condition.name}.")
        return 0, len(condition.files)

    ncols = max(1, int(settings.grid_ncols))
    nrows = int(math.ceil(len(participants) / ncols))
    fig_w, fig_h = _figure_size(ncols, nrows, settings.use_letter_portrait)
    fig = plt.figure(figsize=(fig_w, fig_h))
    gs = fig.add_gridspec(nrows * 2, ncols, height_ratios=[1, 0.9] * nrows)

    for idx, pid in enumerate(participants):
        row = (idx // ncols) * 2
        col = idx % ncols
        ax_topo = fig.add_subplot(gs[row, col])
        ax_snr = fig.add_subplot(gs[row + 1, col])

        z_display = np.where(
            topo_values[idx] >= settings.z_threshold,
            topo_values[idx],
            settings.z_threshold,
        )
        _ensure_no_nan(z_display)
        pos = _resolve_biosemi_positions(electrodes)
        cmap = _detectability_cmap()
        vmax = float(max(float(z_display.max()), settings.z_threshold + 1e-6))
        _plot_topomap_compat(
            z_display,
            pos,
            axes=ax_topo,
            vmin=settings.z_threshold,
            vmax=vmax,
            contours=0,
            cmap=cmap,
        )
        ax_topo.set_title(pid, fontsize=10)

        rel_freqs, snr_avg = spectra[idx]
        ax_snr.plot(rel_freqs, snr_avg, color="#2166ac", linewidth=1.2)
        ax_snr.axvline(0, color="#777777", linewidth=0.8, linestyle="--")
        ax_snr.axhline(1, color="#777777", linewidth=0.8, linestyle="--")
        ax_snr.set_xlim(-settings.half_window_hz, settings.half_window_hz)
        ax_snr.set_ylim(settings.snr_ymin_fixed, settings.snr_ymax_fixed)
        if settings.snr_show_mid_xtick:
            ax_snr.set_xticks(
                [-settings.half_window_hz, 0, settings.half_window_hz]
            )
        else:
            ax_snr.set_xticks(
                [-settings.half_window_hz, settings.half_window_hz]
            )
        ax_snr.tick_params(labelsize=8)

    fig.tight_layout()
    svg_path = output_dir / f"{output_stem}.svg"
    fig.savefig(svg_path, format="svg")
    if export_png:
        png_path = output_dir / f"{output_stem}.png"
        fig.savefig(png_path, format="png", dpi=600)
    plt.close(fig)
    return len(participants), len(condition.files)


def _figure_size(ncols: int, nrows: int, use_letter: bool) -> tuple[float, float]:
    if use_letter:
        return (8.5, 11.0)
    width = max(6.0, ncols * 3.0)
    height = max(4.5, nrows * 3.0)
    return (width, height)


def _ensure_no_nan(values: Sequence[float]) -> None:
    import numpy as np

    array = np.asarray(values, dtype=float)
    if np.isnan(array).any():
        raise ValueError("Z topomap values contain NaNs; cannot render.")


def _detectability_cmap():
    from matplotlib.colors import LinearSegmentedColormap

    return LinearSegmentedColormap.from_list(
        "detectability_z",
        ["#ffffff", "#2166ac", "#b2182b"],
    )


def _plot_topomap_compat(
    z_values,
    pos,
    axes,
    vmin: float,
    vmax: float,
    contours: int,
    cmap,
    sensor_kwargs: dict | None = None,
) -> None:
    import mne

    base_kwargs = {
        "axes": axes,
        "show": False,
        "contours": contours,
        "cmap": cmap,
    }
    if sensor_kwargs is not None:
        base_kwargs["sensor_kwargs"] = sensor_kwargs

    try:
        mne.viz.plot_topomap(z_values, pos, vlim=(vmin, vmax), **base_kwargs)
        return
    except TypeError:
        pass

    if sensor_kwargs is not None:
        kwargs_no_sensors = base_kwargs.copy()
        kwargs_no_sensors.pop("sensor_kwargs", None)
        try:
            mne.viz.plot_topomap(z_values, pos, vlim=(vmin, vmax), **kwargs_no_sensors)
            return
        except TypeError:
            pass

    try:
        mne.viz.plot_topomap(
            z_values,
            pos,
            vmin=vmin,
            vmax=vmax,
            **base_kwargs,
        )
    except TypeError:
        if sensor_kwargs is None:
            raise
        kwargs_no_sensors = base_kwargs.copy()
        kwargs_no_sensors.pop("sensor_kwargs", None)
        mne.viz.plot_topomap(
            z_values,
            pos,
            vmin=vmin,
            vmax=vmax,
            **kwargs_no_sensors,
        )


def _resolve_biosemi_positions(electrodes: Sequence[str]):
    import mne
    import numpy as np

    montage = mne.channels.make_standard_montage("biosemi64")
    ch_pos = montage.get_positions()["ch_pos"]
    upper_map = {name.upper(): pos for name, pos in ch_pos.items()}
    missing = [name for name in electrodes if name.upper() not in upper_map]
    if missing:
        example = ", ".join(missing[:5])
        raise ValueError(
            "Unrecognized electrodes in Excel export: "
            f"{example} (and {max(0, len(missing) - 5)} more)."
        )
    pos = np.array([upper_map[name.upper()] for name in electrodes], dtype=float)
    return pos


def _load_combined_z(
    excel_path: Path,
    settings: DetectabilitySettings,
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    import numpy as np
    import pandas as pd
    from scipy.stats import norm
    import mne

    try:
        df = pd.read_excel(excel_path, sheet_name=SHEET_Z)
    except Exception as exc:
        raise ValueError(f"Missing required sheet '{SHEET_Z}'.") from exc
    if ELECTRODE_COL not in df.columns:
        raise ValueError(f"Missing column '{ELECTRODE_COL}' in '{SHEET_Z}'.")
    electrodes = df[ELECTRODE_COL].astype(str).tolist()
    freq_cols = _select_harmonic_columns(df, settings.oddball_harmonics_hz)
    z_values = df[freq_cols].to_numpy(dtype=float)
    if np.isnan(z_values).any():
        raise ValueError(f"Found NaNs in '{SHEET_Z}' harmonic columns.")
    combined = z_values.sum(axis=1) / math.sqrt(len(freq_cols))
    if settings.use_bh_fdr:
        pvals = norm.sf(np.abs(combined)) * 2
        reject, _ = mne.stats.fdr_correction(pvals, alpha=settings.fdr_alpha)
        sig_mask = reject
    else:
        sig_mask = combined >= settings.z_threshold
    return combined, sig_mask, electrodes


def _load_snr_spectrum(
    excel_path: Path,
    settings: DetectabilitySettings,
    sig_mask: np.ndarray,
    electrodes: Sequence[str],
    log: Callable[[str], None],
) -> tuple[np.ndarray, np.ndarray]:
    import numpy as np
    import pandas as pd

    try:
        df = pd.read_excel(excel_path, sheet_name=SHEET_FULLSNR)
    except Exception as exc:
        raise ValueError(f"Missing required sheet '{SHEET_FULLSNR}'.") from exc
    if ELECTRODE_COL not in df.columns:
        raise ValueError(f"Missing column '{ELECTRODE_COL}' in '{SHEET_FULLSNR}'.")
    df_electrodes = df[ELECTRODE_COL].astype(str).str.upper().tolist()
    if [e.upper() for e in electrodes] != df_electrodes:
        raise ValueError("Electrode ordering mismatch between Z and FullSNR sheets.")

    freq_cols, freqs = _snr_freq_columns(df)
    snr_data = df[freq_cols].to_numpy(dtype=float)

    sig_indices = np.where(sig_mask)[0]
    if sig_indices.size == 0:
        log("No significant electrodes found; using all electrodes for SNR average.")
        sig_indices = np.arange(snr_data.shape[0])

    base_rel: np.ndarray | None = None
    harmonic_curves: list[np.ndarray] = []

    for harmonic in settings.oddball_harmonics_hz:
        mask = (freqs >= harmonic - settings.half_window_hz) & (
            freqs <= harmonic + settings.half_window_hz
        )
        if not mask.any():
            raise ValueError(
                f"No SNR points within {settings.half_window_hz} Hz of {harmonic} Hz."
            )
        rel = freqs[mask] - harmonic
        mean_snr = snr_data[sig_indices][:, mask].mean(axis=0)
        if base_rel is None:
            base_rel = rel
            harmonic_curves.append(mean_snr)
        else:
            if rel.shape != base_rel.shape or not np.allclose(rel, base_rel):
                mean_snr = np.interp(base_rel, rel, mean_snr)
            harmonic_curves.append(mean_snr)

    if base_rel is None:
        raise ValueError("No harmonics available for SNR averaging.")
    snr_avg = np.mean(np.vstack(harmonic_curves), axis=0)
    return base_rel, snr_avg


def _snr_freq_columns(df) -> tuple[list[str], np.ndarray]:
    import numpy as np

    freq_cols: list[str] = []
    freqs: list[float] = []
    for col in df.columns:
        if col == ELECTRODE_COL:
            continue
        freq_val = _extract_float(col)
        if freq_val is None:
            raise ValueError(f"Invalid frequency column '{col}'.")
        freq_cols.append(col)
        freqs.append(freq_val)
    if not freq_cols:
        raise ValueError("No frequency columns found in FullSNR sheet.")
    return freq_cols, np.asarray(freqs, dtype=float)


def _select_harmonic_columns(df, harmonics: Iterable[float]) -> list[str]:
    cols = {}
    for col in df.columns:
        if col == ELECTRODE_COL:
            continue
        freq_val = _extract_float(col)
        if freq_val is not None:
            cols[_round_hz(freq_val)] = col
    selected: list[str] = []
    missing: list[str] = []
    for hz in harmonics:
        key = _round_hz(hz)
        col = cols.get(key)
        if col is None:
            missing.append(f"{hz:g}")
        else:
            selected.append(col)
    if missing:
        raise ValueError(
            "Missing required harmonics in Z Score sheet: "
            + ", ".join(missing)
        )
    return selected


def _extract_float(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value)
    match = re.search(r"([-+]?\d*\.?\d+)", text)
    if not match:
        return None
    return float(match.group(1))


def _round_hz(value: float) -> float:
    return float(round(float(value), 6))
