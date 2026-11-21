"""Stable Studio handoff boundary for Toolbox's supported scientific subset.

Application releases are provenance, not format revisions. Historical envelopes
are admitted here once; numerical protocol validation stays with its owner.
Authoring/runtime details are retained as evidence, never interpreted as EEG.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from fractions import Fraction
from typing import Any

HANDOFF_FORMAT = "fpvs-handoff"
HANDOFF_FORMAT_VERSION = 2
LEGACY_CONFIG_VERSIONS = tuple(f"1.{minor}.0" for minor in range(16))

_TOP_FIELDS = frozenset({
    "format", "format_version", "kind", "metadata", "producer", "experiment_category",
    "project", "conditions", "condition_defaults", "stimulus_sets", "task_modules",
    "condition_modifiers", "task_assets", "display", "presentation", "recording",
    "protocol", "session", "triggers", "toolbox", "stimulus_provenance", "completed_session",
})
_CONDITION_FIELDS = frozenset({
    "condition_id", "name", "trigger_code", "base_stimulus_set_id", "oddball_stimulus_set_id",
    "t2_stimulus_set_id", "isi_stimulus_set_id", "attentional_blink", "stimulus_variant",
    "sequence_count", "oddball_cycle_repeats_per_sequence", "base_hz", "stream_duration_seconds",
    "presentation_count", "duty_cycle_mode", "order_index", "instructions", "presentation",
    "pre_task_bindings", "post_task_bindings", "masking_catch",
})
_TRIGGER_FIELDS = frozenset({
    "backend", "enabled", "serial_port", "baudrate", "oddball_trigger_code",
    "allow_nonstandard_oddball_trigger_code", "pulse_width_ms", "reset_code", "reset_delay_ms",
})
_DEFAULT_FIELDS = frozenset({
    "duty_cycle_mode", "sequence_count", "oddball_cycle_repeats_per_sequence",
    "stream_duration_seconds", "presentation_count", "target_repeats_per_image",
})
_COMPLETED_FIELDS = frozenset({
    "session_id", "session_seed", "randomization_mode", "randomization_modes",
    "randomization_seeds", "randomization_algorithm_version", "ordering_policy", "refresh_hz",
    "block_orders", "source_run_dir", "ordered_runs", "execution_id", "participant_number",
    "participant_session_number", "acquisition_evidence", "manual_removed_electrodes",
})
_PROJECT_FIELDS = frozenset({
    "project_id", "name", "template_id", "description", "allow_repeated_participant_sessions",
    "demographics_questions",
})
_SESSION_FIELDS = frozenset({
    "block_count", "session_seed", "randomization_mode", "randomization_modes", "stimulus_seed",
    "fixation_seed", "saved_condition_order", "condition_ordering", "randomize_conditions_per_block",
    "randomize_across_blocks", "inter_condition_mode", "inter_condition_break_seconds",
    "continue_key", "show_condition_title_on_screen",
})
_RECORDING_FIELDS = frozenset({
    "recording_backend", "unicorn_udp_port", "brainproducts_serial_port", "brainproducts_parallel_address",
    "brainproducts_pulse_width_ms", "brainproducts_amplifier", "brainproducts_sampling_rate_hz",
    "acquisition_profile",
})
_EFFECTIVE_BACKENDS = {
    "serial": "serial", "biosemi_active_three": "serial",
    "brainproducts_triggerbox": "brainproducts_triggerbox",
    "brainproducts_parallel": "brainproducts_parallel", "unicorn_udp": "unicorn_udp",
}


def _object(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object.")
    return value


def _known_fields(value: Mapping[str, Any], fields: frozenset[str], field: str) -> None:
    unknown = set(value) - fields
    if unknown:
        names = ", ".join(sorted(str(key) for key in unknown))
        raise ValueError(f"Unsupported Studio fields in {field}: {names}.")


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be non-empty text.")
    return value


def _positive_int(value: Any, field: str) -> None:
    if type(value) is not int or value < 1:
        raise ValueError(f"{field} must be a positive integer.")


def _rate(value: Any, field: str) -> Fraction:
    try:
        if isinstance(value, bool):
            raise ValueError
        result = Fraction(str(value))
        if result <= 0:
            raise ValueError
        return result
    except (ValueError, ZeroDivisionError) as exc:
        raise ValueError(f"{field} must be a finite positive frequency.") from exc


def normalize_studio_handoff(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate an envelope and return detached content without guessing identities.

    Legacy version identity is retained for the existing 1.0/1.1 protocol-default
    adapter. Current handoffs require their explicit contract and provenance.
    """
    data = deepcopy(dict(_object(payload, "FPVS config")))
    current = any(key in data for key in ("format", "format_version", "kind"))
    if current:
        if "schema_version" in data:
            raise ValueError("Studio config cannot mix schema_version with the handoff envelope.")
        if data.get("format") != HANDOFF_FORMAT:
            raise ValueError(f"Unsupported Studio handoff format: {data.get('format')!r}.")
        if type(data.get("format_version")) is not int or data["format_version"] != HANDOFF_FORMAT_VERSION:
            raise ValueError(f"Unsupported Studio handoff format revision: {data.get('format_version')!r}.")
        if data.get("kind") not in ("setup", "completed_session"):
            raise ValueError(f"Unsupported Studio handoff kind: {data.get('kind')!r}.")
        _known_fields(data, _TOP_FIELDS, "handoff")
        _object(data.get("metadata", {}), "metadata")
        producer = _object(data.get("producer"), "producer")
        _known_fields(producer, frozenset({"application", "version", "exported_at"}), "producer")
        _text(producer.get("application"), "producer.application")
        _text(producer.get("version"), "producer.version")
        project = _object(data.get("project"), "project")
        _known_fields(project, _PROJECT_FIELDS, "project")
        _text(project.get("project_id"), "project.project_id")
        _object(data.get("protocol"), "protocol")
        if "session" in data:
            _known_fields(_object(data["session"], "session"), _SESSION_FIELDS, "session")
        if data.get("recording") is not None:
            recording = _object(data["recording"], "recording")
            _known_fields(recording, _RECORDING_FIELDS, "recording")
            _recording_backend(recording.get("recording_backend"), "recording.recording_backend")
    elif data.get("schema_version") not in LEGACY_CONFIG_VERSIONS:
        raise ValueError(f"Unsupported FPVS config schema version: {data.get('schema_version')!r}.")

    category = data.get("experiment_category", "fpvs_oddball")
    if category not in ("fpvs_oddball", "cognitive_load_fpvs"):
        raise ValueError(f"Unsupported Studio experiment category for FPVS processing: {category!r}.")
    _validate_protocol_semantics(data, strict=current)
    _validate_toolbox_summary(data)
    _validate_completion(data, strict=current)
    return data


