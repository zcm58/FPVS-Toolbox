from __future__ import annotations

import importlib
import importlib.util
import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Iterable

import numpy as np
import pandas as pd
from xlsxwriter.utility import xl_col_to_name
from PySide6.QtCore import QObject, Signal

from Tools.Ratio_Calculator.PySide6.model import RatioCalcInputs, RatioCalcResult
from Tools.Stats.PySide6.stats_data_loader import ScanError, scan_folder_simple
from Tools.Stats.Legacy.stats_export import _auto_format_and_write_excel
from Tools.Stats.roi_resolver import ROI

logger = logging.getLogger(__name__)

_SCIPY_STATS_SPEC = importlib.util.find_spec("scipy.stats")
_SCIPY_STATS_MODULE = None
_SCIPY_FALLBACK_LOGGED = False


ProgressCallback = Callable[[int], None]
LogCallback = Callable[[str], None]


@dataclass(frozen=True)
class _ParticipantFiles:
    pid: str
    cond_a_file: Path
    cond_b_file: Path


@dataclass
class RatioRow:
    pid: str
    summary_a: float | None
    summary_b: float | None
    ratio: float | None
    log_ratio: float | None
    ratio_percent: float | None
    sig_count: int
    sig_count_a: int
    sig_count_b: int
    metric_used: str
    skip_reason: str | None = None
    include_in_summary: bool = False
    base_valid: bool = False
    outlier_flag: bool = False
    outlier_method: str | None = None
    outlier_score: float | None = None
    excluded_as_outlier: bool = False
    snr_a: float | None = None
    snr_b: float | None = None
    denom_floor: float | None = None


@dataclass
class RoiComputation:
    rows: list[RatioRow]
    sig_harmonics_group_a: int
    sig_harmonics_group_b: int
    n_detected: int
    skip_reason: str | None = None


@dataclass
class RatioCalcSummaryCounts:
    participants_total: int = 0
    participants_used_per_roi: dict[str, int] = field(default_factory=dict)
    skipped_denominator_zero: int = 0
    skipped_missing: int = 0
    skipped_nonpositive_bca: int = 0
    outliers_flagged_per_roi: dict[str, int] = field(default_factory=dict)
    floor_excluded_per_roi: dict[str, int] = field(default_factory=dict)


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
                pd.DataFrame(), {}, None, [msg], {}, self.inputs.output_path, self.inputs.output_path.parent, [], []
            )
        self.finished.emit(result)


def compute_ratios(
    inputs: RatioCalcInputs,
    progress_cb: ProgressCallback | None = None,
    error_cb: LogCallback | None = None,
) -> RatioCalcResult:
    warnings: list[str] = []
    summary_counts = RatioCalcSummaryCounts()

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
    summary_counts.participants_total = len(participants_map)
    if not participants_map:
        log_warning("No participants with both conditions available.")
        empty_df = _build_output_frame(
            {},
            [],
            {},
            {},
            inputs.cond_a,
            inputs.cond_b,
            inputs.significance_mode,
            inputs.outlier_action,
            inputs.summary_metric,
            inputs.metric,
            None,
            {},
        )
        summary_table, exclusions = _build_report_tables(empty_df)
        return RatioCalcResult(
            empty_df,
            {},
            None,
            warnings,
            asdict(summary_counts),
            inputs.output_path,
            inputs.output_path.parent,
            summary_table,
            exclusions,
        )

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
            {},
            inputs.cond_a,
            inputs.cond_b,
            inputs.significance_mode,
            inputs.outlier_action,
            inputs.summary_metric,
            inputs.metric,
            None,
            {},
        )
        summary_table, exclusions = _build_report_tables(empty_df)
        return RatioCalcResult(
            empty_df,
            {},
            None,
            warnings,
            asdict(summary_counts),
            inputs.output_path,
            inputs.output_path.parent,
            summary_table,
            exclusions,
        )

    z_scores_a = _load_roi_z_scores_for_files(participants_map.values(), rois, log_warning, which="a")
    z_scores_b = _load_roi_z_scores_for_files(participants_map.values(), rois, log_warning, which="b")
    _emit(progress_cb, 40)
    sig_freqs_by_pid_a: dict[str, dict[str, list[float]]] | None = None
    sig_freqs_by_pid_b: dict[str, dict[str, list[float]]] | None = None
    if inputs.significance_mode == "individual":
        sig_freqs_by_pid_a = _determine_significant_frequencies_individual(z_scores_a, inputs.z_threshold)
        sig_freqs_by_pid_b = _determine_significant_frequencies_individual(z_scores_b, inputs.z_threshold)
        sig_freqs_a = _merge_individual_sig_freqs(sig_freqs_by_pid_a)
        sig_freqs_b = _merge_individual_sig_freqs(sig_freqs_by_pid_b)
    else:
        sig_freqs_a = _determine_significant_frequencies_group(z_scores_a, inputs.z_threshold)
        sig_freqs_b = _determine_significant_frequencies_group(z_scores_b, inputs.z_threshold)
    if not any(sig_freqs_a.values()) and not any(sig_freqs_b.values()):
        log_warning("No significant harmonics identified for any ROI.")
    _emit(progress_cb, 50)

    participants_seq = list(participants_map.values())
    ratio_data = _compute_ratio_table(
        participants_seq,
        rois,
        sig_freqs_a,
        sig_freqs_b,
        sig_freqs_by_pid_a,
        sig_freqs_by_pid_b,
        inputs,
        log_warning,
        summary_counts,
    )
    _apply_outlier_detection(ratio_data, inputs, log_warning, summary_counts)
    floor_map, floor_ref_n, floor_ref_key = _compute_denominator_floors(ratio_data, inputs, log_warning)
    _apply_denominator_floor(ratio_data, floor_map, summary_counts)
    summary_counts.participants_used_per_roi = _participants_used(ratio_data, inputs.summary_metric)
    _emit(progress_cb, 85)

    df = _build_output_frame(
        ratio_data,
        selected_roi_names,
        sig_freqs_a,
        sig_freqs_b,
        inputs.cond_a,
        inputs.cond_b,
        inputs.significance_mode,
        inputs.outlier_action,
        inputs.summary_metric,
        inputs.metric,
        floor_ref_key,
        floor_ref_n,
    )
    _emit(progress_cb, 90)
    _write_excel(df, inputs.output_path, log_info)
    _emit(progress_cb, 100)
    summary_table, exclusions = _build_report_tables(df)

    log_info(f"Participants total: {summary_counts.participants_total}")
    log_info(f"Participants used per ROI: {summary_counts.participants_used_per_roi}")
    log_info(f"Skipped denominator zero: {summary_counts.skipped_denominator_zero}")
    log_info(f"Skipped missing data: {summary_counts.skipped_missing}")
    log_info(f"Skipped non-positive BCA: {summary_counts.skipped_nonpositive_bca}")
    log_info(f"Outliers flagged per ROI: {summary_counts.outliers_flagged_per_roi}")
    log_info(f"Denominator floor exclusions per ROI: {summary_counts.floor_excluded_per_roi}")

    return RatioCalcResult(
        df,
        sig_freqs_a,
        sig_freqs_by_pid_a,
        warnings,
        asdict(summary_counts),
        inputs.output_path,
        inputs.output_path.parent,
        summary_table,
        exclusions,
    )


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


