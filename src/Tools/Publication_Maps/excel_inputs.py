"""Workbook discovery and frequency-column helpers for publication scalp maps."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

import pandas as pd

from Tools.Plot_Generator.excel_inputs import _infer_subject_id_from_path
from Tools.Publication_Maps.models import ConditionInfo, FrequencyColumn, WorkbookEntry
from Tools.Ratio_Calculator.utils import is_excel_temp_lock_file

BCA_SHEET = "BCA (uV)"
ELECTRODE_COLUMN = "Electrode"

_NUMERIC_PREFIX_RE = re.compile(r"^\s*([+-]?\d+(?:\.\d+)?)")
_FREQUENCY_TOLERANCE_HZ = 0.00005


def discover_conditions(input_root: Path) -> list[ConditionInfo]:
    """Return condition folders with workbook counts under an Excel root."""

    root = Path(input_root)
    if not root.exists():
        return []
    conditions: list[ConditionInfo] = []
    for child in sorted(root.iterdir(), key=lambda path: path.name.lower()):
        if not child.is_dir():
            continue
        files = tuple(_iter_excel_files(child))
        if files:
            conditions.append(ConditionInfo(name=child.name, path=child, files=files))
    return conditions


def discover_workbooks(
    input_root: Path,
    conditions: Iterable[str],
    *,
    excluded_subjects: Iterable[str] = (),
) -> list[WorkbookEntry]:
    """Return selected workbooks under condition folders."""

    root = Path(input_root)
    excluded = {str(subject).strip().upper() for subject in excluded_subjects}
    entries: list[WorkbookEntry] = []
    for condition in conditions:
        condition_name = str(condition)
        condition_dir = root / condition_name
        if not condition_dir.is_dir():
            continue
        for workbook in _iter_excel_files(condition_dir):
            subject_id = _infer_subject_id_from_path(workbook) or workbook.stem.upper()
            if subject_id.upper() in excluded:
                continue
            entries.append(
                WorkbookEntry(
                    condition=condition_name,
                    subject_id=subject_id,
                    path=workbook,
                )
            )
    return entries


def _iter_excel_files(folder: Path) -> list[Path]:
    files = [
        path
        for path in folder.rglob("*.xlsx")
        if path.is_file() and not is_excel_temp_lock_file(path.name)
    ]
    return sorted(files, key=lambda path: str(path).lower())


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
