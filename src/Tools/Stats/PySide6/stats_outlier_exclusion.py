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

OUTLIER_REASON_LIMIT = "DV_HARD_LIMIT"
OUTLIER_REASON_NONFINITE = "REQUIRED_EXCLUSION_NONFINITE"
OUTLIER_REASON_MAD = "MAD_OUTLIER"
OUTLIER_REASON_MANUAL = "MANUAL"

OUTLIER_REASON_FRIENDLY = {
    OUTLIER_REASON_LIMIT: "Exceeded hard cutoff (±{abs_limit:g} DV)",
    OUTLIER_REASON_MAD: "Unusually extreme compared to the group (robust rule)",
    OUTLIER_REASON_NONFINITE: "Required exclusion: non-finite DV value",
    OUTLIER_REASON_MANUAL: "Manually excluded",
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
    n_subjects_flagged: int = 0
    n_subjects_required_excluded: int = 0


@dataclass(frozen=True)
class DvViolation:
    participant_id: str
    condition: str
    roi: str
    value: float
    reason: str


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
    dv_violations: list[DvViolation] = field(default_factory=list)
    required_exclusion: bool = False


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
    """Flag DV outliers, excluding only participants with non-finite values."""

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
    flagged_pids = sorted(violations[participant_col].unique())
    required_exclusions = sorted(
        df.loc[~finite_mask, participant_col].dropna().unique().tolist()
    )

    filtered_df = df.loc[~df[participant_col].isin(required_exclusions)].copy()

    participants = []
    if flagged_pids:
        for pid in flagged_pids:
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
            dv_violations = [
                DvViolation(
                    participant_id=str(pid),
                    condition=str(row[condition_col]),
                    roi=str(row[roi_col]),
                    value=float(row[value_col]),
                    reason=OUTLIER_REASON_NONFINITE
                    if not np.isfinite(float(row[value_col]))
                    else OUTLIER_REASON_LIMIT,
                )
                for _, row in pid_violations.iterrows()
            ]

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
                    dv_violations=dv_violations,
                    required_exclusion=str(pid) in required_exclusions,
                )
            )

    summary = OutlierExclusionSummary(
        n_subjects_before=int(df[participant_col].nunique()),
        n_subjects_excluded=len(required_exclusions),
        n_subjects_after=int(filtered_df[participant_col].nunique()),
        abs_limit=float(abs_limit),
        n_subjects_flagged=len(flagged_pids),
        n_subjects_required_excluded=len(required_exclusions),
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
                "required_exclusion": item.required_exclusion,
            }
        )
    return pd.DataFrame(rows)


def build_outlier_summary_text(report: OutlierExclusionReport) -> str:
    summary = report.summary
    abs_limit = float(summary.abs_limit)
    lines = [
        "QC screened all conditions/ROIs in the project, independent of selections.",
        "Outlier Flag Summary",
        f"Participants flagged: {summary.n_subjects_flagged} (of {summary.n_subjects_before})",
        f"Required exclusions (non-finite DV): {summary.n_subjects_required_excluded}",
    ]
    if not report.participants:
        lines.append("No participants were flagged.")
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
            f"{participant.participant_id} was flagged because {reason_sentence}. "
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
                "n_subjects_flagged": summary.n_subjects_flagged,
                "n_subjects_required_excluded": summary.n_subjects_required_excluded,
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
    n_flagged = len({p.participant_id for p in combined_participants})
    n_required = dv_report.summary.n_subjects_required_excluded
    summary = OutlierExclusionSummary(
        n_subjects_before=n_before,
        n_subjects_excluded=n_required,
        n_subjects_after=max(0, n_before - n_required),
        abs_limit=float(dv_report.summary.abs_limit),
        n_subjects_flagged=n_flagged,
        n_subjects_required_excluded=n_required,
    )
    qc_metadata = {
        "screened_conditions": qc_report.screened_conditions,
        "screened_rois": qc_report.screened_rois,
        "warn_threshold": qc_report.summary.warn_threshold,
        "critical_threshold": qc_report.summary.critical_threshold,
        "warn_abs_floor_sumabs": qc_report.summary.warn_abs_floor_sumabs,
        "critical_abs_floor_sumabs": qc_report.summary.critical_abs_floor_sumabs,
        "warn_abs_floor_maxabs": qc_report.summary.warn_abs_floor_maxabs,
        "critical_abs_floor_maxabs": qc_report.summary.critical_abs_floor_maxabs,
    }
    return OutlierExclusionReport(
        summary=summary,
        participants=combined_participants,
        qc_metadata=qc_metadata,
    )


