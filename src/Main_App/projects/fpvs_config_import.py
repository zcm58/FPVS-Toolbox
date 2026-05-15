"""Import FPVS Studio `.fpvsconfig` files into Toolbox project shells."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from Main_App.projects.project import Project

CONFIG_SUFFIX = ".fpvsconfig"
WINDOWS_FORBIDDEN_PROJECT_CHARS = set('<>:"/\\|?*')
_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


class FPVSConfigImportError(ValueError):
    """Raised when a Studio `.fpvsconfig` cannot seed a Toolbox project."""


@dataclass(frozen=True)
class FPVSConfigImport:
    """The Toolbox-owned subset of a Studio project config."""

    project_title: str
    event_map: dict[str, int]


def read_fpvs_config(path: Path) -> FPVSConfigImport:
    """Read project title and condition trigger map from a Studio `.fpvsconfig`."""

    config_path = Path(path)
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise FPVSConfigImportError(f"Unable to read FPVS config: {config_path}") from exc
    except json.JSONDecodeError as exc:
        raise FPVSConfigImportError(f"FPVS config is not valid JSON: {config_path}") from exc
    if not isinstance(payload, Mapping):
        raise FPVSConfigImportError("FPVS config must contain a JSON object.")

    schema_version = payload.get("schema_version")
    if schema_version != "1.0.0":
        raise FPVSConfigImportError(
            "Unsupported FPVS config schema version: "
            f"{schema_version!r}. Expected '1.0.0'."
        )

    project = payload.get("project")
    if not isinstance(project, Mapping):
        raise FPVSConfigImportError("FPVS config is missing a project object.")
    title = _required_text(project.get("name"), "project.name")

    conditions = payload.get("conditions")
    if not isinstance(conditions, list) or not conditions:
        raise FPVSConfigImportError("FPVS config must contain at least one condition.")

    event_map: dict[str, int] = {}
    used_codes: set[int] = set()
    for index, raw_condition in enumerate(conditions):
        if not isinstance(raw_condition, Mapping):
            raise FPVSConfigImportError(f"conditions[{index}] must be an object.")
        name = _required_text(raw_condition.get("name"), f"conditions[{index}].name")
        if name in event_map:
            raise FPVSConfigImportError(f"Duplicate condition name in FPVS config: {name!r}.")
        code = _required_int(
            raw_condition.get("trigger_code"),
            f"conditions[{index}].trigger_code",
        )
        if code in used_codes:
            raise FPVSConfigImportError(f"Duplicate trigger code in FPVS config: {code}.")
        event_map[name] = code
        used_codes.add(code)

    return FPVSConfigImport(project_title=title, event_map=event_map)


def create_project_from_fpvs_config(projects_root: Path, config_path: Path) -> Project:
    """Create and save a Toolbox project from the importable Studio config subset."""

    imported = read_fpvs_config(config_path)
    project_root = _unique_project_root(Path(projects_root), imported.project_title)
    project_root.mkdir(parents=True, exist_ok=False)
    project = Project.load(project_root)
    project.name = imported.project_title
    project.event_map = imported.event_map
    project.save()
    return project


def _required_text(value: Any, location: str) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        raise FPVSConfigImportError(f"FPVS config is missing {location}.")
    return text


def _required_int(value: Any, location: str) -> int:
    if isinstance(value, bool):
        raise FPVSConfigImportError(f"{location} must be an integer.")
    if isinstance(value, int):
        code = value
    elif isinstance(value, str) and value.strip().isdigit():
        code = int(value)
    else:
        raise FPVSConfigImportError(f"{location} must be an integer.")
    if code < 1:
        raise FPVSConfigImportError(f"{location} must be a positive integer.")
    return code


def _project_dir_name(project_title: str) -> str:
    cleaned = "".join(
        "_" if char in WINDOWS_FORBIDDEN_PROJECT_CHARS else char for char in project_title.strip()
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    if not cleaned:
        cleaned = "Imported FPVS Project"
    if cleaned.upper() in _WINDOWS_RESERVED_NAMES:
        cleaned = f"{cleaned}_Project"
    return cleaned


def _unique_project_root(projects_root: Path, project_title: str) -> Path:
    base_name = _project_dir_name(project_title)
    candidate = projects_root / base_name
    if not candidate.exists():
        return candidate

    suffix = 2
    while True:
        candidate = projects_root / f"{base_name} {suffix}"
        if not candidate.exists():
            return candidate
        suffix += 1
