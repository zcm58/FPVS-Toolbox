"""Utilities for scalp map preparation."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Iterable, Sequence

import mne
import numpy as np
import pandas as pd

ODDBALL_THRESHOLD = 1.64


@dataclass
class ScalpInputs:
    """Container for scalp map inputs."""

    data: np.ndarray
    info: mne.io.Info


def _freq_columns(df: pd.DataFrame) -> dict[float, str]:
    mapping: dict[float, str] = {}
    for col in df.columns:
        if isinstance(col, str) and col.endswith("_Hz"):
            try:
                freq_val = float(col.split("_")[0])
            except ValueError:
                continue
            mapping[round(freq_val, 4)] = col
    return mapping


def _is_base_harmonic(freq: float, base_freq: float) -> bool:
    if base_freq <= 0:
        return False
    ratio = freq / base_freq
    nearest = round(ratio)
    return math.isclose(ratio, nearest, rel_tol=1e-3, abs_tol=1e-3) and nearest > 0


def select_oddball_harmonics(
    configured: Iterable[float],
    *,
    base_freq: float,
) -> list[float]:
    """Return oddball harmonics excluding base-rate harmonics."""

    oddballs: list[float] = []
    for freq in configured:
        if _is_base_harmonic(freq, base_freq):
            continue
        if not math.isfinite(freq):
            continue
        oddballs.append(freq)
    return oddballs


def _electrode_row(df: pd.DataFrame, electrode: str) -> pd.Series | None:
    mask = df["Electrode"].astype(str).str.upper() == electrode
    if not mask.any():
        return None
    return df.loc[mask].iloc[0]


def summarize_subject_scalp(
    df_bca: pd.DataFrame,
    df_z: pd.DataFrame,
    oddballs: Sequence[float],
) -> dict[str, float]:
    """Compute per-electrode oddball sums for a subject."""

    freq_cols_bca = _freq_columns(df_bca)
    freq_cols_z = _freq_columns(df_z)
    values: dict[str, float] = {}
    electrodes = df_bca["Electrode"].astype(str).str.upper()
    for electrode in electrodes:
        bca_row = _electrode_row(df_bca, electrode)
        z_row = _electrode_row(df_z, electrode)
        if bca_row is None or z_row is None:
            continue
        total = 0.0
        for freq in oddballs:
            key = round(freq, 4)
            bca_col = freq_cols_bca.get(key)
            z_col = freq_cols_z.get(key)
            if not bca_col or not z_col:
                continue
            try:
                z_val = float(z_row[z_col])
                bca_val = float(bca_row[bca_col])
            except Exception:
                continue
            if z_val >= ODDBALL_THRESHOLD:
                total += bca_val
        values[electrode] = total
    return values


def prepare_scalp_inputs(
    subject_maps: Dict[str, Dict[str, float]],
    roi_channels: Sequence[str] | None = None,
    *,
    mask_non_roi: bool = False,
) -> ScalpInputs | None:
    """Aggregate subject scalp maps and return data aligned to BioSemi64.

    The default behavior returns whole-head values without masking electrodes
    outside the selected ROI. Set ``mask_non_roi`` to ``True`` to zero out
    electrodes that are not part of the ROI channel list.
    """

    if not subject_maps:
        return None

    montage = mne.channels.make_standard_montage("biosemi64")
    info = mne.create_info(ch_names=montage.ch_names, sfreq=100, ch_types="eeg")
    info.set_montage(montage)
    name_to_idx = {name.upper(): idx for idx, name in enumerate(info.ch_names)}

    data_matrix = np.full((len(subject_maps), len(info.ch_names)), np.nan)
    for row_idx, electrode_map in enumerate(subject_maps.values()):
        for name, value in electrode_map.items():
            idx = name_to_idx.get(name.upper())
            if idx is None:
                continue
            data_matrix[row_idx, idx] = value

    mean_values = np.nanmean(data_matrix, axis=0)
    if np.isnan(mean_values).all():
        return None

    mean_values = np.nan_to_num(mean_values, nan=0.0)
    if mask_non_roi and roi_channels:
        roi_set = {c.upper() for c in roi_channels}
        mask = [name.upper() not in roi_set for name in info.ch_names]
        mean_values[mask] = 0.0
    return ScalpInputs(data=mean_values, info=info)
