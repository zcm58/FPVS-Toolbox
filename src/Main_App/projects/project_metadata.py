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
    except UnicodeError:
        raw = None

    parse_error = raw is None
    if raw is not None:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parse_error = True
        else:
            if isinstance(parsed, dict):
                data = parsed
            else:
                parse_error = True

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


def read_project_experimental_qc_settings(project_root: Path):
    """Read committed QC choices without loading widgets or changing a project."""
    from .experimental_qc_settings import normalize_project_experimental_qc_settings

    manifest = json.loads((Path(project_root) / "project.json").read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("Project QC settings require a valid project.json object.")
    return normalize_project_experimental_qc_settings(manifest)
