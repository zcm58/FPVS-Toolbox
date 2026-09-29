"""Read-only adapter for Studio's candidate, receiver-validation-pending handoff.

The observed Studio AcquisitionEvidence schema is string ``1.0``; its nested
RecordingSnapshot schema is integer ``1``. This is not a finalized shared
contract, a project importer, receiver proof, or scientific-processing approval.
Callback clocks remain run-relative. No EEG samples or timing offsets are inferred.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
import json
import math
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any


SCHEMA_VERSION = "1.0"
CONTRACT_STATUS = "candidate_receiver_validation_pending"
_CLOCK_MEANINGS = {
    "wall_clock_meaning": "UTC evidence write time; not EEG synchronization",
    "callback_time_units": "seconds",
    "callback_time_origin": "per-run playback clock after warmup; not EEG time",
    "sent_status_meaning": "local transport submission only; receipt and disk logging unknown",
    "persistence_boundary": (
        "between runs and on orderly failure; abrupt process loss may omit current run"
    ),
}
_RUN_STATES = {"not_started", "started", "completed", "aborted", "interrupted"}


class StudioAcquisitionEvidenceError(ValueError):
    """The evidence does not satisfy the supported candidate contract."""


@dataclass(frozen=True)
class StudioAttemptedEvent:
    trigger_index: int
    frame_index: int
    time_s: float | None
    code: int
    label: str
    backend_name: str
    status: str
    message: str | None


@dataclass(frozen=True)
class StudioAcquisitionRun:
    run_id: str
    condition_id: str
    condition_name: str
    code_map: tuple[tuple[int, str], ...]
    planned_event_count: int
    attempted_events: tuple[StudioAttemptedEvent, ...]
    state: str


@dataclass(frozen=True)
class StudioAcquisitionEvidence:
    schema_version: str
    contract_status: str
    execution_id: str
    project_id: str
    participant_number: str
    studio_version: str
    state: str
    recording: Mapping[str, Any]
    runs: tuple[StudioAcquisitionRun, ...]
    raw_payload: Mapping[str, Any]

    @property
    def attempted_events(self) -> tuple[StudioAttemptedEvent, ...]:
        """Preserve source run/event order, including repeated codes and errors."""
        return tuple(event for run in self.runs for event in run.attempted_events)


@dataclass(frozen=True)
class ReviewedRecordingAssociation:
    """Caller-reviewed binding, never inferred from filenames or Studio hints."""

    execution_id: str
    recording_id: str
    raw_sha256: str
    review_id: str


@dataclass(frozen=True)
class StudioMarkerComparison:
    """Code/order comparison only; not receiver, clock, or scientific approval."""

    association: ReviewedRecordingAssociation
    status: str
    code_sequence_equal: bool
    attempted_count: int
    recorded_count: int
    send_error_count: int


def _object(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise StudioAcquisitionEvidenceError(f"{field} must be an object with string keys.")
    return value


def _text(value: Any, field: str, *, optional: bool = False) -> str | None:
    if optional and value is None:
        return None
    if type(value) is not str or (not optional and not value.strip()):
        raise StudioAcquisitionEvidenceError(f"{field} must be a nonblank string.")
    return value


def _integer(value: Any, field: str, minimum: int = 0, maximum: int | None = None) -> int:
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        raise StudioAcquisitionEvidenceError(f"{field} must be an integer in the supported range.")
    return value


def _choice(value: Any, field: str, choices: set[str]) -> str:
    if type(value) is not str or value not in choices:
        raise StudioAcquisitionEvidenceError(f"Unsupported {field}: {value!r}.")
    return value


def _array(value: Any, field: str) -> list[Any] | tuple[Any, ...]:
    if not isinstance(value, (list, tuple)):
        raise StudioAcquisitionEvidenceError(f"{field} must be an array.")
    return value


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in _object(value, "JSON").items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    raise StudioAcquisitionEvidenceError("Evidence must contain only finite JSON values.")


def _utc_datetime(value: Any, field: str) -> datetime:
    text = _text(value, field)
    try:
        result = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise StudioAcquisitionEvidenceError(f"{field} must be a UTC datetime.") from exc
    if result.utcoffset() != timedelta(0):
        raise StudioAcquisitionEvidenceError(f"{field} must have an explicit UTC offset.")
    return result


def _event(value: Any) -> StudioAttemptedEvent:
    item = _object(value, "attempted event")
    time_s = item.get("time_s")
    if time_s is not None and (
        type(time_s) not in (int, float) or not math.isfinite(time_s) or time_s < 0
    ):
        raise StudioAcquisitionEvidenceError("time_s must be finite, nonnegative, or null.")
    return StudioAttemptedEvent(
        trigger_index=_integer(item.get("trigger_index"), "trigger_index"),
        frame_index=_integer(item.get("frame_index"), "frame_index"),
        time_s=time_s,
        code=_integer(item.get("code"), "code", 1, 255),
        label=_text(item.get("label"), "label"),
        backend_name=_choice(item.get("backend_name"), "backend_name", {"unicorn_udp"}),
        status=_choice(item.get("status"), "attempt status", {"sent", "error"}),
        message=_text(item.get("message"), "message", optional=True),
    )


def parse_studio_acquisition_evidence(payload: Mapping[str, Any]) -> StudioAcquisitionEvidence:
    """Validate the observed envelope and expose immutable ordered attempt evidence.

    Additional JSON fields are preserved immutably but are not interpreted. Optional
    null fields may be absent, matching Studio's exclude-none serialization.
    """
    data = _object(_freeze(_object(payload, "evidence")), "evidence")
    _choice(data.get("schema_version"), "schema_version", {SCHEMA_VERSION})
    _choice(data.get("contract_status"), "contract_status", {CONTRACT_STATUS})
    for field, expected in _CLOCK_MEANINGS.items():
        _choice(data.get(field), field, {expected})
    _utc_datetime(data.get("created_at_utc"), "created_at_utc")
    _utc_datetime(data.get("updated_at_utc"), "updated_at_utc")
    state = _choice(data.get("state"), "state", {"prepared", "running", "completed", "aborted", "interrupted"})
    if data.get("participant_session_number") is not None:
        _integer(data["participant_session_number"], "participant_session_number", 1)
    for field in ("session_id", "abort_reason", "export_error"):
        _text(data.get(field), field, optional=True)
    recording = _object(data.get("recording"), "recording")
    _integer(recording.get("schema_version"), "recording.schema_version", 1, 1)
    _choice(recording.get("selected_backend"), "selected_backend", {"unicorn_udp"})
    _choice(recording.get("effective_backend"), "effective_backend", {"unicorn_udp", "null"})
    _choice(recording.get("selection_source"), "selection_source", {"legacy_project", "local_settings"})
    _choice(recording.get("udp_host"), "udp_host", {"127.0.0.1"})
    _integer(recording.get("udp_port"), "udp_port", 1, 65535)
    if type(recording.get("operator_confirmed_raw_bdf_recording")) is not bool:
        raise StudioAcquisitionEvidenceError("operator_confirmed_raw_bdf_recording must be boolean.")
    _choice(recording.get("receiver_validation"), "receiver_validation", {"pending"})
    for field, value in (("recorded_marker_integrity", "unknown"), ("physical_timing", "uncharacterized"), ("acquisition_status", "unknown")):
        _choice(recording.get(field), field, {value})
    for field in ("recording_association", "recorder_version"):
        _text(recording.get(field), field, optional=True)
    runs = []
    for value in _array(data.get("runs"), "runs"):
        item = _object(value, "run")
        code_map = []
        for entry in _array(item.get("code_map"), "code_map"):
            entry = _object(entry, "code_map entry")
            code_map.append((_integer(entry.get("code"), "code", 1, 255), _text(entry.get("label"), "label")))
        if item.get("completed_frames") is not None:
            _integer(item["completed_frames"], "completed_frames")
        _text(item.get("abort_reason"), "abort_reason", optional=True)
        runs.append(StudioAcquisitionRun(
            run_id=_text(item.get("run_id"), "run_id"),
            condition_id=_text(item.get("condition_id"), "condition_id"),
            condition_name=_text(item.get("condition_name"), "condition_name"),
            code_map=tuple(code_map),
            planned_event_count=_integer(item.get("planned_event_count"), "planned_event_count"),
            attempted_events=tuple(_event(event) for event in _array(item.get("attempted_events"), "attempted_events")),
            state=_choice(item.get("state"), "run state", _RUN_STATES),
        ))
    if len({run.run_id for run in runs}) != len(runs):
        raise StudioAcquisitionEvidenceError("Duplicate run_id makes run association ambiguous.")
    return StudioAcquisitionEvidence(
        schema_version=SCHEMA_VERSION, contract_status=CONTRACT_STATUS,
        execution_id=_text(data.get("execution_id"), "execution_id"),
        project_id=_text(data.get("project_id"), "project_id"),
        participant_number=_text(data.get("participant_number"), "participant_number"),
        studio_version=_text(data.get("studio_version"), "studio_version"),
        state=state, recording=recording, runs=tuple(runs), raw_payload=data,
    )


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise StudioAcquisitionEvidenceError(f"Duplicate JSON key: {key}.")
        result[key] = value
    return result


def load_studio_acquisition_evidence(path: str | Path) -> StudioAcquisitionEvidence:
    """Read only the explicitly selected file; do not discover or modify projects."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StudioAcquisitionEvidenceError(f"Cannot read Studio acquisition evidence: {exc}") from exc
    return parse_studio_acquisition_evidence(payload)


