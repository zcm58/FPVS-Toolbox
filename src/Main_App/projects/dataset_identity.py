"""Internal participant and group identity helpers for the dataset index."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable, Mapping

_LEGACY_PARTICIPANT_PATTERN = re.compile(
    r"(P\d+[A-Za-z]*|Sub\d+[A-Za-z]*|S\d+[A-Za-z]*)",
    re.IGNORECASE,
)


def infer_workbook_participant_id(
    workbook_path: str | Path,
    *,
    known_participant_ids: Iterable[str] = (),
    fallback_to_stem: bool = False,
    require_leading_legacy_match: bool = False,
    generated_condition: str | None = None,
) -> str | None:
    """Infer a participant ID, preferring exact manifest identities.

    Managed project scans can anchor the legacy fallback to the start of the
    generated workbook name so summary files cannot impersonate participants.
    A final exact generated-name fallback preserves unregistered participant
    IDs for strict manifest validation instead of silently dropping them.
    """

    stem = Path(workbook_path).stem.strip()
    if not stem:
        return None
    stem_upper = stem.upper()
    candidates = sorted(
        {str(value).strip() for value in known_participant_ids if str(value).strip()},
        key=len,
        reverse=True,
    )
    for candidate in candidates:
        candidate_upper = candidate.upper()
        if stem_upper == candidate_upper or stem_upper.startswith(f"{candidate_upper}_"):
            return candidate
    condition = str(generated_condition or "").strip()
    generated_suffix = f"_{condition}_Results"
    if (
        condition
        and stem.casefold().endswith(generated_suffix.casefold())
        and len(stem) > len(generated_suffix)
    ):
        participant_prefix = stem[: -len(generated_suffix)].strip()
        if participant_prefix:
            return participant_prefix.upper()
    match = (
        _LEGACY_PARTICIPANT_PATTERN.match(stem)
        if require_leading_legacy_match
        else _LEGACY_PARTICIPANT_PATTERN.search(stem)
    )
    if match:
        return match.group(1).upper()
    return stem_upper if fallback_to_stem else None


def participant_group_label_map_from_manifest(
    manifest: Mapping[str, Any] | None,
    *,
    include_legacy_aliases: bool = True,
) -> dict[str, str]:
    """Return an uppercase participant-to-label map from manifest metadata."""

    if not isinstance(manifest, Mapping):
        return {}
    groups, aliases = _manifest_group_identities(manifest)
    participants = manifest.get("participants", {})
    if not isinstance(participants, Mapping):
        return {}
    result: dict[str, str] = {}
    for raw_id, raw_info in participants.items():
        if not isinstance(raw_info, Mapping):
            continue
        participant_id = str(raw_id).strip()
        raw_group = raw_info.get("group_id", raw_info.get("group"))
        group_key = str(raw_group or "").strip().casefold()
        group_id = aliases.get(group_key)
        if not participant_id or group_id is None:
            continue
        result[participant_id.upper()] = groups[group_id][0]
    if include_legacy_aliases:
        add_legacy_participant_aliases(result)
    return result


def group_labels_from_manifest(
    manifest: Mapping[str, Any] | None,
) -> tuple[str, ...]:
    """Return canonical group display labels ordered for presentation."""

    if not isinstance(manifest, Mapping):
        return ()
    groups, _aliases = _manifest_group_identities(manifest)
    return tuple(sorted({label for label, _folder in groups.values()}, key=str.casefold))


def is_multi_group_manifest(manifest: Mapping[str, Any] | None) -> bool:
    """Return whether the manifest defines at least two canonical groups."""

    if not isinstance(manifest, Mapping):
        return False
    groups, _aliases = _manifest_group_identities(manifest)
    return len(groups) >= 2


def add_legacy_participant_aliases(values: dict[str, str]) -> tuple[str, ...]:
    """Add only unambiguous ``P#`` aliases for older workbook naming.

    The returned aliases were ambiguous across distinct mapped values and were
    deliberately omitted. Explicit participant keys always retain authority.
    """

    original = tuple(values.items())
    explicit_values = {
        str(participant_id).strip().upper(): value
        for participant_id, value in original
        if str(participant_id).strip()
    }
    candidates: dict[str, set[str]] = {}
    for participant_id, value in original:
        match = re.search(r"P\d+", participant_id, re.IGNORECASE)
        if match is None:
            continue
        alias = match.group(0).upper()
        if alias == str(participant_id).strip().upper():
            continue
        candidates.setdefault(alias, set()).add(value)

    ambiguous: list[str] = []
    for alias, candidate_values in sorted(candidates.items()):
        explicit = explicit_values.get(alias)
        if explicit is not None:
            if any(value != explicit for value in candidate_values):
                ambiguous.append(alias)
            continue
        if len(candidate_values) == 1:
            values[alias] = next(iter(candidate_values))
        else:
            ambiguous.append(alias)
    return tuple(ambiguous)


def _manifest_group_identities(
    manifest: Mapping[str, Any],
) -> tuple[dict[str, tuple[str, str]], dict[str, str]]:
    raw_groups = manifest.get("groups", {})
    if not isinstance(raw_groups, Mapping):
        return {}, {}
    groups: dict[str, tuple[str, str]] = {}
    alias_candidates: dict[str, set[str]] = {}
    for raw_id, raw_info in raw_groups.items():
        info = raw_info if isinstance(raw_info, Mapping) else {}
        group_key = str(raw_id).strip()
        if not group_key:
            continue
        label = str(info.get("label") or raw_id).strip() or group_key
        folder = str(info.get("folder_name") or label).strip() or label
        groups[group_key] = (label, folder)
        for alias in (
            raw_id,
            info.get("group_id"),
            info.get("label"),
            info.get("folder_name"),
        ):
            alias_key = str(alias or "").strip().casefold()
            if alias_key:
                alias_candidates.setdefault(alias_key, set()).add(group_key)
    aliases = {
        alias: next(iter(group_keys))
        for alias, group_keys in alias_candidates.items()
        if len(group_keys) == 1
    }
    return groups, aliases


__all__ = [
    "add_legacy_participant_aliases",
    "group_labels_from_manifest",
    "infer_workbook_participant_id",
    "is_multi_group_manifest",
    "participant_group_label_map_from_manifest",
]
