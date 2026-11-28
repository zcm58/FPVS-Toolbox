"""Workbook discovery and frequency-column helpers for publication scalp maps."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

import pandas as pd

from Main_App.projects import (
    DatasetIndexError,
    GroupInfo,
    ProjectDatasetIndex,
    WorkbookRecord,
    load_project_dataset_index,
)
from Tools.Publication_Maps.models import ConditionInfo, FrequencyColumn, WorkbookEntry

BCA_SHEET = "BCA (uV)"
SNR_SHEET = "SNR"
ELECTRODE_COLUMN = "Electrode"

_NUMERIC_PREFIX_RE = re.compile(r"^\s*([+-]?\d+(?:\.\d+)?)")
_FREQUENCY_TOLERANCE_HZ = 0.00005


def discover_conditions(input_root: Path) -> list[ConditionInfo]:
    """Return canonical indexed conditions with active workbook counts."""

    root = Path(input_root)
    if not root.exists():
        return []
    try:
        index = load_project_dataset_index(root)
    except DatasetIndexError:
        return []
    records_by_condition: dict[str, list[WorkbookRecord]] = {}
    for record in index.workbooks:
        records_by_condition.setdefault(record.condition, []).append(record)
    return [
        ConditionInfo(
            name=condition,
            path=index.excel_root / condition,
            files=tuple(record.path for record in records),
        )
        for condition, records in sorted(
            records_by_condition.items(),
            key=lambda item: item[0].casefold(),
        )
    ]


def load_publication_dataset_index(
    input_root: str | Path,
    *,
    project_root: str | Path | None = None,
) -> ProjectDatasetIndex:
    """Load the shared index and bind managed input to the active project."""

    index = load_project_dataset_index(input_root)
    if project_root in (None, ""):
        return index
    expected_root = Path(project_root).expanduser().resolve(strict=False)
    if index.manifest is None:
        raise DatasetIndexError(
            f"Scalp Maps input must be inside the active project's configured Excel root: {expected_root}"
        )
    indexed_root = index.project_root.expanduser().resolve(strict=False)
    if indexed_root != expected_root:
        raise DatasetIndexError(
            f"Scalp Maps input belongs to a different project: {indexed_root} (active project: {expected_root})."
        )
    requested_root = Path(input_root).expanduser().resolve(strict=False)
    canonical_excel_root = index.excel_root.expanduser().resolve(strict=False)
    if requested_root != canonical_excel_root:
        raise DatasetIndexError(
            "Scalp Maps input must be the active project's exact configured "
            f"Excel root: {canonical_excel_root}."
        )
    return index


def resolve_publication_group(
    index: ProjectDatasetIndex,
    *,
    group_id: str | None = None,
    group_label: str | None = None,
    group_folder: str | None = None,
) -> GroupInfo | None:
    """Resolve exactly one canonical project group for aggregation."""

    requested_id = str(group_id or "").strip()
    requested_label = str(group_label or "").strip()
    requested_folder = str(group_folder or "").strip()
    ordered_groups = index.ordered_groups
    if not ordered_groups:
        if requested_id or requested_label or requested_folder:
            raise DatasetIndexError("This project has no canonical group metadata for the requested Scalp Maps group.")
        return None

    if not requested_id:
        if len(ordered_groups) > 1:
            raise DatasetIndexError(
                "Select one canonical project group before generating Scalp Maps. "
                "An all-groups action must run each group separately."
            )
        group = ordered_groups[0]
    else:
        matches = [group for group in ordered_groups if group.group_id.casefold() == requested_id.casefold()]
        if not matches:
            raise DatasetIndexError(f"Unknown canonical project group_id: {requested_id}.")
        group = matches[0]

    if requested_label and requested_label != group.label:
        raise DatasetIndexError(f"Selected group label changed for {group.group_id}; reopen Scalp Maps.")
    if requested_folder and requested_folder != group.folder_name:
        raise DatasetIndexError(f"Selected group output folder changed for {group.group_id}; reopen Scalp Maps.")
    return group


def select_publication_workbooks(
    index: ProjectDatasetIndex,
    conditions: Iterable[str],
    *,
    excluded_subjects: Iterable[str] = (),
    group_id: str | None = None,
    group_label: str | None = None,
    group_folder: str | None = None,
    session_ids: Iterable[str] | None = None,
) -> tuple[tuple[WorkbookEntry, ...], GroupInfo | None]:
    """Select active canonical workbook records for one group-scoped run."""

    requested_conditions = tuple(
        dict.fromkeys(str(condition).strip() for condition in conditions if str(condition).strip())
    )
    if not requested_conditions:
        raise DatasetIndexError("Select at least one condition for Scalp Maps.")
    _require_requested_group_assignments(index, requested_conditions)
    group = resolve_publication_group(
        index,
        group_id=group_id,
        group_label=group_label,
        group_folder=group_folder,
    )
    records = index.select(
        conditions=requested_conditions,
        group_ids=None if group is None else (group.group_id,),
        session_ids=session_ids,
        require_nonempty_groups=False,
        require_nonempty_sessions=session_ids is not None,
    )
    excluded = {str(subject).strip().casefold() for subject in excluded_subjects if str(subject).strip()}
    records = tuple(record for record in records if record.participant_id.casefold() not in excluded)
    present_conditions = {record.condition.casefold() for record in records}
    empty_conditions = [
        condition for condition in requested_conditions if condition.casefold() not in present_conditions
    ]
    if empty_conditions:
        scope = ""
        if group is not None:
            scope = f" for group {group.group_id}"
        raise DatasetIndexError(
            f"No active canonical workbooks remain{scope} for condition(s): {', '.join(empty_conditions)}."
        )
    canonical_folder = None if group is None else group.folder_name
    entries = tuple(
        WorkbookEntry(
            condition=record.condition,
            subject_id=record.participant_id,
            path=record.path,
            group_id=record.group_id,
            group_label=record.group_label,
            group_folder=canonical_folder,
        )
        for record in records
    )
    return entries, group


def _require_requested_group_assignments(
    index: ProjectDatasetIndex,
    requested_conditions: tuple[str, ...],
) -> None:
    """Reject ambiguous active cohorts only within the requested conditions."""

    if not index.has_group_metadata:
        return
    condition_keys = {condition.casefold() for condition in requested_conditions}
    unassigned = sorted(
        {
            record.participant_id
            for record in index.workbooks
            if record.condition.casefold() in condition_keys and record.group_id is None
        },
        key=str.casefold,
    )
    if unassigned:
        raise DatasetIndexError(
            "Grouped project workbook identity is incomplete for the requested "
            "Scalp Maps condition(s): participants without a canonical group "
            "assignment: " + ", ".join(unassigned)
        )


def discover_workbooks(
    input_root: Path,
    conditions: Iterable[str],
    *,
    excluded_subjects: Iterable[str] = (),
    project_root: str | Path | None = None,
    group_id: str | None = None,
    group_label: str | None = None,
    group_folder: str | None = None,
    session_ids: Iterable[str] | None = None,
) -> list[WorkbookEntry]:
    """Return shared-index workbooks for one canonical group scope."""

    index = load_publication_dataset_index(
        input_root,
        project_root=project_root,
    )
    entries, _group = select_publication_workbooks(
        index,
        conditions,
        excluded_subjects=excluded_subjects,
        group_id=group_id,
        group_label=group_label,
        group_folder=group_folder,
        session_ids=session_ids,
    )
    return list(entries)


def parse_frequency_column_name(column: object) -> float | None:
    """Parse a frequency from a workbook column label."""

    if not isinstance(column, str):
        return None
    match = _NUMERIC_PREFIX_RE.match(column)
    if not match:
        return None
    try:
        value = float(match.group(1))
    except ValueError:
        return None
    return value if pd.notna(value) else None


def frequency_columns(columns: Iterable[object]) -> list[FrequencyColumn]:
    """Return parseable frequency columns in workbook order."""

    parsed: list[FrequencyColumn] = []
    for column in columns:
        freq = parse_frequency_column_name(column)
        if freq is None:
            continue
        parsed.append(
            FrequencyColumn(
                requested_hz=freq,
                column_hz=freq,
                column_name=str(column),
                exact_label_match=False,
            )
        )
    return parsed


def find_frequency_column(columns: Iterable[object], requested_hz: float) -> FrequencyColumn | None:
    """Find a requested frequency column without nearest-bin fallback."""

    requested = round(float(requested_hz), 4)
    exact_label = f"{requested:.4f}_Hz"
    column_list = list(columns)
    for column in column_list:
        if str(column) == exact_label:
            return FrequencyColumn(
                requested_hz=requested,
                column_hz=requested,
                column_name=str(column),
                exact_label_match=True,
            )
    for column in column_list:
        parsed = parse_frequency_column_name(column)
        if parsed is None:
            continue
        if abs(round(float(parsed), 4) - requested) <= _FREQUENCY_TOLERANCE_HZ:
            return FrequencyColumn(
                requested_hz=requested,
                column_hz=float(parsed),
                column_name=str(column),
                exact_label_match=False,
            )
    return None


def read_excel_sheet(path: Path, sheet_name: str, *, usecols: list[str] | None = None) -> pd.DataFrame:
    """Read one workbook sheet with a stable pandas call site."""

    return pd.read_excel(path, sheet_name=sheet_name, usecols=usecols)