def _load_roi_z_scores_for_files(
    participants: Iterable[_ParticipantFiles],
    rois: list[ROI],
    log_warning: LogCallback,
    which: str,
) -> dict[str, dict[str, pd.Series]]:
    if which not in {"a", "b"}:
        raise ValueError(f"Invalid condition selector: {which}")
    data: dict[str, dict[str, pd.Series]] = {roi.name: {} for roi in rois}
    for part in participants:
        file_path = part.cond_a_file if which == "a" else part.cond_b_file
        try:
            df = pd.read_excel(file_path, sheet_name="Z Score")
        except FileNotFoundError:
            log_warning(f"Missing file for participant {part.pid}: {file_path}")
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
    sig_freqs_a: dict[str, list[float]],
    sig_freqs_b: dict[str, list[float]],
    individual_sig_freqs_a: dict[str, dict[str, list[float]]] | None,
    individual_sig_freqs_b: dict[str, dict[str, list[float]]] | None,
    inputs: RatioCalcInputs,
    log_warning: LogCallback,
    summary_counts: RatioCalcSummaryCounts,
) -> dict[str, RoiComputation]:
    metric_label = "BCA" if inputs.metric == "bca" else "SNR"
    ratio_data: dict[str, RoiComputation] = {}
    min_k = max(1, min(50, inputs.min_significant_harmonics))
    participants_list = list(participants)
    metrics_cache: dict[str, tuple[dict[str, pd.Series], dict[str, pd.Series]]] = {}
    for part in participants_list:
        metric_a = _load_metric_data(part.cond_a_file, rois, log_warning, part.pid, inputs.metric)
        metric_b = _load_metric_data(part.cond_b_file, rois, log_warning, part.pid, inputs.metric)
        metrics_cache[part.pid] = (metric_a, metric_b)
    for roi in rois:
        shared_freqs_a = sig_freqs_a.get(roi.name, [])
        shared_freqs_b = sig_freqs_b.get(roi.name, [])
        roi_rows: list[RatioRow] = []
        skip_reason = None
        if inputs.significance_mode != "individual" and (
            len(shared_freqs_a) < min_k or len(shared_freqs_b) < min_k
        ):
            skip_reason = "insufficient_sig_harmonics"
            log_warning(
                f"ROI {roi.name} has only {len(shared_freqs_a)}/{len(shared_freqs_b)} "
                f"significant harmonics (< {min_k}); skipping ratios."
            )
        for part in participants_list:
            metric_a, metric_b = metrics_cache.get(part.pid, ({}, {}))
            if inputs.significance_mode == "individual":
                freqs_a = (
                    individual_sig_freqs_a.get(roi.name, {}).get(part.pid, [])
                    if individual_sig_freqs_a is not None
                    else []
                )
                freqs_b = (
                    individual_sig_freqs_b.get(roi.name, {}).get(part.pid, [])
                    if individual_sig_freqs_b is not None
                    else []
                )
            else:
                freqs_a = shared_freqs_a
                freqs_b = shared_freqs_b
            sig_count_a = len(freqs_a)
            sig_count_b = len(freqs_b)
            sig_count = min(sig_count_a, sig_count_b)
            if skip_reason or sig_count_a < min_k or sig_count_b < min_k:
                roi_rows.append(
                    RatioRow(
                        pid=part.pid,
                        summary_a=None,
                        summary_b=None,
                        ratio=None,
                        log_ratio=None,
                        ratio_percent=None,
                        sig_count=sig_count,
                        sig_count_a=sig_count_a,
                        sig_count_b=sig_count_b,
                        metric_used=metric_label,
                        skip_reason=skip_reason or "insufficient_sig_harmonics",
                        include_in_summary=False,
                        base_valid=False,
                        snr_a=None,
                        snr_b=None,
                    )
                )
                continue

            summary_a = _summary_for_roi(metric_a.get(roi.name), freqs_a, inputs.metric, inputs.bca_negative_mode)
            summary_b = _summary_for_roi(metric_b.get(roi.name), freqs_b, inputs.metric, inputs.bca_negative_mode)

            if summary_a is None or summary_b is None:
                summary_counts.skipped_missing += 1
                roi_rows.append(
                    RatioRow(
                        pid=part.pid,
                        summary_a=summary_a,
                        summary_b=summary_b,
                        ratio=None,
                        log_ratio=None,
                        ratio_percent=None,
                        sig_count=sig_count,
                        sig_count_a=sig_count_a,
                        sig_count_b=sig_count_b,
                        metric_used=metric_label,
                        skip_reason="missing_data",
                        include_in_summary=False,
                        base_valid=False,
                        snr_a=summary_a,
                        snr_b=summary_b,
                    )
                )
                continue

            base_reason: str | None = None
            if inputs.metric == "bca" and inputs.bca_negative_mode == "strict" and (summary_a <= 0 or summary_b <= 0):
                base_reason = "nonpositive_bca_sum"
                summary_counts.skipped_nonpositive_bca += 1
                if summary_b == 0:
                    summary_counts.skipped_denominator_zero += 1
            if base_reason is None and summary_b == 0:
                base_reason = "denominator_zero"
                summary_counts.skipped_denominator_zero += 1

            ratio_value = None if base_reason else summary_a / summary_b
            log_ratio = float(np.log(ratio_value)) if ratio_value is not None and ratio_value > 0 and summary_a > 0 and summary_b > 0 else None
            ratio_percent = float((np.exp(log_ratio) - 1) * 100) if log_ratio is not None else None

            summary_metric_value = _summary_metric_value(ratio_value, log_ratio, inputs.summary_metric)
            base_valid = base_reason is None and summary_metric_value is not None and np.isfinite(summary_metric_value)

            roi_rows.append(
                RatioRow(
                    pid=part.pid,
                    summary_a=summary_a,
                    summary_b=summary_b,
                    ratio=ratio_value,
                    log_ratio=log_ratio,
                    ratio_percent=ratio_percent,
                    sig_count=sig_count,
                    sig_count_a=sig_count_a,
                    sig_count_b=sig_count_b,
                    metric_used=metric_label,
                    skip_reason=base_reason or None,
                    include_in_summary=base_valid,
                    base_valid=base_valid,
                    snr_a=summary_a,
                    snr_b=summary_b,
                )
            )
        ratio_data[roi.name] = RoiComputation(
            rows=roi_rows,
            sig_harmonics_group_a=len(shared_freqs_a),
            sig_harmonics_group_b=len(shared_freqs_b),
            n_detected=len(participants_list),
            skip_reason=skip_reason,
        )
    return ratio_data


