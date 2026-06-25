"""Project and workbook discovery for publication reports."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable, Mapping

from Main_App.Shared.file_filters import is_excel_workbook_file
from Main_App.projects.project import EXCEL_SUBFOLDER_NAME
from Tools.Publication_Report.models import (
    PUBLICATION_REPORT_OUTPUT_FOLDER,
    DiscoveredCondition,
    PublicationReportRequest,
    WorkbookEntry,
)

_PID_PATTERN = re.compile(r"(?:[A-Za-z]*)?(P\d+)", re.IGNORECASE)


def load_project_manifest(project_root: Path) -> dict[str, object]:
    """Read project.json when available."""

    manifest_path = Path(project_root) / "project.json"
    if not manifest_path.exists():
        return {}
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def resolve_project_paths(project_root: Path) -> tuple[Path, Path, Path]:
    """Return project root, Excel root, and default report output root."""

    root = Path(project_root).expanduser().resolve()
    manifest = load_project_manifest(root)
    results_folder = _resolve_manifest_path(
        root,
        manifest.get("results_folder") if isinstance(manifest, Mapping) else None,
        default=".",
    )
    subfolders = manifest.get("subfolders") if isinstance(manifest, Mapping) else {}
    excel_name = EXCEL_SUBFOLDER_NAME
    if isinstance(subfolders, Mapping):
        raw_excel = subfolders.get("excel")
        if raw_excel not in (None, ""):
            excel_name = str(raw_excel)
    excel_root = _resolve_manifest_path(results_folder, excel_name, default=EXCEL_SUBFOLDER_NAME)
    output_root = _resolve_manifest_path(
        results_folder,
        PUBLICATION_REPORT_OUTPUT_FOLDER,
        default=PUBLICATION_REPORT_OUTPUT_FOLDER,
    )
    return root, excel_root, output_root


def _resolve_manifest_path(base: Path, value: object, *, default: str) -> Path:
    text = str(value if value not in (None, "") else default)
    candidate = Path(text)
    return candidate.expanduser().resolve() if candidate.is_absolute() else (base / candidate).resolve()


def validate_single_group_project(project_root: Path) -> None:
    """Raise when project metadata declares multiple groups."""

    manifest = load_project_manifest(project_root)
    groups = manifest.get("groups") if isinstance(manifest, Mapping) else None
    if isinstance(groups, Mapping) and len(groups) >= 2:
        raise RuntimeError(
            "Publication Report is currently a single-group workflow. "
            f"This project has {len(groups)} configured groups."
        )


def discover_conditions(input_root: Path) -> list[DiscoveredCondition]:
    """Return condition folders that contain result workbooks."""

    root = Path(input_root)
    if not root.exists():
        return []
    conditions: list[DiscoveredCondition] = []
    for child in sorted(root.iterdir(), key=lambda path: path.name.lower()):
        if not child.is_dir():
            continue
        files = tuple(_iter_excel_files(child))
        if files:
            conditions.append(DiscoveredCondition(name=child.name, path=child, files=files))
    return conditions


def discover_workbooks(
    input_root: Path,
    conditions: Iterable[str],
) -> list[WorkbookEntry]:
    """Return workbook entries for selected condition folders."""

    root = Path(input_root)
    entries: list[WorkbookEntry] = []
    for condition in conditions:
        condition_name = str(condition)
        condition_dir = root / condition_name
        if not condition_dir.is_dir():
            continue
        for workbook in _iter_excel_files(condition_dir):
            entries.append(
                WorkbookEntry(
                    condition=condition_name,
                    subject_id=infer_subject_id(workbook),
                    path=workbook,
                )
            )
    return entries


def infer_subject_id(excel_path: Path) -> str:
    """Return a stable participant ID inferred from a result workbook name."""

    stem = Path(excel_path).stem.strip()
    if not stem:
        return Path(excel_path).name.upper()
    match = _PID_PATTERN.search(stem)
    if match:
        return match.group(1).upper()
    return stem.upper()


def _iter_excel_files(folder: Path) -> list[Path]:
    files = [
        path
        for path in Path(folder).rglob("*.xlsx")
        if path.is_file() and is_excel_workbook_file(path)
    ]
    return sorted(files, key=lambda path: str(path).lower())


def selected_condition_names(
    *,
    request: PublicationReportRequest,
    discovered: Iterable[DiscoveredCondition],
) -> tuple[str, ...]:
    """Resolve selected conditions, defaulting to all discovered conditions."""

    available = {condition.name for condition in discovered}
    if not request.selected_conditions:
        return tuple(sorted(available, key=str.lower))
    selected = tuple(str(name) for name in request.selected_conditions if str(name) in available)
    missing = [str(name) for name in request.selected_conditions if str(name) not in available]
    if missing:
        raise RuntimeError(
            "Selected condition folder(s) were not found under the Excel root: "
            + ", ".join(missing)
        )
    return selected


def participant_ids(entries: Iterable[WorkbookEntry]) -> tuple[str, ...]:
    """Return sorted participant IDs from workbook entries."""

    return tuple(sorted({entry.subject_id for entry in entries}, key=_participant_sort_key))


def _participant_sort_key(value: str) -> tuple[int, str]:
    match = re.match(r"(?i)^P(\d+)$", str(value).strip())
    if match:
        return int(match.group(1)), str(value)
    return 10**9, str(value)
