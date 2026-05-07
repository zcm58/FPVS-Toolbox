"""Project path helpers for the Plot Generator GUI."""
from __future__ import annotations

import json
from json import JSONDecodeError
from pathlib import Path
from typing import Any

from Main_App.projects.project import EXCEL_SUBFOLDER_NAME, SNR_SUBFOLDER_NAME


def _auto_detect_project_dir() -> Path:
    """Return the nearest ancestor folder containing ``project.json``."""
    path = Path.cwd()
    while not (path / "project.json").is_file():
        if path.parent == path:
            return Path.cwd()
        path = path.parent
    return path


def _load_manifest(root: Path) -> tuple[str | None, dict[str, str]]:
    manifest = root / "project.json"
    if not manifest.is_file():
        return None, {}
    try:
        cfg = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, JSONDecodeError):
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


def _project_paths(
    parent: Any | None,
    project_dir: str | Path | None,
) -> tuple[str | None, str | None]:
    """Return Excel and SNR plot folders for the given or detected project."""
    if project_dir and Path(project_dir).is_dir():
        root = Path(project_dir)
    else:
        proj = getattr(parent, "currentProject", None)
        if proj and hasattr(proj, "project_root"):
            root = Path(proj.project_root)
        else:
            root = _auto_detect_project_dir()

    results_folder, subfolders = _load_manifest(root)
    if results_folder is not None or subfolders:
        try:
            excel_path = _resolve_project_subfolder(
                root, results_folder, subfolders, "excel", EXCEL_SUBFOLDER_NAME
            )
            snr_path = _resolve_project_subfolder(
                root, results_folder, subfolders, "snr", SNR_SUBFOLDER_NAME
            )
            return str(excel_path), str(snr_path)
        except (OSError, RuntimeError, ValueError):
            pass
    fallback_root = root if isinstance(root, Path) else Path(root)
    return (
        str((fallback_root / EXCEL_SUBFOLDER_NAME).resolve()),
        str((fallback_root / SNR_SUBFOLDER_NAME).resolve()),
    )
