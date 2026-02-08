"""QC exclusion helpers for the Stats tool."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd

from Tools.Stats.Legacy.excel_io import safe_read_excel
from Tools.Stats.Legacy.stats_analysis import (
    SUMMED_BCA_ODDBALL_EVERY_N_DEFAULT,
    _match_freq_column,
    filter_to_oddball_harmonics,
    get_included_freqs,
)

logger = logging.getLogger("Tools.Stats")

QC_REASON_SUMABS = "QC_SUMABS"
QC_REASON_MAXABS = "QC_MAXABS"

QC_SEVERITY_WARNING = "WARNING"
QC_SEVERITY_CRITICAL = "CRITICAL"

QC_METRIC_LABELS = {
    QC_REASON_SUMABS: "Unusually large total response",
    QC_REASON_MAXABS: "Unusually large peak response",
}

# Conservative defaults to reduce false positives; these values are reported in exports.
QC_DEFAULT_WARN_THRESHOLD = 6.0
QC_DEFAULT_CRITICAL_THRESHOLD = 10.0

# Absolute floors per metric ensure very small QC metrics do not trigger flags even if robust scores spike.
# These defaults are tuned to typical summed/peak BCA scales (µV) observed in the Stats tool.
QC_DEFAULT_WARN_ABS_FLOOR_SUMABS = 5.0
QC_DEFAULT_CRITICAL_ABS_FLOOR_SUMABS = 10.0
QC_DEFAULT_WARN_ABS_FLOOR_MAXABS = 1.0
QC_DEFAULT_CRITICAL_ABS_FLOOR_MAXABS = 2.0


@dataclass(frozen=True)
class QcViolation:
    condition: str
    roi: str
    metric: str
    severity: str
    value: float
    robust_center: float
    robust_spread: float
    robust_score: float
    threshold_used: float
    abs_floor_used: float
    trigger_harmonic_hz: Optional[float] = None
    roi_mean_bca_at_trigger: Optional[float] = None


@dataclass(frozen=True)
class QcParticipantReport:
    participant_id: str
    reasons: list[str]
    n_violations: int
    worst_value: float
    worst_condition: str
    worst_roi: str
    worst_metric: str
    robust_center: float
    robust_spread: float
    robust_score: float
    threshold_used: float
    trigger_harmonic_hz: Optional[float]
    roi_mean_bca_at_trigger: Optional[float]
    violations: list[QcViolation]


@dataclass(frozen=True)
class QcExclusionSummary:
    n_subjects_before: int
    n_subjects_flagged: int
    n_subjects_after: int
    warn_threshold: float
    critical_threshold: float
    warn_abs_floor_sumabs: float
    critical_abs_floor_sumabs: float
    warn_abs_floor_maxabs: float
    critical_abs_floor_maxabs: float


@dataclass(frozen=True)
class QcExclusionReport:
    summary: QcExclusionSummary
    participants: list[QcParticipantReport]
    screened_conditions: list[str]
    screened_rois: list[str]


def format_qc_violation(violation: QcViolation) -> str:
    label = QC_METRIC_LABELS.get(violation.metric, str(violation.metric))
    lines = [
        f"{label} — {violation.severity}",
        f"Condition: {violation.condition}, ROI: {violation.roi}, value: {violation.value:.4f}",
        (
            f"Robust score: {violation.robust_score:.3f} "
            f"(threshold {violation.threshold_used:.2f}, abs floor {violation.abs_floor_used:.2f})"
        ),
        (
            f"Robust center: {violation.robust_center:.4f}, "
            f"robust spread: {violation.robust_spread:.4f}"
        ),
    ]
    if violation.trigger_harmonic_hz is not None:
        lines.append(
            "Trigger harmonic: "
            f"{violation.trigger_harmonic_hz:.3f} Hz, "
            f"mean BCA at trigger: {violation.roi_mean_bca_at_trigger:.4f}"
        )
    return "\n".join(lines)


def qc_metric_label(metric: str) -> str:
    return QC_METRIC_LABELS.get(metric, str(metric))


def _log_message(log_func: Optional[Callable[[str], None]], message: str) -> None:
    if log_func:
        log_func(message)
    else:
        logger.info(message)


def _build_qc_harmonic_domain(
    columns: Iterable[object],
    base_freq: float,
    log_func: Optional[Callable[[str], None]],
) -> list[float]:
    freq_candidates = get_included_freqs(base_freq, columns, lambda m: _log_message(log_func, m))
    if not freq_candidates:
        return []
    oddball_list = filter_to_oddball_harmonics(
        freq_candidates,
        base_freq,
        every_n=SUMMED_BCA_ODDBALL_EVERY_N_DEFAULT,
        tol=1e-3,
    )
    return [freq for freq, _k in oddball_list]


def _robust_center_spread(values: np.ndarray) -> tuple[float, float]:
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return float("nan"), float("nan")
    center = float(np.median(finite))
    mad = float(np.median(np.abs(finite - center)))
    if mad > 0:
        return center, float(1.4826 * mad)
    q1, q3 = np.percentile(finite, [25, 75])
    iqr = float(q3 - q1)
    if iqr > 0:
        return center, float(0.7413 * iqr)
    return center, 0.0


def _robust_score(value: float, center: float, spread: float) -> float:
    if not np.isfinite(value):
        return float("nan")
    if spread > 0:
        return (value - center) / spread
    if not np.isfinite(center):
        return float("nan")
    if value == center:
        return 0.0
    # Fallback for zero spread: any deviation from the center is treated as extreme.
    return float("inf") if value > center else float("-inf")


def _qc_severity(
    *,
    score: float,
    value: float,
    warn_threshold: float,
    critical_threshold: float,
    warn_abs_floor: float,
    critical_abs_floor: float,
) -> tuple[str | None, float | None]:
    if not np.isfinite(score) or not np.isfinite(value):
        return None, None
    if score >= critical_threshold and value >= critical_abs_floor:
        return QC_SEVERITY_CRITICAL, critical_abs_floor
    if score >= warn_threshold and value >= warn_abs_floor:
        return QC_SEVERITY_WARNING, warn_abs_floor
    return None, None


def run_qc_exclusion(
    *,
    subjects: list[str],
    subject_data: Dict[str, Dict[str, str]],
    conditions_all: list[str],
    rois_all: Dict[str, List[str]],
    base_freq: float,
    warn_threshold: float = QC_DEFAULT_WARN_THRESHOLD,
    critical_threshold: float = QC_DEFAULT_CRITICAL_THRESHOLD,
    warn_abs_floor_sumabs: float = QC_DEFAULT_WARN_ABS_FLOOR_SUMABS,
    critical_abs_floor_sumabs: float = QC_DEFAULT_CRITICAL_ABS_FLOOR_SUMABS,
    warn_abs_floor_maxabs: float = QC_DEFAULT_WARN_ABS_FLOOR_MAXABS,
    critical_abs_floor_maxabs: float = QC_DEFAULT_CRITICAL_ABS_FLOOR_MAXABS,
    log_func: Optional[Callable[[str], None]] = None,
) -> QcExclusionReport:
    screened_conditions = list(conditions_all or [])
    if not screened_conditions:
        screened_conditions = sorted(
            {
                cond
                for subj in subject_data.values()
                for cond in (subj or {}).keys()
            },
            key=repr,
        )
    screened_rois = sorted(rois_all.keys()) if isinstance(rois_all, dict) else []

    _log_message(
        log_func,
        "QC screening all conditions/ROIs in the project (independent of selections)…",
    )
    logger.info(
        "stats_qc_screen_start",
        extra={
            "n_subjects": len(subjects),
            "n_conditions": len(screened_conditions),
            "n_rois": len(screened_rois),
        },
    )

    qc_values: dict[tuple[str, str], dict[str, dict[str, object]]] = {}

    for pid in subjects:
        for cond_name in screened_conditions:
            file_path = subject_data.get(pid, {}).get(cond_name)
            if not file_path:
                _log_message(log_func, f"QC: Missing file for {pid} {cond_name}: {file_path}")
                continue
            if not Path(file_path).exists():
                _log_message(log_func, f"QC: Missing file for {pid} {cond_name}: {file_path}")
                continue
            try:
                df_bca = safe_read_excel(file_path, sheet_name="BCA (uV)", index_col="Electrode")
            except Exception as exc:  # noqa: BLE001
                _log_message(log_func, f"QC: Failed to read BCA sheet from {file_path}: {exc}")
                continue

            df_bca.index = df_bca.index.astype(str).str.upper().str.strip()
            harmonic_freqs = _build_qc_harmonic_domain(df_bca.columns, base_freq, log_func)
            if not harmonic_freqs:
                _log_message(
                    log_func,
                    f"QC: No harmonic columns found for {pid} {cond_name}; skipping.",
                )
                continue
            col_map = {freq: _match_freq_column(df_bca.columns, freq) for freq in harmonic_freqs}

            for roi_name, roi_channels in (rois_all or {}).items():
                roi_chans = [
                    str(ch).strip().upper()
                    for ch in (roi_channels or [])
                    if str(ch).strip().upper() in df_bca.index
                ]
                if not roi_chans:
                    _log_message(
                        log_func,
                        f"QC: No overlapping BCA data for ROI {roi_name} in {file_path}.",
                    )
                    continue
                df_roi = df_bca.loc[roi_chans].dropna(how="all")
                if df_roi.empty:
                    _log_message(log_func, f"QC: No BCA data for ROI {roi_name} in {file_path}.")
                    continue

                mean_values: list[float] = []
                max_abs_value = float("nan")
                max_abs_freq: Optional[float] = None
                max_abs_raw: Optional[float] = None

                for freq_val in harmonic_freqs:
                    col_bca = col_map.get(freq_val)
                    if not col_bca:
                        continue
                    series = pd.to_numeric(df_roi[col_bca], errors="coerce").replace(
                        [np.inf, -np.inf], np.nan
                    )
                    mean_val = float(series.mean(skipna=True))
                    if not np.isfinite(mean_val):
                        continue
                    mean_values.append(mean_val)
                    abs_val = abs(mean_val)
                    if not np.isfinite(max_abs_value) or abs_val > max_abs_value:
                        max_abs_value = abs_val
                        max_abs_freq = float(freq_val)
                        max_abs_raw = mean_val

                if not mean_values:
                    _log_message(
                        log_func,
                        f"QC: No finite harmonic means for {pid} {cond_name} {roi_name}.",
                    )
                    continue

                qc_sumabs = float(np.sum(np.abs(mean_values)))
                qc_maxabs = float(max_abs_value)
                cell_key = (cond_name, roi_name)
                pid_entry = qc_values.setdefault(cell_key, {}).setdefault(pid, {})
                pid_entry["sumabs"] = qc_sumabs
                pid_entry["maxabs"] = qc_maxabs
                pid_entry["maxabs_freq"] = max_abs_freq
                pid_entry["maxabs_raw"] = max_abs_raw

    participants: list[QcParticipantReport] = []
    flagged_ids: set[str] = set()

    for (cond_name, roi_name), pid_map in qc_values.items():
        pids = sorted(pid_map.keys())
        sumabs_values = np.array(
            [pid_map[pid].get("sumabs", float("nan")) for pid in pids], dtype=float
        )
        maxabs_values = np.array(
            [pid_map[pid].get("maxabs", float("nan")) for pid in pids], dtype=float
        )
        sumabs_center, sumabs_spread = _robust_center_spread(sumabs_values)
        maxabs_center, maxabs_spread = _robust_center_spread(maxabs_values)

        for idx, pid in enumerate(pids):
            violations: list[QcViolation] = []

            sumabs_value = float(sumabs_values[idx])
            sumabs_score = _robust_score(sumabs_value, sumabs_center, sumabs_spread)
            severity, abs_floor = _qc_severity(
                score=sumabs_score,
                value=sumabs_value,
                warn_threshold=warn_threshold,
                critical_threshold=critical_threshold,
                warn_abs_floor=warn_abs_floor_sumabs,
                critical_abs_floor=critical_abs_floor_sumabs,
            )
            if severity:
                violations.append(
                    QcViolation(
                        condition=cond_name,
                        roi=roi_name,
                        metric=QC_REASON_SUMABS,
                        severity=severity,
                        value=sumabs_value,
                        robust_center=sumabs_center,
                        robust_spread=sumabs_spread,
                        robust_score=sumabs_score,
                        threshold_used=critical_threshold
                        if severity == QC_SEVERITY_CRITICAL
                        else warn_threshold,
                        abs_floor_used=abs_floor if abs_floor is not None else 0.0,
                    )
                )

            maxabs_value = float(maxabs_values[idx])
            maxabs_score = _robust_score(maxabs_value, maxabs_center, maxabs_spread)
            severity, abs_floor = _qc_severity(
                score=maxabs_score,
                value=maxabs_value,
                warn_threshold=warn_threshold,
                critical_threshold=critical_threshold,
                warn_abs_floor=warn_abs_floor_maxabs,
                critical_abs_floor=critical_abs_floor_maxabs,
            )
            if severity:
                meta = pid_map[pid]
                violations.append(
                    QcViolation(
                        condition=cond_name,
                        roi=roi_name,
                        metric=QC_REASON_MAXABS,
                        severity=severity,
                        value=maxabs_value,
                        robust_center=maxabs_center,
                        robust_spread=maxabs_spread,
                        robust_score=maxabs_score,
                        threshold_used=critical_threshold
                        if severity == QC_SEVERITY_CRITICAL
                        else warn_threshold,
                        abs_floor_used=abs_floor if abs_floor is not None else 0.0,
                        trigger_harmonic_hz=meta.get("maxabs_freq"),
                        roi_mean_bca_at_trigger=meta.get("maxabs_raw"),
                    )
                )

            if not violations:
                continue

            flagged_ids.add(pid)
            existing = next((p for p in participants if p.participant_id == pid), None)
            if existing:
                combined = list(existing.violations) + violations
                worst = max(combined, key=lambda v: abs(v.value))
                reasons = sorted(set(existing.reasons + [v.metric for v in violations]))
                trigger_hz = existing.trigger_harmonic_hz
                trigger_val = existing.roi_mean_bca_at_trigger
                maxabs_candidates = [v for v in combined if v.metric == QC_REASON_MAXABS]
                if maxabs_candidates:
                    maxabs_worst = max(maxabs_candidates, key=lambda v: abs(v.value))
                    trigger_hz = maxabs_worst.trigger_harmonic_hz
                    trigger_val = maxabs_worst.roi_mean_bca_at_trigger
                participants.remove(existing)
                participants.append(
                    QcParticipantReport(
                        participant_id=pid,
                        reasons=reasons,
                        n_violations=len(combined),
                        worst_value=worst.value,
                        worst_condition=worst.condition,
                        worst_roi=worst.roi,
                        worst_metric=worst.metric,
                        robust_center=worst.robust_center,
                        robust_spread=worst.robust_spread,
                        robust_score=worst.robust_score,
                        threshold_used=worst.threshold_used,
                        trigger_harmonic_hz=trigger_hz,
                        roi_mean_bca_at_trigger=trigger_val,
                        violations=combined,
                    )
                )
            else:
                worst = max(violations, key=lambda v: abs(v.value))
                maxabs_candidates = [v for v in violations if v.metric == QC_REASON_MAXABS]
                trigger_hz = worst.trigger_harmonic_hz
                trigger_val = worst.roi_mean_bca_at_trigger
                if maxabs_candidates:
                    maxabs_worst = max(maxabs_candidates, key=lambda v: abs(v.value))
                    trigger_hz = maxabs_worst.trigger_harmonic_hz
                    trigger_val = maxabs_worst.roi_mean_bca_at_trigger
                participants.append(
                    QcParticipantReport(
                        participant_id=pid,
                        reasons=sorted({v.metric for v in violations}),
                        n_violations=len(violations),
                        worst_value=worst.value,
                        worst_condition=worst.condition,
                        worst_roi=worst.roi,
                        worst_metric=worst.metric,
                        robust_center=worst.robust_center,
                        robust_spread=worst.robust_spread,
                        robust_score=worst.robust_score,
                        threshold_used=worst.threshold_used,
                        trigger_harmonic_hz=trigger_hz,
                        roi_mean_bca_at_trigger=trigger_val,
                        violations=violations,
                    )
                )

    participants = sorted(participants, key=lambda p: p.participant_id)
    summary = QcExclusionSummary(
        n_subjects_before=len(subjects),
        n_subjects_flagged=len(flagged_ids),
        n_subjects_after=len(subjects),
        warn_threshold=float(warn_threshold),
        critical_threshold=float(critical_threshold),
        warn_abs_floor_sumabs=float(warn_abs_floor_sumabs),
        critical_abs_floor_sumabs=float(critical_abs_floor_sumabs),
        warn_abs_floor_maxabs=float(warn_abs_floor_maxabs),
        critical_abs_floor_maxabs=float(critical_abs_floor_maxabs),
    )
    report = QcExclusionReport(
        summary=summary,
        participants=participants,
        screened_conditions=screened_conditions,
        screened_rois=screened_rois,
    )
    logger.info(
        "stats_qc_screen_complete",
        extra={
            "n_subjects": len(subjects),
            "n_flagged": len(flagged_ids),
            "n_conditions": len(screened_conditions),
            "n_rois": len(screened_rois),
        },
    )
    return report
