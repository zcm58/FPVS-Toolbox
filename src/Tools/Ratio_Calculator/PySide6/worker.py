from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

import numpy as np
import pandas as pd
from PySide6.QtCore import QObject, Signal

from Tools.Ratio_Calculator.PySide6.model import RatioCalcInputs, RatioCalcResult
from Tools.Stats.PySide6.stats_data_loader import ScanError, scan_folder_simple
from Tools.Stats.Legacy.stats_export import _auto_format_and_write_excel
from Tools.Stats.roi_resolver import ROI

logger = logging.getLogger(__name__)


ProgressCallback = Callable[[int], None]
LogCallback = Callable[[str], None]


@dataclass(frozen=True)
class _ParticipantFiles:
    pid: str
    cond_a_file: Path
    cond_b_file: Path


@dataclass(frozen=True)
class RatioRow:
    pid: str
    snr_a: float | None
    snr_b: float | None
    ratio: float | None
    sig_count: int


class RatioCalcWorker(QObject):
    progress = Signal(int)
    error = Signal(str)
    finished = Signal(RatioCalcResult)

    def __init__(self, inputs: RatioCalcInputs, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.inputs = inputs

    def run(self) -> None:
        try:
            result = compute_ratios(self.inputs, self.progress.emit, self.error.emit)
        except Exception as exc:  # noqa: BLE001
            msg = f"Ratio calculation failed: {exc}"
            logger.exception(msg)
            self.error.emit(msg)
            result = RatioCalcResult(
                pd.DataFrame(), {}, None, [msg], self.inputs.output_path, self.inputs.output_path.parent
            )
        self.finished.emit(result)


def compute_ratios(
    inputs: RatioCalcInputs,
    progress_cb: ProgressCallback | None = None,
    error_cb: LogCallback | None = None,
) -> RatioCalcResult:
    warnings: list[str] = []

    def log_warning(message: str) -> None:
        warnings.append(message)
        if error_cb:
            error_cb(message)

    def log_info(message: str) -> None:
        if error_cb:
            error_cb(message)

    excel_root = inputs.excel_root
    _emit(progress_cb, 2)
    try:
        participants, conditions, subject_data = scan_folder_simple(str(excel_root))
    except ScanError as exc:
        raise RuntimeError(f"Folder scan failed: {exc}") from exc
    _emit(progress_cb, 8)

    if inputs.cond_a not in conditions:
        log_warning(f"Condition {inputs.cond_a} not found in {excel_root}.")
    if inputs.cond_b not in conditions:
        log_warning(f"Condition {inputs.cond_b} not found in {excel_root}.")

    participants_map = _build_participant_files(participants, subject_data, inputs)
    if not participants_map:
        log_warning("No participants with both conditions available.")
        empty_df = _build_output_frame({}, [], {}, inputs.cond_a, inputs.cond_b, inputs.significance_mode)
        return RatioCalcResult(empty_df, {}, None, warnings, inputs.output_path, inputs.output_path.parent)

    _emit(progress_cb, 12)
    rois = inputs.rois
    if inputs.roi_name and inputs.roi_name.lower() != "all rois":
        rois = [roi for roi in rois if roi.name == inputs.roi_name]
    selected_roi_names = [r.name for r in rois]
    if not rois:
        log_warning("No ROI definitions available after filtering.")
        empty_df = _build_output_frame(
            {},
            selected_roi_names,
            {},
            inputs.cond_a,
            inputs.cond_b,
            inputs.significance_mode,
        )
        return RatioCalcResult(empty_df, {}, None, warnings, inputs.output_path, inputs.output_path.parent)

    z_scores = _load_roi_z_scores(participants_map.values(), rois, log_warning)
    _emit(progress_cb, 40)
    sig_freqs_by_pid: dict[str, dict[str, list[float]]] | None = None
    if inputs.significance_mode == "individual":
        sig_freqs_by_pid = _determine_significant_frequencies_individual(z_scores, inputs.z_threshold)
        sig_freqs = _merge_individual_sig_freqs(sig_freqs_by_pid)
    else:
        sig_freqs = _determine_significant_frequencies_group(z_scores, inputs.z_threshold)
    if not any(sig_freqs.values()):
        log_warning("No significant harmonics identified for any ROI.")
    _emit(progress_cb, 50)

    ratios = _compute_ratio_table(participants_map.values(), rois, sig_freqs, sig_freqs_by_pid, inputs, log_warning)
    _emit(progress_cb, 85)

    df = _build_output_frame(
        ratios,
        selected_roi_names,
        sig_freqs,
        inputs.cond_a,
        inputs.cond_b,
        inputs.significance_mode,
    )
    _emit(progress_cb, 90)
    _write_excel(df, inputs.output_path, log_info)
    _emit(progress_cb, 100)

    return RatioCalcResult(df, sig_freqs, sig_freqs_by_pid, warnings, inputs.output_path, inputs.output_path.parent)


def _emit(progress_cb: ProgressCallback | None, value: int) -> None:
    if progress_cb:
        progress_cb(int(value))


def _build_participant_files(
    participants: Iterable[str],
    subject_data: dict[str, dict[str, str]],
    inputs: RatioCalcInputs,
) -> dict[str, _ParticipantFiles]:
    participants_map: dict[str, _ParticipantFiles] = {}
    for pid in participants:
        conds = subject_data.get(pid, {})
        cond_a_file = conds.get(inputs.cond_a)
        cond_b_file = conds.get(inputs.cond_b)
        if not cond_a_file or not cond_b_file:
            continue
        participants_map[pid] = _ParticipantFiles(pid=pid, cond_a_file=Path(cond_a_file), cond_b_file=Path(cond_b_file))
    return participants_map


def _load_roi_z_scores(
    participants: Iterable[_ParticipantFiles],
    rois: list[ROI],
    log_warning: LogCallback,
) -> dict[str, dict[str, pd.Series]]:
    data: dict[str, dict[str, pd.Series]] = {roi.name: {} for roi in rois}
    for part in participants:
        try:
            df = pd.read_excel(part.cond_a_file, sheet_name="Z Score")
        except FileNotFoundError:
            log_warning(f"Missing file for participant {part.pid}: {part.cond_a_file}")
            continue
        except Exception as exc:  # noqa: BLE001
            log_warning(f"Failed to read Z Score sheet for {part.pid}: {exc}")
            continue

        if "Electrode" not in df.columns:
            log_warning(f"Electrode column missing in Z Score for {part.pid}.")
            continue

        freq_cols = [c for c in df.columns if c != "Electrode"]
        df["Electrode"] = df["Electrode"].astype(str).str.upper()
        for roi in rois:
            mask = df["Electrode"].isin([c.upper() for c in roi.channels])
            if not mask.any():
                log_warning(f"No matching channels for ROI {roi.name} in Z Score for {part.pid}.")
                continue
            mean_series = df.loc[mask, freq_cols].mean(axis=0, skipna=True)
            data[roi.name][part.pid] = mean_series
    return data


def _determine_significant_frequencies_group(
    z_scores: dict[str, dict[str, pd.Series]], threshold: float
) -> dict[str, list[float]]:
    sig_freqs: dict[str, list[float]] = {}
    for roi_name, per_part in z_scores.items():
        if not per_part:
            sig_freqs[roi_name] = []
            continue
        df_roi = pd.DataFrame(per_part).T
        means = df_roi.mean(axis=0, skipna=True)
        selected: list[float] = []
        for col, value in means.items():
            try:
                freq_val = float(str(col).split("_")[0])
            except (TypeError, ValueError):
                continue
            if value > threshold:
                selected.append(freq_val)
        sig_freqs[roi_name] = selected
    return sig_freqs


def _determine_significant_frequencies_individual(
    z_scores: dict[str, dict[str, pd.Series]], threshold: float
) -> dict[str, dict[str, list[float]]]:
    sig_freqs: dict[str, dict[str, list[float]]] = {}
    for roi_name, per_part in z_scores.items():
        sig_freqs[roi_name] = {}
        for pid, series in per_part.items():
            sig_freqs[roi_name][pid] = _sig_freqs_for_series(series, threshold)
    return sig_freqs


def _sig_freqs_for_series(series: pd.Series, threshold: float) -> list[float]:
    selected: list[float] = []
    for col, value in series.items():
        try:
            freq_val = float(str(col).split("_")[0])
        except (TypeError, ValueError):
            continue
        if value > threshold:
            selected.append(freq_val)
    return selected


def _merge_individual_sig_freqs(sig_freqs: dict[str, dict[str, list[float]]]) -> dict[str, list[float]]:
    merged: dict[str, list[float]] = {}
    for roi_name, per_pid in sig_freqs.items():
        combined = sorted({freq for freqs in per_pid.values() for freq in freqs})
        merged[roi_name] = combined
    return merged


def _compute_ratio_table(
    participants: Iterable[_ParticipantFiles],
    rois: list[ROI],
    sig_freqs: dict[str, list[float]],
    individual_sig_freqs: dict[str, dict[str, list[float]]] | None,
    inputs: RatioCalcInputs,
    log_warning: LogCallback,
) -> dict[str, list[RatioRow]]:
    ratios: dict[str, list[RatioRow]] = {roi.name: [] for roi in rois}
    for part in participants:
        snr_a = _load_snr(part.cond_a_file, rois, log_warning, part.pid)
        snr_b = _load_snr(part.cond_b_file, rois, log_warning, part.pid)

        for roi in rois:
            if inputs.significance_mode == "individual" and individual_sig_freqs is not None:
                freqs = individual_sig_freqs.get(roi.name, {}).get(part.pid, [])
            else:
                freqs = sig_freqs.get(roi.name, [])
            if not freqs:
                log_warning(f"No significant harmonics for ROI {roi.name}; skipping ratios.")
                continue

            summary_a = _summary_for_roi(snr_a.get(roi.name), freqs)
            summary_b = _summary_for_roi(snr_b.get(roi.name), freqs)

            if summary_a is None or summary_b is None:
                log_warning(f"Missing ROI data for participant {part.pid} in ROI {roi.name}; skipping participant.")
                continue

            if summary_b == 0:
                log_warning(f"Denominator SNR is zero for participant {part.pid} ROI {roi.name}; skipping participant.")
                continue
            ratio_value = summary_a / summary_b
            ratios.setdefault(roi.name, []).append(
                RatioRow(
                    pid=part.pid,
                    snr_a=summary_a,
                    snr_b=summary_b,
                    ratio=ratio_value,
                    sig_count=len(freqs),
                )
            )
    return ratios


def _load_snr(file_path: Path, rois: list[ROI], log_warning: LogCallback, pid: str) -> dict[str, pd.Series]:
    try:
        df = pd.read_excel(file_path, sheet_name="SNR")
    except FileNotFoundError:
        log_warning(f"Missing file for participant {pid}: {file_path}")
        return {}
    except Exception as exc:  # noqa: BLE001
        log_warning(f"Failed to read SNR sheet for {pid}: {exc}")
        return {}

    if "Electrode" not in df.columns:
        log_warning(f"Electrode column missing in SNR for {pid}.")
        return {}

    freq_cols = [c for c in df.columns if c != "Electrode"]
    df["Electrode"] = df["Electrode"].astype(str).str.upper()
    snr_data: dict[str, pd.Series] = {}
    for roi in rois:
        mask = df["Electrode"].isin([c.upper() for c in roi.channels])
        if not mask.any():
            log_warning(f"No matching channels for ROI {roi.name} in SNR for {pid}.")
            continue
        snr_data[roi.name] = df.loc[mask, freq_cols].mean(axis=0, skipna=True)
    return snr_data


def _summary_for_roi(series: pd.Series | None, freqs: list[float]) -> float | None:
    if series is None:
        return None
    values = []
    for freq in freqs:
        col = f"{freq:.4f}_Hz"
        if col not in series.index:
            continue
        values.append(series[col])
    if not values:
        return None
    return float(np.nanmean(values))


def _build_output_frame(
    ratios: dict[str, list[RatioRow]],
    roi_filter: list[str],
    sig_freqs: dict[str, list[float]],
    cond_a: str,
    cond_b: str,
    significance_mode: str,
) -> pd.DataFrame:
    rows: list[dict[str, float | str | int | None]] = []
    roi_names = roi_filter if roi_filter else list(ratios.keys()) or list(sig_freqs.keys())

    for roi in roi_names:
        label = f"{cond_a} vs {cond_b} - {roi}"
        sig_count_group = len(sig_freqs.get(roi, []))
        roi_ratios = ratios.get(roi, []) if sig_count_group or significance_mode == "individual" else []

        for entry in roi_ratios:
            rows.append(
                {
                    "Ratio Label": label,
                    "PID": entry.pid,
                    "SNR_A": entry.snr_a,
                    "SNR_B": entry.snr_b,
                    "Ratio": entry.ratio,
                    "SigHarmonics_N": entry.sig_count,
                    "N": None,
                    "Mean": None,
                    "Median": None,
                    "Std": None,
                    "Variance": None,
                    "CV%": None,
                    "Min": None,
                    "Max": None,
                }
            )

        ratio_series = pd.Series([entry.ratio for entry in roi_ratios if entry.ratio is not None])
        n = int(ratio_series.count()) if not ratio_series.empty else 0
        mean = float(ratio_series.mean()) if n else np.nan
        median = float(ratio_series.median()) if n else np.nan
        std = float(ratio_series.std()) if n else np.nan
        variance = float(ratio_series.var()) if n else np.nan
        if mean is not None and not np.isnan(mean) and mean != 0:
            cv = float((std / mean) * 100) if std is not None else np.nan
        else:
            cv = np.nan
        min_val = float(ratio_series.min()) if n else np.nan
        max_val = float(ratio_series.max()) if n else np.nan

        sig_count_summary = sig_count_group or max((entry.sig_count for entry in roi_ratios), default=0)

        rows.append(
            {
                "Ratio Label": label,
                "PID": "SUMMARY",
                "SNR_A": None,
                "SNR_B": None,
                "Ratio": None,
                "SigHarmonics_N": sig_count_summary,
                "N": n,
                "Mean": mean,
                "Median": median,
                "Std": std,
                "Variance": variance,
                "CV%": cv if np.isfinite(cv) else np.nan,
                "Min": min_val,
                "Max": max_val,
            }
        )
        rows.append({})

    columns = [
        "Ratio Label",
        "PID",
        "SNR_A",
        "SNR_B",
        "Ratio",
        "SigHarmonics_N",
        "N",
        "Mean",
        "Median",
        "Std",
        "Variance",
        "CV%",
        "Min",
        "Max",
    ]
    return pd.DataFrame(rows, columns=columns)


def _write_excel(df: pd.DataFrame, output_path: Path, log_func: LogCallback) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with pd.ExcelWriter(output_path, engine="xlsxwriter") as writer:
            _auto_format_and_write_excel(writer, df, "Ratio Calculator", log_func)
    except Exception as exc:  # noqa: BLE001
        log_func(f"Failed to write Excel file: {exc}")
