"""Read-only multi-group scan helpers for the Stats tool."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Iterable

from Tools.Stats.PySide6.stats_data_loader import IGNORED_FOLDERS

logger = logging.getLogger("Tools.Stats")

PID_REGEX = re.compile(r"(?i)p0*(\d+)(?!\d)")


def _pid_sort_key(pid: str) -> tuple[int, str]:
    """Handle the pid sort key step for the Stats PySide6 workflow."""
    match = PID_REGEX.search(pid or "")
    if match:
        return int(match.group(1)), str(pid)
    return 10**9, str(pid)


@dataclass(frozen=True)
class ScanIssue:
    """Represent the ScanIssue part of the Stats PySide6 tool."""
    severity: str
    message: str
    context: dict[str, str]


@dataclass(frozen=True)
class MultiGroupScanResult:
    """Represent the MultiGroupScanResult part of the Stats PySide6 tool."""
    subject_groups: list[str]
    group_to_subjects: dict[str, list[str]]
    unassigned_subjects: list[str]
    issues: list[ScanIssue]
    multi_group_ready: bool
    discovered_subjects: list[str]
    assigned_subjects: list[str]


def _build_issue(severity: str, message: str, context: dict[str, str] | None = None) -> ScanIssue:
    """Handle the build issue step for the Stats PySide6 workflow."""
    return ScanIssue(severity=severity, message=message, context=context or {})


def extract_canonical_pid(text: str, *, context: dict[str, str] | None = None) -> tuple[str | None, list[ScanIssue]]:
    """Handle the extract canonical pid step for the Stats PySide6 workflow."""
    matches = list(PID_REGEX.finditer(text or ""))
    if not matches:
        return None, [_build_issue("blocking", "PID parse failure.", context)]

    if len(matches) > 1:
        warning = _build_issue("warning", "Multiple PID matches found; using the first.", context)
    else:
        warning = None

    pid_value = int(matches[0].group(1))
    canonical = f"P{pid_value}"
    issues = [warning] if warning else []
    return canonical, issues


def _load_manifest(project_root: Path) -> tuple[dict | None, list[ScanIssue]]:
    """Handle the load manifest step for the Stats PySide6 workflow."""
    issues: list[ScanIssue] = []
    manifest_path = project_root / "project.json"
    if not manifest_path.is_file():
        issues.append(
            _build_issue(
                "blocking",
                "project.json is missing.",
                {"path": str(manifest_path)},
            )
        )
        return None, issues

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        issues.append(
            _build_issue(
                "blocking",
                f"project.json unreadable: {exc}",
                {"path": str(manifest_path)},
            )
        )
        return None, issues

    if not isinstance(manifest, dict):
        issues.append(
            _build_issue(
                "blocking",
                "project.json does not contain a JSON object.",
                {"path": str(manifest_path)},
            )
        )
        return None, issues

    return manifest, issues


def _parse_manifest_participants(manifest: dict | None) -> tuple[dict[str, str], list[ScanIssue]]:
    """Handle the parse manifest participants step for the Stats PySide6 workflow."""
    issues: list[ScanIssue] = []
    if not isinstance(manifest, dict):
        return {}, issues

    participants = manifest.get("participants")
    if not isinstance(participants, dict):
        issues.append(_build_issue("blocking", "project.json participants mapping is missing or invalid."))
        return {}, issues

    groups = manifest.get("groups")
    valid_groups = set(groups.keys()) if isinstance(groups, dict) else set()
    if not isinstance(groups, dict):
        issues.append(_build_issue("blocking", "project.json groups mapping is missing or invalid."))

    mapping: dict[str, str] = {}
    canonical_sources: dict[str, str] = {}

    for raw_pid, raw_info in participants.items():
        pid_text = raw_pid if isinstance(raw_pid, str) else str(raw_pid)
        pid_context = {"pid": pid_text}
        canonical_pid, pid_issues = extract_canonical_pid(pid_text, context=pid_context)
        issues.extend(pid_issues)
        if not canonical_pid:
            continue

        group_name = None
        if isinstance(raw_info, dict):
            group_name = raw_info.get("group")
        if not isinstance(group_name, str) or not group_name.strip():
            issues.append(
                _build_issue(
                    "blocking",
                    "Participant entry is missing a group assignment.",
                    {"pid": canonical_pid},
                )
            )
            continue
        group_name = group_name.strip()
        if group_name not in valid_groups:
            issues.append(
                _build_issue(
                    "blocking",
                    "Participant group is not defined in project.json groups.",
                    {"pid": canonical_pid, "group": group_name},
                )
            )
            continue

        existing = mapping.get(canonical_pid)
        if existing is not None:
            if canonical_sources.get(canonical_pid) != pid_text:
                issues.append(
                    _build_issue(
                        "blocking",
                        "Duplicate manifest participant IDs collapse to the same canonical PID.",
                        {"pid": canonical_pid},
                    )
                )
            continue

        mapping[canonical_pid] = group_name
        canonical_sources[canonical_pid] = pid_text

    return mapping, issues


def _scan_excel_folder(excel_root: Path) -> tuple[list[str], list[ScanIssue]]:
    """Handle the scan excel folder step for the Stats PySide6 workflow."""
    issues: list[ScanIssue] = []
    discovered: set[str] = set()

    if not excel_root.exists() or not excel_root.is_dir():
        issues.append(
            _build_issue(
                "blocking",
                "Excel input folder is missing or unreadable.",
                {"path": str(excel_root)},
            )
        )
        return [], issues

    try:
        for entry in excel_root.iterdir():
            if not entry.is_dir():
                continue
            if entry.name.lower() in IGNORED_FOLDERS:
                continue
            for file_path in entry.iterdir():
                if file_path.suffix.lower() not in (".xlsx", ".xls"):
                    continue
                canonical_pid, pid_issues = extract_canonical_pid(
                    file_path.name,
                    context={"path": str(file_path)},
                )
                issues.extend(pid_issues)
                if not canonical_pid:
                    continue
                discovered.add(canonical_pid)
    except PermissionError as exc:
        issues.append(
            _build_issue(
                "blocking",
                f"Permission denied while scanning Excel folder: {exc}",
                {"path": str(excel_root)},
            )
        )
    except Exception as exc:  # noqa: BLE001
        issues.append(
            _build_issue(
                "blocking",
                f"Failed to scan Excel folder: {exc}",
                {"path": str(excel_root)},
            )
        )

    return sorted(discovered, key=_pid_sort_key), issues


def _sorted_groups_from_mapping(group_map: dict[str, list[str]]) -> list[str]:
    """Handle the sorted groups from mapping step for the Stats PySide6 workflow."""
    return sorted(group_map.keys())


def _build_group_to_subjects(
    discovered: Iterable[str],
    manifest_map: dict[str, str],
) -> dict[str, list[str]]:
    """Handle the build group to subjects step for the Stats PySide6 workflow."""
    group_to_subjects: dict[str, list[str]] = {}
    for pid in discovered:
        group = manifest_map.get(pid)
        if not group:
            continue
        group_to_subjects.setdefault(group, []).append(pid)

    for group, subjects in group_to_subjects.items():
        group_to_subjects[group] = sorted(set(subjects), key=_pid_sort_key)
    return group_to_subjects


def scan_multigroup_readiness(project_root: Path, excel_root: Path) -> MultiGroupScanResult:
    """Handle the scan multigroup readiness step for the Stats PySide6 workflow."""
    issues: list[ScanIssue] = []

    manifest, manifest_issues = _load_manifest(project_root)
    issues.extend(manifest_issues)

    participants_map, participant_issues = _parse_manifest_participants(manifest)
    issues.extend(participant_issues)

    discovered_subjects, scan_issues = _scan_excel_folder(excel_root)
    issues.extend(scan_issues)

    group_to_subjects = _build_group_to_subjects(discovered_subjects, participants_map)
    subject_groups = _sorted_groups_from_mapping(group_to_subjects)

    assigned_subjects = sorted(
        {pid for subjects in group_to_subjects.values() for pid in subjects},
        key=_pid_sort_key,
    )

    unassigned_subjects = sorted(
        (pid for pid in discovered_subjects if pid not in participants_map),
        key=_pid_sort_key,
    )
    for pid in unassigned_subjects:
        issues.append(
            _build_issue(
                "warning",
                "Subject discovered in Excel outputs but not in manifest participants.",
                {"pid": pid},
            )
        )

    manifest_only = sorted(
        (pid for pid in participants_map if pid not in discovered_subjects),
        key=_pid_sort_key,
    )
    for pid in manifest_only:
        issues.append(
            _build_issue(
                "warning",
                "Subject listed in manifest has no Excel outputs.",
                {"pid": pid},
            )
        )

    blocking_issues = [issue for issue in issues if issue.severity == "blocking"]
    multi_group_ready = len(subject_groups) >= 2 and not blocking_issues

    result = MultiGroupScanResult(
        subject_groups=subject_groups,
        group_to_subjects=group_to_subjects,
        unassigned_subjects=unassigned_subjects,
        issues=issues,
        multi_group_ready=multi_group_ready,
        discovered_subjects=sorted(discovered_subjects, key=_pid_sort_key),
        assigned_subjects=assigned_subjects,
    )

    logger.info(
        "stats_multigroup_scan_complete",
        extra={
            "project_root": str(project_root),
            "excel_root": str(excel_root),
            "discovered_subjects": len(discovered_subjects),
            "assigned_subjects": len(assigned_subjects),
            "groups_with_subjects": len(subject_groups),
            "issues": len(issues),
            "blocking_issues": len(blocking_issues),
            "multi_group_ready": multi_group_ready,
        },
    )
    return result


def run_multigroup_scan_worker(
    _progress_emit,
    _message_emit,
    *,
    project_root: Path,
    excel_root: Path,
) -> MultiGroupScanResult:
    """Handle the run multigroup scan worker step for the Stats PySide6 workflow."""
    return scan_multigroup_readiness(project_root, excel_root)


__all__ = [
    "MultiGroupScanResult",
    "ScanIssue",
    "extract_canonical_pid",
    "scan_multigroup_readiness",
    "run_multigroup_scan_worker",
]
