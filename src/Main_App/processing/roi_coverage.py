"""GUI-neutral QC-21 source, fixed-ROI, and release coverage contracts."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any

from Main_App.io import (
    BIOSEMI64_CHANNELS,
    BIOSEMI64_COORDINATE_FINGERPRINT,
    BIOSEMI64_GEOMETRY_VERSION,
    BIOSEMI64_MONTAGE_ID,
    BIOSEMI64_SCALP_SET_FINGERPRINT,
    BioSemi64GeometryError,
    biosemi64_geometry_identity,
    read_xlsx_sheet_header,
    read_xlsx_sheet_selected_columns,
)
from Main_App.processing.preprocessing_outcome import (
    INTERPOLATION_STATUS_SUCCEEDED,
    normalize_preprocessing_outcome,
)
from Main_App.processing.recording_condition_outcomes import (
    CELL_BLOCKED,
    CELL_PARTIALLY_RETAINED,
    CELL_READY,
    RecordingConditionOutcomeLedger,
    require_pre_review_readiness,
)
from Main_App.processing.roi_settings import (
    RoiDefinitionSnapshot,
    build_roi_definition_snapshot,
    snapshot_rois_from_settings,
)

ROI_SOURCE_COVERAGE_VERSION = "roi_source_coverage_v1"
ROI_SOURCE_VALIDATION_STAGE = "pre_exclusion"
ROI_COVERAGE_LEDGER_VERSION = "roi_coverage_ledger_v1"
ROI_COVERAGE_STAGE_PRE_REVIEW = "pre_review"
ROI_COVERAGE_STAGE_FINAL = "final"
ROI_COVERAGE_LEDGER_KEY = "roi_coverage"
FINAL_RELEASE_RECEIPT_VERSION = "qc20_final_release_v1"
FINAL_RELEASE_RECEIPT_KEY = "final_release_readiness"

ROI_VALUE_AVAILABLE = "available"
ROI_VALUE_UNAVAILABLE = "unavailable"
ROI_VALUE_NOT_APPLICABLE = "not_applicable"

_BCA_COLUMN_PATTERN = re.compile(r"^[+]?(\d+(?:\.\d+)?)_hz$", re.IGNORECASE)

_CANONICAL_CHANNEL_BY_CASEFOLD = {
    channel.casefold(): channel for channel in BIOSEMI64_CHANNELS
}


class RoiSourceCoverageError(ValueError):
    """Source rows cannot satisfy the frozen QC-21 electrode contract."""


class RoiCoverageGateError(RuntimeError):
    """QC-20/QC-21 coverage cannot release downstream numerical work."""


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _fingerprint(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _scalp_set_fingerprint(channels: Sequence[str]) -> str:
    encoded = json.dumps(
        sorted(channels),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _normalize_scalp_channels(
    values: object,
    *,
    field_name: str,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    if not isinstance(values, Iterable) or isinstance(
        values,
        (Mapping, str, bytes, bytearray),
    ):
        raise RoiSourceCoverageError(f"{field_name} must be a channel collection.")
    materialized = tuple(values)
    if not materialized and not allow_empty:
        raise RoiSourceCoverageError(f"{field_name} cannot be empty.")

    selected: set[str] = set()
    for index, raw_channel in enumerate(materialized, start=1):
        if not isinstance(raw_channel, str):
            raise RoiSourceCoverageError(
                f"{field_name} channel {index} must be text."
            )
        submitted = raw_channel.strip()
        if not submitted:
            raise RoiSourceCoverageError(
                f"{field_name} contains a blank channel at position {index}."
            )
        canonical = _CANONICAL_CHANNEL_BY_CASEFOLD.get(submitted.casefold())
        if canonical is None:
            raise RoiSourceCoverageError(
                f"{field_name} contains unknown BioSemi64 channel {submitted!r}."
            )
        if canonical in selected:
            raise RoiSourceCoverageError(
                f"{field_name} repeats BioSemi64 channel {canonical!r}."
            )
        selected.add(canonical)
    return tuple(channel for channel in BIOSEMI64_CHANNELS if channel in selected)


@dataclass(frozen=True, slots=True)
class RetainedScalpIdentity:
    """Immutable canonical identity for a run's intentional scalp subset."""

    channels: tuple[str, ...]
    montage_id: str = field(default=BIOSEMI64_MONTAGE_ID, init=False)
    geometry_version: str = field(default=BIOSEMI64_GEOMETRY_VERSION, init=False)
    coordinate_fingerprint: str = field(
        default=BIOSEMI64_COORDINATE_FINGERPRINT,
        init=False,
    )
    canonical_scalp_set_fingerprint: str = field(
        default=BIOSEMI64_SCALP_SET_FINGERPRINT,
        init=False,
    )
    retained_scalp_set_fingerprint: str = field(init=False)
    fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        channels = _normalize_scalp_channels(
            self.channels,
            field_name="Retained scalp set",
        )
        object.__setattr__(self, "channels", channels)
        object.__setattr__(
            self,
            "retained_scalp_set_fingerprint",
            _scalp_set_fingerprint(channels),
        )
        object.__setattr__(self, "fingerprint", _fingerprint(self._identity_payload()))

    def _identity_payload(self) -> dict[str, object]:
        return {
            "montage_id": self.montage_id,
            "geometry_version": self.geometry_version,
            "coordinate_fingerprint": self.coordinate_fingerprint,
            "canonical_scalp_set_fingerprint": self.canonical_scalp_set_fingerprint,
            "retained_scalp_channels": list(self.channels),
            "retained_scalp_set_fingerprint": self.retained_scalp_set_fingerprint,
        }

    def to_payload(self) -> dict[str, object]:
        payload = self._identity_payload()
        payload["fingerprint"] = self.fingerprint
        return payload


def freeze_retained_scalp_identity(
    value: RetainedScalpIdentity | Mapping[str, object] | Iterable[str],
) -> RetainedScalpIdentity:
    """Freeze a canonical channel sequence or validate a QC-15 identity."""

    if isinstance(value, RetainedScalpIdentity):
        return value
    if isinstance(value, Mapping):
        raw_channels = value.get("retained_scalp_channels")
        identity = RetainedScalpIdentity(channels=raw_channels)  # type: ignore[arg-type]
        try:
            expected_qc15_identity = biosemi64_geometry_identity(
                electrode_mapping_profile=value.get("electrode_mapping_profile"),
                retained_channels=identity.channels,
            )
        except (BioSemi64GeometryError, TypeError, ValueError) as error:
            raise RoiSourceCoverageError(
                "Retained scalp identity has an invalid electrode mapping profile."
            ) from error
        required_identity_fields = {
            key: expected_qc15_identity[key]
            for key in (
                "montage_id",
                "geometry_version",
                "coordinate_fingerprint",
                "canonical_scalp_set_fingerprint",
                "retained_scalp_set_fingerprint",
                "geometry_identity_fingerprint",
            )
        }
        for key, expected in required_identity_fields.items():
            if value.get(key) != expected:
                raise RoiSourceCoverageError(
                    f"Retained scalp identity has an invalid or missing {key}."
                )
        return identity
    return RetainedScalpIdentity(channels=value)  # type: ignore[arg-type]


def _normalize_columns(values: object, *, field_name: str) -> tuple[str, ...]:
    if not isinstance(values, Sequence) or isinstance(
        values,
        (str, bytes, bytearray),
    ):
        raise RoiSourceCoverageError(f"{field_name} must be an ordered sequence.")
    normalized: list[str] = []
    seen: set[str] = set()
    for index, raw_value in enumerate(values, start=1):
        if not isinstance(raw_value, str):
            raise RoiSourceCoverageError(f"{field_name} item {index} must be text.")
        value = raw_value.strip()
        if not value:
            raise RoiSourceCoverageError(
                f"{field_name} contains a blank value at position {index}."
            )
        folded = value.casefold()
        if folded in seen:
            raise RoiSourceCoverageError(f"{field_name} repeats {value!r}.")
        seen.add(folded)
        normalized.append(value)
    return tuple(normalized)


def _normalize_auxiliary_rows(values: object) -> tuple[str, ...]:
    rows = _normalize_columns(values, field_name="Allowed auxiliary rows")
    for row in rows:
        if row.casefold() in _CANONICAL_CHANNEL_BY_CASEFOLD:
            raise RoiSourceCoverageError(
                f"BioSemi64 scalp channel {row!r} cannot be declared auxiliary."
            )
    return rows


def _materialize_rows(rows: object) -> tuple[Mapping[object, object], ...]:
    to_dict = getattr(rows, "to_dict", None)
    if callable(to_dict):
        try:
            rows = to_dict(orient="records")
        except TypeError:
            pass
    if isinstance(rows, Mapping) or isinstance(rows, (str, bytes, bytearray)):
        raise RoiSourceCoverageError("Source rows must be an iterable of row mappings.")
    if not isinstance(rows, Iterable):
        raise RoiSourceCoverageError("Source rows must be an iterable of row mappings.")
    materialized = tuple(rows)
    for index, row in enumerate(materialized, start=1):
        if not isinstance(row, Mapping):
            raise RoiSourceCoverageError(f"Source row {index} is not a mapping.")
    return materialized


