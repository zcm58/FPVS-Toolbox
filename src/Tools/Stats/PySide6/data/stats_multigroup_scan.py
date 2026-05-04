"""Read-only multi-group scan helpers for the Stats tool."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from Tools.Stats.PySide6.data.stats_data_loader import IGNORED_FOLDERS
from Tools.Stats.PySide6.data.stats_multigroup_ids import (
    build_multigroup_pid_warning,
    canonical_multigroup_pid_sort_key,
    extract_multigroup_pid,
    normalize_multigroup_manifest_groups,
)

logger = logging.getLogger("Tools.Stats")


def _pid_sort_key(pid: str) -> tuple[int, str]:
    """Handle the pid sort key step for the Stats PySide6 workflow."""
    return canonical_multigroup_pid_sort_key(pid)


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
    match, warnings = extract_multigroup_pid(text)
    if match is None:
        return None, [_build_issue("blocking", "PID parse failure.", context)]

    issues = [_build_issue("warning", message, context) for message in warnings]
    return match.canonical_id, issues


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
    if not isinstance(manifest, dict):
        return {}, []

    mapping, normalization_examples, manifest_issues = normalize_multigroup_manifest_groups(manifest)
    issues: list[ScanIssue] = []

    for issue in manifest_issues:
        context = dict(issue.context)
        if "raw_pid" in context and "pid" not in context:
            context["pid"] = context["raw_pid"]

        if issue.kind == "missing_participants_mapping":
            issues.append(
                _build_issue("blocking", "project.json participants mapping is missing or invalid.")
            )
        elif issue.kind == "missing_groups_mapping":
            issues.append(_build_issue("blocking", "project.json groups mapping is missing or invalid."))
        elif issue.kind == "invalid_pid":
            issues.append(
                _build_issue(
                    "blocking",
                    "Participant ID does not match the supported multigroup P<n> format.",
                    context,
                )
            )
        elif issue.kind == "missing_group":
            issues.append(
                _build_issue(
                    "blocking",
                    "Participant entry is missing a group assignment.",
                    context,
                )
            )
        elif issue.kind == "undefined_group":
            issues.append(
                _build_issue(
                    "blocking",
                    "Participant group is not defined in project.json groups.",
                    context,
                )
            )
        elif issue.kind == "conflicting_group_assignment":
            issues.append(
                _build_issue(
                    "blocking",
                    "Conflicting manifest participant IDs collapse to the same canonical PID.",
                    context,
                )
            )

    warning_message = build_multigroup_pid_warning(
        normalization_examples,
        surface_label="multigroup manifest",
    )
    if warning_message:
        issues.append(_build_issue("warning", warning_message))

    return mapping, issues


def _scan_excel_folder(excel_root: Path) -> tuple[list[str], list[ScanIssue]]:
    """Handle the scan excel folder step for the Stats PySide6 workflow."""
    issues: list[ScanIssue] = []
    discovered: set[str] = set()
    normalization_examples: dict[str, str] = {}

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
                pid_match, pid_warnings = extract_multigroup_pid(file_path.name)
                if pid_match is None:
                    issues.append(
                        _build_issue(
                            "blocking",
                            "PID parse failure.",
                            {"path": str(file_path)},
                        )
                    )
                    continue
                if pid_match.matched_text != pid_match.canonical_id:
                    normalization_examples[pid_match.matched_text] = pid_match.canonical_id
                issues.extend(
                    _build_issue("warning", message, {"path": str(file_path)})
                    for message in pid_warnings
                )
                discovered.add(pid_match.canonical_id)
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

    warning_message = build_multigroup_pid_warning(
        normalization_examples,
        surface_label="multigroup scan",
    )
    if warning_message:
        issues.append(_build_issue("warning", warning_message))

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
