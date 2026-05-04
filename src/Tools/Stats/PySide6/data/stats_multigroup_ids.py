"""Canonical participant-ID helpers for the supported multigroup workflow."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

_STRICT_PID_PATTERN = re.compile(r"^[Pp](\d+)$")
_SEARCH_PID_PATTERN = re.compile(r"[Pp]\d+")


@dataclass(frozen=True)
class MultigroupPidMatch:
    """Normalized participant-ID match for the multigroup workflow."""

    raw_input: str
    matched_text: str
    canonical_id: str
    zero_padded: bool


@dataclass(frozen=True)
class MultigroupManifestIssue:
    """Represent a manifest normalization issue for multigroup PID handling."""

    kind: str
    context: dict[str, str]


@dataclass(frozen=True)
class MultigroupRuntimeSnapshot:
    """Canonical multigroup runtime view derived from raw scan data."""

    subjects: list[str]
    subject_data: dict[str, dict[str, str]]
    subject_groups: dict[str, str | None]
    warnings: list[str]
    errors: list[str]


def normalize_multigroup_pid(raw_id: str | None) -> MultigroupPidMatch | None:
    """Normalize a strict multigroup participant ID to canonical ``P<n>`` form."""

    if not isinstance(raw_id, str):
        return None
    text = raw_id.strip()
    if not text:
        return None

    match = _STRICT_PID_PATTERN.fullmatch(text)
    if not match:
        return None

    digits = match.group(1)
    value = int(digits)
    if value <= 0:
        return None

    return MultigroupPidMatch(
        raw_input=text,
        matched_text=text,
        canonical_id=f"P{value}",
        zero_padded=len(digits) > 1 and digits.startswith("0"),
    )


def extract_multigroup_pid(text: str | None) -> tuple[MultigroupPidMatch | None, list[str]]:
    """Extract and normalize the first multigroup participant ID found in free text."""

    if not isinstance(text, str):
        return None, []
    raw_text = text.strip()
    if not raw_text:
        return None, []

    matches: list[MultigroupPidMatch] = []
    for match in _SEARCH_PID_PATTERN.finditer(raw_text):
        normalized = normalize_multigroup_pid(match.group(0))
        if normalized is None:
            continue
        matches.append(
            MultigroupPidMatch(
                raw_input=raw_text,
                matched_text=match.group(0),
                canonical_id=normalized.canonical_id,
                zero_padded=normalized.zero_padded,
            )
        )

    if not matches:
        return None, []

    warnings: list[str] = []
    if len(matches) > 1:
        warnings.append("Multiple PID matches found; using the first.")
    return matches[0], warnings


def canonical_multigroup_pid_sort_key(pid: str) -> tuple[int, str]:
    """Sort canonical multigroup participant IDs numerically when possible."""

    strict_match = normalize_multigroup_pid(pid)
    if strict_match is not None:
        return int(strict_match.canonical_id[1:]), str(pid)

    extracted, _warnings = extract_multigroup_pid(str(pid) if pid is not None else "")
    if extracted is not None:
        return int(extracted.canonical_id[1:]), str(pid)

    return 10**9, str(pid)


def build_multigroup_pid_warning(
    examples: dict[str, str] | Iterable[tuple[str, str]],
    *,
    surface_label: str,
) -> str | None:
    """Build a single non-blocking warning for multigroup PID normalization."""

    items = examples.items() if isinstance(examples, dict) else examples
    normalized_examples: list[tuple[str, str]] = []
    for raw, canonical in items:
        if not isinstance(raw, str) or not isinstance(canonical, str):
            continue
        raw_text = raw.strip()
        canonical_text = canonical.strip()
        if not raw_text or not canonical_text:
            continue
        normalized_examples.append((raw_text, canonical_text))

    if not normalized_examples:
        return None

    normalized_examples.sort(key=lambda item: canonical_multigroup_pid_sort_key(item[1]))
    example_raw, example_canonical = next(
        (item for item in normalized_examples if item[0] != item[1]),
        normalized_examples[0],
    )
    return (
        "Non-canonical participant IDs were normalized internally for this "
        f"{surface_label} (e.g. {example_raw} -> {example_canonical}). "
        "Canonical format is P1, P2, P3, ... The app extracted participant tokens "
        "internally and left source files/manifests unchanged."
    )


def normalize_multigroup_manifest_groups(
    manifest: dict | None,
) -> tuple[dict[str, str], dict[str, str], list[MultigroupManifestIssue]]:
    """Normalize manifest participant IDs and preserve multigroup group assignments."""

    if not isinstance(manifest, dict):
        return {}, {}, []

    issues: list[MultigroupManifestIssue] = []
    participants = manifest.get("participants")
    if not isinstance(participants, dict):
        issues.append(MultigroupManifestIssue("missing_participants_mapping", {}))
        return {}, {}, issues

    groups = manifest.get("groups")
    valid_groups = set(groups.keys()) if isinstance(groups, dict) else set()
    if not isinstance(groups, dict):
        issues.append(MultigroupManifestIssue("missing_groups_mapping", {}))

    mapping: dict[str, str] = {}
    normalization_examples: dict[str, str] = {}
    raw_ids_by_canonical: dict[str, set[str]] = {}

    for raw_pid, raw_info in participants.items():
        pid_text = raw_pid if isinstance(raw_pid, str) else str(raw_pid)
        pid_match, _pid_warnings = extract_multigroup_pid(pid_text)
        if pid_match is None:
            issues.append(
                MultigroupManifestIssue(
                    "invalid_pid",
                    {"raw_pid": pid_text},
                )
            )
            continue

        canonical_pid = pid_match.canonical_id
        if pid_match.raw_input != canonical_pid:
            normalization_examples[pid_match.raw_input] = canonical_pid

        group_name = raw_info.get("group") if isinstance(raw_info, dict) else None
        if not isinstance(group_name, str) or not group_name.strip():
            issues.append(
                MultigroupManifestIssue(
                    "missing_group",
                    {"raw_pid": pid_text, "pid": canonical_pid},
                )
            )
            continue

        group_name = group_name.strip()
        if isinstance(groups, dict) and group_name not in valid_groups:
            issues.append(
                MultigroupManifestIssue(
                    "undefined_group",
                    {"raw_pid": pid_text, "pid": canonical_pid, "group": group_name},
                )
            )
            continue

        raw_ids_by_canonical.setdefault(canonical_pid, set()).add(pid_text)
        existing_group = mapping.get(canonical_pid)
        if existing_group is None:
            mapping[canonical_pid] = group_name
            continue

        if existing_group != group_name:
            issues.append(
                MultigroupManifestIssue(
                    "conflicting_group_assignment",
                    {
                        "raw_pid": pid_text,
                        "pid": canonical_pid,
                        "group": group_name,
                        "existing_group": existing_group,
                        "raw_ids": ", ".join(sorted(raw_ids_by_canonical[canonical_pid])),
                    },
                )
            )

    return mapping, normalization_examples, issues


def build_multigroup_runtime_snapshot(
    *,
    manifest: dict | None,
    subjects: list[str] | None,
    subject_data: dict[str, dict[str, str]] | None,
) -> MultigroupRuntimeSnapshot:
    """Build a canonical multigroup runtime snapshot from raw scan output."""

    manifest_map, normalization_examples, manifest_issues = normalize_multigroup_manifest_groups(manifest)
    errors = [_format_manifest_issue(issue) for issue in manifest_issues]

    raw_subject_data = subject_data if isinstance(subject_data, dict) else {}
    raw_subjects: list[str] = []
    seen_raw_subjects: set[str] = set()
    for raw_pid in list(subjects or []) + list(raw_subject_data.keys()):
        pid_text = raw_pid if isinstance(raw_pid, str) else str(raw_pid)
        if pid_text in seen_raw_subjects:
            continue
        raw_subjects.append(pid_text)
        seen_raw_subjects.add(pid_text)

    canonical_subjects: set[str] = set()
    canonical_subject_data: dict[str, dict[str, str]] = {}
    raw_aliases: dict[str, set[str]] = {}

    for raw_pid in raw_subjects:
        normalized_pid = normalize_multigroup_pid(raw_pid)
        if normalized_pid is None:
            errors.append(
                f"Discovered participant ID '{raw_pid}' does not match the supported multigroup P<n> format."
            )
            continue

        canonical_pid = normalized_pid.canonical_id
        canonical_subjects.add(canonical_pid)
        raw_aliases.setdefault(canonical_pid, set()).add(normalized_pid.raw_input)
        if normalized_pid.raw_input != canonical_pid:
            normalization_examples[normalized_pid.raw_input] = canonical_pid

        condition_map = raw_subject_data.get(raw_pid, {})
        if not isinstance(condition_map, dict):
            continue

        target_map = canonical_subject_data.setdefault(canonical_pid, {})
        for condition_name, file_path in condition_map.items():
            condition_text = str(condition_name)
            file_path_text = str(file_path)
            existing_path = target_map.get(condition_text)
            if existing_path is not None and existing_path != file_path_text:
                alias_list = ", ".join(sorted(raw_aliases.get(canonical_pid, {canonical_pid})))
                errors.append(
                    "Conflicting discovered participant records collapse to "
                    f"{canonical_pid} for condition '{condition_text}' "
                    f"(raw IDs: {alias_list})."
                )
                continue
            target_map[condition_text] = file_path_text

    canonical_subject_list = sorted(canonical_subjects, key=canonical_multigroup_pid_sort_key)
    canonical_group_map = {pid: manifest_map.get(pid) for pid in canonical_subject_list}

    warnings: list[str] = []
    warning_message = build_multigroup_pid_warning(
        normalization_examples,
        surface_label="multigroup load",
    )
    if warning_message:
        warnings.append(warning_message)

    return MultigroupRuntimeSnapshot(
        subjects=canonical_subject_list,
        subject_data=canonical_subject_data,
        subject_groups=canonical_group_map,
        warnings=warnings,
        errors=_dedupe_messages(errors),
    )


def _format_manifest_issue(issue: MultigroupManifestIssue) -> str:
    """Convert a normalized manifest issue into a user-facing error string."""

    context = issue.context
    if issue.kind == "missing_participants_mapping":
        return "project.json participants mapping is missing or invalid for the multigroup workflow."
    if issue.kind == "missing_groups_mapping":
        return "project.json groups mapping is missing or invalid for the multigroup workflow."
    if issue.kind == "invalid_pid":
        return (
            "Manifest participant ID "
            f"'{context.get('raw_pid', '')}' does not match the supported multigroup P<n> format."
        )
    if issue.kind == "missing_group":
        return (
            "Manifest participant "
            f"{context.get('pid', context.get('raw_pid', ''))} is missing a group assignment."
        )
    if issue.kind == "undefined_group":
        return (
            "Manifest participant "
            f"{context.get('pid', context.get('raw_pid', ''))} references undefined group "
            f"'{context.get('group', '')}'."
        )
    if issue.kind == "conflicting_group_assignment":
        return (
            "Conflicting manifest participant IDs collapse to canonical participant "
            f"{context.get('pid', '')}: raw IDs {context.get('raw_ids', '')} map to multiple groups "
            f"({context.get('existing_group', '')} vs {context.get('group', '')})."
        )
    return "Unknown multigroup manifest normalization issue."


def _dedupe_messages(messages: list[str]) -> list[str]:
    """Preserve order while removing duplicate warning/error strings."""

    deduped: list[str] = []
    seen: set[str] = set()
    for message in messages:
        if message in seen:
            continue
        deduped.append(message)
        seen.add(message)
    return deduped
