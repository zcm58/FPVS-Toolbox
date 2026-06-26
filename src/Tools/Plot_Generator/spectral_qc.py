"""Post-processing spectral QC helpers for SNR plot generation."""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import time
from typing import List, Mapping, Sequence
from xml.etree import ElementTree
import zipfile

import numpy as np
import pandas as pd

from Tools.Plot_Generator.full_snr_reader import (
    _OFFICE_REL_NS,
    _RELATIONSHIP_TAG,
    _ROW_TAG,
    _SHEET_TAG,
    _add_timing_detail,
    _load_shared_strings,
    _row_values_by_column,
    _selected_row_values,
    _xlsx_member_path,
)

FULLFFT_SHEET_NAME = "FullFFT Amplitude (uV)"

_EPSILON = 1e-12


@dataclass(frozen=True)
class SpectralQcThresholds:
    """Conservative defaults for report-only spectral artifact flagging."""

    min_subjects: int = 3
    snr_threshold: float = 3.0
    min_fft_uv: float = 2.0
    fold_threshold: float = 8.0
    robust_z_threshold: float = 6.0
    expected_frequency_tolerance_hz: float = 0.015


@dataclass(frozen=True)
class SpectralQcRecord:
    """One electrode-frequency outlier flagged by spectral QC."""

    condition: str
    pid: str
    electrode: str
    frequency_hz: float
    reason: str
    snr_value: float
    fft_amplitude_uv: float
    group_median_fft_uv: float
    robust_z: float
    fold_over_median: float
    source_workbook: str


@dataclass(frozen=True)
class SpectralQcResult:
    """Summary returned after report-only spectral QC flagging."""

    records: tuple[SpectralQcRecord, ...]
    report_path: Path | None
    checked_cells: int
    flagged_cells: int


def summarize_spectral_qc_records(
    records: Sequence[SpectralQcRecord],
) -> list[dict[str, object]]:
    """Summarize flagged electrode-frequency rows for GUI reporting."""

    grouped: dict[tuple[str, str, str], dict[str, object]] = {}
    for record in records:
        key = (record.condition, record.pid, record.electrode)
        entry = grouped.setdefault(
            key,
            {
                "condition": record.condition,
                "pid": record.pid,
                "electrode": record.electrode,
                "flag_count": 0,
                "min_frequency_hz": record.frequency_hz,
                "max_frequency_hz": record.frequency_hz,
                "max_fft_amplitude_uv": record.fft_amplitude_uv,
                "max_snr": record.snr_value,
                "source_workbook": record.source_workbook,
            },
        )
        entry["flag_count"] = int(entry["flag_count"]) + 1
        entry["min_frequency_hz"] = min(
            float(entry["min_frequency_hz"]),
            record.frequency_hz,
        )
        entry["max_frequency_hz"] = max(
            float(entry["max_frequency_hz"]),
            record.frequency_hz,
        )
        entry["max_fft_amplitude_uv"] = max(
            float(entry["max_fft_amplitude_uv"]),
            record.fft_amplitude_uv,
        )
        entry["max_snr"] = max(float(entry["max_snr"]), record.snr_value)

    return sorted(
        grouped.values(),
        key=lambda item: (
            -int(item["flag_count"]),
            str(item["condition"]),
            str(item["pid"]),
            str(item["electrode"]),
        ),
    )


def _worksheet_member(archive: zipfile.ZipFile, sheet_name: str) -> str:
    workbook_root = ElementTree.fromstring(archive.read("xl/workbook.xml"))
    rels_root = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    rel_targets = {
        rel.attrib.get("Id"): rel.attrib.get("Target")
        for rel in rels_root.iter(_RELATIONSHIP_TAG)
    }
    for sheet in workbook_root.iter(_SHEET_TAG):
        if sheet.attrib.get("name") != sheet_name:
            continue
        rel_id = sheet.attrib.get(f"{{{_OFFICE_REL_NS}}}id")
        target = rel_targets.get(rel_id)
        if not target:
            break
        return _xlsx_member_path("xl/workbook.xml", target)
    raise ValueError(f"Worksheet named '{sheet_name}' not found")


def _frequency_columns(
    header: Sequence[object | None],
    *,
    x_min: float,
    x_max: float,
) -> tuple[int, list[tuple[float, str, int]]]:
    electrode_index = -1
    freq_pairs: list[tuple[float, str, int]] = []
    for index, column in enumerate(header):
        if column == "Electrode":
            electrode_index = index
        if not isinstance(column, str) or not column.endswith("_Hz"):
            continue
        try:
            freq = float(column.split("_")[0])
        except ValueError:
            continue
        freq_pairs.append((freq, column, index))
    if electrode_index < 0:
        raise KeyError("Electrode")

    tolerance = 1e-3
    selected = [
        item
        for item in sorted(freq_pairs, key=lambda value: value[0])
        if (x_min - tolerance) <= item[0] <= (x_max + tolerance)
    ]
    return electrode_index, selected


