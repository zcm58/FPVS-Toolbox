"""Project-protocol marker evidence and occurrence-level review decisions."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from fractions import Fraction
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

import numpy as np

from Main_App.projects.frequency_protocol import (
    FrequencyProtocol,
    FrequencyProtocolError,
    validate_protocol_condition_codes,
)

MARKER_INTEGRITY_METHOD_VERSION = "marker_integrity_v3_review_receipt"
MARKER_REVIEW_DECISION_SCHEMA_VERSION = "marker_review_decision_v2_audit_receipt"
MARKER_REVIEWER_STATE_EXPLICIT_GUI = "explicit_gui_review"
MARKER_REVIEWER_IDENTITY_STATUS_NOT_COLLECTED = "not_collected"
MARKER_REVIEWER_IDENTITY_STATUS_PROVIDED = "provided"
EARLY_MARKER_BOUNDARY_CYCLES = Fraction(1, 2)
MISSING_MARKER_BOUNDARY_CYCLES = Fraction(3, 2)

MARKER_STATUS_READY = "ready"
MARKER_STATUS_REVIEW_REQUIRED = "review_required"

MARKER_DECISION_RETAIN_FULL = "retain_full_occurrence"
MARKER_DECISION_USE_CONTIGUOUS = "use_verified_contiguous_span"
MARKER_DECISION_EXCLUDE = "exclude_occurrence"


class MarkerIntegrityError(ValueError):
    """Raised when marker evidence or a review decision is invalid."""


def _positive_fraction(value: Any, *, field_name: str) -> Fraction:
    if isinstance(value, bool):
        raise MarkerIntegrityError(f"{field_name} must be a finite positive number.")
    if isinstance(value, float) and not math.isfinite(value):
        raise MarkerIntegrityError(f"{field_name} must be a finite positive number.")
    try:
        result = value if isinstance(value, Fraction) else Fraction(str(value).strip())
    except (AttributeError, ValueError, ZeroDivisionError) as exc:
        raise MarkerIntegrityError(
            f"{field_name} must be a finite positive number."
        ) from exc
    if result <= 0:
        raise MarkerIntegrityError(f"{field_name} must be a finite positive number.")
    return result


def _fraction_text(value: Fraction) -> str:
    return str(value.numerator) if value.denominator == 1 else str(value)


def _normalized_events(events: np.ndarray) -> np.ndarray:
    array = np.asarray(events)
    if array.size == 0:
        return np.empty((0, 3), dtype=np.int64)
    if array.ndim != 2 or array.shape[1] < 3:
        raise MarkerIntegrityError("events must have shape (n_events, 3).")
    normalized = np.asarray(array[:, :3], dtype=np.int64)
    order = np.argsort(normalized[:, 0], kind="stable")
    return np.ascontiguousarray(normalized[order])


def _event_digest(events: np.ndarray) -> str:
    relevant = np.ascontiguousarray(events[:, (0, 2)], dtype="<i8")
    return hashlib.sha256(relevant.tobytes()).hexdigest()


def marker_event_digest(events: np.ndarray) -> str:
    """Return the stable sample/code digest used by a marker plan."""

    return _event_digest(_normalized_events(events))


def _round_positive_fraction(value: Fraction) -> int:
    """Round a nonnegative rational to nearest integer, with halves upward."""

    return (2 * value.numerator + value.denominator) // (2 * value.denominator)


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _optional_int(value: object) -> int | None:
    return int(value) if value is not None else None


def _normalized_path_identity(value: str | Path) -> str:
    try:
        resolved = Path(value).resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        raise MarkerIntegrityError(
            "Marker review source-file identity is invalid."
        ) from exc
    return os.path.normcase(str(resolved))


def _normalized_optional_scope_text(value: object) -> str | None:
    normalized = _optional_text(value)
    return normalized if normalized is not None else None


def _is_sha256(value: object) -> bool:
    text = str(value or "").strip()
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text)


def _validate_utc_review_time(value: object) -> str:
    """Return a validated ISO-8601 UTC timestamp ending in ``Z``."""

    from datetime import datetime, timedelta

    text = str(value or "").strip()
    if not text.endswith("Z"):
        raise MarkerIntegrityError(
            "Marker review time must be an ISO-8601 UTC timestamp ending in Z."
        )
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as exc:
        raise MarkerIntegrityError(
            "Marker review time must be a valid ISO-8601 UTC timestamp."
        ) from exc
    if parsed.utcoffset() != timedelta(0):
        raise MarkerIntegrityError("Marker review time must be in UTC.")
    return text


@dataclass(frozen=True, slots=True)
class ExactDuplicateGroup:
    sample: int
    raw_count: int
    collapsed_count: int


@dataclass(frozen=True, slots=True)
class MarkerIntervalFinding:
    start_sample: int
    stop_sample: int
    interval_samples: int
    interval_seconds: Fraction
    interval_cycles: Fraction
    phase_residual_cycles: Fraction
    early_or_extra_marker: bool
    missing_marker_gap: bool
    estimated_missing_markers: int

    def to_payload(self) -> dict[str, Any]:
        return {
            "start_sample": self.start_sample,
            "stop_sample": self.stop_sample,
            "interval_samples": self.interval_samples,
            "interval_seconds": _fraction_text(self.interval_seconds),
            "interval_cycles": _fraction_text(self.interval_cycles),
            "phase_residual_cycles": _fraction_text(self.phase_residual_cycles),
            "early_or_extra_marker": self.early_or_extra_marker,
            "missing_marker_gap": self.missing_marker_gap,
            "estimated_missing_markers": self.estimated_missing_markers,
        }


@dataclass(frozen=True, slots=True)
class MarkerOccurrencePlan:
    condition_label: str
    condition_code: int
    repetition_index: int
    onset_sample: int
    block_stop_sample: int
    oddball_marker_code: int
    raw_marker_samples: tuple[int, ...]
    retained_marker_samples: tuple[int, ...]
    duplicate_groups: tuple[ExactDuplicateGroup, ...]
    intervals: tuple[MarkerIntervalFinding, ...]
    expected_interval_samples: Fraction
    expected_analyzed_cycles: int
    expected_analyzed_samples: int
    available_span_samples: int
    proposed_start_sample: int | None
    proposed_stop_sample: int | None
    contiguous_candidate_spans: tuple[tuple[int, int], ...]
    status: str
    review_reasons: tuple[str, ...]
    fingerprint: str

    @property
    def requires_review(self) -> bool:
        return self.status == MARKER_STATUS_REVIEW_REQUIRED

    @property
    def occurrence_key(self) -> str:
        return f"{self.condition_code}:{self.repetition_index}"

    @property
    def raw_marker_count(self) -> int:
        return len(self.raw_marker_samples)

    @property
    def retained_marker_count(self) -> int:
        return len(self.retained_marker_samples)

    @property
    def collapsed_duplicate_count(self) -> int:
        return self.raw_marker_count - self.retained_marker_count

    def to_payload(self) -> dict[str, Any]:
        return {
            "condition_label": self.condition_label,
            "condition_code": self.condition_code,
            "repetition_index": self.repetition_index,
            "onset_sample": self.onset_sample,
            "block_stop_sample": self.block_stop_sample,
            "oddball_marker_code": self.oddball_marker_code,
            "raw_marker_samples": list(self.raw_marker_samples),
            "retained_marker_samples": list(self.retained_marker_samples),
            "duplicate_groups": [asdict(group) for group in self.duplicate_groups],
            "intervals": [finding.to_payload() for finding in self.intervals],
            "expected_interval_samples": _fraction_text(
                self.expected_interval_samples
            ),
            "expected_analyzed_cycles": self.expected_analyzed_cycles,
            "expected_analyzed_samples": self.expected_analyzed_samples,
            "available_span_samples": self.available_span_samples,
            "proposed_start_sample": self.proposed_start_sample,
            "proposed_stop_sample": self.proposed_stop_sample,
            "contiguous_candidate_spans": [
                [start, stop] for start, stop in self.contiguous_candidate_spans
            ],
            "status": self.status,
            "review_reasons": list(self.review_reasons),
            "fingerprint": self.fingerprint,
        }


@dataclass(frozen=True, slots=True)
class MarkerIntegrityPlan:
    method_version: str
    sampling_rate_hz: Fraction
    first_samp: int
    event_count: int
    event_digest: str
    protocol_fingerprint: str
    occurrences: tuple[MarkerOccurrencePlan, ...]

    @property
    def unresolved_occurrences(self) -> tuple[MarkerOccurrencePlan, ...]:
        return tuple(item for item in self.occurrences if item.requires_review)

    @property
    def fingerprint(self) -> str:
        payload = self._identity_payload()
        encoded = json.dumps(
            payload,
            separators=(",", ":"),
            sort_keys=True,
            ensure_ascii=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _identity_payload(self) -> dict[str, Any]:
        return {
            "method_version": self.method_version,
            "sampling_rate_hz": _fraction_text(self.sampling_rate_hz),
            "first_samp": self.first_samp,
            "event_count": self.event_count,
            "event_digest": self.event_digest,
            "protocol_fingerprint": self.protocol_fingerprint,
            "occurrences": [item.to_payload() for item in self.occurrences],
        }

    def to_payload(self) -> dict[str, Any]:
        payload = self._identity_payload()
        payload["fingerprint"] = self.fingerprint
        return payload


@dataclass(frozen=True, slots=True)
class MarkerReviewDecision:
    decision: str
    schema_version: str | None = None
    reason: str | None = None
    reviewed_at_utc: str | None = None
    reviewer_state: str | None = None
    reviewer_identity: str | None = None
    reviewer_identity_status: str | None = None
    source_file_path: str | None = None
    participant_id: str | None = None
    recording_id: str | None = None
    session_id: str | None = None
    session_label: str | None = None
    condition_label: str | None = None
    condition_code: int | None = None
    repetition_index: int | None = None
    occurrence_key: str | None = None
    reviewed_marker_plan_fingerprint: str | None = None
    reviewed_occurrence_fingerprint: str | None = None
    evidence_type: str | None = None
    evidence_note: str | None = None
    evidence_reference: str | None = None
    verified_start_sample: int | None = None
    verified_stop_sample: int | None = None

    def __post_init__(self) -> None:
        if not str(self.reason or "").strip():
            object.__setattr__(self, "reason", "No reason provided")

    @classmethod
    def from_payload(cls, value: Mapping[str, Any]) -> "MarkerReviewDecision":
        if not isinstance(value, Mapping):
            raise MarkerIntegrityError("Marker review decision must be an object.")
        try:
            return cls(
                decision=str(value.get("decision") or "").strip(),
                schema_version=_optional_text(value.get("schema_version")),
                reason=_optional_text(value.get("reason")),
                reviewed_at_utc=_optional_text(value.get("reviewed_at_utc")),
                reviewer_state=_optional_text(value.get("reviewer_state")),
                reviewer_identity=_optional_text(value.get("reviewer_identity")),
                reviewer_identity_status=_optional_text(
                    value.get("reviewer_identity_status")
                ),
                source_file_path=_optional_text(value.get("source_file_path")),
                participant_id=_optional_text(value.get("participant_id")),
                recording_id=_optional_text(value.get("recording_id")),
                session_id=_optional_text(value.get("session_id")),
                session_label=_optional_text(value.get("session_label")),
                condition_label=_optional_text(value.get("condition_label")),
                condition_code=_optional_int(value.get("condition_code")),
                repetition_index=_optional_int(value.get("repetition_index")),
                occurrence_key=_optional_text(value.get("occurrence_key")),
                reviewed_marker_plan_fingerprint=_optional_text(
                    value.get("reviewed_marker_plan_fingerprint")
                ),
                reviewed_occurrence_fingerprint=_optional_text(
                    value.get("reviewed_occurrence_fingerprint")
                ),
                evidence_type=_optional_text(value.get("evidence_type")),
                evidence_note=_optional_text(value.get("evidence_note")),
                evidence_reference=_optional_text(value.get("evidence_reference")),
                verified_start_sample=_optional_int(
                    value.get("verified_start_sample")
                ),
                verified_stop_sample=_optional_int(value.get("verified_stop_sample")),
            )
        except (TypeError, ValueError) as exc:
            raise MarkerIntegrityError("Marker review decision is malformed.") from exc


@dataclass(frozen=True, slots=True)
class ApprovedOccurrenceSpan:
    condition_code: int
    repetition_index: int
    disposition: str
    start_sample: int | None
    stop_sample: int | None
    marker_plan_fingerprint: str
    decision_payload: Mapping[str, Any] | None
    fingerprint: str

    @property
    def is_excluded(self) -> bool:
        return self.disposition == MARKER_DECISION_EXCLUDE

    @property
    def occurrence_key(self) -> str:
        return f"{self.condition_code}:{self.repetition_index}"

    def to_payload(self) -> dict[str, Any]:
        return {
            "condition_code": self.condition_code,
            "repetition_index": self.repetition_index,
            "disposition": self.disposition,
            "start_sample": self.start_sample,
            "stop_sample": self.stop_sample,
            "marker_plan_fingerprint": self.marker_plan_fingerprint,
            "decision_payload": (
                dict(self.decision_payload)
                if self.decision_payload is not None
                else None
            ),
            "fingerprint": self.fingerprint,
        }

    @classmethod
    def from_payload(cls, value: Mapping[str, Any]) -> "ApprovedOccurrenceSpan":
        if not isinstance(value, Mapping):
            raise MarkerIntegrityError("Approved occurrence span must be an object.")
        decision_payload = value.get("decision_payload")
        if decision_payload is not None and not isinstance(decision_payload, Mapping):
            raise MarkerIntegrityError("Approved span decision_payload must be an object.")
        try:
            parsed = cls(
                condition_code=int(value["condition_code"]),
                repetition_index=int(value["repetition_index"]),
                disposition=str(value["disposition"]),
                start_sample=(
                    int(value["start_sample"])
                    if value.get("start_sample") is not None
                    else None
                ),
                stop_sample=(
                    int(value["stop_sample"])
                    if value.get("stop_sample") is not None
                    else None
                ),
                marker_plan_fingerprint=str(value["marker_plan_fingerprint"]),
                decision_payload=(
                    dict(decision_payload) if decision_payload is not None else None
                ),
                fingerprint=str(value["fingerprint"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise MarkerIntegrityError("Approved occurrence span is malformed.") from exc
        expected = _occurrence_fingerprint(
            {
                "condition_code": parsed.condition_code,
                "repetition_index": parsed.repetition_index,
                "disposition": parsed.disposition,
                "start_sample": parsed.start_sample,
                "stop_sample": parsed.stop_sample,
                "marker_plan_fingerprint": parsed.marker_plan_fingerprint,
                "decision_payload": parsed.decision_payload,
            }
        )
        if parsed.fingerprint != expected:
            raise MarkerIntegrityError("Approved occurrence span fingerprint mismatch.")
        return parsed


def _occurrence_fingerprint(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        separators=(",", ":"),
        sort_keys=True,
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _interval_findings(
    samples: Sequence[int],
    *,
    sampling_rate_hz: Fraction,
    oddball_rate_hz: Fraction,
) -> tuple[MarkerIntervalFinding, ...]:
    findings: list[MarkerIntervalFinding] = []
    for start, stop in zip(samples, samples[1:], strict=False):
        delta = int(stop) - int(start)
        interval_cycles = Fraction(delta) * oddball_rate_hz / sampling_rate_hz
        nearest_cycles = _round_positive_fraction(interval_cycles)
        missing = interval_cycles > MISSING_MARKER_BOUNDARY_CYCLES
        early = interval_cycles < EARLY_MARKER_BOUNDARY_CYCLES
        findings.append(
            MarkerIntervalFinding(
                start_sample=int(start),
                stop_sample=int(stop),
                interval_samples=delta,
                interval_seconds=Fraction(delta) / sampling_rate_hz,
                interval_cycles=interval_cycles,
                phase_residual_cycles=interval_cycles - nearest_cycles,
                early_or_extra_marker=early,
                missing_marker_gap=missing,
                estimated_missing_markers=(
                    max(1, nearest_cycles - 1) if missing else 0
                ),
            )
        )
    return tuple(findings)


def _deduplicate_exact_samples(
    raw_samples: Sequence[int],
) -> tuple[tuple[int, ...], tuple[ExactDuplicateGroup, ...]]:
    counts: dict[int, int] = {}
    ordered: list[int] = []
    for raw_sample in raw_samples:
        sample = int(raw_sample)
        if sample not in counts:
            counts[sample] = 0
            ordered.append(sample)
        counts[sample] += 1
    groups = tuple(
        ExactDuplicateGroup(
            sample=sample,
            raw_count=counts[sample],
            collapsed_count=counts[sample] - 1,
        )
        for sample in ordered
        if counts[sample] > 1
    )
    return tuple(ordered), groups


def _contiguous_candidate_spans(
    samples: Sequence[int],
    intervals: Sequence[MarkerIntervalFinding],
    *,
    expected_samples: int,
) -> tuple[tuple[int, int], ...]:
    sample_to_index = {int(sample): index for index, sample in enumerate(samples)}
    candidates: list[tuple[int, int]] = []
    for start_index, raw_start in enumerate(samples):
        start = int(raw_start)
        stop = start + int(expected_samples)
        stop_index = sample_to_index.get(stop)
        if stop_index is None or stop_index <= start_index:
            continue
        used_intervals = intervals[start_index:stop_index]
        if any(
            item.early_or_extra_marker or item.missing_marker_gap
            for item in used_intervals
        ):
            continue
        candidates.append((start, stop))
    return tuple(candidates)


def build_marker_integrity_plan(
    *,
    events: np.ndarray,
    event_map: Mapping[str, int],
    sampling_rate_hz: Any,
    n_times: int,
    first_samp: int = 0,
    protocol: FrequencyProtocol,
) -> MarkerIntegrityPlan:
    """Build occurrence-local marker evidence from one immutable protocol."""

    if not protocol.is_ready or protocol.oddball_rate_hz is None:
        raise MarkerIntegrityError(
            "A ready project frequency protocol is required for marker review."
        )
    sample_rate = _positive_fraction(
        sampling_rate_hz,
        field_name="sampling_rate_hz",
    )
    sample_count = int(n_times)
    if sample_count <= 0:
        raise MarkerIntegrityError("n_times must be positive.")
    sample_origin = int(first_samp)
    recording_stop = sample_origin + sample_count

    labels_by_code: dict[int, list[str]] = defaultdict(list)
    for raw_label, raw_code in event_map.items():
        label = str(raw_label).strip()
        if not label:
            continue
        code = int(raw_code)
        labels_by_code[code].append(label)
    if not labels_by_code:
        raise MarkerIntegrityError("A non-empty condition event map is required.")
    try:
        validate_protocol_condition_codes(protocol, labels_by_code)
        expected_samples = protocol.expected_analyzed_samples(sample_rate)
    except FrequencyProtocolError as exc:
        raise MarkerIntegrityError(str(exc)) from exc

    normalized = _normalized_events(events)
    onset_codes = set(labels_by_code)
    onset_rows = [row for row in normalized if int(row[2]) in onset_codes]
    if not onset_rows:
        raise MarkerIntegrityError(
            "No configured condition onset events were found in the recording."
        )

    marker_code = int(protocol.oddball_marker_code)
    expected_interval_samples = sample_rate / protocol.oddball_rate_hz
    repetition_counts: dict[int, int] = defaultdict(int)
    occurrences: list[MarkerOccurrencePlan] = []
    for index, onset_row in enumerate(onset_rows):
        onset_sample = int(onset_row[0])
        if onset_sample < sample_origin or onset_sample >= recording_stop:
            raise MarkerIntegrityError(
                "Configured condition onset is outside the Raw sample grid."
            )
        condition_code = int(onset_row[2])
        repetition_index = repetition_counts[condition_code]
        repetition_counts[condition_code] += 1
        block_stop = (
            min(recording_stop, int(onset_rows[index + 1][0]))
            if index + 1 < len(onset_rows)
            else recording_stop
        )
        raw_samples = tuple(
            int(row[0])
            for row in normalized
            if onset_sample < int(row[0]) < block_stop
            and int(row[2]) == marker_code
        )
        retained_samples, duplicate_groups = _deduplicate_exact_samples(raw_samples)
        intervals = _interval_findings(
            retained_samples,
            sampling_rate_hz=sample_rate,
            oddball_rate_hz=protocol.oddball_rate_hz,
        )
        available_span = (
            retained_samples[-1] - retained_samples[0]
            if len(retained_samples) >= 2
            else 0
        )

        reasons: list[str] = []
        if len(retained_samples) < 2:
            reasons.append("insufficient_project_oddball_markers")
        if any(item.early_or_extra_marker for item in intervals):
            reasons.append("early_or_extra_marker")
        if any(item.missing_marker_gap for item in intervals):
            reasons.append("missing_marker_gap")
        if len(retained_samples) >= 2 and available_span < expected_samples:
            reasons.append("shorter_than_expected_analyzed_cycles")

        proposed_start = retained_samples[0] if retained_samples else None
        proposed_stop = (
            proposed_start + expected_samples
            if proposed_start is not None and available_span >= expected_samples
            else None
        )
        contiguous_candidates = _contiguous_candidate_spans(
            retained_samples,
            intervals,
            expected_samples=expected_samples,
        )
        status = MARKER_STATUS_REVIEW_REQUIRED if reasons else MARKER_STATUS_READY
        base_payload = {
            "method_version": MARKER_INTEGRITY_METHOD_VERSION,
            "protocol_fingerprint": protocol.fingerprint,
            "condition_code": condition_code,
            "repetition_index": repetition_index,
            "onset_sample": onset_sample,
            "block_stop_sample": block_stop,
            "marker_code": marker_code,
            "raw_marker_samples": list(raw_samples),
            "retained_marker_samples": list(retained_samples),
            "duplicate_groups": [asdict(group) for group in duplicate_groups],
            "intervals": [item.to_payload() for item in intervals],
            "expected_analyzed_samples": expected_samples,
            "proposed_start_sample": proposed_start,
            "proposed_stop_sample": proposed_stop,
            "contiguous_candidate_spans": [
                list(span) for span in contiguous_candidates
            ],
            "review_reasons": reasons,
        }
        occurrences.append(
            MarkerOccurrencePlan(
                condition_label=labels_by_code[condition_code][0],
                condition_code=condition_code,
                repetition_index=repetition_index,
                onset_sample=onset_sample,
                block_stop_sample=block_stop,
                oddball_marker_code=marker_code,
                raw_marker_samples=raw_samples,
                retained_marker_samples=retained_samples,
                duplicate_groups=duplicate_groups,
                intervals=intervals,
                expected_interval_samples=expected_interval_samples,
                expected_analyzed_cycles=int(
                    protocol.expected_analyzed_oddball_cycles
                ),
                expected_analyzed_samples=expected_samples,
                available_span_samples=available_span,
                proposed_start_sample=proposed_start,
                proposed_stop_sample=proposed_stop,
                contiguous_candidate_spans=contiguous_candidates,
                status=status,
                review_reasons=tuple(reasons),
                fingerprint=_occurrence_fingerprint(base_payload),
            )
        )

    return MarkerIntegrityPlan(
        method_version=MARKER_INTEGRITY_METHOD_VERSION,
        sampling_rate_hz=sample_rate,
        first_samp=sample_origin,
        event_count=len(normalized),
        event_digest=_event_digest(normalized),
        protocol_fingerprint=protocol.fingerprint,
        occurrences=tuple(occurrences),
    )


def approve_clean_occurrence(
    occurrence: MarkerOccurrencePlan,
) -> ApprovedOccurrenceSpan:
    """Approve the deterministic declared-length span of a clean occurrence."""

    if occurrence.requires_review:
        raise MarkerIntegrityError(
            "This occurrence requires a recorded GUI review decision."
        )
    if (
        occurrence.proposed_start_sample is None
        or occurrence.proposed_stop_sample is None
    ):
        raise MarkerIntegrityError("The clean occurrence has no usable proposed span.")
    return _approved_span(
        occurrence,
        disposition="automatic_clean",
        start=occurrence.proposed_start_sample,
        stop=occurrence.proposed_stop_sample,
        decision_payload=None,
    )


def _validate_marker_review_receipt(
    occurrence: MarkerOccurrencePlan,
    decision: MarkerReviewDecision,
    *,
    marker_plan_fingerprint: str,
    review_scope: Mapping[str, Any],
) -> None:
    if decision.schema_version != MARKER_REVIEW_DECISION_SCHEMA_VERSION:
        raise MarkerIntegrityError(
            "Marker review decision schema is missing or stale; review this "
            "occurrence again."
        )
    _validate_utc_review_time(decision.reviewed_at_utc)
    if decision.reviewer_state != MARKER_REVIEWER_STATE_EXPLICIT_GUI:
        raise MarkerIntegrityError(
            "Marker review decision does not record an explicit GUI reviewer state."
        )
    if (
        decision.reviewer_identity_status
        == MARKER_REVIEWER_IDENTITY_STATUS_NOT_COLLECTED
    ):
        if decision.reviewer_identity is not None:
            raise MarkerIntegrityError(
                "Marker review cannot name a reviewer when identity was not collected."
            )
    elif (
        decision.reviewer_identity_status
        == MARKER_REVIEWER_IDENTITY_STATUS_PROVIDED
    ):
        if not str(decision.reviewer_identity or "").strip():
            raise MarkerIntegrityError(
                "Marker review says reviewer identity was provided but stores no identity."
            )
    else:
        raise MarkerIntegrityError(
            "Marker review decision has no truthful reviewer identity status."
        )

    current_plan_fingerprint = str(marker_plan_fingerprint).strip()
    if not _is_sha256(current_plan_fingerprint):
        raise MarkerIntegrityError("Current marker-plan fingerprint is malformed.")
    if decision.reviewed_marker_plan_fingerprint != current_plan_fingerprint:
        raise MarkerIntegrityError(
            "Marker review decision was made from a different marker plan; review "
            "this occurrence again."
        )
    if (
        not _is_sha256(decision.reviewed_occurrence_fingerprint)
        or decision.reviewed_occurrence_fingerprint != occurrence.fingerprint
    ):
        raise MarkerIntegrityError(
            "Marker review decision was made from different occurrence evidence; "
            "review this occurrence again."
        )

    expected_occurrence_scope = {
        "condition_label": occurrence.condition_label,
        "condition_code": occurrence.condition_code,
        "repetition_index": occurrence.repetition_index,
        "occurrence_key": occurrence.occurrence_key,
    }
    actual_occurrence_scope = {
        "condition_label": decision.condition_label,
        "condition_code": decision.condition_code,
        "repetition_index": decision.repetition_index,
        "occurrence_key": decision.occurrence_key,
    }
    if actual_occurrence_scope != expected_occurrence_scope:
        raise MarkerIntegrityError(
            "Marker review decision occurrence scope does not match the current "
            "condition occurrence."
        )

    if not str(decision.participant_id or "").strip():
        raise MarkerIntegrityError(
            "Marker review decision is missing its participant scope."
        )

    expected_path = review_scope.get("source_file_path")
    if expected_path is None or decision.source_file_path is None:
        raise MarkerIntegrityError(
            "Marker review decision is missing its source-file scope."
        )
    if _normalized_path_identity(decision.source_file_path) != _normalized_path_identity(
        str(expected_path)
    ):
        raise MarkerIntegrityError(
            "Marker review decision belongs to a different source file."
        )
    for field_name in (
        "participant_id",
        "recording_id",
        "session_id",
        "session_label",
    ):
        expected = _normalized_optional_scope_text(review_scope.get(field_name))
        actual = _normalized_optional_scope_text(getattr(decision, field_name))
        if actual != expected:
            raise MarkerIntegrityError(
                f"Marker review decision {field_name} scope is stale."
            )


def apply_marker_review_decision(
    occurrence: MarkerOccurrencePlan,
    decision: MarkerReviewDecision,
    *,
    marker_plan_fingerprint: str,
    review_scope: Mapping[str, Any],
) -> ApprovedOccurrenceSpan:
    """Validate one GUI decision and return the sole downstream span record."""

    choice = str(decision.decision).strip()
    if choice not in {
        MARKER_DECISION_RETAIN_FULL,
        MARKER_DECISION_USE_CONTIGUOUS,
        MARKER_DECISION_EXCLUDE,
    }:
        raise MarkerIntegrityError(f"Unsupported marker review decision {choice!r}.")

    _validate_marker_review_receipt(
        occurrence,
        decision,
        marker_plan_fingerprint=marker_plan_fingerprint,
        review_scope=review_scope,
    )

    decision_payload = asdict(decision)
    if choice == MARKER_DECISION_EXCLUDE:
        return _approved_span(
            occurrence,
            disposition=choice,
            start=None,
            stop=None,
            decision_payload=decision_payload,
        )

    if choice == MARKER_DECISION_RETAIN_FULL:
        evidence_type = str(decision.evidence_type or "").strip()
        evidence_note = str(decision.evidence_note or "").strip()
        evidence_reference = str(decision.evidence_reference or "").strip()
        if not evidence_type or not (evidence_note or evidence_reference):
            raise MarkerIntegrityError(
                "Retaining across a marker gap requires an evidence type and a note "
                "or log reference showing continuous phase-correct stimulation."
            )
        start = occurrence.proposed_start_sample
        stop = occurrence.proposed_stop_sample
        if start is None or stop is None:
            raise MarkerIntegrityError(
                "This occurrence is too short for the declared analyzed cycle count; "
                "it cannot be retained without padding."
            )
    else:
        if (
            decision.verified_start_sample is None
            or decision.verified_stop_sample is None
        ):
            raise MarkerIntegrityError(
                "A verified contiguous span requires explicit start and stop samples."
            )
        start = int(decision.verified_start_sample)
        stop = int(decision.verified_stop_sample)
        if stop - start != occurrence.expected_analyzed_samples:
            raise MarkerIntegrityError(
                "The verified contiguous span must contain exactly the project's "
                "declared analyzed oddball cycles."
            )
        if (start, stop) not in occurrence.contiguous_candidate_spans:
            raise MarkerIntegrityError(
                "The selected span is not an unambiguous contiguous marker sequence."
            )
        if start < occurrence.onset_sample or stop > occurrence.block_stop_sample:
            raise MarkerIntegrityError(
                "The verified contiguous span must stay inside this condition occurrence."
            )

    return _approved_span(
        occurrence,
        disposition=choice,
        start=start,
        stop=stop,
        decision_payload=decision_payload,
    )


def _approved_span(
    occurrence: MarkerOccurrencePlan,
    *,
    disposition: str,
    start: int | None,
    stop: int | None,
    decision_payload: Mapping[str, Any] | None,
) -> ApprovedOccurrenceSpan:
    payload = {
        "condition_code": occurrence.condition_code,
        "repetition_index": occurrence.repetition_index,
        "disposition": disposition,
        "start_sample": start,
        "stop_sample": stop,
        "marker_plan_fingerprint": occurrence.fingerprint,
        "decision_payload": decision_payload,
    }
    return ApprovedOccurrenceSpan(
        condition_code=occurrence.condition_code,
        repetition_index=occurrence.repetition_index,
        disposition=disposition,
        start_sample=start,
        stop_sample=stop,
        marker_plan_fingerprint=occurrence.fingerprint,
        decision_payload=decision_payload,
        fingerprint=_occurrence_fingerprint(payload),
    )


def validate_approved_event_plan(
    *,
    event_plan_payload: Mapping[str, Any],
    events: np.ndarray,
    sampling_rate_hz: Any,
    n_times: int,
    first_samp: int = 0,
    event_map: Mapping[str, int],
    protocol: FrequencyProtocol,
) -> tuple[ApprovedOccurrenceSpan, ...]:
    """Validate preflight's exact approved spans without rebuilding crop logic."""

    if not isinstance(event_plan_payload, Mapping):
        raise MarkerIntegrityError("Preflight event plan must be an object.")
    marker_plan = event_plan_payload.get("marker_integrity_plan")
    if not isinstance(marker_plan, Mapping):
        raise MarkerIntegrityError("Preflight event plan is missing marker integrity data.")
    if marker_plan.get("method_version") != MARKER_INTEGRITY_METHOD_VERSION:
        raise MarkerIntegrityError("Preflight marker policy version is not current.")
    sample_rate = _positive_fraction(
        sampling_rate_hz,
        field_name="sampling_rate_hz",
    )
    if _positive_fraction(
        marker_plan.get("sampling_rate_hz"),
        field_name="planned_sampling_rate_hz",
    ) != sample_rate:
        raise MarkerIntegrityError("Preflight marker plan sampling rate is stale.")
    sample_origin = int(first_samp)
    if int(marker_plan.get("first_samp", -1)) != sample_origin:
        raise MarkerIntegrityError("Preflight marker plan sample origin is stale.")
    if int(event_plan_payload.get("first_samp", -1)) != sample_origin:
        raise MarkerIntegrityError("Preflight event plan sample origin is stale.")
    normalized = _normalized_events(events)
    if int(marker_plan.get("event_count", -1)) != len(normalized):
        raise MarkerIntegrityError("Preflight marker event count is stale.")
    if str(marker_plan.get("event_digest") or "") != _event_digest(normalized):
        raise MarkerIntegrityError("Preflight marker event digest is stale.")
    if str(marker_plan.get("protocol_fingerprint") or "") != protocol.fingerprint:
        raise MarkerIntegrityError("Preflight marker plan protocol is stale.")
    if int(event_plan_payload.get("n_times", -1)) != int(n_times):
        raise MarkerIntegrityError("Preflight marker plan recording length is stale.")
    planned_fingerprint = str(marker_plan.get("fingerprint") or "").strip()
    if not _is_sha256(planned_fingerprint):
        raise MarkerIntegrityError("Preflight marker-plan fingerprint is malformed.")
    rebuilt_plan = build_marker_integrity_plan(
        events=normalized,
        event_map=event_map,
        sampling_rate_hz=sample_rate,
        n_times=n_times,
        first_samp=sample_origin,
        protocol=protocol,
    )
    if planned_fingerprint != rebuilt_plan.fingerprint:
        raise MarkerIntegrityError(
            "Preflight marker-plan evidence fingerprint is stale or invalid."
        )
    unresolved = event_plan_payload.get("unresolved_occurrences")
    if unresolved not in (None, [], ()):
        raise MarkerIntegrityError(
            "Preflight marker plan still contains unresolved occurrences."
        )

    raw_occurrences = marker_plan.get("occurrences")
    raw_approved = event_plan_payload.get("approved_occurrences")
    if not isinstance(raw_occurrences, Sequence) or isinstance(raw_occurrences, str):
        raise MarkerIntegrityError("Preflight marker occurrences are malformed.")
    if not isinstance(raw_approved, Sequence) or isinstance(raw_approved, str):
        raise MarkerIntegrityError("Preflight approved occurrences are malformed.")
    if len(raw_occurrences) != len(raw_approved):
        raise MarkerIntegrityError(
            "Every marker occurrence must have one approved or excluded disposition."
        )

    labels_by_code = {int(code): str(label) for label, code in event_map.items()}
    expected_samples = protocol.expected_analyzed_samples(sample_rate)
    rebuilt_occurrences_by_key = {
        occurrence.occurrence_key: occurrence
        for occurrence in rebuilt_plan.occurrences
    }
    approved_by_key: dict[str, ApprovedOccurrenceSpan] = {}
    occurrence_by_key: dict[str, Mapping[str, Any]] = {}
    for raw_occurrence in raw_occurrences:
        if not isinstance(raw_occurrence, Mapping):
            raise MarkerIntegrityError("Preflight marker occurrence is malformed.")
        try:
            key = (
                f"{int(raw_occurrence['condition_code'])}:"
                f"{int(raw_occurrence['repetition_index'])}"
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise MarkerIntegrityError("Preflight marker occurrence key is malformed.") from exc
        if key in occurrence_by_key:
            raise MarkerIntegrityError("Preflight marker occurrence keys are duplicated.")
        occurrence_by_key[key] = raw_occurrence

    for raw_span in raw_approved:
        approved = ApprovedOccurrenceSpan.from_payload(raw_span)
        if approved.occurrence_key in approved_by_key:
            raise MarkerIntegrityError("Approved occurrence keys are duplicated.")
        occurrence = occurrence_by_key.get(approved.occurrence_key)
        if occurrence is None:
            raise MarkerIntegrityError("Approved occurrence is not in the marker plan.")
        if approved.condition_code not in labels_by_code:
            raise MarkerIntegrityError(
                "Approved occurrence uses an unknown condition-onset code."
            )
        if str(occurrence.get("fingerprint") or "") != approved.marker_plan_fingerprint:
            raise MarkerIntegrityError("Approved occurrence evidence fingerprint is stale.")
        if int(occurrence.get("oddball_marker_code", -1)) != protocol.oddball_marker_code:
            raise MarkerIntegrityError("Approved occurrence marker code is stale.")
        allowed_dispositions = {
            "automatic_clean",
            MARKER_DECISION_RETAIN_FULL,
            MARKER_DECISION_USE_CONTIGUOUS,
            MARKER_DECISION_EXCLUDE,
        }
        if approved.disposition not in allowed_dispositions:
            raise MarkerIntegrityError("Approved occurrence disposition is unsupported.")
        if approved.disposition == "automatic_clean":
            if approved.decision_payload is not None:
                raise MarkerIntegrityError(
                    "Automatically approved occurrence cannot contain a manual decision."
                )
        else:
            if approved.decision_payload is None:
                raise MarkerIntegrityError(
                    "Manually reviewed occurrence is missing its audit receipt."
                )
            rebuilt_occurrence = rebuilt_occurrences_by_key.get(
                approved.occurrence_key
            )
            if rebuilt_occurrence is None:
                raise MarkerIntegrityError(
                    "Reviewed occurrence is missing from the current marker plan."
                )
            reviewed_decision = MarkerReviewDecision.from_payload(
                approved.decision_payload
            )
            _validate_marker_review_receipt(
                rebuilt_occurrence,
                reviewed_decision,
                marker_plan_fingerprint=rebuilt_plan.fingerprint,
                review_scope={
                    "source_file_path": reviewed_decision.source_file_path,
                    "participant_id": reviewed_decision.participant_id,
                    "recording_id": reviewed_decision.recording_id,
                    "session_id": reviewed_decision.session_id,
                    "session_label": reviewed_decision.session_label,
                },
            )
            if reviewed_decision.decision != approved.disposition:
                raise MarkerIntegrityError(
                    "Marker review receipt does not match the approved disposition."
                )
        if approved.is_excluded:
            if approved.start_sample is not None or approved.stop_sample is not None:
                raise MarkerIntegrityError("Excluded occurrence cannot contain a span.")
        else:
            if approved.start_sample is None or approved.stop_sample is None:
                raise MarkerIntegrityError("Retained occurrence must contain a span.")
            if approved.stop_sample - approved.start_sample != expected_samples:
                raise MarkerIntegrityError(
                    "Approved occurrence no longer matches the declared analyzed cycles."
                )
            onset = int(occurrence.get("onset_sample", -1))
            block_stop = int(occurrence.get("block_stop_sample", -1))
            recording_stop = sample_origin + int(n_times)
            if onset < sample_origin or block_stop > recording_stop:
                raise MarkerIntegrityError(
                    "Approved occurrence evidence is outside the source Raw sample grid."
                )
            if approved.start_sample < onset or approved.stop_sample > block_stop:
                raise MarkerIntegrityError(
                    "Approved occurrence span is outside its condition occurrence."
                )
        approved_by_key[approved.occurrence_key] = approved

    return tuple(
        approved_by_key[key]
        for key in occurrence_by_key
    )
