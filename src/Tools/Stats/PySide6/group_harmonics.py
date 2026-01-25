"""Helpers for Group Mean-Z harmonic union selection."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Sequence

import numpy as np
import pandas as pd

from Tools.Stats.Legacy.excel_io import safe_read_excel
from Tools.Stats.Legacy.stats_analysis import (
    SUMMED_BCA_ODDBALL_EVERY_N_DEFAULT,
    SUMMED_BCA_Z_SHEET_NAME,
    _match_freq_column,
    filter_to_oddball_harmonics,
    get_included_freqs,
)


@dataclass(frozen=True)
class GroupMeanZSummary:
    harmonic_freqs: List[float]
    mean_z_table: pd.DataFrame
    columns: pd.Index


def _find_first_z_columns(
    subjects: List[str],
    conditions: List[str],
    subject_data: Dict[str, Dict[str, str]],
    log_func: Callable[[str], None],
) -> pd.Index:
    for pid in subjects:
        for cond_name in conditions:
            file_path = subject_data.get(pid, {}).get(cond_name)
            if not file_path:
                continue
            try:
                df_z = safe_read_excel(
                    file_path, sheet_name=SUMMED_BCA_Z_SHEET_NAME, index_col="Electrode"
                )
                return df_z.columns
            except Exception as exc:  # noqa: BLE001
                log_func(f"Failed to read Z columns from {file_path}: {exc}")
    return pd.Index([])


def _build_harmonic_domain(
    columns: Iterable[object],
    base_freq: float,
    log_func: Callable[[str], None],
) -> List[float]:
    freq_candidates = get_included_freqs(base_freq, columns, log_func)
    if not freq_candidates:
        return []
    oddball_list = filter_to_oddball_harmonics(
        freq_candidates,
        base_freq,
        every_n=SUMMED_BCA_ODDBALL_EVERY_N_DEFAULT,
        tol=1e-3,
    )
    return [freq for freq, _k in oddball_list]


def compute_union_harmonics_by_roi(
    mean_z_table: pd.DataFrame,
    *,
    conditions: Sequence[str],
    z_threshold: float,
) -> dict[str, list[float]]:
    union_map: dict[str, list[float]] = {}
    if mean_z_table.empty:
        return union_map

    filtered = mean_z_table[mean_z_table["condition"].isin(conditions)]
    grouped = filtered.groupby("roi")
    for roi_name, roi_df in grouped:
        sig_df = roi_df[roi_df["mean_z"] > z_threshold]
        harmonics = sorted(sig_df["harmonic_hz"].unique().tolist())
        union_map[str(roi_name)] = harmonics
    return union_map


def build_group_mean_z_summary(
    *,
    subjects: List[str],
    conditions: List[str],
    subject_data: Dict[str, Dict[str, str]],
    base_freq: float,
    rois: Dict[str, List[str]],
    z_threshold: float,
    log_func: Callable[[str], None],
) -> GroupMeanZSummary:
    columns = _find_first_z_columns(subjects, conditions, subject_data, log_func)
    harmonic_freqs = _build_harmonic_domain(columns, base_freq, log_func)
    if not harmonic_freqs:
        raise RuntimeError(
            "Group Mean-Z harmonics selection produced an empty list. "
            "Verify Z-score sheets and base frequency."
        )

    roi_map = rois
    mean_values: dict[tuple[str, str, float], list[float]] = {}

    for pid in subjects:
        for cond_name in conditions:
            file_path = subject_data.get(pid, {}).get(cond_name)
            if not file_path:
                log_func(f"Missing file for {pid} {cond_name}: {file_path}")
                continue
            if not Path(file_path).exists():
                log_func(f"Missing file for {pid} {cond_name}: {file_path}")
                continue
            try:
                df_z = safe_read_excel(
                    file_path, sheet_name=SUMMED_BCA_Z_SHEET_NAME, index_col="Electrode"
                )
            except Exception as exc:  # noqa: BLE001
                log_func(f"Failed to read Z sheet from {file_path}: {exc}")
                continue

            df_z.index = df_z.index.astype(str).str.upper().str.strip()
            col_map = {freq: _match_freq_column(df_z.columns, freq) for freq in harmonic_freqs}

            for roi_name, roi_channels in roi_map.items():
                roi_chans = [
                    str(ch).strip().upper()
                    for ch in (roi_channels or [])
                    if str(ch).strip().upper() in df_z.index
                ]
                if not roi_chans:
                    log_func(f"No overlapping Z data for ROI {roi_name} in {file_path}.")
                    continue
                df_roi = df_z.loc[roi_chans].dropna(how="all")
                if df_roi.empty:
                    log_func(f"No Z data for ROI {roi_name} in {file_path}.")
                    continue

                for freq_val in harmonic_freqs:
                    col_z = col_map.get(freq_val)
                    if not col_z:
                        continue
                    series = pd.to_numeric(df_roi[col_z], errors="coerce").replace(
                        [np.inf, -np.inf], np.nan
                    )
                    mean_val = float(series.mean(skipna=True))
                    if not np.isfinite(mean_val):
                        continue
                    key = (cond_name, roi_name, float(freq_val))
                    mean_values.setdefault(key, []).append(mean_val)

    rows = []
    for (cond_name, roi_name, freq_val), values in mean_values.items():
        mean_val = float(np.nanmean(values)) if values else np.nan
        rows.append(
            {
                "condition": cond_name,
                "roi": roi_name,
                "harmonic_hz": float(freq_val),
                "mean_z": mean_val,
                "significant": bool(mean_val > z_threshold),
            }
        )

    mean_z_table = pd.DataFrame(rows)
    if not mean_z_table.empty:
        mean_z_table = mean_z_table.sort_values(["roi", "condition", "harmonic_hz"])

    return GroupMeanZSummary(
        harmonic_freqs=harmonic_freqs,
        mean_z_table=mean_z_table,
        columns=columns,
    )
