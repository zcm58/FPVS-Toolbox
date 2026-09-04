"""GUI-neutral QC-21 ROI source-row integrity validation.

This wave-one foundation validates workbook-shaped rows before any downstream
electrode exclusions. It records structural evidence only and does not alter
ROI aggregation or write project state.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
import hashlib
import json
import math

from Main_App.io import (
    BIOSEMI64_CHANNELS,
    BIOSEMI64_COORDINATE_FINGERPRINT,
    BIOSEMI64_GEOMETRY_VERSION,
    BIOSEMI64_MONTAGE_ID,
    BIOSEMI64_SCALP_SET_FINGERPRINT,
    BioSemi64GeometryError,
    biosemi64_geometry_identity,
)

ROI_SOURCE_COVERAGE_VERSION = "roi_source_coverage_v1"
ROI_SOURCE_VALIDATION_STAGE = "pre_exclusion"

_CANONICAL_CHANNEL_BY_CASEFOLD = {
    channel.casefold(): channel for channel in BIOSEMI64_CHANNELS
}


class RoiSourceCoverageError(ValueError):
    """Source rows cannot satisfy the frozen QC-21 electrode contract."""


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


__all__ = [
    "ROI_SOURCE_COVERAGE_VERSION",
    "ROI_SOURCE_VALIDATION_STAGE",
    "RetainedScalpIdentity",
    "RoiSourceCoverageError",
    "RoiSourceCoverageEvidence",
    "freeze_retained_scalp_identity",
    "validate_roi_source_rows",
]
