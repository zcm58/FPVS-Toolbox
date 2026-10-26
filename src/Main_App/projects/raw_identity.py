"""Shared participant identity parsing for canonical raw-recording workflows."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_PARTICIPANT_ID_REGEX = re.compile(
    r"(?<![A-Za-z0-9])(P\d+|Sub\d+|S\d+)(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_RAW_SUFFIX_REGEX = re.compile(
    r"(_unamb|_ambig|_mid|_run\d*|_sess\d*|_task\w*|_eeg|_fpvs|_raw|_preproc|_ica).*$",
    re.IGNORECASE,
)


def infer_raw_participant_id(file_path: str | Path) -> str:
    """Infer the stable participant label used by processing and import audit."""

    path = Path(file_path)
    base = path.stem
    match = _PARTICIPANT_ID_REGEX.search(base)
    if match:
        return match.group(1).upper()

    cleaned = _RAW_SUFFIX_REGEX.sub("", base)
    cleaned = re.sub(r"[^a-zA-Z0-9]", "", cleaned)
    return cleaned if cleaned else base


@dataclass(frozen=True, slots=True)
class RegisteredRawIdentity:
    """Persisted ownership of a raw path, independent of its basename."""

    participant_id: str
    processing_id: str
    raw_file: Path
    source_study_id: str | None = None
    source_participant_id: str | None = None
    display_label: str | None = None


def normalize_source_studies(value: object) -> dict[str, dict[str, str]]:
    """Validate an optional portable source-study registry without adding defaults."""
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError("Source studies must be a mapping.")
    result: dict[str, dict[str, str]] = {}
    seen: set[str] = set()
    for source_id, info in value.items():
        if not isinstance(source_id, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", source_id):
            raise ValueError("Source study IDs must start with a letter and contain only letters, digits, '_' or '-'.")
        if source_id.casefold() in seen or not isinstance(info, Mapping):
            raise ValueError(f"Invalid or duplicate source study '{source_id}'.")
        seen.add(source_id.casefold())
        label = str(info.get("label") or source_id).strip()
        if not label:
            raise ValueError(f"Source study '{source_id}' requires a label.")
        row = {"label": label}
        for key in ("source_project_name", "manifest_sha256"):
            if info.get(key) is not None:
                row[key] = str(info[key]).strip()
        if "manifest_sha256" in row and not re.fullmatch(r"[0-9a-fA-F]{64}", row["manifest_sha256"]):
            raise ValueError(f"Source study '{source_id}' has an invalid manifest SHA256.")
        result[source_id] = row
    return result


def validate_source_participants(
    participants: Mapping[str, Mapping[str, Any]],
    source_studies: Mapping[str, Mapping[str, Any]],
) -> None:
    """Reject partial source identities and accidental cross-study person joins."""
    seen: dict[tuple[str, str], str] = {}
    for participant_id, row in participants.items():
        source = row.get("source_study_id")
        local = row.get("source_participant_id")
        if source is None and local is None:
            continue
        if not source or not local:
            raise ValueError(f"Participant '{participant_id}' requires both source study and original ID.")
        if source not in source_studies:
            raise ValueError(f"Participant '{participant_id}' references unknown source study '{source}'.")
        key = (str(source).casefold(), str(local).casefold())
        if key in seen:
            raise ValueError(f"Source participant '{source} / {local}' is assigned to both '{seen[key]}' and '{participant_id}'.")
        seen[key] = participant_id


def registered_raw_identities(context: object, *, project_root: str | Path | None = None) -> dict[Path, RegisteredRawIdentity]:
    """Resolve canonical registered paths for flat or repeated-session projects.

    A manifest requires its current root explicitly. No source/group prefix is
    parsed and no filename inference is performed by this read-only resolver.
    """
    if isinstance(context, Mapping):
        if project_root is None:
            raise ValueError("A manifest identity lookup requires its active project root.")
        root = Path(project_root).resolve(strict=False)
        participants = context.get("participants", {})
        recordings = context.get("recordings", {})
    else:
        root = Path(getattr(context, "project_root")).resolve(strict=False)
        participants = getattr(context, "participants", {})
        recordings = getattr(context, "recordings", {})
    if not isinstance(participants, Mapping) or not isinstance(recordings, Mapping):
        raise ValueError("Registered participants and recordings must be mappings.")
    result: dict[Path, RegisteredRawIdentity] = {}
    rows = recordings if recordings else participants
    for processing_id, row in rows.items():
        if not isinstance(row, Mapping):
            raise ValueError("Registered raw identity metadata must be a mapping.")
        if not row.get("raw_file"):
            continue
        pid = str(row.get("participant_id")) if recordings else str(processing_id)
        if pid not in participants:
            raise ValueError(f"Recording '{processing_id}' references unknown participant '{pid}'.")
        person = participants[pid]
        path = Path(row["raw_file"])
        path = (path if path.is_absolute() else root / path).resolve(strict=False)
        if path in result:
            raise ValueError(f"Raw file '{path}' has more than one registered owner.")
        result[path] = RegisteredRawIdentity(
            participant_id=pid, processing_id=str(processing_id), raw_file=path,
            source_study_id=person.get("source_study_id"),
            source_participant_id=person.get("source_participant_id"),
            display_label=person.get("display_label"),
        )
    return result


def resolve_registered_raw_identity(context: object, path: str | Path, *, project_root: str | Path | None = None) -> RegisteredRawIdentity | None:
    """Return persisted ownership first; absent paths need explicit registration."""
    return registered_raw_identities(context, project_root=project_root).get(Path(path).resolve(strict=False))


def propose_source_participant_id(source_study_id: str, source_participant_id: str, existing_ids: object = ()) -> str:
    """Propose a name once for review, rejecting case/sanitization collisions.

    Leading zeros remain meaningful. This never rekeys an existing person or
    silently adds a numeric suffix to hide an ambiguous allocation.
    """
    namespace = re.sub(r"[^A-Za-z0-9]", "", str(source_study_id)).upper()
    local = re.sub(r"[^A-Za-z0-9]", "", str(source_participant_id))
    if not namespace or not local:
        raise ValueError("Source study and original participant ID must contain letters or digits.")
    candidate = namespace + local
    key = candidate.casefold()
    if key in {re.sub(r"[^A-Za-z0-9]", "", str(item)).casefold() for item in existing_ids}:
        raise ValueError(f"Proposed participant ID '{candidate}' collides with an existing project ID; choose a distinct ID.")
    return candidate


__all__ = [
    "RegisteredRawIdentity", "infer_raw_participant_id", "normalize_source_studies",
    "validate_source_participants", "registered_raw_identities", "resolve_registered_raw_identity",
    "propose_source_participant_id",
]