def _normalize_row_keys(
    row: Mapping[object, object],
    *,
    row_number: int,
) -> dict[str, tuple[str, object]]:
    normalized: dict[str, tuple[str, object]] = {}
    for raw_key, value in row.items():
        if not isinstance(raw_key, str):
            raise RoiSourceCoverageError(
                f"Source row {row_number} contains a non-text column name."
            )
        key = raw_key.strip()
        if not key:
            raise RoiSourceCoverageError(
                f"Source row {row_number} contains a blank column name."
            )
        folded = key.casefold()
        if folded in normalized:
            raise RoiSourceCoverageError(
                f"Source row {row_number} repeats column {key!r} ignoring case/whitespace."
            )
        normalized[folded] = (key, value)
    return normalized


def _is_finite_number(value: object) -> bool:
    if isinstance(value, bool) or value is None:
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


@dataclass(frozen=True, slots=True)
class RoiSourceCoverageEvidence:
    """Immutable evidence that source rows passed pre-exclusion validation."""

    retained_scalp_identity: RetainedScalpIdentity
    required_columns: tuple[str, ...]
    explicitly_unavailable_columns: tuple[str, ...]
    observed_scalp_channels: tuple[str, ...]
    allowed_auxiliary_rows: tuple[str, ...]
    observed_auxiliary_rows: tuple[str, ...]
    successfully_interpolated_channels: tuple[str, ...]
    nonfinite_unavailable_values: tuple[tuple[str, tuple[str, ...]], ...]
    method_version: str = field(default=ROI_SOURCE_COVERAGE_VERSION, init=False)
    validation_stage: str = field(default=ROI_SOURCE_VALIDATION_STAGE, init=False)
    fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        if self.observed_scalp_channels != self.retained_scalp_identity.channels:
            raise RoiSourceCoverageError(
                "Validated observed scalp rows must equal the frozen retained set."
            )
        object.__setattr__(self, "fingerprint", _fingerprint(self._identity_payload()))

    @property
    def expected_scalp_channels(self) -> tuple[str, ...]:
        return self.retained_scalp_identity.channels

    @property
    def expected_scalp_count(self) -> int:
        return len(self.expected_scalp_channels)

    @property
    def observed_scalp_count(self) -> int:
        return len(self.observed_scalp_channels)

    @property
    def successfully_interpolated_count(self) -> int:
        return len(self.successfully_interpolated_channels)

    def _identity_payload(self) -> dict[str, object]:
        return {
            "method_version": self.method_version,
            "validation_stage": self.validation_stage,
            "retained_scalp_identity": self.retained_scalp_identity.to_payload(),
            "required_columns": list(self.required_columns),
            "explicitly_unavailable_columns": list(
                self.explicitly_unavailable_columns
            ),
            "expected_scalp_channels": list(self.expected_scalp_channels),
            "observed_scalp_channels": list(self.observed_scalp_channels),
            "expected_scalp_count": self.expected_scalp_count,
            "observed_scalp_count": self.observed_scalp_count,
            "allowed_auxiliary_rows": list(self.allowed_auxiliary_rows),
            "observed_auxiliary_rows": list(self.observed_auxiliary_rows),
            "successfully_interpolated_channels": list(
                self.successfully_interpolated_channels
            ),
            "successfully_interpolated_count": self.successfully_interpolated_count,
            "nonfinite_unavailable_values": {
                column: list(channels)
                for column, channels in self.nonfinite_unavailable_values
            },
        }

    def to_payload(self) -> dict[str, object]:
        payload = self._identity_payload()
        payload["fingerprint"] = self.fingerprint
        return payload


def _source_evidence_from_payload(
    value: Mapping[str, Any],
) -> RoiSourceCoverageEvidence:
    raw_retained = value.get("retained_scalp_identity")
    raw_nonfinite = value.get("nonfinite_unavailable_values")
    if not isinstance(raw_retained, Mapping) or not isinstance(raw_nonfinite, Mapping):
        raise RoiCoverageGateError("Persisted ROI source evidence is malformed.")
    retained = RetainedScalpIdentity(
        channels=tuple(raw_retained.get("retained_scalp_channels") or ()),
    )
    if dict(raw_retained) != retained.to_payload():
        raise RoiCoverageGateError("Persisted retained-scalp identity is stale.")
    evidence = RoiSourceCoverageEvidence(
        retained_scalp_identity=retained,
        required_columns=tuple(value.get("required_columns") or ()),
        explicitly_unavailable_columns=tuple(
            value.get("explicitly_unavailable_columns") or ()
        ),
        observed_scalp_channels=tuple(value.get("observed_scalp_channels") or ()),
        allowed_auxiliary_rows=tuple(value.get("allowed_auxiliary_rows") or ()),
        observed_auxiliary_rows=tuple(value.get("observed_auxiliary_rows") or ()),
        successfully_interpolated_channels=tuple(
            value.get("successfully_interpolated_channels") or ()
        ),
        nonfinite_unavailable_values=tuple(
            (str(column), tuple(channels or ()))
            for column, channels in raw_nonfinite.items()
        ),
    )
    if dict(value) != evidence.to_payload():
        raise RoiCoverageGateError("Persisted ROI source evidence is stale.")
    return evidence


def validate_roi_source_rows(
    rows: object,
    *,
    retained_scalp: RetainedScalpIdentity
    | Mapping[str, object]
    | Iterable[str],
    required_columns: Sequence[str],
    electrode_column: str = "Electrode",
    allowed_auxiliary_rows: Sequence[str] = (),
    successfully_interpolated_channels: Iterable[str] = (),
    unavailable_columns: Sequence[str] = (),
) -> RoiSourceCoverageEvidence:
    """Validate one source table against its frozen retained scalp identity.

    The check intentionally has no exclusion input: the complete source table
    must pass before a later stage may apply scoped electrode exclusions.
    """

    retained = freeze_retained_scalp_identity(retained_scalp)
    required = _normalize_columns(required_columns, field_name="Required columns")
    if not required:
        raise RoiSourceCoverageError("At least one required computable column is needed.")
    unavailable = _normalize_columns(
        unavailable_columns,
        field_name="Unavailable columns",
    )
    required_by_casefold = {column.casefold(): column for column in required}
    unknown_unavailable = [
        column for column in unavailable if column.casefold() not in required_by_casefold
    ]
    if unknown_unavailable:
        raise RoiSourceCoverageError(
            "Unavailable columns are not in the required column set: "
            + ", ".join(unknown_unavailable)
        )
    canonical_unavailable = tuple(
        required_by_casefold[column.casefold()] for column in unavailable
    )
    unavailable_set = {column.casefold() for column in canonical_unavailable}

    if not isinstance(electrode_column, str) or not electrode_column.strip():
        raise RoiSourceCoverageError("The electrode column name cannot be blank.")
    electrode_column = electrode_column.strip()
    if electrode_column.casefold() in required_by_casefold:
        raise RoiSourceCoverageError(
            "The electrode identity column cannot also be a computable column."
        )

    allowed_auxiliary = _normalize_auxiliary_rows(allowed_auxiliary_rows)
    allowed_auxiliary_by_casefold = {
        row.casefold(): row for row in allowed_auxiliary
    }
    interpolated = _normalize_scalp_channels(
        successfully_interpolated_channels,
        field_name="Successfully interpolated channels",
        allow_empty=True,
    )
    outside_retained = [
        channel for channel in interpolated if channel not in retained.channels
    ]
    if outside_retained:
        raise RoiSourceCoverageError(
            "Successfully interpolated channels are outside the retained scalp set: "
            + ", ".join(outside_retained)
        )

    records = _materialize_rows(rows)
    observed_scalp: dict[str, int] = {}
    observed_auxiliary: dict[str, str] = {}
    nonfinite_by_column: dict[str, list[str]] = {
        column: [] for column in canonical_unavailable
    }

    for row_number, raw_row in enumerate(records, start=1):
        row = _normalize_row_keys(raw_row, row_number=row_number)
        electrode_entry = row.get(electrode_column.casefold())
        if electrode_entry is None:
            raise RoiSourceCoverageError(
                f"Source row {row_number} is missing electrode column {electrode_column!r}."
            )
        raw_electrode = electrode_entry[1]
        if not isinstance(raw_electrode, str) or not raw_electrode.strip():
            raise RoiSourceCoverageError(
                f"Source row {row_number} has a blank or non-text electrode identity."
            )
        submitted_electrode = raw_electrode.strip()
        canonical = _CANONICAL_CHANNEL_BY_CASEFOLD.get(
            submitted_electrode.casefold()
        )
        if canonical is not None:
            if canonical not in retained.channels:
                raise RoiSourceCoverageError(
                    f"Source rows contain scalp channel {canonical!r} outside the frozen retained set."
                )
            if canonical in observed_scalp:
                raise RoiSourceCoverageError(
                    f"Source rows repeat scalp channel {canonical!r}."
                )
            observed_scalp[canonical] = row_number
            for required_column in required:
                entry = row.get(required_column.casefold())
                if entry is None:
                    raise RoiSourceCoverageError(
                        f"Source row {canonical!r} is missing required column {required_column!r}."
                    )
                if not _is_finite_number(entry[1]):
                    if required_column.casefold() not in unavailable_set:
                        raise RoiSourceCoverageError(
                            f"Source row {canonical!r} has a nonfinite value in computable column "
                            f"{required_column!r}."
                        )
                    nonfinite_by_column[required_column].append(canonical)
            continue

        auxiliary = allowed_auxiliary_by_casefold.get(
            submitted_electrode.casefold()
        )
        if auxiliary is None:
            raise RoiSourceCoverageError(
                f"Source rows contain undeclared or unknown row {submitted_electrode!r}."
            )
        if auxiliary.casefold() in observed_auxiliary:
            raise RoiSourceCoverageError(
                f"Source rows repeat auxiliary row {auxiliary!r}."
            )
        observed_auxiliary[auxiliary.casefold()] = auxiliary

    missing = [
        channel for channel in retained.channels if channel not in observed_scalp
    ]
    if missing:
        raise RoiSourceCoverageError(
            "Source rows are missing retained scalp channel(s): " + ", ".join(missing)
        )

    observed_scalp_ordered = tuple(
        channel for channel in retained.channels if channel in observed_scalp
    )
    observed_auxiliary_ordered = tuple(
        row for row in allowed_auxiliary if row.casefold() in observed_auxiliary
    )
    nonfinite_evidence = tuple(
        (
            column,
            tuple(
                channel
                for channel in retained.channels
                if channel in nonfinite_by_column[column]
            ),
        )
        for column in canonical_unavailable
    )
    return RoiSourceCoverageEvidence(
        retained_scalp_identity=retained,
        required_columns=required,
        explicitly_unavailable_columns=canonical_unavailable,
        observed_scalp_channels=observed_scalp_ordered,
        allowed_auxiliary_rows=allowed_auxiliary,
        observed_auxiliary_rows=observed_auxiliary_ordered,
        successfully_interpolated_channels=interpolated,
        nonfinite_unavailable_values=nonfinite_evidence,
    )


