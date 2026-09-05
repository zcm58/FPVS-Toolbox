"""Versioned kurtosis evidence and interpolation-decision authority.

This module owns the GUI-neutral QC-16 contract.  It deliberately separates
the numerical screen from corroboration, review, and interpolation.  The
initial eligible-corroborator registry is empty, so a current kurtosis finding
cannot authorize interpolation without an explicit, current GUI receipt.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any
import warnings

import numpy as np
from scipy.stats import kurtosis

from Main_App.io.eeg_geometry import (
    BIOSEMI64_CHANNELS,
    BIOSEMI64_CHANNEL_SET,
    BIOSEMI64_COORDINATE_FINGERPRINT,
    BIOSEMI64_GEOMETRY_VERSION,
    BIOSEMI64_MONTAGE_ID,
    biosemi64_geometry_identity,
)
from Main_App.processing.analysis_spans import (
    ANALYSIS_SPAN_PLAN_VERSION,
    TARGET_SPAN_ROUNDING_VERSION,
    merge_relative_spans,
)

KURTOSIS_QC_METHOD_VERSION = "eeglab_inspired_trimmed_kurtosis_v1"
KURTOSIS_AUTHORITY_POLICY_VERSION = "kurtosis_review_or_corroboration_v1"
KURTOSIS_CORROBORATOR_REGISTRY_VERSION = "kurtosis_corroborators_v1_empty"
KURTOSIS_REVIEW_DECISION_SCHEMA_VERSION = "kurtosis_review_decision_v1"
LEGACY_KURTOSIS_METHOD_VERSION = "legacy_fpvs_kurtosis_auto_v0"

KURTOSIS_TRIM_FRACTION = 0.10
KURTOSIS_MIN_VALID_REFERENCE_CHANNELS = 16
KURTOSIS_MIN_SAMPLES_PER_CHANNEL = 4
KURTOSIS_MIN_REFERENCE_SCALE = 1e-12

EVIDENCE_STATUS_VALID = "valid"
EVIDENCE_STATUS_PARTIAL = "partially_valid"
EVIDENCE_STATUS_UNAVAILABLE = "unavailable"

CHANNEL_VALIDITY_VALID = "valid"
CHANNEL_VALIDITY_NONFINITE_INPUT = "nonfinite_input"
CHANNEL_VALIDITY_UNDEFINED_STATISTIC = "undefined_kurtosis"
CHANNEL_VALIDITY_REFERENCE_UNAVAILABLE = "reference_unavailable"

KURTOSIS_DECISION_APPROVE = "approve_interpolation"
KURTOSIS_DECISION_REJECT = "reject_interpolation"
KURTOSIS_REVIEWER_STATE_EXPLICIT_GUI = "explicit_gui_review"
KURTOSIS_REVIEWER_STATE_EXPERIMENTAL_AUTO = "gui_enabled_experimental_abs_z_gt_10_v1"
KURTOSIS_REVIEWER_STATE_EXPERIMENTAL_AUTO_ALL = "gui_enabled_experimental_all_flags_v1"
KURTOSIS_NO_REASON_PROVIDED = "No reason provided"
KURTOSIS_EXPERIMENTAL_AUTO_Z_THRESHOLD = 10.0
KURTOSIS_REVIEWER_IDENTITY_STATUS_NOT_COLLECTED = "not_collected"
KURTOSIS_REVIEWER_IDENTITY_STATUS_PROVIDED = "provided"

CORROBORATOR_SCOPE_RECORDING_UNION = "recording_analyzed_interval_union"
CORROBORATOR_AUTHORITY_ELIGIBLE = "eligible_for_automatic_interpolation"
CORROBORATOR_AUTHORITY_REVIEW_ONLY = "review_only"

CHANNEL_DECISION_CLEAR = "not_flagged"
CHANNEL_DECISION_REVIEW_REQUIRED = "review_required"
CHANNEL_DECISION_CORROBORATED_AUTO = "corroborated_automatic"
CHANNEL_DECISION_EXPERIMENTAL_AUTO = "experimental_automatic"
CHANNEL_DECISION_USER_APPROVED = "user_approved"
CHANNEL_DECISION_USER_REJECTED = "user_rejected"
CHANNEL_DECISION_DIRECT = "confirmed_manual_or_physical"
CHANNEL_DECISION_EVALUATION_UNAVAILABLE = "evaluation_unavailable"


class KurtosisQCError(ValueError):
    """Raised when QC-16 inputs or a persisted decision are invalid."""


def _fingerprint(value: Mapping[str, Any]) -> str:
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise KurtosisQCError("Kurtosis evidence contains non-JSON or nonfinite provenance.") from exc
    return hashlib.sha256(encoded).hexdigest()


def _is_sha256(value: object) -> bool:
    text = str(value or "").strip().casefold()
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text)


def _canonical_json_mapping(value: Mapping[str, Any], *, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or not value:
        raise KurtosisQCError(f"{field_name} must be a nonempty object.")
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        result = json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise KurtosisQCError(f"{field_name} must contain JSON-safe finite values.") from exc
    if not isinstance(result, dict) or not result:
        raise KurtosisQCError(f"{field_name} must be a nonempty object.")
    return result


def _positive_finite(value: object, *, field_name: str) -> float:
    if isinstance(value, bool):
        raise KurtosisQCError(f"{field_name} must be a positive finite number.")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise KurtosisQCError(f"{field_name} must be a positive finite number.") from exc
    if not math.isfinite(number) or number <= 0.0:
        raise KurtosisQCError(f"{field_name} must be a positive finite number.")
    return number


def _integer(value: object, *, field_name: str, minimum: int | None = None) -> int:
    if isinstance(value, bool):
        raise KurtosisQCError(f"{field_name} must be an integer.")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise KurtosisQCError(f"{field_name} must be an integer.") from exc
    if number != value or (minimum is not None and number < minimum):
        qualifier = f" greater than or equal to {minimum}" if minimum is not None else ""
        raise KurtosisQCError(f"{field_name} must be an integer{qualifier}.")
    return number


def _canonical_channels(values: Sequence[object], *, field_name: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, bytearray)):
        raise KurtosisQCError(f"{field_name} must be a sequence of BioSemi64 channels.")
    names = tuple(str(value or "").strip() for value in values)
    if any(not name for name in names):
        raise KurtosisQCError(f"{field_name} contains a blank channel.")
    if len({name.casefold() for name in names}) != len(names):
        raise KurtosisQCError(f"{field_name} contains duplicate channels.")
    unknown = sorted(set(names).difference(BIOSEMI64_CHANNEL_SET))
    if unknown:
        raise KurtosisQCError(
            f"{field_name} contains channels outside BioSemi64: {', '.join(unknown)}."
        )
    selected = set(names)
    return tuple(channel for channel in BIOSEMI64_CHANNELS if channel in selected)


@dataclass(frozen=True, slots=True)
class KurtosisOccurrenceScope:
    condition_label: str
    condition_code: int
    repetition_index: int
    occurrence_key: str
    marker_plan_fingerprint: str
    approved_span_fingerprint: str
    marker_disposition: str
    source_start_sample: int
    source_stop_sample: int
    target_start_sample: int
    target_stop_sample: int
    source_span_fingerprint: str
    target_span_fingerprint: str

    def to_payload(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class KurtosisScoringScope:
    plan_version: str
    rounding_version: str
    analysis_span_fingerprint: str
    source_plan_fingerprint: str
    target_sampling_rate_hz: float
    target_first_samp: int
    target_n_times: int
    unique_sample_count: int
    occurrences: tuple[KurtosisOccurrenceScope, ...]

    @property
    def occurrence_keys(self) -> tuple[str, ...]:
        return tuple(item.occurrence_key for item in self.occurrences)

    def to_payload(self) -> dict[str, object]:
        return {
            "plan_version": self.plan_version,
            "rounding_version": self.rounding_version,
            "analysis_span_fingerprint": self.analysis_span_fingerprint,
            "source_plan_fingerprint": self.source_plan_fingerprint,
            "target_sampling_rate_hz": self.target_sampling_rate_hz,
            "target_first_samp": self.target_first_samp,
            "target_n_times": self.target_n_times,
            "unique_sample_count": self.unique_sample_count,
            "occurrences": [item.to_payload() for item in self.occurrences],
        }


def scoring_scope_from_realized_plan(
    value: Mapping[str, Any],
    *,
    expected_sample_count: int,
) -> KurtosisScoringScope:
    """Validate and reduce a realized QC-06 plan to QC-16 scope evidence."""

    if not isinstance(value, Mapping):
        raise KurtosisQCError("Realized analysis-span plan must be an object.")
    if value.get("version") != ANALYSIS_SPAN_PLAN_VERSION:
        raise KurtosisQCError("Realized analysis-span plan version is missing or stale.")
    if value.get("rounding_version") != TARGET_SPAN_ROUNDING_VERSION:
        raise KurtosisQCError("Realized analysis-span rounding version is missing or stale.")
    supplied_fingerprint = str(value.get("fingerprint") or "")
    expected_fingerprint = _fingerprint(
        {key: item for key, item in value.items() if key != "fingerprint"}
    )
    if supplied_fingerprint != expected_fingerprint:
        raise KurtosisQCError("Realized analysis-span fingerprint is missing or stale.")
    source_fingerprint = str(value.get("source_plan_fingerprint") or "")
    if not _is_sha256(source_fingerprint):
        raise KurtosisQCError("Realized analysis-span source fingerprint is malformed.")

    target_grid = value.get("target_grid")
    if not isinstance(target_grid, Mapping):
        raise KurtosisQCError("Realized analysis-span target grid is malformed.")
    sampling_rate = _positive_finite(
        target_grid.get("sfreq_hz"), field_name="target_grid.sfreq_hz"
    )
    n_times = _integer(target_grid.get("n_times"), field_name="target_grid.n_times", minimum=1)
    first_samp = _integer(target_grid.get("first_samp"), field_name="target_grid.first_samp")

    raw_spans = value.get("spans")
    if not isinstance(raw_spans, Sequence) or isinstance(raw_spans, (str, bytes)) or not raw_spans:
        raise KurtosisQCError("Realized analysis-span plan must contain occurrence spans.")
    occurrences: list[KurtosisOccurrenceScope] = []
    seen_keys: set[str] = set()
    relative_spans: list[tuple[int, int]] = []
    for index, raw_span in enumerate(raw_spans):
        if not isinstance(raw_span, Mapping):
            raise KurtosisQCError(f"Analysis occurrence {index} is malformed.")
        span_fingerprint = str(raw_span.get("fingerprint") or "")
        expected_span_fingerprint = _fingerprint(
            {key: item for key, item in raw_span.items() if key != "fingerprint"}
        )
        if span_fingerprint != expected_span_fingerprint:
            raise KurtosisQCError(f"Analysis occurrence {index} fingerprint is stale.")
        occurrence_key = str(raw_span.get("occurrence_key") or "").strip()
        if not occurrence_key or occurrence_key in seen_keys:
            raise KurtosisQCError("Analysis occurrence keys must be nonempty and unique.")
        seen_keys.add(occurrence_key)
        condition_label = str(raw_span.get("condition_label") or "").strip()
        if not condition_label:
            raise KurtosisQCError(
                f"Analysis occurrence {occurrence_key} has no condition label."
            )
        marker_plan_fingerprint = str(
            raw_span.get("marker_plan_fingerprint") or ""
        )
        approved_span_fingerprint = str(
            raw_span.get("approved_span_fingerprint") or ""
        )
        if not _is_sha256(marker_plan_fingerprint) or not _is_sha256(
            approved_span_fingerprint
        ):
            raise KurtosisQCError(
                f"Analysis occurrence {occurrence_key} crop provenance is malformed."
            )
        marker_disposition = str(raw_span.get("marker_disposition") or "").strip()
        if not marker_disposition:
            raise KurtosisQCError(
                f"Analysis occurrence {occurrence_key} has no marker disposition."
            )
        target = raw_span.get("target_coordinates")
        source = raw_span.get("source_coordinates")
        if not isinstance(target, Mapping) or not isinstance(source, Mapping):
            raise KurtosisQCError(f"Analysis occurrence {occurrence_key} has malformed coordinates.")
        start_relative = _integer(
            target.get("start_relative_sample"),
            field_name=f"{occurrence_key}.target_start_relative",
            minimum=0,
        )
        stop_relative = _integer(
            target.get("stop_relative_sample"),
            field_name=f"{occurrence_key}.target_stop_relative",
            minimum=1,
        )
        if stop_relative <= start_relative or stop_relative > n_times:
            raise KurtosisQCError(f"Analysis occurrence {occurrence_key} is outside the target grid.")
        target_start = _integer(
            target.get("start_sample"), field_name=f"{occurrence_key}.target_start"
        )
        target_stop = _integer(
            target.get("stop_sample"), field_name=f"{occurrence_key}.target_stop"
        )
        if target_start != first_samp + start_relative or target_stop != first_samp + stop_relative:
            raise KurtosisQCError(
                f"Analysis occurrence {occurrence_key} target coordinates disagree."
            )
        source_start = _integer(
            source.get("start_sample"), field_name=f"{occurrence_key}.source_start"
        )
        source_stop = _integer(
            source.get("stop_sample"), field_name=f"{occurrence_key}.source_stop"
        )
        if source_stop <= source_start:
            raise KurtosisQCError(f"Analysis occurrence {occurrence_key} has an empty source span.")
        source_span_fingerprint = str(raw_span.get("source_span_fingerprint") or "")
        if not _is_sha256(source_span_fingerprint):
            raise KurtosisQCError(
                f"Analysis occurrence {occurrence_key} source fingerprint is malformed."
            )
        occurrences.append(
            KurtosisOccurrenceScope(
                condition_label=condition_label,
                condition_code=_integer(
                    raw_span.get("condition_code"),
                    field_name=f"{occurrence_key}.condition_code",
                ),
                repetition_index=_integer(
                    raw_span.get("repetition_index"),
                    field_name=f"{occurrence_key}.repetition_index",
                    minimum=0,
                ),
                occurrence_key=occurrence_key,
                marker_plan_fingerprint=marker_plan_fingerprint,
                approved_span_fingerprint=approved_span_fingerprint,
                marker_disposition=marker_disposition,
                source_start_sample=source_start,
                source_stop_sample=source_stop,
                target_start_sample=target_start,
                target_stop_sample=target_stop,
                source_span_fingerprint=source_span_fingerprint,
                target_span_fingerprint=span_fingerprint,
            )
        )
        relative_spans.append((start_relative, stop_relative))

    merged = merge_relative_spans(relative_spans, n_times=n_times)
    supplied_unique = value.get("unique_relative_spans")
    try:
        normalized_unique = merge_relative_spans(supplied_unique, n_times=n_times)
    except (TypeError, ValueError) as exc:
        raise KurtosisQCError("Realized analysis-span unique coverage is malformed.") from exc
    if normalized_unique != merged:
        raise KurtosisQCError("Realized analysis-span unique coverage disagrees with occurrences.")
    unique_sample_count = sum(stop - start for start, stop in merged)
    if _integer(
        value.get("unique_sample_count"),
        field_name="unique_sample_count",
        minimum=1,
    ) != unique_sample_count:
        raise KurtosisQCError("Realized analysis-span sample count is stale.")
    if _integer(expected_sample_count, field_name="expected_sample_count", minimum=1) != unique_sample_count:
        raise KurtosisQCError(
            "Kurtosis data sample count does not match the realized analyzed intervals."
        )
    return KurtosisScoringScope(
        plan_version=ANALYSIS_SPAN_PLAN_VERSION,
        rounding_version=TARGET_SPAN_ROUNDING_VERSION,
        analysis_span_fingerprint=supplied_fingerprint,
        source_plan_fingerprint=source_fingerprint,
        target_sampling_rate_hz=sampling_rate,
        target_first_samp=first_samp,
        target_n_times=n_times,
        unique_sample_count=unique_sample_count,
        occurrences=tuple(occurrences),
    )


@dataclass(frozen=True, slots=True)
class KurtosisCorroboratorMethod:
    method_id: str
    method_version: str
    approval_reference: str
    required_scope: str = CORROBORATOR_SCOPE_RECORDING_UNION

    def __post_init__(self) -> None:
        for field_name in ("method_id", "method_version", "approval_reference"):
            if not str(getattr(self, field_name) or "").strip():
                raise KurtosisQCError(f"Corroborator {field_name} must not be empty.")
        if self.required_scope != CORROBORATOR_SCOPE_RECORDING_UNION:
            raise KurtosisQCError("QC-16 corroborators must use the full analyzed recording union.")

    def to_payload(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class KurtosisCorroboratorRegistry:
    version: str
    methods: tuple[KurtosisCorroboratorMethod, ...] = ()

    def __post_init__(self) -> None:
        if not str(self.version or "").strip():
            raise KurtosisQCError("Corroborator registry version must not be empty.")
        if not isinstance(self.methods, tuple) or any(
            not isinstance(item, KurtosisCorroboratorMethod) for item in self.methods
        ):
            raise KurtosisQCError("Corroborator registry methods must be a tuple of definitions.")
        identities = [(item.method_id, item.method_version) for item in self.methods]
        if len(set(identities)) != len(identities):
            raise KurtosisQCError("Corroborator registry contains duplicate method identities.")

    @property
    def fingerprint(self) -> str:
        return _fingerprint(self._identity_payload())

    def _identity_payload(self) -> dict[str, object]:
        return {
            "version": self.version,
            "methods": [item.to_payload() for item in self.methods],
        }

    def to_payload(self) -> dict[str, object]:
        return {**self._identity_payload(), "fingerprint": self.fingerprint}


CURRENT_KURTOSIS_CORROBORATOR_REGISTRY = KurtosisCorroboratorRegistry(
    version=KURTOSIS_CORROBORATOR_REGISTRY_VERSION,
    methods=(),
)
ELIGIBLE_KURTOSIS_CORROBORATORS = CURRENT_KURTOSIS_CORROBORATOR_REGISTRY.methods


@dataclass(frozen=True, slots=True)
class KurtosisReferenceDistribution:
    status: str
    reason: str | None
    finite_channel_count: int
    invalid_channel_count: int
    trim_fraction: float
    trim_count_per_tail: int
    minimum_valid_channels: int
    included_channels: tuple[str, ...]
    included_raw_kurtosis: tuple[float, ...]
    trimmed_low_channels: tuple[str, ...]
    trimmed_high_channels: tuple[str, ...]
    mean: float | None
    population_sd: float | None
    minimum_scale: float

    @property
    def fingerprint(self) -> str:
        return _fingerprint(self._identity_payload())

    def _identity_payload(self) -> dict[str, object]:
        return {
            "status": self.status,
            "reason": self.reason,
            "finite_channel_count": self.finite_channel_count,
            "invalid_channel_count": self.invalid_channel_count,
            "trim_fraction": self.trim_fraction,
            "trim_count_per_tail": self.trim_count_per_tail,
            "minimum_valid_channels": self.minimum_valid_channels,
            "included_channels": list(self.included_channels),
            "included_raw_kurtosis": list(self.included_raw_kurtosis),
            "trimmed_low_channels": list(self.trimmed_low_channels),
            "trimmed_high_channels": list(self.trimmed_high_channels),
            "mean": self.mean,
            "population_sd": self.population_sd,
            "minimum_scale": self.minimum_scale,
        }

    def to_payload(self) -> dict[str, object]:
        return {**self._identity_payload(), "fingerprint": self.fingerprint}


@dataclass(frozen=True, slots=True)
class KurtosisChannelEvidence:
    channel: str
    raw_kurtosis: float | None
    signed_z: float | None
    absolute_z: float | None
    threshold: float
    exceeds_threshold: bool
    input_sample_count: int
    input_finite: bool
    validity: str
    validity_reason: str | None
    reference_fingerprint: str
    evidence_context_fingerprint: str

    @property
    def fingerprint(self) -> str:
        return _fingerprint(self._identity_payload())

    def _identity_payload(self) -> dict[str, object]:
        return asdict(self)

    def to_payload(self) -> dict[str, object]:
        return {**self._identity_payload(), "fingerprint": self.fingerprint}


@dataclass(frozen=True, slots=True)
class KurtosisQCEvidence:
    method_version: str
    method_label: str
    authority_policy_version: str
    corroborator_registry_version: str
    corroborator_registry_fingerprint: str
    threshold: float
    scoring_scope: KurtosisScoringScope
    filter_identity: Mapping[str, Any]
    downsample_identity: Mapping[str, Any]
    geometry_identity: Mapping[str, Any]
    processing_provenance_fingerprint: str
    status: str
    unavailable_reason: str | None
    reference_distribution: KurtosisReferenceDistribution
    channels: tuple[KurtosisChannelEvidence, ...]

    @property
    def candidate_channels(self) -> tuple[str, ...]:
        return tuple(item.channel for item in self.channels if item.exceeds_threshold)

    @property
    def invalid_channels(self) -> tuple[str, ...]:
        return tuple(
            item.channel for item in self.channels if item.validity != CHANNEL_VALIDITY_VALID
        )

    @property
    def fingerprint(self) -> str:
        return _fingerprint(self._identity_payload())

    def channel(self, name: str) -> KurtosisChannelEvidence | None:
        return next((item for item in self.channels if item.channel == name), None)

    def _identity_payload(self) -> dict[str, object]:
        return {
            "method_version": self.method_version,
            "method_label": self.method_label,
            "authority_policy_version": self.authority_policy_version,
            "corroborator_registry_version": self.corroborator_registry_version,
            "corroborator_registry_fingerprint": self.corroborator_registry_fingerprint,
            "threshold": self.threshold,
            "scoring_scope": self.scoring_scope.to_payload(),
            "filter_identity": dict(self.filter_identity),
            "downsample_identity": dict(self.downsample_identity),
            "geometry_identity": dict(self.geometry_identity),
            "processing_provenance_fingerprint": self.processing_provenance_fingerprint,
            "status": self.status,
            "unavailable_reason": self.unavailable_reason,
            "reference_distribution": self.reference_distribution.to_payload(),
            "channels": [item.to_payload() for item in self.channels],
        }

    def to_payload(self) -> dict[str, object]:
        return {**self._identity_payload(), "fingerprint": self.fingerprint}


def _validated_geometry_identity(
    value: Mapping[str, Any],
    *,
    evaluated_channels: tuple[str, ...],
) -> dict[str, Any]:
    supplied = _canonical_json_mapping(value, field_name="geometry_identity")
    retained = _canonical_channels(
        supplied.get("retained_scalp_channels", ()),
        field_name="geometry_identity.retained_scalp_channels",
    )
    if not set(evaluated_channels).issubset(retained):
        raise KurtosisQCError("Kurtosis channels are not all present in retained geometry.")
    expected = biosemi64_geometry_identity(
        electrode_mapping_profile=supplied.get("electrode_mapping_profile"),
        retained_channels=retained,
    )
    for field_name, expected_value in expected.items():
        if supplied.get(field_name) != expected_value:
            raise KurtosisQCError(f"Kurtosis geometry {field_name} is missing or stale.")
    if supplied.get("montage_id") != BIOSEMI64_MONTAGE_ID:
        raise KurtosisQCError("Kurtosis evidence requires the BioSemi64 montage.")
    if supplied.get("geometry_version") != BIOSEMI64_GEOMETRY_VERSION:
        raise KurtosisQCError("Kurtosis evidence geometry version is stale.")
    if supplied.get("coordinate_fingerprint") != BIOSEMI64_COORDINATE_FINGERPRINT:
        raise KurtosisQCError("Kurtosis evidence coordinate fingerprint is stale.")
    return supplied


def evaluate_kurtosis_qc(
    data: np.ndarray,
    channel_names: Sequence[object],
    *,
    threshold: object,
    realized_analysis_span_plan: Mapping[str, Any],
    filter_identity: Mapping[str, Any],
    downsample_identity: Mapping[str, Any],
    geometry_identity: Mapping[str, Any],
    registry: KurtosisCorroboratorRegistry = CURRENT_KURTOSIS_CORROBORATOR_REGISTRY,
) -> KurtosisQCEvidence:
    """Calculate the current QC-16 kurtosis evidence without taking action."""

    threshold_value = _positive_finite(threshold, field_name="threshold")
    if not isinstance(registry, KurtosisCorroboratorRegistry):
        raise KurtosisQCError("registry must be a KurtosisCorroboratorRegistry.")
    try:
        array = np.asarray(data, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise KurtosisQCError("Kurtosis data must be a numeric channel-by-sample array.") from exc
    if array.ndim != 2 or array.shape[0] < 1 or array.shape[1] < 1:
        raise KurtosisQCError("Kurtosis data must be a nonempty channel-by-sample array.")
    supplied_channels = tuple(str(item or "").strip() for item in channel_names)
    canonical_channels = _canonical_channels(supplied_channels, field_name="channel_names")
    if len(supplied_channels) != array.shape[0]:
        raise KurtosisQCError("channel_names count does not match the data rows.")
    source_index = {name: index for index, name in enumerate(supplied_channels)}
    array = array[np.asarray([source_index[name] for name in canonical_channels], dtype=int)]

    scope = scoring_scope_from_realized_plan(
        realized_analysis_span_plan,
        expected_sample_count=array.shape[1],
    )
    normalized_filter = _canonical_json_mapping(filter_identity, field_name="filter_identity")
    normalized_downsample = _canonical_json_mapping(
        downsample_identity, field_name="downsample_identity"
    )
    normalized_geometry = _validated_geometry_identity(
        geometry_identity,
        evaluated_channels=canonical_channels,
    )
    processing_provenance = {
        "analysis_span_fingerprint": scope.analysis_span_fingerprint,
        "filter_identity": normalized_filter,
        "downsample_identity": normalized_downsample,
        "geometry_identity_fingerprint": normalized_geometry["geometry_identity_fingerprint"],
    }
    processing_provenance_fingerprint = _fingerprint(processing_provenance)

    input_finite = np.all(np.isfinite(array), axis=1)
    if array.shape[1] >= KURTOSIS_MIN_SAMPLES_PER_CHANNEL:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            raw_values = np.asarray(
                kurtosis(array, axis=1, fisher=True, bias=False, nan_policy="propagate"),
                dtype=np.float64,
            )
    else:
        raw_values = np.full(array.shape[0], np.nan, dtype=np.float64)

    preliminary_validity: list[tuple[str, str | None]] = []
    finite_rows: list[tuple[str, float]] = []
    for index, channel in enumerate(canonical_channels):
        if not input_finite[index]:
            validity = CHANNEL_VALIDITY_NONFINITE_INPUT
            reason = "Analyzed samples contain NaN or infinite values."
        elif array.shape[1] < KURTOSIS_MIN_SAMPLES_PER_CHANNEL:
            validity = CHANNEL_VALIDITY_UNDEFINED_STATISTIC
            reason = (
                f"Kurtosis requires at least {KURTOSIS_MIN_SAMPLES_PER_CHANNEL} samples."
            )
        elif not math.isfinite(float(raw_values[index])):
            validity = CHANNEL_VALIDITY_UNDEFINED_STATISTIC
            reason = "Kurtosis is undefined for this channel's analyzed samples."
        else:
            validity = CHANNEL_VALIDITY_VALID
            reason = None
            finite_rows.append((channel, float(raw_values[index])))
        preliminary_validity.append((validity, reason))

    sorted_reference = sorted(finite_rows, key=lambda item: (item[1], item[0]))
    trim_count = math.floor(len(sorted_reference) * KURTOSIS_TRIM_FRACTION)
    included = (
        sorted_reference[trim_count : len(sorted_reference) - trim_count]
        if trim_count
        else sorted_reference
    )
    reference_status = EVIDENCE_STATUS_VALID
    reference_reason: str | None = None
    reference_mean: float | None = None
    reference_sd: float | None = None
    if len(sorted_reference) < KURTOSIS_MIN_VALID_REFERENCE_CHANNELS:
        reference_status = EVIDENCE_STATUS_UNAVAILABLE
        reference_reason = (
            "Too few channels have finite kurtosis for the versioned reference "
            f"distribution ({len(sorted_reference)} < "
            f"{KURTOSIS_MIN_VALID_REFERENCE_CHANNELS})."
        )
    elif len(included) < 2:
        reference_status = EVIDENCE_STATUS_UNAVAILABLE
        reference_reason = "Kurtosis trimming left fewer than two reference channels."
    else:
        included_values = np.asarray([item[1] for item in included], dtype=np.float64)
        candidate_mean = float(np.mean(included_values))
        candidate_sd = float(np.std(included_values, ddof=0))
        if not math.isfinite(candidate_mean) or not math.isfinite(candidate_sd):
            reference_status = EVIDENCE_STATUS_UNAVAILABLE
            reference_reason = "The trimmed kurtosis reference distribution is nonfinite."
        elif candidate_sd <= KURTOSIS_MIN_REFERENCE_SCALE:
            reference_status = EVIDENCE_STATUS_UNAVAILABLE
            reference_reason = "The trimmed kurtosis reference distribution has degenerate scale."
        else:
            reference_mean = candidate_mean
            reference_sd = candidate_sd

    reference = KurtosisReferenceDistribution(
        status=reference_status,
        reason=reference_reason,
        finite_channel_count=len(sorted_reference),
        invalid_channel_count=len(canonical_channels) - len(sorted_reference),
        trim_fraction=KURTOSIS_TRIM_FRACTION,
        trim_count_per_tail=trim_count,
        minimum_valid_channels=KURTOSIS_MIN_VALID_REFERENCE_CHANNELS,
        included_channels=tuple(item[0] for item in included),
        included_raw_kurtosis=tuple(item[1] for item in included),
        trimmed_low_channels=tuple(item[0] for item in sorted_reference[:trim_count]),
        trimmed_high_channels=(
            tuple(item[0] for item in sorted_reference[-trim_count:]) if trim_count else ()
        ),
        mean=reference_mean,
        population_sd=reference_sd,
        minimum_scale=KURTOSIS_MIN_REFERENCE_SCALE,
    )
    evidence_context = {
        "method_version": KURTOSIS_QC_METHOD_VERSION,
        "authority_policy_version": KURTOSIS_AUTHORITY_POLICY_VERSION,
        "corroborator_registry_version": registry.version,
        "corroborator_registry_fingerprint": registry.fingerprint,
        "threshold": threshold_value,
        "analysis_span_fingerprint": scope.analysis_span_fingerprint,
        "processing_provenance_fingerprint": processing_provenance_fingerprint,
        "reference_fingerprint": reference.fingerprint,
    }
    context_fingerprint = _fingerprint(evidence_context)
    channel_rows: list[KurtosisChannelEvidence] = []
    for index, channel in enumerate(canonical_channels):
        raw_value = float(raw_values[index]) if math.isfinite(float(raw_values[index])) else None
        validity, validity_reason = preliminary_validity[index]
        signed_z: float | None = None
        absolute_z: float | None = None
        exceeds = False
        if validity == CHANNEL_VALIDITY_VALID and reference_status == EVIDENCE_STATUS_VALID:
            assert raw_value is not None and reference_mean is not None and reference_sd is not None
            signed_z = (raw_value - reference_mean) / reference_sd
            if not math.isfinite(signed_z):
                validity = CHANNEL_VALIDITY_REFERENCE_UNAVAILABLE
                validity_reason = "Normalized kurtosis is nonfinite."
                signed_z = None
            else:
                absolute_z = abs(signed_z)
                exceeds = absolute_z > threshold_value
        elif validity == CHANNEL_VALIDITY_VALID:
            validity = CHANNEL_VALIDITY_REFERENCE_UNAVAILABLE
            validity_reason = reference_reason
        channel_rows.append(
            KurtosisChannelEvidence(
                channel=channel,
                raw_kurtosis=raw_value,
                signed_z=signed_z,
                absolute_z=absolute_z,
                threshold=threshold_value,
                exceeds_threshold=exceeds,
                input_sample_count=array.shape[1],
                input_finite=bool(input_finite[index]),
                validity=validity,
                validity_reason=validity_reason,
                reference_fingerprint=reference.fingerprint,
                evidence_context_fingerprint=context_fingerprint,
            )
        )

    if reference_status == EVIDENCE_STATUS_UNAVAILABLE:
        status = EVIDENCE_STATUS_UNAVAILABLE
        unavailable_reason = reference_reason
    elif any(item.validity != CHANNEL_VALIDITY_VALID for item in channel_rows):
        status = EVIDENCE_STATUS_PARTIAL
        unavailable_reason = None
    else:
        status = EVIDENCE_STATUS_VALID
        unavailable_reason = None
    return KurtosisQCEvidence(
        method_version=KURTOSIS_QC_METHOD_VERSION,
        method_label=(
            "EEGLAB-inspired 10%-trimmed normalized excess kurtosis "
            "(SciPy bias-corrected estimate; population reference SD)"
        ),
        authority_policy_version=KURTOSIS_AUTHORITY_POLICY_VERSION,
        corroborator_registry_version=registry.version,
        corroborator_registry_fingerprint=registry.fingerprint,
        threshold=threshold_value,
        scoring_scope=scope,
        filter_identity=normalized_filter,
        downsample_identity=normalized_downsample,
        geometry_identity=normalized_geometry,
        processing_provenance_fingerprint=processing_provenance_fingerprint,
        status=status,
        unavailable_reason=unavailable_reason,
        reference_distribution=reference,
        channels=tuple(channel_rows),
    )


@dataclass(frozen=True, slots=True)
class KurtosisCorroboratorFinding:
    method_id: str
    method_version: str
    channel: str
    scope: str
    analysis_span_fingerprint: str
    occurrence_keys: tuple[str, ...]
    authority: str
    evidence_fingerprint: str
    valid: bool = True

    @classmethod
    def from_payload(cls, value: Mapping[str, Any]) -> "KurtosisCorroboratorFinding":
        if not isinstance(value, Mapping):
            raise KurtosisQCError("Corroborator finding must be an object.")
        raw_occurrences = value.get("occurrence_keys", ())
        if not isinstance(raw_occurrences, Sequence) or isinstance(
            raw_occurrences, (str, bytes, bytearray)
        ):
            raise KurtosisQCError("Corroborator occurrence_keys must be a sequence.")
        valid = value.get("valid", True)
        if not isinstance(valid, bool):
            raise KurtosisQCError("Corroborator valid state must be boolean.")
        return cls(
            method_id=str(value.get("method_id") or "").strip(),
            method_version=str(value.get("method_version") or "").strip(),
            channel=str(value.get("channel") or "").strip(),
            scope=str(value.get("scope") or "").strip(),
            analysis_span_fingerprint=str(
                value.get("analysis_span_fingerprint") or ""
            ).strip(),
            occurrence_keys=tuple(str(item or "").strip() for item in raw_occurrences),
            authority=str(value.get("authority") or "").strip(),
            evidence_fingerprint=str(value.get("evidence_fingerprint") or "").strip(),
            valid=valid,
        )

    def validate(self) -> None:
        if not self.method_id or not self.method_version:
            raise KurtosisQCError("Corroborator method identity must not be empty.")
        if self.channel not in BIOSEMI64_CHANNEL_SET:
            raise KurtosisQCError("Corroborator finding channel is outside BioSemi64.")
        if not self.scope:
            raise KurtosisQCError("Corroborator finding scope must not be empty.")
        if not _is_sha256(self.analysis_span_fingerprint):
            raise KurtosisQCError("Corroborator analysis-span fingerprint is malformed.")
        if not _is_sha256(self.evidence_fingerprint):
            raise KurtosisQCError("Corroborator evidence fingerprint is malformed.")
        if not isinstance(self.valid, bool):
            raise KurtosisQCError("Corroborator valid state must be boolean.")
        if any(not item for item in self.occurrence_keys) or len(set(self.occurrence_keys)) != len(
            self.occurrence_keys
        ):
            raise KurtosisQCError("Corroborator occurrence keys must be nonempty and unique.")

    def to_payload(self) -> dict[str, object]:
        return {
            "method_id": self.method_id,
            "method_version": self.method_version,
            "channel": self.channel,
            "scope": self.scope,
            "analysis_span_fingerprint": self.analysis_span_fingerprint,
            "occurrence_keys": list(self.occurrence_keys),
            "authority": self.authority,
            "evidence_fingerprint": self.evidence_fingerprint,
            "valid": self.valid,
        }


@dataclass(frozen=True, slots=True)
class KurtosisCorroborationAssessment:
    finding: KurtosisCorroboratorFinding
    eligible: bool
    reason: str

    def to_payload(self) -> dict[str, object]:
        return {
            "finding": self.finding.to_payload(),
            "eligible": self.eligible,
            "reason": self.reason,
        }


def _assess_corroborator(
    finding: KurtosisCorroboratorFinding,
    *,
    evidence: KurtosisQCEvidence,
    registry: KurtosisCorroboratorRegistry,
) -> KurtosisCorroborationAssessment:
    finding.validate()
    definition = next(
        (
            item
            for item in registry.methods
            if (item.method_id, item.method_version)
            == (finding.method_id, finding.method_version)
        ),
        None,
    )
    if definition is None:
        return KurtosisCorroborationAssessment(finding, False, "method_not_registered")
    if not finding.valid:
        return KurtosisCorroborationAssessment(finding, False, "finding_not_valid")
    if finding.authority != CORROBORATOR_AUTHORITY_ELIGIBLE:
        return KurtosisCorroborationAssessment(finding, False, "finding_is_review_only")
    if finding.scope != definition.required_scope:
        return KurtosisCorroborationAssessment(finding, False, "scope_not_recording_union")
    if finding.analysis_span_fingerprint != evidence.scoring_scope.analysis_span_fingerprint:
        return KurtosisCorroborationAssessment(finding, False, "analysis_spans_do_not_match")
    if set(finding.occurrence_keys) != set(evidence.scoring_scope.occurrence_keys):
        return KurtosisCorroborationAssessment(finding, False, "occurrence_scope_does_not_match")
    return KurtosisCorroborationAssessment(finding, True, "eligible_same_channel_same_scope")


@dataclass(frozen=True, slots=True)
class KurtosisReviewDecision:
    schema_version: str
    decision: str
    reason: str
    reviewed_at_utc: str
    reviewer_state: str
    reviewer_identity: str | None
    reviewer_identity_status: str
    source_file_path: str
    participant_id: str
    recording_id: str
    session_id: str | None
    session_label: str | None
    channel: str
    reviewed_method_version: str
    reviewed_registry_version: str
    reviewed_evidence_fingerprint: str
    reviewed_channel_evidence_fingerprint: str
    reviewed_analysis_span_fingerprint: str
    reviewed_occurrence_keys: tuple[str, ...]

    @classmethod
    def from_payload(cls, value: Mapping[str, Any]) -> "KurtosisReviewDecision":
        if not isinstance(value, Mapping):
            raise KurtosisQCError("Kurtosis review decision must be an object.")
        occurrences = value.get("reviewed_occurrence_keys", ())
        if not isinstance(occurrences, Sequence) or isinstance(
            occurrences, (str, bytes, bytearray)
        ):
            raise KurtosisQCError("reviewed_occurrence_keys must be a sequence.")
        return cls(
            schema_version=str(value.get("schema_version") or "").strip(),
            decision=str(value.get("decision") or "").strip(),
            reason=str(value.get("reason") or "").strip() or KURTOSIS_NO_REASON_PROVIDED,
            reviewed_at_utc=str(value.get("reviewed_at_utc") or "").strip(),
            reviewer_state=str(value.get("reviewer_state") or "").strip(),
            reviewer_identity=(
                str(value.get("reviewer_identity")).strip()
                if value.get("reviewer_identity") is not None
                else None
            ),
            reviewer_identity_status=str(
                value.get("reviewer_identity_status") or ""
            ).strip(),
            source_file_path=str(value.get("source_file_path") or "").strip(),
            participant_id=str(value.get("participant_id") or "").strip(),
            recording_id=str(value.get("recording_id") or "").strip(),
            session_id=(
                str(value.get("session_id")).strip()
                if value.get("session_id") is not None
                else None
            ),
            session_label=(
                str(value.get("session_label")).strip()
                if value.get("session_label") is not None
                else None
            ),
            channel=str(value.get("channel") or "").strip(),
            reviewed_method_version=str(
                value.get("reviewed_method_version") or ""
            ).strip(),
            reviewed_registry_version=str(
                value.get("reviewed_registry_version") or ""
            ).strip(),
            reviewed_evidence_fingerprint=str(
                value.get("reviewed_evidence_fingerprint") or ""
            ).strip(),
            reviewed_channel_evidence_fingerprint=str(
                value.get("reviewed_channel_evidence_fingerprint") or ""
            ).strip(),
            reviewed_analysis_span_fingerprint=str(
                value.get("reviewed_analysis_span_fingerprint") or ""
            ).strip(),
            reviewed_occurrence_keys=tuple(
                str(item or "").strip() for item in occurrences
            ),
        )

    def to_payload(self) -> dict[str, object]:
        payload = asdict(self)
        payload["reviewed_occurrence_keys"] = list(self.reviewed_occurrence_keys)
        return payload


def qualifies_for_experimental_kurtosis_auto(channel: Mapping[str, Any]) -> bool:
    """Apply the optional authority rule to existing scores; never rescore data."""

    score = channel.get("signed_z")
    return (
        channel.get("validity") == CHANNEL_VALIDITY_VALID
        and channel.get("exceeds_threshold") is True
        and isinstance(score, (int, float))
        and not isinstance(score, bool)
        and math.isfinite(score)
        and abs(score) > KURTOSIS_EXPERIMENTAL_AUTO_Z_THRESHOLD
    )


def qualifies_for_experimental_kurtosis_auto_all(channel: Mapping[str, Any]) -> bool:
    """Use the existing normalized rejection result without changing its math."""

    score = channel.get("signed_z")
    return (
        channel.get("validity") == CHANNEL_VALIDITY_VALID
        and channel.get("exceeds_threshold") is True
        and isinstance(score, (int, float))
        and not isinstance(score, bool)
        and math.isfinite(score)
    )


def _validate_review_authority(
    receipt: KurtosisReviewDecision,
    channel: Mapping[str, Any] | None = None,
    *,
    kurtosis_auto_interpolate_all: bool | None = None,
) -> None:
    if receipt.reviewer_state == KURTOSIS_REVIEWER_STATE_EXPLICIT_GUI:
        return
    if (
        receipt.reviewer_state == KURTOSIS_REVIEWER_STATE_EXPERIMENTAL_AUTO
        and receipt.decision == KURTOSIS_DECISION_APPROVE
        and (channel is None or qualifies_for_experimental_kurtosis_auto(channel))
    ):
        return
    if (
        receipt.reviewer_state == KURTOSIS_REVIEWER_STATE_EXPERIMENTAL_AUTO_ALL
        and receipt.decision == KURTOSIS_DECISION_APPROVE
        and kurtosis_auto_interpolate_all is not False
        and (channel is None or qualifies_for_experimental_kurtosis_auto_all(channel))
    ):
        return
    raise KurtosisQCError(
        "Kurtosis review requires explicit GUI review or a valid enabled experimental approval."
    )


def build_kurtosis_review_decision(
    evidence: Mapping[str, Any],
    *,
    channel: object,
    decision: object,
    reason: object,
    review_scope: Mapping[str, Any],
    reviewer_identity: object | None = None,
    reviewed_at_utc: str | None = None,
    experimental_auto: bool = False,
    experimental_auto_all: bool = False,
) -> KurtosisReviewDecision:
    """Build an auditable GUI receipt from one cached evidence payload."""

    if not isinstance(evidence, Mapping):
        raise KurtosisQCError("Kurtosis review evidence must be an object.")
    evidence_core = {key: value for key, value in evidence.items() if key != "fingerprint"}
    evidence_fingerprint = str(evidence.get("fingerprint") or "")
    if evidence_fingerprint != _fingerprint(evidence_core):
        raise KurtosisQCError("Kurtosis review evidence fingerprint is stale.")
    normalized_channel = str(channel or "").strip()
    if normalized_channel not in BIOSEMI64_CHANNEL_SET:
        raise KurtosisQCError("Kurtosis review channel is outside BioSemi64.")
    normalized_decision = str(decision or "").strip()
    if normalized_decision not in {
        KURTOSIS_DECISION_APPROVE,
        KURTOSIS_DECISION_REJECT,
    }:
        raise KurtosisQCError("Kurtosis review decision must approve or reject interpolation.")
    normalized_reason = str(reason or "").strip() or KURTOSIS_NO_REASON_PROVIDED
    if not isinstance(review_scope, Mapping):
        raise KurtosisQCError("Kurtosis review scope must be an object.")

    raw_channels = evidence.get("channels")
    if not isinstance(raw_channels, Sequence) or isinstance(
        raw_channels, (str, bytes, bytearray)
    ):
        raise KurtosisQCError("Kurtosis review evidence channels are malformed.")
    channel_rows = [
        row
        for row in raw_channels
        if isinstance(row, Mapping)
        and str(row.get("channel") or "").strip() == normalized_channel
    ]
    if len(channel_rows) != 1:
        raise KurtosisQCError("Kurtosis review channel evidence is missing or duplicated.")
    channel_row = channel_rows[0]
    channel_core = {
        key: value for key, value in channel_row.items() if key != "fingerprint"
    }
    channel_fingerprint = str(channel_row.get("fingerprint") or "")
    if channel_fingerprint != _fingerprint(channel_core):
        raise KurtosisQCError("Kurtosis channel evidence fingerprint is stale.")
    if not (
        bool(channel_row.get("exceeds_threshold"))
        or str(channel_row.get("validity") or "") != CHANNEL_VALIDITY_VALID
    ):
        raise KurtosisQCError("Kurtosis review is not required for this channel.")

    scoring_scope = evidence.get("scoring_scope")
    if not isinstance(scoring_scope, Mapping):
        raise KurtosisQCError("Kurtosis review scoring scope is malformed.")
    analysis_span_fingerprint = str(
        scoring_scope.get("analysis_span_fingerprint") or ""
    )
    if not _is_sha256(analysis_span_fingerprint):
        raise KurtosisQCError("Kurtosis review analysis-span fingerprint is malformed.")
    raw_occurrences = scoring_scope.get("occurrences")
    if not isinstance(raw_occurrences, Sequence) or isinstance(
        raw_occurrences, (str, bytes, bytearray)
    ):
        raise KurtosisQCError("Kurtosis review occurrence scope is malformed.")
    occurrence_keys = tuple(
        str(row.get("occurrence_key") or "").strip()
        for row in raw_occurrences
        if isinstance(row, Mapping)
    )
    if len(occurrence_keys) != len(raw_occurrences) or any(
        not item for item in occurrence_keys
    ):
        raise KurtosisQCError("Kurtosis review occurrence scope is malformed.")

    source_file_path = str(review_scope.get("source_file_path") or "").strip()
    participant_id = str(review_scope.get("participant_id") or "").strip()
    recording_id = str(review_scope.get("recording_id") or "").strip()
    if not source_file_path or not participant_id or not recording_id:
        raise KurtosisQCError(
            "Kurtosis review requires source file, participant, and recording identity."
        )
    reviewer = _normalized_optional_text(reviewer_identity)
    reviewed_time = reviewed_at_utc or datetime.now(timezone.utc).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")
    _validate_utc_time(reviewed_time)
    receipt = KurtosisReviewDecision(
        schema_version=KURTOSIS_REVIEW_DECISION_SCHEMA_VERSION,
        decision=normalized_decision,
        reason=normalized_reason,
        reviewed_at_utc=reviewed_time,
        reviewer_state=(
            KURTOSIS_REVIEWER_STATE_EXPERIMENTAL_AUTO_ALL
            if experimental_auto_all
            else KURTOSIS_REVIEWER_STATE_EXPERIMENTAL_AUTO
            if experimental_auto
            else KURTOSIS_REVIEWER_STATE_EXPLICIT_GUI
        ),
        reviewer_identity=reviewer,
        reviewer_identity_status=(
            KURTOSIS_REVIEWER_IDENTITY_STATUS_PROVIDED
            if reviewer is not None
            else KURTOSIS_REVIEWER_IDENTITY_STATUS_NOT_COLLECTED
        ),
        source_file_path=source_file_path,
        participant_id=participant_id,
        recording_id=recording_id,
        session_id=_normalized_optional_text(review_scope.get("session_id")),
        session_label=_normalized_optional_text(review_scope.get("session_label")),
        channel=normalized_channel,
        reviewed_method_version=str(evidence.get("method_version") or "").strip(),
        reviewed_registry_version=str(
            evidence.get("corroborator_registry_version") or ""
        ).strip(),
        reviewed_evidence_fingerprint=evidence_fingerprint,
        reviewed_channel_evidence_fingerprint=channel_fingerprint,
        reviewed_analysis_span_fingerprint=analysis_span_fingerprint,
        reviewed_occurrence_keys=occurrence_keys,
    )
    _validate_review_authority(receipt, channel_row)
    return receipt


def make_kurtosis_auto_all_decision_receipt(
    evidence: Mapping[str, Any], *, channel: object, review_scope: Mapping[str, Any],
    reviewer_identity: object | None = None, reviewed_at_utc: str | None = None,
) -> KurtosisReviewDecision:
    """Record the selected experimental policy separately from manual review."""

    return build_kurtosis_review_decision(
        evidence, channel=channel, decision=KURTOSIS_DECISION_APPROVE,
        reason="Experimental project setting: automatically interpolate all kurtosis flags.",
        review_scope=review_scope, reviewer_identity=reviewer_identity,
        reviewed_at_utc=reviewed_at_utc, experimental_auto_all=True,
    )


def _normalized_optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalized_path(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        raise KurtosisQCError("Kurtosis review requires a source-file path.")
    try:
        return os.path.normcase(str(Path(text).resolve()))
    except (OSError, RuntimeError, ValueError) as exc:
        raise KurtosisQCError("Kurtosis review source-file path is invalid.") from exc


def _validate_utc_time(value: str) -> None:
    if not value.endswith("Z"):
        raise KurtosisQCError("Kurtosis review time must be ISO-8601 UTC ending in Z.")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise KurtosisQCError("Kurtosis review time must be valid ISO-8601 UTC.") from exc
    if parsed.utcoffset() != timedelta(0):
        raise KurtosisQCError("Kurtosis review time must be UTC.")


def validate_kurtosis_review_decision(
    decision: KurtosisReviewDecision | Mapping[str, Any],
    *,
    evidence: KurtosisQCEvidence,
    channel_evidence: KurtosisChannelEvidence,
    review_scope: Mapping[str, Any],
    kurtosis_auto_interpolate_all: bool = False,
) -> KurtosisReviewDecision:
    """Validate one explicit GUI receipt against current recording evidence."""

    receipt = KurtosisReviewDecision.from_payload(
        decision.to_payload()
        if isinstance(decision, KurtosisReviewDecision)
        else decision
    )
    if receipt.schema_version != KURTOSIS_REVIEW_DECISION_SCHEMA_VERSION:
        raise KurtosisQCError("Kurtosis review schema is missing or stale; review again.")
    if receipt.decision not in {KURTOSIS_DECISION_APPROVE, KURTOSIS_DECISION_REJECT}:
        raise KurtosisQCError("Kurtosis review decision must approve or reject interpolation.")
    if not receipt.reason:
        raise KurtosisQCError("Kurtosis review decision requires a reason.")
    _validate_utc_time(receipt.reviewed_at_utc)
    _validate_review_authority(receipt, channel_evidence.to_payload(), kurtosis_auto_interpolate_all=kurtosis_auto_interpolate_all)
    if receipt.reviewer_identity_status == KURTOSIS_REVIEWER_IDENTITY_STATUS_NOT_COLLECTED:
        if _normalized_optional_text(receipt.reviewer_identity) is not None:
            raise KurtosisQCError("Reviewer identity cannot be stored when it was not collected.")
    elif receipt.reviewer_identity_status == KURTOSIS_REVIEWER_IDENTITY_STATUS_PROVIDED:
        if _normalized_optional_text(receipt.reviewer_identity) is None:
            raise KurtosisQCError("Reviewer identity is missing despite provided status.")
    else:
        raise KurtosisQCError("Kurtosis review has no truthful reviewer identity status.")

    if receipt.channel != channel_evidence.channel:
        raise KurtosisQCError("Kurtosis review belongs to a different channel.")
    if receipt.reviewed_method_version != evidence.method_version:
        raise KurtosisQCError("Kurtosis review method is stale.")
    if receipt.reviewed_registry_version != evidence.corroborator_registry_version:
        raise KurtosisQCError("Kurtosis review corroborator registry is stale.")
    if receipt.reviewed_evidence_fingerprint != evidence.fingerprint:
        raise KurtosisQCError("Kurtosis review evidence changed; review again.")
    if receipt.reviewed_channel_evidence_fingerprint != channel_evidence.fingerprint:
        raise KurtosisQCError("Kurtosis channel evidence changed; review again.")
    if receipt.reviewed_analysis_span_fingerprint != evidence.scoring_scope.analysis_span_fingerprint:
        raise KurtosisQCError("Kurtosis review analyzed intervals changed; review again.")
    if set(receipt.reviewed_occurrence_keys) != set(evidence.scoring_scope.occurrence_keys):
        raise KurtosisQCError("Kurtosis review occurrence scope changed; review again.")

    expected_path = review_scope.get("source_file_path")
    if _normalized_path(receipt.source_file_path) != _normalized_path(expected_path):
        raise KurtosisQCError("Kurtosis review belongs to a different source file.")
    for field_name in ("participant_id", "recording_id"):
        expected = str(review_scope.get(field_name) or "").strip()
        actual = str(getattr(receipt, field_name) or "").strip()
        if not expected or actual != expected:
            raise KurtosisQCError(f"Kurtosis review {field_name} scope is missing or stale.")
    for field_name in ("session_id", "session_label"):
        if _normalized_optional_text(getattr(receipt, field_name)) != _normalized_optional_text(
            review_scope.get(field_name)
        ):
            raise KurtosisQCError(f"Kurtosis review {field_name} scope is stale.")
    return receipt


def validate_kurtosis_review_decision_payload(
    decision: KurtosisReviewDecision | Mapping[str, Any],
    *,
    evidence: Mapping[str, Any],
    channel: object,
    review_scope: Mapping[str, Any],
    kurtosis_auto_interpolate_all: bool = False,
) -> KurtosisReviewDecision:
    """Validate a saved GUI receipt against serialized scanner evidence."""

    if not isinstance(evidence, Mapping):
        raise KurtosisQCError("Kurtosis review evidence must be an object.")
    evidence_core = {
        key: value for key, value in evidence.items() if key != "fingerprint"
    }
    evidence_fingerprint = str(evidence.get("fingerprint") or "")
    if evidence_fingerprint != _fingerprint(evidence_core):
        raise KurtosisQCError("Kurtosis review evidence fingerprint is stale.")

    normalized_channel = str(channel or "").strip()
    raw_channels = evidence.get("channels")
    if not isinstance(raw_channels, Sequence) or isinstance(
        raw_channels,
        (str, bytes, bytearray),
    ):
        raise KurtosisQCError("Kurtosis review evidence channels are malformed.")
    channel_rows = [
        row
        for row in raw_channels
        if isinstance(row, Mapping)
        and str(row.get("channel") or "").strip() == normalized_channel
    ]
    if len(channel_rows) != 1:
        raise KurtosisQCError(
            "Kurtosis review channel evidence is missing or duplicated."
        )
    channel_row = channel_rows[0]
    channel_core = {
        key: value for key, value in channel_row.items() if key != "fingerprint"
    }
    channel_fingerprint = str(channel_row.get("fingerprint") or "")
    if channel_fingerprint != _fingerprint(channel_core):
        raise KurtosisQCError("Kurtosis channel evidence fingerprint is stale.")
    if not (
        bool(channel_row.get("exceeds_threshold"))
        or str(channel_row.get("validity") or "") != CHANNEL_VALIDITY_VALID
    ):
        raise KurtosisQCError("Kurtosis review is not required for this channel.")

    scoring_scope = evidence.get("scoring_scope")
    if not isinstance(scoring_scope, Mapping):
        raise KurtosisQCError("Kurtosis review scoring scope is malformed.")
    analysis_span_fingerprint = str(
        scoring_scope.get("analysis_span_fingerprint") or ""
    )
    if not _is_sha256(analysis_span_fingerprint):
        raise KurtosisQCError(
            "Kurtosis review analysis-span fingerprint is malformed."
        )
    raw_occurrences = scoring_scope.get("occurrences")
    if not isinstance(raw_occurrences, Sequence) or isinstance(
        raw_occurrences,
        (str, bytes, bytearray),
    ):
        raise KurtosisQCError("Kurtosis review occurrence scope is malformed.")
    occurrence_keys = tuple(
        str(row.get("occurrence_key") or "").strip()
        for row in raw_occurrences
        if isinstance(row, Mapping)
    )
    if len(occurrence_keys) != len(raw_occurrences) or any(
        not item for item in occurrence_keys
    ):
        raise KurtosisQCError("Kurtosis review occurrence scope is malformed.")

    receipt = KurtosisReviewDecision.from_payload(
        decision.to_payload()
        if isinstance(decision, KurtosisReviewDecision)
        else decision
    )
    if receipt.schema_version != KURTOSIS_REVIEW_DECISION_SCHEMA_VERSION:
        raise KurtosisQCError(
            "Kurtosis review schema is missing or stale; review again."
        )
    if receipt.decision not in {
        KURTOSIS_DECISION_APPROVE,
        KURTOSIS_DECISION_REJECT,
    }:
        raise KurtosisQCError(
            "Kurtosis review decision must approve or reject interpolation."
        )
    if not receipt.reason:
        raise KurtosisQCError("Kurtosis review decision requires a reason.")
    _validate_utc_time(receipt.reviewed_at_utc)
    _validate_review_authority(receipt, channel_row, kurtosis_auto_interpolate_all=kurtosis_auto_interpolate_all)
    if receipt.reviewer_identity_status == (
        KURTOSIS_REVIEWER_IDENTITY_STATUS_NOT_COLLECTED
    ):
        if _normalized_optional_text(receipt.reviewer_identity) is not None:
            raise KurtosisQCError(
                "Reviewer identity cannot be stored when it was not collected."
            )
    elif receipt.reviewer_identity_status == (
        KURTOSIS_REVIEWER_IDENTITY_STATUS_PROVIDED
    ):
        if _normalized_optional_text(receipt.reviewer_identity) is None:
            raise KurtosisQCError(
                "Reviewer identity is missing despite provided status."
            )
    else:
        raise KurtosisQCError(
            "Kurtosis review has no truthful reviewer identity status."
        )

    if receipt.channel != normalized_channel:
        raise KurtosisQCError("Kurtosis review belongs to a different channel.")
    if receipt.reviewed_method_version != str(
        evidence.get("method_version") or ""
    ):
        raise KurtosisQCError("Kurtosis review method is stale.")
    if receipt.reviewed_registry_version != str(
        evidence.get("corroborator_registry_version") or ""
    ):
        raise KurtosisQCError("Kurtosis review corroborator registry is stale.")
    if receipt.reviewed_evidence_fingerprint != evidence_fingerprint:
        raise KurtosisQCError("Kurtosis review evidence changed; review again.")
    if receipt.reviewed_channel_evidence_fingerprint != channel_fingerprint:
        raise KurtosisQCError("Kurtosis channel evidence changed; review again.")
    if receipt.reviewed_analysis_span_fingerprint != analysis_span_fingerprint:
        raise KurtosisQCError(
            "Kurtosis review analyzed intervals changed; review again."
        )
    if set(receipt.reviewed_occurrence_keys) != set(occurrence_keys):
        raise KurtosisQCError("Kurtosis review occurrence scope changed; review again.")

    expected_path = review_scope.get("source_file_path")
    if _normalized_path(receipt.source_file_path) != _normalized_path(expected_path):
        raise KurtosisQCError("Kurtosis review belongs to a different source file.")
    for field_name in ("participant_id", "recording_id"):
        expected = str(review_scope.get(field_name) or "").strip()
        actual = str(getattr(receipt, field_name) or "").strip()
        if not expected or actual != expected:
            raise KurtosisQCError(
                f"Kurtosis review {field_name} scope is missing or stale."
            )
    for field_name in ("session_id", "session_label"):
        if _normalized_optional_text(
            getattr(receipt, field_name)
        ) != _normalized_optional_text(review_scope.get(field_name)):
            raise KurtosisQCError(f"Kurtosis review {field_name} scope is stale.")
    return receipt


def normalize_kurtosis_review_decisions_by_recording(
    value: Any,
) -> dict[str, dict[str, dict[str, object]]]:
    """Normalize persisted QC-16 receipts without treating them as current."""

    if value in (None, ""):
        return {}
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError) as exc:
            raise KurtosisQCError(
                "Kurtosis review decisions must be a recording-to-channel map."
            ) from exc
    if not isinstance(value, Mapping):
        raise KurtosisQCError(
            "Kurtosis review decisions must be a recording-to-channel map."
        )

    normalized: dict[str, dict[str, dict[str, object]]] = {}
    seen_recordings: set[str] = set()
    for raw_recording_id, raw_channels in value.items():
        recording_id = str(raw_recording_id or "").strip()
        if not recording_id or not isinstance(raw_channels, Mapping):
            raise KurtosisQCError(
                "Each kurtosis review recording must contain a channel-decision map."
            )
        recording_key = recording_id.casefold()
        if recording_key in seen_recordings:
            raise KurtosisQCError(
                "Kurtosis review decisions contain duplicate recording identities."
            )
        seen_recordings.add(recording_key)
        channel_rows: dict[str, dict[str, object]] = {}
        seen_channels: set[str] = set()
        canonical_recording_id: str | None = None
        for raw_channel, raw_receipt in raw_channels.items():
            channel = str(raw_channel or "").strip()
            if not isinstance(raw_receipt, Mapping):
                raise KurtosisQCError("Kurtosis review receipt must be an object.")
            receipt = KurtosisReviewDecision.from_payload(raw_receipt)
            if receipt.schema_version != KURTOSIS_REVIEW_DECISION_SCHEMA_VERSION:
                raise KurtosisQCError("Kurtosis review schema is missing or stale.")
            if receipt.decision not in {
                KURTOSIS_DECISION_APPROVE,
                KURTOSIS_DECISION_REJECT,
            }:
                raise KurtosisQCError(
                    "Kurtosis review decision must approve or reject interpolation."
                )
            if not receipt.reason:
                raise KurtosisQCError("Kurtosis review decision requires a reason.")
            _validate_utc_time(receipt.reviewed_at_utc)
            _validate_review_authority(receipt)
            if receipt.channel != channel:
                raise KurtosisQCError(
                    "Kurtosis review channel key does not match its receipt."
                )
            if receipt.recording_id.casefold() != recording_key:
                raise KurtosisQCError(
                    "Kurtosis review recording key does not match its receipt."
                )
            if channel not in BIOSEMI64_CHANNEL_SET or channel.casefold() in seen_channels:
                raise KurtosisQCError(
                    "Kurtosis review channels must be unique BioSemi64 labels."
                )
            seen_channels.add(channel.casefold())
            canonical_recording_id = receipt.recording_id
            channel_rows[channel] = receipt.to_payload()
        normalized[canonical_recording_id or recording_id] = dict(
            sorted(channel_rows.items(), key=lambda item: item[0].casefold())
        )
    return dict(sorted(normalized.items(), key=lambda item: item[0].casefold()))


@dataclass(frozen=True, slots=True)
class KurtosisChannelDecision:
    channel: str
    state: str
    interpolation_authorized: bool
    reasons: tuple[str, ...]
    channel_evidence_fingerprint: str | None
    corroborator_assessments: tuple[KurtosisCorroborationAssessment, ...]
    review_receipt: KurtosisReviewDecision | None

    def to_payload(self) -> dict[str, object]:
        return {
            "channel": self.channel,
            "state": self.state,
            "interpolation_authorized": self.interpolation_authorized,
            "reasons": list(self.reasons),
            "channel_evidence_fingerprint": self.channel_evidence_fingerprint,
            "corroborator_assessments": [
                item.to_payload() for item in self.corroborator_assessments
            ],
            "review_receipt": (
                self.review_receipt.to_payload() if self.review_receipt is not None else None
            ),
        }


@dataclass(frozen=True, slots=True)
class KurtosisDecisionPlan:
    method_version: str
    authority_policy_version: str
    registry_version: str
    registry_fingerprint: str
    evidence_fingerprint: str
    ready_for_interpolation: bool
    blocking_reasons: tuple[str, ...]
    channel_decisions: tuple[KurtosisChannelDecision, ...]
    kurtosis_auto_interpolate_all: bool = False

    @property
    def candidate_channels(self) -> tuple[str, ...]:
        return tuple(
            item.channel
            for item in self.channel_decisions
            if "kurtosis_threshold_exceeded" in item.reasons
        )

    @property
    def pending_review_channels(self) -> tuple[str, ...]:
        return tuple(
            item.channel
            for item in self.channel_decisions
            if item.state == CHANNEL_DECISION_REVIEW_REQUIRED
        )

    @property
    def corroborated_automatic_channels(self) -> tuple[str, ...]:
        return tuple(
            item.channel
            for item in self.channel_decisions
            if item.state == CHANNEL_DECISION_CORROBORATED_AUTO
        )

    @property
    def user_approved_channels(self) -> tuple[str, ...]:
        return tuple(
            item.channel
            for item in self.channel_decisions
            if item.state == CHANNEL_DECISION_USER_APPROVED
        )

    @property
    def user_rejected_channels(self) -> tuple[str, ...]:
        return tuple(
            item.channel
            for item in self.channel_decisions
            if item.state == CHANNEL_DECISION_USER_REJECTED
        )

    @property
    def direct_channels(self) -> tuple[str, ...]:
        return tuple(
            item.channel
            for item in self.channel_decisions
            if item.state == CHANNEL_DECISION_DIRECT
        )

    @property
    def authorized_interpolation_channels(self) -> tuple[str, ...]:
        return tuple(
            item.channel for item in self.channel_decisions if item.interpolation_authorized
        )

    @property
    def fingerprint(self) -> str:
        return _fingerprint(self._identity_payload())

    def _identity_payload(self) -> dict[str, object]:
        return {
            "method_version": self.method_version,
            "authority_policy_version": self.authority_policy_version,
            "registry_version": self.registry_version,
            "registry_fingerprint": self.registry_fingerprint,
            "evidence_fingerprint": self.evidence_fingerprint,
            "ready_for_interpolation": self.ready_for_interpolation,
            "blocking_reasons": list(self.blocking_reasons),
            "channel_decisions": [item.to_payload() for item in self.channel_decisions],
            "kurtosis_auto_interpolate_all": self.kurtosis_auto_interpolate_all,
        }

    def to_payload(self) -> dict[str, object]:
        return {**self._identity_payload(), "fingerprint": self.fingerprint}


def _normalized_decisions(
    values: Mapping[str, KurtosisReviewDecision | Mapping[str, Any]] | None,
) -> dict[str, KurtosisReviewDecision | Mapping[str, Any]]:
    if values is None:
        return {}
    if not isinstance(values, Mapping):
        raise KurtosisQCError("Kurtosis review decisions must be keyed by channel.")
    result: dict[str, KurtosisReviewDecision | Mapping[str, Any]] = {}
    for raw_channel, decision in values.items():
        channel = str(raw_channel or "").strip()
        if channel not in BIOSEMI64_CHANNEL_SET:
            raise KurtosisQCError("Kurtosis review decision channel is outside BioSemi64.")
        if channel in result:
            raise KurtosisQCError("Kurtosis review decisions contain duplicate channels.")
        result[channel] = decision
    return result


def build_kurtosis_decision_plan(
    evidence: KurtosisQCEvidence,
    *,
    corroborator_findings: Sequence[
        KurtosisCorroboratorFinding | Mapping[str, Any]
    ] = (),
    review_decisions: Mapping[
        str, KurtosisReviewDecision | Mapping[str, Any]
    ] | None = None,
    review_scope: Mapping[str, Any] | None = None,
    direct_bad_channels: Mapping[str, str] | None = None,
    registry: KurtosisCorroboratorRegistry = CURRENT_KURTOSIS_CORROBORATOR_REGISTRY,
    kurtosis_auto_interpolate_all: bool = False,
) -> KurtosisDecisionPlan:
    """Apply QC-16 authority without treating candidates as interpolation outcomes."""

    if evidence.method_version != KURTOSIS_QC_METHOD_VERSION:
        raise KurtosisQCError("Kurtosis evidence method is missing or stale.")
    if not isinstance(kurtosis_auto_interpolate_all, bool):
        raise KurtosisQCError("The experimental auto-interpolate-all setting must be boolean.")
    if evidence.authority_policy_version != KURTOSIS_AUTHORITY_POLICY_VERSION:
        raise KurtosisQCError("Kurtosis authority policy is missing or stale.")
    if (
        evidence.corroborator_registry_version != registry.version
        or evidence.corroborator_registry_fingerprint != registry.fingerprint
    ):
        raise KurtosisQCError("Kurtosis evidence uses a different corroborator registry.")
    decisions = _normalized_decisions(review_decisions)
    scope = review_scope or {}
    if not isinstance(scope, Mapping):
        raise KurtosisQCError("review_scope must be an object.")
    direct_raw = direct_bad_channels or {}
    if not isinstance(direct_raw, Mapping):
        raise KurtosisQCError("direct_bad_channels must map channels to nonempty reasons.")
    direct: dict[str, str] = {}
    retained = _canonical_channels(
        evidence.geometry_identity.get("retained_scalp_channels", ()),
        field_name="geometry_identity.retained_scalp_channels",
    )
    for raw_channel, raw_reason in direct_raw.items():
        channel = str(raw_channel or "").strip()
        reason = str(raw_reason or "").strip()
        if channel not in retained or not reason:
            raise KurtosisQCError(
                "Direct bad channels must be retained BioSemi64 channels with reasons."
            )
        direct[channel] = reason

    evidence_by_channel = {item.channel: item for item in evidence.channels}
    unexplained_missing = set(retained).difference(evidence_by_channel).difference(direct)
    if unexplained_missing:
        raise KurtosisQCError(
            "Retained channels missing from kurtosis evidence lack direct manual/physical "
            f"authority: {', '.join(sorted(unexplained_missing))}."
        )

    findings: list[KurtosisCorroboratorFinding] = []
    seen_findings: set[str] = set()
    for raw_finding in corroborator_findings:
        finding = (
            raw_finding
            if isinstance(raw_finding, KurtosisCorroboratorFinding)
            else KurtosisCorroboratorFinding.from_payload(raw_finding)
        )
        finding.validate()
        if finding.channel not in retained:
            raise KurtosisQCError("Corroborator finding channel is not retained.")
        if finding.evidence_fingerprint in seen_findings:
            raise KurtosisQCError("Duplicate corroborator evidence was supplied.")
        seen_findings.add(finding.evidence_fingerprint)
        findings.append(finding)

    rows: list[KurtosisChannelDecision] = []
    used_decisions: set[str] = set()
    blocking: list[str] = []
    if evidence.status == EVIDENCE_STATUS_UNAVAILABLE:
        blocking.append("kurtosis_evidence_unavailable")
    for channel in retained:
        channel_evidence = evidence_by_channel.get(channel)
        assessments = tuple(
            _assess_corroborator(item, evidence=evidence, registry=registry)
            for item in findings
            if item.channel == channel
        )
        receipt: KurtosisReviewDecision | None = None
        reasons: list[str] = []
        if channel in direct:
            state = CHANNEL_DECISION_DIRECT
            authorized = True
            reasons.extend(("direct_manual_or_physical_authority", direct[channel]))
            if channel in decisions:
                raise KurtosisQCError("A direct bad channel cannot also have a kurtosis review decision.")
        elif channel_evidence is None:
            raise KurtosisQCError("Internal kurtosis channel evidence is missing.")
        elif evidence.status == EVIDENCE_STATUS_UNAVAILABLE:
            state = CHANNEL_DECISION_EVALUATION_UNAVAILABLE
            authorized = False
            reasons.append("kurtosis_evidence_unavailable")
            if channel in decisions:
                raise KurtosisQCError("Unavailable kurtosis evidence cannot consume a review receipt.")
        elif channel_evidence.exceeds_threshold or channel_evidence.validity != CHANNEL_VALIDITY_VALID:
            if channel_evidence.exceeds_threshold:
                reasons.append("kurtosis_threshold_exceeded")
            else:
                reasons.append("kurtosis_statistic_invalid")
            eligible = tuple(item for item in assessments if item.eligible)
            if channel_evidence.exceeds_threshold and eligible:
                state = CHANNEL_DECISION_CORROBORATED_AUTO
                authorized = True
                reasons.extend(
                    f"corroborated:{item.finding.method_id}:{item.finding.method_version}"
                    for item in eligible
                )
                if channel in decisions:
                    raise KurtosisQCError(
                        "A corroborated automatic channel cannot also have a review decision."
                    )
            elif kurtosis_auto_interpolate_all and qualifies_for_experimental_kurtosis_auto_all(channel_evidence.to_payload()):
                state = CHANNEL_DECISION_EXPERIMENTAL_AUTO
                authorized = True
                reasons.append("experimental_all_kurtosis_flags_v1")
                if channel in decisions:
                    # Keep any current receipt for audit, but the selected
                    # project policy is the authority while this option is on.
                    receipt = validate_kurtosis_review_decision(
                        decisions[channel], evidence=evidence, channel_evidence=channel_evidence,
                        review_scope=scope, kurtosis_auto_interpolate_all=True,
                    )
                    used_decisions.add(channel)
            elif channel in decisions:
                receipt = validate_kurtosis_review_decision(
                    decisions[channel],
                    evidence=evidence,
                    channel_evidence=channel_evidence,
                    review_scope=scope,
                    kurtosis_auto_interpolate_all=kurtosis_auto_interpolate_all,
                )
                used_decisions.add(channel)
                if receipt.decision == KURTOSIS_DECISION_APPROVE:
                    experimental = receipt.reviewer_state in {KURTOSIS_REVIEWER_STATE_EXPERIMENTAL_AUTO, KURTOSIS_REVIEWER_STATE_EXPERIMENTAL_AUTO_ALL}
                    state = CHANNEL_DECISION_EXPERIMENTAL_AUTO if experimental else CHANNEL_DECISION_USER_APPROVED
                    authorized = True
                    reasons.append("experimental_abs_z_gt_10_v1" if experimental else "explicit_gui_approval")
                else:
                    state = CHANNEL_DECISION_USER_REJECTED
                    authorized = False
                    reasons.append("explicit_gui_rejection")
            else:
                state = CHANNEL_DECISION_REVIEW_REQUIRED
                authorized = False
                reasons.append("explicit_gui_review_required")
                blocking.append(f"review_required:{channel}")
        else:
            state = CHANNEL_DECISION_CLEAR
            authorized = False
            reasons.append("kurtosis_within_threshold")
            if channel in decisions:
                raise KurtosisQCError("A channel without a current finding cannot consume a review receipt.")
        rows.append(
            KurtosisChannelDecision(
                channel=channel,
                state=state,
                interpolation_authorized=authorized,
                reasons=tuple(reasons),
                channel_evidence_fingerprint=(
                    channel_evidence.fingerprint if channel_evidence is not None else None
                ),
                corroborator_assessments=assessments,
                review_receipt=receipt,
            )
        )

    unused = set(decisions).difference(used_decisions)
    if unused:
        raise KurtosisQCError(
            "Kurtosis review decisions do not match current review-required channels: "
            + ", ".join(sorted(unused))
            + "."
        )
    return KurtosisDecisionPlan(
        method_version=evidence.method_version,
        authority_policy_version=evidence.authority_policy_version,
        registry_version=registry.version,
        registry_fingerprint=registry.fingerprint,
        evidence_fingerprint=evidence.fingerprint,
        ready_for_interpolation=not blocking,
        blocking_reasons=tuple(blocking),
        channel_decisions=tuple(rows),
        kurtosis_auto_interpolate_all=kurtosis_auto_interpolate_all,
    )


def legacy_kurtosis_audit_payload(channels: Sequence[object]) -> dict[str, object]:
    """Label pre-QC-16 automatic kurtosis output without upgrading its authority."""

    normalized = _canonical_channels(channels, field_name="legacy kurtosis channels")
    core: dict[str, object] = {
        "method_version": LEGACY_KURTOSIS_METHOD_VERSION,
        "authority": "legacy_automatic_interpolation_without_review_or_corroboration",
        "channels": list(normalized),
        "evidence_status": "legacy_unknown",
        "review_status": "not_recorded",
        "reuse_status": "stale_requires_reprocessing",
    }
    return {**core, "fingerprint": _fingerprint(core)}


__all__ = [
    "CHANNEL_DECISION_CLEAR",
    "CHANNEL_DECISION_CORROBORATED_AUTO",
    "CHANNEL_DECISION_EXPERIMENTAL_AUTO",
    "CHANNEL_DECISION_DIRECT",
    "CHANNEL_DECISION_EVALUATION_UNAVAILABLE",
    "CHANNEL_DECISION_REVIEW_REQUIRED",
    "CHANNEL_DECISION_USER_APPROVED",
    "CHANNEL_DECISION_USER_REJECTED",
    "CHANNEL_VALIDITY_NONFINITE_INPUT",
    "CHANNEL_VALIDITY_REFERENCE_UNAVAILABLE",
    "CHANNEL_VALIDITY_UNDEFINED_STATISTIC",
    "CHANNEL_VALIDITY_VALID",
    "CORROBORATOR_AUTHORITY_ELIGIBLE",
    "CORROBORATOR_AUTHORITY_REVIEW_ONLY",
    "CORROBORATOR_SCOPE_RECORDING_UNION",
    "CURRENT_KURTOSIS_CORROBORATOR_REGISTRY",
    "ELIGIBLE_KURTOSIS_CORROBORATORS",
    "EVIDENCE_STATUS_PARTIAL",
    "EVIDENCE_STATUS_UNAVAILABLE",
    "EVIDENCE_STATUS_VALID",
    "KURTOSIS_AUTHORITY_POLICY_VERSION",
    "KURTOSIS_CORROBORATOR_REGISTRY_VERSION",
    "KURTOSIS_DECISION_APPROVE",
    "KURTOSIS_DECISION_REJECT",
    "KURTOSIS_MIN_VALID_REFERENCE_CHANNELS",
    "KURTOSIS_QC_METHOD_VERSION",
    "KURTOSIS_REVIEW_DECISION_SCHEMA_VERSION",
    "KURTOSIS_REVIEWER_IDENTITY_STATUS_NOT_COLLECTED",
    "KURTOSIS_REVIEWER_IDENTITY_STATUS_PROVIDED",
    "KURTOSIS_REVIEWER_STATE_EXPLICIT_GUI",
    "KURTOSIS_REVIEWER_STATE_EXPERIMENTAL_AUTO",
    "KURTOSIS_REVIEWER_STATE_EXPERIMENTAL_AUTO_ALL",
    "KURTOSIS_NO_REASON_PROVIDED",
    "KURTOSIS_EXPERIMENTAL_AUTO_Z_THRESHOLD",
    "qualifies_for_experimental_kurtosis_auto",
    "qualifies_for_experimental_kurtosis_auto_all",
    "make_kurtosis_auto_all_decision_receipt",
    "KurtosisChannelDecision",
    "KurtosisChannelEvidence",
    "KurtosisCorroborationAssessment",
    "KurtosisCorroboratorFinding",
    "KurtosisCorroboratorMethod",
    "KurtosisCorroboratorRegistry",
    "KurtosisDecisionPlan",
    "KurtosisOccurrenceScope",
    "KurtosisQCEvidence",
    "KurtosisQCError",
    "KurtosisReferenceDistribution",
    "KurtosisReviewDecision",
    "KurtosisScoringScope",
    "build_kurtosis_decision_plan",
    "build_kurtosis_review_decision",
    "evaluate_kurtosis_qc",
    "legacy_kurtosis_audit_payload",
    "normalize_kurtosis_review_decisions_by_recording",
    "scoring_scope_from_realized_plan",
    "validate_kurtosis_review_decision",
    "validate_kurtosis_review_decision_payload",
]