def read_full_fft_sheet_read_only(
    excel_path: Path,
    *,
    x_min: float,
    x_max: float,
    timing_details: dict[str, float] | None = None,
    included_electrodes_upper: set[str] | None = None,
) -> tuple[pd.DataFrame, List[float], List[str]]:
    """Read selected FullFFT columns without using Pandas' Excel engine."""

    started = time.perf_counter()
    with zipfile.ZipFile(excel_path) as archive:
        sheet_member = _worksheet_member(archive, FULLFFT_SHEET_NAME)
        _add_timing_detail(timing_details, "fullfft_workbook_open", started)

        started = time.perf_counter()
        shared_strings = _load_shared_strings(archive)
        _add_timing_detail(timing_details, "fullfft_shared_strings", started)

        started = time.perf_counter()
        with archive.open(sheet_member) as worksheet_stream:
            rows: list[list[object | None]] = []
            columns = ["Electrode"]
            ordered_freqs: list[float] = []
            ordered_cols: list[str] = []
            required_positions: dict[int, int] = {}
            electrode_index = -1
            max_required_index = -1
            header_seen = False

            for _, row in ElementTree.iterparse(worksheet_stream, events=("end",)):
                if row.tag != _ROW_TAG:
                    continue
                if not header_seen:
                    header_seen = True
                    header = _row_values_by_column(row, shared_strings)
                    if not header:
                        _add_timing_detail(timing_details, "fullfft_header_scan", started)
                        return pd.DataFrame(), [], []

                    electrode_index, selected = _frequency_columns(
                        header,
                        x_min=x_min,
                        x_max=x_max,
                    )
                    ordered_freqs = [freq for freq, _, _ in selected]
                    ordered_cols = [column for _, column, _ in selected]
                    if not selected:
                        _add_timing_detail(timing_details, "fullfft_header_scan", started)
                        return pd.DataFrame(columns=["Electrode"]), [], []

                    columns = ["Electrode"] + ordered_cols
                    required_indexes = [electrode_index] + [
                        index for _, _, index in selected
                    ]
                    required_positions = {
                        column_index: position
                        for position, column_index in enumerate(required_indexes)
                    }
                    max_required_index = max(required_indexes)
                    _add_timing_detail(timing_details, "fullfft_header_scan", started)
                    started = time.perf_counter()
                    row.clear()
                    continue

                values = _selected_row_values(
                    row,
                    shared_strings,
                    required_positions=required_positions,
                    electrode_index=electrode_index,
                    max_required_index=max_required_index,
                )
                electrode = values[0] if values else None
                if (
                    included_electrodes_upper is not None
                    and str(electrode).upper() not in included_electrodes_upper
                ):
                    row.clear()
                    continue
                rows.append(values)
                row.clear()

            if not header_seen:
                _add_timing_detail(timing_details, "fullfft_header_scan", started)
                return pd.DataFrame(), [], []

            _add_timing_detail(timing_details, "fullfft_row_stream", started)
            started = time.perf_counter()
            df = pd.DataFrame(rows, columns=columns)
            _add_timing_detail(timing_details, "fullfft_dataframe_build", started)
            return df, ordered_freqs, ordered_cols


def electrode_snr_data(
    df: pd.DataFrame,
    snr_cols: Sequence[str],
) -> dict[str, list[float]]:
    """Return SNR rows keyed by uppercase electrode name."""

    if df.empty or not snr_cols:
        return {}
    data: dict[str, list[float]] = {}
    for _, row in df.iterrows():
        electrode = str(row.get("Electrode") or "").strip().upper()
        if not electrode:
            continue
        data[electrode] = [
            float(value) if pd.notna(value) else math.nan
            for value in row[list(snr_cols)].tolist()
        ]
    return data


def interpolate_fullfft_electrode_data(
    df: pd.DataFrame,
    fft_freqs: Sequence[float],
    fft_cols: Sequence[str],
    target_freqs: Sequence[float],
    *,
    electrodes_upper: set[str] | None = None,
) -> dict[str, list[float]]:
    """Return electrode-level FullFFT amplitudes interpolated onto SNR grid."""

    if df.empty or not fft_freqs or not fft_cols or not target_freqs:
        return {}

    source_freqs = np.asarray(list(fft_freqs), dtype=float)
    target = np.asarray(list(target_freqs), dtype=float)
    data: dict[str, list[float]] = {}
    for _, row in df.iterrows():
        electrode = str(row.get("Electrode") or "").strip().upper()
        if not electrode:
            continue
        if electrodes_upper is not None and electrode not in electrodes_upper:
            continue
        values = row[list(fft_cols)].to_numpy(dtype=float, copy=True)
        data[electrode] = np.interp(target, source_freqs, values).tolist()
    return data


