"""Internal processed-workbook layout, filtering, and scoring helpers."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

_IGNORED_WORKBOOK_FOLDERS = frozenset({".fif files", "loreta results"})
_CONDITION_PREFIX_PATTERN = re.compile(r"^\d+\s*[-_]*\s*")


def workbook_location(
    path: Path,
    *,
    excel_root: Path,
    scan_root: Path,
    project_managed: bool,
) -> tuple[str | None, str, str | None]:
    if project_managed:
        try:
            parts = path.resolve(strict=False).relative_to(
                excel_root.resolve(strict=False)
            ).parts
        except ValueError:
            return None, "outside_excel_root", None
        if len(parts) < 2:
            return None, "excel_root_file", None
        condition = clean_condition(parts[0])
        observed_group = str(parts[1]) if len(parts) >= 3 else None
        if len(parts) == 2:
            layout = "condition_flat"
        elif len(parts) == 3:
            layout = "condition_group"
        else:
            layout = "unexpected_nested"
        return condition, layout, observed_group
    try:
        parts = path.relative_to(scan_root).parts
    except ValueError:
        parts = path.parts
    raw_condition = parts[0] if len(parts) >= 2 else scan_root.name
    return (
        clean_condition(raw_condition),
        "nested" if len(parts) >= 2 else "flat",
        None,
    )


def workbook_candidate_score(
    path: Path,
    *,
    observed_layout: str,
    observed_group_folder: str | None,
    expected_group_folder: str | None,
) -> tuple[int, int, str]:
    if observed_layout == "unexpected_nested":
        routing_score = -1
    elif observed_layout in {"condition_flat", "flat"}:
        routing_score = 1
    elif expected_group_folder is not None and observed_group_folder is not None:
        routing_score = (
            3
            if observed_group_folder.casefold() == expected_group_folder.casefold()
            else 0
        )
    else:
        routing_score = 2
    try:
        mtime_ns = int(path.stat().st_mtime_ns)
    except OSError:
        mtime_ns = 0
    return routing_score, mtime_ns, str(path)


def is_ignored_workbook_path(path: Path, scan_root: Path) -> bool:
    try:
        relative_parts = path.relative_to(scan_root).parts[:-1]
    except ValueError:
        relative_parts = path.parts[:-1]
    return any(
        part.casefold() in _IGNORED_WORKBOOK_FOLDERS
        for part in relative_parts
    )


def casefold_set(values: Iterable[str] | None) -> set[str] | None:
    if values is None:
        return None
    return {str(value).strip().casefold() for value in values if str(value).strip()}


def clean_condition(value: object) -> str | None:
    condition = _CONDITION_PREFIX_PATTERN.sub("", str(value).strip()).strip()
    return condition or None
