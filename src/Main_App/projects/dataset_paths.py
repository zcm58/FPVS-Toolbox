"""Internal non-mutating project dataset path and manifest helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .project import EXCEL_SUBFOLDER_NAME


class DatasetIndexError(ValueError):
    """Raised when a processed dataset cannot be indexed safely."""


def resolve_project_excel_root(
    project_root: str | Path,
    manifest: Mapping[str, Any],
) -> Path:
    """Resolve the manifest-owned Excel root without creating directories."""

    root = Path(project_root).expanduser().resolve(strict=False)
    results_value = manifest.get("results_folder", ".")
    results_path = Path(str(results_value or ".")).expanduser()
    results_root = (
        results_path
        if results_path.is_absolute()
        else (root / results_path).resolve(strict=False)
    )
    subfolders = manifest.get("subfolders", {})
    excel_value: object = EXCEL_SUBFOLDER_NAME
    if isinstance(subfolders, Mapping):
        excel_value = subfolders.get("excel", EXCEL_SUBFOLDER_NAME)
    excel_path = Path(str(excel_value or EXCEL_SUBFOLDER_NAME)).expanduser()
    return (
        excel_path.resolve(strict=False)
        if excel_path.is_absolute()
        else (results_root / excel_path).resolve(strict=False)
    )


def find_project_manifest_for_dataset_path(
    dataset_path: str | Path,
) -> tuple[Path, dict[str, Any]] | tuple[None, None]:
    """Locate the manifest that canonically owns a project dataset path."""

    start = Path(dataset_path).expanduser().resolve(strict=False)
    input_is_file = start.is_file()
    current = start.parent if input_is_file else start
    for candidate in (current, *current.parents):
        manifest_path = candidate / "project.json"
        if not manifest_path.is_file():
            continue
        manifest = _read_manifest(manifest_path)
        excel_root = resolve_project_excel_root(candidate, manifest)
        if (
            (not input_is_file and current == candidate)
            or _is_relative_to(current, excel_root)
        ):
            return candidate.resolve(strict=False), manifest
    return None, None


def load_project_manifest_for_dataset_path(
    dataset_path: str | Path,
) -> dict[str, Any] | None:
    """Return the owning project manifest, if the path is project-managed."""

    _root, manifest = find_project_manifest_for_dataset_path(dataset_path)
    return manifest


def _nearest_project_manifest_root(dataset_path: str | Path) -> Path | None:
    start = Path(dataset_path).expanduser().resolve(strict=False)
    current = start.parent if start.is_file() else start
    for candidate in (current, *current.parents):
        if (candidate / "project.json").is_file():
            return candidate.resolve(strict=False)
    return None


def _unmanaged_excel_root(dataset_root: Path) -> Path:
    conventional = dataset_root / EXCEL_SUBFOLDER_NAME
    return conventional if conventional.is_dir() else dataset_root


def _read_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DatasetIndexError(f"Unable to read project manifest: {path}") from exc
    if not isinstance(payload, dict):
        raise DatasetIndexError(f"Project manifest must contain a JSON object: {path}")
    return payload


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True
