"""GUI-neutral design auditing for single- and multi-group Stats inference.

The complete-core rule implemented here is intentionally participant-first:
the QC-eligible cohort is frozen before shared conditions are identified.
Conditions may be excluded for incomplete/non-finite cells, but participants
are never silently removed to recover a larger condition set.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Mapping, Sequence

import numpy as np
import pandas as pd


DESIGN_AUDIT_SCHEMA_VERSION = 1
UNKNOWN_GROUP_IDS = frozenset({"", "unknown", "unassigned", "none", "nan"})


class DesignAuditError(ValueError):
    """Raised when the participant x condition x ROI grain is invalid."""


class DesignStatus(str, Enum):
    """Machine-readable readiness of a prepared statistical design."""

    READY = "ready"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class DesignAuditResult:
    """Explicit design-audit result and exportable supporting tables."""

    status: DesignStatus
    status_code: str
    message: str
    frozen_participants: tuple[str, ...]
    requested_conditions: tuple[str, ...]
    selected_rois: tuple[str, ...]
    complete_conditions: tuple[str, ...]
    excluded_conditions: tuple[str, ...]
    primary_data: pd.DataFrame
    coverage: pd.DataFrame
    exclusions: pd.DataFrame
    group_assignments: pd.DataFrame

    @property
    def ready(self) -> bool:
        """Return whether primary inference may proceed."""

        return self.status is DesignStatus.READY

    def metadata_frame(self) -> pd.DataFrame:
        """Return one explicit, Excel-safe design metadata row."""

        return pd.DataFrame(
            [
                {
                    "design_audit_schema_version": DESIGN_AUDIT_SCHEMA_VERSION,
                    "status": self.status.value,
                    "status_code": self.status_code,
                    "message": self.message,
                    "participant_scope": "frozen_before_condition_intersection",
                    "n_frozen_participants": len(self.frozen_participants),
                    "frozen_participants": "; ".join(self.frozen_participants),
                    "n_requested_conditions": len(self.requested_conditions),
                    "requested_conditions": "; ".join(self.requested_conditions),
                    "n_complete_conditions": len(self.complete_conditions),
                    "complete_conditions": "; ".join(self.complete_conditions),
                    "n_excluded_conditions": len(self.excluded_conditions),
                    "excluded_conditions": "; ".join(self.excluded_conditions),
                    "n_selected_rois": len(self.selected_rois),
                    "selected_rois": "; ".join(self.selected_rois),
                }
            ]
        )

    def to_frames(self) -> dict[str, pd.DataFrame]:
        """Return explicit frames without relying on ``DataFrame.attrs``."""

        return {
            "Analysis Design": self.metadata_frame(),
            "Coverage": self.coverage.copy(),
            "Exclusions": self.exclusions.copy(),
            "Group Assignments": self.group_assignments.copy(),
            "Primary Data": self.primary_data.copy(),
        }


def _ordered_unique(values: Iterable[object], *, label: str) -> tuple[str, ...]:
    output: list[str] = []
    seen: set[str] = set()
    for raw in values:
        if raw is None or bool(pd.isna(raw)):
            continue
        value = str(raw).strip()
        if not value:
            continue
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        output.append(value)
    if not output:
        raise DesignAuditError(f"No {label} were supplied or observed.")
    return tuple(output)


def _observed_values(data: pd.DataFrame, column: str) -> tuple[str, ...]:
    values = (
        data[column]
        .dropna()
        .map(lambda value: str(value).strip())
        .loc[lambda series: series.ne("")]
        .unique()
        .tolist()
    )
    return tuple(sorted(values, key=str.casefold))


def _normalized_group_map(
    canonical_group_ids: Mapping[object, object] | None,
) -> dict[str, str]:
    if canonical_group_ids is None:
        return {}
    normalized: dict[str, str] = {}
    for raw_participant, raw_group in canonical_group_ids.items():
        participant = str(raw_participant).strip()
        group_id = "" if raw_group is None else str(raw_group).strip()
        if participant:
            normalized[participant.casefold()] = group_id
    return normalized


def _is_unknown_group_id(group_id: object) -> bool:
    if group_id is None:
        return True
    return str(group_id).strip().casefold() in UNKNOWN_GROUP_IDS


def _duplicate_message(
    duplicates: pd.DataFrame,
    *,
    subject_col: str,
    condition_col: str,
    roi_col: str,
) -> str:
    examples = []
    for _, row in duplicates.head(10).iterrows():
        examples.append(
            "("
            f"{row[subject_col]!r}, {row[condition_col]!r}, {row[roi_col]!r}"
            f") -> {int(row['row_count'])} rows"
        )
    return (
        "Duplicate participant x Condition x ROI observations were found; "
        "exactly one row is required for each selected cell. Examples: "
        + "; ".join(examples)
    )


def audit_complete_core_design(
    data: pd.DataFrame,
    *,
    dv_col: str,
    subject_col: str,
    condition_col: str,
    roi_col: str,
    frozen_participants: Sequence[object] | None = None,
    selected_conditions: Sequence[object] | None = None,
    selected_rois: Sequence[object] | None = None,
    canonical_group_ids: Mapping[object, object] | None = None,
    require_groups: bool = False,
) -> DesignAuditResult:
    """Audit and prepare the complete primary Condition x ROI design.

    ``frozen_participants`` should already reflect canonical QC and manual
    exclusions. When omitted, all observed participants are frozen. A selected
    condition is complete only when every frozen participant contributes
    exactly one finite dependent value in every selected ROI.
    """

    if not isinstance(data, pd.DataFrame):
        raise TypeError("data must be a pandas DataFrame.")
    required = (dv_col, subject_col, condition_col, roi_col)
    missing_columns = [column for column in required if column not in data.columns]
    if missing_columns:
        raise DesignAuditError(f"Missing required columns: {missing_columns}")

    participants = _ordered_unique(
        frozen_participants
        if frozen_participants is not None
        else _observed_values(data, subject_col),
        label="frozen participants",
    )
    conditions = _ordered_unique(
        selected_conditions
        if selected_conditions is not None
        else _observed_values(data, condition_col),
        label="selected conditions",
    )
    rois = _ordered_unique(
        selected_rois
        if selected_rois is not None
        else _observed_values(data, roi_col),
        label="selected ROIs",
    )

    working = data.loc[:, list(dict.fromkeys(required))].copy()
    working[subject_col] = working[subject_col].map(
        lambda value: "" if pd.isna(value) else str(value).strip()
    )
    working[condition_col] = working[condition_col].map(
        lambda value: "" if pd.isna(value) else str(value).strip()
    )
    working[roi_col] = working[roi_col].map(
        lambda value: "" if pd.isna(value) else str(value).strip()
    )
    working["_numeric_dv"] = pd.to_numeric(working[dv_col], errors="coerce")
    working["_finite_dv"] = np.isfinite(working["_numeric_dv"].to_numpy(dtype=float))

    participant_keys = {value.casefold() for value in participants}
    condition_keys = {value.casefold() for value in conditions}
    roi_keys = {value.casefold() for value in rois}
    selected = working[
        working[subject_col].str.casefold().isin(participant_keys)
        & working[condition_col].str.casefold().isin(condition_keys)
        & working[roi_col].str.casefold().isin(roi_keys)
    ].copy()

    counts = (
        selected.groupby(
            [subject_col, condition_col, roi_col],
            dropna=False,
            sort=False,
        )
        .size()
        .reset_index(name="row_count")
    )
    duplicates = counts[counts["row_count"] > 1]
    if not duplicates.empty:
        raise DesignAuditError(
            _duplicate_message(
                duplicates,
                subject_col=subject_col,
                condition_col=condition_col,
                roi_col=roi_col,
            )
        )

    lookup = {
        (
            str(row[subject_col]).casefold(),
            str(row[condition_col]).casefold(),
            str(row[roi_col]).casefold(),
        ): row
        for _, row in selected.iterrows()
    }
    coverage_rows: list[dict[str, object]] = []
    condition_complete: dict[str, bool] = {}
    for condition in conditions:
        all_rois_complete = True
        for roi in rois:
            n_present = 0
            n_finite = 0
            for participant in participants:
                row = lookup.get(
                    (
                        participant.casefold(),
                        condition.casefold(),
                        roi.casefold(),
                    )
                )
                if row is None:
                    continue
                n_present += 1
                if bool(row["_finite_dv"]):
                    n_finite += 1
            complete = n_present == len(participants) and n_finite == len(participants)
            all_rois_complete = all_rois_complete and complete
            coverage_rows.append(
                {
                    "condition": condition,
                    "roi": roi,
                    "n_frozen_participants": len(participants),
                    "n_rows_present": n_present,
                    "n_finite_values": n_finite,
                    "n_missing_rows": len(participants) - n_present,
                    "n_nonfinite_values": n_present - n_finite,
                    "cell_complete": complete,
                }
            )
        condition_complete[condition] = all_rois_complete

    complete_conditions = tuple(
        condition for condition in conditions if condition_complete[condition]
    )
    excluded_conditions = tuple(
        condition for condition in conditions if not condition_complete[condition]
    )
    coverage = pd.DataFrame(coverage_rows)
    coverage["condition_complete"] = coverage["condition"].map(condition_complete)
    coverage["retained_primary"] = coverage["condition"].isin(complete_conditions)

    exclusion_rows: list[dict[str, object]] = []
    for condition in excluded_conditions:
        rows = coverage[coverage["condition"] == condition]
        exclusion_rows.append(
            {
                "scope": "condition",
                "condition": condition,
                "reason": "incomplete_for_frozen_cohort",
                "n_frozen_participants": len(participants),
                "missing_cells": int(rows["n_missing_rows"].sum()),
                "nonfinite_cells": int(rows["n_nonfinite_values"].sum()),
            }
        )
    exclusions = pd.DataFrame(
        exclusion_rows,
        columns=[
            "scope",
            "condition",
            "reason",
            "n_frozen_participants",
            "missing_cells",
            "nonfinite_cells",
        ],
    )

    group_map = _normalized_group_map(canonical_group_ids)
    assignment_rows: list[dict[str, object]] = []
    missing_group_participants: list[str] = []
    for participant in participants:
        group_id = group_map.get(participant.casefold(), "")
        assigned = not _is_unknown_group_id(group_id)
        if not assigned:
            missing_group_participants.append(participant)
        assignment_rows.append(
            {
                "participant_id": participant,
                "group_id": group_id if assigned else None,
                "assignment_status": "assigned" if assigned else "missing_or_unknown",
            }
        )
    group_assignments = pd.DataFrame(assignment_rows)

    primary = selected[
        selected[condition_col].str.casefold().isin(
            {value.casefold() for value in complete_conditions}
        )
        & selected["_finite_dv"]
    ].copy()
    primary[dv_col] = primary["_numeric_dv"].astype(float)
    primary = primary.drop(columns=["_numeric_dv", "_finite_dv"])
    if group_map:
        primary["group_id"] = primary[subject_col].map(
            lambda value: group_map.get(str(value).casefold()) or np.nan
        )
    primary = primary.sort_values(
        [subject_col, condition_col, roi_col],
        kind="stable",
    ).reset_index(drop=True)

    status = DesignStatus.READY
    status_code = "complete_core_ready"
    message = (
        f"Complete-core design is ready with {len(participants)} participants "
        f"and {len(complete_conditions)} shared condition(s)."
    )
    if not complete_conditions:
        status = DesignStatus.BLOCKED
        status_code = "no_shared_complete_condition"
        message = (
            "No selected condition has exactly one finite value for every "
            "frozen participant in every selected ROI."
        )
    elif require_groups and missing_group_participants:
        status = DesignStatus.BLOCKED
        status_code = "missing_group_assignments"
        message = (
            "Canonical group assignment is missing or unknown for: "
            + ", ".join(missing_group_participants)
        )
    elif require_groups:
        assigned_groups = {
            str(value)
            for value in group_assignments["group_id"].dropna().tolist()
        }
        if len(assigned_groups) < 2:
            status = DesignStatus.BLOCKED
            status_code = "insufficient_groups"
            message = (
                "Multi-group inference requires at least two canonical groups "
                "in the frozen cohort."
            )

    return DesignAuditResult(
        status=status,
        status_code=status_code,
        message=message,
        frozen_participants=participants,
        requested_conditions=conditions,
        selected_rois=rois,
        complete_conditions=complete_conditions,
        excluded_conditions=excluded_conditions,
        primary_data=primary,
        coverage=coverage.reset_index(drop=True),
        exclusions=exclusions,
        group_assignments=group_assignments,
    )


def build_factor_cell_coverage(
    data: pd.DataFrame,
    *,
    factors: Sequence[str],
    subject_col: str,
) -> pd.DataFrame:
    """Return observed subject coverage for structural estimability audits."""

    if not isinstance(data, pd.DataFrame):
        raise TypeError("data must be a pandas DataFrame.")
    factor_columns = tuple(str(column) for column in factors)
    if not factor_columns:
        raise DesignAuditError("At least one factor column is required.")
    required = [subject_col, *factor_columns]
    missing = [column for column in required if column not in data.columns]
    if missing:
        raise DesignAuditError(f"Missing required columns: {missing}")
    total_subjects = int(data[subject_col].dropna().nunique())
    coverage = (
        data.groupby(list(factor_columns), dropna=False, sort=True)[subject_col]
        .nunique()
        .reset_index(name="n_participants")
    )
    coverage["n_total_participants"] = total_subjects
    coverage["structurally_observed"] = coverage["n_participants"].gt(0)
    coverage["complete_participant_coverage"] = coverage["n_participants"].eq(
        total_subjects
    )
    return coverage


__all__ = [
    "DESIGN_AUDIT_SCHEMA_VERSION",
    "DesignAuditError",
    "DesignAuditResult",
    "DesignStatus",
    "audit_complete_core_design",
    "build_factor_cell_coverage",
]
