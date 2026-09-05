"""QC-07 interpolation-burden results from confirmed preprocessing outcomes."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from typing import Any

from Main_App.io.eeg_geometry import (
    BioSemi64GeometryError,
    biosemi64_geometry_identity,
)
from Main_App.processing.preprocessing_outcome import (
    INTERPOLATION_STATUS_NOT_NEEDED,
    INTERPOLATION_STATUS_SUCCEEDED,
    PreprocessingOutcome,
    normalize_preprocessing_outcome,
)

INTERPOLATION_BURDEN_VERSION = "interpolation_burden_v1"
INTERPOLATION_BURDEN_REVIEW_THRESHOLD_PERCENT = 5.0
INTERPOLATION_BURDEN_AVAILABLE = "available"
INTERPOLATION_BURDEN_UNAVAILABLE = "unavailable"
INTERPOLATION_BURDEN_DECISION_VERSION = "interpolation_burden_decision_v2"
_LEGACY_INTERPOLATION_BURDEN_DECISION_VERSION = (
    "interpolation_burden_decision_v1"
)
INTERPOLATION_BURDEN_DECISION_RETAIN = "retain"
INTERPOLATION_BURDEN_DECISION_EXCLUDE = "exclude"
INTERPOLATION_BURDEN_SCOPE_PARTICIPANT = "participant"
INTERPOLATION_BURDEN_SCOPE_RECORDING = "recording"
_INTERPOLATION_BURDEN_DECISIONS = frozenset(
    {
        INTERPOLATION_BURDEN_DECISION_RETAIN,
        INTERPOLATION_BURDEN_DECISION_EXCLUDE,
    }
)
_INTERPOLATION_BURDEN_SCOPES = frozenset(
    {
        INTERPOLATION_BURDEN_SCOPE_PARTICIPANT,
        INTERPOLATION_BURDEN_SCOPE_RECORDING,
    }
)


class InterpolationBurdenError(ValueError):
    """Raised when current burden evidence is internally inconsistent."""


def _fingerprint(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class InterpolationBurden:
    """One recording's confirmed interpolation burden and review status."""

    version: str
    status: str
    reason: str
    eligible_scalp_channels: tuple[str, ...]
    successfully_interpolated_channels: tuple[str, ...]
    percentage: float | None
    review_threshold_percent: float
    requires_review: bool
    outcome_version: str | None
    geometry_identity_fingerprint: str | None

    def __post_init__(self) -> None:
        if self.version != INTERPOLATION_BURDEN_VERSION:
            raise InterpolationBurdenError("Interpolation-burden version is stale.")
        if self.status not in {
            INTERPOLATION_BURDEN_AVAILABLE,
            INTERPOLATION_BURDEN_UNAVAILABLE,
        }:
            raise InterpolationBurdenError("Interpolation-burden status is invalid.")
        if self.review_threshold_percent != INTERPOLATION_BURDEN_REVIEW_THRESHOLD_PERCENT:
            raise InterpolationBurdenError("Interpolation-burden threshold is stale.")
        if self.status == INTERPOLATION_BURDEN_AVAILABLE:
            if not self.eligible_scalp_channels or self.percentage is None:
                raise InterpolationBurdenError(
                    "Available interpolation burden requires eligible channels and a percentage."
                )
            expected = (
                100.0
                * len(self.successfully_interpolated_channels)
                / len(self.eligible_scalp_channels)
            )
            if abs(float(self.percentage) - expected) > 1e-12:
                raise InterpolationBurdenError(
                    "Interpolation-burden percentage is inconsistent with its counts."
                )
            if self.requires_review != (
                expected > INTERPOLATION_BURDEN_REVIEW_THRESHOLD_PERCENT
            ):
                raise InterpolationBurdenError(
                    "Interpolation-burden review flag is inconsistent with its percentage."
                )
            unknown = set(self.successfully_interpolated_channels).difference(
                self.eligible_scalp_channels
            )
            if unknown:
                raise InterpolationBurdenError(
                    "Successfully interpolated channels fall outside the eligible scalp set."
                )
            if not self.geometry_identity_fingerprint or not self.outcome_version:
                raise InterpolationBurdenError(
                    "Available interpolation burden requires outcome and geometry provenance."
                )
        else:
            if not self.reason:
                raise InterpolationBurdenError(
                    "Unavailable interpolation burden requires a reason."
                )
            if self.percentage is not None or self.requires_review:
                raise InterpolationBurdenError(
                    "Unavailable interpolation burden cannot claim a percentage or review flag."
                )

    @property
    def numerator(self) -> int | None:
        if self.status != INTERPOLATION_BURDEN_AVAILABLE:
            return None
        return len(self.successfully_interpolated_channels)

    @property
    def denominator(self) -> int | None:
        if self.status != INTERPOLATION_BURDEN_AVAILABLE:
            return None
        return len(self.eligible_scalp_channels)

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "status": self.status,
            "reason": self.reason,
            "eligible_scalp_channels": list(self.eligible_scalp_channels),
            "successfully_interpolated_channels": list(
                self.successfully_interpolated_channels
            ),
            "numerator": self.numerator,
            "denominator": self.denominator,
            "percentage": self.percentage,
            "review_threshold_percent": self.review_threshold_percent,
            "requires_review": self.requires_review,
            "outcome_version": self.outcome_version,
            "geometry_identity_fingerprint": self.geometry_identity_fingerprint,
        }

    @property
    def fingerprint(self) -> str:
        return _fingerprint(self.canonical_payload())

    def to_payload(self) -> dict[str, Any]:
        payload = self.canonical_payload()
        payload["fingerprint"] = self.fingerprint
        return payload