def is_expected_frequency(
    freq: float,
    *,
    oddball_freq: float,
    base_freq: float,
    tolerance_hz: float,
) -> bool:
    """Return True for expected FPVS oddball/base harmonics."""

    if not math.isfinite(freq) or freq <= 0:
        return False
    for fundamental in (oddball_freq, base_freq):
        if not math.isfinite(fundamental) or fundamental <= 0:
            continue
        nearest = round(freq / fundamental)
        if nearest >= 1 and abs(freq - (nearest * fundamental)) <= tolerance_hz:
            return True
    return False


def _robust_stats(values: np.ndarray) -> tuple[float, float]:
    median = float(np.nanmedian(values))
    mad = float(np.nanmedian(np.abs(values - median)))
    return median, 1.4826 * mad


def _should_flag(
    *,
    snr_value: float,
    fft_value: float,
    median: float,
    robust_scale: float,
    thresholds: SpectralQcThresholds,
) -> tuple[bool, float, float]:
    fold = fft_value / max(abs(median), _EPSILON)
    if robust_scale > _EPSILON:
        robust_z = (fft_value - median) / robust_scale
    else:
        robust_z = math.inf if fft_value > median else 0.0
    should_flag = (
        math.isfinite(snr_value)
        and snr_value >= thresholds.snr_threshold
        and math.isfinite(fft_value)
        and fft_value >= thresholds.min_fft_uv
        and fold >= thresholds.fold_threshold
        and robust_z >= thresholds.robust_z_threshold
    )
    return should_flag, float(robust_z), float(fold)


def flag_spectral_qc_electrode_outliers(
    *,
    condition: str,
    freqs: Sequence[float],
    subject_snr_data: Mapping[str, Mapping[str, Sequence[float]]],
    subject_fft_data: Mapping[str, Mapping[str, Sequence[float]]],
    source_workbooks: Mapping[str, str],
    oddball_freq: float,
    base_freq: float,
    thresholds: SpectralQcThresholds,
) -> SpectralQcResult:
    """Flag suspicious off-harmonic electrode peaks without mutating plot data."""

    records: list[SpectralQcRecord] = []
    checked_cells = 0
    electrode_names = sorted(
        {
            electrode
            for electrode_values in subject_fft_data.values()
            for electrode in electrode_values
        }
    )

    for electrode in electrode_names:
        pids = [
            pid
            for pid, electrode_values in subject_snr_data.items()
            if electrode in electrode_values and electrode in subject_fft_data.get(pid, {})
        ]
        if len(pids) < thresholds.min_subjects:
            continue

        for freq_index, freq in enumerate(freqs):
            if is_expected_frequency(
                float(freq),
                oddball_freq=oddball_freq,
                base_freq=base_freq,
                tolerance_hz=thresholds.expected_frequency_tolerance_hz,
            ):
                continue

            fft_pairs: list[tuple[str, float]] = []
            for pid in pids:
                fft_values = subject_fft_data.get(pid, {}).get(electrode, [])
                if freq_index >= len(fft_values):
                    continue
                value = float(fft_values[freq_index])
                if math.isfinite(value):
                    fft_pairs.append((pid, value))
            if len(fft_pairs) < thresholds.min_subjects:
                continue

            fft_array = np.asarray([value for _, value in fft_pairs], dtype=float)
            median, robust_scale = _robust_stats(fft_array)

            for pid, fft_value in fft_pairs:
                electrode_snr = subject_snr_data.get(pid, {}).get(electrode, [])
                if freq_index >= len(electrode_snr):
                    continue
                snr_value = float(electrode_snr[freq_index])
                if not math.isfinite(snr_value):
                    continue
                checked_cells += 1
                should_flag, robust_z, fold = _should_flag(
                    snr_value=snr_value,
                    fft_value=fft_value,
                    median=median,
                    robust_scale=robust_scale,
                    thresholds=thresholds,
                )
                if not should_flag:
                    continue

                records.append(
                    SpectralQcRecord(
                        condition=condition,
                        pid=pid,
                        electrode=electrode,
                        frequency_hz=float(freq),
                        reason="off_harmonic_fft_snr_outlier",
                        snr_value=snr_value,
                        fft_amplitude_uv=fft_value,
                        group_median_fft_uv=median,
                        robust_z=robust_z,
                        fold_over_median=fold,
                        source_workbook=source_workbooks.get(pid, ""),
                    )
                )

    return SpectralQcResult(
        records=tuple(records),
        report_path=None,
        checked_cells=checked_cells,
        flagged_cells=len(records),
    )
