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
    sig_count: int
    metric_used: str
    skip_reason: str | None = None
    include_in_summary: bool = True
    outlier_flag: bool = False
    outlier_method: str | None = None
    outlier_score: float | None = None
    snr_a: float | None = None
    snr_b: float | None = None


@dataclass
class RatioCalcSummaryCounts:
    participants_total: int = 0
    participants_used_per_roi: dict[str, int] = field(default_factory=dict)
    skipped_denominator_zero: int = 0
    skipped_missing: int = 0
    skipped_nonpositive_bca: int = 0
    outliers_flagged_per_roi: dict[str, int] = field(default_factory=dict)


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
    ratios = _compute_ratio_table(
        participants_seq, rois, sig_freqs, sig_freqs_by_pid, inputs, log_warning, summary_counts
    )
    _apply_outlier_detection(ratios, inputs, log_warning, summary_counts)
    summary_counts.participants_used_per_roi = _participants_used(ratios, inputs.outlier_action)
    _emit(progress_cb, 85)

    df = _build_output_frame(
        ratios,
        selected_roi_names,
        sig_freqs,
        inputs.cond_a,
        inputs.cond_b,
        inputs.significance_mode,
        inputs.outlier_action,
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
) -> dict[str, list[RatioRow]]:
    ratios: dict[str, list[RatioRow]] = {roi.name: [] for roi in rois}
    metric_label = "BCA" if inputs.metric == "bca" else "SNR"
    for part in participants:
        metric_a = _load_metric_data(part.cond_a_file, rois, log_warning, part.pid, inputs.metric)
        metric_b = _load_metric_data(part.cond_b_file, rois, log_warning, part.pid, inputs.metric)

        for roi in rois:
            if inputs.significance_mode == "individual" and individual_sig_freqs is not None:
                freqs = individual_sig_freqs.get(roi.name, {}).get(part.pid, [])
            else:
                freqs = sig_freqs.get(roi.name, [])
            if not freqs:
                log_warning(f"No significant harmonics for ROI {roi.name}; skipping ratios.")
                continue

            summary_a = _summary_for_roi(metric_a.get(roi.name), freqs, inputs.metric, inputs.bca_negative_mode)
            summary_b = _summary_for_roi(metric_b.get(roi.name), freqs, inputs.metric, inputs.bca_negative_mode)

            if summary_a is None or summary_b is None:
                summary_counts.skipped_missing += 1
                log_warning(f"Missing ROI data for participant {part.pid} in ROI {roi.name}; skipping participant.")
                continue

            skip_reason: str | None = None
            include_in_summary = True

            if inputs.metric == "bca" and inputs.bca_negative_mode == "strict":
                if summary_a <= 0 or summary_b <= 0:
                    skip_reason = "Non-positive BCA sum"
                    include_in_summary = False
                    summary_counts.skipped_nonpositive_bca += 1
                    log_warning(f"Non-positive BCA sum for participant {part.pid} ROI {roi.name}; skipping ratio.")
                    if summary_b == 0:
                        summary_counts.skipped_denominator_zero += 1

            if skip_reason is None and summary_b == 0:
                summary_counts.skipped_denominator_zero += 1
                log_warning(f"Denominator {metric_label} is zero for participant {part.pid} ROI {roi.name}; skipping participant.")
                if inputs.metric == "bca":
                    skip_reason = "Denominator zero"
                    include_in_summary = False
                else:
                    continue

            ratio_value = None if skip_reason else summary_a / summary_b
            ratios.setdefault(roi.name, []).append(
                RatioRow(
                    pid=part.pid,
                    summary_a=summary_a,
                    summary_b=summary_b,
                    ratio=ratio_value,
                    sig_count=len(freqs),
                    metric_used=metric_label,
                    skip_reason=skip_reason,
                    include_in_summary=include_in_summary,
                    snr_a=summary_a,
                    snr_b=summary_b,
                )
            )
    return ratios


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


def _apply_outlier_detection(
    ratios: dict[str, list[RatioRow]],
    inputs: RatioCalcInputs,
    log_warning: LogCallback,
    summary_counts: RatioCalcSummaryCounts,
) -> None:
    if not inputs.outlier_enabled:
        return
    for roi_name, rows in ratios.items():
        valid_indices = [idx for idx, row in enumerate(rows) if row.ratio is not None and np.isfinite(row.ratio)]
        if len(valid_indices) < 5:
            log_warning(f"Outlier detection skipped for ROI {roi_name}: fewer than 5 valid ratios.")
            continue
        values = np.array([rows[idx].ratio for idx in valid_indices], dtype=float)
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
                rows[idx].outlier_method = method_label
                rows[idx].outlier_score = float(score)
                rows[idx].outlier_flag = bool(flag)
                if flag:
                    summary_counts.outliers_flagged_per_roi[roi_name] = (
                        summary_counts.outliers_flagged_per_roi.get(roi_name, 0) + 1
                    )
                    if inputs.outlier_action == "exclude":
                        rows[idx].include_in_summary = False
        else:
            q1 = float(np.nanpercentile(values, 25))
            q3 = float(np.nanpercentile(values, 75))
            iqr = q3 - q1
            lower = q1 - inputs.outlier_threshold * iqr
            upper = q3 + inputs.outlier_threshold * iqr
            method_label = "IQR"
            for idx, val in zip(valid_indices, values):
                score = np.nan
                flag = False
                if val < lower:
                    score = val - lower
                    flag = True
                elif val > upper:
                    score = val - upper
                    flag = True
                rows[idx].outlier_method = method_label
                rows[idx].outlier_score = float(score) if score == score else np.nan
                rows[idx].outlier_flag = flag
                if flag:
                    summary_counts.outliers_flagged_per_roi[roi_name] = (
                        summary_counts.outliers_flagged_per_roi.get(roi_name, 0) + 1
                    )
                    if inputs.outlier_action == "exclude":
                        rows[idx].include_in_summary = False


def _participants_used(ratios: dict[str, list[RatioRow]], outlier_action: str) -> dict[str, int]:
    usage: dict[str, int] = {}
    for roi_name, rows in ratios.items():
        usage[roi_name] = sum(
            1
            for row in rows
            if row.ratio is not None and (row.include_in_summary or outlier_action != "exclude")
        )
    return usage


def _build_output_frame(
    ratios: dict[str, list[RatioRow]],
    roi_filter: list[str],
    sig_freqs: dict[str, list[float]],
    cond_a: str,
    cond_b: str,
    significance_mode: str,
    outlier_action: str,
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
                    "SummaryA": entry.summary_a,
                    "SummaryB": entry.summary_b,
                    "Ratio": entry.ratio,
                    "MetricUsed": entry.metric_used,
                    "SkipReason": entry.skip_reason or "",
                    "OutlierFlag": bool(entry.outlier_flag),
                    "OutlierMethod": entry.outlier_method or "",
                    "OutlierScore": entry.outlier_score,
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

        ratio_values = [
            entry.ratio
            for entry in roi_ratios
            if entry.ratio is not None and (entry.include_in_summary or outlier_action != "exclude")
        ]
        ratio_series = pd.Series(ratio_values)
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
                "SummaryA": None,
                "SummaryB": None,
                "Ratio": None,
                "MetricUsed": None,
                "SkipReason": "",
                "OutlierFlag": None,
                "OutlierMethod": None,
                "OutlierScore": None,
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
        "SummaryA",
        "SummaryB",
        "Ratio",
        "MetricUsed",
        "SkipReason",
        "OutlierFlag",
        "OutlierMethod",
        "OutlierScore",
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