def _validate_protocol_semantics(data: Mapping[str, Any], *, strict: bool) -> None:
    protocol = data.get("protocol")
    if protocol is not None:
        protocol = _object(protocol, "protocol")
        _known_fields(protocol, frozenset({"base_hz", "oddball_every_n"}), "protocol")
    defaults = data.get("condition_defaults")
    if defaults is not None:
        defaults = _object(defaults, "condition_defaults")
        _known_fields(defaults, _DEFAULT_FIELDS, "condition_defaults")
        _validate_duration_and_count(defaults, "condition_defaults")
    conditions = data.get("conditions")
    if not isinstance(conditions, list) or not conditions:
        raise ValueError("FPVS config must contain at least one condition.")
    condition_ids: set[str] = set()
    for index, raw in enumerate(conditions):
        field = f"conditions[{index}]"
        condition = _object(raw, field)
        if strict:
            _known_fields(condition, _CONDITION_FIELDS, field)
            condition_id = _text(condition.get("condition_id"), f"{field}.condition_id")
            if condition_id in condition_ids:
                raise ValueError(f"Duplicate Studio condition_id: {condition_id!r}.")
            condition_ids.add(condition_id)
        _validate_duration_and_count(condition, field)
        if condition.get("base_hz") is not None:
            if protocol is None or _rate(condition["base_hz"], f"{field}.base_hz") != _rate(protocol.get("base_hz"), "protocol.base_hz"):
                raise ValueError("Toolbox does not support condition-specific frequencies; all conditions must use the shared protocol rate.")
        if condition.get("attentional_blink") is not None:
            raise ValueError("Toolbox does not support Attentional-Blink condition semantics.")
        if condition.get("masking_catch", False) is not False:
            raise ValueError("Toolbox does not support masking/catch condition semantics.")
    modifiers = data.get("condition_modifiers", [])
    if not isinstance(modifiers, list):
        raise ValueError("condition_modifiers must be an array.")
    for modifier in modifiers:
        if _object(modifier, "condition modifier").get("masking") is not None:
            raise ValueError("Toolbox does not support masking/catch condition semantics.")
    if strict:
        triggers = _object(data.get("triggers"), "triggers")
        _known_fields(triggers, _TRIGGER_FIELDS, "triggers")


