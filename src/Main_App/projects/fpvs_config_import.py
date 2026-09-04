"""Import FPVS Studio `.fpvsconfig` files into Toolbox project shells."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from Main_App.processing.removed_electrode_detection import (
    REMOVED_ELECTRODE_DETECTION_MODE_MANUAL,
    normalize_manual_removed_electrodes_map,
    parse_electrode_list,
)
from Main_App.projects.project import Project
from Main_App.projects.frequency_protocol import (
    EXPECTED_CYCLES_SOURCE_FPVS_STUDIO_IMPORT,
    ODDBALL_INPUT_MODE_DIRECT_HZ,
    ODDBALL_MARKER_SOURCE_FPVS_STUDIO_IMPORT,
    FrequencyProtocol,
    FrequencyProtocolError,
    validate_protocol_condition_codes,
)
from Main_App.projects.preprocessing_settings import (
    REMOVED_ELECTRODE_DETECTION_CHOICE_SOURCE_FPVS_STUDIO_IMPORT,
    new_project_preprocessing_settings,
)

CONFIG_SUFFIX = ".fpvsconfig"
WINDOWS_FORBIDDEN_PROJECT_CHARS = set('<>:"/\\|?*')
_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


class FPVSConfigImportError(ValueError):
    """Raised when a Studio `.fpvsconfig` cannot seed a Toolbox project."""


@dataclass(frozen=True)
class FPVSConfigImport:
    """The Toolbox-owned subset of a Studio project config."""

    project_title: str
    event_map: dict[str, int]
    manual_removed_electrodes: dict[str, list[str]]
    oddball_marker_code: int
    frequency_protocol: FrequencyProtocol | None


def read_fpvs_config(path: Path) -> FPVSConfigImport:
    """Read project title and condition trigger map from a Studio `.fpvsconfig`."""

    config_path = Path(path)
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise FPVSConfigImportError(f"Unable to read FPVS config: {config_path}") from exc
    except json.JSONDecodeError as exc:
        raise FPVSConfigImportError(f"FPVS config is not valid JSON: {config_path}") from exc
    if not isinstance(payload, Mapping):
        raise FPVSConfigImportError("FPVS config must contain a JSON object.")

    schema_version = payload.get("schema_version")
    if schema_version != "1.0.0":
        raise FPVSConfigImportError(
            "Unsupported FPVS config schema version: "
            f"{schema_version!r}. Expected '1.0.0'."
        )

    project = payload.get("project")
    if not isinstance(project, Mapping):
        raise FPVSConfigImportError("FPVS config is missing a project object.")
    title = _required_text(project.get("name"), "project.name")

    conditions = payload.get("conditions")
    if not isinstance(conditions, list) or not conditions:
        raise FPVSConfigImportError("FPVS config must contain at least one condition.")

    event_map: dict[str, int] = {}
    used_codes: set[int] = set()
    for index, raw_condition in enumerate(conditions):
        if not isinstance(raw_condition, Mapping):
            raise FPVSConfigImportError(f"conditions[{index}] must be an object.")
        name = _required_text(raw_condition.get("name"), f"conditions[{index}].name")
        if name in event_map:
            raise FPVSConfigImportError(f"Duplicate condition name in FPVS config: {name!r}.")
        code = _required_int(
            raw_condition.get("trigger_code"),
            f"conditions[{index}].trigger_code",
        )
        if code in used_codes:
            raise FPVSConfigImportError(f"Duplicate trigger code in FPVS config: {code}.")
        event_map[name] = code
        used_codes.add(code)

    manual_removed_electrodes = _manual_removed_electrodes_from_config(payload)
    oddball_marker_code = _oddball_marker_code_from_config(payload)
    frequency_protocol = _frequency_protocol_from_config(
        payload,
        oddball_marker_code=oddball_marker_code,
    )
    try:
        validate_protocol_condition_codes(
            frequency_protocol
            or FrequencyProtocol.from_recurrence(
                6,
                5,
                oddball_marker_code=oddball_marker_code,
                oddball_marker_code_source=ODDBALL_MARKER_SOURCE_FPVS_STUDIO_IMPORT,
            ),
            event_map.values(),
        )
    except FrequencyProtocolError as exc:
        raise FPVSConfigImportError(str(exc)) from exc

    return FPVSConfigImport(
        project_title=title,
        event_map=event_map,
        manual_removed_electrodes=manual_removed_electrodes,
        oddball_marker_code=oddball_marker_code,
        frequency_protocol=frequency_protocol,
    )


def create_project_from_fpvs_config(projects_root: Path, config_path: Path) -> Project:
    """Create and save a Toolbox project from the importable Studio config subset."""

    imported = read_fpvs_config(config_path)
    project_root = _unique_project_root(Path(projects_root), imported.project_title)
    project_root.mkdir(parents=True, exist_ok=False)
    project = Project.load(
        project_root,
        manifest={"preprocessing": new_project_preprocessing_settings()},
    )
    project.name = imported.project_title
    project.event_map = imported.event_map
    imported_protocol = imported.frequency_protocol
    if imported_protocol is None:
        imported_protocol = project.frequency_protocol.with_oddball_marker_code(
            imported.oddball_marker_code,
            source=ODDBALL_MARKER_SOURCE_FPVS_STUDIO_IMPORT,
        )
    project.update_frequency_protocol(imported_protocol)
    if imported.manual_removed_electrodes:
        project.confirm_removed_electrode_detection_choice(
            REMOVED_ELECTRODE_DETECTION_MODE_MANUAL,
            source=REMOVED_ELECTRODE_DETECTION_CHOICE_SOURCE_FPVS_STUDIO_IMPORT,
        )
        project.update_preprocessing(
            {
                **project.preprocessing,
                "removed_electrode_detection_mode": REMOVED_ELECTRODE_DETECTION_MODE_MANUAL,
                "manual_removed_electrodes": imported.manual_removed_electrodes,
            }
        )
    project.save()
    return project


def _oddball_marker_code_from_config(payload: Mapping[str, Any]) -> int:
    triggers = payload.get("triggers")
    if triggers is None:
        return 55
    if not isinstance(triggers, Mapping):
        raise FPVSConfigImportError("triggers must be an object when provided.")
    value = triggers.get("oddball_trigger_code", 55)
    return _required_int(value, "triggers.oddball_trigger_code")


def _frequency_protocol_from_config(
    payload: Mapping[str, Any],
    *,
    oddball_marker_code: int,
) -> FrequencyProtocol | None:
    """Read an explicitly named Studio protocol without inferring generic fields."""

    raw_protocol = payload.get("frequency_protocol")
    if raw_protocol is None:
        return None
    if not isinstance(raw_protocol, Mapping):
        raise FPVSConfigImportError("frequency_protocol must be an object.")

    presentation_rate = raw_protocol.get("presentation_rate_hz")
    cycles = raw_protocol.get("expected_analyzed_oddball_cycles")
    cycle_source = (
        EXPECTED_CYCLES_SOURCE_FPVS_STUDIO_IMPORT if cycles is not None else None
    )
    mode = str(raw_protocol.get("oddball_input_mode") or "").strip()
    try:
        if mode == ODDBALL_INPUT_MODE_DIRECT_HZ:
            return FrequencyProtocol.from_direct_hz(
                presentation_rate,
                raw_protocol.get(
                    "entered_oddball_rate_hz",
                    raw_protocol.get("oddball_rate_hz"),
                ),
                expected_analyzed_oddball_cycles=cycles,
                expected_analyzed_oddball_cycles_source=cycle_source,
                oddball_marker_code=oddball_marker_code,
                oddball_marker_code_source=ODDBALL_MARKER_SOURCE_FPVS_STUDIO_IMPORT,
            )
        if mode and mode != "oddball_every_n":
            raise FPVSConfigImportError(
                f"Unsupported frequency_protocol.oddball_input_mode: {mode!r}."
            )
        return FrequencyProtocol.from_recurrence(
            presentation_rate,
            raw_protocol.get("oddball_every_n"),
            expected_analyzed_oddball_cycles=cycles,
            expected_analyzed_oddball_cycles_source=cycle_source,
            oddball_marker_code=oddball_marker_code,
            oddball_marker_code_source=ODDBALL_MARKER_SOURCE_FPVS_STUDIO_IMPORT,
        )
    except FrequencyProtocolError as exc:
        raise FPVSConfigImportError(f"Invalid frequency_protocol: {exc}") from exc


def _manual_removed_electrodes_from_config(
    payload: Mapping[str, Any],
) -> dict[str, list[str]]:
    """Extract optional Studio PID -> physically removed electrodes metadata."""

    direct = _first_mapping(
        payload,
        (
            "manual_removed_electrodes",
            "manually_removed_electrodes",
            "manual_removed_electrode_map",
            "excluded_electrodes_by_participant",
            "removed_electrodes_by_participant",
        ),
    )
    if direct:
        return normalize_manual_removed_electrodes_map(direct)

    participants = payload.get("participants")
    if isinstance(participants, Mapping):
        return _manual_removed_electrodes_from_participant_map(participants)
    if isinstance(participants, list):
        return _manual_removed_electrodes_from_participant_list(participants)
    return {}


def _first_mapping(
    source: Mapping[str, Any],
    keys: tuple[str, ...],
) -> Mapping[str, Any] | None:
    for key in keys:
        value = source.get(key)
        if isinstance(value, Mapping):
            return value
    return None


def _manual_removed_electrodes_from_participant_map(
    participants: Mapping[str, Any],
) -> dict[str, list[str]]:
    manual_map: dict[str, list[str]] = {}
    for raw_pid, raw_info in participants.items():
        pid = str(raw_pid or "").strip()
        if not pid:
            continue
        if isinstance(raw_info, Mapping):
            has_value, electrodes_value = _participant_removed_electrodes_value(
                raw_info
            )
            if has_value:
                manual_map[pid] = parse_electrode_list(electrodes_value)
        else:
            manual_map[pid] = parse_electrode_list(raw_info)
    return normalize_manual_removed_electrodes_map(manual_map)


def _manual_removed_electrodes_from_participant_list(
    participants: list[Any],
) -> dict[str, list[str]]:
    manual_map: dict[str, list[str]] = {}
    for raw_info in participants:
        if not isinstance(raw_info, Mapping):
            continue
        pid_value = (
            raw_info.get("participant_id")
            or raw_info.get("pid")
            or raw_info.get("subject_id")
            or raw_info.get("id")
        )
        pid = str(pid_value or "").strip()
        if not pid:
            continue
        has_value, electrodes_value = _participant_removed_electrodes_value(raw_info)
        if has_value:
            manual_map[pid] = parse_electrode_list(electrodes_value)
    return normalize_manual_removed_electrodes_map(manual_map)


def _participant_removed_electrodes_value(info: Mapping[str, Any]) -> tuple[bool, Any]:
    for key in (
        "manual_removed_electrodes",
        "manually_removed_electrodes",
        "removed_electrodes",
        "excluded_electrodes",
        "physically_removed_electrodes",
    ):
        if key in info:
            return True, info.get(key)
    return False, None


def _required_text(value: Any, location: str) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        raise FPVSConfigImportError(f"FPVS config is missing {location}.")
    return text


def _required_int(value: Any, location: str) -> int:
    if isinstance(value, bool):
        raise FPVSConfigImportError(f"{location} must be an integer.")
    if isinstance(value, int):
        code = value
    elif isinstance(value, str) and value.strip().isdigit():
        code = int(value)
    else:
        raise FPVSConfigImportError(f"{location} must be an integer.")
    if code < 1:
        raise FPVSConfigImportError(f"{location} must be a positive integer.")
    return code


def _project_dir_name(project_title: str) -> str:
    cleaned = "".join(
        "_" if char in WINDOWS_FORBIDDEN_PROJECT_CHARS else char for char in project_title.strip()
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    if not cleaned:
        cleaned = "Imported FPVS Project"
    if cleaned.upper() in _WINDOWS_RESERVED_NAMES:
        cleaned = f"{cleaned}_Project"
    return cleaned


def _unique_project_root(projects_root: Path, project_title: str) -> Path:
    base_name = _project_dir_name(project_title)
    candidate = projects_root / base_name
    if not candidate.exists():
        return candidate

    suffix = 2
    while True:
        candidate = projects_root / f"{base_name} {suffix}"
        if not candidate.exists():
            return candidate
        suffix += 1