@dataclass(frozen=True, slots=True)
class InterpolationBurdenCohortSummary:
    """Descriptive preprocessing-cohort burden; unavailable data stay missing."""

    recording_count: int
    contributing_recording_count: int
    unavailable_recording_count: int
    mean_percentage: float | None
    minimum_percentage: float | None
    maximum_percentage: float | None
    recordings_above_threshold: int
    review_threshold_percent: float = INTERPOLATION_BURDEN_REVIEW_THRESHOLD_PERCENT

    def to_payload(self) -> dict[str, object]:
        return {
            "recording_count": self.recording_count,
            "contributing_recording_count": self.contributing_recording_count,
            "unavailable_recording_count": self.unavailable_recording_count,
            "mean_percentage": self.mean_percentage,
            "minimum_percentage": self.minimum_percentage,
            "maximum_percentage": self.maximum_percentage,
            "recordings_above_threshold": self.recordings_above_threshold,
            "review_threshold_percent": self.review_threshold_percent,
        }


@dataclass(frozen=True, slots=True)
class InterpolationBurdenReviewFinding:
    """One non-excluding manual-review prompt for an above-threshold recording."""

    recording_id: str
    burden_fingerprint: str
    successfully_interpolated_channels: tuple[str, ...]
    numerator: int
    denominator: int
    percentage: float
    message: str