def _validate_duration_and_count(value: Mapping[str, Any], field: str) -> None:
    if value.get("stream_duration_seconds") is not None:
        raise ValueError("Toolbox does not support Studio stream-duration overrides; use a shared sequence/repeat protocol.")
    if value.get("presentation_count") is not None:
        _positive_int(value["presentation_count"], f"{field}.presentation_count")
    if "duty_cycle_mode" in value and value["duty_cycle_mode"] not in (
        "continuous", "blank_50", "sinusoidal",
    ):
        raise ValueError(f"Unsupported Studio duty-cycle mode in {field}.")


def _validate_toolbox_summary(data: Mapping[str, Any]) -> None:
    summary = data.get("toolbox")
    if summary is None:
        return
    summary = _object(summary, "toolbox")
    project = _object(data.get("project"), "project")
    if "project_title" in summary and summary["project_title"] != project.get("name"):
        raise ValueError("toolbox.project_title conflicts with project.name.")
    if "event_map" in summary:
        event_map = {
            _text(item.get("name"), "condition.name"): item.get("trigger_code")
            for item in data["conditions"]
        }
        if summary["event_map"] != event_map:
            raise ValueError("toolbox.event_map conflicts with the condition trigger map.")
    triggers = _object(data.get("triggers", {}), "triggers")
    if "oddball_trigger_code" in summary and summary["oddball_trigger_code"] != triggers.get("oddball_trigger_code", 55):
        raise ValueError("toolbox.oddball_trigger_code conflicts with triggers.oddball_trigger_code.")


def _validate_completion(data: Mapping[str, Any], *, strict: bool) -> None:
    completed = data.get("completed_session")
    if strict and (data["kind"] == "completed_session") != (completed is not None):
        raise ValueError("Studio handoff kind must agree with its completed_session content.")
    if completed is None:
        return
    completed = _object(completed, "completed_session")
    if strict:
        _known_fields(completed, _COMPLETED_FIELDS, "completed_session")
        _text(completed.get("session_id"), "completed_session.session_id")
    for field in ("participant_number", "execution_id"):
        if completed.get(field) is not None:
            _text(completed[field], f"completed_session.{field}")
    if completed.get("participant_session_number") is not None:
        _positive_int(completed["participant_session_number"], "completed_session.participant_session_number")
    electrodes = completed.get("manual_removed_electrodes")
    if electrodes is not None:
        if not isinstance(electrodes, list):
            raise ValueError("completed_session.manual_removed_electrodes must be an array or null.")
        for electrode in electrodes:
            _text(electrode, "completed_session.manual_removed_electrodes entry")
        if completed.get("participant_number") is None:
            raise ValueError("Completed removed electrodes require the Studio participant_number.")
    evidence = completed.get("acquisition_evidence")
    if evidence is not None:
        _validate_acquisition_identity(data, completed, _object(evidence, "acquisition_evidence"))


