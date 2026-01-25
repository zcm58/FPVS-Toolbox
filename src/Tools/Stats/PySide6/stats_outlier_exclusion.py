"""Outlier exclusion helpers for the Stats tool."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

from Tools.Stats.Legacy.stats_export import _auto_format_and_write_excel

OUTLIER_REASON_LIMIT = "HARD_DV_LIMIT"
OUTLIER_REASON_NONFINITE = "DV_NONFINITE"


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


@dataclass(frozen=True)
class OutlierExclusionReport:
    summary: OutlierExclusionSummary
    participants: list[
        OutlierParticipantReport
    ]


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
                )
            )

    summary = OutlierExclusionSummary(
        n_subjects_before=int(df[participant_col].nunique()),
        n_subjects_excluded=len(excluded_pids),
        n_subjects_after=int(filtered_df[participant_col].nunique()),
        abs_limit=float(abs_limit),
    )

    return filtered_df, OutlierExclusionReport(summary=summary, participants=participants)


def report_to_dataframe(report: OutlierExclusionReport) -> pd.DataFrame:
    rows = []
    for item in report.participants:
        rows.append(
            {
                "participant_id": item.participant_id,
                "reasons": ", ".join(item.reasons),
                "worst_value": item.worst_value,
                "worst_condition": item.worst_condition,
                "worst_roi": item.worst_roi,
                "n_violations": item.n_violations,
                "max_abs_dv": item.max_abs_dv,
            }
        )
    return pd.DataFrame(rows)


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
