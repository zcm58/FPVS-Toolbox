"""Group-level significant-harmonic Summed BCA DV policy helpers."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Callable, Dict, List, Optional, Sequence

import numpy as np
from openpyxl import load_workbook
import pandas as pd

from Tools.Stats.analysis.dv_policy_settings import (
    DVPolicySettings,
    GROUP_SIGNIFICANT_POLICY_ID,
    GROUP_SIGNIFICANT_POLICY_LABEL,
    GROUP_SIGNIFICANT_POLICY_NAME,
)
from Tools.Stats.analysis.noise_utils import compute_noise_stats_for_bin
from Tools.Stats.analysis.stats_analysis import (
    SUMMED_BCA_ODDBALL_EVERY_N_DEFAULT,
    _current_rois_map,
    _match_freq_column,
)
from Tools.Stats.io.excel_io import safe_read_excel

logger = logging.getLogger("Tools.Stats")

FULL_FFT_AMPLITUDE_SHEET_NAME = "FullFFT Amplitude (uV)"
GROUP_SIGNIFICANT_BASE_TOLERANCE_HZ = 0.01
GROUP_SIGNIFICANT_MATCHING_TOLERANCE_HZ = 0.01
GROUP_SIGNIFICANT_NOISE_WINDOW_BINS = 10


@dataclass(frozen=True)
class GroupSignificantHarmonicRow:
    harmonic_index: int
    target_frequency_hz: float
    matched_frequency_hz: float | None
    matched_column: str | None
    matched_bin_index: int | None
    z_score: float | None
    selected: bool
    excluded_base_rate: bool
    exclusion_reason: str
    warning: str


@dataclass(frozen=True)
class GroupSignificantHarmonicSelection:
    harmonic_domain_hz: list[float]
    selected_harmonics_hz: list[float]
    selected_columns: list[str]
    selected_bin_indices: list[int]
    z_by_harmonic: dict[float, float]
    excluded_base_harmonics_hz: list[float]
    oddball_frequency_hz: float
    base_frequency_hz: float
    z_threshold: float
    electrode_scope: str
    selection_scope: str
    selection_conditions: list[str]
    selection_subjects: list[str]
    selection_spectra_count: int
    selection_electrode_count: int
    frequency_resolution_hz: float | None
    base_overlap_tolerance_hz: float
    matching_tolerance_hz: float
    noise_window_bins: int
    rows: list[GroupSignificantHarmonicRow]

    def to_metadata(self) -> dict[str, object]:
        return {
            "harmonic_policy": GROUP_SIGNIFICANT_POLICY_ID,
            "harmonic_policy_label": GROUP_SIGNIFICANT_POLICY_LABEL,
            "dependent_variable": "summed_bca",
            "selection_source_sheet": FULL_FFT_AMPLITUDE_SHEET_NAME,
            "selection_amplitude_summary": "grand_average_raw_amplitude_spectrum",
            "selection_scope": self.selection_scope,
            "selection_conditions": list(self.selection_conditions),
            "selection_subjects": list(self.selection_subjects),
            "selection_spectra_count": int(self.selection_spectra_count),
            "selection_electrode_count": int(self.selection_electrode_count),
            "electrode_scope": self.electrode_scope,
            "z_threshold": float(self.z_threshold),
            "z_score_source": "computed_from_grand_averaged_amplitude_spectrum",
            "noise_window_bins": int(self.noise_window_bins),
            "base_frequency_hz": float(self.base_frequency_hz),
            "oddball_frequency_hz": float(self.oddball_frequency_hz),
            "base_overlap_exclusion_enabled": True,
            "base_overlap_tolerance_hz": float(self.base_overlap_tolerance_hz),
            "matching_tolerance_hz": float(self.matching_tolerance_hz),
            "frequency_resolution_hz": self.frequency_resolution_hz,
            "harmonic_domain_hz": list(self.harmonic_domain_hz),
            "common_harmonics_hz": list(self.selected_harmonics_hz),
            "selected_harmonics_hz": list(self.selected_harmonics_hz),
            "selected_columns": list(self.selected_columns),
            "selected_bin_indices": list(self.selected_bin_indices),
            "selection_z_by_harmonic": dict(self.z_by_harmonic),
            "excluded_base_harmonics_hz": list(self.excluded_base_harmonics_hz),
            "applied_uniformly_across_participants": True,
            "applied_uniformly_across_conditions": True,
            "applied_uniformly_across_rois": True,
            "snr_used_for_statistics": False,
            "bca_negative_values_retained": True,
            "bca_near_zero_values_retained": True,
            "selection_rows": [
                {
                    "harmonic_index": row.harmonic_index,
                    "target_frequency_hz": row.target_frequency_hz,
                    "matched_frequency_hz": row.matched_frequency_hz,
                    "matched_column": row.matched_column,
                    "matched_bin_index": row.matched_bin_index,
                    "z_score": row.z_score,
                    "selected": row.selected,
                    "excluded_base_rate": row.excluded_base_rate,
                    "exclusion_reason": row.exclusion_reason,
                    "warning": row.warning,
                }
                for row in self.rows
            ],
            "methods_summary": _methods_summary(self),
        }


@dataclass(frozen=True)
class RequiredFullFftColumns:
    usecols: list[str]
    frequency_columns: list[tuple[float, str, int]]
    candidate_indices: list[int]
    excluded_base_indices: list[int]


def build_group_significant_harmonic_selection(
    *,
    subjects: List[str],
    conditions: List[str],
    subject_data: Dict[str, Dict[str, str]],
    base_frequency_hz: float,
    rois: Dict[str, List[str]],
    log_func: Callable[[str], None],
    settings: DVPolicySettings,
    max_freq: float | None = None,
) -> GroupSignificantHarmonicSelection:
    started = perf_counter()
    base = float(base_frequency_hz)
    oddball = base / float(SUMMED_BCA_ODDBALL_EVERY_N_DEFAULT)
    required = _plan_required_full_fft_columns(
        subjects=subjects,
        conditions=conditions,
        subject_data=subject_data,
        base_frequency_hz=base,
        max_freq=max_freq,
        log_func=log_func,
    )
    log_func(
        "[PERF] Group harmonic selection column plan: "
        f"{len(required.usecols) - 1} FullFFT frequency columns needed "
        f"from {len(required.frequency_columns)} available columns."
    )
    logger.info(
        "stats_group_harmonics_column_plan",
        extra={
            "needed_frequency_columns": len(required.usecols) - 1,
            "available_frequency_columns": len(required.frequency_columns),
            "candidate_indices": len(required.candidate_indices),
        },
    )
    grand_average, columns, bin_indices, spectra_count, electrode_count = _build_grand_average_amplitude(
        subjects=subjects,
        conditions=conditions,
        subject_data=subject_data,
        rois=rois,
        electrode_scope=settings.group_significant_electrode_scope,
        log_func=log_func,
        usecols=required.usecols,
        frequency_columns=required.frequency_columns,
    )
    if grand_average.empty:
        raise RuntimeError("Group-level harmonic selection found no usable amplitude spectra.")

    frequency_resolution = _frequency_resolution(
        [freq for freq, _column, _idx in required.frequency_columns]
    )
    amplitude_by_bin = {
        int(bin_idx): float(value)
        for bin_idx, value in zip(bin_indices, grand_average.to_numpy(dtype=float))
        if np.isfinite(value)
    }
    column_by_bin = {
        int(bin_idx): str(column)
        for _freq, column, bin_idx in required.frequency_columns
        if int(bin_idx) in set(bin_indices)
    }
    freq_by_bin = {
        int(bin_idx): float(freq)
        for freq, _column, bin_idx in required.frequency_columns
        if int(bin_idx) in set(bin_indices)
    }
    rows: list[GroupSignificantHarmonicRow] = []
    harmonic_domain: list[float] = []
    selected_freqs: list[float] = []
    selected_columns: list[str] = []
    selected_indices: list[int] = []
    z_by_harmonic: dict[float, float] = {}
    excluded_base: list[float] = []
    seen_indices: set[int] = set()

    for matched_idx in required.candidate_indices:
        matched_freq = freq_by_bin.get(int(matched_idx))
        if matched_freq is None:
            continue
        harmonic_index = int(round(matched_freq / oddball))
        target_freq = float(harmonic_index * oddball)
        diff = abs(float(matched_freq) - target_freq)
        if diff > GROUP_SIGNIFICANT_MATCHING_TOLERANCE_HZ:
            rows.append(
                GroupSignificantHarmonicRow(
                    harmonic_index=harmonic_index,
                    target_frequency_hz=target_freq,
                    matched_frequency_hz=matched_freq,
                    matched_column=None,
                    matched_bin_index=matched_idx,
                    z_score=None,
                    selected=False,
                    excluded_base_rate=False,
                    exclusion_reason="no_full_fft_bin_within_tolerance",
                    warning=(
                        f"Nearest full-spectrum bin differs by {diff:g} Hz, "
                        f"above tolerance {GROUP_SIGNIFICANT_MATCHING_TOLERANCE_HZ:g} Hz."
                    ),
                )
            )
            continue
        if matched_idx in seen_indices:
            continue
        seen_indices.add(matched_idx)
        matched_column = column_by_bin.get(int(matched_idx), f"{matched_freq:.4f}_Hz")
        is_base_overlap = _is_base_overlap(
            matched_freq,
            base,
            GROUP_SIGNIFICANT_BASE_TOLERANCE_HZ,
        )
        if is_base_overlap:
            excluded_base.append(matched_freq)
            rows.append(
                GroupSignificantHarmonicRow(
                    harmonic_index=harmonic_index,
                    target_frequency_hz=target_freq,
                    matched_frequency_hz=matched_freq,
                    matched_column=matched_column,
                    matched_bin_index=matched_idx,
                    z_score=None,
                    selected=False,
                    excluded_base_rate=True,
                    exclusion_reason="base_rate_overlap",
                    warning="Base-rate overlap excluded from oddball summation.",
                )
            )
            continue

        noise_mean, noise_std = _compute_noise_stats_for_planned_bin(
            amplitude_by_bin,
            matched_idx,
            window_size=GROUP_SIGNIFICANT_NOISE_WINDOW_BINS,
            min_bins=4,
        )
        target_amp = amplitude_by_bin.get(int(matched_idx), np.nan)
        z_score = (target_amp - noise_mean) / noise_std if noise_std > 1e-12 else np.nan
        z_value = float(z_score) if np.isfinite(z_score) else np.nan
        harmonic_domain.append(matched_freq)
        z_by_harmonic[matched_freq] = z_value
        selected = bool(np.isfinite(z_value) and z_value > settings.group_significant_z_threshold)
        if selected:
            selected_freqs.append(matched_freq)
            selected_columns.append(matched_column)
            selected_indices.append(matched_idx)
        rows.append(
            GroupSignificantHarmonicRow(
                harmonic_index=harmonic_index,
                target_frequency_hz=target_freq,
                matched_frequency_hz=matched_freq,
                matched_column=matched_column,
                matched_bin_index=matched_idx,
                z_score=z_value if np.isfinite(z_value) else None,
                selected=selected,
                excluded_base_rate=False,
                exclusion_reason="" if selected else "z_below_threshold",
                warning="" if selected else "Z-score did not exceed threshold.",
            )
        )

    if not selected_freqs:
        raise RuntimeError(
            "Group-level significant harmonic selection found no oddball harmonics "
            f"above z>{settings.group_significant_z_threshold:g}. "
            "Use the fixed/predefined policy or inspect the regenerated full-spectrum workbooks."
        )
    elapsed = perf_counter() - started
    log_func(
        "[PERF] Group harmonic selection finished: "
        f"{spectra_count} spectra, {electrode_count} electrodes/spectrum max, "
        f"{len(selected_freqs)} selected harmonics in {elapsed:.2f}s."
    )
    logger.info(
        "stats_group_harmonics_selection_done",
        extra={
            "elapsed_s": elapsed,
            "spectra_count": spectra_count,
            "selected_harmonics": selected_freqs,
        },
    )

    return GroupSignificantHarmonicSelection(
        harmonic_domain_hz=harmonic_domain,
        selected_harmonics_hz=selected_freqs,
        selected_columns=selected_columns,
        selected_bin_indices=selected_indices,
        z_by_harmonic=z_by_harmonic,
        excluded_base_harmonics_hz=excluded_base,
        oddball_frequency_hz=float(oddball),
        base_frequency_hz=base,
        z_threshold=float(settings.group_significant_z_threshold),
        electrode_scope=str(settings.group_significant_electrode_scope),
        selection_scope="group_level_all_scalp_electrodes_all_selected_conditions",
        selection_conditions=list(conditions),
        selection_subjects=list(subjects),
        selection_spectra_count=int(spectra_count),
        selection_electrode_count=int(electrode_count),
        frequency_resolution_hz=frequency_resolution,
        base_overlap_tolerance_hz=GROUP_SIGNIFICANT_BASE_TOLERANCE_HZ,
        matching_tolerance_hz=GROUP_SIGNIFICANT_MATCHING_TOLERANCE_HZ,
        noise_window_bins=GROUP_SIGNIFICANT_NOISE_WINDOW_BINS,
        rows=rows,
    )


def _prepare_group_significant_bca_data(
    *,
    subjects: List[str],
    conditions: List[str],
    subject_data: Dict[str, Dict[str, str]],
    base_freq: float,
    log_func: Callable[[str], None],
    rois: Optional[Dict[str, List[str]]] = None,
    provenance_map: Optional[dict[tuple[str, str, str], dict[str, object]]] = None,
    settings: DVPolicySettings,
    dv_metadata: Optional[dict[str, object]] = None,
    max_freq: float | None = None,
) -> Optional[Dict[str, Dict[str, Dict[str, float]]]]:
    if not subjects or not subject_data:
        log_func("No subject data. Scan folder first.")
        return None

    rois_map = rois if rois is not None else _current_rois_map()
    if not rois_map:
        log_func("No ROIs defined or available.")
        return None

    started = perf_counter()
    selection = build_group_significant_harmonic_selection(
        subjects=subjects,
        conditions=conditions,
        subject_data=subject_data,
        base_frequency_hz=base_freq,
        rois=rois_map,
        log_func=log_func,
        settings=settings,
        max_freq=max_freq,
    )
    log_func(
        "Group-level significant harmonics selected: "
        + ", ".join(f"{freq:g} Hz" for freq in selection.selected_harmonics_hz)
    )
    log_func(
        "[PERF] Group harmonic selection phase complete in "
        f"{perf_counter() - started:.2f}s."
    )

    bca_started = perf_counter()
    all_subject_data: Dict[str, Dict[str, Dict[str, float]]] = {}
    for pid in subjects:
        all_subject_data[pid] = {}
        for cond_name in conditions:
            file_path = subject_data.get(pid, {}).get(cond_name)
            all_subject_data[pid].setdefault(cond_name, {})
            roi_values, roi_provenance = _aggregate_bca_for_all_rois(
                file_path=file_path,
                rois=rois_map,
                log_func=log_func,
                harmonic_freqs=list(selection.selected_harmonics_hz),
                provenance_enabled=provenance_map is not None,
            )
            for roi_name in rois_map.keys():
                all_subject_data[pid][cond_name][roi_name] = roi_values.get(roi_name, np.nan)
                if provenance_map is not None:
                    provenance = roi_provenance.get(
                        roi_name,
                        {
                            "source_file": file_path,
                            "sheet": "BCA (uV)",
                            "row_label": None,
                            "col_label": list(selection.selected_columns),
                            "raw_cell": None,
                            "harmonic_policy": GROUP_SIGNIFICANT_POLICY_ID,
                        },
                    )
                    provenance["harmonic_policy"] = GROUP_SIGNIFICANT_POLICY_ID
                    provenance_map[(pid, cond_name, roi_name)] = provenance
    log_func(
        "[PERF] Group policy BCA aggregation finished: "
        f"{len(subjects) * len(conditions)} workbook reads for "
        f"{len(rois_map)} ROIs in {perf_counter() - bca_started:.2f}s."
    )

    if dv_metadata is not None:
        dv_metadata.update(
            settings.to_metadata(base_freq=base_freq, selected_conditions=conditions)
        )
        dv_metadata["policy_name"] = GROUP_SIGNIFICANT_POLICY_NAME
        dv_metadata["group_significant_harmonics"] = selection.to_metadata()

    total = 0
    finite = 0
    for _pid, conds in all_subject_data.items():
        for _cond, rois_dict in conds.items():
            for _roi, val in rois_dict.items():
                total += 1
                if val is not None and np.isfinite(val):
                    finite += 1
    log_func(f"[DEBUG] Summed BCA finite cells: {finite}/{total}")
    log_func(f"Summed BCA data prep complete in {perf_counter() - started:.2f}s.")
    return all_subject_data


def _build_grand_average_amplitude(
    *,
    subjects: List[str],
    conditions: List[str],
    subject_data: Dict[str, Dict[str, str]],
    rois: Dict[str, List[str]],
    electrode_scope: str,
    log_func: Callable[[str], None],
    usecols: list[str],
    frequency_columns: list[tuple[float, str, int]],
) -> tuple[pd.Series, list[str], list[int], int, int]:
    started = perf_counter()
    spectra: list[pd.Series] = []
    columns: list[str] = []
    bin_indices: list[int] = []
    electrode_count = 0
    read_elapsed = 0.0
    for pid in subjects:
        for cond_name in conditions:
            file_path = subject_data.get(pid, {}).get(cond_name)
            if not file_path or not Path(file_path).exists():
                log_func(f"Missing file for {pid} {cond_name}: {file_path}")
                continue
            read_started = perf_counter()
            series, file_columns, n_electrodes = _load_mean_amplitude_series(
                file_path,
                rois=rois,
                electrode_scope=electrode_scope,
                usecols=usecols,
            )
            read_elapsed += perf_counter() - read_started
            if series.empty:
                log_func(f"No usable full-spectrum amplitude data for {pid} {cond_name}.")
                continue
            spectra.append(series)
            if not columns:
                columns = file_columns
                bin_lookup = {column: int(idx) for _freq, column, idx in frequency_columns}
                bin_indices = [bin_lookup[column] for column in file_columns if column in bin_lookup]
            electrode_count = max(electrode_count, int(n_electrodes))

    if not spectra:
        raise RuntimeError(
            "Group-level significant harmonic selection requires workbooks with a "
            f"'{FULL_FFT_AMPLITUDE_SHEET_NAME}' sheet for included participants and conditions."
        )
    frame = pd.concat(spectra, axis=1)
    grand_average = frame.mean(axis=1, skipna=True).sort_index()
    columns = [f"{float(freq):.4f}_Hz" for freq in grand_average.index]
    bin_lookup = {column: idx for _freq, column, idx in frequency_columns}
    bin_indices = [int(bin_lookup[column]) for column in columns if column in bin_lookup]
    elapsed = perf_counter() - started
    log_func(
        "[PERF] FullFFT grand-average read: "
        f"{len(spectra)} workbooks x {max(len(usecols) - 1, 0)} frequency columns "
        f"in {elapsed:.2f}s (read phase {read_elapsed:.2f}s)."
    )
    logger.info(
        "stats_group_harmonics_fullfft_read_done",
        extra={
            "elapsed_s": elapsed,
            "read_elapsed_s": read_elapsed,
            "spectra_count": len(spectra),
            "frequency_columns": max(len(usecols) - 1, 0),
        },
    )
    return grand_average, columns, bin_indices, len(spectra), electrode_count


def _plan_required_full_fft_columns(
    *,
    subjects: List[str],
    conditions: List[str],
    subject_data: Dict[str, Dict[str, str]],
    base_frequency_hz: float,
    max_freq: float | None,
    log_func: Callable[[str], None],
) -> RequiredFullFftColumns:
    started = perf_counter()
    header_columns = _find_first_full_fft_columns(subjects, conditions, subject_data)
    frequency_columns = _parse_frequency_columns(header_columns)
    if not frequency_columns:
        raise RuntimeError(
            "Group-level significant harmonic selection found no frequency columns "
            f"in '{FULL_FFT_AMPLITUDE_SHEET_NAME}'."
        )

    freq_axis = np.asarray([freq for freq, _column, _idx in frequency_columns], dtype=float)
    base = float(base_frequency_hz)
    oddball = base / float(SUMMED_BCA_ODDBALL_EVERY_N_DEFAULT)
    max_limit = float(max_freq) if max_freq is not None else float(np.nanmax(freq_axis))
    highest_k = int(np.floor(max_limit / oddball))
    candidate_indices: list[int] = []
    excluded_base_indices: list[int] = []
    required_indices: set[int] = set()
    all_indices = {int(idx) for _freq, _column, idx in frequency_columns}

    for harmonic_index in range(1, highest_k + 1):
        target_freq = float(harmonic_index * oddball)
        nearest_pos = int(np.argmin(np.abs(freq_axis - target_freq)))
        matched_freq, _column, matched_idx = frequency_columns[nearest_pos]
        diff = abs(float(matched_freq) - target_freq)
        if diff > GROUP_SIGNIFICANT_MATCHING_TOLERANCE_HZ:
            continue
        candidate_indices.append(int(matched_idx))
        required_indices.add(int(matched_idx))
        if _is_base_overlap(matched_freq, base, GROUP_SIGNIFICANT_BASE_TOLERANCE_HZ):
            excluded_base_indices.append(int(matched_idx))
            continue
        for noise_idx in _noise_indices_for_bin(
            int(matched_idx),
            available_indices=all_indices,
            window_size=GROUP_SIGNIFICANT_NOISE_WINDOW_BINS,
        ):
            required_indices.add(int(noise_idx))

    if not candidate_indices:
        raise RuntimeError(
            "Group-level significant harmonic selection produced no candidate oddball "
            "harmonic bins. Check base frequency and FullFFT frequency columns."
        )

    column_by_idx = {int(idx): str(column) for _freq, column, idx in frequency_columns}
    ordered_columns = [
        column_by_idx[idx]
        for idx in sorted(required_indices)
        if idx in column_by_idx
    ]
    usecols = ["Electrode", *ordered_columns]
    log_func(
        "[PERF] FullFFT required-column plan built in "
        f"{perf_counter() - started:.2f}s: "
        f"{len(candidate_indices)} candidate oddball bins, "
        f"{len(ordered_columns)} frequency columns to read."
    )
    return RequiredFullFftColumns(
        usecols=usecols,
        frequency_columns=frequency_columns,
        candidate_indices=candidate_indices,
        excluded_base_indices=excluded_base_indices,
    )


def _find_first_full_fft_columns(
    subjects: List[str],
    conditions: List[str],
    subject_data: Dict[str, Dict[str, str]],
) -> list[object]:
    for pid in subjects:
        for cond_name in conditions:
            file_path = subject_data.get(pid, {}).get(cond_name)
            if not file_path or not Path(file_path).exists():
                continue
            try:
                workbook = load_workbook(
                    file_path,
                    read_only=True,
                    data_only=True,
                )
                try:
                    worksheet = workbook[FULL_FFT_AMPLITUDE_SHEET_NAME]
                    return [cell.value for cell in next(worksheet.iter_rows(max_row=1))]
                finally:
                    workbook.close()
            except KeyError as exc:
                raise RuntimeError(
                    "Group-level significant harmonic selection requires regenerated "
                    f"workbooks with a '{FULL_FFT_AMPLITUDE_SHEET_NAME}' sheet: {file_path}"
                ) from exc
    return []


def _load_mean_amplitude_series(
    file_path: str,
    *,
    rois: Dict[str, List[str]],
    electrode_scope: str,
    usecols: list[str],
) -> tuple[pd.Series, list[str], int]:
    try:
        df_fft = safe_read_excel(
            file_path,
            sheet_name=FULL_FFT_AMPLITUDE_SHEET_NAME,
            index_col="Electrode",
            usecols=usecols,
            use_cache=False,
        )
    except ValueError as exc:
        raise RuntimeError(
            "Group-level significant harmonic selection requires regenerated "
            f"workbooks with a '{FULL_FFT_AMPLITUDE_SHEET_NAME}' sheet: {file_path}"
        ) from exc

    df_fft.index = df_fft.index.astype(str).str.upper().str.strip()
    electrode_names = _electrodes_for_scope(df_fft, rois=rois, electrode_scope=electrode_scope)
    if not electrode_names:
        return pd.Series(dtype=float), [], 0

    freq_columns = _parse_frequency_columns(df_fft.columns)
    if not freq_columns:
        return pd.Series(dtype=float), [], 0

    ordered_columns = [column for _freq, column, _idx in freq_columns]
    block = (
        df_fft.loc[electrode_names, ordered_columns]
        .apply(pd.to_numeric, errors="coerce")
        .replace([np.inf, -np.inf], np.nan)
    )
    series = block.mean(axis=0, skipna=True)
    series.index = [freq for freq, _column, _idx in freq_columns]
    return pd.to_numeric(series, errors="coerce"), ordered_columns, len(electrode_names)


def _aggregate_bca_for_all_rois(
    *,
    file_path: str | None,
    rois: Dict[str, List[str]],
    log_func: Callable[[str], None],
    harmonic_freqs: List[float],
    provenance_enabled: bool,
) -> tuple[dict[str, float], dict[str, dict[str, object]]]:
    values = {roi_name: np.nan for roi_name in rois.keys()}
    provenance: dict[str, dict[str, object]] = {}
    if not file_path or not Path(file_path).exists():
        log_func(f"Missing file: {file_path}")
        return values, provenance

    started = perf_counter()
    try:
        df_bca = safe_read_excel(
            file_path,
            sheet_name="BCA (uV)",
            index_col="Electrode",
            use_cache=False,
        )
    except Exception as exc:  # noqa: BLE001
        log_func(f"Error reading BCA sheet for {file_path}: {exc}")
        return values, provenance

    read_elapsed = perf_counter() - started
    df_bca.index = df_bca.index.astype(str).str.upper().str.strip()
    cols_to_sum: List[str] = []
    for freq_val in harmonic_freqs:
        col_bca = _match_freq_column(df_bca.columns, freq_val)
        if col_bca:
            cols_to_sum.append(col_bca)
    if not cols_to_sum:
        log_func(f"No group-selected harmonics found in BCA sheet for {file_path}.")
        return values, provenance

    numeric_bca = (
        df_bca[cols_to_sum]
        .apply(pd.to_numeric, errors="coerce")
        .replace([np.inf, -np.inf], np.nan)
    )
    for roi_name, roi_channels in rois.items():
        roi_chans = [
            str(ch).strip().upper()
            for ch in (roi_channels or [])
            if str(ch).strip().upper() in numeric_bca.index
        ]
        if not roi_chans:
            log_func(f"No overlapping BCA data for ROI {roi_name} in {file_path}.")
            if provenance_enabled:
                provenance[roi_name] = _empty_provenance(file_path, row_label=[], col_label=cols_to_sum)
            continue
        df_roi = numeric_bca.loc[roi_chans].dropna(how="all")
        if df_roi.empty:
            log_func(f"No data for ROI {roi_name} in {file_path}.")
            if provenance_enabled:
                provenance[roi_name] = _empty_provenance(file_path, row_label=roi_chans, col_label=cols_to_sum)
            continue
        bca_vals = df_roi.sum(axis=1, min_count=1)
        bca_vals = pd.to_numeric(bca_vals, errors="coerce").replace([np.inf, -np.inf], np.nan)
        if bca_vals.notna().any():
            out = float(bca_vals.mean(skipna=True))
            values[roi_name] = out if np.isfinite(out) else np.nan
        if provenance_enabled:
            provenance[roi_name] = {
                "source_file": file_path,
                "sheet": "BCA (uV)",
                "row_label": roi_chans,
                "col_label": cols_to_sum,
                "raw_cell": df_roi.to_dict(orient="index"),
                "harmonic_policy": GROUP_SIGNIFICANT_POLICY_ID,
            }
    logger.info(
        "stats_group_harmonics_bca_workbook_done",
        extra={
            "elapsed_s": perf_counter() - started,
            "read_elapsed_s": read_elapsed,
            "path": str(file_path),
            "roi_count": len(rois),
            "harmonic_count": len(cols_to_sum),
        },
    )
    return values, provenance


def _empty_provenance(
    file_path: str | None,
    *,
    row_label: list[str],
    col_label: list[str],
) -> dict[str, object]:
    return {
        "source_file": file_path,
        "sheet": "BCA (uV)",
        "row_label": row_label,
        "col_label": col_label,
        "raw_cell": None,
        "harmonic_policy": GROUP_SIGNIFICANT_POLICY_ID,
    }


def _noise_indices_for_bin(
    target_idx: int,
    *,
    available_indices: set[int],
    window_size: int,
) -> list[int]:
    low = max(0, int(target_idx) - int(window_size))
    high = int(target_idx) + int(window_size)
    excluded = {int(target_idx) - 1, int(target_idx), int(target_idx) + 1}
    return [
        idx
        for idx in range(low, high + 1)
        if idx in available_indices and idx not in excluded
    ]


def _compute_noise_stats_for_planned_bin(
    amplitude_by_bin: dict[int, float],
    target_idx: int,
    *,
    window_size: int,
    min_bins: int,
) -> tuple[float, float]:
    indices = _noise_indices_for_bin(
        int(target_idx),
        available_indices=set(amplitude_by_bin.keys()),
        window_size=window_size,
    )
    if len(indices) < min_bins:
        return 0.0, 0.0
    noise_vals = np.asarray(
        [amplitude_by_bin[idx] for idx in indices if np.isfinite(amplitude_by_bin.get(idx, np.nan))],
        dtype=float,
    )
    if noise_vals.size < min_bins:
        return 0.0, 0.0
    if noise_vals.size > 2:
        max_idx = int(noise_vals.argmax())
        min_idx = int(noise_vals.argmin())
        mask = np.ones(noise_vals.shape[0], dtype=bool)
        mask[max_idx] = False
        mask[min_idx] = False
        noise_vals = noise_vals[mask]
    if noise_vals.size == 0:
        return 0.0, 0.0
    return float(noise_vals.mean()), float(noise_vals.std(ddof=0))


def _electrodes_for_scope(
    df_fft: pd.DataFrame,
    *,
    rois: Dict[str, List[str]],
    electrode_scope: str,
) -> list[str]:
    if electrode_scope == "union_roi_electrodes":
        wanted = {
            str(ch).strip().upper()
            for channels in (rois or {}).values()
            for ch in (channels or [])
            if str(ch).strip()
        }
        return [idx for idx in df_fft.index.astype(str) if idx in wanted]
    _ = rois
    return list(df_fft.index.astype(str))


def _parse_frequency_columns(columns: Sequence[object]) -> list[tuple[float, str, int]]:
    out: list[tuple[float, str, int]] = []
    freq_idx = 0
    for col_name in columns:
        if not isinstance(col_name, str) or not col_name.endswith("_Hz"):
            continue
        try:
            out.append((float(col_name[:-3]), col_name, freq_idx))
            freq_idx += 1
        except ValueError:
            continue
    return sorted(out, key=lambda item: item[0])


def _frequency_resolution(freqs: Sequence[float]) -> float | None:
    unique = sorted(set(float(freq) for freq in freqs))
    if len(unique) < 2:
        return None
    diffs = np.diff(np.asarray(unique, dtype=float))
    diffs = diffs[np.isfinite(diffs) & (diffs > 0)]
    if diffs.size == 0:
        return None
    return float(np.median(diffs))


def _is_base_overlap(freq: float, base: float, tolerance_hz: float) -> bool:
    if base <= 0:
        return False
    multiple = round(float(freq) / float(base))
    if multiple <= 0:
        return False
    return abs(float(freq) - multiple * float(base)) < float(tolerance_hz)


def _methods_summary(selection: GroupSignificantHarmonicSelection) -> str:
    harmonics = ", ".join(f"{freq:g}" for freq in selection.selected_harmonics_hz)
    excluded = ", ".join(f"{freq:g}" for freq in selection.excluded_base_harmonics_hz)
    return (
        "Baseline-corrected amplitudes were summed across a common group-level "
        "set of significant oddball harmonics selected from the grand-averaged "
        f"raw amplitude spectrum ({harmonics} Hz). Candidate oddball harmonics "
        f"were tested against neighboring-bin noise with z>{selection.z_threshold:g}; "
        "base-rate overlaps were excluded"
        + (f" ({excluded} Hz)." if excluded else ".")
        + " The same selected harmonic list was applied to every participant, "
        "condition, and ROI. SNR values were not used as the primary dependent variable."
    )