@dataclass(frozen=True, slots=True)
class InterpolationBurdenReviewDecision:
    """Audited downstream decision for one exact burden finding."""

    version: str
    decision: str
    processing_id: str
    participant_id: str
    reason: str
    burden_fingerprint: str
    reviewed_at_utc: str
    reviewer_identity: str | None
    reviewer_identity_status: str
    exclusion_scope: str
    owns_canonical_exclusion: bool

    def __post_init__(self) -> None:
        if self.version != INTERPOLATION_BURDEN_DECISION_VERSION:
            raise InterpolationBurdenError("Interpolation-burden decision is stale.")
        if self.decision not in _INTERPOLATION_BURDEN_DECISIONS:
            raise InterpolationBurdenError("Interpolation-burden decision is invalid.")
        if self.exclusion_scope not in _INTERPOLATION_BURDEN_SCOPES:
            raise InterpolationBurdenError(
                "Interpolation-burden exclusion scope is invalid."
            )
        if (
            self.decision != INTERPOLATION_BURDEN_DECISION_EXCLUDE
            and self.owns_canonical_exclusion
        ):
            raise InterpolationBurdenError(
                "Only an exclusion decision can own a canonical exclusion."
            )
        if not self.processing_id.strip() or not self.participant_id.strip():
            raise InterpolationBurdenError(
                "Interpolation-burden decision requires recording and participant identity."
            )
        if not self.reason.strip():
            raise InterpolationBurdenError(
                "Interpolation-burden decision requires a reason."
            )
        if len(self.burden_fingerprint) != 64:
            raise InterpolationBurdenError(
                "Interpolation-burden decision requires an evidence fingerprint."
            )
        try:
            reviewed_at = datetime.fromisoformat(
                self.reviewed_at_utc.replace("Z", "+00:00")
            )
        except ValueError as exc:
            raise InterpolationBurdenError(
                "Interpolation-burden review time is invalid."
            ) from exc
        if reviewed_at.tzinfo is None:
            raise InterpolationBurdenError(
                "Interpolation-burden review time must include a timezone."
            )
        if self.reviewer_identity is None:
            if self.reviewer_identity_status != "not_collected":
                raise InterpolationBurdenError(
                    "Missing reviewer identity must be labeled not_collected."
                )
        elif self.reviewer_identity_status != "collected":
            raise InterpolationBurdenError(
                "Recorded reviewer identity must be labeled collected."
            )

    def canonical_payload(self) -> dict[str, object]:
        return {
            "version": self.version,
            "decision": self.decision,
            "processing_id": self.processing_id,
            "participant_id": self.participant_id,
            "reason": self.reason,
            "burden_fingerprint": self.burden_fingerprint,
            "reviewed_at_utc": self.reviewed_at_utc,
            "reviewer_identity": self.reviewer_identity,
            "reviewer_identity_status": self.reviewer_identity_status,
            "exclusion_scope": self.exclusion_scope,
            "owns_canonical_exclusion": self.owns_canonical_exclusion,
        }

    @property
    def fingerprint(self) -> str:
        return _fingerprint(self.canonical_payload())

    def to_payload(self) -> dict[str, object]:
        payload = self.canonical_payload()
        payload["fingerprint"] = self.fingerprint
        return payload


def _unavailable(
    reason: str,
    *,
    outcome: PreprocessingOutcome,
    geometry_fingerprint: str | None = None,
) -> InterpolationBurden:
    return InterpolationBurden(
        version=INTERPOLATION_BURDEN_VERSION,
        status=INTERPOLATION_BURDEN_UNAVAILABLE,
        reason=reason,
        eligible_scalp_channels=(),
        successfully_interpolated_channels=(),
        percentage=None,
        review_threshold_percent=INTERPOLATION_BURDEN_REVIEW_THRESHOLD_PERCENT,
        requires_review=False,
        outcome_version=outcome.outcome_version,
        geometry_identity_fingerprint=geometry_fingerprint,
    )


def build_interpolation_burden(
    preprocessing_outcome: PreprocessingOutcome | Mapping[str, Any] | None,
    geometry_identity: Mapping[str, Any] | None,
) -> InterpolationBurden:
    """Calculate burden only from current confirmed success and valid geometry."""

    outcome = normalize_preprocessing_outcome(preprocessing_outcome)
    if not outcome.is_current:
        return _unavailable(
            "Confirmed interpolation outcome was not recorded for this legacy result.",
            outcome=outcome,
        )
    if outcome.interpolation_status not in {
        INTERPOLATION_STATUS_SUCCEEDED,
        INTERPOLATION_STATUS_NOT_NEEDED,
    }:
        return _unavailable(
            "Interpolation did not finish with a confirmed successful or not-needed outcome.",
            outcome=outcome,
        )
    if not isinstance(geometry_identity, Mapping):
        return _unavailable(
            "Eligible BioSemi64 scalp-channel provenance was not recorded.",
            outcome=outcome,
        )
    raw_retained = geometry_identity.get("retained_scalp_channels")
    if not isinstance(raw_retained, list):
        return _unavailable(
            "Eligible BioSemi64 scalp-channel provenance was not recorded.",
            outcome=outcome,
        )
    try:
        canonical_geometry = biosemi64_geometry_identity(
            electrode_mapping_profile=geometry_identity.get(
                "electrode_mapping_profile"
            ),
            retained_channels=raw_retained,
        )
    except BioSemi64GeometryError:
        return _unavailable(
            "Eligible BioSemi64 scalp-channel provenance is invalid.",
            outcome=outcome,
        )
    if dict(geometry_identity) != canonical_geometry:
        return _unavailable(
            "Eligible BioSemi64 scalp-channel provenance is stale.",
            outcome=outcome,
        )

    eligible = tuple(str(value) for value in canonical_geometry["retained_scalp_channels"])
    successful_lookup = {
        value.casefold(): value
        for value in outcome.interpolation_successful_channels
    }
    eligible_by_case = {value.casefold(): value for value in eligible}
    unknown = set(successful_lookup).difference(eligible_by_case)
    if unknown:
        return _unavailable(
            "Confirmed interpolation includes a channel outside the eligible scalp set.",
            outcome=outcome,
            geometry_fingerprint=str(
                canonical_geometry["geometry_identity_fingerprint"]
            ),
        )
    successful = tuple(
        channel for channel in eligible if channel.casefold() in successful_lookup
    )
    percentage = 100.0 * len(successful) / len(eligible)
    return InterpolationBurden(
        version=INTERPOLATION_BURDEN_VERSION,
        status=INTERPOLATION_BURDEN_AVAILABLE,
        reason="",
        eligible_scalp_channels=eligible,
        successfully_interpolated_channels=successful,
        percentage=percentage,
        review_threshold_percent=INTERPOLATION_BURDEN_REVIEW_THRESHOLD_PERCENT,
        requires_review=(
            percentage > INTERPOLATION_BURDEN_REVIEW_THRESHOLD_PERCENT
        ),
        outcome_version=outcome.outcome_version,
        geometry_identity_fingerprint=str(
            canonical_geometry["geometry_identity_fingerprint"]
        ),
    )


