"""Project-owned source trigger interpretation, independent of group membership.

Only source marker interpretation belongs here. Native events are never rewritten.
All runtime records use frozen tuples so the same snapshot can cross process
boundaries without sharing mutable editor state.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Mapping

CONDITION_TRIGGER_MAPS_SCHEMA_VERSION = "1.0"
_STABLE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


class TriggerMapError(ValueError):
    """An incomplete, ambiguous, or stale source trigger configuration."""


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TriggerMapError(f"{name} must be an object.")
    return value


def _identifier(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _STABLE_ID.fullmatch(value):
        raise TriggerMapError(f"{name} must start with a letter or number and contain only letters, numbers, _ or -.")
    return value


def _code(value: Any) -> int:
    try:
        exact = Fraction(str(value))
    except (ValueError, TypeError, ZeroDivisionError) as exc:
        raise TriggerMapError("Trigger codes must be positive whole numbers.") from exc
    if isinstance(value, bool) or exact.denominator != 1 or not 1 <= exact <= 2147483647:
        raise TriggerMapError("Trigger codes must be positive whole numbers representable as signed 32-bit events.")
    return int(exact)


def _unique_ids(values: Mapping[str, Any], name: str) -> None:
    seen: set[str] = set()
    for key in values:
        normalized = _identifier(key, name).casefold()
        if normalized in seen:
            raise TriggerMapError(f"Duplicate {name} {key!r} (IDs are case-insensitive).")
        seen.add(normalized)


@dataclass(frozen=True, slots=True)
class CanonicalCondition:
    condition_id: str
    label: str


@dataclass(frozen=True, slots=True)
class ConditionTrigger:
    condition_id: str
    onset_code: int
    oddball_code: int


@dataclass(frozen=True, slots=True)
class SourceTriggerProfile:
    profile_id: str
    label: str
    conditions: tuple[ConditionTrigger, ...]
    boundary_only_onset_codes: tuple[int, ...] = ()
    boundary_labels: tuple[tuple[int, str], ...] = ()


@dataclass(frozen=True, slots=True)
class ResolvedConditionTrigger:
    condition_id: str
    label: str
    onset_code: int
    oddball_code: int


@dataclass(frozen=True, slots=True)
class ResolvedRecordingEventSchema:
    recording_id: str
    profile_id: str | None
    conditions: tuple[ResolvedConditionTrigger, ...]
    boundary_only_onset_codes: tuple[int, ...]
    interpretation_fingerprint: str

    @property
    def event_map(self) -> dict[str, int]:
        return {item.label: item.onset_code for item in self.conditions}

    @property
    def canonical_condition_ids(self) -> dict[str, str]:
        return {item.label: item.condition_id for item in self.conditions}

    @property
    def oddball_marker_codes(self) -> dict[int, int]:
        return {item.onset_code: item.oddball_code for item in self.conditions}

    @property
    def fingerprint(self) -> str:
        return self.interpretation_fingerprint


@dataclass(frozen=True, slots=True)
class ConditionTriggerMaps:
    canonical_conditions: tuple[CanonicalCondition, ...]
    profiles: tuple[SourceTriggerProfile, ...]
    recording_assignments: tuple[tuple[str, str], ...]
    registration_group_defaults: tuple[tuple[str, str], ...] = ()
    schema_version: str = CONDITION_TRIGGER_MAPS_SCHEMA_VERSION

    @classmethod
    def from_manifest(cls, value: Mapping[str, Any] | ConditionTriggerMaps) -> ConditionTriggerMaps:
        if isinstance(value, cls):
            value = value.to_manifest()
        value = _mapping(value, "condition_trigger_maps")
        if value.get("schema_version") != CONDITION_TRIGGER_MAPS_SCHEMA_VERSION:
            raise TriggerMapError(f"Unsupported condition trigger map schema {value.get('schema_version')!r}.")
        catalog = _mapping(value.get("canonical_conditions"), "canonical_conditions")
        if not catalog:
            raise TriggerMapError("Select at least one canonical condition.")
        _unique_ids(catalog, "condition ID")
        conditions: list[CanonicalCondition] = []
        labels: set[str] = set()
        for key, raw in catalog.items():
            raw = _mapping(raw, f"Condition {key!r}")
            label = str(raw.get("label") or "").strip()
            if not label or label.casefold() in labels:
                raise TriggerMapError("Canonical condition labels must be nonempty and unique.")
            if "/" in label or "\\" in label:
                raise TriggerMapError("Canonical condition labels cannot contain path separators.")
            conditions.append(CanonicalCondition(key, label))
            labels.add(label.casefold())
        # Reuse output-path collision and safety rules instead of inventing names.
        from .grouping import GroupConfigurationError, validate_condition_output_names

        try:
            validate_condition_output_names(item.label for item in conditions)
        except GroupConfigurationError as exc:
            raise TriggerMapError(str(exc)) from exc
        profiles_raw = _mapping(value.get("profiles"), "profiles")
        if not profiles_raw:
            raise TriggerMapError("Create at least one source trigger profile.")
        _unique_ids(profiles_raw, "profile ID")
        profiles: list[SourceTriggerProfile] = []
        for key, raw in profiles_raw.items():
            raw = _mapping(raw, f"Profile {key!r}")
            pairs = _mapping(raw.get("conditions"), f"Profile {key!r} conditions")
            if set(pairs) != set(catalog):
                raise TriggerMapError(
                    f"Profile {key!r} must map every selected condition exactly "
                    f"(missing: {sorted(set(catalog) - set(pairs))}; unknown: {sorted(set(pairs) - set(catalog))})."
                )
            triggers = tuple(
                ConditionTrigger(item.condition_id,
                                 _code(_mapping(pairs[item.condition_id], "condition markers").get("onset_code")),
                                 _code(pairs[item.condition_id].get("oddball_code")))
                for item in conditions
            )
            onsets = {item.onset_code for item in triggers}
            if len(onsets) != len(triggers):
                raise TriggerMapError(f"Profile {key!r} has duplicate condition onset codes.")
            boundary_raw = raw.get("boundary_only_onset_codes", ())
            if not isinstance(boundary_raw, (list, tuple)):
                raise TriggerMapError("boundary_only_onset_codes must be a list.")
            boundaries = tuple(sorted(_code(code) for code in boundary_raw))
            if len(set(boundaries)) != len(boundaries):
                raise TriggerMapError(f"Profile {key!r} has duplicate boundary-only onset codes.")
            if onsets & set(boundaries):
                raise TriggerMapError(f"Profile {key!r} has overlapping selected and boundary-only onset codes.")
            if (onsets | set(boundaries)) & {item.oddball_code for item in triggers}:
                raise TriggerMapError(f"Profile {key!r} has an onset/oddball code collision.")
            boundary_labels = _mapping(raw.get("boundary_labels", {}), "boundary_labels")
            normalized_labels = tuple(sorted((_code(code), str(label)) for code, label in boundary_labels.items()))
            if len({code for code, _ in normalized_labels}) != len(normalized_labels):
                raise TriggerMapError("Boundary labels must have unique source codes.")
            if any(code not in boundaries for code, _ in normalized_labels):
                raise TriggerMapError("Boundary labels must refer to recognized boundary-only codes.")
            profiles.append(SourceTriggerProfile(key, str(raw.get("label") or key), triggers, boundaries, normalized_labels))
        assignments = _mapping(value.get("recording_assignments"), "recording_assignments")
        _unique_ids(assignments, "recording ID")
        defaults = _mapping(value.get("registration_group_defaults", {}), "registration_group_defaults")
        _unique_ids(defaults, "group ID")
        for name, mappings in (("recording", assignments), ("group default", defaults)):
            for key, profile_id in mappings.items():
                if not isinstance(profile_id, str) or profile_id not in profiles_raw:
                    raise TriggerMapError(f"Unknown profile {profile_id!r} assigned to {name} {key!r}.")
        return cls(tuple(conditions), tuple(profiles), tuple(sorted(assignments.items())), tuple(sorted(defaults.items())))

    def to_manifest(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "canonical_conditions": {item.condition_id: {"label": item.label} for item in self.canonical_conditions},
            "profiles": {profile.profile_id: {
                "label": profile.label,
                "conditions": {item.condition_id: {"onset_code": item.onset_code, "oddball_code": item.oddball_code}
                               for item in profile.conditions},
                "boundary_only_onset_codes": list(profile.boundary_only_onset_codes),
                **({"boundary_labels": {str(code): label for code, label in profile.boundary_labels}}
                   if profile.boundary_labels else {}),
            } for profile in self.profiles},
            "recording_assignments": dict(self.recording_assignments),
            "registration_group_defaults": dict(self.registration_group_defaults),
        }

    def canonical_payload(self) -> dict[str, Any]:
        payload = self.to_manifest()
        payload.pop("registration_group_defaults")
        for profile in payload["profiles"].values():
            profile.pop("label")
            profile.pop("boundary_labels", None)
        return payload

    @property
    def fingerprint(self) -> str:
        return _digest(self.canonical_payload())

    def resolve(self, recording_id: str) -> ResolvedRecordingEventSchema:
        if not isinstance(recording_id, str) or not recording_id.strip():
            raise TriggerMapError("Source trigger maps require a canonical recording ID.")
        assignment = next((item for item in self.recording_assignments if item[0].casefold() == recording_id.casefold()), None)
        if assignment is None:
            raise TriggerMapError(f"No source trigger profile is assigned to recording {recording_id!r}.")
        canonical_recording_id, profile_id = assignment
        profile = next(item for item in self.profiles if item.profile_id == profile_id)
        labels = {item.condition_id: item.label for item in self.canonical_conditions}
        conditions = tuple(ResolvedConditionTrigger(item.condition_id, labels[item.condition_id], item.onset_code, item.oddball_code)
                           for item in profile.conditions)
        # Whole-project semantics intentionally invalidate every interpreted result.
        return ResolvedRecordingEventSchema(canonical_recording_id, profile_id, conditions,
                                            profile.boundary_only_onset_codes, self.fingerprint)


def _context_value(context: Any, name: str, default: Any = None) -> Any:
    return context.get(name, default) if isinstance(context, Mapping) else getattr(context, name, default)


def _protocol(context: Any) -> Any:
    from .frequency_protocol import FrequencyProtocol, normalize_frequency_protocol

    if isinstance(context, FrequencyProtocol):
        return context
    raw = _context_value(context, "frequency_protocol")
    # A serialized protocol itself is also a valid processing snapshot.
    if raw is None and isinstance(context, Mapping) and "presentation_rate_hz" in context:
        raw = context
    return normalize_frequency_protocol(raw) if raw is not None else None


def project_conditions(context: Any) -> tuple[CanonicalCondition, ...]:
    protocol = _protocol(context)
    if protocol is not None and protocol.condition_trigger_maps is not None:
        if _context_value(context, "event_map", {}):
            raise TriggerMapError("A source-mapped project cannot also have an active global event_map.")
        return protocol.condition_trigger_maps.canonical_conditions
    event_map = _context_value(context, "event_map", {})
    return tuple(CanonicalCondition(str(label), str(label)) for label in event_map)


def resolve_recording_event_schema(context: Any, processing_id: str, *, event_map: Mapping[str, Any] | None = None) -> ResolvedRecordingEventSchema:
    protocol = _protocol(context)
    if protocol is None:
        raise TriggerMapError("A frequency protocol is required to resolve trigger interpretation.")
    if protocol.condition_trigger_maps is not None:
        if _context_value(context, "event_map", {}):
            raise TriggerMapError("A source-mapped project cannot also have an active global event_map.")
        return protocol.condition_trigger_maps.resolve(processing_id)
    legacy_map = event_map if event_map is not None else _context_value(context, "event_map", {})
    rows = tuple(ResolvedConditionTrigger(str(label), str(label), _code(code),
                                         protocol.oddball_marker_code_for_condition(code, recording_id=processing_id))
                 for label, code in legacy_map.items())
    return ResolvedRecordingEventSchema(str(processing_id), None, rows, (), protocol.fingerprint)


def _registered_ids(context: Any) -> tuple[str, ...]:
    recordings = _context_value(context, "recordings", {})
    if recordings:
        return tuple(recordings) if isinstance(recordings, Mapping) else tuple(item.recording_id for item in recordings)
    participants = _context_value(context, "participants", {})
    return tuple(participants) if isinstance(participants, Mapping) else tuple(item.participant_id for item in participants)


def validate_project_trigger_maps(context: Any) -> ConditionTriggerMaps | None:
    protocol = _protocol(context)
    if protocol is None or protocol.condition_trigger_maps is None:
        return None
    maps = protocol.condition_trigger_maps
    project_conditions(context)  # Enforce the single authoritative catalog.
    registered = {item.casefold() for item in _registered_ids(context)}
    assigned = {item.casefold() for item, _ in maps.recording_assignments}
    if registered != assigned:
        raise TriggerMapError(
            "Source trigger assignments must cover every registered recording exactly "
            f"(missing: {sorted(registered - assigned)}; unknown: {sorted(assigned - registered)})."
        )
    groups = _context_value(context, "groups", {})
    group_ids = set(groups) if isinstance(groups, Mapping) else {item.group_id for item in groups}
    unknown_defaults = set(dict(maps.registration_group_defaults)) - group_ids
    if unknown_defaults:
        raise TriggerMapError(f"Unknown groups in registration defaults: {sorted(unknown_defaults)}.")
    return maps


def apply_condition_catalog_transition(candidate: dict[str, Any], previous: Mapping[str, Any]) -> bool:
    """Carry explicit exclusions through one old-to-new canonical-ID transition.

    The caller supplies an unpublished candidate whose label-keyed settings still
    refer to the previous catalog. Call once, inside its manifest transaction.
    Home drafts publish this result directly; ordinary Project.save calls it only
    when the on-disk protocol differs. No results or review approvals migrate.
    """
    after_protocol = _protocol(candidate)
    if after_protocol is None or after_protocol.condition_trigger_maps is None:
        return False
    before_protocol = _protocol(previous)
    if before_protocol is not None and before_protocol.condition_trigger_maps is not None:
        before = before_protocol.condition_trigger_maps
    elif _context_value(previous, "event_map", {}):
        before = migrate_legacy_trigger_maps(previous)
    else:
        before = None
    old = {} if before is None else {item.condition_id: item.label for item in before.canonical_conditions}
    new = {item.condition_id: item.label for item in after_protocol.condition_trigger_maps.canonical_conditions}
    if old == new:
        return False
    old_ids = {label.casefold(): ident for ident, label in old.items()}
    new_labels = {label.casefold() for label in new.values()}
    from .preprocessing_settings import (
        normalize_manual_excluded_participant_conditions,
        normalize_preprocessing_settings,
    )

    keys = ("manual_excluded_participant_conditions", "manual_excluded_recording_conditions")
    candidate_preprocessing = _mapping(candidate.get("preprocessing") or {}, "preprocessing")
    candidate_settings = normalize_preprocessing_settings(candidate_preprocessing)
    previous_settings = normalize_preprocessing_settings(previous.get("preprocessing"))
    replacements: dict[str, Any] = {}
    for key in keys:
        current = candidate_settings[key]
        prior = previous_settings[key]
        for labels in (*prior.values(), *current.values()):
            for label in labels:
                ident = old_ids.get(label.casefold())
                if ident is not None and ident not in new:
                    raise TriggerMapError(
                        f"Condition {old[ident]!r} ({ident}) has saved exclusions and cannot be removed or "
                        "replaced by a different condition ID. Keep its ID when renaming it, or explicitly "
                        "clear its exclusions in a separate save before removing it."
                    )
                if ident is None and label.casefold() in new_labels:
                    raise TriggerMapError(
                        f"Saved exclusion {label!r} has no condition ID in the previous catalog. "
                        "Resolve that exclusion before assigning its label to a new condition."
                    )
        # Resolve every original label independently: swaps must not chain.
        remapped = normalize_manual_excluded_participant_conditions({
            identity: [new.get(old_ids.get(label.casefold()), label) for label in labels]
            for identity, labels in current.items()
        })
        if remapped != current:
            replacements[key] = remapped

    # Accepted electrode repairs retain label-keyed, fingerprinted evidence.
    # They need their own reviewed migration rather than a fabricated approval.
    for manifest in (previous, candidate):
        state = (manifest.get("tools") or {}).get("condition_electrode_interpolation") or {}
        for requests in (state.get("requests") or {}).values():
            for label in requests:
                ident = old_ids.get(str(label).casefold())
                if ((ident is not None and new.get(ident) != old[ident])
                        or (ident is None and str(label).casefold() in new_labels)):
                    raise TriggerMapError(
                        f"Condition {label!r} has saved condition-electrode repair requests. "
                        "Resolve or retire those requests before changing its condition label or ID."
                    )
    if replacements:
        candidate["preprocessing"] = {**candidate_preprocessing, **replacements}
    return bool(replacements)


def migrate_legacy_trigger_maps(context: Any) -> ConditionTriggerMaps:
    """Build an explicit opt-in draft, preserving every existing marker schema."""
    protocol = _protocol(context)
    if protocol is None or not protocol.is_ready:
        raise TriggerMapError("Confirm the project frequency and duration protocol before creating source maps.")
    if protocol.condition_trigger_maps is not None:
        return protocol.condition_trigger_maps
    event_map = _mapping(_context_value(context, "event_map", {}), "event_map")
    if not event_map:
        raise TriggerMapError("Add the conditions to the shared map before converting it to source maps.")
    catalog: dict[str, dict[str, str]] = {}
    by_label: dict[str, str] = {}
    for label in event_map:
        base = re.sub(r"[^a-z0-9]+", "_", str(label).lower()).strip("_") or "condition"
        key, suffix = base, 2
        while key in catalog:
            key, suffix = f"{base}_{suffix}", suffix + 1
        catalog[key] = {"label": str(label)}
        by_label[str(label)] = key
    profiles: dict[str, Any] = {}
    assignments: dict[str, str] = {}
    keys: dict[str, str] = {}
    for recording_id in _registered_ids(context):
        schema = resolve_recording_event_schema(context, recording_id)
        pairs = {by_label[item.label]: {"onset_code": item.onset_code, "oddball_code": item.oddball_code} for item in schema.conditions}
        signature = _digest(pairs)
        profile_id = keys.setdefault(signature, f"source_{len(keys) + 1}")
        profiles[profile_id] = {"label": f"Source map {profile_id.removeprefix('source_')}", "conditions": pairs,
                                "boundary_only_onset_codes": []}
        assignments[recording_id] = profile_id
    if not profiles:
        raise TriggerMapError("Register recordings before creating source trigger maps.")
    return ConditionTriggerMaps.from_manifest({"schema_version": CONDITION_TRIGGER_MAPS_SCHEMA_VERSION,
        "canonical_conditions": catalog, "profiles": profiles, "recording_assignments": assignments})


def _draft_baseline(context: Any) -> str:
    protocol = _protocol(context)
    return _digest({"event_map": _context_value(context, "event_map", {}),
                    "frequency_protocol": protocol.to_manifest() if protocol is not None else None,
                    "recording_ids": sorted(_registered_ids(context))})


@dataclass
class TriggerMapDraft:
    """Detached editor state; the caller owns the existing manifest transaction."""
    baseline: str
    payload: dict[str, Any]

    @classmethod
    def from_project(cls, context: Any, *, allow_empty: bool = False) -> TriggerMapDraft:
        protocol = _protocol(context)
        if (allow_empty and protocol is not None and protocol.is_ready
                and protocol.condition_trigger_maps is None and not _context_value(context, "event_map", {})):
            return cls(_draft_baseline(context), {
                "schema_version": CONDITION_TRIGGER_MAPS_SCHEMA_VERSION,
                "canonical_conditions": {},
                "profiles": {"source_1": {"label": "Source 1", "conditions": {}, "boundary_only_onset_codes": []}},
                "recording_assignments": {}, "registration_group_defaults": {},
            })
        maps = migrate_legacy_trigger_maps(context)
        return cls(_draft_baseline(context), maps.to_manifest())

    def validate(self, context: Any) -> ConditionTriggerMaps:
        maps = ConditionTriggerMaps.from_manifest(self.payload)
        validation_context = {
            "frequency_protocol": _protocol(context).with_condition_trigger_maps(maps),
            "event_map": {}, "participants": _context_value(context, "participants", {}),
            "recordings": _context_value(context, "recordings", {}),
            "groups": _context_value(context, "groups", {}),
        }
        validate_project_trigger_maps(validation_context)
        return maps

    def apply_to_manifest(self, current_manifest: Mapping[str, Any]) -> dict[str, Any]:
        if _draft_baseline(current_manifest) != self.baseline:
            raise TriggerMapError("The project changed after this trigger-map draft opened. Reopen it before saving.")
        maps = self.validate(current_manifest)
        result = copy.deepcopy(dict(current_manifest))
        protocol = _protocol(current_manifest)
        if protocol.condition_trigger_maps is None:
            result.setdefault("tools", {}).setdefault("trigger_map_migration", {})["legacy_protocol"] = protocol.to_manifest()
            result["tools"]["trigger_map_migration"]["legacy_event_map"] = copy.deepcopy(result.get("event_map", {}))
        result["event_map"] = {}
        result["frequency_protocol"] = protocol.with_condition_trigger_maps(maps).to_manifest()
        apply_condition_catalog_transition(result, current_manifest)
        return result
