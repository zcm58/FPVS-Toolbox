"""Exact, project-owned FPVS frequency and analyzed-length protocol."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, replace
from decimal import Decimal
from fractions import Fraction
from typing import Any, Mapping, TypeAlias

LEGACY_FREQUENCY_PROTOCOL_VERSION = "1.0.0"
FREQUENCY_PROTOCOL_VERSION = "1.1.0"

ODDBALL_INPUT_MODE_RECURRENCE = "oddball_every_n"
ODDBALL_INPUT_MODE_DIRECT_HZ = "oddball_rate_hz"

FREQUENCY_PROTOCOL_STATUS_READY = "ready"
FREQUENCY_PROTOCOL_STATUS_INCOMPLETE = "incomplete"
FREQUENCY_PROTOCOL_STATUS_CONFIRMATION_REQUIRED = "confirmation_required"

EXPECTED_CYCLES_SOURCE_MANUAL = "manual"
EXPECTED_CYCLES_SOURCE_FPVS_STUDIO_IMPORT = "fpvs_studio_import"

ODDBALL_MARKER_SOURCE_MANUAL = "manual"
ODDBALL_MARKER_SOURCE_FPVS_STUDIO_IMPORT = "fpvs_studio_import"
ODDBALL_MARKER_SOURCE_LEGACY_DEFAULT_55 = "legacy_default_55"
ODDBALL_MARKER_SOURCE_LEGACY_EVIDENCE = "legacy_evidence"

# Protocol v1 accepts a directly entered rate when it is no farther than half
# of one four-decimal display unit from an exact whole-stimulus recurrence.
# The accepted value is then replaced by the exact presentation-rate / N value.
DIRECT_HZ_DISPLAY_DECIMAL_PLACES = 4
DIRECT_HZ_DISPLAY_TOLERANCE_HZ = Fraction(
    1,
    2 * (10**DIRECT_HZ_DISPLAY_DECIMAL_PLACES),
)

DEFAULT_PRESENTATION_RATE_HZ = Fraction(6, 1)
DEFAULT_ODDBALL_EVERY_N = 5
DEFAULT_ODDBALL_MARKER_CODE = 55

RateValue: TypeAlias = Fraction | Decimal | int | float | str


class FrequencyProtocolError(ValueError):
    """Raised when project frequency-protocol values are invalid."""


def _positive_fraction(value: RateValue, *, field_name: str) -> Fraction:
    if isinstance(value, bool):
        raise FrequencyProtocolError(f"{field_name} must be a finite positive number.")
    if isinstance(value, float) and not math.isfinite(value):
        raise FrequencyProtocolError(f"{field_name} must be a finite positive number.")
    if isinstance(value, Decimal) and not value.is_finite():
        raise FrequencyProtocolError(f"{field_name} must be a finite positive number.")
    try:
        rate = value if isinstance(value, Fraction) else Fraction(str(value).strip())
    except (ValueError, ZeroDivisionError, AttributeError) as exc:
        raise FrequencyProtocolError(
            f"{field_name} must be a finite positive number."
        ) from exc
    if rate <= 0:
        raise FrequencyProtocolError(f"{field_name} must be a finite positive number.")
    return rate


def _positive_integer(value: Any, *, field_name: str, minimum: int = 1) -> int:
    if isinstance(value, bool):
        raise FrequencyProtocolError(
            f"{field_name} must be a whole number greater than or equal to {minimum}."
        )
    try:
        exact = value if isinstance(value, Fraction) else Fraction(str(value).strip())
    except (ValueError, ZeroDivisionError, AttributeError) as exc:
        raise FrequencyProtocolError(
            f"{field_name} must be a whole number greater than or equal to {minimum}."
        ) from exc
    if exact.denominator != 1 or exact.numerator < minimum:
        raise FrequencyProtocolError(
            f"{field_name} must be a whole number greater than or equal to {minimum}."
        )
    return int(exact.numerator)


def _fraction_text(value: Fraction) -> str:
    """Return a stable exact decimal when finite, otherwise a rational string."""

    numerator = value.numerator
    denominator = value.denominator
    if denominator == 1:
        return str(numerator)

    twos = 0
    fives = 0
    remainder = denominator
    while remainder % 2 == 0:
        twos += 1
        remainder //= 2
    while remainder % 5 == 0:
        fives += 1
        remainder //= 5
    if remainder != 1:
        return f"{numerator}/{denominator}"

    places = max(twos, fives)
    scaled = numerator * (2 ** (places - twos)) * (5 ** (places - fives))
    sign = "-" if scaled < 0 else ""
    digits = str(abs(scaled)).zfill(places + 1)
    whole = digits[:-places] if places else digits
    decimal = digits[-places:] if places else ""
    decimal = decimal.rstrip("0")
    return f"{sign}{whole}.{decimal}" if decimal else f"{sign}{whole}"


def _nearest_recurrence_candidates(
    presentation_rate_hz: Fraction,
    entered_oddball_rate_hz: Fraction,
) -> tuple[int, ...]:
    ratio = presentation_rate_hz / entered_oddball_rate_hz
    floor_ratio = ratio.numerator // ratio.denominator
    candidates = {
        candidate
        for candidate in range(max(2, floor_ratio - 1), max(2, floor_ratio) + 3)
        if candidate >= 2
    }
    candidates.add(2)
    return tuple(
        sorted(
            candidates,
            key=lambda n: (
                abs((presentation_rate_hz / n) - entered_oddball_rate_hz),
                n,
            ),
        )
    )


@dataclass(frozen=True, slots=True)
class HarmonicTarget:
    """One exact harmonic on the canonical oddball/presentation grid."""

    frequency_hz: Fraction
    oddball_harmonic_order: int
    presentation_harmonic_order: int | None

    @property
    def is_presentation_harmonic(self) -> bool:
        return self.presentation_harmonic_order is not None


@dataclass(frozen=True, slots=True)
class FrequencyProtocol:
    """Immutable canonical protocol stored once per project."""

    version: str
    status: str
    presentation_rate_hz: Fraction | None
    oddball_input_mode: str | None
    oddball_every_n: int | None
    oddball_rate_hz: Fraction | None
    entered_oddball_rate_hz: str | None
    expected_analyzed_oddball_cycles: int | None
    expected_analyzed_oddball_cycles_source: str | None
    oddball_marker_code: int | None
    oddball_marker_code_source: str | None

    def __post_init__(self) -> None:
        if self.version != FREQUENCY_PROTOCOL_VERSION:
            raise FrequencyProtocolError(
                "Unsupported frequency protocol version "
                f"{self.version!r}; expected {FREQUENCY_PROTOCOL_VERSION!r}."
            )
        valid_statuses = {
            FREQUENCY_PROTOCOL_STATUS_READY,
            FREQUENCY_PROTOCOL_STATUS_INCOMPLETE,
            FREQUENCY_PROTOCOL_STATUS_CONFIRMATION_REQUIRED,
        }
        if self.status not in valid_statuses:
            raise FrequencyProtocolError(f"Unsupported frequency protocol status {self.status!r}.")

        marker_confirmation_required = (
            self.status == FREQUENCY_PROTOCOL_STATUS_CONFIRMATION_REQUIRED
        )
        if marker_confirmation_required:
            protocol_values = (
                self.presentation_rate_hz,
                self.oddball_input_mode,
                self.oddball_every_n,
                self.oddball_rate_hz,
                self.entered_oddball_rate_hz,
                self.expected_analyzed_oddball_cycles,
                self.expected_analyzed_oddball_cycles_source,
            )
            marker_values = (
                self.oddball_marker_code,
                self.oddball_marker_code_source,
            )
            if any(value is not None for value in marker_values):
                raise FrequencyProtocolError(
                    "A confirmation-required protocol cannot claim a confirmed oddball "
                    "marker code or source."
                )
            if not any(value is not None for value in protocol_values):
                return

        presentation_rate = _positive_fraction(
            self.presentation_rate_hz,
            field_name="presentation_rate_hz",
        )
        oddball_rate = _positive_fraction(
            self.oddball_rate_hz,
            field_name="oddball_rate_hz",
        )
        recurrence = _positive_integer(
            self.oddball_every_n,
            field_name="oddball_every_n",
            minimum=2,
        )
        input_mode = str(self.oddball_input_mode or "").strip()
        if input_mode not in {
            ODDBALL_INPUT_MODE_RECURRENCE,
            ODDBALL_INPUT_MODE_DIRECT_HZ,
        }:
            raise FrequencyProtocolError(
                f"Unsupported oddball input mode {self.oddball_input_mode!r}."
            )
        canonical_oddball = presentation_rate / recurrence
        entered_text: str | None = None
        if input_mode == ODDBALL_INPUT_MODE_RECURRENCE:
            if self.entered_oddball_rate_hz is not None:
                raise FrequencyProtocolError(
                    "entered_oddball_rate_hz is only valid for direct-Hz input."
                )
        else:
            entered_text = str(self.entered_oddball_rate_hz or "").strip()
            if not entered_text:
                raise FrequencyProtocolError(
                    "Direct-Hz input requires entered_oddball_rate_hz audit metadata."
                )
            entered_rate = _positive_fraction(
                entered_text,
                field_name="entered_oddball_rate_hz",
            )
            if abs(entered_rate - canonical_oddball) > DIRECT_HZ_DISPLAY_TOLERANCE_HZ:
                raise FrequencyProtocolError(
                    "entered_oddball_rate_hz exceeds the protocol-v1 display tolerance "
                    "for the canonical whole-stimulus recurrence."
                )
        if oddball_rate != canonical_oddball:
            raise FrequencyProtocolError(
                "oddball_rate_hz must equal presentation_rate_hz / oddball_every_n exactly."
            )

        cycles = self.expected_analyzed_oddball_cycles
        source = self.expected_analyzed_oddball_cycles_source
        if cycles is None and source is not None:
            raise FrequencyProtocolError(
                "expected_analyzed_oddball_cycles_source requires an expected cycle count."
            )
        if cycles is not None:
            cycles = _positive_integer(
                cycles,
                field_name="expected_analyzed_oddball_cycles",
            )
            source = str(source or "").strip()
            if source not in {
                EXPECTED_CYCLES_SOURCE_MANUAL,
                EXPECTED_CYCLES_SOURCE_FPVS_STUDIO_IMPORT,
            }:
                raise FrequencyProtocolError(
                    "expected_analyzed_oddball_cycles_source must be 'manual' or "
                    "'fpvs_studio_import'."
                )

        marker_code: int | None = None
        marker_source: str | None = None
        if not marker_confirmation_required:
            marker_code = _positive_integer(
                self.oddball_marker_code,
                field_name="oddball_marker_code",
            )
            marker_source = str(self.oddball_marker_code_source or "").strip()
            if marker_source not in {
                ODDBALL_MARKER_SOURCE_MANUAL,
                ODDBALL_MARKER_SOURCE_FPVS_STUDIO_IMPORT,
                ODDBALL_MARKER_SOURCE_LEGACY_DEFAULT_55,
                ODDBALL_MARKER_SOURCE_LEGACY_EVIDENCE,
            }:
                raise FrequencyProtocolError(
                    "oddball_marker_code_source must identify manual, FPVS Studio, "
                    "or explicit legacy confirmation."
                )

        expected_status = (
            FREQUENCY_PROTOCOL_STATUS_READY
            if cycles is not None
            else FREQUENCY_PROTOCOL_STATUS_INCOMPLETE
        )
        if not marker_confirmation_required and self.status != expected_status:
            raise FrequencyProtocolError(
                f"Frequency protocol status must be {expected_status!r} for its cycle fields."
            )

        # A frozen instance still normalizes constructor inputs once here so
        # every successfully created object exposes canonical runtime types.
        object.__setattr__(self, "presentation_rate_hz", presentation_rate)
        object.__setattr__(self, "oddball_input_mode", input_mode)
        object.__setattr__(self, "oddball_every_n", recurrence)
        object.__setattr__(self, "oddball_rate_hz", oddball_rate)
        object.__setattr__(self, "entered_oddball_rate_hz", entered_text)
        object.__setattr__(self, "expected_analyzed_oddball_cycles", cycles)
        object.__setattr__(self, "expected_analyzed_oddball_cycles_source", source)
        object.__setattr__(self, "oddball_marker_code", marker_code)
        object.__setattr__(self, "oddball_marker_code_source", marker_source)

    @classmethod
    def confirmation_required(cls) -> "FrequencyProtocol":
        """Represent an existing project whose historical protocol is unknown."""

        return cls(
            version=FREQUENCY_PROTOCOL_VERSION,
            status=FREQUENCY_PROTOCOL_STATUS_CONFIRMATION_REQUIRED,
            presentation_rate_hz=None,
            oddball_input_mode=None,
            oddball_every_n=None,
            oddball_rate_hz=None,
            entered_oddball_rate_hz=None,
            expected_analyzed_oddball_cycles=None,
            expected_analyzed_oddball_cycles_source=None,
            oddball_marker_code=None,
            oddball_marker_code_source=None,
        )

    @classmethod
    def from_recurrence(
        cls,
        presentation_rate_hz: RateValue,
        oddball_every_n: Any,
        *,
        expected_analyzed_oddball_cycles: Any | None = None,
        expected_analyzed_oddball_cycles_source: str | None = None,
        oddball_marker_code: Any = DEFAULT_ODDBALL_MARKER_CODE,
        oddball_marker_code_source: str = ODDBALL_MARKER_SOURCE_MANUAL,
    ) -> "FrequencyProtocol":
        presentation_rate = _positive_fraction(
            presentation_rate_hz,
            field_name="presentation_rate_hz",
        )
        recurrence = _positive_integer(
            oddball_every_n,
            field_name="oddball_every_n",
            minimum=2,
        )
        cycles, source, status = _normalize_cycles(
            expected_analyzed_oddball_cycles,
            expected_analyzed_oddball_cycles_source,
        )
        return cls(
            version=FREQUENCY_PROTOCOL_VERSION,
            status=status,
            presentation_rate_hz=presentation_rate,
            oddball_input_mode=ODDBALL_INPUT_MODE_RECURRENCE,
            oddball_every_n=recurrence,
            oddball_rate_hz=presentation_rate / recurrence,
            entered_oddball_rate_hz=None,
            expected_analyzed_oddball_cycles=cycles,
            expected_analyzed_oddball_cycles_source=source,
            oddball_marker_code=oddball_marker_code,
            oddball_marker_code_source=oddball_marker_code_source,
        )

    @classmethod
    def from_direct_hz(
        cls,
        presentation_rate_hz: RateValue,
        oddball_rate_hz: RateValue,
        *,
        expected_analyzed_oddball_cycles: Any | None = None,
        expected_analyzed_oddball_cycles_source: str | None = None,
        oddball_marker_code: Any = DEFAULT_ODDBALL_MARKER_CODE,
        oddball_marker_code_source: str = ODDBALL_MARKER_SOURCE_MANUAL,
    ) -> "FrequencyProtocol":
        presentation_rate = _positive_fraction(
            presentation_rate_hz,
            field_name="presentation_rate_hz",
        )
        entered_oddball_rate = _positive_fraction(
            oddball_rate_hz,
            field_name="oddball_rate_hz",
        )
        candidates = _nearest_recurrence_candidates(
            presentation_rate,
            entered_oddball_rate,
        )
        recurrence = candidates[0]
        canonical_oddball = presentation_rate / recurrence
        difference = abs(canonical_oddball - entered_oddball_rate)
        if difference > DIRECT_HZ_DISPLAY_TOLERANCE_HZ:
            nearby = ", ".join(
                f"{_fraction_text(presentation_rate / n)} Hz (every {n})"
                for n in candidates[:2]
            )
            raise FrequencyProtocolError(
                f"Direct oddball rate {_fraction_text(entered_oddball_rate)} Hz does not "
                "resolve to a whole-stimulus recurrence within the protocol-v1 "
                f"four-decimal display tolerance ({float(DIRECT_HZ_DISPLAY_TOLERANCE_HZ):g} Hz). "
                f"Nearby valid choices: {nearby}."
            )
        cycles, source, status = _normalize_cycles(
            expected_analyzed_oddball_cycles,
            expected_analyzed_oddball_cycles_source,
        )
        return cls(
            version=FREQUENCY_PROTOCOL_VERSION,
            status=status,
            presentation_rate_hz=presentation_rate,
            oddball_input_mode=ODDBALL_INPUT_MODE_DIRECT_HZ,
            oddball_every_n=recurrence,
            oddball_rate_hz=canonical_oddball,
            entered_oddball_rate_hz=str(oddball_rate_hz).strip(),
            expected_analyzed_oddball_cycles=cycles,
            expected_analyzed_oddball_cycles_source=source,
            oddball_marker_code=oddball_marker_code,
            oddball_marker_code_source=oddball_marker_code_source,
        )

    @classmethod
    def from_manifest(cls, value: Mapping[str, Any]) -> "FrequencyProtocol":
        """Normalize and validate one persisted protocol record."""

        if not isinstance(value, Mapping):
            raise FrequencyProtocolError("frequency_protocol must be a JSON object.")
        version = str(value.get("version") or "").strip()
        status = str(value.get("status") or "").strip()
        has_marker_code = "oddball_marker_code" in value
        has_marker_source = "oddball_marker_code_source" in value
        if version == LEGACY_FREQUENCY_PROTOCOL_VERSION:
            if has_marker_code != has_marker_source:
                raise FrequencyProtocolError(
                    "Legacy frequency protocol marker identity is incomplete."
                )
            version = FREQUENCY_PROTOCOL_VERSION
            if not has_marker_code:
                # Protocol v1.0 predated project-owned marker identity. Preserve
                # every validated rate/cycle field, but require the proposed
                # marker code to be explicitly confirmed before processing.
                status = FREQUENCY_PROTOCOL_STATUS_CONFIRMATION_REQUIRED
        if status == FREQUENCY_PROTOCOL_STATUS_CONFIRMATION_REQUIRED:
            return cls(
                version=version,
                status=status,
                presentation_rate_hz=value.get("presentation_rate_hz"),
                oddball_input_mode=value.get("oddball_input_mode"),
                oddball_every_n=value.get("oddball_every_n"),
                oddball_rate_hz=value.get("oddball_rate_hz"),
                entered_oddball_rate_hz=value.get("entered_oddball_rate_hz"),
                expected_analyzed_oddball_cycles=value.get(
                    "expected_analyzed_oddball_cycles"
                ),
                expected_analyzed_oddball_cycles_source=value.get(
                    "expected_analyzed_oddball_cycles_source"
                ),
                oddball_marker_code=value.get("oddball_marker_code"),
                oddball_marker_code_source=value.get("oddball_marker_code_source"),
            )
        if not status:
            status = (
                FREQUENCY_PROTOCOL_STATUS_READY
                if value.get("expected_analyzed_oddball_cycles") is not None
                else FREQUENCY_PROTOCOL_STATUS_INCOMPLETE
            )

        presentation_rate = _positive_fraction(
            value.get("presentation_rate_hz"),
            field_name="presentation_rate_hz",
        )
        oddball_rate = _positive_fraction(
            value.get("oddball_rate_hz"),
            field_name="oddball_rate_hz",
        )
        recurrence = _positive_integer(
            value.get("oddball_every_n"),
            field_name="oddball_every_n",
            minimum=2,
        )
        raw_cycles = value.get("expected_analyzed_oddball_cycles")
        cycles = (
            _positive_integer(
                raw_cycles,
                field_name="expected_analyzed_oddball_cycles",
            )
            if raw_cycles is not None
            else None
        )
        raw_source = value.get("expected_analyzed_oddball_cycles_source")
        source = str(raw_source).strip() if raw_source is not None else None
        raw_entered_rate = value.get("entered_oddball_rate_hz")
        entered_rate = (
            str(raw_entered_rate).strip()
            if raw_entered_rate is not None
            else (
                _fraction_text(oddball_rate)
                if value.get("oddball_input_mode") == ODDBALL_INPUT_MODE_DIRECT_HZ
                else None
            )
        )
        return cls(
            version=version,
            status=status,
            presentation_rate_hz=presentation_rate,
            oddball_input_mode=str(value.get("oddball_input_mode") or "").strip(),
            oddball_every_n=recurrence,
            oddball_rate_hz=oddball_rate,
            entered_oddball_rate_hz=entered_rate,
            expected_analyzed_oddball_cycles=cycles,
            expected_analyzed_oddball_cycles_source=source,
            oddball_marker_code=value.get("oddball_marker_code"),
            oddball_marker_code_source=value.get("oddball_marker_code_source"),
        )

    @property
    def is_ready(self) -> bool:
        return self.status == FREQUENCY_PROTOCOL_STATUS_READY

    @property
    def derived_analyzed_seconds(self) -> Fraction | None:
        """Return exact analyzed seconds, or ``None`` until cycles are supplied."""

        if (
            self.expected_analyzed_oddball_cycles is None
            or self.oddball_rate_hz is None
        ):
            return None
        return self.expected_analyzed_oddball_cycles / self.oddball_rate_hz

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def canonical_payload(self) -> dict[str, Any]:
        """Return the deterministic JSON-compatible scientific identity."""

        return {
            "version": self.version,
            "status": self.status,
            "presentation_rate_hz": (
                _fraction_text(self.presentation_rate_hz)
                if self.presentation_rate_hz is not None
                else None
            ),
            "oddball_input_mode": self.oddball_input_mode,
            "oddball_every_n": self.oddball_every_n,
            "oddball_rate_hz": (
                _fraction_text(self.oddball_rate_hz)
                if self.oddball_rate_hz is not None
                else None
            ),
            "expected_analyzed_oddball_cycles": self.expected_analyzed_oddball_cycles,
            "expected_analyzed_oddball_cycles_source": (
                self.expected_analyzed_oddball_cycles_source
            ),
            "oddball_marker_code": self.oddball_marker_code,
            "oddball_marker_code_source": self.oddball_marker_code_source,
        }

    def canonical_json(self) -> str:
        return json.dumps(
            self.canonical_payload(),
            separators=(",", ":"),
            sort_keys=True,
            ensure_ascii=False,
        )

    def to_manifest(self) -> dict[str, Any]:
        payload = self.canonical_payload()
        payload["entered_oddball_rate_hz"] = self.entered_oddball_rate_hz
        return payload

    def with_expected_cycles(
        self,
        cycles: Any,
        *,
        source: str,
    ) -> "FrequencyProtocol":
        if self.status == FREQUENCY_PROTOCOL_STATUS_CONFIRMATION_REQUIRED:
            raise FrequencyProtocolError(
                "Confirm canonical project rates before setting expected analyzed cycles."
            )
        normalized_cycles, normalized_source, status = _normalize_cycles(cycles, source)
        return replace(
            self,
            status=status,
            expected_analyzed_oddball_cycles=normalized_cycles,
            expected_analyzed_oddball_cycles_source=normalized_source,
        )

    def with_oddball_marker_code(
        self,
        marker_code: Any,
        *,
        source: str,
    ) -> "FrequencyProtocol":
        """Return the same rate/cycle protocol with explicit marker identity."""

        if self.status == FREQUENCY_PROTOCOL_STATUS_CONFIRMATION_REQUIRED:
            raise FrequencyProtocolError(
                "Confirm canonical project rates before setting the oddball marker code."
            )
        return replace(
            self,
            oddball_marker_code=marker_code,
            oddball_marker_code_source=source,
        )

    def expected_analyzed_samples(self, sampling_rate_hz: RateValue) -> int:
        """Return the exact target sample count or reject an incompatible grid."""

        if not self.is_ready or self.oddball_rate_hz is None:
            raise FrequencyProtocolError(
                "Expected analyzed cycles are required before resolving a sample count."
            )
        sampling_rate = _positive_fraction(
            sampling_rate_hz,
            field_name="sampling_rate_hz",
        )
        exact_samples = (
            self.expected_analyzed_oddball_cycles
            * sampling_rate
            / self.oddball_rate_hz
        )
        if exact_samples.denominator != 1:
            raise FrequencyProtocolError(
                "Expected analyzed cycles are incompatible with the sampling-rate grid: "
                f"{self.expected_analyzed_oddball_cycles} cycles at "
                f"{_fraction_text(self.oddball_rate_hz)} Hz and "
                f"{_fraction_text(sampling_rate)} Hz sampling require "
                f"{_fraction_text(exact_samples)} samples."
            )
        return int(exact_samples.numerator)


def _normalize_cycles(
    cycles: Any | None,
    source: str | None,
) -> tuple[int | None, str | None, str]:
    if cycles is None:
        if source is not None:
            raise FrequencyProtocolError(
                "expected_analyzed_oddball_cycles_source requires an expected cycle count."
            )
        return None, None, FREQUENCY_PROTOCOL_STATUS_INCOMPLETE
    normalized_cycles = _positive_integer(
        cycles,
        field_name="expected_analyzed_oddball_cycles",
    )
    normalized_source = str(source).strip() if source is not None else ""
    if normalized_source not in {
        EXPECTED_CYCLES_SOURCE_MANUAL,
        EXPECTED_CYCLES_SOURCE_FPVS_STUDIO_IMPORT,
    }:
        raise FrequencyProtocolError(
            "expected_analyzed_oddball_cycles_source must be 'manual' or "
            "'fpvs_studio_import'."
        )
    return normalized_cycles, normalized_source, FREQUENCY_PROTOCOL_STATUS_READY


def new_manual_frequency_protocol() -> FrequencyProtocol:
    """Return the seeded, explicitly incomplete protocol for a new project."""

    return FrequencyProtocol.from_recurrence(
        DEFAULT_PRESENTATION_RATE_HZ,
        DEFAULT_ODDBALL_EVERY_N,
    )


def normalize_frequency_protocol(
    value: FrequencyProtocol | Mapping[str, Any],
) -> FrequencyProtocol:
    if isinstance(value, FrequencyProtocol):
        return value
    return FrequencyProtocol.from_manifest(value)


def validate_protocol_condition_codes(
    protocol: FrequencyProtocol,
    condition_onset_codes: Any,
) -> None:
    """Reject a project marker code that is also a condition-onset code."""

    if protocol.oddball_marker_code is None:
        raise FrequencyProtocolError(
            "Confirm the project oddball marker code before processing."
        )
    try:
        onset_codes = {
            _positive_integer(value, field_name="condition_onset_code")
            for value in condition_onset_codes
        }
    except TypeError as exc:
        raise FrequencyProtocolError(
            "condition_onset_codes must be an iterable of positive integers."
        ) from exc
    if protocol.oddball_marker_code in onset_codes:
        raise FrequencyProtocolError(
            f"Oddball marker code {protocol.oddball_marker_code} is also a "
            "condition-onset code. Choose a distinct project marker code."
        )


def enumerate_exact_harmonics(
    fundamental_rate_hz: RateValue,
    upper_bound_hz: RateValue,
) -> tuple[Fraction, ...]:
    """Enumerate exact positive harmonics through an inclusive caller bound."""

    fundamental = _positive_fraction(
        fundamental_rate_hz,
        field_name="fundamental_rate_hz",
    )
    upper_bound = _positive_fraction(
        upper_bound_hz,
        field_name="upper_bound_hz",
    )
    count = int(upper_bound // fundamental)
    return tuple(fundamental * order for order in range(1, count + 1))


def enumerate_protocol_harmonics(
    protocol: FrequencyProtocol,
    upper_bound_hz: RateValue,
) -> tuple[HarmonicTarget, ...]:
    """Enumerate the exact oddball grid and identify presentation overlaps.

    This helper applies no filter, notch, neighboring-bin, significance, or
    profile policy. The caller owns the inclusive technical upper bound.
    """

    if (
        protocol.status == FREQUENCY_PROTOCOL_STATUS_CONFIRMATION_REQUIRED
        or protocol.oddball_rate_hz is None
        or protocol.oddball_every_n is None
    ):
        raise FrequencyProtocolError(
            "Canonical project rates are required before enumerating harmonics."
        )
    frequencies = enumerate_exact_harmonics(
        protocol.oddball_rate_hz,
        upper_bound_hz,
    )
    return tuple(
        HarmonicTarget(
            frequency_hz=frequency,
            oddball_harmonic_order=order,
            presentation_harmonic_order=(
                order // protocol.oddball_every_n
                if order % protocol.oddball_every_n == 0
                else None
            ),
        )
        for order, frequency in enumerate(frequencies, start=1)
    )