def collect_flagged_pid_map(
    qc_report: QcExclusionReport | None,
    dv_report: OutlierExclusionReport | None,
) -> dict[str, list[str]]:
    flagged: dict[str, set[str]] = {}
    if qc_report:
        for participant in qc_report.participants:
            flagged.setdefault(participant.participant_id, set()).update(participant.reasons)
    if dv_report:
        for participant in dv_report.participants:
            flagged.setdefault(participant.participant_id, set()).update(participant.reasons)
    return {pid: sorted(reasons) for pid, reasons in flagged.items()}


def _qc_threshold_metadata(qc_report: QcExclusionReport | None) -> dict[str, float]:
    if not qc_report:
        return {
            "warn_threshold": float("nan"),
            "critical_threshold": float("nan"),
            "warn_abs_floor_sumabs": float("nan"),
            "critical_abs_floor_sumabs": float("nan"),
            "warn_abs_floor_maxabs": float("nan"),
            "critical_abs_floor_maxabs": float("nan"),
        }
    summary = qc_report.summary
    return {
        "warn_threshold": summary.warn_threshold,
        "critical_threshold": summary.critical_threshold,
        "warn_abs_floor_sumabs": summary.warn_abs_floor_sumabs,
        "critical_abs_floor_sumabs": summary.critical_abs_floor_sumabs,
        "warn_abs_floor_maxabs": summary.warn_abs_floor_maxabs,
        "critical_abs_floor_maxabs": summary.critical_abs_floor_maxabs,
    }


