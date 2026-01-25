"""Helpers for Group Mean-Z and Rossion harmonic selection."""
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


@dataclass(frozen=True)
class RossionHarmonicsSummary:
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
    *,
    exclude_harmonic1: bool = False,
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
    harmonic_freqs = [freq for freq, _k in oddball_list]
    if exclude_harmonic1:
        harmonic_freqs = [
            freq
            for freq, _k in oddball_list
            if int(_k) != 1
        ]
    return harmonic_freqs


def build_rossion_harmonics_summary(
    *,
    subjects: List[str],
    conditions: List[str],
    subject_data: Dict[str, Dict[str, str]],
    base_freq: float,
    rois: Dict[str, List[str]],
    z_threshold: float,
    exclude_harmonic1: bool,
    log_func: Callable[[str], None],
) -> RossionHarmonicsSummary:
    columns = _find_first_z_columns(subjects, conditions, subject_data, log_func)
    harmonic_freqs = _build_harmonic_domain(
        columns,
        base_freq,
        log_func,
        exclude_harmonic1=exclude_harmonic1,
    )
    if not harmonic_freqs:
        raise RuntimeError(
            "Rossion harmonics selection produced an empty list. "
            "Verify Z-score sheets and base frequency."
        )

    mean_values: dict[tuple[str, float], list[float]] = {}

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

            for roi_name, roi_channels in rois.items():
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
                    key = (roi_name, float(freq_val))
                    mean_values.setdefault(key, []).append(mean_val)

    rows = []
    for (roi_name, freq_val), values in mean_values.items():
        mean_val = float(np.nanmean(values)) if values else np.nan
        rows.append(
            {
                "roi": roi_name,
                "harmonic_hz": float(freq_val),
                "mean_z": mean_val,
                "n_cells": int(len(values)),
                "significant": bool(np.isfinite(mean_val) and mean_val > z_threshold),
            }
        )

    mean_z_table = pd.DataFrame(rows)
    if not mean_z_table.empty:
        mean_z_table = mean_z_table.sort_values(["roi", "harmonic_hz"])

    return RossionHarmonicsSummary(
        harmonic_freqs=harmonic_freqs,
        mean_z_table=mean_z_table,
        columns=columns,
    )


def select_rossion_harmonics_by_roi(
    summary: RossionHarmonicsSummary,
    *,
    rois: Iterable[str],
    z_threshold: float,
    stop_after_n: int = 2,
) -> tuple[dict[str, list[float]], dict[str, dict[str, object]]]:
    selected_map: dict[str, list[float]] = {}
    meta_by_roi: dict[str, dict[str, object]] = {}

    mean_lookup: dict[tuple[str, float], float] = {}
    if not summary.mean_z_table.empty:
        for _, row in summary.mean_z_table.iterrows():
            mean_lookup[(str(row["roi"]), float(row["harmonic_hz"]))] = float(row["mean_z"])

    for roi_name in rois:
        selected: list[float] = []
        nonsig_run = 0
        stop_reason = "end_of_domain"
        stop_fail_harmonics: list[float] = []
        scanned = 0

        for freq_val in summary.harmonic_freqs:
            scanned += 1
            mean_z = mean_lookup.get((str(roi_name), float(freq_val)), np.nan)
            is_sig = bool(np.isfinite(mean_z) and mean_z > z_threshold)
            if is_sig:
                selected.append(float(freq_val))
                nonsig_run = 0
                stop_fail_harmonics = []
            else:
                nonsig_run += 1
                stop_fail_harmonics.append(float(freq_val))
                if nonsig_run >= stop_after_n:
                    stop_reason = "two_consecutive_nonsignificant"
                    stop_fail_harmonics = stop_fail_harmonics[-stop_after_n:]
                    break

        selected_map[str(roi_name)] = selected
        meta_by_roi[str(roi_name)] = {
            "stop_reason": stop_reason,
            "fail_harmonics": stop_fail_harmonics,
            "n_scanned": scanned,
            "n_significant": len(selected),
            "stop_after_n": int(stop_after_n),
        }
    return selected_map, meta_by_roi


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
