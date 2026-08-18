"""Canonical repeated-session recording metadata and context helpers."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .grouping import (
    GroupInfo,
    ParticipantInfo,
    normalize_project_groups,
    normalize_project_participants,
)

_STABLE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


class RecordingConfigurationError(ValueError):
    """Raised when repeated-session metadata is incomplete or inconsistent."""


@dataclass(frozen=True, slots=True)
class SessionInfo:
    """Canonical identity and visit order for one declared session."""

    session_id: str
    label: str
    visit_index: int


@dataclass(frozen=True, slots=True)
class RecordingSourceInfo:
    """One raw-input folder registered to a canonical group/session cell."""

    source_id: str
    group_id: str
    session_id: str
    raw_input_folder: Path


@dataclass(frozen=True, slots=True)
class RecordingInfo:
    """Stable raw-file identity for one participant recording."""

    recording_id: str
    participant_id: str
    session_id: str
    source_id: str
    raw_file: Path
    visit_index: int
    days_from_baseline: float | None = None


@dataclass(frozen=True, slots=True)
class ProjectRecordingContext:
    """Read-only repeated-session context shared by project-aware workflows."""

    project_root: Path
    sessions: tuple[SessionInfo, ...]
    sources: tuple[RecordingSourceInfo, ...]
    recordings: tuple[RecordingInfo, ...]
    groups: tuple[GroupInfo, ...] = ()
    participants: tuple[ParticipantInfo, ...] = ()

    @property
    def is_repeated_session(self) -> bool:
        """Return whether the project opts into v2.2 recording metadata."""

        return bool(self.sessions or self.sources or self.recordings)

    def session(self, session_id: str) -> SessionInfo:
        key = str(session_id).casefold()
        for session in self.sessions:
            if session.session_id.casefold() == key:
                return session
        raise RecordingConfigurationError(f"Unknown project session_id '{session_id}'.")

    def source(self, source_id: str) -> RecordingSourceInfo:
        key = str(source_id).casefold()
        for source in self.sources:
            if source.source_id.casefold() == key:
                return source
        raise RecordingConfigurationError(f"Unknown project recording source_id '{source_id}'.")

    def recording(self, recording_id: str) -> RecordingInfo:
        key = str(recording_id).casefold()
        for recording in self.recordings:
            if recording.recording_id.casefold() == key:
                return recording
        raise RecordingConfigurationError(f"Unknown project recording_id '{recording_id}'.")

    def recording_for_raw_path(self, raw_file: str | Path) -> RecordingInfo:
        try:
            target = Path(raw_file).expanduser().resolve(strict=False)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            raise RecordingConfigurationError(f"Invalid recording raw-file path: {raw_file}") from exc
        for recording in self.recordings:
            if recording.raw_file == target:
                return recording
        raise RecordingConfigurationError(f"No project recording owns raw file '{target}'.")

    def recordings_for_participant(
        self,
        participant_id: str,
    ) -> tuple[RecordingInfo, ...]:
        key = str(participant_id).casefold()
        return tuple(recording for recording in self.recordings if recording.participant_id.casefold() == key)


def _stable_id(value: object, *, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise RecordingConfigurationError(f"{field_name} cannot be empty.")
    if not _STABLE_ID_PATTERN.fullmatch(text):
        raise RecordingConfigurationError(
            f"{field_name} '{text}' must contain only letters, numbers, underscores, "
            "or hyphens and must start with a letter or number."
        )
    return text


def _positive_visit_index(value: object, *, field_name: str) -> int:
    if isinstance(value, bool):
        raise RecordingConfigurationError(f"{field_name} must be a positive integer.")
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise RecordingConfigurationError(f"{field_name} must be a positive integer.") from exc
    if result < 1 or str(value).strip() not in {str(result), f"+{result}"}:
        raise RecordingConfigurationError(f"{field_name} must be a positive integer.")
    return result


def _optional_finite_number(value: object, *, field_name: str) -> float | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool):
        raise RecordingConfigurationError(f"{field_name} must be a finite number.")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise RecordingConfigurationError(f"{field_name} must be a finite number.") from exc
    if not math.isfinite(result):
        raise RecordingConfigurationError(f"{field_name} must be a finite number.")
    return result


def _resolve_project_path(project_root: Path, value: object) -> Path:
    try:
        path = Path(str(value)).expanduser()
        candidate = path if path.is_absolute() else project_root / path
        return candidate.resolve(strict=False)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise RecordingConfigurationError("Unable to resolve project path.") from exc


def _canonical_id(
    value: object,
    identities: Mapping[str, object],
    *,
    field_name: str,
) -> str:
    requested = _stable_id(value, field_name=field_name)
    lookup = {str(identity).casefold(): str(identity) for identity in identities}
    canonical = lookup.get(requested.casefold())
    if canonical is None:
        raise RecordingConfigurationError(f"Unknown {field_name} '{requested}'.")
    return canonical


def normalize_project_sessions(sessions_raw: object) -> dict[str, dict[str, Any]]:
    """Normalize declared session identities and unique visit indices."""

    if sessions_raw is None:
        sessions_raw = {}
    if not isinstance(sessions_raw, Mapping):
        raise RecordingConfigurationError("Project sessions must be a mapping.")

    sessions: dict[str, dict[str, Any]] = {}
    used_ids: dict[str, str] = {}
    used_visits: dict[int, str] = {}
    for raw_session_id, raw_info in sessions_raw.items():
        session_id = _stable_id(raw_session_id, field_name="session_id")
        session_key = session_id.casefold()
        if session_key in used_ids:
            raise RecordingConfigurationError(
                f"Session IDs '{used_ids[session_key]}' and '{session_id}' differ only by case."
            )
        if not isinstance(raw_info, Mapping):
            raise RecordingConfigurationError(f"Session '{session_id}' metadata must be a mapping.")
        label = str(raw_info.get("label") or session_id).strip()
        if not label:
            raise RecordingConfigurationError(f"Session '{session_id}' requires a nonblank label.")
        visit_index = _positive_visit_index(
            raw_info.get("visit_index"),
            field_name=f"Session '{session_id}' visit_index",
        )
        if visit_index in used_visits:
            raise RecordingConfigurationError(
                f"Sessions '{used_visits[visit_index]}' and '{session_id}' use the same visit_index {visit_index}."
            )
        sessions[session_id] = {
            "label": label,
            "visit_index": visit_index,
        }
        used_ids[session_key] = session_id
        used_visits[visit_index] = session_id
    return sessions


def normalize_project_recording_sources(
    project_root: str | Path,
    sources_raw: object,
    groups: Mapping[str, Mapping[str, Any]],
    sessions: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Normalize raw source folders against canonical groups and sessions."""

    root = Path(project_root).resolve(strict=False)
    if sources_raw is None:
        sources_raw = {}
    if not isinstance(sources_raw, Mapping):
        raise RecordingConfigurationError("Project recording_sources must be a mapping.")

    sources: dict[str, dict[str, Any]] = {}
    used_ids: dict[str, str] = {}
    used_folders: dict[Path, str] = {}
    used_cells: dict[tuple[str, str], str] = {}
    for raw_source_id, raw_info in sources_raw.items():
        source_id = _stable_id(raw_source_id, field_name="source_id")
        source_key = source_id.casefold()
        if source_key in used_ids:
            raise RecordingConfigurationError(
                f"Recording source IDs '{used_ids[source_key]}' and '{source_id}' differ only by case."
            )
        if not isinstance(raw_info, Mapping):
            raise RecordingConfigurationError(f"Recording source '{source_id}' metadata must be a mapping.")
        group_id = _canonical_id(
            raw_info.get("group_id"),
            groups,
            field_name="group_id",
        )
        session_id = _canonical_id(
            raw_info.get("session_id"),
            sessions,
            field_name="session_id",
        )
        raw_folder = raw_info.get("raw_input_folder")
        if raw_folder is None or not str(raw_folder).strip():
            raise RecordingConfigurationError(f"Recording source '{source_id}' requires a nonblank raw_input_folder.")
        raw_input_folder = _resolve_project_path(root, raw_folder)
        if raw_input_folder in used_folders:
            raise RecordingConfigurationError(
                f"Recording sources '{used_folders[raw_input_folder]}' and "
                f"'{source_id}' use the same raw_input_folder '{raw_input_folder}'."
            )
        cell = (group_id.casefold(), session_id.casefold())
        if cell in used_cells:
            raise RecordingConfigurationError(
                f"Recording sources '{used_cells[cell]}' and '{source_id}' both "
                f"define group/session cell '{group_id}/{session_id}'."
            )
        sources[source_id] = {
            "group_id": group_id,
            "session_id": session_id,
            "raw_input_folder": raw_input_folder,
        }
        used_ids[source_key] = source_id
        used_folders[raw_input_folder] = source_id
        used_cells[cell] = source_id
    return sources