@dataclass(frozen=True, slots=True)
class RoiMembershipCoverage:
    """Exact membership decision for one recording-condition ROI value."""

    roi_name: str
    expected_channels: tuple[str, ...]
    observed_channels: tuple[str, ...]
    excluded_channels: tuple[str, ...]
    interpolated_channels: tuple[str, ...]
    used_channels: tuple[str, ...]
    status: str
    reason_codes: tuple[str, ...] = ()
    all_members_interpolated_warning: bool = False

    def __post_init__(self) -> None:
        if self.status not in {
            ROI_VALUE_AVAILABLE,
            ROI_VALUE_UNAVAILABLE,
            ROI_VALUE_NOT_APPLICABLE,
        }:
            raise RoiCoverageGateError(
                f"Unsupported ROI coverage status {self.status!r}."
            )
        expected = set(self.expected_channels)
        for label, values in (
            ("observed", self.observed_channels),
            ("excluded", self.excluded_channels),
            ("interpolated", self.interpolated_channels),
            ("used", self.used_channels),
        ):
            if not set(values).issubset(expected):
                raise RoiCoverageGateError(
                    f"ROI {self.roi_name!r} has {label} channels outside its frozen definition."
                )
        if self.status == ROI_VALUE_AVAILABLE:
            if self.observed_channels != self.expected_channels:
                raise RoiCoverageGateError(
                    f"Available ROI {self.roi_name!r} lacks complete observed membership."
                )
            if self.excluded_channels or self.used_channels != self.expected_channels:
                raise RoiCoverageGateError(
                    f"Available ROI {self.roi_name!r} must use its complete frozen set."
                )
        elif self.used_channels:
            raise RoiCoverageGateError(
                f"Unavailable ROI {self.roi_name!r} cannot claim used channels."
            )

    @property
    def configured_count(self) -> int:
        return len(self.expected_channels)

    @property
    def interpolated_count(self) -> int:
        return len(self.interpolated_channels)

    def canonical_payload(self) -> dict[str, object]:
        return {
            "roi_name": self.roi_name,
            "expected_channels": list(self.expected_channels),
            "observed_channels": list(self.observed_channels),
            "excluded_channels": list(self.excluded_channels),
            "interpolated_channels": list(self.interpolated_channels),
            "used_channels": list(self.used_channels),
            "configured_count": self.configured_count,
            "interpolated_count": self.interpolated_count,
            "status": self.status,
            "reason_codes": list(self.reason_codes),
            "all_members_interpolated_warning": self.all_members_interpolated_warning,
        }

    @property
    def fingerprint(self) -> str:
        return _fingerprint(self.canonical_payload())

    def to_payload(self) -> dict[str, object]:
        return {**self.canonical_payload(), "fingerprint": self.fingerprint}

    @classmethod
    def from_payload(cls, value: Mapping[str, Any]) -> "RoiMembershipCoverage":
        result = cls(
            roi_name=str(value.get("roi_name") or ""),
            expected_channels=tuple(value.get("expected_channels") or ()),
            observed_channels=tuple(value.get("observed_channels") or ()),
            excluded_channels=tuple(value.get("excluded_channels") or ()),
            interpolated_channels=tuple(value.get("interpolated_channels") or ()),
            used_channels=tuple(value.get("used_channels") or ()),
            status=str(value.get("status") or ""),
            reason_codes=tuple(value.get("reason_codes") or ()),
            all_members_interpolated_warning=bool(
                value.get("all_members_interpolated_warning")
            ),
        )
        if dict(value) != result.to_payload():
            raise RoiCoverageGateError(
                f"Persisted ROI coverage for {result.roi_name!r} is stale."
            )
        return result


@dataclass(frozen=True, slots=True)
class WholeScalpNormalizationCoverage:
    """Complete frozen denominator availability for one recording-condition."""

    expected_channels: tuple[str, ...]
    observed_channels: tuple[str, ...]
    excluded_channels: tuple[str, ...]
    interpolated_channels: tuple[str, ...]
    used_channels: tuple[str, ...]
    status: str
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        expected = set(self.expected_channels)
        if any(
            not set(values).issubset(expected)
            for values in (
                self.observed_channels,
                self.excluded_channels,
                self.interpolated_channels,
                self.used_channels,
            )
        ):
            raise RoiCoverageGateError(
                "Whole-scalp normalization coverage contains channels outside its frozen set."
            )
        if self.status == ROI_VALUE_AVAILABLE:
            if (
                self.observed_channels != self.expected_channels
                or self.excluded_channels
                or self.used_channels != self.expected_channels
            ):
                raise RoiCoverageGateError(
                    "Available whole-scalp normalization requires its complete frozen set."
                )
        elif self.status not in {ROI_VALUE_UNAVAILABLE, ROI_VALUE_NOT_APPLICABLE}:
            raise RoiCoverageGateError(
                f"Unsupported normalization coverage status {self.status!r}."
            )
        elif self.used_channels:
            raise RoiCoverageGateError(
                "Unavailable whole-scalp normalization cannot claim a denominator set."
            )

    def canonical_payload(self) -> dict[str, object]:
        return {
            "expected_channels": list(self.expected_channels),
            "observed_channels": list(self.observed_channels),
            "excluded_channels": list(self.excluded_channels),
            "interpolated_channels": list(self.interpolated_channels),
            "used_channels": list(self.used_channels),
            "expected_count": len(self.expected_channels),
            "interpolated_count": len(self.interpolated_channels),
            "status": self.status,
            "reason_codes": list(self.reason_codes),
        }

    @property
    def fingerprint(self) -> str:
        return _fingerprint(self.canonical_payload())

    def to_payload(self) -> dict[str, object]:
        return {**self.canonical_payload(), "fingerprint": self.fingerprint}

    @classmethod
    def from_payload(
        cls,
        value: Mapping[str, Any],
    ) -> "WholeScalpNormalizationCoverage":
        result = cls(
            expected_channels=tuple(value.get("expected_channels") or ()),
            observed_channels=tuple(value.get("observed_channels") or ()),
            excluded_channels=tuple(value.get("excluded_channels") or ()),
            interpolated_channels=tuple(value.get("interpolated_channels") or ()),
            used_channels=tuple(value.get("used_channels") or ()),
            status=str(value.get("status") or ""),
            reason_codes=tuple(value.get("reason_codes") or ()),
        )
        if dict(value) != result.to_payload():
            raise RoiCoverageGateError(
                "Persisted whole-scalp normalization coverage is stale."
            )
        return result


