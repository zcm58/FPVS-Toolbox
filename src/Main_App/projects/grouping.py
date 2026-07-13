"""Canonical project-group metadata and output-path helpers."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any, Mapping

_INVALID_WINDOWS_FOLDER_CHARS = frozenset('<>:"/\\|?*')
_RESERVED_WINDOWS_DEVICE_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    "CONIN$",
    "CONOUT$",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
    "COM¹",
    "COM²",
    "COM³",
    "LPT¹",
    "LPT²",
    "LPT³",
}


class GroupConfigurationError(ValueError):
    """Raised when project-group metadata cannot produce a safe configuration."""


@dataclass(frozen=True, slots=True)
class GroupInfo:
    """Canonical identity and paths for one project group."""

    group_id: str
    label: str
    folder_name: str
    raw_input_folder: Path


@dataclass(frozen=True, slots=True)
class ParticipantInfo:
    """Canonical group assignment and raw source for one participant."""

    participant_id: str
    group_id: str | None
    raw_file: Path | None


@dataclass(frozen=True, slots=True)
class ProjectGroupContext:
    """Read-only group/participant context shared by project-aware workflows."""

    project_root: Path
    groups: tuple[GroupInfo, ...]
    participants: tuple[ParticipantInfo, ...]

    @property
    def has_group_metadata(self) -> bool:
        return bool(self.groups)

    @property
    def is_multi_group(self) -> bool:
        return len(self.groups) > 1

    def group(self, group_id: str) -> GroupInfo:
        for group in self.groups:
            if group.group_id == group_id:
                return group
        raise GroupConfigurationError(f"Unknown project group_id '{group_id}'.")

    def participant(self, participant_id: str) -> ParticipantInfo:
        key = str(participant_id).casefold()
        for participant in self.participants:
            if participant.participant_id.casefold() == key:
                return participant
        raise GroupConfigurationError(
            f"Unknown project participant_id '{participant_id}'."
        )


def make_group_id(label: object, used_ids: set[str] | None = None) -> str:
    """Return a readable, deterministic group ID with collision suffixes."""

    text = str(label or "").strip().lower()
    base = re.sub(r"[^a-z0-9]+", "_", text).strip("_") or "group"
    used = used_ids if used_ids is not None else set()
    candidate = base
    suffix = 2
    while candidate in used:
        candidate = f"{base}_{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


def _resolve_project_path(project_root: Path, value: object) -> Path:
    path = Path(str(value))
    candidate = path if path.is_absolute() else project_root / path
    return candidate.resolve(strict=False)


def normalize_project_groups(
    project_root: str | Path,
    groups_raw: object,
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """Normalize and validate manifest/runtime group metadata once."""

    root = Path(project_root).resolve(strict=False)
    if groups_raw is None:
        groups_raw = {}
    if not isinstance(groups_raw, Mapping):
        raise GroupConfigurationError("Project groups must be a mapping.")

    groups: dict[str, dict[str, Any]] = {}
    aliases: dict[str, str] = {}
    used_group_ids: set[str] = set()
    used_folder_names: dict[str, str] = {}
    used_raw_folders: dict[Path, str] = {}
    for raw_key, raw_info in groups_raw.items():
        raw_key_text = str(raw_key).strip()
        if not raw_key_text:
            raise GroupConfigurationError("Project group IDs cannot be empty.")
        if not isinstance(raw_info, Mapping):
            raise GroupConfigurationError(
                f"Group '{raw_key_text}' metadata must be a mapping."
            )

        raw_group_id = raw_info.get("group_id") or raw_key_text
        group_id = make_group_id(raw_group_id, used_group_ids)
        label = str(raw_info.get("label") or raw_key_text).strip() or group_id
        try:
            folder_name = validate_group_folder_name(
                raw_info.get("folder_name") or label
            )
        except GroupConfigurationError as exc:
            raise GroupConfigurationError(
                f"Invalid folder_name for group '{raw_key_text}': {exc}"
            ) from exc
        folder_key = folder_name.casefold()
        if folder_key in used_folder_names:
            raise GroupConfigurationError(
                f"Groups '{used_folder_names[folder_key]}' and '{raw_key_text}' use the same folder_name '{folder_name}'."
            )

        raw_folder = raw_info.get("raw_input_folder")
        if raw_folder is None or not str(raw_folder).strip():
            raise GroupConfigurationError(
                f"Group '{raw_key_text}' requires a nonblank raw_input_folder."
            )
        try:
            raw_input_folder = _resolve_project_path(root, raw_folder)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            raise GroupConfigurationError(
                f"Group '{raw_key_text}' has an invalid raw_input_folder."
            ) from exc
        if raw_input_folder in used_raw_folders:
            raise GroupConfigurationError(
                f"Groups '{used_raw_folders[raw_input_folder]}' and '{raw_key_text}' use the same raw_input_folder "
                f"'{raw_input_folder}'."
            )

        normalized: dict[str, Any] = {
            "label": label,
            "folder_name": folder_name,
            "raw_input_folder": raw_input_folder,
        }
        description = raw_info.get("description")
        if description:
            normalized["description"] = str(description)
        groups[group_id] = normalized
        used_folder_names[folder_key] = raw_key_text
        used_raw_folders[raw_input_folder] = raw_key_text

        for alias in (raw_key_text, raw_group_id, group_id, label, folder_name):
            alias_text = str(alias or "").strip()
            if alias_text:
                for alias_key in {alias_text, alias_text.casefold()}:
                    existing_group_id = aliases.get(alias_key)
                    if (
                        existing_group_id is not None
                        and existing_group_id != group_id
                    ):
                        raise GroupConfigurationError(
                            f"Group alias '{alias_text}' is ambiguous between "
                            f"'{existing_group_id}' and '{group_id}'. Use unique group "
                            "IDs, labels, and folder names."
                        )
                    aliases[alias_key] = group_id
    return groups, aliases


def normalize_project_participants(
    project_root: str | Path,
    participants_raw: object,
    groups: Mapping[str, Mapping[str, Any]],
    group_aliases: Mapping[str, str],
) -> dict[str, dict[str, Any]]:
    """Normalize participant identities and group assignments from a manifest."""

    root = Path(project_root).resolve(strict=False)
    if participants_raw is None:
        participants_raw = {}
    if not isinstance(participants_raw, Mapping):
        raise GroupConfigurationError("Project participants must be a mapping.")

    participants: dict[str, dict[str, Any]] = {}
    used_participant_ids: dict[str, str] = {}
    used_raw_files: dict[Path, str] = {}
    for raw_participant_id, raw_info in participants_raw.items():
        participant_id = str(raw_participant_id).strip()
        if not participant_id:
            raise GroupConfigurationError("Project participant IDs cannot be empty.")
        participant_key = participant_id.casefold()
        if participant_key in used_participant_ids:
            raise GroupConfigurationError(
                f"Participant IDs '{used_participant_ids[participant_key]}' and "
                f"'{participant_id}' differ only by case. Participant IDs must be "
                "unique across the project."
            )
        if not isinstance(raw_info, Mapping):
            raise GroupConfigurationError(
                f"Participant '{participant_id}' metadata must be a mapping."
            )

        normalized: dict[str, Any] = {}
        raw_group = (
            raw_info.get("group_id")
            if raw_info.get("group_id") is not None
            else raw_info.get("group")
        )
        if raw_group is not None and str(raw_group).strip():
            raw_group_text = str(raw_group).strip()
            group_id = group_aliases.get(raw_group_text) or group_aliases.get(
                raw_group_text.casefold()
            )
            if group_id is None:
                group_id = make_group_id(raw_group_text)
            if groups and group_id not in groups:
                raise GroupConfigurationError(
                    f"Participant '{participant_id}' references unknown group_id '{raw_group_text}'."
                )
            normalized["group_id"] = group_id
        elif groups:
            raise GroupConfigurationError(
                f"Participant '{participant_id}' requires a group_id in a grouped project."
            )

        raw_file = raw_info.get("raw_file")
        if raw_file is not None and str(raw_file).strip():
            try:
                raw_path = _resolve_project_path(root, raw_file)
            except (OSError, RuntimeError, TypeError, ValueError) as exc:
                raise GroupConfigurationError(
                    f"Participant '{participant_id}' has an invalid raw_file."
                ) from exc
            if raw_path.suffix.casefold() != ".bdf":
                raise GroupConfigurationError(
                    f"Participant '{participant_id}' raw_file must be a .bdf file: "
                    f"{raw_path}"
                )
            if groups:
                group_id = str(normalized["group_id"])
                group_root = Path(groups[group_id]["raw_input_folder"]).resolve(
                    strict=False
                )
                if raw_path.parent != group_root:
                    raise GroupConfigurationError(
                        f"Participant '{participant_id}' raw_file is outside its "
                        f"assigned group '{group_id}' raw_input_folder: {raw_path}"
                    )
            if raw_path in used_raw_files:
                raise GroupConfigurationError(
                    f"Participants '{used_raw_files[raw_path]}' and "
                    f"'{participant_id}' use the same raw_file '{raw_path}'."
                )
            normalized["raw_file"] = raw_path
            used_raw_files[raw_path] = participant_id
        participants[participant_id] = normalized
        used_participant_ids[participant_key] = participant_id
    return participants


def project_group_context(project: object) -> ProjectGroupContext:
    """Build the canonical context from an active project without filesystem writes."""

    root = Path(getattr(project, "project_root")).resolve(strict=False)
    groups, aliases = normalize_project_groups(root, getattr(project, "groups", {}))
    participants = normalize_project_participants(
        root,
        getattr(project, "participants", {}),
        groups,
        aliases,
    )
    return _build_context(root, groups, participants)


def load_project_group_context(project_root: str | Path) -> ProjectGroupContext:
    """Read canonical group context from project.json without creating directories."""

    root = Path(project_root).resolve(strict=False)
    manifest_path = root / "project.json"
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise GroupConfigurationError(
            f"Unable to read project group metadata from {manifest_path}."
        ) from exc
    if not isinstance(payload, Mapping):
        raise GroupConfigurationError("Project manifest must contain a JSON object.")
    groups, aliases = normalize_project_groups(root, payload.get("groups", {}))
    participants = normalize_project_participants(
        root,
        payload.get("participants", {}),
        groups,
        aliases,
    )
    return _build_context(root, groups, participants)


def _build_context(
    project_root: Path,
    groups: Mapping[str, Mapping[str, Any]],
    participants: Mapping[str, Mapping[str, Any]],
) -> ProjectGroupContext:
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
            group_id=(str(info["group_id"]) if info.get("group_id") else None),
            raw_file=(Path(info["raw_file"]) if info.get("raw_file") else None),
        )
        for participant_id, info in participants.items()
    )
    return ProjectGroupContext(
        project_root=project_root,
        groups=group_rows,
        participants=participant_rows,
    )


def validate_group_folder_name(value: object) -> str:
    """Return a safe, stripped single Windows folder component."""

    if not isinstance(value, str):
        raise GroupConfigurationError("Group folder name must be text.")

    raw_name = value
    if any(ord(character) < 32 for character in raw_name):
        raise GroupConfigurationError("Group folder name contains a control character.")
    if raw_name.endswith((" ", ".")):
        raise GroupConfigurationError(
            "Group folder name cannot end with a space or period."
        )

    folder_name = raw_name.strip()
    if not folder_name:
        raise GroupConfigurationError("Group folder name cannot be empty.")
    if folder_name in {".", ".."}:
        raise GroupConfigurationError(
            "Group folder name must identify one child folder."
        )
    if PureWindowsPath(folder_name).is_absolute():
        raise GroupConfigurationError("Group folder name cannot be an absolute path.")
    if "/" in folder_name or "\\" in folder_name:
        raise GroupConfigurationError(
            "Group folder name cannot contain path separators."
        )

    invalid_characters = sorted(
        {
            character
            for character in folder_name
            if character in _INVALID_WINDOWS_FOLDER_CHARS
        }
    )
    if invalid_characters:
        joined = "".join(invalid_characters)
        raise GroupConfigurationError(
            f"Group folder name contains invalid Windows character(s): {joined}"
        )

    device_stem = folder_name.split(".", maxsplit=1)[0].upper()
    if device_stem in _RESERVED_WINDOWS_DEVICE_NAMES:
        raise GroupConfigurationError(
            f"Group folder name uses reserved Windows device name: {device_stem}"
        )
    return folder_name


def resolve_output_directory(parent: str | Path, folder_name: object) -> Path:
    """Resolve one safe Windows folder component below ``parent``."""

    safe_folder_name = validate_group_folder_name(folder_name)
    try:
        resolved_parent = Path(parent).expanduser().resolve(strict=False)
        resolved_output = (resolved_parent / safe_folder_name).resolve(strict=False)
    except (OSError, RuntimeError, ValueError, TypeError) as exc:
        raise GroupConfigurationError(
            "Unable to resolve the group output directory."
        ) from exc

    try:
        relative_output = resolved_output.relative_to(resolved_parent)
    except ValueError as exc:
        raise GroupConfigurationError(
            "Resolved group output directory escapes its parent directory."
        ) from exc
    if not relative_output.parts:
        raise GroupConfigurationError(
            "Resolved group output directory must be below its parent directory."
        )
    return resolved_output


def resolve_group_output_directory(parent: str | Path, folder_name: object) -> Path:
    """Resolve a validated group output folder below ``parent``."""

    return resolve_output_directory(parent, folder_name)


__all__ = [
    "GroupInfo",
    "GroupConfigurationError",
    "ParticipantInfo",
    "ProjectGroupContext",
    "load_project_group_context",
    "make_group_id",
    "normalize_project_groups",
    "normalize_project_participants",
    "project_group_context",
    "resolve_group_output_directory",
    "resolve_output_directory",
    "validate_group_folder_name",
]