def normalize_project_recordings(
    project_root: str | Path,
    recordings_raw: object,
    groups: Mapping[str, Mapping[str, Any]],
    participants: Mapping[str, Mapping[str, Any]],
    sessions: Mapping[str, Mapping[str, Any]],
    sources: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Normalize recording ownership and enforce the repeated-session contract."""

    root = Path(project_root).resolve(strict=False)
    if recordings_raw is None:
        recordings_raw = {}
    if not isinstance(recordings_raw, Mapping):
        raise RecordingConfigurationError("Project recordings must be a mapping.")

    recordings: dict[str, dict[str, Any]] = {}
    used_ids: dict[str, str] = {}
    used_raw_files: dict[Path, str] = {}
    used_participant_sessions: dict[tuple[str, str], str] = {}
    participant_lookup = {str(participant_id).casefold(): str(participant_id) for participant_id in participants}
    for raw_recording_id, raw_info in recordings_raw.items():
        recording_id = _stable_id(raw_recording_id, field_name="recording_id")
        recording_key = recording_id.casefold()
        if recording_key in used_ids:
            raise RecordingConfigurationError(
                f"Recording IDs '{used_ids[recording_key]}' and '{recording_id}' differ only by case."
            )
        if not isinstance(raw_info, Mapping):
            raise RecordingConfigurationError(f"Recording '{recording_id}' metadata must be a mapping.")

        requested_participant = str(raw_info.get("participant_id") or "").strip()
        participant_id = participant_lookup.get(requested_participant.casefold())
        if participant_id is None:
            raise RecordingConfigurationError(
                f"Recording '{recording_id}' references unknown participant_id '{requested_participant}'."
            )
        source_id = _canonical_id(
            raw_info.get("source_id"),
            sources,
            field_name="source_id",
        )
        source = sources[source_id]
        session_id = _canonical_id(
            raw_info.get("session_id"),
            sessions,
            field_name="session_id",
        )
        if session_id != source["session_id"]:
            raise RecordingConfigurationError(
                f"Recording '{recording_id}' session_id '{session_id}' does not "
                f"match source '{source_id}' session_id '{source['session_id']}'."
            )

        participant_group_id = participants[participant_id].get("group_id")
        if participant_group_id is None or participant_group_id not in groups:
            raise RecordingConfigurationError(
                f"Recording '{recording_id}' participant '{participant_id}' has no canonical project group assignment."
            )
        source_group_id = str(source["group_id"])
        if str(participant_group_id) != source_group_id:
            raise RecordingConfigurationError(
                f"Recording '{recording_id}' participant '{participant_id}' belongs "
                f"to group '{participant_group_id}', but source '{source_id}' belongs "
                f"to group '{source_group_id}'."
            )
        declared_group = raw_info.get("group_id")
        if declared_group is not None and str(declared_group).strip():
            recording_group_id = _canonical_id(
                declared_group,
                groups,
                field_name="group_id",
            )
            if recording_group_id != source_group_id:
                raise RecordingConfigurationError(
                    f"Recording '{recording_id}' group_id '{recording_group_id}' does "
                    f"not match source '{source_id}' group_id '{source_group_id}'."
                )

        raw_file_value = raw_info.get("raw_file")
        if raw_file_value is None or not str(raw_file_value).strip():
            raise RecordingConfigurationError(f"Recording '{recording_id}' requires a nonblank raw_file.")
        raw_file = _resolve_project_path(root, raw_file_value)
        if raw_file.suffix.casefold() != ".bdf":
            raise RecordingConfigurationError(f"Recording '{recording_id}' raw_file must be a .bdf file: {raw_file}")
        source_root = Path(source["raw_input_folder"]).resolve(strict=False)
        if raw_file.parent != source_root:
            raise RecordingConfigurationError(
                f"Recording '{recording_id}' raw_file is outside its declared source "
                f"'{source_id}' raw_input_folder: {raw_file}"
            )
        if raw_file in used_raw_files:
            raise RecordingConfigurationError(
                f"Recordings '{used_raw_files[raw_file]}' and '{recording_id}' use the same raw_file '{raw_file}'."
            )

        session_visit_index = int(sessions[session_id]["visit_index"])
        requested_visit_index = raw_info.get("visit_index", session_visit_index)
        visit_index = _positive_visit_index(
            requested_visit_index,
            field_name=f"Recording '{recording_id}' visit_index",
        )
        if visit_index != session_visit_index:
            raise RecordingConfigurationError(
                f"Recording '{recording_id}' visit_index {visit_index} does not match "
                f"session '{session_id}' visit_index {session_visit_index}."
            )
        days_from_baseline = _optional_finite_number(
            raw_info.get("days_from_baseline"),
            field_name=f"Recording '{recording_id}' days_from_baseline",
        )

        participant_session = (participant_id.casefold(), session_id.casefold())
        if participant_session in used_participant_sessions:
            raise RecordingConfigurationError(
                f"Recordings '{used_participant_sessions[participant_session]}' and "
                f"'{recording_id}' both assign participant '{participant_id}' to "
                f"session '{session_id}'."
            )
        normalized: dict[str, Any] = {
            "participant_id": participant_id,
            "session_id": session_id,
            "source_id": source_id,
            "raw_file": raw_file,
            "visit_index": visit_index,
        }
        if days_from_baseline is not None:
            normalized["days_from_baseline"] = days_from_baseline
        recordings[recording_id] = normalized
        used_ids[recording_key] = recording_id
        used_raw_files[raw_file] = recording_id
        used_participant_sessions[participant_session] = recording_id
    return recordings


def project_recording_context(project: object) -> ProjectRecordingContext:
    """Build canonical repeated-session context without filesystem writes."""

    root = Path(getattr(project, "project_root")).resolve(strict=False)
    groups, group_aliases = normalize_project_groups(
        root,
        getattr(project, "groups", {}),
    )
    participants = normalize_project_participants(
        root,
        getattr(project, "participants", {}),
        groups,
        group_aliases,
    )
    sessions = normalize_project_sessions(getattr(project, "sessions", {}))
    sources = normalize_project_recording_sources(
        root,
        getattr(project, "recording_sources", {}),
        groups,
        sessions,
    )
    recordings = normalize_project_recordings(
        root,
        getattr(project, "recordings", {}),
        groups,
        participants,
        sessions,
        sources,
    )
    return _build_context(root, groups, participants, sessions, sources, recordings)


def load_project_recording_context(
    project_root: str | Path,
) -> ProjectRecordingContext:
    """Read canonical recording context from project.json without writes."""

    root = Path(project_root).resolve(strict=False)
    manifest_path = root / "project.json"
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RecordingConfigurationError(f"Unable to read project recording metadata from {manifest_path}.") from exc
    if not isinstance(payload, Mapping):
        raise RecordingConfigurationError("Project manifest must contain a JSON object.")

    groups, group_aliases = normalize_project_groups(root, payload.get("groups", {}))
    participants = normalize_project_participants(
        root,
        payload.get("participants", {}),
        groups,
        group_aliases,
    )
    sessions = normalize_project_sessions(payload.get("sessions", {}))
    sources = normalize_project_recording_sources(
        root,
        payload.get("recording_sources", {}),
        groups,
        sessions,
    )
    recordings = normalize_project_recordings(
        root,
        payload.get("recordings", {}),
        groups,
        participants,
        sessions,
        sources,
    )
    return _build_context(root, groups, participants, sessions, sources, recordings)


def _build_context(
    project_root: Path,
    groups: Mapping[str, Mapping[str, Any]],
    participants: Mapping[str, Mapping[str, Any]],
    sessions: Mapping[str, Mapping[str, Any]],
    sources: Mapping[str, Mapping[str, Any]],
    recordings: Mapping[str, Mapping[str, Any]],
) -> ProjectRecordingContext:
    group_rows = tuple(
        GroupInfo(
            group_id=group_id,
            label=str(info["label"]),
            folder_name=str(info["folder_name"]),
            raw_input_folder=Path(info["raw_input_folder"]),
        )
        for group_id, info in groups.items()
    )
    participant_rows = tuple(
        ParticipantInfo(
            participant_id=participant_id,
            group_id=str(info["group_id"]) if info.get("group_id") else None,
            raw_file=Path(info["raw_file"]) if info.get("raw_file") else None,
        )
        for participant_id, info in participants.items()
    )
    session_rows = tuple(
        SessionInfo(
            session_id=session_id,
            label=str(info["label"]),
            visit_index=int(info["visit_index"]),
        )
        for session_id, info in sessions.items()
    )
    source_rows = tuple(
        RecordingSourceInfo(
            source_id=source_id,
            group_id=str(info["group_id"]),
            session_id=str(info["session_id"]),
            raw_input_folder=Path(info["raw_input_folder"]),
        )
        for source_id, info in sources.items()
    )
    recording_rows = tuple(
        RecordingInfo(
            recording_id=recording_id,
            participant_id=str(info["participant_id"]),
            session_id=str(info["session_id"]),
            source_id=str(info["source_id"]),
            raw_file=Path(info["raw_file"]),
            visit_index=int(info["visit_index"]),
            days_from_baseline=(
                float(info["days_from_baseline"]) if info.get("days_from_baseline") is not None else None
            ),
        )
        for recording_id, info in recordings.items()
    )
    return ProjectRecordingContext(
        project_root=project_root,
        groups=group_rows,
        participants=participant_rows,
        sessions=session_rows,
        sources=source_rows,
        recordings=recording_rows,
    )


__all__ = [
    "ProjectRecordingContext",
    "RecordingConfigurationError",
    "RecordingInfo",
    "RecordingSourceInfo",
    "SessionInfo",
    "load_project_recording_context",
    "normalize_project_recording_sources",
    "normalize_project_recordings",
    "normalize_project_sessions",
    "project_recording_context",
]