def normalize_interpolation_burden(
    value: Mapping[str, Any],
) -> InterpolationBurden:
    """Validate a ledger burden payload and its evidence fingerprint."""

    if not isinstance(value, Mapping):
        raise InterpolationBurdenError(
            "Interpolation-burden evidence must be an object."
        )

    def _channels(field_name: str) -> tuple[str, ...]:
        raw_channels = value.get(field_name)
        if not isinstance(raw_channels, list):
            raise InterpolationBurdenError(
                f"Interpolation-burden {field_name} must be a list."
            )
        channels = tuple(str(channel).strip() for channel in raw_channels)
        if any(not channel for channel in channels):
            raise InterpolationBurdenError(
                f"Interpolation-burden {field_name} contains a blank channel."
            )
        if len({channel.casefold() for channel in channels}) != len(channels):
            raise InterpolationBurdenError(
                f"Interpolation-burden {field_name} contains duplicate channels."
            )
        return channels

    raw_requires_review = value.get("requires_review")
    if not isinstance(raw_requires_review, bool):
        raise InterpolationBurdenError(
            "Interpolation-burden review status must be true or false."
        )
    raw_percentage = value.get("percentage")
    try:
        percentage = (
            None if raw_percentage is None else float(raw_percentage)
        )
        burden = InterpolationBurden(
            version=str(value["version"]),
            status=str(value["status"]),
            reason=str(value.get("reason") or ""),
            eligible_scalp_channels=_channels("eligible_scalp_channels"),
            successfully_interpolated_channels=_channels(
                "successfully_interpolated_channels"
            ),
            percentage=percentage,
            review_threshold_percent=float(value["review_threshold_percent"]),
            requires_review=raw_requires_review,
            outcome_version=(
                str(value["outcome_version"])
                if value.get("outcome_version") is not None
                else None
            ),
            geometry_identity_fingerprint=(
                str(value["geometry_identity_fingerprint"])
                if value.get("geometry_identity_fingerprint") is not None
                else None
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, InterpolationBurdenError):
            raise
        raise InterpolationBurdenError(
            "Interpolation-burden evidence is malformed."
        ) from exc

    if value.get("numerator") != burden.numerator:
        raise InterpolationBurdenError(
            "Interpolation-burden numerator is inconsistent with its channels."
        )
    if value.get("denominator") != burden.denominator:
        raise InterpolationBurdenError(
            "Interpolation-burden denominator is inconsistent with its channels."
        )
    if str(value.get("fingerprint") or "") != burden.fingerprint:
        raise InterpolationBurdenError(
            "Interpolation-burden evidence fingerprint is stale."
        )
    return burden


def summarize_interpolation_burdens(
    burdens: Sequence[InterpolationBurden],
) -> InterpolationBurdenCohortSummary:
    """Summarize each supplied recording once without zero-filling unavailable data."""

    values = [
        float(item.percentage)
        for item in burdens
        if item.status == INTERPOLATION_BURDEN_AVAILABLE
        and item.percentage is not None
    ]
    return InterpolationBurdenCohortSummary(
        recording_count=len(burdens),
        contributing_recording_count=len(values),
        unavailable_recording_count=len(burdens) - len(values),
        mean_percentage=(sum(values) / len(values) if values else None),
        minimum_percentage=(min(values) if values else None),
        maximum_percentage=(max(values) if values else None),
        recordings_above_threshold=sum(item.requires_review for item in burdens),
    )


def interpolation_burden_review_finding(
    recording_id: object,
    burden: InterpolationBurden,
) -> InterpolationBurdenReviewFinding | None:
    """Return a concise review finding; the finding itself never excludes data."""

    identity = str(recording_id or "").strip()
    if not identity:
        raise InterpolationBurdenError("A recording identity is required for review.")
    if not burden.requires_review:
        return None
    if burden.numerator is None or burden.denominator is None or burden.percentage is None:
        raise InterpolationBurdenError(
            "A review finding requires an available interpolation burden."
        )
    return InterpolationBurdenReviewFinding(
        recording_id=identity,
        burden_fingerprint=burden.fingerprint,
        successfully_interpolated_channels=(
            burden.successfully_interpolated_channels
        ),
        numerator=burden.numerator,
        denominator=burden.denominator,
        percentage=burden.percentage,
        message=(
            f"{burden.numerator} of {burden.denominator} scalp electrodes were "
            f"interpolated ({burden.percentage:.2f}%). Review this recording "
            "before deciding whether to include it."
        ),
    )


def build_interpolation_burden_review_decision(
    finding: InterpolationBurdenReviewFinding,
    *,
    participant_id: object,
    decision: str,
    reason: object = None,
    reviewed_at_utc: str | None = None,
    reviewer_identity: str | None = None,
    exclusion_scope: str | None = None,
    owns_canonical_exclusion: bool = False,
) -> InterpolationBurdenReviewDecision:
    """Create a decision tied to the exact evidence shown in the GUI."""

    normalized_identity = (
        str(reviewer_identity).strip() if reviewer_identity is not None else None
    )
    if not normalized_identity:
        normalized_identity = None
    normalized_participant_id = str(participant_id or "").strip()
    normalized_scope = str(exclusion_scope or "").strip().casefold()
    if not normalized_scope:
        normalized_scope = (
            INTERPOLATION_BURDEN_SCOPE_PARTICIPANT
            if finding.recording_id.casefold() == normalized_participant_id.casefold()
            else INTERPOLATION_BURDEN_SCOPE_RECORDING
        )
    return InterpolationBurdenReviewDecision(
        version=INTERPOLATION_BURDEN_DECISION_VERSION,
        decision=str(decision or "").strip().casefold(),
        processing_id=finding.recording_id,
        participant_id=normalized_participant_id,
        reason=str(reason or "").strip() or "No reason provided",
        burden_fingerprint=finding.burden_fingerprint,
        reviewed_at_utc=(
            reviewed_at_utc
            or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        ),
        reviewer_identity=normalized_identity,
        reviewer_identity_status=(
            "collected" if normalized_identity is not None else "not_collected"
        ),
        exclusion_scope=normalized_scope,
        owns_canonical_exclusion=bool(owns_canonical_exclusion),
    )


def normalize_interpolation_burden_review_decision(
    value: Mapping[str, Any],
) -> InterpolationBurdenReviewDecision:
    """Validate a stored decision and its self-fingerprint."""

    if not isinstance(value, Mapping):
        raise InterpolationBurdenError(
            "Interpolation-burden decision must be an object."
        )
    raw_version = str(value.get("version") or "")
    if raw_version == _LEGACY_INTERPOLATION_BURDEN_DECISION_VERSION:
        legacy_keys = (
            "version",
            "decision",
            "processing_id",
            "participant_id",
            "reason",
            "burden_fingerprint",
            "reviewed_at_utc",
            "reviewer_identity",
            "reviewer_identity_status",
        )
        try:
            legacy_payload = {key: value[key] for key in legacy_keys}
        except KeyError as exc:
            raise InterpolationBurdenError(
                "Interpolation-burden decision is malformed."
            ) from exc
        if str(value.get("fingerprint") or "") != _fingerprint(legacy_payload):
            raise InterpolationBurdenError(
                "Interpolation-burden decision fingerprint is stale."
            )
        participant_id = str(value["participant_id"])
        processing_id = str(value["processing_id"])
        value = {
            **legacy_payload,
            "version": INTERPOLATION_BURDEN_DECISION_VERSION,
            "exclusion_scope": (
                INTERPOLATION_BURDEN_SCOPE_PARTICIPANT
                if participant_id.casefold() == processing_id.casefold()
                else INTERPOLATION_BURDEN_SCOPE_RECORDING
            ),
            # V1 did not establish whether QC-07 created an exclusion-list entry,
            # so migration must never claim authority to remove one.
            "owns_canonical_exclusion": False,
        }

    raw_ownership = value.get("owns_canonical_exclusion")
    if not isinstance(raw_ownership, bool):
        raise InterpolationBurdenError(
            "Interpolation-burden exclusion ownership must be true or false."
        )
    try:
        decision = InterpolationBurdenReviewDecision(
            version=str(value["version"]),
            decision=str(value["decision"]),
            processing_id=str(value["processing_id"]),
            participant_id=str(value["participant_id"]),
            reason=str(value["reason"]),
            burden_fingerprint=str(value["burden_fingerprint"]),
            reviewed_at_utc=str(value["reviewed_at_utc"]),
            reviewer_identity=(
                str(value["reviewer_identity"])
                if value.get("reviewer_identity") is not None
                else None
            ),
            reviewer_identity_status=str(value["reviewer_identity_status"]),
            exclusion_scope=str(value["exclusion_scope"]),
            owns_canonical_exclusion=raw_ownership,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise InterpolationBurdenError(
            "Interpolation-burden decision is malformed."
        ) from exc
    if (
        raw_version != _LEGACY_INTERPOLATION_BURDEN_DECISION_VERSION
        and str(value.get("fingerprint") or "") != decision.fingerprint
    ):
        raise InterpolationBurdenError(
            "Interpolation-burden decision fingerprint is stale."
        )
    return decision


def interpolation_burden_decision_is_current(
    finding: InterpolationBurdenReviewFinding,
    decision: InterpolationBurdenReviewDecision | Mapping[str, Any],
) -> bool:
    """Return whether a reviewed decision covers this exact finding."""

    normalized = (
        decision
        if isinstance(decision, InterpolationBurdenReviewDecision)
        else normalize_interpolation_burden_review_decision(decision)
    )
    return (
        normalized.processing_id.casefold() == finding.recording_id.casefold()
        and normalized.burden_fingerprint == finding.burden_fingerprint
    )


__all__ = [
    "INTERPOLATION_BURDEN_AVAILABLE",
    "INTERPOLATION_BURDEN_DECISION_EXCLUDE",
    "INTERPOLATION_BURDEN_DECISION_RETAIN",
    "INTERPOLATION_BURDEN_DECISION_VERSION",
    "INTERPOLATION_BURDEN_REVIEW_THRESHOLD_PERCENT",
    "INTERPOLATION_BURDEN_SCOPE_PARTICIPANT",
    "INTERPOLATION_BURDEN_SCOPE_RECORDING",
    "INTERPOLATION_BURDEN_UNAVAILABLE",
    "INTERPOLATION_BURDEN_VERSION",
    "InterpolationBurden",
    "InterpolationBurdenCohortSummary",
    "InterpolationBurdenError",
    "InterpolationBurdenReviewDecision",
    "InterpolationBurdenReviewFinding",
    "build_interpolation_burden",
    "build_interpolation_burden_review_decision",
    "interpolation_burden_decision_is_current",
    "interpolation_burden_review_finding",
    "normalize_interpolation_burden_review_decision",
    "normalize_interpolation_burden",
    "summarize_interpolation_burdens",
]