def reconcile_studio_marker_codes(
    evidence: StudioAcquisitionEvidence,
    recorded_codes: Sequence[int],
    *,
    association: ReviewedRecordingAssociation,
) -> StudioMarkerComparison:
    """Compare the entire reviewed recording's code order, never timing or EEG.

    The caller supplies canonical recorded events and a separately reviewed raw-file
    binding. Studio's optional recording_association string is only an operator hint.
    Exact equality cannot establish receiver integrity or enable processing.
    """
    if not isinstance(association, ReviewedRecordingAssociation):
        raise StudioAcquisitionEvidenceError("A caller-reviewed recording association is required.")
    for field in ("execution_id", "recording_id", "review_id"):
        _text(getattr(association, field), field)
    if association.execution_id != evidence.execution_id:
        raise StudioAcquisitionEvidenceError("Reviewed association belongs to a different Studio execution.")
    if type(association.raw_sha256) is not str or re.fullmatch(r"[0-9a-f]{64}", association.raw_sha256) is None:
        raise StudioAcquisitionEvidenceError("Reviewed association requires a lowercase raw-file SHA256.")
    if evidence.recording["effective_backend"] != "unicorn_udp":
        raise StudioAcquisitionEvidenceError("Disabled marker output cannot be reconciled as Unicorn emission.")
    codes = tuple(_integer(code, "recorded code", 1, 255) for code in recorded_codes)
    attempts = evidence.attempted_events
    equal = tuple(event.code for event in attempts) == codes
    errors = sum(event.status == "error" for event in attempts)
    complete = evidence.state == "completed" and bool(evidence.runs) and all(
        run.state == "completed" and len(run.attempted_events) == run.planned_event_count
        for run in evidence.runs
    )
    status = "code_sequence_match" if equal else "code_sequence_mismatch"
    if errors:
        status = "sender_errors_unresolved"
    elif not complete:
        status = "incomplete_sender_evidence"
    return StudioMarkerComparison(association, status, equal, len(attempts), len(codes), errors)
