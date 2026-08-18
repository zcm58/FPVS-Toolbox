"""Project path helpers for the Plot Generator GUI."""
from __future__ import annotations

from pathlib import Path

from Main_App.projects import DatasetIndexError, load_project_manifest_for_dataset_path


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(parent.resolve(strict=False))
    except ValueError:
        return False
    return True


def _auto_detect_project_dir() -> Path:
    """Return the nearest ancestor folder containing ``project.json``."""
    path = Path.cwd()
    while not (path / "project.json").is_file():
        if path.parent == path:
            return Path.cwd()
        path = path.parent
    return path


def _load_manifest(root: Path) -> tuple[str | None, dict[str, str]]:
    try:
        cfg = load_project_manifest_for_dataset_path(root)
    except DatasetIndexError:
        return None, {}
    if not isinstance(cfg, dict):
        return None, {}
    results_folder = cfg.get("results_folder")
    if not isinstance(results_folder, str):
        results_folder = None
    subfolders = cfg.get("subfolders", {})
    if not isinstance(subfolders, dict):
        subfolders = {}
    normalized: dict[str, str] = {}
    for key, value in subfolders.items():
        if isinstance(value, str):
            normalized[key] = value
    return results_folder, normalized


def _resolve_results_root(project_root: Path, results_folder: str | None) -> Path:
    if results_folder:
        folder = Path(results_folder)
        if not folder.is_absolute():
            folder = project_root / folder
    else:
        folder = project_root
    return folder.resolve()


def _resolve_project_subfolder(
    project_root: Path,
    results_folder: str | None,
    subfolders: dict[str, str],
    key: str,
    default_name: str,
) -> Path:
    name = subfolders.get(key, default_name)
    candidate = Path(name)
    if candidate.is_absolute():
        return candidate.resolve()
    return (_resolve_results_root(project_root, results_folder) / candidate).resolve()