def build_flagged_participants_tables(
    qc_report: QcExclusionReport | None,
    dv_report: OutlierExclusionReport | None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    details: list[dict[str, object]] = []
    qc_meta = _qc_threshold_metadata(qc_report)

    if qc_report:
        for participant in qc_report.participants:
            for violation in participant.violations:
                details.append(
                    {
                        "participant_id": participant.participant_id,
                        "flag_type": violation.metric,
                        "severity": violation.severity,
                        "condition": violation.condition,
                        "roi": violation.roi,
                        "metric_value": violation.value,
                        "robust_center": violation.robust_center,
                        "robust_spread": violation.robust_spread,
                        "robust_score": violation.robust_score,
                        "threshold_used": violation.threshold_used,
                        "abs_floor_used": violation.abs_floor_used,
                        "trigger_harmonic_hz": violation.trigger_harmonic_hz,
                        "roi_mean_bca_at_trigger": violation.roi_mean_bca_at_trigger,
                        "reason_text": format_qc_violation(violation),
                    }
                )

    if dv_report:
        for participant in dv_report.participants:
            for dv_violation in participant.dv_violations:
                details.append(
                    {
                        "participant_id": participant.participant_id,
                        "flag_type": dv_violation.reason,
                        "severity": "REQUIRED" if dv_violation.reason == OUTLIER_REASON_NONFINITE else "FLAG",
                        "condition": dv_violation.condition,
                        "roi": dv_violation.roi,
                        "metric_value": dv_violation.value,
                        "robust_center": None,
                        "robust_spread": None,
                        "robust_score": None,
                        "threshold_used": dv_report.summary.abs_limit,
                        "abs_floor_used": None,
                        "trigger_harmonic_hz": None,
                        "roi_mean_bca_at_trigger": None,
                        "reason_text": format_outlier_reason(
                            dv_violation.reason,
                            abs_limit=dv_report.summary.abs_limit,
                        ),
                    }
                )

    details_df = pd.DataFrame(
        details,
        columns=[
            "participant_id",
            "flag_type",
            "severity",
            "condition",
            "roi",
            "metric_value",
            "robust_center",
            "robust_spread",
            "robust_score",
            "threshold_used",
            "abs_floor_used",
            "trigger_harmonic_hz",
            "roi_mean_bca_at_trigger",
            "reason_text",
        ],
    )

    summary_rows: list[dict[str, object]] = []
    if not details_df.empty:
        grouped = details_df.groupby("participant_id", sort=True)
        for pid, group in grouped:
            values = group["metric_value"].to_numpy()
            finite_mask = np.isfinite(values)
            worst_idx = None
            if values.size:
                worst_scores = np.where(finite_mask, np.abs(values), np.inf)
                worst_idx = int(np.argmax(worst_scores))
            worst_row = group.iloc[worst_idx] if worst_idx is not None else group.iloc[0]
            summary_rows.append(
                {
                    "participant_id": pid,
                    "flag_types": ", ".join(sorted(set(group["flag_type"].tolist()))),
                    "n_flags": int(group.shape[0]),
                    "worst_value": worst_row["metric_value"],
                    "worst_condition": worst_row["condition"],
                    "worst_roi": worst_row["roi"],
                    "reason_text": "; ".join(sorted(set(group["reason_text"].tolist()))),
                    **qc_meta,
                }
            )
    summary_df = pd.DataFrame(
        summary_rows,
        columns=[
            "participant_id",
            "flag_types",
            "n_flags",
            "worst_value",
            "worst_condition",
            "worst_roi",
            "reason_text",
            "warn_threshold",
            "critical_threshold",
            "warn_abs_floor_sumabs",
            "critical_abs_floor_sumabs",
            "warn_abs_floor_maxabs",
            "critical_abs_floor_maxabs",
        ],
    )
    if summary_df.empty and qc_meta:
        summary_df = pd.DataFrame(
            [],
            columns=[
                "participant_id",
                "flag_types",
                "n_flags",
                "worst_value",
                "worst_condition",
                "worst_roi",
                "reason_text",
                "warn_threshold",
                "critical_threshold",
                "warn_abs_floor_sumabs",
                "critical_abs_floor_sumabs",
                "warn_abs_floor_maxabs",
                "critical_abs_floor_maxabs",
            ],
        )
    return summary_df, details_df


def export_flagged_participants_report(
    save_path: str | bytes | "os.PathLike[str]",
    qc_report: QcExclusionReport | None,
    dv_report: OutlierExclusionReport | None,
    log_func,
) -> None:
    summary_df, details_df = build_flagged_participants_tables(qc_report, dv_report)
    with pd.ExcelWriter(save_path, engine="xlsxwriter") as writer:
        _auto_format_and_write_excel(writer, summary_df, "Flag Summary", log_func)
        _auto_format_and_write_excel(writer, details_df, "Flag Details", log_func)


def export_excluded_participants_report(
    save_path: str | bytes | "os.PathLike[str]",
    *,
    manual_excluded: list[str],
    required_exclusions: list[DvViolation],
    log_func,
) -> None:
    rows = []
    for pid in manual_excluded:
        rows.append(
            {
                "participant_id": pid,
                "exclusion_reason": OUTLIER_REASON_MANUAL,
                "worst_value": None,
                "worst_condition": None,
                "worst_roi": None,
            }
        )
    grouped: dict[str, DvViolation] = {}
    for violation in required_exclusions:
        current = grouped.get(violation.participant_id)
        if current is None:
            grouped[violation.participant_id] = violation
            continue
        current_val = current.value
        candidate_val = violation.value
        current_score = np.inf if not np.isfinite(current_val) else abs(current_val)
        candidate_score = np.inf if not np.isfinite(candidate_val) else abs(candidate_val)
        if candidate_score >= current_score:
            grouped[violation.participant_id] = violation
    for violation in grouped.values():
        rows.append(
            {
                "participant_id": violation.participant_id,
                "exclusion_reason": OUTLIER_REASON_NONFINITE,
                "worst_value": violation.value,
                "worst_condition": violation.condition,
                "worst_roi": violation.roi,
            }
        )
    df = pd.DataFrame(
        rows,
        columns=[
            "participant_id",
            "exclusion_reason",
            "worst_value",
            "worst_condition",
            "worst_roi",
        ],
    )
    with pd.ExcelWriter(save_path, engine="xlsxwriter") as writer:
        _auto_format_and_write_excel(writer, df, "Excluded Participants", log_func)
