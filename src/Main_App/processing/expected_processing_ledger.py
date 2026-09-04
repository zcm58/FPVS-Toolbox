"""Versioned QC-20 expected recording-condition ledger foundation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from fractions import Fraction
import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, Sequence
from uuid import uuid4

from Main_App.processing.analysis_spans import (
    AnalysisSpanPlanError,
    read_source_analysis_span_plan,
)
from Main_App.processing.marker_integrity import (
    MARKER_DECISION_EXCLUDE,
    MARKER_DECISION_RETAIN_FULL,
    MARKER_DECISION_USE_CONTIGUOUS,
    MARKER_INTEGRITY_METHOD_VERSION,
    ApprovedOccurrenceSpan,
    MarkerIntegrityError,
)
from Main_App.projects.frequency_protocol import (
    FrequencyProtocol,
    FrequencyProtocolError,
    normalize_frequency_protocol,
    validate_protocol_condition_codes,
)
from Main_App.projects.preprocessing_settings import (
    normalize_manual_excluded_participant_conditions,
    normalize_manual_excluded_participants,
    normalize_manual_excluded_recording_conditions,
    normalize_manual_excluded_recordings,
)

if TYPE_CHECKING:
    from Main_App.processing.processing_ledger import (
        ProcessingInputState,
        ProcessingPlan,
    )

EXPECTED_RECORDING_CONDITION_PLAN_VERSION = "expected_recording_condition_plan_v1"
EXPECTED_RECORDING_CONDITION_PLAN_LEDGER_KEY = "expected_recording_condition_plan"
EXPECTED_PLANNING_STATE_PLANNED = "planned"
EXPECTED_PLANNING_STATE_LEGACY_UNKNOWN = "legacy_unknown"
EXPECTED_WORKBOOK_REQUIRED = "required"
EXPECTED_WORKBOOK_NOT_REQUIRED = "not_required"
EXPECTED_WORKBOOK_UNRESOLVED = "unresolved"
EXPECTED_RECORDING_ACTION_PROCESS = "process_recording"
EXPECTED_RECORDING_ACTION_EXCLUDE = "exclude_recording"
EXPECTED_RECORDING_ACTION_LEGACY_UNKNOWN = "legacy_unknown"
EXPECTED_CELL_ACTION_PROCESS = "process_condition"
EXPECTED_CELL_ACTION_EXCLUDE_CONDITION = "exclude_condition"
EXPECTED_CELL_ACTION_EXCLUDE_RECORDING = "exclude_with_recording"
EXPECTED_CELL_ACTION_LEGACY_UNKNOWN = "legacy_unknown"
_EXPECTED_PLANNING_STATES = frozenset(
    {
        EXPECTED_PLANNING_STATE_PLANNED,
        EXPECTED_PLANNING_STATE_LEGACY_UNKNOWN,
    }
)
_EXPECTED_WORKBOOK_REQUIREMENTS = frozenset(
    {
        EXPECTED_WORKBOOK_REQUIRED,
        EXPECTED_WORKBOOK_NOT_REQUIRED,
        EXPECTED_WORKBOOK_UNRESOLVED,
    }
)
_EXPECTED_RECORDING_ACTIONS = frozenset(
    {
        EXPECTED_RECORDING_ACTION_PROCESS,
        EXPECTED_RECORDING_ACTION_EXCLUDE,
        EXPECTED_RECORDING_ACTION_LEGACY_UNKNOWN,
    }
)
_EXPECTED_CELL_ACTIONS = frozenset(
    {
        EXPECTED_CELL_ACTION_PROCESS,
        EXPECTED_CELL_ACTION_EXCLUDE_CONDITION,
        EXPECTED_CELL_ACTION_EXCLUDE_RECORDING,
        EXPECTED_CELL_ACTION_LEGACY_UNKNOWN,
    }
)
_PLANNED_MARKER_DISPOSITIONS = frozenset(
    {
        "automatic_clean",
        MARKER_DECISION_RETAIN_FULL,
        MARKER_DECISION_USE_CONTIGUOUS,
        MARKER_DECISION_EXCLUDE,
    }
)


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)


def _raw_file_metadata(file_path: Path) -> dict[str, Any]:
    stat = Path(file_path).stat()
    return {
        "raw_file": str(Path(file_path).resolve()),
        "raw_size": int(stat.st_size),
        "raw_mtime_ns": int(stat.st_mtime_ns),
    }


def _recording_identity_payload(info: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"participant_id": info.subject_id}
    if info.recording_id:
        payload["recording_id"] = info.recording_id
    if info.session_id:
        payload["session_id"] = info.session_id
    if info.session_label:
        payload["session_label"] = info.session_label
    if info.visit_index is not None:
        payload["visit_index"] = int(info.visit_index)
    if info.source_id:
        payload["source_id"] = info.source_id
    if info.days_from_baseline is not None:
        payload["days_from_baseline"] = float(info.days_from_baseline)
    return payload


def _load_ledger(project_root: Path) -> dict[str, Any]:
    from Main_App.processing.processing_ledger import load_ledger

    return load_ledger(project_root)


def _save_ledger(project_root: Path, ledger: Mapping[str, Any]) -> None:
    from Main_App.processing.processing_ledger import save_ledger

    save_ledger(project_root, ledger)


def _current_processing_fingerprint_version() -> str:
    from Main_App.processing.processing_ledger import PROCESSING_FINGERPRINT_VERSION

    return PROCESSING_FINGERPRINT_VERSION


class ExpectedRecordingConditionPlanError(ValueError):
    """Raised when the QC-20 expected matrix is incomplete or stale."""


def _payload_fingerprint(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _validate_no_output_decision(
    value: Mapping[str, Any] | None,
    *,
    expected_decision: str,
    field_name: str,
) -> None:
    if not isinstance(value, Mapping):
        raise ExpectedRecordingConditionPlanError(
            f"{field_name} requires a structured no-output decision."
        )
    if str(value.get("decision") or "") != expected_decision:
        raise ExpectedRecordingConditionPlanError(
            f"{field_name} has a stale decision type."
        )
    for key in ("reason", "source", "recorded_at_utc", "reviewer_identity_status"):
        _required_plan_text(value.get(key), field_name=f"{field_name}.{key}")
    if not isinstance(value.get("scope"), Mapping):
        raise ExpectedRecordingConditionPlanError(
            f"{field_name}.scope must be an object."
        )
    if not isinstance(value.get("evidence"), Mapping):
        raise ExpectedRecordingConditionPlanError(
            f"{field_name}.evidence must be an object."
        )


def _decision_payload(
    *,
    decision: str,
    reason: str,
    source: str,
    recorded_at_utc: str,
    scope: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    """Record a truthful current planning decision without inventing identity."""

    return {
        "decision": decision,
        "reason": _required_plan_text(reason, field_name="planning decision reason"),
        "source": _required_plan_text(source, field_name="planning decision source"),
        "recorded_at_utc": _required_plan_text(
            recorded_at_utc,
            field_name="planning decision recorded_at_utc",
        ),
        "reviewer_identity": None,
        "reviewer_identity_status": "not_collected",
        "scope": dict(scope),
        "evidence": dict(evidence),
    }


def _required_plan_text(value: Any, *, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ExpectedRecordingConditionPlanError(f"{field_name} cannot be blank.")
    return text


def _payload_sequence(value: Any, *, field_name: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ExpectedRecordingConditionPlanError(f"{field_name} must be a list.")
    return value


def _fraction_identity(value: Any, *, field_name: str) -> str:
    if isinstance(value, bool):
        raise ExpectedRecordingConditionPlanError(
            f"{field_name} must be a positive sampling rate."
        )
    try:
        fraction = value if isinstance(value, Fraction) else Fraction(str(value).strip())
    except (AttributeError, ValueError, ZeroDivisionError) as exc:
        raise ExpectedRecordingConditionPlanError(
            f"{field_name} must be a positive sampling rate."
        ) from exc
    if fraction <= 0:
        raise ExpectedRecordingConditionPlanError(
            f"{field_name} must be a positive sampling rate."
        )
    return str(fraction)


@dataclass(frozen=True, slots=True)
class ExpectedOccurrencePlan:
    """One reviewed marker occurrence expected by a future processing receipt.

    ``planning_state`` and ``planned_disposition`` describe what the current run
    intends to do. They are deliberately separate from a processing outcome;
    wave 3 receipts will record whether the intended contribution actually
    succeeded.
    """

    condition_label: str
    condition_code: int
    repetition_index: int
    planning_state: str
    planned_disposition: str
    source_sampling_rate_hz: str
    source_start_sample: int | None
    source_stop_sample: int | None
    marker_plan_fingerprint: str
    approved_span_fingerprint: str
    decision_payload: Mapping[str, Any] | None
    planning_issues: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _required_plan_text(self.condition_label, field_name="condition_label")
        if int(self.condition_code) <= 0:
            raise ExpectedRecordingConditionPlanError(
                "condition_code must be a positive integer."
            )
        if int(self.repetition_index) < 0:
            raise ExpectedRecordingConditionPlanError(
                "repetition_index cannot be negative."
            )
        if self.planning_state != EXPECTED_PLANNING_STATE_PLANNED:
            raise ExpectedRecordingConditionPlanError(
                "An occurrence with reviewed marker evidence must be in the "
                "planned state."
            )
        if self.planned_disposition not in _PLANNED_MARKER_DISPOSITIONS:
            raise ExpectedRecordingConditionPlanError(
                f"Unsupported planned marker disposition {self.planned_disposition!r}."
            )
        canonical_sampling_rate = _fraction_identity(
            self.source_sampling_rate_hz,
            field_name="source_sampling_rate_hz",
        )
        if self.source_sampling_rate_hz != canonical_sampling_rate:
            raise ExpectedRecordingConditionPlanError(
                "source_sampling_rate_hz must use its canonical exact identity."
            )
        _required_plan_text(
            self.marker_plan_fingerprint,
            field_name="marker_plan_fingerprint",
        )
        _required_plan_text(
            self.approved_span_fingerprint,
            field_name="approved_span_fingerprint",
        )
        if self.planned_disposition == MARKER_DECISION_EXCLUDE:
            if self.source_start_sample is not None or self.source_stop_sample is not None:
                raise ExpectedRecordingConditionPlanError(
                    "A planned excluded occurrence cannot contain an analysis span."
                )
        elif (
            self.source_start_sample is None
            or self.source_stop_sample is None
            or int(self.source_start_sample) < 0
            or int(self.source_stop_sample) <= int(self.source_start_sample)
        ):
            raise ExpectedRecordingConditionPlanError(
                "A planned contributing occurrence requires a positive exact span."
            )
        if self.decision_payload is not None and not isinstance(
            self.decision_payload,
            Mapping,
        ):
            raise ExpectedRecordingConditionPlanError(
                "decision_payload must be an object when present."
            )

    @property
    def occurrence_key(self) -> str:
        return f"{self.condition_code}:{self.repetition_index}"

    @property
    def plans_workbook_contribution(self) -> bool:
        return self.planned_disposition != MARKER_DECISION_EXCLUDE

    @property
    def source_sample_count(self) -> int | None:
        if self.source_start_sample is None or self.source_stop_sample is None:
            return None
        return int(self.source_stop_sample) - int(self.source_start_sample)

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "condition_label": self.condition_label,
            "condition_code": int(self.condition_code),
            "repetition_index": int(self.repetition_index),
            "planning_state": self.planning_state,
            "planned_disposition": self.planned_disposition,
            "source_sampling_rate_hz": self.source_sampling_rate_hz,
            "source_start_sample": self.source_start_sample,
            "source_stop_sample": self.source_stop_sample,
            "source_sample_count": self.source_sample_count,
            "marker_plan_fingerprint": self.marker_plan_fingerprint,
            "approved_span_fingerprint": self.approved_span_fingerprint,
            "decision_payload": (
                dict(self.decision_payload)
                if self.decision_payload is not None
                else None
            ),
            "planning_issues": list(self.planning_issues),
            # A planned disposition is evidence for the intended run. It is not
            # proof that processing retained, excluded, or exported the item.
            "final_outcome": None,
        }

    @property
    def fingerprint(self) -> str:
        return _payload_fingerprint(self.canonical_payload())

    def to_payload(self) -> dict[str, Any]:
        payload = self.canonical_payload()
        payload["fingerprint"] = self.fingerprint
        return payload

    @classmethod
    def from_payload(cls, value: Mapping[str, Any]) -> "ExpectedOccurrencePlan":
        if not isinstance(value, Mapping):
            raise ExpectedRecordingConditionPlanError(
                "Expected occurrence plan must be an object."
            )
        if value.get("final_outcome") is not None:
            raise ExpectedRecordingConditionPlanError(
                "Expected occurrence plans cannot claim a final processing outcome."
            )
        raw_decision = value.get("decision_payload")
        raw_issues = _payload_sequence(
            value.get("planning_issues", ()),
            field_name="planning_issues",
        )
        try:
            result = cls(
                condition_label=str(value["condition_label"]),
                condition_code=int(value["condition_code"]),
                repetition_index=int(value["repetition_index"]),
                planning_state=str(value["planning_state"]),
                planned_disposition=str(value["planned_disposition"]),
                source_sampling_rate_hz=str(value["source_sampling_rate_hz"]),
                source_start_sample=(
                    int(value["source_start_sample"])
                    if value.get("source_start_sample") is not None
                    else None
                ),
                source_stop_sample=(
                    int(value["source_stop_sample"])
                    if value.get("source_stop_sample") is not None
                    else None
                ),
                marker_plan_fingerprint=str(value["marker_plan_fingerprint"]),
                approved_span_fingerprint=str(value["approved_span_fingerprint"]),
                decision_payload=(
                    dict(raw_decision) if isinstance(raw_decision, Mapping) else None
                ),
                planning_issues=tuple(str(item) for item in raw_issues),
            )
        except ExpectedRecordingConditionPlanError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise ExpectedRecordingConditionPlanError(
                "Expected occurrence plan is malformed."
            ) from exc
        if raw_decision is not None and not isinstance(raw_decision, Mapping):
            raise ExpectedRecordingConditionPlanError(
                "decision_payload must be an object when present."
            )
        if value.get("source_sample_count") != result.source_sample_count:
            raise ExpectedRecordingConditionPlanError(
                "Expected occurrence source sample count is stale."
            )
        if str(value.get("fingerprint") or "") != result.fingerprint:
            raise ExpectedRecordingConditionPlanError(
                "Expected occurrence plan fingerprint mismatch."
            )
        return result


@dataclass(frozen=True, slots=True)
class ExpectedRecordingConditionCell:
    """One expected recording-by-condition cell before processing outcomes."""

    processing_id: str
    condition_label: str
    condition_code: int
    expected_workbook: str
    planning_state: str
    planned_cell_action: str
    planned_workbook_requirement: str
    occurrences: tuple[ExpectedOccurrencePlan, ...]
    no_output_decision: Mapping[str, Any] | None = None
    planning_issues: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _required_plan_text(self.processing_id, field_name="processing_id")
        _required_plan_text(self.condition_label, field_name="condition_label")
        expected_workbook = _required_plan_text(
            self.expected_workbook,
            field_name="expected_workbook",
        )
        if not Path(expected_workbook).is_absolute():
            raise ExpectedRecordingConditionPlanError(
                "Expected workbook path must be absolute."
            )
        if int(self.condition_code) <= 0:
            raise ExpectedRecordingConditionPlanError(
                "condition_code must be a positive integer."
            )
        if self.planning_state not in _EXPECTED_PLANNING_STATES:
            raise ExpectedRecordingConditionPlanError(
                f"Unsupported cell planning state {self.planning_state!r}."
            )
        if self.planned_cell_action not in _EXPECTED_CELL_ACTIONS:
            raise ExpectedRecordingConditionPlanError(
                f"Unsupported planned cell action {self.planned_cell_action!r}."
            )
        if self.planned_workbook_requirement not in _EXPECTED_WORKBOOK_REQUIREMENTS:
            raise ExpectedRecordingConditionPlanError(
                "Unsupported planned workbook requirement "
                f"{self.planned_workbook_requirement!r}."
            )
        if self.planning_state == EXPECTED_PLANNING_STATE_LEGACY_UNKNOWN:
            if self.planned_cell_action != EXPECTED_CELL_ACTION_LEGACY_UNKNOWN:
                raise ExpectedRecordingConditionPlanError(
                    "A legacy-unknown cell must use the legacy-unknown action."
                )
            if self.occurrences:
                raise ExpectedRecordingConditionPlanError(
                    "A legacy-unknown cell cannot claim current occurrence evidence."
                )
            if self.planned_workbook_requirement != EXPECTED_WORKBOOK_UNRESOLVED:
                raise ExpectedRecordingConditionPlanError(
                    "A legacy-unknown cell must leave workbook need unresolved."
                )
            if self.no_output_decision is not None:
                raise ExpectedRecordingConditionPlanError(
                    "A legacy-unknown cell cannot claim a current no-output decision."
                )
        elif self.planned_cell_action == EXPECTED_CELL_ACTION_PROCESS:
            if self.no_output_decision is not None:
                raise ExpectedRecordingConditionPlanError(
                    "A processed condition cannot contain a whole-cell no-output decision."
                )
        else:
            if self.planned_workbook_requirement != EXPECTED_WORKBOOK_NOT_REQUIRED:
                raise ExpectedRecordingConditionPlanError(
                    "An explicitly excluded condition cannot require a workbook."
                )
            _validate_no_output_decision(
                self.no_output_decision,
                expected_decision=(
                    "exclude_recording"
                    if self.planned_cell_action
                    == EXPECTED_CELL_ACTION_EXCLUDE_RECORDING
                    else "exclude_condition"
                ),
                field_name="no_output_decision",
            )
        occurrence_keys = [occurrence.occurrence_key for occurrence in self.occurrences]
        if len(occurrence_keys) != len(set(occurrence_keys)):
            raise ExpectedRecordingConditionPlanError(
                "Expected occurrence keys are duplicated within a condition cell."
            )
        if any(
            occurrence.condition_code != self.condition_code
            or occurrence.condition_label != self.condition_label
            for occurrence in self.occurrences
        ):
            raise ExpectedRecordingConditionPlanError(
                "Expected occurrence identity does not match its condition cell."
            )

    @property
    def cell_id(self) -> str:
        return f"{self.processing_id}:{self.condition_code}"

    @property
    def planned_occurrence_count(self) -> int:
        return len(self.occurrences)

    @property
    def planned_contributing_occurrence_count(self) -> int:
        if self.planned_cell_action != EXPECTED_CELL_ACTION_PROCESS:
            return 0
        return sum(
            occurrence.plans_workbook_contribution
            for occurrence in self.occurrences
        )

    @property
    def planned_excluded_occurrence_count(self) -> int:
        return self.planned_occurrence_count - self.planned_contributing_occurrence_count

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "cell_id": self.cell_id,
            "processing_id": self.processing_id,
            "condition_label": self.condition_label,
            "condition_code": int(self.condition_code),
            "expected_workbook": self.expected_workbook,
            "planning_state": self.planning_state,
            "planned_cell_action": self.planned_cell_action,
            "planned_workbook_requirement": self.planned_workbook_requirement,
            "planned_occurrence_count": self.planned_occurrence_count,
            "planned_contributing_occurrence_count": (
                self.planned_contributing_occurrence_count
            ),
            "planned_excluded_occurrence_count": (
                self.planned_excluded_occurrence_count
            ),
            "occurrences": [item.to_payload() for item in self.occurrences],
            "no_output_decision": (
                dict(self.no_output_decision)
                if self.no_output_decision is not None
                else None
            ),
            "planning_issues": list(self.planning_issues),
            "final_outcome": None,
        }

    @property
    def fingerprint(self) -> str:
        return _payload_fingerprint(self.canonical_payload())

    def to_payload(self) -> dict[str, Any]:
        payload = self.canonical_payload()
        payload["fingerprint"] = self.fingerprint
        return payload

    @classmethod
    def from_payload(
        cls,
        value: Mapping[str, Any],
    ) -> "ExpectedRecordingConditionCell":
        if not isinstance(value, Mapping):
            raise ExpectedRecordingConditionPlanError(
                "Expected recording-condition cell must be an object."
            )
        if value.get("final_outcome") is not None:
            raise ExpectedRecordingConditionPlanError(
                "Expected cells cannot claim a final processing outcome."
            )
        raw_occurrences = _payload_sequence(
            value.get("occurrences"),
            field_name="occurrences",
        )
        raw_no_output_decision = value.get("no_output_decision")
        raw_issues = _payload_sequence(
            value.get("planning_issues", ()),
            field_name="planning_issues",
        )
        try:
            result = cls(
                processing_id=str(value["processing_id"]),
                condition_label=str(value["condition_label"]),
                condition_code=int(value["condition_code"]),
                expected_workbook=str(value["expected_workbook"]),
                planning_state=str(value["planning_state"]),
                planned_cell_action=str(value["planned_cell_action"]),
                planned_workbook_requirement=str(
                    value["planned_workbook_requirement"]
                ),
                occurrences=tuple(
                    ExpectedOccurrencePlan.from_payload(item)
                    for item in raw_occurrences
                ),
                no_output_decision=(
                    dict(raw_no_output_decision)
                    if isinstance(raw_no_output_decision, Mapping)
                    else None
                ),
                planning_issues=tuple(str(item) for item in raw_issues),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ExpectedRecordingConditionPlanError(
                "Expected recording-condition cell is malformed."
            ) from exc
        if raw_no_output_decision is not None and not isinstance(
            raw_no_output_decision,
            Mapping,
        ):
            raise ExpectedRecordingConditionPlanError(
                "no_output_decision must be an object when present."
            )
        expected_derived = {
            "cell_id": result.cell_id,
            "planned_occurrence_count": result.planned_occurrence_count,
            "planned_contributing_occurrence_count": (
                result.planned_contributing_occurrence_count
            ),
            "planned_excluded_occurrence_count": (
                result.planned_excluded_occurrence_count
            ),
        }
        for key, expected in expected_derived.items():
            if value.get(key) != expected:
                raise ExpectedRecordingConditionPlanError(
                    f"Expected cell {key} is stale."
                )
        if str(value.get("fingerprint") or "") != result.fingerprint:
            raise ExpectedRecordingConditionPlanError(
                "Expected recording-condition cell fingerprint mismatch."
            )
        return result


@dataclass(frozen=True, slots=True)
class ExpectedRecordingPlan:
    """Canonical recording identity and every condition expected for it."""

    processing_id: str
    participant_id: str
    group_id: str | None
    recording_id: str | None
    session_id: str | None
    session_label: str | None
    visit_index: int | None
    source_id: str | None
    days_from_baseline: float | None
    raw_file_identity: Mapping[str, Any]
    marker_plan_identity: Mapping[str, Any] | None
    planning_state: str
    planned_recording_action: str
    no_output_decision: Mapping[str, Any] | None
    cells: tuple[ExpectedRecordingConditionCell, ...]

    def __post_init__(self) -> None:
        _required_plan_text(self.processing_id, field_name="processing_id")
        _required_plan_text(self.participant_id, field_name="participant_id")
        if self.planning_state not in _EXPECTED_PLANNING_STATES:
            raise ExpectedRecordingConditionPlanError(
                f"Unsupported recording planning state {self.planning_state!r}."
            )
        if self.planned_recording_action not in _EXPECTED_RECORDING_ACTIONS:
            raise ExpectedRecordingConditionPlanError(
                "Unsupported planned recording action "
                f"{self.planned_recording_action!r}."
            )
        if (
            self.planning_state == EXPECTED_PLANNING_STATE_PLANNED
            and self.planned_recording_action
            == EXPECTED_RECORDING_ACTION_LEGACY_UNKNOWN
        ):
            raise ExpectedRecordingConditionPlanError(
                "A current planned recording requires a current recording action."
            )
        if not isinstance(self.raw_file_identity, Mapping):
            raise ExpectedRecordingConditionPlanError(
                "raw_file_identity must be an object."
            )
        for key in ("raw_file", "raw_size", "raw_mtime_ns"):
            if key not in self.raw_file_identity:
                raise ExpectedRecordingConditionPlanError(
                    f"raw_file_identity is missing {key}."
                )
        raw_file_text = _required_plan_text(
            self.raw_file_identity.get("raw_file"),
            field_name="raw_file",
        )
        if not Path(raw_file_text).is_absolute():
            raise ExpectedRecordingConditionPlanError(
                "Expected recording raw_file must be absolute."
            )
        try:
            raw_size = int(self.raw_file_identity.get("raw_size"))
            raw_mtime_ns = int(self.raw_file_identity.get("raw_mtime_ns"))
        except (TypeError, ValueError, OverflowError) as exc:
            raise ExpectedRecordingConditionPlanError(
                "Expected recording raw-file size or timestamp is malformed."
            ) from exc
        if raw_size < 0 or raw_mtime_ns < 0:
            raise ExpectedRecordingConditionPlanError(
                "Expected recording raw-file size and timestamp cannot be negative."
            )
        repeated_identity = (
            self.recording_id,
            self.session_id,
            self.session_label,
            self.visit_index,
            self.source_id,
        )
        if any(value is not None for value in repeated_identity):
            if any(value is None for value in repeated_identity):
                raise ExpectedRecordingConditionPlanError(
                    "Repeated-session recording identity is incomplete."
                )
            if self.processing_id != self.recording_id:
                raise ExpectedRecordingConditionPlanError(
                    "Repeated-session processing_id must equal recording_id."
                )
            if int(self.visit_index) < 1:
                raise ExpectedRecordingConditionPlanError(
                    "Repeated-session visit_index must be positive."
                )
        elif self.processing_id != self.participant_id:
            raise ExpectedRecordingConditionPlanError(
                "Legacy processing_id must equal participant_id."
            )
        if (
            self.planning_state == EXPECTED_PLANNING_STATE_PLANNED
            and self.planned_recording_action == EXPECTED_RECORDING_ACTION_PROCESS
        ):
            if not isinstance(self.marker_plan_identity, Mapping):
                raise ExpectedRecordingConditionPlanError(
                    "A current planned recording requires marker-plan identity."
                )
            marker_identity = dict(self.marker_plan_identity)
            marker_identity_fingerprint = str(
                marker_identity.pop("fingerprint", "") or ""
            )
            for key in (
                "method_version",
                "sampling_rate_hz",
                "first_samp",
                "n_times",
                "event_count",
                "event_digest",
                "marker_evidence_fingerprint",
                "approved_event_plan_fingerprint",
            ):
                if key not in marker_identity:
                    raise ExpectedRecordingConditionPlanError(
                        f"marker_plan_identity is missing {key}."
                    )
            if marker_identity.get("method_version") != MARKER_INTEGRITY_METHOD_VERSION:
                raise ExpectedRecordingConditionPlanError(
                    "Recording marker-plan method is not current."
                )
            if marker_identity_fingerprint != _payload_fingerprint(marker_identity):
                raise ExpectedRecordingConditionPlanError(
                    "Recording marker-plan identity fingerprint mismatch."
                )
            if self.no_output_decision is not None:
                raise ExpectedRecordingConditionPlanError(
                    "A processed recording cannot contain a whole-recording "
                    "no-output decision."
                )
        elif (
            self.planning_state == EXPECTED_PLANNING_STATE_PLANNED
            and self.planned_recording_action == EXPECTED_RECORDING_ACTION_EXCLUDE
        ):
            if self.marker_plan_identity is not None:
                raise ExpectedRecordingConditionPlanError(
                    "A recording excluded before signal processing cannot claim "
                    "marker-plan identity."
                )
            _validate_no_output_decision(
                self.no_output_decision,
                expected_decision="exclude_recording",
                field_name="no_output_decision",
            )
        elif self.marker_plan_identity is not None or self.no_output_decision is not None:
            raise ExpectedRecordingConditionPlanError(
                "A legacy-unknown recording cannot claim current planning evidence."
            )
        if (
            self.planning_state == EXPECTED_PLANNING_STATE_LEGACY_UNKNOWN
            and self.planned_recording_action
            != EXPECTED_RECORDING_ACTION_LEGACY_UNKNOWN
        ):
            raise ExpectedRecordingConditionPlanError(
                "A legacy-unknown recording must use the legacy-unknown action."
            )
        if not self.cells:
            raise ExpectedRecordingConditionPlanError(
                "Every expected recording requires at least one condition cell."
            )
        if any(cell.processing_id != self.processing_id for cell in self.cells):
            raise ExpectedRecordingConditionPlanError(
                "Expected condition cell belongs to a different recording."
            )
        cell_ids = [cell.cell_id for cell in self.cells]
        if len(cell_ids) != len(set(cell_ids)):
            raise ExpectedRecordingConditionPlanError(
                "Expected condition cells are duplicated within a recording."
            )
        derived_state = (
            EXPECTED_PLANNING_STATE_LEGACY_UNKNOWN
            if any(
                cell.planning_state == EXPECTED_PLANNING_STATE_LEGACY_UNKNOWN
                for cell in self.cells
            )
            else EXPECTED_PLANNING_STATE_PLANNED
        )
        if self.planning_state != derived_state:
            raise ExpectedRecordingConditionPlanError(
                "Recording planning state does not match its condition cells."
            )
        expected_cell_action = (
            EXPECTED_CELL_ACTION_EXCLUDE_RECORDING
            if self.planned_recording_action == EXPECTED_RECORDING_ACTION_EXCLUDE
            else None
        )
        if expected_cell_action is not None and any(
            cell.planned_cell_action != expected_cell_action for cell in self.cells
        ):
            raise ExpectedRecordingConditionPlanError(
                "Every condition in an excluded recording must inherit that exclusion."
            )

    @property
    def raw_file_fingerprint(self) -> str:
        return _payload_fingerprint(dict(self.raw_file_identity))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "processing_id": self.processing_id,
            "participant_id": self.participant_id,
            "group_id": self.group_id,
            "recording_id": self.recording_id,
            "session_id": self.session_id,
            "session_label": self.session_label,
            "visit_index": self.visit_index,
            "source_id": self.source_id,
            "days_from_baseline": self.days_from_baseline,
            "raw_file_identity": dict(self.raw_file_identity),
            "raw_file_fingerprint": self.raw_file_fingerprint,
            "marker_plan_identity": (
                dict(self.marker_plan_identity)
                if self.marker_plan_identity is not None
                else None
            ),
            "planning_state": self.planning_state,
            "planned_recording_action": self.planned_recording_action,
            "no_output_decision": (
                dict(self.no_output_decision)
                if self.no_output_decision is not None
                else None
            ),
            "cells": [cell.to_payload() for cell in self.cells],
        }

    @property
    def fingerprint(self) -> str:
        return _payload_fingerprint(self.canonical_payload())

    def to_payload(self) -> dict[str, Any]:
        payload = self.canonical_payload()
        payload["fingerprint"] = self.fingerprint
        return payload

    @classmethod
    def from_payload(cls, value: Mapping[str, Any]) -> "ExpectedRecordingPlan":
        if not isinstance(value, Mapping):
            raise ExpectedRecordingConditionPlanError(
                "Expected recording plan must be an object."
            )
        raw_identity = value.get("raw_file_identity")
        raw_marker_identity = value.get("marker_plan_identity")
        raw_no_output_decision = value.get("no_output_decision")
        raw_cells = _payload_sequence(value.get("cells"), field_name="cells")
        if not isinstance(raw_identity, Mapping):
            raise ExpectedRecordingConditionPlanError(
                "raw_file_identity must be an object."
            )
        try:
            result = cls(
                processing_id=str(value["processing_id"]),
                participant_id=str(value["participant_id"]),
                group_id=(
                    str(value["group_id"])
                    if value.get("group_id") is not None
                    else None
                ),
                recording_id=(
                    str(value["recording_id"])
                    if value.get("recording_id") is not None
                    else None
                ),
                session_id=(
                    str(value["session_id"])
                    if value.get("session_id") is not None
                    else None
                ),
                session_label=(
                    str(value["session_label"])
                    if value.get("session_label") is not None
                    else None
                ),
                visit_index=(
                    int(value["visit_index"])
                    if value.get("visit_index") is not None
                    else None
                ),
                source_id=(
                    str(value["source_id"])
                    if value.get("source_id") is not None
                    else None
                ),
                days_from_baseline=(
                    float(value["days_from_baseline"])
                    if value.get("days_from_baseline") is not None
                    else None
                ),
                raw_file_identity=dict(raw_identity),
                marker_plan_identity=(
                    dict(raw_marker_identity)
                    if isinstance(raw_marker_identity, Mapping)
                    else None
                ),
                planning_state=str(value["planning_state"]),
                planned_recording_action=str(value["planned_recording_action"]),
                no_output_decision=(
                    dict(raw_no_output_decision)
                    if isinstance(raw_no_output_decision, Mapping)
                    else None
                ),
                cells=tuple(
                    ExpectedRecordingConditionCell.from_payload(item)
                    for item in raw_cells
                ),
            )
        except ExpectedRecordingConditionPlanError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise ExpectedRecordingConditionPlanError(
                "Expected recording plan is malformed."
            ) from exc
        if raw_marker_identity is not None and not isinstance(
            raw_marker_identity,
            Mapping,
        ):
            raise ExpectedRecordingConditionPlanError(
                "marker_plan_identity must be an object when present."
            )
        if raw_no_output_decision is not None and not isinstance(
            raw_no_output_decision,
            Mapping,
        ):
            raise ExpectedRecordingConditionPlanError(
                "no_output_decision must be an object when present."
            )
        if str(value.get("raw_file_fingerprint") or "") != result.raw_file_fingerprint:
            raise ExpectedRecordingConditionPlanError(
                "Expected recording raw-file fingerprint mismatch."
            )
        if str(value.get("fingerprint") or "") != result.fingerprint:
            raise ExpectedRecordingConditionPlanError(
                "Expected recording plan fingerprint mismatch."
            )
        return result


@dataclass(frozen=True, slots=True)
class ExpectedRecordingConditionPlan:
    """Versioned QC-20 expected matrix built before result accounting."""

    version: str
    run_id: str
    created_at: str
    processing_fingerprint_version: str
    processing_fingerprint: str
    geometry_identity: Mapping[str, Any]
    marker_integrity_method_version: str
    protocol_payload: Mapping[str, Any]
    protocol_fingerprint: str
    event_map: tuple[tuple[str, int], ...]
    recordings: tuple[ExpectedRecordingPlan, ...]

    def __post_init__(self) -> None:
        if self.version != EXPECTED_RECORDING_CONDITION_PLAN_VERSION:
            raise ExpectedRecordingConditionPlanError(
                f"Unsupported expected-plan version {self.version!r}."
            )
        _required_plan_text(self.run_id, field_name="run_id")
        _required_plan_text(self.created_at, field_name="created_at")
        _required_plan_text(
            self.processing_fingerprint_version,
            field_name="processing_fingerprint_version",
        )
        if (
            self.processing_fingerprint_version
            != _current_processing_fingerprint_version()
        ):
            raise ExpectedRecordingConditionPlanError(
                "Expected plan processing fingerprint version is stale."
            )
        _required_plan_text(
            self.processing_fingerprint,
            field_name="processing_fingerprint",
        )
        if not isinstance(self.geometry_identity, Mapping) or not self.geometry_identity:
            raise ExpectedRecordingConditionPlanError(
                "A non-empty processing geometry identity is required."
            )
        if self.marker_integrity_method_version != MARKER_INTEGRITY_METHOD_VERSION:
            raise ExpectedRecordingConditionPlanError(
                "Expected plan marker-integrity method is not current."
            )
        if not isinstance(self.protocol_payload, Mapping):
            raise ExpectedRecordingConditionPlanError(
                "protocol_payload must be an object."
            )
        try:
            protocol = normalize_frequency_protocol(self.protocol_payload)
        except FrequencyProtocolError as exc:
            raise ExpectedRecordingConditionPlanError(str(exc)) from exc
        if not protocol.is_ready or protocol.fingerprint != self.protocol_fingerprint:
            raise ExpectedRecordingConditionPlanError(
                "Expected plan protocol is incomplete or its fingerprint is stale."
            )
        _validate_expected_event_map(self.event_map, protocol)
        if not self.recordings:
            raise ExpectedRecordingConditionPlanError(
                "Expected plan requires at least one canonical recording."
            )
        processing_ids = [recording.processing_id.casefold() for recording in self.recordings]
        if len(processing_ids) != len(set(processing_ids)):
            raise ExpectedRecordingConditionPlanError(
                "Expected plan contains duplicate canonical recording identities."
            )
        raw_files = [
            str(recording.raw_file_identity["raw_file"]).casefold()
            for recording in self.recordings
        ]
        if len(raw_files) != len(set(raw_files)):
            raise ExpectedRecordingConditionPlanError(
                "Expected plan contains duplicate raw-file identities."
            )

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "run_id": self.run_id,
            "created_at": self.created_at,
            "processing_fingerprint_version": self.processing_fingerprint_version,
            "processing_fingerprint": self.processing_fingerprint,
            "geometry_identity": dict(self.geometry_identity),
            "marker_integrity_method_version": self.marker_integrity_method_version,
            "protocol_payload": dict(self.protocol_payload),
            "protocol_fingerprint": self.protocol_fingerprint,
            "event_map": [
                {"condition_label": label, "condition_code": code}
                for label, code in self.event_map
            ],
            "recordings": [recording.to_payload() for recording in self.recordings],
        }

    @property
    def fingerprint(self) -> str:
        return _payload_fingerprint(self.canonical_payload())

    def to_payload(self) -> dict[str, Any]:
        payload = self.canonical_payload()
        payload["fingerprint"] = self.fingerprint
        return payload

    @classmethod
    def from_payload(
        cls,
        value: Mapping[str, Any],
    ) -> "ExpectedRecordingConditionPlan":
        if not isinstance(value, Mapping):
            raise ExpectedRecordingConditionPlanError(
                "Expected recording-condition plan must be an object."
            )
        raw_event_map = _payload_sequence(
            value.get("event_map"),
            field_name="event_map",
        )
        event_rows: list[tuple[str, int]] = []
        for row in raw_event_map:
            if not isinstance(row, Mapping):
                raise ExpectedRecordingConditionPlanError(
                    "Expected-plan event-map row must be an object."
                )
            try:
                event_rows.append(
                    (str(row["condition_label"]), int(row["condition_code"]))
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ExpectedRecordingConditionPlanError(
                    "Expected-plan event-map row is malformed."
                ) from exc
        raw_recordings = _payload_sequence(
            value.get("recordings"),
            field_name="recordings",
        )
        raw_geometry = value.get("geometry_identity")
        raw_protocol = value.get("protocol_payload")
        if not isinstance(raw_geometry, Mapping) or not isinstance(raw_protocol, Mapping):
            raise ExpectedRecordingConditionPlanError(
                "Expected plan geometry and protocol must be objects."
            )
        try:
            result = cls(
                version=str(value["version"]),
                run_id=str(value["run_id"]),
                created_at=str(value["created_at"]),
                processing_fingerprint_version=str(
                    value["processing_fingerprint_version"]
                ),
                processing_fingerprint=str(value["processing_fingerprint"]),
                geometry_identity=dict(raw_geometry),
                marker_integrity_method_version=str(
                    value["marker_integrity_method_version"]
                ),
                protocol_payload=dict(raw_protocol),
                protocol_fingerprint=str(value["protocol_fingerprint"]),
                event_map=tuple(event_rows),
                recordings=tuple(
                    ExpectedRecordingPlan.from_payload(item)
                    for item in raw_recordings
                ),
            )
        except ExpectedRecordingConditionPlanError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise ExpectedRecordingConditionPlanError(
                "Expected recording-condition plan is malformed."
            ) from exc
        if str(value.get("fingerprint") or "") != result.fingerprint:
            raise ExpectedRecordingConditionPlanError(
                "Expected recording-condition plan fingerprint mismatch."
            )
        return result



def _validate_expected_event_map(
    event_rows: Sequence[tuple[str, int]],
    protocol: FrequencyProtocol,
) -> None:
    if not event_rows:
        raise ExpectedRecordingConditionPlanError(
            "The expected matrix requires at least one project condition."
        )
    labels: list[str] = []
    codes: list[int] = []
    for raw_label, raw_code in event_rows:
        label = _required_plan_text(raw_label, field_name="condition_label")
        try:
            code = int(raw_code)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ExpectedRecordingConditionPlanError(
                "condition_code must be a positive integer."
            ) from exc
        if isinstance(raw_code, bool) or code <= 0 or str(raw_code).strip() != str(code):
            raise ExpectedRecordingConditionPlanError(
                "condition_code must be a positive integer."
            )
        labels.append(label)
        codes.append(code)
    if len({label.casefold() for label in labels}) != len(labels):
        raise ExpectedRecordingConditionPlanError(
            "Project condition labels must be unique ignoring case."
        )
    if len(set(codes)) != len(codes):
        raise ExpectedRecordingConditionPlanError(
            "Each project condition requires a distinct onset code."
        )
    try:
        validate_protocol_condition_codes(protocol, codes)
    except FrequencyProtocolError as exc:
        raise ExpectedRecordingConditionPlanError(str(exc)) from exc


def _normalized_expected_event_map(
    event_map: Mapping[str, int],
    protocol: FrequencyProtocol,
) -> tuple[tuple[str, int], ...]:
    if not isinstance(event_map, Mapping):
        raise ExpectedRecordingConditionPlanError(
            "The project condition event map must be an object."
        )
    rows = tuple((str(label).strip(), int(code)) for label, code in event_map.items())
    _validate_expected_event_map(rows, protocol)
    return rows


def _event_plan_for_processing_state(
    state: ProcessingInputState,
    event_plans: Mapping[Any, Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    """Resolve only a canonical processing ID or exact raw path.

    A basename fallback would allow recordings in different source folders to
    overwrite one another, so it is intentionally unsupported here.
    """

    processing_key = state.processing_id.casefold()
    raw_path = state.info.path.resolve(strict=False)
    matches: list[Mapping[str, Any]] = []
    for raw_key, raw_value in event_plans.items():
        key_text = str(raw_key).strip()
        is_match = key_text.casefold() == processing_key
        if not is_match:
            try:
                is_match = Path(key_text).expanduser().resolve(strict=False) == raw_path
            except (OSError, RuntimeError, TypeError, ValueError):
                is_match = False
        if not is_match:
            continue
        if not isinstance(raw_value, Mapping):
            raise ExpectedRecordingConditionPlanError(
                f"Approved marker plan for {state.processing_id} must be an object."
            )
        matches.append(raw_value)
    if not matches:
        return None
    first_identity = _canonical_json(dict(matches[0]))
    if any(_canonical_json(dict(item)) != first_identity for item in matches[1:]):
        raise ExpectedRecordingConditionPlanError(
            f"Conflicting approved marker plans were supplied for {state.processing_id}."
        )
    return matches[0]


def _approved_occurrences_from_event_plan(
    event_plan: Mapping[str, Any],
    *,
    event_rows: Sequence[tuple[str, int]],
    protocol: FrequencyProtocol,
) -> tuple[dict[int, tuple[ExpectedOccurrencePlan, ...]], dict[str, Any]]:
    try:
        # Validate the stored event-plan fingerprint and the independently
        # fingerprinted source-coordinate plan before copying any marker or
        # span evidence into QC-20.  The runner performs the later raw-file
        # comparison; this boundary guarantees that the ledger freezes the
        # exact plan the user reviewed rather than a modified copy.
        read_source_analysis_span_plan(event_plan)
    except AnalysisSpanPlanError as exc:
        raise ExpectedRecordingConditionPlanError(
            f"Approved analyzed-interval plan is missing or stale: {exc}"
        ) from exc

    marker_plan = event_plan.get("marker_integrity_plan")
    if not isinstance(marker_plan, Mapping):
        raise ExpectedRecordingConditionPlanError(
            "Approved event plan is missing marker-integrity evidence."
        )
    if marker_plan.get("method_version") != MARKER_INTEGRITY_METHOD_VERSION:
        raise ExpectedRecordingConditionPlanError(
            "Approved event plan marker policy is not current."
        )
    if str(marker_plan.get("protocol_fingerprint") or "") != protocol.fingerprint:
        raise ExpectedRecordingConditionPlanError(
            "Approved event plan was built from a different project protocol."
        )
    sampling_rate_identity = _fraction_identity(
        marker_plan.get("sampling_rate_hz"),
        field_name="marker sampling_rate_hz",
    )
    sampling_rate = Fraction(sampling_rate_identity)
    try:
        expected_samples = protocol.expected_analyzed_samples(sampling_rate)
    except FrequencyProtocolError as exc:
        raise ExpectedRecordingConditionPlanError(str(exc)) from exc

    try:
        event_count = int(marker_plan.get("event_count"))
        n_times = int(event_plan.get("n_times"))
        first_samp = int(event_plan.get("first_samp"))
    except (TypeError, ValueError, OverflowError) as exc:
        raise ExpectedRecordingConditionPlanError(
            "Approved marker event count, recording length, or sample origin is malformed."
        ) from exc
    if event_count < 0 or n_times <= 0:
        raise ExpectedRecordingConditionPlanError(
            "Approved marker event count or recording length is invalid."
        )
    event_digest = _required_plan_text(
        marker_plan.get("event_digest"),
        field_name="marker event_digest",
    )
    if int(event_plan.get("event_count", -1)) != event_count:
        raise ExpectedRecordingConditionPlanError(
            "Approved event plan and marker evidence disagree about event count."
        )
    if str(event_plan.get("event_digest") or "") != event_digest:
        raise ExpectedRecordingConditionPlanError(
            "Approved event plan and marker evidence disagree about event identity."
        )
    if _fraction_identity(
        event_plan.get("sfreq"),
        field_name="approved event-plan sfreq",
    ) != sampling_rate_identity:
        raise ExpectedRecordingConditionPlanError(
            "Approved event plan and marker evidence disagree about sampling rate."
        )
    try:
        marker_first_samp = int(marker_plan.get("first_samp"))
    except (TypeError, ValueError, OverflowError) as exc:
        raise ExpectedRecordingConditionPlanError(
            "Approved marker sample origin is malformed."
        ) from exc
    if marker_first_samp != first_samp:
        raise ExpectedRecordingConditionPlanError(
            "Approved event plan and marker evidence disagree about sample origin."
        )
    recording_stop = first_samp + n_times

    unresolved = _payload_sequence(
        event_plan.get("unresolved_occurrences", ()),
        field_name="unresolved_occurrences",
    )
    if unresolved:
        raise ExpectedRecordingConditionPlanError(
            "Every marker occurrence must be reviewed before building the expected matrix."
        )
    raw_occurrences = _payload_sequence(
        marker_plan.get("occurrences"),
        field_name="marker occurrences",
    )
    raw_approved = _payload_sequence(
        event_plan.get("approved_occurrences"),
        field_name="approved occurrences",
    )
    if len(raw_occurrences) != len(raw_approved):
        raise ExpectedRecordingConditionPlanError(
            "Every marker occurrence requires one approved or excluded disposition."
        )

    labels_by_code = {code: label for label, code in event_rows}
    occurrence_evidence: dict[str, Mapping[str, Any]] = {}
    for raw_occurrence in raw_occurrences:
        if not isinstance(raw_occurrence, Mapping):
            raise ExpectedRecordingConditionPlanError(
                "Marker occurrence evidence must be an object."
            )
        try:
            condition_code = int(raw_occurrence["condition_code"])
            repetition_index = int(raw_occurrence["repetition_index"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ExpectedRecordingConditionPlanError(
                "Marker occurrence identity is malformed."
            ) from exc
        key = f"{condition_code}:{repetition_index}"
        if condition_code not in labels_by_code:
            raise ExpectedRecordingConditionPlanError(
                "Marker occurrence uses a condition code outside the project event map."
            )
        if repetition_index < 0 or key in occurrence_evidence:
            raise ExpectedRecordingConditionPlanError(
                "Marker occurrence repetition identity is invalid or duplicated."
            )
        if str(raw_occurrence.get("condition_label") or "") != labels_by_code[condition_code]:
            raise ExpectedRecordingConditionPlanError(
                "Marker occurrence condition label is stale."
            )
        if int(raw_occurrence.get("oddball_marker_code", -1)) != int(
            protocol.oddball_marker_code
        ):
            raise ExpectedRecordingConditionPlanError(
                "Marker occurrence uses a stale project oddball code."
            )
        if int(raw_occurrence.get("expected_analyzed_cycles", -1)) != int(
            protocol.expected_analyzed_oddball_cycles
        ):
            raise ExpectedRecordingConditionPlanError(
                "Marker occurrence uses a stale analyzed-cycle count."
            )
        if int(raw_occurrence.get("expected_analyzed_samples", -1)) != expected_samples:
            raise ExpectedRecordingConditionPlanError(
                "Marker occurrence uses a stale exact sample count."
            )
        _required_plan_text(
            raw_occurrence.get("fingerprint"),
            field_name="marker occurrence fingerprint",
        )
        occurrence_evidence[key] = raw_occurrence

    approved_by_key: dict[str, ApprovedOccurrenceSpan] = {}
    for raw_span in raw_approved:
        try:
            approved = ApprovedOccurrenceSpan.from_payload(raw_span)
        except MarkerIntegrityError as exc:
            raise ExpectedRecordingConditionPlanError(str(exc)) from exc
        if approved.occurrence_key in approved_by_key:
            raise ExpectedRecordingConditionPlanError(
                "Approved marker occurrence identities are duplicated."
            )
        evidence = occurrence_evidence.get(approved.occurrence_key)
        if evidence is None:
            raise ExpectedRecordingConditionPlanError(
                "Approved occurrence is absent from marker evidence."
            )
        if approved.disposition not in _PLANNED_MARKER_DISPOSITIONS:
            raise ExpectedRecordingConditionPlanError(
                "Approved occurrence disposition is unsupported."
            )
        if str(evidence.get("fingerprint") or "") != approved.marker_plan_fingerprint:
            raise ExpectedRecordingConditionPlanError(
                "Approved occurrence marker evidence is stale."
            )
        if approved.is_excluded:
            if approved.start_sample is not None or approved.stop_sample is not None:
                raise ExpectedRecordingConditionPlanError(
                    "Excluded marker occurrence cannot contain an analysis span."
                )
        elif (
            approved.start_sample is None
            or approved.stop_sample is None
            or approved.stop_sample - approved.start_sample != expected_samples
        ):
            raise ExpectedRecordingConditionPlanError(
                "Planned occurrence span no longer matches the project cycle count."
            )
        if not approved.is_excluded:
            onset_sample = int(evidence.get("onset_sample", -1))
            block_stop_sample = int(evidence.get("block_stop_sample", -1))
            if (
                approved.start_sample < onset_sample
                or approved.stop_sample > block_stop_sample
                or approved.start_sample < first_samp
                or approved.stop_sample > recording_stop
            ):
                raise ExpectedRecordingConditionPlanError(
                    "Planned occurrence span is outside its source condition block."
                )
        approved_by_key[approved.occurrence_key] = approved

    if set(occurrence_evidence) != set(approved_by_key):
        raise ExpectedRecordingConditionPlanError(
            "Marker evidence and approved occurrence identities do not match."
        )

    raw_spans = _payload_sequence(event_plan.get("spans"), field_name="spans")
    planned_span_by_key: dict[str, Mapping[str, Any]] = {}
    for raw_span in raw_spans:
        if not isinstance(raw_span, Mapping):
            raise ExpectedRecordingConditionPlanError(
                "Approved analysis span must be an object."
            )
        try:
            key = f"{int(raw_span['condition_id'])}:{int(raw_span['repetition_index'])}"
        except (KeyError, TypeError, ValueError) as exc:
            raise ExpectedRecordingConditionPlanError(
                "Approved analysis span identity is malformed."
            ) from exc
        if key in planned_span_by_key:
            raise ExpectedRecordingConditionPlanError(
                "Approved analysis span identities are duplicated."
            )
        planned_span_by_key[key] = raw_span
    expected_span_keys = {
        key for key, approved in approved_by_key.items() if not approved.is_excluded
    }
    if set(planned_span_by_key) != expected_span_keys:
        raise ExpectedRecordingConditionPlanError(
            "Approved analysis spans do not match planned contributing occurrences."
        )

    occurrences_by_code: dict[int, list[ExpectedOccurrencePlan]] = {
        code: [] for _label, code in event_rows
    }
    for key, evidence in occurrence_evidence.items():
        approved = approved_by_key[key]
        condition_code = approved.condition_code
        if not approved.is_excluded:
            span = planned_span_by_key[key]
            if (
                int(span.get("time_start_sample", -1)) != approved.start_sample
                or int(span.get("time_stop_sample", -1)) != approved.stop_sample
                or str(span.get("approved_span_fingerprint") or "")
                != approved.fingerprint
                or str(span.get("marker_plan_fingerprint") or "")
                != approved.marker_plan_fingerprint
            ):
                raise ExpectedRecordingConditionPlanError(
                    "Approved analysis span is stale relative to marker review."
                )
        review_reasons_raw = _payload_sequence(
            evidence.get("review_reasons", ()),
            field_name="marker review_reasons",
        )
        occurrences_by_code[condition_code].append(
            ExpectedOccurrencePlan(
                condition_label=labels_by_code[condition_code],
                condition_code=condition_code,
                repetition_index=approved.repetition_index,
                planning_state=EXPECTED_PLANNING_STATE_PLANNED,
                planned_disposition=approved.disposition,
                source_sampling_rate_hz=sampling_rate_identity,
                source_start_sample=approved.start_sample,
                source_stop_sample=approved.stop_sample,
                marker_plan_fingerprint=approved.marker_plan_fingerprint,
                approved_span_fingerprint=approved.fingerprint,
                decision_payload=(
                    dict(approved.decision_payload)
                    if approved.decision_payload is not None
                    else None
                ),
                planning_issues=tuple(str(item) for item in review_reasons_raw),
            )
        )

    frozen_by_code: dict[int, tuple[ExpectedOccurrencePlan, ...]] = {}
    for code, occurrences in occurrences_by_code.items():
        ordered = tuple(sorted(occurrences, key=lambda item: item.repetition_index))
        if [item.repetition_index for item in ordered] != list(range(len(ordered))):
            raise ExpectedRecordingConditionPlanError(
                f"Condition code {code} has a non-contiguous occurrence sequence."
            )
        frozen_by_code[code] = ordered

    marker_identity_payload = {
        "method_version": MARKER_INTEGRITY_METHOD_VERSION,
        "sampling_rate_hz": sampling_rate_identity,
        "first_samp": first_samp,
        "n_times": n_times,
        "event_count": event_count,
        "event_digest": event_digest,
        "marker_evidence_fingerprint": _payload_fingerprint(dict(marker_plan)),
        "approved_event_plan_fingerprint": _payload_fingerprint(dict(event_plan)),
    }
    marker_identity_payload["fingerprint"] = _payload_fingerprint(
        marker_identity_payload
    )
    return frozen_by_code, marker_identity_payload


def _casefolded_condition_map(
    value: Mapping[str, Sequence[str]],
) -> dict[str, frozenset[str]]:
    return {
        str(owner).strip().casefold(): frozenset(
            str(condition).strip().casefold() for condition in conditions
        )
        for owner, conditions in value.items()
        if str(owner).strip()
    }


def _normalized_planning_exclusions(
    settings: Mapping[str, Any] | None,
) -> dict[str, Any]:
    source = settings or {}
    try:
        participant_conditions = normalize_manual_excluded_participant_conditions(
            source.get("manual_excluded_participant_conditions")
        )
        recording_conditions = normalize_manual_excluded_recording_conditions(
            source.get("manual_excluded_recording_conditions")
        )
    except ValueError as exc:
        raise ExpectedRecordingConditionPlanError(
            f"Project condition-exclusion settings are malformed: {exc}"
        ) from exc
    recording_not_started: set[Path] = set()
    raw_recording_not_started = source.get(
        "_fpvs_preflight_recording_not_started_files",
        (),
    )
    if isinstance(raw_recording_not_started, str):
        raw_recording_not_started = (raw_recording_not_started,)
    if isinstance(raw_recording_not_started, Sequence):
        for raw_path in raw_recording_not_started:
            try:
                recording_not_started.add(
                    Path(str(raw_path)).expanduser().resolve(strict=False)
                )
            except (OSError, RuntimeError, TypeError, ValueError):
                continue
    return {
        "participants": frozenset(
            value.casefold()
            for value in normalize_manual_excluded_participants(
                source.get("manual_excluded_participants")
            )
        ),
        "recordings": frozenset(
            value.casefold()
            for value in normalize_manual_excluded_recordings(
                source.get("manual_excluded_recordings")
            )
        ),
        "participant_conditions": _casefolded_condition_map(
            participant_conditions
        ),
        "recording_conditions": _casefolded_condition_map(recording_conditions),
        "recording_not_started": frozenset(recording_not_started),
    }


def _planning_evidence(reason_codes: Sequence[str], **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "reason_codes": sorted({str(code) for code in reason_codes}),
        **extra,
    }
    payload["fingerprint"] = _payload_fingerprint(payload)
    return payload


def _recording_no_output_decision(
    state: ProcessingInputState,
    *,
    exclusions: Mapping[str, Any],
    recorded_at_utc: str,
) -> dict[str, Any] | None:
    reason_codes: list[str] = []
    participant_key = state.participant_id.casefold()
    recording_key = state.processing_id.casefold()
    raw_path = state.info.path.resolve(strict=False)
    if participant_key in exclusions["participants"]:
        reason_codes.append("manual_participant_exclusion")
    if recording_key in exclusions["recordings"]:
        reason_codes.append("manual_recording_exclusion")
    if raw_path in exclusions["recording_not_started"]:
        reason_codes.append("recording_not_started")
    if state.status == "excluded":
        reason_codes.append("current_processing_plan_exclusion")
    if not reason_codes:
        return None

    reason_text = {
        "manual_participant_exclusion": (
            "The participant is explicitly excluded in project preprocessing settings."
        ),
        "manual_recording_exclusion": (
            "The recording is explicitly excluded in project preprocessing settings."
        ),
        "recording_not_started": (
            "The reviewed BDF header indicates that recording was not started."
        ),
        "current_processing_plan_exclusion": (
            state.reason or "The current processing plan explicitly excludes this recording."
        ),
    }
    reasons = [reason_text[code] for code in reason_codes]
    source = (
        "current_project_preprocessing_settings"
        if any(code != "current_processing_plan_exclusion" for code in reason_codes)
        else "current_processing_ledger"
    )
    return _decision_payload(
        decision="exclude_recording",
        reason=" ".join(dict.fromkeys(reasons)),
        source=source,
        recorded_at_utc=recorded_at_utc,
        scope={
            "processing_id": state.processing_id,
            "participant_id": state.participant_id,
            "recording_id": state.info.recording_id,
            "raw_file": str(raw_path),
        },
        evidence=_planning_evidence(
            reason_codes,
            processing_state_status=state.status,
            processing_state_reason=state.reason,
        ),
    )


def _condition_no_output_decision(
    state: ProcessingInputState,
    condition_label: str,
    condition_code: int,
    *,
    exclusions: Mapping[str, Any],
    recorded_at_utc: str,
) -> dict[str, Any] | None:
    condition_key = condition_label.casefold()
    reason_codes: list[str] = []
    if condition_key in exclusions["participant_conditions"].get(
        state.participant_id.casefold(),
        (),
    ):
        reason_codes.append("manual_participant_condition_exclusion")
    if condition_key in exclusions["recording_conditions"].get(
        state.processing_id.casefold(),
        (),
    ):
        reason_codes.append("manual_recording_condition_exclusion")
    if not reason_codes:
        return None
    return _decision_payload(
        decision="exclude_condition",
        reason=(
            "This recording-condition is explicitly excluded in project "
            "preprocessing settings."
        ),
        source="current_project_preprocessing_settings",
        recorded_at_utc=recorded_at_utc,
        scope={
            "processing_id": state.processing_id,
            "participant_id": state.participant_id,
            "recording_id": state.info.recording_id,
            "condition_label": condition_label,
            "condition_code": int(condition_code),
        },
        evidence=_planning_evidence(reason_codes),
    )


def build_expected_recording_condition_plan(
    *,
    processing_plan: ProcessingPlan,
    event_map: Mapping[str, int],
    frequency_protocol: FrequencyProtocol | Mapping[str, Any],
    approved_event_plans: Mapping[Any, Mapping[str, Any]],
    planning_settings: Mapping[str, Any] | None = None,
    run_id: str | None = None,
    created_at: str | None = None,
) -> ExpectedRecordingConditionPlan:
    """Freeze the QC-20 expected matrix before numerical processing starts.

    ``ProcessingInputState.info`` is the canonical identity emitted by raw-file
    discovery. Current run files require a fully reviewed QC-19 event plan.
    Skipped entries without current occurrence evidence remain
    ``legacy_unknown`` even when an older ledger called them complete or
    partial; file presence never upgrades them to a final QC-20 outcome.
    """

    from Main_App.processing.processing_ledger import PROCESSING_FINGERPRINT_VERSION

    try:
        protocol = normalize_frequency_protocol(frequency_protocol)
    except FrequencyProtocolError as exc:
        raise ExpectedRecordingConditionPlanError(str(exc)) from exc
    if not protocol.is_ready:
        raise ExpectedRecordingConditionPlanError(
            "A ready project frequency protocol is required for the expected matrix."
        )
    event_rows = _normalized_expected_event_map(event_map, protocol)
    if tuple(processing_plan.condition_labels) != tuple(
        label for label, _code in event_rows
    ):
        raise ExpectedRecordingConditionPlanError(
            "Processing-plan conditions are stale relative to the project event map."
        )
    if not isinstance(approved_event_plans, Mapping):
        raise ExpectedRecordingConditionPlanError(
            "approved_event_plans must be an object."
        )
    _required_plan_text(
        processing_plan.fingerprint,
        field_name="processing_fingerprint",
    )
    if not processing_plan.geometry_identity:
        raise ExpectedRecordingConditionPlanError(
            "Processing plan is missing its electrode geometry identity."
        )

    plan_created_at = (
        _required_plan_text(created_at, field_name="created_at")
        if created_at is not None
        else _now_iso()
    )
    exclusions = _normalized_planning_exclusions(planning_settings)
    run_paths = {Path(path).resolve(strict=False) for path in processing_plan.run_files}
    seen_processing_ids: set[str] = set()
    seen_raw_paths: set[Path] = set()
    recording_plans: list[ExpectedRecordingPlan] = []
    for state in processing_plan.states:
        processing_key = _required_plan_text(
            state.processing_id,
            field_name="processing_id",
        ).casefold()
        raw_path = state.info.path.resolve(strict=False)
        if processing_key in seen_processing_ids:
            raise ExpectedRecordingConditionPlanError(
                "Processing plan contains duplicate canonical recording IDs."
            )
        if raw_path in seen_raw_paths:
            raise ExpectedRecordingConditionPlanError(
                "Processing plan contains the same raw file more than once."
            )
        seen_processing_ids.add(processing_key)
        seen_raw_paths.add(raw_path)
        event_plan = _event_plan_for_processing_state(
            state,
            approved_event_plans,
        )
        recording_no_output = _recording_no_output_decision(
            state,
            exclusions=exclusions,
            recorded_at_utc=plan_created_at,
        )
        if (
            event_plan is None
            and raw_path in run_paths
            and recording_no_output is None
        ):
            raise ExpectedRecordingConditionPlanError(
                f"Current run file {state.info.path.name} has no reviewed marker plan."
            )

        if recording_no_output is not None:
            planning_state = EXPECTED_PLANNING_STATE_PLANNED
            planned_recording_action = EXPECTED_RECORDING_ACTION_EXCLUDE
            marker_identity = None
            occurrences_by_code = {code: () for _label, code in event_rows}
        elif event_plan is None:
            planning_state = EXPECTED_PLANNING_STATE_LEGACY_UNKNOWN
            planned_recording_action = EXPECTED_RECORDING_ACTION_LEGACY_UNKNOWN
            marker_identity = None
            occurrences_by_code: dict[int, tuple[ExpectedOccurrencePlan, ...]] = {
                code: () for _label, code in event_rows
            }
        else:
            planning_state = EXPECTED_PLANNING_STATE_PLANNED
            planned_recording_action = EXPECTED_RECORDING_ACTION_PROCESS
            occurrences_by_code, marker_identity = (
                _approved_occurrences_from_event_plan(
                    event_plan,
                    event_rows=event_rows,
                    protocol=protocol,
                )
            )

        if len(state.expected_outputs) != len(event_rows):
            raise ExpectedRecordingConditionPlanError(
                f"Expected workbook routes are incomplete for {state.processing_id}."
            )
        cells: list[ExpectedRecordingConditionCell] = []
        for (condition_label, condition_code), output_path in zip(
            event_rows,
            state.expected_outputs,
            strict=True,
        ):
            occurrences = occurrences_by_code[condition_code]
            condition_no_output = (
                None
                if recording_no_output is not None
                else _condition_no_output_decision(
                    state,
                    condition_label,
                    condition_code,
                    exclusions=exclusions,
                    recorded_at_utc=plan_created_at,
                )
            )
            if recording_no_output is not None:
                planned_cell_action = EXPECTED_CELL_ACTION_EXCLUDE_RECORDING
                workbook_requirement = EXPECTED_WORKBOOK_NOT_REQUIRED
                cell_no_output = recording_no_output
                issues = ()
            elif planning_state == EXPECTED_PLANNING_STATE_LEGACY_UNKNOWN:
                planned_cell_action = EXPECTED_CELL_ACTION_LEGACY_UNKNOWN
                workbook_requirement = EXPECTED_WORKBOOK_UNRESOLVED
                cell_no_output = None
                issues = ("current_occurrence_plan_unavailable",)
            elif condition_no_output is not None:
                planned_cell_action = EXPECTED_CELL_ACTION_EXCLUDE_CONDITION
                workbook_requirement = EXPECTED_WORKBOOK_NOT_REQUIRED
                cell_no_output = condition_no_output
                issues = ()
            elif not occurrences:
                planned_cell_action = EXPECTED_CELL_ACTION_PROCESS
                workbook_requirement = EXPECTED_WORKBOOK_UNRESOLVED
                cell_no_output = None
                issues = ("no_marker_occurrence_for_expected_condition",)
            elif any(item.plans_workbook_contribution for item in occurrences):
                planned_cell_action = EXPECTED_CELL_ACTION_PROCESS
                workbook_requirement = EXPECTED_WORKBOOK_REQUIRED
                cell_no_output = None
                issues = ()
            else:
                planned_cell_action = EXPECTED_CELL_ACTION_PROCESS
                workbook_requirement = EXPECTED_WORKBOOK_NOT_REQUIRED
                cell_no_output = None
                issues = ()
            cells.append(
                ExpectedRecordingConditionCell(
                    processing_id=state.processing_id,
                    condition_label=condition_label,
                    condition_code=condition_code,
                    expected_workbook=str(Path(output_path).resolve(strict=False)),
                    planning_state=planning_state,
                    planned_cell_action=planned_cell_action,
                    planned_workbook_requirement=workbook_requirement,
                    occurrences=occurrences,
                    no_output_decision=cell_no_output,
                    planning_issues=issues,
                )
            )

        identity = _recording_identity_payload(state.info)
        recording_plans.append(
            ExpectedRecordingPlan(
                processing_id=state.processing_id,
                participant_id=str(identity["participant_id"]),
                group_id=state.info.group,
                recording_id=identity.get("recording_id"),
                session_id=identity.get("session_id"),
                session_label=identity.get("session_label"),
                visit_index=identity.get("visit_index"),
                source_id=identity.get("source_id"),
                days_from_baseline=identity.get("days_from_baseline"),
                raw_file_identity=_raw_file_metadata(state.info.path),
                marker_plan_identity=marker_identity,
                planning_state=planning_state,
                planned_recording_action=planned_recording_action,
                no_output_decision=recording_no_output,
                cells=tuple(cells),
            )
        )

    return ExpectedRecordingConditionPlan(
        version=EXPECTED_RECORDING_CONDITION_PLAN_VERSION,
        run_id=(
            _required_plan_text(run_id, field_name="run_id")
            if run_id is not None
            else uuid4().hex
        ),
        created_at=plan_created_at,
        processing_fingerprint_version=PROCESSING_FINGERPRINT_VERSION,
        processing_fingerprint=processing_plan.fingerprint,
        geometry_identity=dict(processing_plan.geometry_identity),
        marker_integrity_method_version=MARKER_INTEGRITY_METHOD_VERSION,
        protocol_payload=protocol.to_manifest(),
        protocol_fingerprint=protocol.fingerprint,
        event_map=event_rows,
        recordings=tuple(recording_plans),
    )


def save_expected_recording_condition_plan(
    project_root: Path,
    expected_plan: ExpectedRecordingConditionPlan,
) -> None:
    """Atomically store the current expected matrix beside legacy entries."""

    if not isinstance(expected_plan, ExpectedRecordingConditionPlan):
        raise ExpectedRecordingConditionPlanError(
            "expected_plan must be an ExpectedRecordingConditionPlan."
        )
    ledger = _load_ledger(Path(project_root))
    ledger[EXPECTED_RECORDING_CONDITION_PLAN_LEDGER_KEY] = expected_plan.to_payload()
    _save_ledger(Path(project_root), ledger)


def load_expected_recording_condition_plan(
    project_root: Path,
) -> ExpectedRecordingConditionPlan | None:
    """Load a current versioned matrix without upgrading legacy completion rows.

    Returning ``None`` for a legacy ledger is intentional. In particular, the
    historical ``condition_completeness='partial'`` flag is not evidence for
    QC-20's ``partially_retained`` outcome because it has no occurrence plan or
    current-run receipt.
    """

    ledger = _load_ledger(Path(project_root))
    payload = ledger.get(EXPECTED_RECORDING_CONDITION_PLAN_LEDGER_KEY)
    if payload is None:
        return None
    if not isinstance(payload, Mapping):
        raise ExpectedRecordingConditionPlanError(
            "Stored expected recording-condition plan must be an object."
        )
    return ExpectedRecordingConditionPlan.from_payload(payload)



__all__ = [
    "EXPECTED_CELL_ACTION_EXCLUDE_CONDITION",
    "EXPECTED_CELL_ACTION_EXCLUDE_RECORDING",
    "EXPECTED_CELL_ACTION_LEGACY_UNKNOWN",
    "EXPECTED_CELL_ACTION_PROCESS",
    "EXPECTED_PLANNING_STATE_LEGACY_UNKNOWN",
    "EXPECTED_PLANNING_STATE_PLANNED",
    "EXPECTED_RECORDING_ACTION_EXCLUDE",
    "EXPECTED_RECORDING_ACTION_LEGACY_UNKNOWN",
    "EXPECTED_RECORDING_ACTION_PROCESS",
    "EXPECTED_RECORDING_CONDITION_PLAN_LEDGER_KEY",
    "EXPECTED_RECORDING_CONDITION_PLAN_VERSION",
    "EXPECTED_WORKBOOK_NOT_REQUIRED",
    "EXPECTED_WORKBOOK_REQUIRED",
    "EXPECTED_WORKBOOK_UNRESOLVED",
    "ExpectedOccurrencePlan",
    "ExpectedRecordingConditionCell",
    "ExpectedRecordingConditionPlan",
    "ExpectedRecordingConditionPlanError",
    "ExpectedRecordingPlan",
    "build_expected_recording_condition_plan",
    "load_expected_recording_condition_plan",
    "save_expected_recording_condition_plan",
]