@dataclass(frozen=True, slots=True)
class RecordingConditionRoiCoverage:
    """QC-21 coverage for one exact QC-20 expected cell."""

    cell_id: str
    recording_id: str
    participant_id: str
    condition_label: str
    outcome_status: str
    workbook_path: str
    source_evidence: RoiSourceCoverageEvidence | None
    roi_memberships: tuple[RoiMembershipCoverage, ...]
    whole_scalp_normalization: WholeScalpNormalizationCoverage | None
    downstream_cell_excluded: bool = False
    decision_reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        contributing = self.outcome_status in {CELL_READY, CELL_PARTIALLY_RETAINED}
        if contributing:
            if self.source_evidence is None or not self.workbook_path:
                raise RoiCoverageGateError(
                    f"Contributing cell {self.cell_id!r} lacks validated source evidence."
                )
            if self.whole_scalp_normalization is None:
                raise RoiCoverageGateError(
                    f"Contributing cell {self.cell_id!r} lacks normalization coverage."
                )
        elif self.source_evidence is not None or self.roi_memberships:
            raise RoiCoverageGateError(
                f"No-output cell {self.cell_id!r} cannot claim ROI source coverage."
            )

    def canonical_payload(self) -> dict[str, object]:
        return {
            "cell_id": self.cell_id,
            "recording_id": self.recording_id,
            "participant_id": self.participant_id,
            "condition_label": self.condition_label,
            "outcome_status": self.outcome_status,
            "workbook_path": self.workbook_path,
            "source_evidence": (
                self.source_evidence.to_payload()
                if self.source_evidence is not None
                else None
            ),
            "roi_memberships": [row.to_payload() for row in self.roi_memberships],
            "whole_scalp_normalization": (
                self.whole_scalp_normalization.to_payload()
                if self.whole_scalp_normalization is not None
                else None
            ),
            "downstream_cell_excluded": self.downstream_cell_excluded,
            "decision_reason_codes": list(self.decision_reason_codes),
        }

    @property
    def fingerprint(self) -> str:
        return _fingerprint(self.canonical_payload())

    def to_payload(self) -> dict[str, object]:
        return {**self.canonical_payload(), "fingerprint": self.fingerprint}

    @classmethod
    def from_payload(
        cls,
        value: Mapping[str, Any],
    ) -> "RecordingConditionRoiCoverage":
        raw_source = value.get("source_evidence")
        raw_rois = value.get("roi_memberships")
        raw_normalization = value.get("whole_scalp_normalization")
        if not isinstance(raw_rois, Sequence) or isinstance(raw_rois, (str, bytes)):
            raise RoiCoverageGateError("Persisted recording-condition ROI rows are malformed.")
        result = cls(
            cell_id=str(value.get("cell_id") or ""),
            recording_id=str(value.get("recording_id") or ""),
            participant_id=str(value.get("participant_id") or ""),
            condition_label=str(value.get("condition_label") or ""),
            outcome_status=str(value.get("outcome_status") or ""),
            workbook_path=str(value.get("workbook_path") or ""),
            source_evidence=(
                _source_evidence_from_payload(raw_source)
                if isinstance(raw_source, Mapping)
                else None
            ),
            roi_memberships=tuple(
                RoiMembershipCoverage.from_payload(row)
                for row in raw_rois
                if isinstance(row, Mapping)
            ),
            whole_scalp_normalization=(
                WholeScalpNormalizationCoverage.from_payload(raw_normalization)
                if isinstance(raw_normalization, Mapping)
                else None
            ),
            downstream_cell_excluded=bool(value.get("downstream_cell_excluded")),
            decision_reason_codes=tuple(value.get("decision_reason_codes") or ()),
        )
        if len(result.roi_memberships) != len(raw_rois) or dict(value) != result.to_payload():
            raise RoiCoverageGateError(
                f"Persisted ROI coverage cell {result.cell_id!r} is stale."
            )
        return result


@dataclass(frozen=True, slots=True)
class RoiCoverageLedger:
    """Durable QC-21 result bound to one complete QC-20 matrix."""

    stage: str
    outcome_ledger_fingerprint: str
    roi_snapshot: RoiDefinitionSnapshot
    cells: tuple[RecordingConditionRoiCoverage, ...]
    decision_fingerprint: str = ""
    review_complete: bool = False
    decision_payload: Mapping[str, object] = field(default_factory=dict)
    method_version: str = field(default=ROI_COVERAGE_LEDGER_VERSION, init=False)

    def __post_init__(self) -> None:
        if self.stage not in {
            ROI_COVERAGE_STAGE_PRE_REVIEW,
            ROI_COVERAGE_STAGE_FINAL,
        }:
            raise RoiCoverageGateError(f"Unsupported ROI coverage stage {self.stage!r}.")
        if not self.outcome_ledger_fingerprint:
            raise RoiCoverageGateError("ROI coverage lacks its QC-20 ledger identity.")
        if self.stage == ROI_COVERAGE_STAGE_FINAL:
            if not self.review_complete or not self.decision_fingerprint:
                raise RoiCoverageGateError(
                    "Final ROI coverage requires a completed reviewed-decision identity."
                )
        identities = [cell.cell_id.casefold() for cell in self.cells]
        if len(identities) != len(set(identities)):
            raise RoiCoverageGateError("ROI coverage repeats a recording-condition cell.")

    def canonical_payload(self) -> dict[str, object]:
        return {
            "version": self.method_version,
            "stage": self.stage,
            "outcome_ledger_fingerprint": self.outcome_ledger_fingerprint,
            "roi_snapshot": self.roi_snapshot.to_payload(),
            "decision_fingerprint": self.decision_fingerprint,
            "review_complete": self.review_complete,
            "decision_payload": dict(self.decision_payload),
            "cells": [cell.to_payload() for cell in self.cells],
        }

    @property
    def fingerprint(self) -> str:
        return _fingerprint(self.canonical_payload())

    def to_payload(self) -> dict[str, object]:
        return {**self.canonical_payload(), "fingerprint": self.fingerprint}

    def cell_for(
        self,
        recording_id: object,
        condition_label: object,
    ) -> RecordingConditionRoiCoverage | None:
        recording_key = str(recording_id or "").strip().casefold()
        condition_key = str(condition_label or "").strip().casefold()
        return next(
            (
                cell
                for cell in self.cells
                if cell.recording_id.casefold() == recording_key
                and cell.condition_label.casefold() == condition_key
            ),
            None,
        )

    @classmethod
    def from_payload(cls, value: Mapping[str, Any]) -> "RoiCoverageLedger":
        if value.get("version") != ROI_COVERAGE_LEDGER_VERSION:
            raise RoiCoverageGateError("Persisted ROI coverage version is stale.")
        raw_snapshot = value.get("roi_snapshot")
        raw_cells = value.get("cells")
        raw_decision = value.get("decision_payload")
        if (
            not isinstance(raw_snapshot, Mapping)
            or not isinstance(raw_cells, Sequence)
            or isinstance(raw_cells, (str, bytes))
            or not isinstance(raw_decision, Mapping)
        ):
            raise RoiCoverageGateError("Persisted ROI coverage ledger is malformed.")
        raw_rois = raw_snapshot.get("rois")
        if not isinstance(raw_rois, Sequence) or isinstance(raw_rois, (str, bytes)):
            raise RoiCoverageGateError("Persisted ROI snapshot is malformed.")
        snapshot = build_roi_definition_snapshot(
            [
                (row.get("name"), row.get("electrodes"))
                for row in raw_rois
                if isinstance(row, Mapping)
            ]
        )
        if len(snapshot.rois) != len(raw_rois) or dict(raw_snapshot) != snapshot.to_payload():
            raise RoiCoverageGateError("Persisted ROI snapshot is stale.")
        result = cls(
            stage=str(value.get("stage") or ""),
            outcome_ledger_fingerprint=str(
                value.get("outcome_ledger_fingerprint") or ""
            ),
            roi_snapshot=snapshot,
            decision_fingerprint=str(value.get("decision_fingerprint") or ""),
            review_complete=bool(value.get("review_complete")),
            decision_payload=dict(raw_decision),
            cells=tuple(
                RecordingConditionRoiCoverage.from_payload(row)
                for row in raw_cells
                if isinstance(row, Mapping)
            ),
        )
        if len(result.cells) != len(raw_cells) or dict(value) != result.to_payload():
            raise RoiCoverageGateError("Persisted ROI coverage ledger is stale.")
        return result


