"""Data loading helpers for the Stats pipelines.

This module belongs to the model/service layer. It scans FPVS project folders,
validates manifests, and provides normalized metadata to the controller and
workers while remaining GUI-agnostic.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Tuple

from Tools.Stats.data.stats_subjects import canonical_subject_id

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
    """Represent the ProjectScanResult part of the Stats tool."""
    subjects: List[str]
    conditions: List[str]
    subject_data: Dict[str, Dict[str, str]]
    manifest: dict | None
    participants_map: Dict[str, str]
    project_root: Path | None = None


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
    """Walk upward from an Excel folder to locate the owning project manifest."""
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
                return None, None
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
            return candidate.resolve(), cfg
    return None, None


def load_project_manifest_for_excel_root(excel_root: Path) -> dict | None:
    """Walk upward from an Excel folder to locate and load project.json."""

    _project_root, manifest = find_project_manifest_for_excel_root(excel_root)
    return manifest


def normalize_participants_map(manifest: dict | None) -> dict[str, str]:
    """Return {SUBJECT_ID -> group_name} using upper-case participant IDs."""

    if not isinstance(manifest, dict):
        return {}
    group_labels = _group_label_aliases(manifest)
    participants = manifest.get("participants", {})
    if not isinstance(participants, dict):
        return {}
    normalized: dict[str, str] = {}
    for pid, info in participants.items():
        if not isinstance(pid, str) or not pid.strip():
            continue
        if not isinstance(info, dict):
            continue
        group = info.get("group_id")
        if group is None:
            group = info.get("group")
        if not isinstance(group, str) or not group.strip():
            continue
        group_key = group.strip()
        normalized[pid.strip().upper()] = group_labels.get(group_key, group_key)

    # Example: manifest participants {"SCP7": "DEFAULT"} and Excel filename
    # "SCP7_Fruit vs Veg_Results.xlsx" (PID "P7").
    # We now add an alias "P7" -> "DEFAULT" so the scan and warning logic
    # sees this as a known subject.
    for pid_raw, group in list(normalized.items()):
        pid_canonical = canonical_subject_id(pid_raw)
        pid_canonical = pid_canonical.strip().upper() if pid_canonical else ""
        if not pid_canonical or pid_canonical == pid_raw:
            continue
        existing_group = normalized.get(pid_canonical)
        if existing_group is None:
            normalized[pid_canonical] = group
        elif existing_group != group:
            logger.warning(
                "Conflicting canonical participant IDs detected: %s (%s) vs %s (%s)",
                pid_raw,
                group,
                pid_canonical,
                existing_group,
            )
    return normalized


def _group_label_aliases(manifest: dict | None) -> dict[str, str]:
    if not isinstance(manifest, dict):
        return {}
    groups = manifest.get("groups")
    if not isinstance(groups, dict):
        return {}
    aliases: dict[str, str] = {}
    for raw_group_id, raw_info in groups.items():
        if not isinstance(raw_group_id, str) or not raw_group_id.strip():
            continue
        info = raw_info if isinstance(raw_info, dict) else {}
        label = str(
            info.get("label")
            or info.get("folder_name")
            or raw_group_id
        ).strip()
        if not label:
            label = raw_group_id.strip()
        for alias in (
            raw_group_id,
            info.get("group_id"),
            info.get("label"),
            info.get("folder_name"),
        ):
            if isinstance(alias, str) and alias.strip():
                aliases[alias.strip()] = label
    return aliases


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
        if name.lower().endswith((".xlsx", ".xls")):
            fpath = os.path.join(folder_path, name)
            try:
                os.rename(fpath, fpath)
            except OSError:
                open_files.append(name)
    return open_files


def _condition_from_manifest_excel_root(filepath: Path, expected_excel_root: Path) -> str | None:
    try:
        rel_parts = filepath.resolve().relative_to(expected_excel_root.resolve()).parts
    except ValueError:
        return None
    if len(rel_parts) < 2:
        return None
    condition = re.sub(r"^\d+\s*[-_]*\s*", "", rel_parts[0]).strip()
    return condition or None


def _group_folder_aliases(manifest: dict | None) -> set[str]:
    if not isinstance(manifest, dict):
        return set()
    aliases = {"default"}
    groups = manifest.get("groups")
    if not isinstance(groups, dict):
        return aliases
    for group_id, info_raw in groups.items():
        info = info_raw if isinstance(info_raw, dict) else {}
        for value in (
            group_id,
            info.get("group_id"),
            info.get("label"),
            info.get("folder_name"),
        ):
            if isinstance(value, str) and value.strip():
                aliases.add(value.strip().casefold())
    return aliases


def _workbook_candidate_score(
    filepath: Path,
    *,
    expected_excel_root: Path | None,
    group_aliases: set[str],
) -> tuple[int, int, int, str]:
    group_folder_score = 0
    nested_score = 0
    if expected_excel_root is not None:
        try:
            rel_parts = filepath.resolve().relative_to(expected_excel_root.resolve()).parts
        except ValueError:
            rel_parts = filepath.parts
    else:
        rel_parts = filepath.parts
    if len(rel_parts) >= 3:
        nested_parts = rel_parts[1:-1]
        nested_score = len(nested_parts)
        if any(str(part).strip().casefold() in group_aliases for part in nested_parts):
            group_folder_score = 1
    try:
        mtime_ns = int(filepath.stat().st_mtime_ns)
    except OSError:
        mtime_ns = 0
    return group_folder_score, nested_score, mtime_ns, str(filepath)


def _prefer_workbook_candidate(
    existing: str | None,
    candidate: Path,
    *,
    expected_excel_root: Path | None,
    group_aliases: set[str],
) -> str:
    if not existing:
        return str(candidate)
    existing_path = Path(existing)
    if _workbook_candidate_score(
        candidate,
        expected_excel_root=expected_excel_root,
        group_aliases=group_aliases,
    ) >= _workbook_candidate_score(
        existing_path,
        expected_excel_root=expected_excel_root,
        group_aliases=group_aliases,
    ):
        return str(candidate)
    return existing


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
        parent_path = Path(parent_folder)
        project_root, manifest = find_project_manifest_for_excel_root(parent_path)
        expected_excel_root = None
        if project_root is not None and manifest is not None:
            results_folder, subfolders = load_manifest_data(project_root, manifest)
            expected_excel_root = resolve_project_subfolder(
                project_root,
                results_folder,
                subfolders,
                "excel",
                "1 - Excel Data Files",
            )
        group_aliases = _group_folder_aliases(manifest)

        for filepath in sorted(parent_path.rglob("*.xlsx")):
            if filepath.name.startswith("~$"):
                continue
            if any(part.lower() in IGNORED_FOLDERS for part in filepath.parts):
                continue
            filename = filepath.name
            match = pid_pattern.search(filename)
            if not match:
                continue
            condition_clean = (
                _condition_from_manifest_excel_root(filepath, expected_excel_root)
                if expected_excel_root is not None
                else None
            )
            if condition_clean is None:
                try:
                    rel_parts = filepath.relative_to(parent_path).parts
                except ValueError:
                    rel_parts = filepath.parts
                if len(rel_parts) >= 2:
                    raw_condition = rel_parts[0]
                elif parent_path.name.strip().casefold() in group_aliases and parent_path.parent != parent_path:
                    raw_condition = parent_path.parent.name
                else:
                    raw_condition = parent_path.name
                condition_clean = re.sub(r"^\d+\s*[-_]*\s*", "", raw_condition).strip()
            if not condition_clean:
                continue

            pid = match.group(1).upper()
            subjects_set.add(pid)
            conditions_set.add(condition_clean)

            subject_data.setdefault(pid, {})
            subject_data[pid][condition_clean] = _prefer_workbook_candidate(
                subject_data[pid].get(condition_clean),
                filepath,
                expected_excel_root=expected_excel_root,
                group_aliases=group_aliases,
            )
    except PermissionError as e:  # noqa: PERF203
        raise ScanError(f"Permission denied to access folder: {parent_folder}\n{e}")
    except Exception as e:  # noqa: BLE001
        raise ScanError(f"Error scanning folder '{parent_folder}': {e}")

    subjects = sorted(subjects_set)
    conditions = sorted(conditions_set)
    return subjects, conditions, subject_data


def load_project_scan(folder: str) -> ProjectScanResult:
    """Handle the load project scan step for the Stats workflow."""
    subjects, conditions, data = scan_folder_simple(folder)
    project_root, manifest = find_project_manifest_for_excel_root(Path(folder))
    participants_map = normalize_participants_map(manifest)
    return ProjectScanResult(
        subjects=subjects,
        conditions=conditions,
        subject_data=data,
        manifest=manifest,
        participants_map=participants_map,
        project_root=project_root,
    )

