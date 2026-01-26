"""Helpers for Rossion harmonic selection."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List

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

logger = logging.getLogger("Tools.Stats")
_DV_TRACE_ENV = "FPVS_STATS_DV_TRACE"


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
    trace_label: str | None = None,
) -> List[float]:
    trace_enabled = _dv_trace_enabled() and trace_label
    freq_candidates = get_included_freqs(base_freq, columns, log_func)
    if not freq_candidates:
        return []
    if trace_enabled:
        logger.info(
            "DV_TRACE domain_build label=%s stage=after_get_included_freqs count=%d first_10=%s "
            "base_multiples=removed_by_get_included_freqs",
            trace_label,
            len(freq_candidates),
            freq_candidates[:10],
        )
    oddball_list = filter_to_oddball_harmonics(
        freq_candidates,
        base_freq,
        every_n=SUMMED_BCA_ODDBALL_EVERY_N_DEFAULT,
        tol=1e-3,
    )
    if trace_enabled:
        logger.info(
            "DV_TRACE domain_build label=%s stage=after_filter_to_oddball count=%d first_10=%s",
            trace_label,
            len(oddball_list),
            [freq for freq, _k in oddball_list[:10]],
        )
    harmonic_freqs = [freq for freq, _k in oddball_list]
    if exclude_harmonic1:
        harmonic_freqs = [
            freq
            for freq, _k in oddball_list
            if int(_k) != 1
        ]
    if trace_enabled:
        logger.info(
            "DV_TRACE domain_build label=%s stage=after_exclude_harmonic1 count=%d first_10=%s",
            trace_label,
            len(harmonic_freqs),
            harmonic_freqs[:10],
        )
    return harmonic_freqs


def _dv_trace_enabled() -> bool:
    value = os.getenv(_DV_TRACE_ENV, "").strip().lower()
    return value not in ("", "0", "false", "no", "off")


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
    if _dv_trace_enabled():
        logger.info(
            "DV_TRACE domain_build label=rossion stage=raw_z_columns count=%d",
            int(len(columns)),
        )
    harmonic_freqs = _build_harmonic_domain(
        columns,
        base_freq,
        log_func,
        exclude_harmonic1=exclude_harmonic1,
        trace_label="rossion",
    )
    if not harmonic_freqs:
        raise RuntimeError(
            "Rossion harmonics selection produced an empty list. "
            "Verify Z-score sheets and base frequency."
        )

    mean_values: dict[tuple[str, float], list[float]] = {}
    trace_enabled = _dv_trace_enabled()
    trace_harmonics = set(harmonic_freqs[:5])
    trace_cell_meta: dict[str, dict[float, dict[str, object]]] = {}
    trace_overall: dict[str, dict[str, int]] = {}
    trace_electrode_counts: dict[str, int] = {}

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
                if trace_enabled:
                    trace_electrode_counts.setdefault(roi_name, len(roi_chans))
                df_roi = df_z.loc[roi_chans].dropna(how="all")
                if df_roi.empty:
                    log_func(f"No Z data for ROI {roi_name} in {file_path}.")
                    continue

                for freq_val in harmonic_freqs:
                    col_z = col_map.get(freq_val)
                    if not col_z:
                        continue
                    if trace_enabled:
                        roi_counts = trace_overall.setdefault(roi_name, {"total": 0, "nan": 0})
                        roi_counts["total"] += 1
                        if freq_val in trace_harmonics:
                            roi_meta = trace_cell_meta.setdefault(roi_name, {})
                            harm_meta = roi_meta.setdefault(
                                float(freq_val),
                                {"total": 0, "nan": 0, "values": []},
                            )
                            harm_meta["total"] += 1
                    series = pd.to_numeric(df_roi[col_z], errors="coerce").replace(
                        [np.inf, -np.inf], np.nan
                    )
                    mean_val = float(series.mean(skipna=True))
                    if trace_enabled:
                        if not np.isfinite(mean_val):
                            trace_overall[roi_name]["nan"] += 1
                            if freq_val in trace_harmonics:
                                trace_cell_meta[roi_name][float(freq_val)]["nan"] += 1
                        else:
                            if freq_val in trace_harmonics:
                                trace_cell_meta[roi_name][float(freq_val)]["values"].append(mean_val)
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

    if trace_enabled:
        for roi_name in rois.keys():
            total = trace_overall.get(roi_name, {}).get("total", 0)
            nan_total = trace_overall.get(roi_name, {}).get("nan", 0)
            fraction_nan = float(nan_total) / float(total) if total else 0.0
            logger.info(
                "DV_TRACE z_validity roi=%s electrode_count=%s fraction_nan_overall=%.4f",
                roi_name,
                trace_electrode_counts.get(roi_name, 0),
                fraction_nan,
            )
            for freq_val in harmonic_freqs[:5]:
                harm_meta = trace_cell_meta.get(roi_name, {}).get(float(freq_val), {})
                values = harm_meta.get("values", [])
                min_val = float(np.nanmin(values)) if values else np.nan
                mean_val = float(np.nanmean(values)) if values else np.nan
                max_val = float(np.nanmax(values)) if values else np.nan
                logger.info(
                    "DV_TRACE z_validity roi=%s harmonic=%g n_cells_total=%s n_cells_nan=%s "
                    "min=%s mean=%s max=%s",
                    roi_name,
                    float(freq_val),
                    harm_meta.get("total", 0),
                    harm_meta.get("nan", 0),
                    min_val,
                    mean_val,
                    max_val,
                )

        if mean_z_table.empty:
            logger.info("DV_TRACE z_group_summary note=empty_mean_z_table")
        else:
            mean_lookup: dict[tuple[str, float], float] = {}
            for _, row in mean_z_table.iterrows():
                mean_lookup[(str(row["roi"]), float(row["harmonic_hz"]))] = float(row["mean_z"])
            for roi_name in rois.keys():
                z_vals = []
                triplets = []
                sig_count = 0
                for freq_val in harmonic_freqs:
                    mean_z = mean_lookup.get((str(roi_name), float(freq_val)), np.nan)
                    if np.isfinite(mean_z):
                        z_vals.append(mean_z)
                    is_sig = bool(np.isfinite(mean_z) and mean_z > z_threshold)
                    if is_sig:
                        sig_count += 1
                    if len(triplets) < 10:
                        triplets.append((float(freq_val), float(mean_z), is_sig))
                z_min = float(np.nanmin(z_vals)) if z_vals else np.nan
                z_mean = float(np.nanmean(z_vals)) if z_vals else np.nan
                z_max = float(np.nanmax(z_vals)) if z_vals else np.nan
                logger.info(
                    "DV_TRACE z_group_summary roi=%s z_min=%s z_mean=%s z_max=%s "
                    "count_sig_total=%d first_10=%s",
                    roi_name,
                    z_min,
                    z_mean,
                    z_max,
                    sig_count,
                    triplets,
                )

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
    trace_enabled = _dv_trace_enabled()

    mean_lookup: dict[tuple[str, float], float] = {}
    if not summary.mean_z_table.empty:
        for _, row in summary.mean_z_table.iterrows():
            mean_lookup[(str(row["roi"]), float(row["harmonic_hz"]))] = float(row["mean_z"])

    for roi_name in rois:
        selected: list[float] = []
        nonsig_run = 0
        found_any_sig = False
        stop_reason = "end_of_domain"
        stop_fail_harmonics: list[float] = []
        scanned = 0
        stop_at_harmonic: float | None = None
        failure_run: list[tuple[float, float]] = []

        for freq_val in summary.harmonic_freqs:
            scanned += 1
            mean_z = mean_lookup.get((str(roi_name), float(freq_val)), np.nan)
            is_sig = bool(np.isfinite(mean_z) and mean_z > z_threshold)
            if is_sig:
                selected.append(float(freq_val))
                found_any_sig = True
                nonsig_run = 0
                stop_fail_harmonics = []
                failure_run = []
            else:
                if not found_any_sig:
                    continue
                nonsig_run += 1
                stop_fail_harmonics.append(float(freq_val))
                failure_run.append((float(freq_val), float(mean_z)))
                if len(failure_run) > stop_after_n:
                    failure_run = failure_run[-stop_after_n:]
                if nonsig_run >= stop_after_n:
                    stop_reason = "two_consecutive_nonsignificant"
                    stop_fail_harmonics = stop_fail_harmonics[-stop_after_n:]
                    stop_at_harmonic = float(freq_val)
                    break

        if not found_any_sig:
            stop_reason = "end_of_domain_no_sig"

        selected_map[str(roi_name)] = selected
        meta_by_roi[str(roi_name)] = {
            "stop_reason": stop_reason,
            "fail_harmonics": stop_fail_harmonics,
            "n_scanned": scanned,
            "n_significant": len(selected),
            "stop_after_n": int(stop_after_n),
        }
        if trace_enabled:
            logger.info(
                "DV_TRACE stop_rule roi=%s scanned_count=%d included_harmonics=%s included_count=%d "
                "stop_triggered=%s stop_at_harmonic=%s failure_run=%s",
                roi_name,
                scanned,
                selected,
                len(selected),
                stop_reason == "two_consecutive_nonsignificant",
                stop_at_harmonic,
                failure_run,
            )
    return selected_map, meta_by_roi