def _dataset_index_identity_payload(dataset_index: Any) -> dict[str, object]:
    def _path(value: object) -> str:
        return str(Path(str(value)).expanduser().resolve(strict=False))

    def _workbook_rows(values: object, *, disposition: str) -> list[dict[str, object]]:
        return sorted(
            [
                {
                    "disposition": disposition,
                    "participant_id": str(getattr(row, "participant_id", "")),
                    "recording_id": str(getattr(row, "recording_id", "") or ""),
                    "condition": str(getattr(row, "condition", "")),
                    "group_id": str(getattr(row, "group_id", "") or ""),
                    "session_id": str(getattr(row, "session_id", "") or ""),
                    "visit_index": getattr(row, "visit_index", None),
                    "path": _path(getattr(row, "path", "")),
                }
                for row in values or ()
            ],
            key=lambda row: (
                str(row["recording_id"] or row["participant_id"]).casefold(),
                str(row["condition"]).casefold(),
                str(row["path"]).casefold(),
                str(row["disposition"]),
            ),
        )

    groups = sorted(
        (
            str(getattr(row, "group_id", "")),
            str(getattr(row, "label", "")),
        )
        for row in (getattr(dataset_index, "groups", {}) or {}).values()
    )
    participants = sorted(
        (
            str(getattr(row, "participant_id", "")),
            str(getattr(row, "group_id", "") or ""),
        )
        for row in (getattr(dataset_index, "participants", {}) or {}).values()
    )
    sessions = sorted(
        (
            str(getattr(row, "session_id", "")),
            str(getattr(row, "label", "")),
            getattr(row, "visit_index", None),
        )
        for row in (getattr(dataset_index, "sessions", {}) or {}).values()
    )
    recordings = sorted(
        (
            str(getattr(row, "recording_id", "")),
            str(getattr(row, "participant_id", "")),
            str(getattr(row, "session_id", "")),
            str(getattr(row, "source_id", "")),
            getattr(row, "visit_index", None),
        )
        for row in (getattr(dataset_index, "recordings", {}) or {}).values()
    )
    return {
        "project_root": _path(getattr(dataset_index, "project_root", "")),
        "groups": groups,
        "participants": participants,
        "sessions": sessions,
        "recordings": recordings,
        "workbooks": [
            *_workbook_rows(
                getattr(dataset_index, "workbooks", ()),
                disposition="included",
            ),
            *_workbook_rows(
                getattr(dataset_index, "excluded_workbooks", ()),
                disposition="excluded",
            ),
        ],
    }


def require_canonical_released_dataset_index(
    project_root: str | Path,
    dataset_index: Any | None = None,
    *,
    final_coverage: RoiCoverageLedger | None = None,
) -> Any:
    """Return a fresh canonical index after rejecting stale same-root identity."""

    from Main_App.projects import load_project_dataset_index

    root = _resolved_project_root(project_root)
    canonical = load_project_dataset_index(root)
    if dataset_index is not None:
        supplied_root = Path(dataset_index.project_root).expanduser().resolve(
            strict=False
        )
        if supplied_root != root:
            raise ValueError(
                "The supplied dataset index belongs to a different project root."
            )
        if _dataset_index_identity_payload(dataset_index) != (
            _dataset_index_identity_payload(canonical)
        ):
            raise RoiCoverageGateError(
                "The supplied dataset index has stale participant, group, session, "
                "recording, condition, or workbook identity. Reload the project."
            )

    if final_coverage is not None:
        records = [*canonical.workbooks, *canonical.excluded_workbooks]
        for cell in final_coverage.cells:
            if cell.source_evidence is None:
                continue
            matches = [
                record
                for record in records
                if str(record.recording_id or record.participant_id).casefold()
                == cell.recording_id.casefold()
                and str(record.condition).casefold()
                == cell.condition_label.casefold()
            ]
            if len(matches) != 1:
                raise RoiCoverageGateError(
                    "The canonical dataset index does not uniquely match released "
                    f"coverage for {cell.recording_id}/{cell.condition_label}."
                )
            record = matches[0]
            if (
                str(record.participant_id).casefold()
                != cell.participant_id.casefold()
                or Path(record.path).resolve(strict=False)
                != Path(cell.workbook_path).resolve(strict=False)
            ):
                raise RoiCoverageGateError(
                    "The canonical dataset index identity differs from released "
                    f"coverage for {cell.recording_id}/{cell.condition_label}."
                )
    return canonical


@dataclass(frozen=True, slots=True)
class FinalReleaseReceipt:
    """QC-20 proof that reviewed coverage may enter numerical consumers."""

    outcome_ledger_fingerprint: str
    roi_coverage_fingerprint: str
    decision_fingerprint: str
    status: str = "passed"
    version: str = field(default=FINAL_RELEASE_RECEIPT_VERSION, init=False)

    def canonical_payload(self) -> dict[str, object]:
        return {
            "version": self.version,
            "status": self.status,
            "outcome_ledger_fingerprint": self.outcome_ledger_fingerprint,
            "roi_coverage_fingerprint": self.roi_coverage_fingerprint,
            "decision_fingerprint": self.decision_fingerprint,
        }

    @property
    def fingerprint(self) -> str:
        return _fingerprint(self.canonical_payload())

    def to_payload(self) -> dict[str, object]:
        return {**self.canonical_payload(), "fingerprint": self.fingerprint}

    @classmethod
    def from_payload(cls, value: Mapping[str, Any]) -> "FinalReleaseReceipt":
        if value.get("version") != FINAL_RELEASE_RECEIPT_VERSION:
            raise RoiCoverageGateError("Final-release receipt version is stale.")
        result = cls(
            outcome_ledger_fingerprint=str(
                value.get("outcome_ledger_fingerprint") or ""
            ),
            roi_coverage_fingerprint=str(
                value.get("roi_coverage_fingerprint") or ""
            ),
            decision_fingerprint=str(value.get("decision_fingerprint") or ""),
            status=str(value.get("status") or ""),
        )
        if result.status != "passed" or dict(value) != result.to_payload():
            raise RoiCoverageGateError("Final-release receipt is stale or did not pass.")
        return result


def _resolved_project_root(project: Any) -> Path:
    raw_root = getattr(project, "project_root", project)
    if raw_root in (None, ""):
        raise RoiCoverageGateError("ROI coverage requires an active project root.")
    return Path(raw_root).expanduser().resolve(strict=False)


def _processing_entry(
    processing_ledger: Mapping[str, Any],
    processing_id: str,
) -> Mapping[str, Any]:
    raw_entries = processing_ledger.get("entries")
    if not isinstance(raw_entries, Mapping):
        raise RoiCoverageGateError("The processing ledger has no recording entries.")
    wanted = processing_id.casefold()
    matches = [
        entry
        for key, entry in raw_entries.items()
        if str(key).casefold() == wanted and isinstance(entry, Mapping)
    ]
    if len(matches) != 1:
        raise RoiCoverageGateError(
            f"Recording {processing_id!r} lacks one exact processing-ledger entry."
        )
    return matches[0]


def _successful_interpolation_provenance(
    processing_ledger: Mapping[str, Any],
    processing_id: str,
) -> tuple[tuple[str, ...], dict[str, object]]:
    entry = _processing_entry(processing_ledger, processing_id)
    try:
        outcome = normalize_preprocessing_outcome(entry)
    except (TypeError, ValueError) as error:
        raise RoiCoverageGateError(
            f"Recording {processing_id!r} has invalid preprocessing outcome provenance."
        ) from error
    if not outcome.is_current:
        raise RoiCoverageGateError(
            f"Recording {processing_id!r} has legacy/unknown interpolation provenance."
        )
    successful = (
        _normalize_scalp_channels(
            outcome.interpolation_successful_channels,
            field_name="Successfully interpolated channels",
            allow_empty=True,
        )
        if outcome.interpolation_status == INTERPOLATION_STATUS_SUCCEEDED
        else ()
    )
    return successful, outcome.to_payload()


def _bca_columns_for_workbook(path: Path) -> tuple[str, ...]:
    try:
        header = read_xlsx_sheet_header(path, sheet_name="BCA (uV)")
    except (OSError, ValueError) as error:
        raise RoiCoverageGateError(
            f"Cannot read the BCA source table for ROI coverage: {path}"
        ) from error
    columns = tuple(
        str(column).strip()
        for column in header
        if _BCA_COLUMN_PATTERN.fullmatch(str(column).strip())
    )
    if not columns:
        raise RoiCoverageGateError(
            f"The BCA source table has no exact frequency columns: {path}"
        )
    if len({column.casefold() for column in columns}) != len(columns):
        raise RoiCoverageGateError(
            f"The BCA source table repeats a frequency column: {path}"
        )
    return columns


