"""Data loading helpers for the Stats pipelines.

This module belongs to the model/service layer. It scans FPVS project folders,
validates manifests, and provides normalized metadata to the controller and
workers while remaining GUI-agnostic.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Tuple

from Main_App.Shared.file_filters import is_excel_workbook_file
from Main_App.projects import (
    DatasetDiagnostic,
    DatasetIndexError,
    find_project_manifest_for_dataset_path,
    is_multi_group_manifest,
    load_project_dataset_index,
    load_project_manifest_for_dataset_path,
    participant_group_label_map_from_manifest,
)


class ScanError(Exception):
    """Exception raised when scanning fails due to invalid folder or permissions."""


@dataclass
class ProjectScanResult:
    """Represent the ProjectScanResult part of the Stats tool."""
    subjects: List[str]
    conditions: List[str]
    subject_data: Dict[str, Dict[str, str]]
    manifest: dict | None
    participants_map: Dict[str, str]
    project_root: Path | None = None
    project_is_multi_group: bool = False


logger = logging.getLogger(__name__)


def auto_detect_project_dir() -> str:
    """Walk upward to find a folder containing project.json."""

    path = Path.cwd()
    while not (path / "project.json").is_file():
        if path.parent == path:
            return str(Path.cwd())
        path = path.parent
    return str(path)


def load_manifest_data(project_root: Path, cfg: dict | None = None) -> tuple[str | None, dict[str, str]]:
    """Handle the load manifest data step for the Stats workflow."""
    if cfg is None:
        cfg = load_project_manifest_for_dataset_path(project_root)
        if cfg is None:
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
    """Handle the resolve results root step for the Stats workflow."""
    if results_folder:
        base = Path(results_folder)
        if not base.is_absolute():
            base = project_root / base
    else:
        base = project_root
    return base.resolve()


def resolve_project_subfolder(
    project_root: Path,
    results_folder: str | None,
    subfolders: dict[str, str],
    key: str,
    default_name: str,
) -> Path:
    """Handle the resolve project subfolder step for the Stats workflow."""
    name = subfolders.get(key, default_name)
    candidate = Path(name)
    if candidate.is_absolute():
        return candidate.resolve()
    return (_resolve_results_root(project_root, results_folder) / candidate).resolve()


def find_project_manifest_for_excel_root(excel_root: Path) -> tuple[Path, dict] | tuple[None, None]:
    """Compatibility wrapper for shared project-manifest discovery."""

    return find_project_manifest_for_dataset_path(excel_root)


def load_project_manifest_for_excel_root(excel_root: Path) -> dict | None:
    """Compatibility wrapper for shared project-manifest discovery."""

    return load_project_manifest_for_dataset_path(excel_root)


def is_multi_group_project_config(manifest: dict | None) -> bool:
    """Compatibility wrapper for canonical multi-group detection."""

    return is_multi_group_manifest(manifest)


def normalize_participants_map(manifest: dict | None) -> dict[str, str]:
    """Return the shared display-label compatibility map."""

    return participant_group_label_map_from_manifest(manifest)


def map_subjects_to_groups(subjects: Iterable[str], participants_map: dict[str, str]) -> dict[str, str | None]:
    """Handle the map subjects to groups step for the Stats workflow."""
    return {pid: participants_map.get(pid.upper()) for pid in subjects}


def safe_export_call(
    func: Callable[..., None],
    data_obj,
    out_dir: str | Path,
    base_name: str,
    *,
    log_func: Callable[[str], None],
) -> Path:
    """Invoke an export helper, handling legacy signatures and paths.

    Tries the modern signature first:
        func(data_obj, save_path=path, log_func=log_func)

    If that raises TypeError, fall back to the legacy form:
        func(data_obj, out_dir, log_func=log_func)

    Returns the Path that should contain the exported Excel file.
    """

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    fname = base_name if str(base_name).lower().endswith(".xlsx") else f"{base_name}.xlsx"
    save_path = out_path / fname

    log_func(f"Exporting {base_name} to {save_path}")

    try:
        try:
            # Preferred modern signature
            func(data_obj, save_path=save_path, log_func=log_func)
        except TypeError:
            # Legacy signature that expects an output directory instead of a file path
            func(data_obj, str(out_path), log_func=log_func)
    except Exception as exc:  # noqa: BLE001
        log_func(f"Export failed for {base_name}: {exc}")
        raise

    log_func(f"Export completed for {base_name}")
    return save_path



def ensure_results_dir(
    project_root: Path,
    results_folder_hint: str | None,
    subfolder_hints: dict[str, str],
    *,
    results_subfolder_name: str,
    subfolder_key: str = "stats",
) -> Path:
    """Compute and create the Stats results directory."""

    if not project_root.exists():
        logger.warning(
            "ensure_results_dir called with non-existent project_root: %s",
            project_root,
        )

    target = resolve_project_subfolder(
        project_root,
        results_folder_hint,
        subfolder_hints,
        subfolder_key,
        results_subfolder_name,
    )

    target.mkdir(parents=True, exist_ok=True)

    logger.info("ensure_results_dir using results directory: %s", target)

    return target



def check_for_open_excel_files(folder_path: str) -> list[str]:
    """Return Excel filenames that appear to be open (Windows rename guard)."""

    if not folder_path or not os.path.isdir(folder_path):
        return []

    open_files: list[str] = []
    for name in os.listdir(folder_path):
        if is_excel_workbook_file(name, suffixes=(".xlsx", ".xls")):
            fpath = os.path.join(folder_path, name)
            try:
                os.rename(fpath, fpath)
            except OSError:
                open_files.append(name)
    return open_files


def scan_folder_simple(parent_folder: str) -> Tuple[List[str], List[str], Dict[str, Dict[str, str]]]:
    """Return the legacy Stats scan shape from the shared dataset index."""

    if not parent_folder:
        raise ScanError(f"Invalid or missing parent folder: {parent_folder}")
    try:
        index = load_project_dataset_index(parent_folder)
    except DatasetIndexError as exc:
        raise ScanError(str(exc)) from exc
    _log_dataset_index_diagnostics(index.diagnostics)
    return (
        list(index.participant_ids),
        list(index.conditions),
        index.subject_data(),
    )


def _log_dataset_index_diagnostics(
    diagnostics: Iterable[DatasetDiagnostic],
) -> None:
    for diagnostic in diagnostics:
        logger.warning(
            "stats_dataset_index_diagnostic code=%s message=%s paths=%s",
            diagnostic.code,
            diagnostic.message,
            [str(path) for path in diagnostic.paths],
        )


def load_project_scan(folder: str) -> ProjectScanResult:
    """Handle the load project scan step for the Stats workflow."""
    try:
        index = load_project_dataset_index(folder)
    except DatasetIndexError as exc:
        raise ScanError(str(exc)) from exc
    _log_dataset_index_diagnostics(index.diagnostics)
    manifest = dict(index.manifest) if index.manifest is not None else None
    return ProjectScanResult(
        subjects=list(index.participant_ids),
        conditions=list(index.conditions),
        subject_data=index.subject_data(),
        manifest=manifest,
        participants_map=index.participant_group_label_map(
            uppercase_keys=True,
            include_legacy_aliases=True,
        ),
        project_root=index.project_root if index.manifest is not None else None,
        project_is_multi_group=index.is_multi_group,
    )
