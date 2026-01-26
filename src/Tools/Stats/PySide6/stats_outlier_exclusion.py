"""Outlier exclusion helpers for the Stats tool."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

import numpy as np
import pandas as pd

from Tools.Stats.Legacy.stats_export import _auto_format_and_write_excel
from Tools.Stats.PySide6.stats_qc_exclusion import (
    QC_REASON_MAXABS,
    QC_REASON_SUMABS,
    QcExclusionReport,
    format_qc_violation,
)

OUTLIER_REASON_LIMIT = "HARD_DV_LIMIT"
OUTLIER_REASON_NONFINITE = "DV_NONFINITE"
OUTLIER_REASON_MAD = "MAD_OUTLIER"

OUTLIER_REASON_FRIENDLY = {
    OUTLIER_REASON_LIMIT: "Exceeded hard cutoff (±{abs_limit:g} DV)",
    OUTLIER_REASON_MAD: "Unusually extreme compared to the group (robust rule)",
    OUTLIER_REASON_NONFINITE: "Non-finite DV value",
    QC_REASON_SUMABS: "QC sum(|BCA|) robust outlier (threshold {threshold_used:.2f})",
    QC_REASON_MAXABS: "QC max(|BCA|) robust outlier (threshold {threshold_used:.2f})",
}

OUTLIER_REASON_SENTENCE = {
    OUTLIER_REASON_LIMIT: "a value exceeded the hard cutoff (±{abs_limit:g} DV)",
    OUTLIER_REASON_MAD: "values were unusually extreme compared to the group (robust rule)",
    OUTLIER_REASON_NONFINITE: "a value was non-finite",
}


@dataclass(frozen=True)
class OutlierExclusionSummary:
    n_subjects_before: int
    n_subjects_excluded: int
    n_subjects_after: int
    abs_limit: float


@dataclass(frozen=True)
class OutlierParticipantReport:
    participant_id: str
    reasons: list[str]
    n_violations: int
    max_abs_dv: float
    worst_value: float
    worst_condition: str
    worst_roi: str
    robust_center: float | None = None
    robust_spread: float | None = None
    robust_score: float | None = None
    threshold_used: float | None = None
    trigger_harmonic_hz: float | None = None
    roi_mean_bca_at_trigger: float | None = None
    violations: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class OutlierExclusionReport:
    summary: OutlierExclusionSummary
    participants: list[
        OutlierParticipantReport
    ]
    qc_metadata: dict[str, object] | None = None


def _resolve_column_name(df: pd.DataFrame, candidates: Iterable[str], label: str) -> str:
    for name in candidates:
        if name in df.columns:
            return name
    raise KeyError(f"Missing required column for {label}: {', '.join(candidates)}")


def apply_hard_dv_exclusion(
    dv_long_df: pd.DataFrame,
    abs_limit: float,
    *,
    participant_col: str | None = None,
    condition_col: str | None = None,
    roi_col: str | None = None,
    value_col: str | None = None,
) -> tuple[pd.DataFrame, OutlierExclusionReport]:
    """Exclude entire participants when any DV cell exceeds a hard limit."""

    if dv_long_df is None or dv_long_df.empty:
        summary = OutlierExclusionSummary(0, 0, 0, float(abs_limit))
        return dv_long_df.copy(), OutlierExclusionReport(summary=summary, participants=[])

    participant_col = participant_col or _resolve_column_name(
        dv_long_df, ["participant_id", "subject", "pid"], "participant id"
    )
    condition_col = condition_col or _resolve_column_name(
        dv_long_df, ["condition"], "condition"
    )
    roi_col = roi_col or _resolve_column_name(dv_long_df, ["roi"], "roi")
    value_col = value_col or _resolve_column_name(
        dv_long_df, ["value", "dv"], "DV value"
    )

    df = dv_long_df.copy()
    values = df[value_col]
    finite_mask = np.isfinite(values.to_numpy())
    limit_mask = np.abs(values.to_numpy()) > float(abs_limit)
    violation_mask = ~finite_mask | limit_mask

    violations = df.loc[violation_mask].copy()
    excluded_pids = sorted(violations[participant_col].unique())

    filtered_df = df.loc[~df[participant_col].isin(excluded_pids)].copy()

    participants = []
    if excluded_pids:
        for pid in excluded_pids:
            pid_rows = df.loc[df[participant_col] == pid]
            pid_values = pid_rows[value_col].to_numpy()
            pid_finite = np.isfinite(pid_values)
            pid_limit = np.abs(pid_values) > float(abs_limit)
            pid_violation = (~pid_finite) | pid_limit
            pid_violations = pid_rows.loc[pid_violation].copy()

            reasons = []
            if np.any(~pid_finite):
                reasons.append(OUTLIER_REASON_NONFINITE)
            if np.any(pid_limit):
                reasons.append(OUTLIER_REASON_LIMIT)

            if pid_violations.empty:
                continue

            worst_scores = np.where(
                np.isfinite(pid_violations[value_col].to_numpy()),
                np.abs(pid_violations[value_col].to_numpy()),
                np.inf,
            )
            worst_idx = int(np.argmax(worst_scores))
            worst_row = pid_violations.iloc[worst_idx]

            finite_abs_values = np.abs(pid_values[pid_finite])
            max_abs_dv = float(finite_abs_values.max()) if finite_abs_values.size else float("nan")

            participants.append(
                OutlierParticipantReport(
                    participant_id=str(pid),
                    reasons=reasons,
                    n_violations=int(pid_violations.shape[0]),
                    max_abs_dv=max_abs_dv,
                    worst_value=float(worst_row[value_col]),
                    worst_condition=str(worst_row[condition_col]),
                    worst_roi=str(worst_row[roi_col]),
                    violations=[f"DV cells={int(pid_violations.shape[0])}"],
                )
            )

    summary = OutlierExclusionSummary(
        n_subjects_before=int(df[participant_col].nunique()),
        n_subjects_excluded=len(excluded_pids),
        n_subjects_after=int(filtered_df[participant_col].nunique()),
        abs_limit=float(abs_limit),
    )

    return filtered_df, OutlierExclusionReport(summary=summary, participants=participants)


def format_outlier_reason(
    reason: str,
    *,
    abs_limit: float | None = None,
    threshold_used: float | None = None,
) -> str:
    if reason == OUTLIER_REASON_LIMIT:
        limit = abs_limit if abs_limit is not None else 0.0
        return OUTLIER_REASON_FRIENDLY[reason].format(abs_limit=limit)
    if reason in (QC_REASON_SUMABS, QC_REASON_MAXABS):
        threshold = threshold_used if threshold_used is not None else 0.0
        return OUTLIER_REASON_FRIENDLY[reason].format(threshold_used=threshold)
    if reason in OUTLIER_REASON_FRIENDLY:
        return OUTLIER_REASON_FRIENDLY[reason]
    return str(reason)


def _format_reason_sentence(reason: str, *, abs_limit: float) -> str:
    if reason == OUTLIER_REASON_LIMIT:
        return OUTLIER_REASON_SENTENCE[reason].format(abs_limit=abs_limit)
    if reason in OUTLIER_REASON_SENTENCE:
        return OUTLIER_REASON_SENTENCE[reason]
    return str(reason)


def _join_reason_sentences(clauses: list[str]) -> str:
    if not clauses:
        return "an outlier value was detected"
    if len(clauses) == 1:
        return clauses[0]
    if len(clauses) == 2:
        return f"{clauses[0]} and {clauses[1]}"
    return ", ".join(clauses[:-1]) + f", and {clauses[-1]}"


def report_to_dataframe(report: OutlierExclusionReport) -> pd.DataFrame:
    rows = []
    for item in report.participants:
        reasons = list(item.reasons)
        violation_text = "; ".join(item.violations) if item.violations else ""
        rows.append(
            {
                "participant_id": item.participant_id,
                "exclusion_reason": ", ".join(reasons),
                "worst_value": item.worst_value,
                "worst_condition": item.worst_condition,
                "worst_roi": item.worst_roi,
                "robust_center": item.robust_center,
                "robust_spread": item.robust_spread,
                "robust_score": item.robust_score,
                "threshold_used": item.threshold_used,
                "trigger_harmonic_hz": item.trigger_harmonic_hz,
                "roi_mean_bca_at_trigger": item.roi_mean_bca_at_trigger,
                "violations": violation_text,
                "max_abs_dv": item.max_abs_dv,
            }
        )
    return pd.DataFrame(rows)


def build_outlier_summary_text(report: OutlierExclusionReport) -> str:
    summary = report.summary
    abs_limit = float(summary.abs_limit)
    lines = [
        "QC screened all conditions/ROIs in the project, independent of selections.",
        "Outlier Exclusion Summary",
        f"Participants excluded: {summary.n_subjects_excluded} (of {summary.n_subjects_before})",
    ]
    if not report.participants:
        lines.append("No participants were excluded.")
        return "\n".join(lines)

    for participant in report.participants:
        reason_clauses = []
        for reason in participant.reasons:
            if reason in (QC_REASON_SUMABS, QC_REASON_MAXABS):
                if participant.robust_score is not None and participant.threshold_used is not None:
                    reason_clauses.append(
                        "QC screening flagged extreme values (robust score "
                        f"{participant.robust_score:.2f} > {participant.threshold_used:.2f})"
                    )
                else:
                    reason_clauses.append("QC screening flagged extreme values")
            else:
                reason_clauses.append(_format_reason_sentence(reason, abs_limit=abs_limit))
        reason_sentence = _join_reason_sentences(reason_clauses)
        worst_value = participant.worst_value
        if np.isfinite(worst_value):
            worst_text = f"{worst_value:.2f}"
        else:
            worst_text = "non-finite"
        lines.append(
            f"{participant.participant_id} was excluded as an outlier because {reason_sentence}. "
            f"Worst value: {worst_text} DV ({participant.worst_condition}, {participant.worst_roi})."
        )

    return "\n".join(lines)


def summary_to_dataframe(report: OutlierExclusionReport) -> pd.DataFrame:
    summary = report.summary
    return pd.DataFrame(
        [
            {
                "n_subjects_before": summary.n_subjects_before,
                "n_subjects_excluded": summary.n_subjects_excluded,
                "n_subjects_after": summary.n_subjects_after,
                "abs_limit": summary.abs_limit,
            }
        ]
    )


def export_outlier_exclusion_report(
    save_path: str | bytes | "os.PathLike[str]",
    report: OutlierExclusionReport,
    log_func,
) -> None:
    summary_df = summary_to_dataframe(report)
    participants_df = report_to_dataframe(report)
    with pd.ExcelWriter(save_path, engine="xlsxwriter") as writer:
        _auto_format_and_write_excel(writer, summary_df, "Summary", log_func)
        _auto_format_and_write_excel(writer, participants_df, "Excluded Participants", log_func)


def merge_exclusion_reports(
    dv_report: OutlierExclusionReport,
    qc_report: QcExclusionReport | None,
) -> OutlierExclusionReport:
    if qc_report is None:
        return dv_report

    participants_map = {p.participant_id: p for p in dv_report.participants}

    for qc_participant in qc_report.participants:
        qc_violations = [format_qc_violation(v) for v in qc_participant.violations]
        qc_entry = OutlierParticipantReport(
            participant_id=qc_participant.participant_id,
            reasons=qc_participant.reasons,
            n_violations=qc_participant.n_violations,
            max_abs_dv=float("nan"),
            worst_value=qc_participant.worst_value,
            worst_condition=qc_participant.worst_condition,
            worst_roi=qc_participant.worst_roi,
            robust_center=qc_participant.robust_center,
            robust_spread=qc_participant.robust_spread,
            robust_score=qc_participant.robust_score,
            threshold_used=qc_participant.threshold_used,
            trigger_harmonic_hz=qc_participant.trigger_harmonic_hz,
            roi_mean_bca_at_trigger=qc_participant.roi_mean_bca_at_trigger,
            violations=qc_violations,
        )

        existing = participants_map.get(qc_participant.participant_id)
        if existing is None:
            participants_map[qc_participant.participant_id] = qc_entry
            continue

        combined_reasons = sorted(set(existing.reasons + qc_entry.reasons))
        combined_violations = list(existing.violations) + qc_entry.violations
        combined_n_violations = existing.n_violations + qc_entry.n_violations
        use_qc_worst = bool(qc_entry.reasons)
        participants_map[qc_participant.participant_id] = OutlierParticipantReport(
            participant_id=qc_participant.participant_id,
            reasons=combined_reasons,
            n_violations=combined_n_violations,
            max_abs_dv=existing.max_abs_dv,
            worst_value=qc_entry.worst_value if use_qc_worst else existing.worst_value,
            worst_condition=qc_entry.worst_condition if use_qc_worst else existing.worst_condition,
            worst_roi=qc_entry.worst_roi if use_qc_worst else existing.worst_roi,
            robust_center=qc_entry.robust_center if use_qc_worst else existing.robust_center,
            robust_spread=qc_entry.robust_spread if use_qc_worst else existing.robust_spread,
            robust_score=qc_entry.robust_score if use_qc_worst else existing.robust_score,
            threshold_used=qc_entry.threshold_used if use_qc_worst else existing.threshold_used,
            trigger_harmonic_hz=qc_entry.trigger_harmonic_hz
            if use_qc_worst
            else existing.trigger_harmonic_hz,
            roi_mean_bca_at_trigger=qc_entry.roi_mean_bca_at_trigger
            if use_qc_worst
            else existing.roi_mean_bca_at_trigger,
            violations=combined_violations,
        )

    combined_participants = sorted(participants_map.values(), key=lambda p: p.participant_id)
    n_before = max(
        dv_report.summary.n_subjects_before,
        qc_report.summary.n_subjects_before,
    )
    n_excluded = len({p.participant_id for p in combined_participants})
    summary = OutlierExclusionSummary(
        n_subjects_before=n_before,
        n_subjects_excluded=n_excluded,
        n_subjects_after=max(0, n_before - n_excluded),
        abs_limit=float(dv_report.summary.abs_limit),
    )
    qc_metadata = {
        "screened_conditions": qc_report.screened_conditions,
        "screened_rois": qc_report.screened_rois,
        "threshold_sumabs": qc_report.summary.threshold_sumabs,
        "threshold_maxabs": qc_report.summary.threshold_maxabs,
    }
    return OutlierExclusionReport(
        summary=summary,
        participants=combined_participants,
        qc_metadata=qc_metadata,
    )