def _truthy_cell(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return math.isfinite(float(value)) and bool(float(value))
        except (TypeError, ValueError):
            return False
    return str(value or "").strip().casefold() in {"true", "yes", "1"}


def _unavailable_bca_columns(
    path: Path,
    *,
    bca_columns: Sequence[str],
) -> tuple[str, ...]:
    try:
        frame = read_xlsx_sheet_selected_columns(
            path,
            sheet_name="Spectral Eligibility",
            required_columns=["Target Frequency (Hz)", "BCA Available"],
        )
    except (OSError, ValueError) as error:
        raise RoiCoverageGateError(
            f"The workbook lacks current Spectral Eligibility evidence: {path}"
        ) from error
    decisions: dict[str, bool] = {}
    for _, row in frame.iterrows():
        try:
            column = f"{float(row['Target Frequency (Hz)']):.4f}_Hz"
        except (TypeError, ValueError, OverflowError) as error:
            raise RoiCoverageGateError(
                f"The workbook has an invalid spectral target identity: {path}"
            ) from error
        key = column.casefold()
        available = _truthy_cell(row["BCA Available"])
        if key in decisions and decisions[key] is not available:
            raise RoiCoverageGateError(
                f"The workbook has conflicting BCA availability rows for {column}: {path}"
            )
        decisions[key] = available
    missing = [column for column in bca_columns if column.casefold() not in decisions]
    if missing:
        raise RoiCoverageGateError(
            "Spectral Eligibility does not account for BCA column(s) "
            + ", ".join(missing)
            + f": {path}"
        )
    return tuple(
        column for column in bca_columns if not decisions[column.casefold()]
    )


def _source_evidence_for_cell(
    cell: Any,
    *,
    processing_ledger: Mapping[str, Any],
    roi_snapshot: RoiDefinitionSnapshot,
) -> tuple[RoiSourceCoverageEvidence, dict[str, object]]:
    receipt = cell.export_receipt
    if not isinstance(receipt, Mapping):
        raise RoiCoverageGateError(
            f"Contributing cell {cell.cell_id!r} has no current export receipt."
        )
    workbook_path = Path(str(receipt.get("path") or "")).resolve(strict=False)
    geometry = receipt.get("geometry")
    if not isinstance(geometry, Mapping):
        raise RoiCoverageGateError(
            f"Contributing cell {cell.cell_id!r} has no frozen geometry identity."
        )
    retained = freeze_retained_scalp_identity(geometry)
    retained_set = set(retained.channels)
    outside = [
        f"{roi.name}: {channel}"
        for roi in roi_snapshot.rois
        for channel in roi.electrodes
        if channel not in retained_set
    ]
    if outside:
        raise RoiCoverageGateError(
            "Configured ROI member(s) are outside the run's frozen retained scalp set: "
            + ", ".join(outside)
        )
    interpolated, interpolation_outcome = _successful_interpolation_provenance(
        processing_ledger,
        cell.processing_id,
    )
    bca_columns = _bca_columns_for_workbook(workbook_path)
    unavailable_columns = _unavailable_bca_columns(
        workbook_path,
        bca_columns=bca_columns,
    )
    source_rows = read_xlsx_sheet_selected_columns(
        workbook_path,
        sheet_name="BCA (uV)",
        required_columns=["Electrode", *bca_columns],
    )
    try:
        evidence = validate_roi_source_rows(
            source_rows,
            retained_scalp=retained,
            required_columns=bca_columns,
            successfully_interpolated_channels=interpolated,
            unavailable_columns=unavailable_columns,
        )
    except RoiSourceCoverageError as error:
        raise RoiCoverageGateError(
            f"QC-21 source validation failed for {cell.processing_id}/"
            f"{cell.condition_label}: {error}"
        ) from error
    return evidence, interpolation_outcome


def _roi_memberships(
    snapshot: RoiDefinitionSnapshot,
    source: RoiSourceCoverageEvidence,
    *,
    excluded_channels: Iterable[str] = (),
    downstream_cell_excluded: bool = False,
) -> tuple[RoiMembershipCoverage, ...]:
    excluded = set(
        _normalize_scalp_channels(
            excluded_channels,
            field_name="Reviewed excluded channels",
            allow_empty=True,
        )
    )
    observed = set(source.observed_scalp_channels)
    interpolated = set(source.successfully_interpolated_channels)
    rows: list[RoiMembershipCoverage] = []
    for roi in snapshot.rois:
        expected = roi.electrodes
        observed_members = tuple(channel for channel in expected if channel in observed)
        excluded_members = tuple(channel for channel in expected if channel in excluded)
        interpolated_members = tuple(
            channel for channel in expected if channel in interpolated
        )
        unavailable = downstream_cell_excluded or bool(excluded_members)
        reasons = (
            ("reviewed_recording_condition_exclusion",)
            if downstream_cell_excluded
            else ("reviewed_required_electrode_exclusion",)
            if excluded_members
            else ()
        )
        rows.append(
            RoiMembershipCoverage(
                roi_name=roi.name,
                expected_channels=expected,
                observed_channels=observed_members,
                excluded_channels=excluded_members,
                interpolated_channels=interpolated_members,
                used_channels=() if unavailable else expected,
                status=ROI_VALUE_UNAVAILABLE if unavailable else ROI_VALUE_AVAILABLE,
                reason_codes=reasons,
                all_members_interpolated_warning=(
                    bool(expected) and set(expected).issubset(interpolated)
                ),
            )
        )
    return tuple(rows)


def _normalization_coverage(
    source: RoiSourceCoverageEvidence,
    *,
    excluded_channels: Iterable[str] = (),
    downstream_cell_excluded: bool = False,
) -> WholeScalpNormalizationCoverage:
    expected = source.expected_scalp_channels
    excluded_set = set(
        _normalize_scalp_channels(
            excluded_channels,
            field_name="Reviewed excluded channels",
            allow_empty=True,
        )
    )
    excluded = tuple(channel for channel in expected if channel in excluded_set)
    unavailable = downstream_cell_excluded or bool(excluded)
    return WholeScalpNormalizationCoverage(
        expected_channels=expected,
        observed_channels=source.observed_scalp_channels,
        excluded_channels=excluded,
        interpolated_channels=source.successfully_interpolated_channels,
        used_channels=() if unavailable else expected,
        status=ROI_VALUE_UNAVAILABLE if unavailable else ROI_VALUE_AVAILABLE,
        reason_codes=(
            ("reviewed_recording_condition_exclusion",)
            if downstream_cell_excluded
            else ("reviewed_normalization_member_exclusion",)
            if excluded
            else ()
        ),
    )


def _decision_attribute(value: object, name: str, default: object) -> object:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _decision_pairs(value: object) -> dict[tuple[str, str], object]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[tuple[str, str], object] = {}
    for raw_key, payload in value.items():
        if (
            not isinstance(raw_key, Sequence)
            or isinstance(raw_key, (str, bytes))
            or len(raw_key) != 2
        ):
            continue
        result[(str(raw_key[0]).casefold(), str(raw_key[1]).casefold())] = payload
    return result


def _decision_channel_pairs(value: object) -> dict[tuple[str, str], frozenset[str]]:
    pairs = _decision_pairs(value)
    return {
        key: frozenset(
            _normalize_scalp_channels(
                channels,
                field_name="Reviewed excluded channels",
                allow_empty=True,
            )
        )
        for key, channels in pairs.items()
    }


def _decision_set(value: object) -> frozenset[str]:
    if not isinstance(value, Iterable) or isinstance(
        value,
        (Mapping, str, bytes, bytearray),
    ):
        return frozenset()
    return frozenset(str(item).strip().casefold() for item in value if str(item).strip())


def _decision_payload(value: object) -> dict[str, object]:
    to_payload = getattr(value, "to_payload", None)
    if callable(to_payload):
        payload = to_payload()
    elif isinstance(value, Mapping):
        payload = value
    else:
        raise RoiCoverageGateError(
            "Reviewed frequency decisions do not expose durable provenance."
        )
    if not isinstance(payload, Mapping):
        raise RoiCoverageGateError(
            "Reviewed frequency decision provenance is malformed."
        )
    try:
        # Reject tuple keys or other in-memory-only structures before persistence.
        return json.loads(_canonical_json(dict(payload)))
    except (TypeError, ValueError) as error:
        raise RoiCoverageGateError(
            "Reviewed frequency decisions are not JSON-persistable."
        ) from error


def _cell_decisions(
    decisions: object,
    *,
    recording_id: str,
    participant_id: str,
    condition_label: str,
) -> tuple[bool, tuple[str, ...], tuple[str, ...]]:
    recording_key = recording_id.casefold()
    participant_key = participant_id.casefold()
    condition_key = condition_label.casefold()
    excluded_recordings = _decision_set(
        _decision_attribute(decisions, "excluded_recordings", ())
    )
    excluded_participants = _decision_set(
        _decision_attribute(decisions, "excluded_participants", ())
    )
    recording_conditions = _decision_pairs(
        _decision_attribute(decisions, "excluded_recording_conditions", {})
    )
    participant_conditions = _decision_pairs(
        _decision_attribute(decisions, "excluded_participant_conditions", {})
    )
    recording_electrodes = _decision_channel_pairs(
        _decision_attribute(
            decisions,
            "excluded_electrodes_by_recording_condition",
            {},
        )
    )
    participant_electrodes = _decision_channel_pairs(
        _decision_attribute(
            decisions,
            "excluded_electrodes_by_participant_condition",
            {},
        )
    )
    reasons: list[str] = []
    if recording_key in excluded_recordings:
        reasons.append("reviewed_recording_exclusion")
    if participant_key in excluded_participants:
        reasons.append("reviewed_participant_exclusion")
    if (recording_key, condition_key) in recording_conditions:
        reasons.append("reviewed_recording_condition_exclusion")
    if (participant_key, condition_key) in participant_conditions:
        reasons.append("reviewed_participant_condition_exclusion")
    excluded_channels = set(
        recording_electrodes.get((recording_key, condition_key), frozenset())
    )
    excluded_channels.update(
        participant_electrodes.get((participant_key, condition_key), frozenset())
    )
    downstream_cell_excluded = bool(reasons)
    return (
        downstream_cell_excluded,
        tuple(
            channel for channel in BIOSEMI64_CHANNELS if channel in excluded_channels
        ),
        tuple(reasons),
    )


def _no_output_coverage(cell: Any) -> RecordingConditionRoiCoverage:
    return RecordingConditionRoiCoverage(
        cell_id=cell.cell_id,
        recording_id=cell.processing_id,
        participant_id=cell.participant_id,
        condition_label=cell.condition_label,
        outcome_status=cell.status,
        workbook_path="",
        source_evidence=None,
        roi_memberships=(),
        whole_scalp_normalization=None,
        downstream_cell_excluded=False,
        decision_reason_codes=tuple(cell.reason_codes),
    )


def build_pre_review_roi_coverage(
    project: Any,
    *,
    outcome_ledger: RecordingConditionOutcomeLedger,
    processing_ledger: Mapping[str, Any] | None = None,
    roi_snapshot: RoiDefinitionSnapshot | None = None,
    persist: bool = True,
) -> RoiCoverageLedger:
    """Validate and freeze complete source rows before frequency review."""

    require_pre_review_readiness(outcome_ledger)
    root = _resolved_project_root(project)
    if processing_ledger is None:
        from Main_App.processing.processing_ledger import load_ledger

        processing_ledger = load_ledger(root)
    snapshot = roi_snapshot or snapshot_rois_from_settings()
    if not snapshot.rois:
        raise RoiCoverageGateError("At least one frozen ROI is required.")
    cells: list[RecordingConditionRoiCoverage] = []
    for cell in outcome_ledger.cells:
        if cell.status not in {CELL_READY, CELL_PARTIALLY_RETAINED}:
            cells.append(_no_output_coverage(cell))
            continue
        source, interpolation_outcome = _source_evidence_for_cell(
            cell,
            processing_ledger=processing_ledger,
            roi_snapshot=snapshot,
        )
        receipt = cell.export_receipt or {}
        cells.append(
            RecordingConditionRoiCoverage(
                cell_id=cell.cell_id,
                recording_id=cell.processing_id,
                participant_id=cell.participant_id,
                condition_label=cell.condition_label,
                outcome_status=cell.status,
                workbook_path=str(receipt.get("path") or ""),
                source_evidence=source,
                roi_memberships=_roi_memberships(snapshot, source),
                whole_scalp_normalization=_normalization_coverage(source),
                decision_reason_codes=(
                    "pre_review_source_validated",
                    "interpolation_provenance_current",
                    str(interpolation_outcome.get("interpolation_status") or ""),
                ),
            )
        )
    coverage = RoiCoverageLedger(
        stage=ROI_COVERAGE_STAGE_PRE_REVIEW,
        outcome_ledger_fingerprint=outcome_ledger.fingerprint,
        roi_snapshot=snapshot,
        cells=tuple(cells),
    )
    _require_coverage_matrix(outcome_ledger, coverage)
    if persist:
        persist_roi_coverage(root, coverage)
    return coverage


def build_final_roi_coverage(
    project: Any,
    *,
    outcome_ledger: RecordingConditionOutcomeLedger,
    frequency_decisions: object,
    pre_review_coverage: RoiCoverageLedger | None = None,
    persist: bool = True,
) -> RoiCoverageLedger:
    """Apply reviewed decisions to the frozen pre-review QC-21 coverage."""

    root = _resolved_project_root(project)
    if pre_review_coverage is None:
        pre_review_coverage = load_roi_coverage(
            root,
            stage=ROI_COVERAGE_STAGE_PRE_REVIEW,
        )
    if pre_review_coverage is None:
        raise RoiCoverageGateError(
            "Final ROI coverage requires current pre-review source validation."
        )
    _require_coverage_matrix(outcome_ledger, pre_review_coverage)
    if pre_review_coverage.stage != ROI_COVERAGE_STAGE_PRE_REVIEW:
        raise RoiCoverageGateError("Final ROI coverage received the wrong stage.")
    review_complete = bool(
        _decision_attribute(frequency_decisions, "review_complete", False)
    )
    decision_fingerprint = str(
        _decision_attribute(frequency_decisions, "decision_fingerprint", "") or ""
    ).strip()
    if not review_complete or not decision_fingerprint:
        raise RoiCoverageGateError(
            "Final ROI coverage requires completed QC-03/QC-17 review decisions."
        )
    pre_by_id = {cell.cell_id.casefold(): cell for cell in pre_review_coverage.cells}
    final_cells: list[RecordingConditionRoiCoverage] = []
    for outcome_cell in outcome_ledger.cells:
        pre_cell = pre_by_id[outcome_cell.cell_id.casefold()]
        if pre_cell.source_evidence is None:
            final_cells.append(_no_output_coverage(outcome_cell))
            continue
        downstream_excluded, excluded_channels, reasons = _cell_decisions(
            frequency_decisions,
            recording_id=outcome_cell.processing_id,
            participant_id=outcome_cell.participant_id,
            condition_label=outcome_cell.condition_label,
        )
        final_cells.append(
            RecordingConditionRoiCoverage(
                cell_id=pre_cell.cell_id,
                recording_id=pre_cell.recording_id,
                participant_id=pre_cell.participant_id,
                condition_label=pre_cell.condition_label,
                outcome_status=pre_cell.outcome_status,
                workbook_path=pre_cell.workbook_path,
                source_evidence=pre_cell.source_evidence,
                roi_memberships=_roi_memberships(
                    pre_review_coverage.roi_snapshot,
                    pre_cell.source_evidence,
                    excluded_channels=excluded_channels,
                    downstream_cell_excluded=downstream_excluded,
                ),
                whole_scalp_normalization=_normalization_coverage(
                    pre_cell.source_evidence,
                    excluded_channels=excluded_channels,
                    downstream_cell_excluded=downstream_excluded,
                ),
                downstream_cell_excluded=downstream_excluded,
                decision_reason_codes=reasons,
            )
        )
    coverage = RoiCoverageLedger(
        stage=ROI_COVERAGE_STAGE_FINAL,
        outcome_ledger_fingerprint=outcome_ledger.fingerprint,
        roi_snapshot=pre_review_coverage.roi_snapshot,
        cells=tuple(final_cells),
        decision_fingerprint=decision_fingerprint,
        review_complete=True,
        decision_payload=_decision_payload(frequency_decisions),
    )
    _require_coverage_matrix(outcome_ledger, coverage)
    if persist:
        persist_roi_coverage(root, coverage)
    return coverage


def _require_coverage_matrix(
    outcomes: RecordingConditionOutcomeLedger,
    coverage: RoiCoverageLedger,
) -> None:
    require_pre_review_readiness(outcomes)
    if coverage.outcome_ledger_fingerprint != outcomes.fingerprint:
        raise RoiCoverageGateError(
            "ROI coverage belongs to a different recording-condition output ledger."
        )
    expected = {
        cell.cell_id.casefold(): (cell.processing_id, cell.condition_label, cell.status)
        for cell in outcomes.cells
    }
    observed = {
        cell.cell_id.casefold(): (
            cell.recording_id,
            cell.condition_label,
            cell.outcome_status,
        )
        for cell in coverage.cells
    }
    if expected != observed:
        raise RoiCoverageGateError(
            "ROI coverage does not account for the exact QC-20 recording-condition matrix."
        )


def persist_roi_coverage(
    project_root: str | Path,
    coverage: RoiCoverageLedger,
) -> None:
    """Persist QC-21 within the existing processing ledger."""

    from Main_App.processing.processing_ledger import load_ledger, save_ledger

    root = _resolved_project_root(project_root)
    ledger = load_ledger(root)
    raw_coverage = ledger.get(ROI_COVERAGE_LEDGER_KEY)
    stages = dict(raw_coverage) if isinstance(raw_coverage, Mapping) else {}
    stages[coverage.stage] = coverage.to_payload()
    if coverage.stage == ROI_COVERAGE_STAGE_PRE_REVIEW:
        stages.pop(ROI_COVERAGE_STAGE_FINAL, None)
        ledger.pop(FINAL_RELEASE_RECEIPT_KEY, None)
    ledger[ROI_COVERAGE_LEDGER_KEY] = stages
    save_ledger(root, ledger)


def load_roi_coverage(
    project_root: str | Path,
    *,
    stage: str,
) -> RoiCoverageLedger | None:
    from Main_App.processing.processing_ledger import load_ledger

    raw = load_ledger(_resolved_project_root(project_root)).get(
        ROI_COVERAGE_LEDGER_KEY
    )
    if not isinstance(raw, Mapping):
        return None
    payload = raw.get(stage)
    if payload is None:
        return None
    if not isinstance(payload, Mapping):
        raise RoiCoverageGateError("Persisted ROI coverage stage is malformed.")
    return RoiCoverageLedger.from_payload(payload)


def require_final_release_readiness(
    outcomes: RecordingConditionOutcomeLedger,
    final_coverage: RoiCoverageLedger,
    *,
    expected_decision_fingerprint: str,
) -> FinalReleaseReceipt:
    """Return a QC-20 release receipt only for complete reviewed QC-21 coverage."""

    _require_coverage_matrix(outcomes, final_coverage)
    if final_coverage.stage != ROI_COVERAGE_STAGE_FINAL:
        raise RoiCoverageGateError("QC-20 final release requires final ROI coverage.")
    expected = str(expected_decision_fingerprint or "").strip()
    if not expected or final_coverage.decision_fingerprint != expected:
        raise RoiCoverageGateError(
            "QC-20 final release has stale QC-03/QC-17 reviewed decisions."
        )
    for cell in final_coverage.cells:
        if cell.outcome_status == CELL_BLOCKED:
            raise RoiCoverageGateError(
                f"QC-20 final release is blocked by {cell.recording_id}/{cell.condition_label}."
            )
        if cell.source_evidence is None:
            continue
        if cell.whole_scalp_normalization is None:
            raise RoiCoverageGateError(
                f"QC-21 normalization coverage is missing for {cell.cell_id}."
            )
        if len(cell.roi_memberships) != len(final_coverage.roi_snapshot.rois):
            raise RoiCoverageGateError(
                f"QC-21 ROI coverage is incomplete for {cell.cell_id}."
            )
    return FinalReleaseReceipt(
        outcome_ledger_fingerprint=outcomes.fingerprint,
        roi_coverage_fingerprint=final_coverage.fingerprint,
        decision_fingerprint=expected,
    )


def persist_final_release_receipt(
    project_root: str | Path,
    receipt: FinalReleaseReceipt,
) -> None:
    from Main_App.processing.processing_ledger import load_ledger, save_ledger

    root = _resolved_project_root(project_root)
    ledger = load_ledger(root)
    ledger[FINAL_RELEASE_RECEIPT_KEY] = receipt.to_payload()
    save_ledger(root, ledger)


def load_final_release_receipt(
    project_root: str | Path,
) -> FinalReleaseReceipt | None:
    from Main_App.processing.processing_ledger import load_ledger

    payload = load_ledger(_resolved_project_root(project_root)).get(
        FINAL_RELEASE_RECEIPT_KEY
    )
    if payload is None:
        return None
    if not isinstance(payload, Mapping):
        raise RoiCoverageGateError("Persisted final-release receipt is malformed.")
    return FinalReleaseReceipt.from_payload(payload)


def record_final_release_readiness(
    project_root: str | Path,
    outcomes: RecordingConditionOutcomeLedger,
    final_coverage: RoiCoverageLedger,
    *,
    expected_decision_fingerprint: str,
) -> FinalReleaseReceipt:
    receipt = require_final_release_readiness(
        outcomes,
        final_coverage,
        expected_decision_fingerprint=expected_decision_fingerprint,
    )
    persist_final_release_receipt(project_root, receipt)
    return receipt


def require_current_final_release(
    project_root: str | Path,
    *,
    expected_decision_fingerprint: str,
) -> tuple[
    RecordingConditionOutcomeLedger,
    RoiCoverageLedger,
    FinalReleaseReceipt,
]:
    """Load and revalidate the durable QC-20/QC-21 release chain."""

    from Main_App.processing.processing_ledger import load_ledger
    from Main_App.processing.recording_condition_outcomes import (
        load_recording_condition_outcomes,
    )

    root = _resolved_project_root(project_root)
    outcomes = load_recording_condition_outcomes(load_ledger(root))
    if outcomes is None:
        raise RoiCoverageGateError(
            "QC-20 final release requires a current recording-condition output ledger."
        )
    for cell in outcomes.cells:
        if cell.status not in {CELL_READY, CELL_PARTIALLY_RETAINED}:
            continue
        receipt = cell.export_receipt
        workbook_write = (
            receipt.get("workbook_write") if isinstance(receipt, Mapping) else None
        )
        recorded_artifact = (
            workbook_write.get("artifact")
            if isinstance(workbook_write, Mapping)
            else None
        )
        workbook_path = Path(str(receipt.get("path") or "")) if receipt else Path()
        if not isinstance(recorded_artifact, Mapping) or (
            _current_workbook_artifact(workbook_path) != dict(recorded_artifact)
        ):
            raise RoiCoverageGateError(
                "QC-20 final release is stale because its workbook changed or "
                f"is missing: {cell.processing_id}/{cell.condition_label}."
            )
        from Main_App.io.condition_data import condition_companion_identity
        from Main_App.io.spectral_data import spectral_companion_identity

        for key, reader in (
            ("condition_companion", condition_companion_identity),
            ("spectral_companion", spectral_companion_identity),
        ):
            try:
                current_companion = reader(workbook_path)
            except (OSError, ValueError) as exc:
                raise RoiCoverageGateError(
                    "QC-20 final release has a missing or changed data companion: "
                    f"{cell.processing_id}/{cell.condition_label}."
                ) from exc
            if current_companion != workbook_write.get(key):
                raise RoiCoverageGateError(
                    "QC-20 final release has a different data companion: "
                    f"{cell.processing_id}/{cell.condition_label}."
                )
    coverage = load_roi_coverage(root, stage=ROI_COVERAGE_STAGE_FINAL)
    if coverage is None:
        raise RoiCoverageGateError("QC-21 final ROI coverage has not been recorded.")
    expected_receipt = require_final_release_readiness(
        outcomes,
        coverage,
        expected_decision_fingerprint=expected_decision_fingerprint,
    )
    receipt = load_final_release_receipt(root)
    if receipt is None or receipt != expected_receipt:
        raise RoiCoverageGateError(
            "QC-20 final-release receipt is missing or stale; rerun reviewed post-processing."
        )
    return outcomes, coverage, receipt


def require_project_final_release(
    project_root: str | Path,
) -> tuple[
    RecordingConditionOutcomeLedger,
    RoiCoverageLedger,
    FinalReleaseReceipt,
]:
    """Resolve current reviewed decisions and require their release receipt."""

    from Main_App.processing.frequency_domain_qc import (
        resolve_frequency_qc_coverage_decisions,
    )

    decisions = resolve_frequency_qc_coverage_decisions(project_root)
    outcomes, coverage, receipt = require_current_final_release(
        project_root,
        expected_decision_fingerprint=decisions.decision_fingerprint,
    )
    current_decision_payload = _decision_payload(decisions)
    if current_decision_payload != dict(coverage.decision_payload):
        raise RoiCoverageGateError(
            "QC-20 final release is stale because its durable QC-03/QC-17 "
            "decision evidence changed. Rerun reviewed post-processing."
        )
    return outcomes, coverage, receipt


def _current_workbook_artifact(path: Path) -> dict[str, object] | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    stat = path.stat()
    return {
        "path": str(path.resolve()),
        "size": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "sha256": digest.hexdigest(),
    }


__all__ = [
    "FINAL_RELEASE_RECEIPT_KEY",
    "FINAL_RELEASE_RECEIPT_VERSION",
    "ROI_COVERAGE_LEDGER_KEY",
    "ROI_COVERAGE_LEDGER_VERSION",
    "ROI_COVERAGE_STAGE_FINAL",
    "ROI_COVERAGE_STAGE_PRE_REVIEW",
    "ROI_SOURCE_COVERAGE_VERSION",
    "ROI_SOURCE_VALIDATION_STAGE",
    "ROI_VALUE_AVAILABLE",
    "ROI_VALUE_NOT_APPLICABLE",
    "ROI_VALUE_UNAVAILABLE",
    "FinalReleaseReceipt",
    "RecordingConditionRoiCoverage",
    "RetainedScalpIdentity",
    "RoiCoverageGateError",
    "RoiCoverageLedger",
    "RoiMembershipCoverage",
    "RoiSourceCoverageError",
    "RoiSourceCoverageEvidence",
    "WholeScalpNormalizationCoverage",
    "build_final_roi_coverage",
    "build_pre_review_roi_coverage",
    "freeze_retained_scalp_identity",
    "load_final_release_receipt",
    "load_roi_coverage",
    "persist_final_release_receipt",
    "persist_roi_coverage",
    "record_final_release_readiness",
    "require_canonical_released_dataset_index",
    "require_current_final_release",
    "require_final_release_readiness",
    "require_project_final_release",
    "validate_roi_source_rows",
]