def _load_metric_data(
    file_path: Path, rois: list[ROI], log_warning: LogCallback, pid: str, metric: str
) -> dict[str, pd.Series]:
    sheet_name = "BCA (uV)" if metric == "bca" else "SNR"
    try:
        df = pd.read_excel(file_path, sheet_name=sheet_name)
    except FileNotFoundError:
        log_warning(f"Missing file for participant {pid}: {file_path}")
        return {}
    except Exception as exc:  # noqa: BLE001
        log_warning(f"Failed to read {sheet_name} sheet for {pid}: {exc}")
        return {}

    if "Electrode" not in df.columns:
        log_warning(f"Electrode column missing in {sheet_name} for {pid}.")
        return {}

    freq_cols = [c for c in df.columns if c != "Electrode"]
    df["Electrode"] = df["Electrode"].astype(str).str.upper()
    metric_data: dict[str, pd.Series] = {}
    for roi in rois:
        mask = df["Electrode"].isin([c.upper() for c in roi.channels])
        if not mask.any():
            log_warning(f"No matching channels for ROI {roi.name} in {sheet_name} for {pid}.")
            continue
        metric_data[roi.name] = df.loc[mask, freq_cols].mean(axis=0, skipna=True)
    return metric_data


def _summary_for_roi(series: pd.Series | None, freqs: list[float], metric: str, negative_mode: str) -> float | None:
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
    arr = np.array(values, dtype=float)
    arr = arr[~np.isnan(arr)]
    if arr.size == 0:
        return None
    if metric == "bca":
        if negative_mode == "rectify":
            arr = np.maximum(arr, 0)
        return float(np.nansum(arr))
    return float(np.nanmean(arr))


def _summary_metric_value(ratio_value: float | None, log_ratio: float | None, summary_metric: str) -> float | None:
    if summary_metric == "ratio":
        return ratio_value if ratio_value is not None and np.isfinite(ratio_value) else None
    return log_ratio if log_ratio is not None and np.isfinite(log_ratio) else None


def _outlier_metric_value(row: RatioRow, metric: str) -> float | None:
    if metric == "ratio":
        return row.ratio if row.ratio is not None and np.isfinite(row.ratio) else None
    if metric == "logratio":
        return row.log_ratio if row.log_ratio is not None and np.isfinite(row.log_ratio) else None
    return None


def _apply_outlier_detection(
    ratio_data: dict[str, RoiComputation],
    inputs: RatioCalcInputs,
    log_warning: LogCallback,
    summary_counts: RatioCalcSummaryCounts,
) -> None:
    if not inputs.outlier_enabled:
        return
    for roi_name, comp in ratio_data.items():
        rows = comp.rows
        metric_name = inputs.outlier_metric if inputs.outlier_metric != "summary" else inputs.summary_metric
        valid_indices = [
            idx
            for idx, row in enumerate(rows)
            if row.base_valid and _outlier_metric_value(row, metric_name) is not None
        ]
        if len(valid_indices) < 5:
            log_warning(f"Outlier detection skipped for ROI {roi_name}: fewer than 5 valid rows.")
            continue
        values = np.array([_outlier_metric_value(rows[idx], metric_name) for idx in valid_indices], dtype=float)
        if inputs.outlier_method == "mad":
            median = float(np.nanmedian(values))
            mad = float(np.nanmedian(np.abs(values - median)))
            if mad == 0:
                log_warning(f"MAD is zero for ROI {roi_name}; treating all robust z as 0.")
                scores = np.zeros_like(values)
            else:
                scores = 0.6745 * (values - median) / mad
            flags = np.abs(scores) > inputs.outlier_threshold
            method_label = "MAD (robust z)"
        elif inputs.outlier_method == "iqr":
            q1 = float(np.nanquantile(values, 0.25))
            q3 = float(np.nanquantile(values, 0.75))
            iqr = q3 - q1
            if iqr == 0:
                log_warning(f"IQR is zero for ROI {roi_name}; no outliers flagged.")
                scores = np.zeros_like(values)
                flags = np.zeros_like(values, dtype=bool)
            else:
                k = float(inputs.outlier_threshold)
                low_fence = q1 - k * iqr
                high_fence = q3 + k * iqr
                flags = (values < low_fence) | (values > high_fence)
                scores = np.where(
                    values < low_fence,
                    low_fence - values,
                    np.where(values > high_fence, values - high_fence, 0.0),
                )
            method_label = "IQR"
        else:
            continue

        for idx, score, flag in zip(valid_indices, scores, flags):
            row = rows[idx]
            row.outlier_method = method_label
            row.outlier_score = float(score)
            row.outlier_flag = bool(flag)
            if flag:
                summary_counts.outliers_flagged_per_roi[roi_name] = (
                    summary_counts.outliers_flagged_per_roi.get(roi_name, 0) + 1
                )
                if inputs.outlier_action == "exclude":
                    row.include_in_summary = False
                    row.excluded_as_outlier = True


