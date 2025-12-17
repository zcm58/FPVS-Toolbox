from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
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


@dataclass
class RatioRow:
    pid: str
    summary_a: float | None
    summary_b: float | None
    ratio: float | None
    log_ratio: float | None
    ratio_percent: float | None
    sig_count: int
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
    sig_harmonics_group: int
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
                pd.DataFrame(), {}, None, [msg], {}, self.inputs.output_path, self.inputs.output_path.parent
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
            inputs.cond_a,
            inputs.cond_b,
            inputs.significance_mode,
            inputs.outlier_action,
            inputs.summary_metric,
        )
        return RatioCalcResult(empty_df, {}, None, warnings, asdict(summary_counts), inputs.output_path, inputs.output_path.parent)

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
            inputs.outlier_action,
            inputs.summary_metric,
        )
        return RatioCalcResult(empty_df, {}, None, warnings, asdict(summary_counts), inputs.output_path, inputs.output_path.parent)

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

    participants_seq = list(participants_map.values())
    ratio_data = _compute_ratio_table(
        participants_seq, rois, sig_freqs, sig_freqs_by_pid, inputs, log_warning, summary_counts
    )
    _apply_outlier_detection(ratio_data, inputs, log_warning, summary_counts)
    floor_map = _compute_denominator_floors(ratio_data, inputs, log_warning)
    _apply_denominator_floor(ratio_data, floor_map, summary_counts)
    summary_counts.participants_used_per_roi = _participants_used(ratio_data, inputs.summary_metric)
    _emit(progress_cb, 85)

    df = _build_output_frame(
        ratio_data,
        selected_roi_names,
        sig_freqs,
        inputs.cond_a,
        inputs.cond_b,
        inputs.significance_mode,
        inputs.outlier_action,
        inputs.summary_metric,
    )
    _emit(progress_cb, 90)
    _write_excel(df, inputs.output_path, log_info)
    _emit(progress_cb, 100)

    log_info(f"Participants total: {summary_counts.participants_total}")
    log_info(f"Participants used per ROI: {summary_counts.participants_used_per_roi}")
    log_info(f"Skipped denominator zero: {summary_counts.skipped_denominator_zero}")
    log_info(f"Skipped missing data: {summary_counts.skipped_missing}")
    log_info(f"Skipped non-positive BCA: {summary_counts.skipped_nonpositive_bca}")
    log_info(f"Outliers flagged per ROI: {summary_counts.outliers_flagged_per_roi}")
    log_info(f"Denominator floor exclusions per ROI: {summary_counts.floor_excluded_per_roi}")

    return RatioCalcResult(
        df,
        sig_freqs,
        sig_freqs_by_pid,
        warnings,
        asdict(summary_counts),
        inputs.output_path,
        inputs.output_path.parent,
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
        shared_freqs = sig_freqs.get(roi.name, [])
        roi_rows: list[RatioRow] = []
        skip_reason = None
        if inputs.significance_mode != "individual" and len(shared_freqs) < min_k:
            skip_reason = "insufficient_sig_harmonics"
            log_warning(f"ROI {roi.name} has only {len(shared_freqs)} significant harmonics (< {min_k}); skipping ratios.")
        for part in participants_list:
            metric_a, metric_b = metrics_cache.get(part.pid, ({}, {}))
            freqs = (
                individual_sig_freqs.get(roi.name, {}).get(part.pid, [])
                if inputs.significance_mode == "individual" and individual_sig_freqs is not None
                else shared_freqs
            )
            sig_count = len(freqs)
            if skip_reason or sig_count < min_k:
                roi_rows.append(
                    RatioRow(
                        pid=part.pid,
                        summary_a=None,
                        summary_b=None,
                        ratio=None,
                        log_ratio=None,
                        ratio_percent=None,
                        sig_count=sig_count,
                        metric_used=metric_label,
                        skip_reason=skip_reason or "insufficient_sig_harmonics",
                        include_in_summary=False,
                        base_valid=False,
                        snr_a=None,
                        snr_b=None,
                    )
                )
                continue

            summary_a = _summary_for_roi(metric_a.get(roi.name), freqs, inputs.metric, inputs.bca_negative_mode)
            summary_b = _summary_for_roi(metric_b.get(roi.name), freqs, inputs.metric, inputs.bca_negative_mode)

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
            sig_harmonics_group=len(shared_freqs),
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


def _compute_denominator_floors(
    ratio_data: dict[str, RoiComputation],
    inputs: RatioCalcInputs,
    log_warning: LogCallback,
) -> dict[str, float]:
    if not inputs.denominator_floor_enabled:
        return {}
    floor_map: dict[str, float] = {}
    if inputs.denominator_floor_mode == "absolute":
        if inputs.denominator_floor_absolute is None:
            return {}
        value = float(inputs.denominator_floor_absolute)
        for roi_name in ratio_data:
            floor_map[roi_name] = value
        return floor_map

    def _eligible_summary_b(comp: RoiComputation) -> list[float]:
        return [
            float(row.summary_b)
            for row in comp.rows
            if row.include_in_summary and row.summary_b is not None and np.isfinite(row.summary_b)
        ]

    quantile = min(max(inputs.denominator_floor_quantile, 0.01), 0.25)
    if inputs.denominator_floor_scope == "global":
        values: list[float] = []
        for comp in ratio_data.values():
            values.extend(_eligible_summary_b(comp))
        if not values:
            log_warning("Denominator floor (global) skipped: no eligible SummaryB values.")
            return {}
        floor_value = float(np.nanquantile(np.array(values, dtype=float), quantile))
        for roi_name in ratio_data:
            floor_map[roi_name] = floor_value
        return floor_map

    for roi_name, comp in ratio_data.items():
        values = _eligible_summary_b(comp)
        if not values:
            log_warning(f"Denominator floor skipped for ROI {roi_name}: no eligible SummaryB values.")
            continue
        floor_map[roi_name] = float(np.nanquantile(np.array(values, dtype=float), quantile))
    return floor_map


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
    sig_freqs: dict[str, list[float]],
    cond_a: str,
    cond_b: str,
    significance_mode: str,
    outlier_action: str,
    summary_metric: str,
) -> pd.DataFrame:
    rows: list[dict[str, float | str | int | None]] = []
    roi_names = roi_filter if roi_filter else list(ratios.keys()) or list(sig_freqs.keys())

    for roi in roi_names:
        label = f"{cond_a} vs {cond_b} - {roi}"
        sig_count_group = len(sig_freqs.get(roi, []))
        roi_comp = ratios.get(roi, RoiComputation(rows=[], sig_harmonics_group=sig_count_group, n_detected=0))
        roi_ratios = roi_comp.rows if sig_count_group or significance_mode == "individual" else []

        n_base_valid = sum(1 for entry in roi_ratios if entry.base_valid)
        n_outlier_excluded = sum(1 for entry in roi_ratios if entry.excluded_as_outlier)
        n_floor_excluded = sum(
            1 for entry in roi_ratios if entry.base_valid and not entry.include_in_summary and (entry.skip_reason or "") == "denom_below_floor"
        )
        n_used = sum(
            1 for entry in roi_ratios if entry.include_in_summary and _summary_metric_value(entry.ratio, entry.log_ratio, summary_metric) is not None
        )

        summary_metric_values = [
            _summary_metric_value(entry.ratio, entry.log_ratio, summary_metric)
            for entry in roi_ratios
            if entry.include_in_summary
        ]
        summary_metric_series = pd.Series([v for v in summary_metric_values if v is not None and np.isfinite(v)])
        n = int(summary_metric_series.count()) if not summary_metric_series.empty else 0
        mean = float(summary_metric_series.mean()) if n else np.nan
        median = float(summary_metric_series.median()) if n else np.nan
        std = float(summary_metric_series.std()) if n else np.nan
        variance = float(summary_metric_series.var()) if n else np.nan
        if mean is not None and not np.isnan(mean) and mean != 0:
            cv = float((std / mean) * 100) if std is not None else np.nan
        else:
            cv = np.nan
        min_val = float(summary_metric_series.min()) if n else np.nan
        max_val = float(summary_metric_series.max()) if n else np.nan

        ratio_used_series = pd.Series([entry.ratio for entry in roi_ratios if entry.include_in_summary and entry.ratio is not None])
        min_ratio = float(ratio_used_series.min()) if not ratio_used_series.empty else np.nan
        max_ratio = float(ratio_used_series.max()) if not ratio_used_series.empty else np.nan

        for entry in roi_ratios:
            rows.append(
                {
                    "Ratio Label": label,
                    "PID": entry.pid,
                    "SNR_A": entry.snr_a,
                    "SNR_B": entry.snr_b,
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
                    "SigHarmonics_N": entry.sig_count,
                    "DenomFloor": entry.denom_floor,
                    "N_detected": None,
                    "N_base_valid": None,
                    "N_outliers_excluded": None,
                    "N_floor_excluded": None,
                    "N_used": None,
                    "N": None,
                    "Mean": None,
                    "Median": None,
                    "Std": None,
                    "Variance": None,
                    "CV%": None,
                    "MeanRatio_fromLog": None,
                    "MedianRatio_fromLog": None,
                    "Min": None,
                    "Max": None,
                    "MinRatio": None,
                    "MaxRatio": None,
                }
            )

        sig_count_summary = sig_count_group or max((entry.sig_count for entry in roi_ratios), default=0)

        mean_ratio_from_log = float(np.exp(summary_metric_series.mean())) if summary_metric == "logratio" and n else np.nan
        median_ratio_from_log = float(np.exp(summary_metric_series.median())) if summary_metric == "logratio" and n else np.nan
        skip_for_summary = roi_comp.skip_reason or ""

        rows.append(
            {
                "Ratio Label": label,
                "PID": "SUMMARY",
                "SNR_A": None,
                "SNR_B": None,
                "SummaryA": None,
                "SummaryB": None,
                "Ratio": None,
                "LogRatio": None,
                "RatioPercent": None,
                "MetricUsed": None,
                "SkipReason": skip_for_summary,
                "IncludedInSummary": None,
                "OutlierFlag": None,
                "OutlierMethod": None,
                "OutlierScore": None,
                "ExcludedAsOutlier": None,
                "SigHarmonics_N": sig_count_summary,
                "DenomFloor": roi_ratios[0].denom_floor if roi_ratios else None,
                "N_detected": roi_comp.n_detected,
                "N_base_valid": n_base_valid,
                "N_outliers_excluded": n_outlier_excluded,
                "N_floor_excluded": n_floor_excluded,
                "N_used": n_used,
                "N": n,
                "Mean": mean,
                "Median": median,
                "Std": std,
                "Variance": variance,
                "CV%": cv if np.isfinite(cv) else np.nan,
                "MeanRatio_fromLog": mean_ratio_from_log if np.isfinite(mean_ratio_from_log) else np.nan,
                "MedianRatio_fromLog": median_ratio_from_log if np.isfinite(median_ratio_from_log) else np.nan,
                "Min": min_val,
                "Max": max_val,
                "MinRatio": min_ratio,
                "MaxRatio": max_ratio,
            }
        )
        rows.append({})

    columns = [
        "Ratio Label",
        "PID",
        "SNR_A",
        "SNR_B",
        "SummaryA",
        "SummaryB",
        "Ratio",
        "LogRatio",
        "RatioPercent",
        "MetricUsed",
        "SkipReason",
        "IncludedInSummary",
        "OutlierFlag",
        "OutlierMethod",
        "OutlierScore",
        "ExcludedAsOutlier",
        "SigHarmonics_N",
        "DenomFloor",
        "N_detected",
        "N_base_valid",
        "N_outliers_excluded",
        "N_floor_excluded",
        "N_used",
        "N",
        "Mean",
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
    ]
    return pd.DataFrame(rows, columns=columns)


def _write_excel(df: pd.DataFrame, output_path: Path, log_func: LogCallback) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with pd.ExcelWriter(output_path, engine="xlsxwriter") as writer:
            _auto_format_and_write_excel(writer, df, "Ratio Calculator", log_func)
    except Exception as exc:  # noqa: BLE001
        log_func(f"Failed to write Excel file: {exc}")