def _validate_acquisition_identity(
    data: Mapping[str, Any], completed: Mapping[str, Any], evidence: Mapping[str, Any],
) -> None:
    if evidence.get("schema_version") != "1.0":
        raise ValueError("Unsupported Studio acquisition-evidence revision.")
    if evidence.get("contract_status") != "candidate_receiver_validation_pending":
        raise ValueError("Unsupported Studio acquisition-evidence status.")
    if evidence.get("state") != "completed" or evidence.get("export_error"):
        raise ValueError("Completed Studio handoff requires successfully finalized acquisition evidence.")
    project = _object(data.get("project"), "project")
    if evidence.get("project_id") != project.get("project_id") or not evidence.get("project_id"):
        raise ValueError("Studio acquisition evidence belongs to a different project.")
    for field in ("session_id", "execution_id", "participant_number", "participant_session_number"):
        if completed.get(field) != evidence.get(field):
            raise ValueError(f"Studio acquisition evidence conflicts with completed_session.{field}.")
    for field in ("session_id", "execution_id", "participant_number"):
        _text(evidence.get(field), f"acquisition_evidence.{field}")
    recording = _object(evidence.get("recording"), "acquisition_evidence.recording")
    if type(recording.get("schema_version")) is not int or recording["schema_version"] != 1:
        raise ValueError("Unsupported Studio recording snapshot revision.")
    if recording.get("effective_backend") == "null":
        raise ValueError("Test/Pilot evidence cannot establish a completed recording handoff.")
    if recording.get("effective_backend") not in (
        "serial", "brainproducts_triggerbox", "brainproducts_parallel", "unicorn_udp",
    ):
        raise ValueError("Unsupported Studio recording backend.")
    selected = _recording_backend(recording.get("selected_backend"), "recording.selected_backend")
    if recording["effective_backend"] != _EFFECTIVE_BACKENDS[selected]:
        raise ValueError("Studio selected and effective recording backends conflict.")
    declared = data.get("recording")
    if declared is not None:
        declared = _object(declared, "recording")
        if declared.get("recording_backend") != selected:
            raise ValueError("Studio acquisition recording backend conflicts with its project declaration.")
    profiles = []
    for owner, field in (
        (declared, "recording"), (data.get("toolbox"), "toolbox"),
        (evidence, "acquisition_evidence"), (recording, "recording snapshot"),
    ):
        if owner is not None:
            profile = _object(owner, field).get("acquisition_profile")
            if profile is not None:
                profiles.append(_object(profile, f"{field}.acquisition_profile"))
    if profiles and any(profile != profiles[0] for profile in profiles[1:]):
        raise ValueError("Studio acquisition profiles conflict across the handoff.")
    runs = evidence.get("runs")
    planned = completed.get("ordered_runs")
    if not isinstance(runs, list) or not runs or not isinstance(planned, list):
        raise ValueError("Completed acquisition evidence requires ordered runs.")
    run_ids = []
    for raw in runs:
        run = _object(raw, "acquisition run")
        if run.get("state") != "completed":
            raise ValueError("Completed acquisition evidence contains an unfinished run.")
        run_ids.append(_text(run.get("run_id"), "acquisition run_id"))
    planned_ids = [_object(run, "completed run").get("run_id") for run in planned]
    if run_ids != planned_ids or len(set(run_ids)) != len(run_ids):
        raise ValueError("Studio acquisition run order does not match completed_session.ordered_runs.")
    conditions = {
        _text(item.get("condition_id"), "condition.condition_id"): item.get("name")
        for item in data["conditions"]
    }
    for actual, expected in zip(runs, planned):
        condition_id = _text(expected.get("condition_id"), "completed run.condition_id")
        if condition_id not in conditions or any(
            actual.get(field) != expected.get(field) for field in ("condition_id", "condition_name")
        ) or expected.get("condition_name") != conditions[condition_id]:
            raise ValueError("Studio acquisition run condition does not match the project condition.")


def _recording_backend(value: Any, field: str) -> str:
    backend = _text(value, field)
    if backend not in _EFFECTIVE_BACKENDS:
        raise ValueError(f"Unsupported Studio recording backend in {field}: {backend!r}.")
    return backend