def _load_reference_group_pids(
    excel_root: Path,
    key: str,
    log_warning: LogCallback,
) -> set[str] | None:
    ref_path = excel_root / "ratio_calculator_reference_groups.json"
    if not ref_path.exists():
        log_warning(f"Denominator floor reference file not found at {ref_path}.")
        return None
    log_warning(f"Denominator floor reference file found at {ref_path}.")
    try:
        data = json.loads(ref_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        log_warning(f"Failed to parse denominator floor reference file: {exc}")
        return None
    if not isinstance(data, dict):
        log_warning("Denominator floor reference file is not a JSON object; ignoring.")
        return None
    raw_pids = data.get(key)
    if not isinstance(raw_pids, list) or not raw_pids:
        log_warning(f"Denominator floor reference key '{key}' missing or empty; ignoring.")
        return None
    normalized = {str(pid).strip().upper() for pid in raw_pids if str(pid).strip()}
    if not normalized:
        log_warning(f"Denominator floor reference key '{key}' contained no usable PIDs; ignoring.")
        return None
    return normalized


def _compute_denominator_floors(
    ratio_data: dict[str, RoiComputation],
    inputs: RatioCalcInputs,
    log_warning: LogCallback,
) -> tuple[dict[str, float], dict[str, int], str | None]:
    if not inputs.denominator_floor_enabled:
        return {}, {}, None
    floor_map: dict[str, float] = {}
    floor_ref_n: dict[str, int] = {}
    if inputs.denominator_floor_mode == "absolute":
        if inputs.denominator_floor_absolute is None:
            return {}, {}, None
        value = float(inputs.denominator_floor_absolute)
        for roi_name in ratio_data:
            floor_map[roi_name] = value
        return floor_map, floor_ref_n, None

    ref_key = inputs.denominator_floor_reference
    log_warning(f"Denominator floor reference key: {ref_key}")
    ref_pids = _load_reference_group_pids(inputs.excel_root, ref_key, log_warning)

    def _eligible_summary_b(comp: RoiComputation) -> tuple[list[float], set[str]]:
        values: list[float] = []
        matched_pids: set[str] = set()
        for row in comp.rows:
            if not row.include_in_summary:
                continue
            if row.summary_b is None or not np.isfinite(row.summary_b):
                continue
            pid = row.pid.upper()
            if ref_pids is not None and pid not in ref_pids:
                continue
            values.append(float(row.summary_b))
            matched_pids.add(pid)
        return values, matched_pids

    quantile = min(max(inputs.denominator_floor_quantile, 0.01), 0.25)
    if inputs.denominator_floor_scope == "global":
        values: list[float] = []
        matched_pids: set[str] = set()
        for comp in ratio_data.values():
            comp_values, comp_pids = _eligible_summary_b(comp)
            values.extend(comp_values)
            matched_pids.update(comp_pids)
        log_warning(f"Denominator floor reference eligible PIDs (global): {len(matched_pids)}")
        if not values:
            log_warning("Denominator floor (global) skipped: no eligible SummaryB values.")
            return {}, {}, ref_key
        floor_value = float(np.nanquantile(np.array(values, dtype=float), quantile))
        for roi_name in ratio_data:
            floor_map[roi_name] = floor_value
            floor_ref_n[roi_name] = len(matched_pids)
        return floor_map, floor_ref_n, ref_key

    for roi_name, comp in ratio_data.items():
        values, matched_pids = _eligible_summary_b(comp)
        log_warning(f"Denominator floor reference eligible PIDs for ROI {roi_name}: {len(matched_pids)}")
        if not values:
            log_warning(f"Denominator floor skipped for ROI {roi_name}: no eligible SummaryB values.")
            continue
        floor_map[roi_name] = float(np.nanquantile(np.array(values, dtype=float), quantile))
        floor_ref_n[roi_name] = len(matched_pids)
    return floor_map, floor_ref_n, ref_key


def _apply_denominator_floor(
    ratio_data: dict[str, RoiComputation],
    floor_map: dict[str, float],
    summary_counts: RatioCalcSummaryCounts,
) -> None:
    if not floor_map:
        return
    for roi_name, comp in ratio_data.items():
        floor_value = floor_map.get(roi_name)
        if floor_value is None:
            continue
        for row in comp.rows:
            row.denom_floor = floor_value
            if not row.include_in_summary:
                continue
            if row.summary_b is None or not np.isfinite(row.summary_b):
                continue
            if row.summary_b < floor_value:
                row.skip_reason = "denom_below_floor"
                row.include_in_summary = False
                row.ratio = None
                row.log_ratio = None
                row.ratio_percent = None
                summary_counts.floor_excluded_per_roi[roi_name] = (
                    summary_counts.floor_excluded_per_roi.get(roi_name, 0) + 1
                )


def _participants_used(ratios: dict[str, RoiComputation], summary_metric: str) -> dict[str, int]:
    usage: dict[str, int] = {}
    for roi_name, comp in ratios.items():
        usage[roi_name] = sum(
            1 for row in comp.rows if row.include_in_summary and _summary_metric_value(row.ratio, row.log_ratio, summary_metric) is not None
        )
    return usage


def _build_output_frame(
    ratios: dict[str, RoiComputation],
    roi_filter: list[str],
    sig_freqs_a: dict[str, list[float]],
    sig_freqs_b: dict[str, list[float]],
    cond_a: str,
    cond_b: str,
    significance_mode: str,
    outlier_action: str,
    summary_metric: str,
    metric: str,
    denom_floor_ref_key: str | None,
    denom_floor_ref_n: dict[str, int] | None,
) -> pd.DataFrame:
    metric_a_col, metric_b_col = _metric_columns(metric)
    rows: list[dict[str, float | str | int | None]] = []
    roi_names = roi_filter if roi_filter else list(ratios.keys()) or list(sig_freqs_a.keys()) or list(sig_freqs_b.keys())
    columns = _result_columns(metric_a_col, metric_b_col)

    for roi in roi_names:
        label = f"{cond_a} vs {cond_b} - {roi}"
        sig_count_group_a = len(sig_freqs_a.get(roi, []))
        sig_count_group_b = len(sig_freqs_b.get(roi, []))
        sig_count_group = min(sig_count_group_a, sig_count_group_b)
        roi_comp = ratios.get(
            roi,
            RoiComputation(
                rows=[],
                sig_harmonics_group_a=sig_count_group_a,
                sig_harmonics_group_b=sig_count_group_b,
                n_detected=0,
            ),
        )
        roi_ratios = roi_comp.rows if sig_count_group or significance_mode == "individual" else []

        n_base_valid = sum(1 for entry in roi_ratios if entry.base_valid)
        n_outlier_excluded = sum(1 for entry in roi_ratios if entry.excluded_as_outlier)
        n_floor_excluded = sum(
            1
            for entry in roi_ratios
            if entry.base_valid and not entry.include_in_summary and (entry.skip_reason or "") == "denom_below_floor"
        )
        n_used = sum(
            1
            for entry in roi_ratios
            if entry.include_in_summary and _summary_metric_value(entry.ratio, entry.log_ratio, summary_metric) is not None
        )

        summary_metric_values = [
            _summary_metric_value(entry.ratio, entry.log_ratio, summary_metric)
            for entry in roi_ratios
            if entry.include_in_summary
        ]
        summary_metric_series = pd.Series([v for v in summary_metric_values if v is not None and np.isfinite(v)])
        summary_metric_values_array = summary_metric_series.to_numpy(dtype=float)
        log_ratio_series = pd.Series(
            [entry.log_ratio for entry in roi_ratios if entry.include_in_summary and not entry.excluded_as_outlier and entry.log_ratio is not None and np.isfinite(entry.log_ratio)]
        )
        ratio_used_series = pd.Series(
            [entry.ratio for entry in roi_ratios if entry.include_in_summary and entry.ratio is not None and np.isfinite(entry.ratio)]
        )
        untrimmed_stats = _compute_summary_stats(summary_metric_series, log_ratio_series, ratio_used_series, summary_metric)
        trimmed_stats, n_trimmed_excluded, n_used_trimmed = _compute_trimmed_stats(summary_metric_series, summary_metric)
        (
            mean_ci_low_trim,
            mean_ci_high_trim,
            gmr_ci_low_trim,
            gmr_ci_high_trim,
        ) = _compute_trimmed_logratio_ci(log_ratio_series, log_func=logger.info)
        mean_ci_low, mean_ci_high = _bootstrap_mean_ci(summary_metric_values_array, n_boot=2000, alpha=0.05, seed=12345)
        if summary_metric == "logratio":
            gmr_ci_low = float(np.exp(mean_ci_low)) if np.isfinite(mean_ci_low) else np.nan
            gmr_ci_high = float(np.exp(mean_ci_high)) if np.isfinite(mean_ci_high) else np.nan
        else:
            gmr_ci_low = np.nan
            gmr_ci_high = np.nan

        for entry in roi_ratios:
            row = {col: None for col in columns}
            row.update(
                {
                    "Ratio Label": label,
                    "PID": entry.pid,
                    metric_a_col: entry.snr_a,
                    metric_b_col: entry.snr_b,
                    "SummaryA": entry.summary_a,
                    "SummaryB": entry.summary_b,
                    "Ratio": entry.ratio,
                    "LogRatio": entry.log_ratio,
                    "RatioPercent": entry.ratio_percent,
                    "MetricUsed": entry.metric_used,
                    "SkipReason": entry.skip_reason or "",
                    "IncludedInSummary": bool(entry.include_in_summary),
                    "OutlierFlag": bool(entry.outlier_flag),
                    "OutlierMethod": entry.outlier_method or "",
                    "OutlierScore": entry.outlier_score,
                    "ExcludedAsOutlier": bool(entry.excluded_as_outlier),
                    "SigHarmonicsA_N": entry.sig_count_a,
                    "SigHarmonicsB_N": entry.sig_count_b,
                    "SigHarmonics_N": entry.sig_count,
                    "DenomFloor": entry.denom_floor,
                }
            )
            rows.append(row)

        if significance_mode == "individual":
            sig_count_summary_a = max((entry.sig_count_a for entry in roi_ratios), default=0)
            sig_count_summary_b = max((entry.sig_count_b for entry in roi_ratios), default=0)
        else:
            sig_count_summary_a = roi_comp.sig_harmonics_group_a
            sig_count_summary_b = roi_comp.sig_harmonics_group_b
        sig_count_summary = min(sig_count_summary_a, sig_count_summary_b)
        skip_for_summary = roi_comp.skip_reason or ""
        denom_floor_ref_n_value = denom_floor_ref_n.get(roi) if denom_floor_ref_n else None
        denom_floor_ref_key_value = denom_floor_ref_key if denom_floor_ref_key else None

        summary_row = {col: None for col in columns}
        summary_row.update(
            {
                "Ratio Label": label,
                "PID": "SUMMARY",
                "SkipReason": skip_for_summary,
                "SummaryMetric": summary_metric,
                "SigHarmonicsA_N": sig_count_summary_a,
                "SigHarmonicsB_N": sig_count_summary_b,
                "SigHarmonics_N": sig_count_summary,
                "DenomFloor": roi_ratios[0].denom_floor if roi_ratios else None,
                "DenomFloorRefKey": denom_floor_ref_key_value,
                "DenomFloorRefN": denom_floor_ref_n_value,
                "N_detected": roi_comp.n_detected,
                "N_base_valid": n_base_valid,
                "N_outliers_excluded": n_outlier_excluded,
                "N_floor_excluded": n_floor_excluded,
                "N_used": n_used,
                "N": untrimmed_stats.n,
                "N_used_untrimmed": n_used,
                "N_used_trimmed": n_used_trimmed,
                "N_trimmed_excluded": n_trimmed_excluded,
                "Mean": untrimmed_stats.mean,
                "Mean_CI_low": mean_ci_low,
                "Mean_CI_high": mean_ci_high,
                "Median": untrimmed_stats.median,
                "Std": untrimmed_stats.std,
                "Variance": untrimmed_stats.variance,
                "CV%": untrimmed_stats.cv,
                "MeanRatio_fromLog": untrimmed_stats.mean_ratio_from_log,
                "MedianRatio_fromLog": untrimmed_stats.median_ratio_from_log,
                "Min": untrimmed_stats.min_val,
                "Max": untrimmed_stats.max_val,
                "MinRatio": untrimmed_stats.min_ratio,
                "MaxRatio": untrimmed_stats.max_ratio,
                "GMR_CI_low": gmr_ci_low,
                "GMR_CI_high": gmr_ci_high,
            }
        )
        rows.append(summary_row)

        trimmed_row = {col: None for col in columns}
        trimmed_row.update(
            {
                "Ratio Label": label,
                "PID": "SUMMARY_TRIMMED",
                "SkipReason": skip_for_summary,
                "SummaryMetric": summary_metric,
                "SigHarmonicsA_N": sig_count_summary_a,
                "SigHarmonicsB_N": sig_count_summary_b,
                "SigHarmonics_N": sig_count_summary,
                "DenomFloor": roi_ratios[0].denom_floor if roi_ratios else None,
                "DenomFloorRefKey": denom_floor_ref_key_value,
                "DenomFloorRefN": denom_floor_ref_n_value,
                "N_detected": roi_comp.n_detected,
                "N_base_valid": n_base_valid,
                "N_outliers_excluded": n_outlier_excluded,
                "N_floor_excluded": n_floor_excluded,
                "N_used": n_used_trimmed,
                "N": trimmed_stats.n,
                "N_used_untrimmed": n_used,
                "N_used_trimmed": n_used_trimmed,
                "N_trimmed_excluded": n_trimmed_excluded,
                "Mean": trimmed_stats.mean,
                "Mean_CI_low": np.nan,
                "Mean_CI_high": np.nan,
                "Median": trimmed_stats.median,
                "Std": trimmed_stats.std,
                "Variance": trimmed_stats.variance,
                "CV%": trimmed_stats.cv,
                "MeanRatio_fromLog": trimmed_stats.mean_ratio_from_log,
                "MedianRatio_fromLog": trimmed_stats.median_ratio_from_log,
                "Min": trimmed_stats.min_val,
                "Max": trimmed_stats.max_val,
                "MinRatio": trimmed_stats.min_ratio,
                "MaxRatio": trimmed_stats.max_ratio,
                "GMR_CI_low": np.nan,
                "GMR_CI_high": np.nan,
                "Mean_trim": trimmed_stats.mean,
                "Median_trim": trimmed_stats.median,
                "Std_trim": trimmed_stats.std,
                "Variance_trim": trimmed_stats.variance,
                "gCV%_trim": trimmed_stats.gcv,
                "MeanRatio_fromLog_trim": trimmed_stats.mean_ratio_from_log,
                "MedianRatio_fromLog_trim": trimmed_stats.median_ratio_from_log,
                "MinRatio_trim": trimmed_stats.min_ratio,
                "MaxRatio_trim": trimmed_stats.max_ratio,
                "Mean_CI_low_trim": mean_ci_low_trim,
                "Mean_CI_high_trim": mean_ci_high_trim,
                "GMR_CI_low_trim": gmr_ci_low_trim,
                "GMR_CI_high_trim": gmr_ci_high_trim,
            }
        )
        rows.append(trimmed_row)
        rows.append({})

    return pd.DataFrame(rows, columns=columns)


def _write_excel(df: pd.DataFrame, output_path: Path, log_func: LogCallback) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with pd.ExcelWriter(output_path, engine="xlsxwriter") as writer:
            _auto_format_and_write_excel(writer, df, "Ratio Calculator", log_func)
            _apply_ratio_calculator_formatting(writer, df, "Ratio Calculator")
    except Exception as exc:  # noqa: BLE001
        log_func(f"Failed to write Excel file: {exc}")


def _apply_ratio_calculator_formatting(writer: pd.ExcelWriter, df: pd.DataFrame, sheet_name: str) -> None:
    workbook = writer.book
    worksheet = writer.sheets[sheet_name]
    total_rows = len(df)
    total_cols = len(df.columns)
    if total_cols == 0:
        return

    worksheet.freeze_panes(1, 2)
    worksheet.autofilter(0, 0, 0, total_cols - 1)

    formats = _ratio_calculator_formats(workbook)
    pid_col_idx = df.columns.get_loc("PID") if "PID" in df.columns else 1

    ratio_cols = {
        "SummaryA",
        "SummaryB",
        "Ratio",
        "Mean",
        "Median",
        "Std",
        "Variance",
        "MeanRatio_fromLog",
        "MedianRatio_fromLog",
        "Min",
        "Max",
        "MinRatio",
        "MaxRatio",
        "GMR_CI_low",
        "GMR_CI_high",
        "Mean_trim",
        "Median_trim",
        "Std_trim",
        "Variance_trim",
        "MeanRatio_fromLog_trim",
        "MedianRatio_fromLog_trim",
        "MinRatio_trim",
        "MaxRatio_trim",
        "Mean_CI_low",
        "Mean_CI_high",
        "Mean_CI_low_trim",
        "Mean_CI_high_trim",
        "GMR_CI_low_trim",
        "GMR_CI_high_trim",
        "BCA_A",
        "BCA_B",
        "SNR_A",
        "SNR_B",
    }
    logratio_cols = {"LogRatio"}
    percent_cols = {"RatioPercent", "CV%", "gCV%_trim"}
    int_cols = {
        "SigHarmonicsA_N",
        "SigHarmonicsB_N",
        "SigHarmonics_N",
        "N_detected",
        "N_base_valid",
        "N_outliers_excluded",
        "N_floor_excluded",
        "N_used",
        "N",
        "N_used_untrimmed",
        "N_used_trimmed",
        "N_trimmed_excluded",
        "DenomFloorRefN",
    }

    for col_idx, col_name in enumerate(df.columns):
        col_series = df[col_name]
        col_format = _ratio_calc_col_format(
            col_name,
            col_series,
            formats,
            ratio_cols,
            logratio_cols,
            percent_cols,
            int_cols,
        )
        col_width = _ratio_calc_col_width(col_series, col_name)
        worksheet.set_column(col_idx, col_idx, col_width, col_format)

    if total_rows == 0:
        return

    first_data_row = 2
    last_data_row = total_rows + 1
    pid_col_letter = xl_col_to_name(pid_col_idx)
    summary_formatters = _ratio_calc_summary_formats(workbook)
    for col_idx, col_name in enumerate(df.columns):
        col_key = _ratio_calc_format_key(
            col_name,
            df[col_name],
            ratio_cols,
            logratio_cols,
            percent_cols,
            int_cols,
        )
        summary_format = summary_formatters["summary"][col_key]
        trimmed_format = summary_formatters["trimmed"][col_key]
        data_range = (first_data_row, col_idx, last_data_row, col_idx)
        worksheet.conditional_format(
            *data_range,
            {
                "type": "formula",
                "criteria": f'=${pid_col_letter}{first_data_row}=\"SUMMARY\"',
                "format": summary_format,
            },
        )
        worksheet.conditional_format(
            *data_range,
            {
                "type": "formula",
                "criteria": f'=${pid_col_letter}{first_data_row}=\"SUMMARY_TRIMMED\"',
                "format": trimmed_format,
            },
        )


def _ratio_calculator_formats(workbook) -> dict[str, object]:
    return {
        "left": workbook.add_format({"align": "left", "valign": "vcenter"}),
        "center": workbook.add_format({"align": "center", "valign": "vcenter"}),
        "int": workbook.add_format({"num_format": "0", "align": "center", "valign": "vcenter"}),
        "num_3dp": workbook.add_format({"num_format": "0.000", "align": "center", "valign": "vcenter"}),
        "num_1dp": workbook.add_format({"num_format": "0.0", "align": "center", "valign": "vcenter"}),
    }


def _ratio_calc_summary_formats(workbook) -> dict[str, dict[str, object]]:
    formats: dict[str, dict[str, object]] = {"summary": {}, "trimmed": {}}
    fill_map = {"summary": "#FFF2CC", "trimmed": "#E2F0D9"}
    for label, fill_color in fill_map.items():
        formats[label] = {
            "left": workbook.add_format(
                {"align": "left", "valign": "vcenter", "bold": True, "fg_color": fill_color}
            ),
            "center": workbook.add_format(
                {"align": "center", "valign": "vcenter", "bold": True, "fg_color": fill_color}
            ),
            "int": workbook.add_format(
                {"num_format": "0", "align": "center", "valign": "vcenter", "bold": True, "fg_color": fill_color}
            ),
            "num_3dp": workbook.add_format(
                {
                    "num_format": "0.000",
                    "align": "center",
                    "valign": "vcenter",
                    "bold": True,
                    "fg_color": fill_color,
                }
            ),
            "num_1dp": workbook.add_format(
                {
                    "num_format": "0.0",
                    "align": "center",
                    "valign": "vcenter",
                    "bold": True,
                    "fg_color": fill_color,
                }
            ),
        }
    return formats


def _ratio_calc_col_format(
    col_name: str,
    col_series: pd.Series,
    formats: dict[str, object],
    ratio_cols: set[str],
    logratio_cols: set[str],
    percent_cols: set[str],
    int_cols: set[str],
) -> object:
    key = _ratio_calc_format_key(col_name, col_series, ratio_cols, logratio_cols, percent_cols, int_cols)
    return formats[key]


def _ratio_calc_format_key(
    col_name: str,
    col_series: pd.Series,
    ratio_cols: set[str],
    logratio_cols: set[str],
    percent_cols: set[str],
    int_cols: set[str],
) -> str:
    if col_name in percent_cols:
        return "num_1dp"
    if col_name in ratio_cols or col_name in logratio_cols:
        return "num_3dp"
    if col_name in int_cols:
        return "int"
    if pd.api.types.is_string_dtype(col_series) or pd.api.types.is_object_dtype(col_series):
        return "left"
    if pd.api.types.is_integer_dtype(col_series):
        return "int"
    if pd.api.types.is_float_dtype(col_series):
        return "num_3dp"
    return "center"


def _ratio_calc_col_width(col_series: pd.Series, col_name: str, padding: int = 2) -> int:
    try:
        max_len = max(col_series.astype(str).map(len).max(), len(str(col_name)))
        return min(max(int(max_len) + padding, 10), 50)
    except Exception:
        return 15


def _result_columns(metric_a_col: str, metric_b_col: str) -> list[str]:
    return [
        "Ratio Label",
        "PID",
        metric_a_col,
        metric_b_col,
        "SummaryA",
        "SummaryB",
        "Ratio",
        "LogRatio",
        "RatioPercent",
        "MetricUsed",
        "SkipReason",
        "SummaryMetric",
        "IncludedInSummary",
        "OutlierFlag",
        "OutlierMethod",
        "OutlierScore",
        "ExcludedAsOutlier",
        "SigHarmonicsA_N",
        "SigHarmonicsB_N",
        "SigHarmonics_N",
        "DenomFloor",
        "DenomFloorRefKey",
        "DenomFloorRefN",
        "N_detected",
        "N_base_valid",
        "N_outliers_excluded",
        "N_floor_excluded",
        "N_used",
        "N",
        "N_used_untrimmed",
        "N_used_trimmed",
        "N_trimmed_excluded",
        "Mean",
        "Mean_CI_low",
        "Mean_CI_high",
        "Median",
        "Std",
        "Variance",
        "CV%",
        "MeanRatio_fromLog",
        "MedianRatio_fromLog",
        "Min",
        "Max",
        "MinRatio",
        "MaxRatio",
        "GMR_CI_low",
        "GMR_CI_high",
        "Mean_trim",
        "Median_trim",
        "Std_trim",
        "Variance_trim",
        "gCV%_trim",
        "MeanRatio_fromLog_trim",
        "MedianRatio_fromLog_trim",
        "Mean_CI_low_trim",
        "Mean_CI_high_trim",
        "GMR_CI_low_trim",
        "GMR_CI_high_trim",
        "MinRatio_trim",
        "MaxRatio_trim",
    ]


def _metric_columns(metric: str) -> tuple[str, str]:
    if metric == "bca":
        return "BCA_A", "BCA_B"
    return "SNR_A", "SNR_B"


@dataclass
class _SummaryStats:
    n: int
    mean: float
    median: float
    std: float
    variance: float
    cv: float
    mean_ratio_from_log: float
    median_ratio_from_log: float
    min_val: float
    max_val: float
    min_ratio: float
    max_ratio: float
    gcv: float


def _geometric_cv(std: float) -> float:
    if std is None or not np.isfinite(std):
        return np.nan
    return float(np.sqrt(np.exp(float(std) ** 2) - 1) * 100)


def _compute_summary_stats(
    summary_metric_series: pd.Series, log_ratio_series: pd.Series, ratio_series: pd.Series, summary_metric: str
) -> _SummaryStats:
    n = int(summary_metric_series.count()) if not summary_metric_series.empty else 0
    mean = float(summary_metric_series.mean()) if n else np.nan
    median = float(summary_metric_series.median()) if n else np.nan
    std = float(summary_metric_series.std()) if n else np.nan
    variance = float(summary_metric_series.var()) if n else np.nan
    if summary_metric == "logratio":
        cv = _geometric_cv(std)
    elif mean is not None and not np.isnan(mean) and mean != 0:
        cv = float((std / mean) * 100) if std is not None else np.nan
    else:
        cv = np.nan

    min_val = float(summary_metric_series.min()) if n else np.nan
    max_val = float(summary_metric_series.max()) if n else np.nan

    mean_ratio_from_log = float(np.exp(log_ratio_series.mean())) if not log_ratio_series.empty else np.nan
    median_ratio_from_log = float(np.exp(log_ratio_series.median())) if not log_ratio_series.empty else np.nan
    min_ratio = float(ratio_series.min()) if not ratio_series.empty else np.nan
    max_ratio = float(ratio_series.max()) if not ratio_series.empty else np.nan
    gcv = _geometric_cv(std if summary_metric == "logratio" else np.nan)
    return _SummaryStats(
        n=n,
        mean=mean,
        median=median,
        std=std,
        variance=variance,
        cv=cv,
        mean_ratio_from_log=mean_ratio_from_log,
        median_ratio_from_log=median_ratio_from_log,
        min_val=min_val,
        max_val=max_val,
        min_ratio=min_ratio,
        max_ratio=max_ratio,
        gcv=gcv,
    )


def _compute_trimmed_stats(values: pd.Series, summary_metric: str) -> tuple[_SummaryStats, int, int]:
    if values.empty or values.size < 3:
        empty_stats = _SummaryStats(
            n=0,
            mean=np.nan,
            median=np.nan,
            std=np.nan,
            variance=np.nan,
            cv=np.nan,
            mean_ratio_from_log=np.nan,
            median_ratio_from_log=np.nan,
            min_val=np.nan,
            max_val=np.nan,
            min_ratio=np.nan,
            max_ratio=np.nan,
            gcv=np.nan,
        )
        return empty_stats, 0, 0

    sorted_vals = np.sort(values.to_numpy())
    trimmed_vals = sorted_vals[1:-1]
    trimmed_series = pd.Series(trimmed_vals)
    n_used_trimmed = int(trimmed_series.size)
    mean = float(trimmed_series.mean()) if n_used_trimmed else np.nan
    median = float(trimmed_series.median()) if n_used_trimmed else np.nan
    std = float(trimmed_series.std()) if n_used_trimmed else np.nan
    variance = float(trimmed_series.var()) if n_used_trimmed else np.nan

    if summary_metric == "logratio":
        cv = _geometric_cv(std)
        mean_ratio_from_log = float(np.exp(trimmed_series.mean())) if n_used_trimmed else np.nan
        median_ratio_from_log = float(np.exp(trimmed_series.median())) if n_used_trimmed else np.nan
        min_val = float(trimmed_series.min()) if n_used_trimmed else np.nan
        max_val = float(trimmed_series.max()) if n_used_trimmed else np.nan
        min_ratio = float(np.exp(trimmed_series.min())) if n_used_trimmed else np.nan
        max_ratio = float(np.exp(trimmed_series.max())) if n_used_trimmed else np.nan
        gcv = _geometric_cv(std)
    else:
        cv = float((std / mean) * 100) if n_used_trimmed and np.isfinite(mean) and mean != 0 else np.nan
        mean_ratio_from_log = np.nan
        median_ratio_from_log = np.nan
        min_val = float(trimmed_series.min()) if n_used_trimmed else np.nan
        max_val = float(trimmed_series.max()) if n_used_trimmed else np.nan
        min_ratio = min_val
        max_ratio = max_val
        gcv = np.nan

    return (
        _SummaryStats(
            n=n_used_trimmed,
            mean=mean,
            median=median,
            std=std,
            variance=variance,
            cv=cv,
            mean_ratio_from_log=mean_ratio_from_log,
            median_ratio_from_log=median_ratio_from_log,
            min_val=min_val,
            max_val=max_val,
            min_ratio=min_ratio,
            max_ratio=max_ratio,
            gcv=gcv,
        ),
        2,
        n_used_trimmed,
    )


def _bootstrap_mean_ci(
    values: np.ndarray,
    n_boot: int = 2000,
    alpha: float = 0.05,
    seed: int = 12345,
) -> tuple[float, float]:
    if values.size < 3:
        return np.nan, np.nan
    if values.ndim != 1 or not np.all(np.isfinite(values)):
        raise ValueError("Values must be a 1D finite array.")
    rng = np.random.default_rng(seed)
    boot_means = np.empty(n_boot, dtype=float)
    for idx in range(n_boot):
        sample = rng.choice(values, size=values.size, replace=True)
        boot_means[idx] = np.mean(sample)
    low = float(np.quantile(boot_means, alpha / 2))
    high = float(np.quantile(boot_means, 1 - alpha / 2))
    return low, high


def _get_scipy_stats(log_func: LogCallback | None = None):
    global _SCIPY_STATS_MODULE
    global _SCIPY_FALLBACK_LOGGED
    if _SCIPY_STATS_MODULE is None and _SCIPY_STATS_SPEC is not None:
        _SCIPY_STATS_MODULE = importlib.import_module("scipy.stats")
    if _SCIPY_STATS_MODULE is None and log_func is not None and not _SCIPY_FALLBACK_LOGGED:
        log_func("SciPy stats unavailable; trimmed CI will use normal approximation.")
        _SCIPY_FALLBACK_LOGGED = True
    return _SCIPY_STATS_MODULE


def _compute_trimmed_logratio_ci(
    log_ratio_series: pd.Series,
    log_func: LogCallback | None = None,
) -> tuple[float, float, float, float]:
    global _SCIPY_FALLBACK_LOGGED
    log_values = log_ratio_series.dropna().to_numpy(dtype=float)
    log_values = log_values[np.isfinite(log_values)]
    if log_values.size < 3:
        return np.nan, np.nan, np.nan, np.nan

    sorted_vals = np.sort(log_values)
    trimmed_vals = sorted_vals[1:-1]
    if trimmed_vals.size < 2:
        return np.nan, np.nan, np.nan, np.nan

    mean = float(np.mean(trimmed_vals))
    std = float(np.std(trimmed_vals, ddof=1))
    if not np.isfinite(std) or std == 0:
        return np.nan, np.nan, np.nan, np.nan
    se = std / np.sqrt(trimmed_vals.size)

    stats_module = _get_scipy_stats(log_func)
    if stats_module is not None:
        tcrit = float(stats_module.t.ppf(0.975, df=trimmed_vals.size - 1))
    else:
        tcrit = 1.96

    mean_ci_low = float(mean - tcrit * se)
    mean_ci_high = float(mean + tcrit * se)
    gmr_ci_low = float(np.exp(mean_ci_low)) if np.isfinite(mean_ci_low) else np.nan
    gmr_ci_high = float(np.exp(mean_ci_high)) if np.isfinite(mean_ci_high) else np.nan
    return mean_ci_low, mean_ci_high, gmr_ci_low, gmr_ci_high


def _parse_roi_name(label: str) -> str:
    if " - " in label:
        return label.split(" - ", 1)[1]
    return label


def _build_report_tables(df: pd.DataFrame) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    summary_rows = df[df["PID"].isin(["SUMMARY", "SUMMARY_TRIMMED"])].copy()
    summaries: list[dict[str, object]] = []
    exclusions: list[dict[str, object]] = []

    for label, group in summary_rows.groupby("Ratio Label"):
        untrimmed = group[group["PID"] == "SUMMARY"].iloc[0] if not group[group["PID"] == "SUMMARY"].empty else None
        trimmed = group[group["PID"] == "SUMMARY_TRIMMED"].iloc[0] if not group[group["PID"] == "SUMMARY_TRIMMED"].empty else None
        roi_name = _parse_roi_name(label)
        summary_metric = None
        if untrimmed is not None:
            summary_metric = untrimmed.get("SummaryMetric")
        if not summary_metric and trimmed is not None:
            summary_metric = trimmed.get("SummaryMetric")
        scale_label = "LogRatio" if summary_metric == "logratio" else "Ratio"
        entry: dict[str, object] = {
            "ROI": roi_name,
            "Ratio Label": label,
            "Scale": f"Scale: {scale_label}",
        }
        if untrimmed is not None:
            entry.update(
                {
                    "SigHarmonics_N": untrimmed.get("SigHarmonics_N"),
                    "N_detected": untrimmed.get("N_detected"),
                    "N_base_valid": untrimmed.get("N_base_valid"),
                    "N_outliers_excluded": untrimmed.get("N_outliers_excluded"),
                    "N_floor_excluded": untrimmed.get("N_floor_excluded"),
                    "N_used_untrimmed": untrimmed.get("N_used_untrimmed"),
                    "Mean": untrimmed.get("Mean"),
                    "Mean_CI_low": untrimmed.get("Mean_CI_low"),
                    "Mean_CI_high": untrimmed.get("Mean_CI_high"),
                    "Median": untrimmed.get("Median"),
                    "Std": untrimmed.get("Std"),
                    "Variance": untrimmed.get("Variance"),
                    "CV%": untrimmed.get("CV%"),
                    "MeanRatio_fromLog": untrimmed.get("MeanRatio_fromLog"),
                    "MedianRatio_fromLog": untrimmed.get("MedianRatio_fromLog"),
                    "Min": untrimmed.get("Min"),
                    "Max": untrimmed.get("Max"),
                    "MinRatio": untrimmed.get("MinRatio"),
                    "MaxRatio": untrimmed.get("MaxRatio"),
                    "GMR_CI_low": untrimmed.get("GMR_CI_low"),
                    "GMR_CI_high": untrimmed.get("GMR_CI_high"),
                }
            )
        if trimmed is not None:
            entry.update(
                {
                    "N_used_trimmed": trimmed.get("N_used_trimmed"),
                    "N_trimmed_excluded": trimmed.get("N_trimmed_excluded"),
                    "Mean_trim": trimmed.get("Mean"),
                    "Median_trim": trimmed.get("Median"),
                    "Std_trim": trimmed.get("Std"),
                    "Variance_trim": trimmed.get("Variance"),
                    "CV%_trim": trimmed.get("CV%"),
                    "MeanRatio_fromLog_trim": trimmed.get("MeanRatio_fromLog_trim"),
                    "MedianRatio_fromLog_trim": trimmed.get("MedianRatio_fromLog_trim"),
                    "Min_trim": trimmed.get("Min"),
                    "Max_trim": trimmed.get("Max"),
                    "MinRatio_trim": trimmed.get("MinRatio_trim"),
                    "MaxRatio_trim": trimmed.get("MaxRatio_trim"),
                }
            )
        summaries.append(entry)

    participant_rows = df[df["PID"].notna() & ~df["PID"].isin(["SUMMARY", "SUMMARY_TRIMMED"])].copy()
    for _, row in participant_rows.iterrows():
        included = bool(row.get("IncludedInSummary"))
        excluded_as_outlier = bool(row.get("ExcludedAsOutlier"))
        reason = str(row.get("SkipReason") or "")
        if included and not excluded_as_outlier:
            continue
        if not reason and excluded_as_outlier:
            reason = "excluded_as_outlier"
        if not reason and not included:
            reason = "excluded"
        if not reason:
            continue
        exclusions.append(
            {
                "ROI": _parse_roi_name(str(row.get("Ratio Label", ""))),
                "PID": row.get("PID"),
                "Reason": reason,
            }
        )

    return summaries, exclusions
