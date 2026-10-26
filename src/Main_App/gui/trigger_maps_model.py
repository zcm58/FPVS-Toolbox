"""Detached editor adapters for the project-owned source trigger map model."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import re

from Main_App.projects import project_recording_context
from Main_App.projects.condition_trigger_maps import (
    ConditionTriggerMaps, migrate_legacy_trigger_maps, validate_project_trigger_maps,
)


@dataclass(frozen=True, slots=True)
class TriggerRecordingRow:
    recording_id: str
    participant_id: str
    source_study: str
    original_id: str
    group_id: str
    group_label: str
    raw_file: str


def trigger_recording_rows(project):
    """Labels never replace canonical recording or participant selection keys."""
    context = project_recording_context(project)
    groups = {row.group_id: row.label for row in context.groups}
    participants = {row.participant_id: row for row in context.participants}
    metadata = getattr(project, "participants", {}) or {}
    studies = (getattr(project, "manifest", {}) or {}).get("source_studies", {})
    records = context.recordings if context.is_repeated_session else context.participants
    rows = []
    for row in records:
        person = participants.get(row.participant_id, row)
        saved = metadata.get(row.participant_id, {})
        source_id = str(saved.get("source_study_id", ""))
        study = studies.get(source_id, {})
        rows.append(TriggerRecordingRow(
            getattr(row, "recording_id", None) or row.participant_id,
            row.participant_id,
            str(study.get("label", study.get("display_name", source_id))),
            str(saved.get("source_participant_id", "")),
            str(person.group_id or ""), groups.get(person.group_id, person.group_id or "Single group"),
            str(getattr(row, "raw_file", "") or ""),
        ))
    return tuple(rows)


def trigger_map_editor_payload(project):
    maps = project.frequency_protocol.condition_trigger_maps
    if maps is not None:
        return deepcopy(maps.to_manifest())
    if project.event_map:
        return migrate_legacy_trigger_maps(project).to_manifest()
    return {
        "schema_version": "1.0", "canonical_conditions": {},
        "profiles": {"source_1": {"label": "Source 1", "conditions": {}, "boundary_only_onset_codes": []}},
        "recording_assignments": {}, "registration_group_defaults": {},
    }


def unused_identifier(label, existing):
    stem = re.sub(r"[^a-z0-9]+", "_", str(label).casefold()).strip("_") or "condition"
    value, suffix = stem, 2
    occupied = {str(item).casefold() for item in existing}
    while value.casefold() in occupied:
        value, suffix = f"{stem}_{suffix}", suffix + 1
    return value


def validated_editor_maps(project, payload):
    maps = ConditionTriggerMaps.from_manifest(payload)
    manifest = deepcopy(project.manifest)
    manifest["event_map"] = {}
    manifest["frequency_protocol"] = project.frequency_protocol.with_condition_trigger_maps(maps).to_manifest()
    validate_project_trigger_maps(manifest)
    return maps


def trigger_map_changes(before, after):
    """Exact readable leaf changes, including all explicitly reassigned recordings."""
    def flatten(value, path=()):
        if isinstance(value, dict):
            result = {}
            for key, child in value.items():
                result.update(flatten(child, (*path, str(key))))
            return result
        return {" / ".join(path): value}
    old, new = flatten(before), flatten(after)
    return tuple((key, old.get(key), new.get(key)) for key in sorted(old.keys() | new.keys()) if old.get(key) != new.get(key))


def trigger_maps_summary(protocol):
    maps = protocol.condition_trigger_maps
    return (
        f"{len(maps.profiles)} source maps · {len(maps.canonical_conditions)} conditions · "
        f"{len(maps.recording_assignments)} assigned recordings"
        if maps is not None else "Shared condition-onset map"
    )
