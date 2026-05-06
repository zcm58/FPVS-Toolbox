from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class ProjectMetadata:
    project_root: Path
    manifest_path: Path
    manifest: dict[str, Any]
    name: str
    input_folder: str | None
    groups_count: int
    last_modified: float
    parse_error: bool = False


def read_project_metadata(project_root: Path) -> ProjectMetadata:
    manifest_path = project_root / "project.json"
    data: dict[str, Any] = {}
    try:
        raw = manifest_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise
    except OSError:
        raise

    parse_error = False
    try:
        parsed = json.loads(raw)
    except Exception:
        parse_error = True
        parsed = {}

    if isinstance(parsed, dict):
        data = parsed
    else:
        data = {}

    raw_name = data.get("name")
    name = str(raw_name) if raw_name else project_root.name
    input_folder = data.get("input_folder")

    groups_raw = data.get("groups", {})
    groups_count = len(groups_raw) if isinstance(groups_raw, Mapping) else 0

    try:
        last_modified = manifest_path.stat().st_mtime
    except OSError:
        last_modified = 0.0

    return ProjectMetadata(
        project_root=project_root,
        manifest_path=manifest_path,
        manifest=dict(data),
        name=name,
        input_folder=str(input_folder) if input_folder is not None else None,
        groups_count=groups_count,
        last_modified=last_modified,
        parse_error=parse_error,
    )


def enumerate_project_metadata(root: Path) -> list[ProjectMetadata]:
    results: list[ProjectMetadata] = []
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        manifest_path = entry / "project.json"
        if not manifest_path.exists():
            continue
        results.append(read_project_metadata(entry))
    return results
