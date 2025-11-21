from __future__ import annotations

"""Data loading helpers for the Stats pipelines.

This module belongs to the model/service layer. It scans FPVS project folders,
validates manifests, and provides normalized metadata to the controller and
workers while remaining GUI-agnostic.
"""

import glob
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

# Folders to ignore during scanning (case-insensitive)
IGNORED_FOLDERS = {".fif files", "loreta results"}

EXCEL_PID_REGEX = re.compile(
    r"(P\d+[A-Za-z]*|Sub\d+[A-Za-z]*|S\d+[A-Za-z]*)",
    re.IGNORECASE,
)


class ScanError(Exception):
    """Exception raised when scanning fails due to invalid folder or permissions."""


@dataclass
class ProjectScanResult:
    subjects: List[str]
    conditions: List[str]
    subject_data: Dict[str, Dict[str, str]]
    manifest: dict | None
    participants_map: Dict[str, str]
    subject_groups: Dict[str, str | None]
    multi_group_manifest: bool


def auto_detect_project_dir() -> str:
    """Walk upward to find a folder containing project.json."""

    path = Path.cwd()
    while not (path / "project.json").is_file():
        if path.parent == path:
            return str(Path.cwd())
        path = path.parent
    return str(path)


def load_manifest_data(project_root: Path, cfg: dict | None = None) -> tuple[str | None, dict[str, str]]:
    if cfg is None:
        manifest = project_root / "project.json"
        if not manifest.is_file():
            return None, {}
        cfg = json.loads(manifest.read_text(encoding="utf-8"))
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
    name = subfolders.get(key, default_name)
    candidate = Path(name)
    if candidate.is_absolute():
        return candidate.resolve()
    return (_resolve_results_root(project_root, results_folder) / candidate).resolve()


def load_project_manifest_for_excel_root(excel_root: Path) -> dict | None:
    """Walk upward from an Excel folder to locate and load project.json."""

    try:
        current = excel_root.resolve()
    except Exception:
        current = excel_root
    for candidate in (current, *current.parents):
        manifest = candidate / "project.json"
        if manifest.is_file():
            try:
                cfg = json.loads(manifest.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001
                import logging

                logging.getLogger(__name__).warning("Failed to load manifest %s: %s", manifest, exc)
                return None
            try:
                results_folder, subfolders = load_manifest_data(candidate, cfg)
                expected_excel = resolve_project_subfolder(
                    candidate,
                    results_folder,
                    subfolders,
                    "excel",
                    "1 - Excel Data Files",
                )
                expected_resolved = expected_excel.resolve()
            except Exception:
                expected_resolved = None
            if expected_resolved is not None:
                allowed = {current, *current.parents}
                if expected_resolved not in allowed:
                    continue
            return cfg
    return None


def normalize_participants_map(manifest: dict | None) -> dict[str, str]:
    """Return {SUBJECT_ID -> group_name} using upper-case participant IDs."""

    if not isinstance(manifest, dict):
        return {}
    participants = manifest.get("participants", {})
    if not isinstance(participants, dict):
        return {}
    normalized: dict[str, str] = {}
    for pid, info in participants.items():
        if not isinstance(pid, str) or not pid.strip():
            continue
        if not isinstance(info, dict):
            continue
        group = info.get("group")
        if not isinstance(group, str) or not group.strip():
            continue
        normalized[pid.strip().upper()] = group.strip()
    return normalized


def map_subjects_to_groups(subjects: Iterable[str], participants_map: dict[str, str]) -> dict[str, str | None]:
    return {pid: participants_map.get(pid.upper()) for pid in subjects}


def has_multi_groups(manifest: dict | None) -> bool:
    if not isinstance(manifest, dict):
        return False
    groups = manifest.get("groups")
    return isinstance(groups, dict) and bool(groups)


def scan_folder_simple(parent_folder: str) -> Tuple[List[str], List[str], Dict[str, Dict[str, str]]]:
    """
    Scans the given parent folder for subject Excel files and condition subfolders.

    Args:
        parent_folder: Path to the folder containing one subfolder per condition.

    Returns:
        subjects: sorted list of subject IDs (e.g., ["P01", "P02", ...])
        conditions: sorted list of condition names (folder names cleaned)
        subject_data: mapping {subject_id: {condition_name: full_file_path}}

    Raises:
        ScanError: if the folder is invalid or access is denied.
    """

    if not parent_folder or not os.path.isdir(parent_folder):
        raise ScanError(f"Invalid or missing parent folder: {parent_folder}")

    subjects_set = set()
    conditions_set = set()
    subject_data: Dict[str, Dict[str, str]] = {}

    pid_pattern = EXCEL_PID_REGEX

    try:
        for entry in os.listdir(parent_folder):
            entry_path = os.path.join(parent_folder, entry)
            if not os.path.isdir(entry_path):
                continue
            if entry.lower() in IGNORED_FOLDERS:
                continue

            condition_clean = re.sub(r"^\d+\s*[-_]*\s*", "", entry).strip()
            if not condition_clean:
                continue

            pattern = os.path.join(entry_path, "*.xlsx")
            for filepath in glob.glob(pattern):
                filename = os.path.basename(filepath)
                match = pid_pattern.search(filename)
                if not match:
                    continue
                pid = match.group(1).upper()
                subjects_set.add(pid)
                conditions_set.add(condition_clean)

                subject_data.setdefault(pid, {})
                subject_data[pid][condition_clean] = filepath
    except PermissionError as e:  # noqa: PERF203
        raise ScanError(f"Permission denied to access folder: {parent_folder}\n{e}")
    except Exception as e:  # noqa: BLE001
        raise ScanError(f"Error scanning folder '{parent_folder}': {e}")

    subjects = sorted(subjects_set)
    conditions = sorted(conditions_set)
    return subjects, conditions, subject_data


def load_project_scan(folder: str) -> ProjectScanResult:
    subjects, conditions, data = scan_folder_simple(folder)
    manifest = load_project_manifest_for_excel_root(Path(folder))
    participants_map = normalize_participants_map(manifest)
    subject_groups = map_subjects_to_groups(subjects, participants_map)
    multi_group_manifest = has_multi_groups(manifest)
    return ProjectScanResult(
        subjects=subjects,
        conditions=conditions,
        subject_data=data,
        manifest=manifest,
        participants_map=participants_map,
        subject_groups=subject_groups,
        multi_group_manifest=multi_group_manifest,
    )

