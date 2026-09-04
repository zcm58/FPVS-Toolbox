"""Pure identity adapters for frequency-domain QC review."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

FREQUENCY_QC_REVIEW_IDENTITY_VERSION = "frequency_qc_review_identity_v1"
IDENTITY_SCOPE_PARTICIPANT = "participant"
IDENTITY_SCOPE_RECORDING = "recording"


class FrequencyQcReviewIdentityError(ValueError):
    """Raised when a review report contains stale or ambiguous identity."""


@dataclass(frozen=True, slots=True)
class FrequencyQcReviewIdentity:
    """Canonical identity for one participant- or recording-scoped review row."""

    identity_scope: str
    decision_key: str
    participant_id: str
    recording_id: str | None = None
    session_id: str | None = None
    session_label: str | None = None
    visit_index: int | None = None
    group_id: str | None = None
    source_id: str | None = None
    days_from_baseline: float | None = None

    def to_payload(self) -> dict[str, object]:
        return {
            "review_identity_version": FREQUENCY_QC_REVIEW_IDENTITY_VERSION,
            "identity_scope": self.identity_scope,
            "decision_key": self.decision_key,
            "participant_id": self.participant_id,
            "recording_id": self.recording_id,
            "session_id": self.session_id,
            "session_label": self.session_label,
            "visit_index": self.visit_index,
            "group_id": self.group_id,
            "source_id": self.source_id,
            "days_from_baseline": self.days_from_baseline,
        }


@dataclass(frozen=True, slots=True)
class ResolvedRecordingReviewDecision:
    """One submitted recording decision bound to canonical report identity."""

    identity: FrequencyQcReviewIdentity
    reason: str


def frequency_qc_review_rows(
    report: Mapping[str, object],
) -> tuple[dict[str, object], ...]:
    """Return scope-aware review summaries with canonical identity attached."""

    scope = _identity_scope(report)
    if scope == IDENTITY_SCOPE_RECORDING:
        identities = _recording_identity_map(report)
        summaries = _mapping_rows(
            report.get("recording_summaries"),
            field_name="recording_summaries",
        )
        key_field = "recording_id"
    else:
        identities = _participant_identity_map(report)
        summaries = _mapping_rows(
            report.get("participant_summaries"),
            field_name="participant_summaries",
        )
        key_field = "participant_id"

    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    for summary in summaries:
        submitted_key = str(summary.get(key_field) or "").strip()
        if not submitted_key:
            raise FrequencyQcReviewIdentityError(f"Frequency-QC {scope} summary is missing {key_field}.")
        key = submitted_key.casefold()
        if key in seen:
            raise FrequencyQcReviewIdentityError(f"Frequency-QC report repeats {scope} identity {submitted_key!r}.")
        seen.add(key)
        identity = identities.get(key)
        if identity is None:
            raise FrequencyQcReviewIdentityError(
                f"Frequency-QC report contains unknown or stale {scope} identity {submitted_key!r}."
            )
        row = dict(summary)
        row.update(identity.to_payload())
        rows.append(row)
    return tuple(rows)


def resolve_frequency_qc_recording_decisions(
    report: Mapping[str, object],
    reasons: Mapping[str, object] | None,
) -> tuple[ResolvedRecordingReviewDecision, ...]:
    """Resolve submitted recording keys to exact canonical report assignments.

    Resolution is case-insensitive for user input, while returned IDs preserve
    the project's canonical spelling. Unknown, stale, blank, or ambiguous keys
    raise before a caller performs any persistence.
    """

    if not reasons:
        return ()
    if _identity_scope(report) != IDENTITY_SCOPE_RECORDING:
        raise FrequencyQcReviewIdentityError("Recording decisions require a recording-scoped Frequency-QC report.")
    identities = _recording_identity_map(report)
    resolved: list[ResolvedRecordingReviewDecision] = []
    seen: set[str] = set()
    for raw_recording_id, raw_reason in reasons.items():
        submitted = str(raw_recording_id or "").strip()
        key = submitted.casefold()
        if not key:
            raise FrequencyQcReviewIdentityError("A submitted Frequency-QC recording ID is blank.")
        if key in seen:
            raise FrequencyQcReviewIdentityError(
                f"A Frequency-QC recording decision was submitted more than once: {submitted!r}."
            )
        seen.add(key)
        identity = identities.get(key)
        if identity is None:
            raise FrequencyQcReviewIdentityError(
                f"Frequency-QC decision references an unknown or stale recording ID: {submitted!r}."
            )
        resolved.append(
            ResolvedRecordingReviewDecision(
                identity=identity,
                reason=str(raw_reason or "").strip(),
            )
        )
    return tuple(resolved)


def _identity_scope(report: Mapping[str, object]) -> str:
    raw_scope = str(report.get("identity_scope") or IDENTITY_SCOPE_PARTICIPANT)
    scope = raw_scope.strip().casefold()
    if scope not in {IDENTITY_SCOPE_PARTICIPANT, IDENTITY_SCOPE_RECORDING}:
        raise FrequencyQcReviewIdentityError(f"Unsupported Frequency-QC identity scope: {raw_scope!r}.")
    return scope


def _recording_identity_map(
    report: Mapping[str, object],
) -> dict[str, FrequencyQcReviewIdentity]:
    assignments = _mapping_rows(
        report.get("recording_assignments"),
        field_name="recording_assignments",
    )
    identities: dict[str, FrequencyQcReviewIdentity] = {}
    for assignment in assignments:
        recording_id = str(assignment.get("recording_id") or "").strip()
        participant_id = str(assignment.get("participant_id") or "").strip()
        if not recording_id or not participant_id:
            raise FrequencyQcReviewIdentityError(
                "Every Frequency-QC recording assignment requires canonical recording_id and participant_id values."
            )
        key = recording_id.casefold()
        if key in identities:
            raise FrequencyQcReviewIdentityError(
                "Frequency-QC recording assignments contain IDs that are duplicated "
                f"case-insensitively: {recording_id!r}."
            )
        identities[key] = FrequencyQcReviewIdentity(
            identity_scope=IDENTITY_SCOPE_RECORDING,
            decision_key=recording_id,
            participant_id=participant_id,
            recording_id=recording_id,
            session_id=_optional_text(assignment.get("session_id")),
            session_label=_optional_text(assignment.get("session_label")),
            visit_index=_optional_int(assignment.get("visit_index")),
            group_id=_optional_text(assignment.get("group_id")),
            source_id=_optional_text(assignment.get("source_id")),
            days_from_baseline=_optional_float(assignment.get("days_from_baseline")),
        )
    return identities


def _participant_identity_map(
    report: Mapping[str, object],
) -> dict[str, FrequencyQcReviewIdentity]:
    subjects = _text_rows(report.get("subjects"), field_name="subjects")
    summaries = _mapping_rows(
        report.get("participant_summaries"),
        field_name="participant_summaries",
    )
    canonical_ids = list(subjects)
    if not canonical_ids:
        canonical_ids = [
            str(summary.get("participant_id") or "").strip()
            for summary in summaries
            if str(summary.get("participant_id") or "").strip()
        ]

    identities: dict[str, FrequencyQcReviewIdentity] = {}
    for participant_id in canonical_ids:
        key = participant_id.casefold()
        existing = identities.get(key)
        if existing is not None and existing.participant_id != participant_id:
            raise FrequencyQcReviewIdentityError(
                "Frequency-QC participant IDs are duplicated case-insensitively: "
                f"{existing.participant_id!r} and {participant_id!r}."
            )
        identities[key] = FrequencyQcReviewIdentity(
            identity_scope=IDENTITY_SCOPE_PARTICIPANT,
            decision_key=participant_id,
            participant_id=participant_id,
        )
    return identities


def _mapping_rows(value: object, *, field_name: str) -> tuple[Mapping[str, Any], ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise FrequencyQcReviewIdentityError(f"Frequency-QC {field_name} must be a sequence of mappings.")
    rows: list[Mapping[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise FrequencyQcReviewIdentityError(f"Frequency-QC {field_name} must contain only mappings.")
        rows.append(item)
    return tuple(rows)


def _text_rows(value: object, *, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise FrequencyQcReviewIdentityError(f"Frequency-QC {field_name} must be a sequence of IDs.")
    return tuple(str(item or "").strip() for item in value if str(item or "").strip())


def _optional_text(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _optional_int(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _optional_float(value: object) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


__all__ = [
    "FREQUENCY_QC_REVIEW_IDENTITY_VERSION",
    "IDENTITY_SCOPE_PARTICIPANT",
    "IDENTITY_SCOPE_RECORDING",
    "FrequencyQcReviewIdentity",
    "FrequencyQcReviewIdentityError",
    "ResolvedRecordingReviewDecision",
    "frequency_qc_review_rows",
    "resolve_frequency_qc_recording_decisions",
]
