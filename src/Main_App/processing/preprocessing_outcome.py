"""Versioned, GUI-neutral preprocessing outcome semantics."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

PREPROCESSING_OUTCOME_VERSION = "preprocessing_outcome_v1"

PROCESSING_STATUS_COMPLETED = "completed"
PROCESSING_STATUS_COMPLETED_MISSING_CONDITIONS = "completed_missing_conditions"
PROCESSING_STATUS_EXCLUDED = "excluded"
PROCESSING_STATUS_FAILED = "failed"
PROCESSING_STATUS_PENDING = "pending"
PROCESSING_STATUS_LEGACY_UNKNOWN = "legacy_unknown"
PROCESSING_STATUSES = frozenset(
    {
        PROCESSING_STATUS_COMPLETED,
        PROCESSING_STATUS_COMPLETED_MISSING_CONDITIONS,
        PROCESSING_STATUS_EXCLUDED,
        PROCESSING_STATUS_FAILED,
        PROCESSING_STATUS_PENDING,
        PROCESSING_STATUS_LEGACY_UNKNOWN,
    }
)

INTERPOLATION_STATUS_ATTEMPTED = "attempted"
INTERPOLATION_STATUS_SUCCEEDED = "succeeded"
INTERPOLATION_STATUS_FAILED = "failed"
INTERPOLATION_STATUS_SKIPPED = "skipped"
INTERPOLATION_STATUS_NOT_NEEDED = "not_needed"
INTERPOLATION_STATUS_LEGACY_UNKNOWN = "legacy_unknown"
INTERPOLATION_STATUSES = frozenset(
    {
        INTERPOLATION_STATUS_ATTEMPTED,
        INTERPOLATION_STATUS_SUCCEEDED,
        INTERPOLATION_STATUS_FAILED,
        INTERPOLATION_STATUS_SKIPPED,
        INTERPOLATION_STATUS_NOT_NEEDED,
        INTERPOLATION_STATUS_LEGACY_UNKNOWN,
    }
)


class PreprocessingOutcomeError(ValueError):
    """Raised when current-version outcome metadata is internally inconsistent."""


@dataclass(frozen=True, slots=True)
class PreprocessingOutcome:
    """One normalized processing-stage and interpolation outcome."""

    outcome_version: str | None
    processing_status: str
    processing_reason: str
    missing_conditions: tuple[str, ...]
    interpolation_status: str
    interpolation_requested_channels: tuple[str, ...]
    interpolation_successful_channels: tuple[str, ...]
    interpolation_detail: str

    @property
    def is_current(self) -> bool:
        return self.outcome_version == PREPROCESSING_OUTCOME_VERSION

    @property
    def interpolation_was_attempted(self) -> bool:
        return self.interpolation_status in {
            INTERPOLATION_STATUS_ATTEMPTED,
            INTERPOLATION_STATUS_SUCCEEDED,
            INTERPOLATION_STATUS_FAILED,
        }

    def to_payload(self) -> dict[str, object]:
        """Return the stable JSON-safe representation for future persistence."""

        return {
            "outcome_version": self.outcome_version,
            "processing_status": self.processing_status,
            "processing_reason": self.processing_reason,
            "missing_conditions": list(self.missing_conditions),
            "interpolation_status": self.interpolation_status,
            "interpolation_requested_channels": list(self.interpolation_requested_channels),
            "interpolation_successful_channels": list(self.interpolation_successful_channels),
            "interpolation_detail": self.interpolation_detail,
        }


def normalize_preprocessing_outcome(
    value: PreprocessingOutcome | Mapping[str, Any] | None,
) -> PreprocessingOutcome:
    """Normalize trusted v1 metadata and quarantine older/unknown records.

    Callers may pass a v1 payload directly or a larger record containing it at
    ``preprocessing_outcome``.  Records without the exact current version are
    deliberately returned as legacy-unknown; adjacent raw-QC or kurtosis flags
    are never interpreted as evidence that interpolation succeeded.
    """

    if isinstance(value, PreprocessingOutcome):
        if not value.is_current:
            return _legacy_unknown_outcome()
        value = value.to_payload()
    if not isinstance(value, Mapping):
        return _legacy_unknown_outcome()

    nested = value.get("preprocessing_outcome")
    payload = nested if isinstance(nested, Mapping) else value
    version = str(payload.get("outcome_version") or "").strip()
    if version != PREPROCESSING_OUTCOME_VERSION:
        return _legacy_unknown_outcome()

    processing_status = _normalized_status(
        payload.get("processing_status"),
        valid=PROCESSING_STATUSES,
        field_name="processing_status",
    )
    interpolation_status = _normalized_status(
        payload.get("interpolation_status"),
        valid=INTERPOLATION_STATUSES,
        field_name="interpolation_status",
    )
    processing_reason = str(payload.get("processing_reason") or "").strip()
    interpolation_detail = str(payload.get("interpolation_detail") or "").strip()
    missing_conditions = _normalized_text_list(
        payload.get("missing_conditions"),
        field_name="missing_conditions",
    )
    requested = _normalized_text_list(
        payload.get("interpolation_requested_channels"),
        field_name="interpolation_requested_channels",
    )
    successful = _normalized_text_list(
        payload.get("interpolation_successful_channels"),
        field_name="interpolation_successful_channels",
    )

    _validate_processing_outcome(
        processing_status=processing_status,
        processing_reason=processing_reason,
        missing_conditions=missing_conditions,
    )
    _validate_interpolation_outcome(
        interpolation_status=interpolation_status,
        requested=requested,
        successful=successful,
        detail=interpolation_detail,
    )
    return PreprocessingOutcome(
        outcome_version=PREPROCESSING_OUTCOME_VERSION,
        processing_status=processing_status,
        processing_reason=processing_reason,
        missing_conditions=missing_conditions,
        interpolation_status=interpolation_status,
        interpolation_requested_channels=requested,
        interpolation_successful_channels=successful,
        interpolation_detail=interpolation_detail,
    )


def build_preprocessing_outcome(
    *,
    processing_status: str,
    interpolation_status: str,
    processing_reason: str = "",
    missing_conditions: Sequence[object] = (),
    interpolation_requested_channels: Sequence[object] = (),
    interpolation_successful_channels: Sequence[object] = (),
    interpolation_detail: str = "",
) -> PreprocessingOutcome:
    """Build and validate a current-version outcome."""

    return normalize_preprocessing_outcome(
        {
            "outcome_version": PREPROCESSING_OUTCOME_VERSION,
            "processing_status": processing_status,
            "processing_reason": processing_reason,
            "missing_conditions": list(missing_conditions),
            "interpolation_status": interpolation_status,
            "interpolation_requested_channels": list(interpolation_requested_channels),
            "interpolation_successful_channels": list(interpolation_successful_channels),
            "interpolation_detail": interpolation_detail,
        }
    )


def _legacy_unknown_outcome() -> PreprocessingOutcome:
    return PreprocessingOutcome(
        outcome_version=None,
        processing_status=PROCESSING_STATUS_LEGACY_UNKNOWN,
        processing_reason="",
        missing_conditions=(),
        interpolation_status=INTERPOLATION_STATUS_LEGACY_UNKNOWN,
        interpolation_requested_channels=(),
        interpolation_successful_channels=(),
        interpolation_detail="",
    )


def _normalized_status(value: object, *, valid: frozenset[str], field_name: str) -> str:
    status = str(value or "").strip().casefold().replace("-", "_")
    if status not in valid:
        raise PreprocessingOutcomeError(f"{field_name} must be one of: {', '.join(sorted(valid))}.")
    return status


def _normalized_text_list(value: object, *, field_name: str) -> tuple[str, ...]:
    if value in (None, ""):
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise PreprocessingOutcomeError(f"{field_name} must be a sequence of strings.")
    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item or "").strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(text)
    return tuple(normalized)


def _validate_processing_outcome(
    *,
    processing_status: str,
    processing_reason: str,
    missing_conditions: tuple[str, ...],
) -> None:
    if processing_status == PROCESSING_STATUS_COMPLETED_MISSING_CONDITIONS and not missing_conditions:
        raise PreprocessingOutcomeError("completed_missing_conditions requires at least one missing condition.")
    if processing_status == PROCESSING_STATUS_COMPLETED and missing_conditions:
        raise PreprocessingOutcomeError(
            "completed cannot include missing conditions; use completed_missing_conditions."
        )
    if processing_status in {PROCESSING_STATUS_EXCLUDED, PROCESSING_STATUS_FAILED}:
        if not processing_reason:
            raise PreprocessingOutcomeError(f"{processing_status} requires a processing_reason.")


def _validate_interpolation_outcome(
    *,
    interpolation_status: str,
    requested: tuple[str, ...],
    successful: tuple[str, ...],
    detail: str,
) -> None:
    if interpolation_status == INTERPOLATION_STATUS_SUCCEEDED:
        if not requested or not successful:
            raise PreprocessingOutcomeError("succeeded interpolation requires requested and successful channels.")
        if {item.casefold() for item in requested} != {item.casefold() for item in successful}:
            raise PreprocessingOutcomeError("succeeded interpolation requires every requested channel to succeed.")
        return

    if successful:
        raise PreprocessingOutcomeError("Only succeeded interpolation may contain successful channels.")
    if (
        interpolation_status
        in {
            INTERPOLATION_STATUS_ATTEMPTED,
            INTERPOLATION_STATUS_FAILED,
        }
        and not requested
    ):
        raise PreprocessingOutcomeError(f"{interpolation_status} interpolation requires requested channels.")
    if interpolation_status == INTERPOLATION_STATUS_FAILED and not detail:
        raise PreprocessingOutcomeError("failed interpolation requires an interpolation_detail.")
    if interpolation_status == INTERPOLATION_STATUS_SKIPPED and not detail:
        raise PreprocessingOutcomeError("skipped interpolation requires an interpolation_detail.")
    if interpolation_status == INTERPOLATION_STATUS_NOT_NEEDED and requested:
        raise PreprocessingOutcomeError("not_needed interpolation cannot contain requested channels.")


__all__ = [
    "INTERPOLATION_STATUSES",
    "INTERPOLATION_STATUS_ATTEMPTED",
    "INTERPOLATION_STATUS_FAILED",
    "INTERPOLATION_STATUS_LEGACY_UNKNOWN",
    "INTERPOLATION_STATUS_NOT_NEEDED",
    "INTERPOLATION_STATUS_SKIPPED",
    "INTERPOLATION_STATUS_SUCCEEDED",
    "PREPROCESSING_OUTCOME_VERSION",
    "PROCESSING_STATUSES",
    "PROCESSING_STATUS_COMPLETED",
    "PROCESSING_STATUS_COMPLETED_MISSING_CONDITIONS",
    "PROCESSING_STATUS_EXCLUDED",
    "PROCESSING_STATUS_FAILED",
    "PROCESSING_STATUS_LEGACY_UNKNOWN",
    "PROCESSING_STATUS_PENDING",
    "PreprocessingOutcome",
    "PreprocessingOutcomeError",
    "build_preprocessing_outcome",
    "normalize_preprocessing_outcome",
]
