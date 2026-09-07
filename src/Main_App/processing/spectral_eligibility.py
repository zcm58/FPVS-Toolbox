"""Canonical spectral-domain eligibility for standard FPVS metrics.

This module is the sole current owner of the technical harmonic domain.  It
combines one exact project protocol with the realized FFT grid, the nominal
filter edges recorded after successful application, and the effective notch
mask.  Consumers must not reconstruct a target list from a legacy ceiling or
from whichever workbook columns happen to exist.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from functools import lru_cache
from typing import Any, Iterable, Mapping, Sequence, TypeAlias

from Main_App.projects.frequency_protocol import (
    FrequencyProtocol,
    HarmonicTarget,
    enumerate_protocol_harmonics,
    normalize_frequency_protocol,
)

SPECTRAL_ELIGIBILITY_METHOD_VERSION = "project_filter_qc14_v1"
_MAX_CACHED_ELIGIBILITY_HARMONICS = 256
FILTER_EDGE_REPRESENTATION_TOLERANCE_HZ = Fraction(1, 1_000_000_000)
QC14_NOISE_WINDOW_BINS = 10
QC14_NOISE_CANDIDATE_OFFSETS = tuple(
    [*range(-QC14_NOISE_WINDOW_BINS, -1), *range(2, QC14_NOISE_WINDOW_BINS + 1)]
)
QC14_RETAINED_NOISE_BIN_COUNT = 16
MINIMUM_REALIZED_ODDBALL_CYCLES_EXCLUSIVE = 10
MAX_CANONICAL_HARMONIC_COUNT = 100_000

TARGET_AMPLITUDE_AVAILABLE = "available"
TARGET_AMPLITUDE_AUDIT_ONLY = "audit_only"
TARGET_AMPLITUDE_UNAVAILABLE = "unavailable"

REASON_INSUFFICIENT_ODDBALL_CYCLES = "insufficient_oddball_cycles"
REASON_TARGET_AT_OR_BELOW_DC = "target_at_or_below_dc"
REASON_TARGET_AT_OR_ABOVE_NYQUIST = "target_at_or_above_nyquist"
REASON_TARGET_BELOW_HIGH_PASS = "target_below_applied_high_pass"
REASON_TARGET_ABOVE_LOW_PASS = "target_above_applied_low_pass"
REASON_NOISE_WINDOW_REACHES_DC = "noise_window_reaches_dc"
REASON_NOISE_WINDOW_REACHES_NYQUIST = "noise_window_reaches_nyquist"
REASON_NOISE_WINDOW_BELOW_HIGH_PASS = "noise_window_below_applied_high_pass"
REASON_NOISE_WINDOW_ABOVE_LOW_PASS = "noise_window_above_applied_low_pass"
REASON_TARGET_NOTCH_COLLISION = "target_inside_applied_notch"
REASON_NOISE_NOTCH_COLLISION = "required_noise_bin_inside_applied_notch"
REASON_TAGGED_HARMONIC_COLLISION = "required_noise_bin_is_fpvs_harmonic"

RateValue: TypeAlias = Fraction | Decimal | int | float | str


class SpectralEligibilityError(ValueError):
    """Raised when the run cannot establish a trustworthy spectral domain."""


def _exact_fraction(value: RateValue, *, field_name: str) -> Fraction:
    if isinstance(value, bool):
        raise SpectralEligibilityError(f"{field_name} must be finite and positive.")
    if isinstance(value, float) and not math.isfinite(value):
        raise SpectralEligibilityError(f"{field_name} must be finite and positive.")
    if isinstance(value, Decimal) and not value.is_finite():
        raise SpectralEligibilityError(f"{field_name} must be finite and positive.")
    try:
        exact = value if isinstance(value, Fraction) else Fraction(str(value).strip())
    except (AttributeError, ValueError, ZeroDivisionError) as exc:
        raise SpectralEligibilityError(
            f"{field_name} must be finite and positive."
        ) from exc
    if exact <= 0:
        raise SpectralEligibilityError(f"{field_name} must be finite and positive.")
    return exact


def _optional_edge(value: RateValue | None, *, field_name: str) -> Fraction | None:
    if value in (None, ""):
        return None
    return _exact_fraction(value, field_name=field_name)


def _fraction_text(value: Fraction | None) -> str | None:
    if value is None:
        return None
    return f"{value.numerator}/{value.denominator}"


def _canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


@dataclass(frozen=True, slots=True)
class AppliedFilterSnapshot:
    """Validated nominal passband from requested and successfully applied edges."""

    requested_high_pass_hz: Fraction | None
    requested_low_pass_hz: Fraction | None
    applied_high_pass_hz: Fraction
    applied_low_pass_hz: Fraction
    nyquist_hz: Fraction
    method_version: str = "mne_fir_nominal_edges_v1"

    @property
    def effective_high_pass_hz(self) -> Fraction:
        return self.applied_high_pass_hz

    @property
    def effective_low_pass_hz(self) -> Fraction:
        return self.applied_low_pass_hz

    def canonical_payload(self) -> dict[str, object]:
        return {
            "method_version": self.method_version,
            "requested_high_pass_hz": _fraction_text(self.requested_high_pass_hz),
            "requested_low_pass_hz": _fraction_text(self.requested_low_pass_hz),
            "applied_high_pass_hz": _fraction_text(self.applied_high_pass_hz),
            "applied_low_pass_hz": _fraction_text(self.applied_low_pass_hz),
            "nyquist_hz": _fraction_text(self.nyquist_hz),
            "representation_tolerance_hz": _fraction_text(
                FILTER_EDGE_REPRESENTATION_TOLERANCE_HZ
            ),
        }


@dataclass(frozen=True, slots=True)
class AppliedNotchSnapshot:
    """Exact effective attenuation holes produced by the applied notch step."""

    applied_centers_hz: tuple[Fraction, ...]
    half_width_hz: Fraction
    method_version: str

    def canonical_payload(self) -> dict[str, object]:
        return {
            "method_version": self.method_version,
            "applied_centers_hz": [
                _fraction_text(center) for center in self.applied_centers_hz
            ],
            "half_width_hz": _fraction_text(self.half_width_hz),
        }


@dataclass(frozen=True, slots=True)
class SpectralTargetAvailability:
    """Static technical availability of one exact project harmonic."""

    target: HarmonicTarget
    target_bin_index: int
    noise_candidate_bin_indices: tuple[int, ...]
    noise_candidate_frequencies_hz: tuple[Fraction, ...]
    target_amplitude_status: str
    bca_available: bool
    snr_available: bool
    local_z_available: bool
    reason_codes: tuple[str, ...]
    target_notch_centers_hz: tuple[Fraction, ...] = ()
    noise_notch_collisions: tuple[tuple[int, Fraction], ...] = ()
    tagged_noise_collisions: tuple[tuple[int, str, int], ...] = ()

    @property
    def standard_metrics_available(self) -> bool:
        return self.bca_available and self.snr_available and self.local_z_available

    @property
    def is_presentation_harmonic(self) -> bool:
        return self.target.is_presentation_harmonic

    def canonical_payload(self) -> dict[str, object]:
        return {
            "frequency_hz": _fraction_text(self.target.frequency_hz),
            "oddball_harmonic_order": self.target.oddball_harmonic_order,
            "presentation_harmonic_order": self.target.presentation_harmonic_order,
            "target_bin_index": self.target_bin_index,
            "noise_candidate_bin_indices": list(self.noise_candidate_bin_indices),
            "noise_candidate_frequencies_hz": [
                _fraction_text(value)
                for value in self.noise_candidate_frequencies_hz
            ],
            "target_amplitude_status": self.target_amplitude_status,
            "bca_available": self.bca_available,
            "snr_available": self.snr_available,
            "local_z_available": self.local_z_available,
            "reason_codes": list(self.reason_codes),
            "target_notch_centers_hz": [
                _fraction_text(value) for value in self.target_notch_centers_hz
            ],
            "noise_notch_collisions": [
                {"bin_index": index, "notch_center_hz": _fraction_text(center)}
                for index, center in self.noise_notch_collisions
            ],
            "tagged_noise_collisions": [
                {"bin_index": index, "kind": kind, "harmonic_order": order}
                for index, kind, order in self.tagged_noise_collisions
            ],
        }


@dataclass(frozen=True, slots=True)
class SpectralEligibilityResult:
    """Complete canonical harmonic-domain decision for one FFT input."""

    protocol: FrequencyProtocol
    sampling_rate_hz: Fraction
    analyzed_samples: int
    realized_oddball_cycles: int
    bin_width_hz: Fraction
    nyquist_hz: Fraction
    applied_filter: AppliedFilterSnapshot
    applied_notch: AppliedNotchSnapshot
    targets: tuple[SpectralTargetAvailability, ...]
    method_version: str = SPECTRAL_ELIGIBILITY_METHOD_VERSION

    @property
    def eligible_targets(self) -> tuple[SpectralTargetAvailability, ...]:
        return tuple(item for item in self.targets if item.standard_metrics_available)

    @property
    def eligible_non_presentation_targets(
        self,
    ) -> tuple[SpectralTargetAvailability, ...]:
        return tuple(
            item
            for item in self.eligible_targets
            if not item.is_presentation_harmonic
        )

    @property
    def eligible_presentation_targets(
        self,
    ) -> tuple[SpectralTargetAvailability, ...]:
        return tuple(
            item for item in self.eligible_targets if item.is_presentation_harmonic
        )

    @property
    def unavailable_targets(self) -> tuple[SpectralTargetAvailability, ...]:
        return tuple(item for item in self.targets if not item.standard_metrics_available)

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(
            _canonical_json(self.canonical_payload()).encode("utf-8")
        ).hexdigest()

    def canonical_payload(self) -> dict[str, object]:
        return {
            "method_version": self.method_version,
            "protocol": self.protocol.canonical_payload(),
            "protocol_fingerprint": self.protocol.fingerprint,
            "sampling_rate_hz": _fraction_text(self.sampling_rate_hz),
            "analyzed_samples": self.analyzed_samples,
            "realized_oddball_cycles": self.realized_oddball_cycles,
            "bin_width_hz": _fraction_text(self.bin_width_hz),
            "nyquist_hz": _fraction_text(self.nyquist_hz),
            "applied_filter": self.applied_filter.canonical_payload(),
            "applied_notch": self.applied_notch.canonical_payload(),
            "targets": [target.canonical_payload() for target in self.targets],
        }

    def to_rows(self) -> list[dict[str, object]]:
        """Return one audit/provenance row per target for workbook export."""

        common = {
            "Eligibility Method Version": self.method_version,
            "Eligibility Fingerprint": self.fingerprint,
            "Protocol Version": self.protocol.version,
            "Protocol Fingerprint": self.protocol.fingerprint,
            "Presentation Rate Exact (Hz)": _fraction_text(
                self.protocol.presentation_rate_hz
            ),
            "Oddball Rate Exact (Hz)": _fraction_text(self.protocol.oddball_rate_hz),
            "Expected Oddball Cycles": self.protocol.expected_analyzed_oddball_cycles,
            "Realized Oddball Cycles": self.realized_oddball_cycles,
            "Sampling Rate Exact (Hz)": _fraction_text(self.sampling_rate_hz),
            "FFT Sample Count": self.analyzed_samples,
            "FFT Bin Width Exact (Hz)": _fraction_text(self.bin_width_hz),
            "Requested High-pass Exact (Hz)": _fraction_text(
                self.applied_filter.requested_high_pass_hz
            ),
            "Requested Low-pass Exact (Hz)": _fraction_text(
                self.applied_filter.requested_low_pass_hz
            ),
            "Applied High-pass Exact (Hz)": _fraction_text(
                self.applied_filter.applied_high_pass_hz
            ),
            "Applied Low-pass Exact (Hz)": _fraction_text(
                self.applied_filter.applied_low_pass_hz
            ),
            "Applied Filter Method Version": self.applied_filter.method_version,
            "Nyquist Exact (Hz)": _fraction_text(self.nyquist_hz),
            "Applied Notch Centers Exact (Hz)": ", ".join(
                str(_fraction_text(value))
                for value in self.applied_notch.applied_centers_hz
            ),
            "Notch Half-width Exact (Hz)": _fraction_text(
                self.applied_notch.half_width_hz
            ),
            "Applied Notch Method Version": self.applied_notch.method_version,
        }
        rows: list[dict[str, object]] = []
        for item in self.targets:
            rows.append(
                {
                    **common,
                    "Oddball Harmonic Order": item.target.oddball_harmonic_order,
                    "Presentation Harmonic Order": (
                        item.target.presentation_harmonic_order
                        if item.target.presentation_harmonic_order is not None
                        else ""
                    ),
                    "Target Frequency Exact (Hz)": _fraction_text(
                        item.target.frequency_hz
                    ),
                    "Target Frequency (Hz)": float(item.target.frequency_hz),
                    "Target FFT Bin": item.target_bin_index,
                    "Noise Candidate FFT Bins": ",".join(
                        str(value) for value in item.noise_candidate_bin_indices
                    ),
                    "Target Amplitude Status": item.target_amplitude_status,
                    "BCA Available": item.bca_available,
                    "SNR Available": item.snr_available,
                    "Local Z Available": item.local_z_available,
                    "Unavailable Reasons": ";".join(item.reason_codes),
                }
            )
        return rows


def spectral_eligibility_from_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    protocol: FrequencyProtocol | Mapping[str, Any],
) -> SpectralEligibilityResult:
    """Rebuild and verify one exported spectral-eligibility decision.

    The workbook is an audit transport, not a second decision maker. This
    function feeds its recorded run/filter/grid inputs back through
    :func:`resolve_spectral_eligibility` and rejects any missing, mixed, or
    altered target decision before a downstream consumer uses it.
    """

    canonical_protocol = normalize_frequency_protocol(protocol)
    normalized_rows = [dict(row) for row in rows if isinstance(row, Mapping)]
    if not normalized_rows:
        raise SpectralEligibilityError(
            "The Spectral Eligibility sheet is missing or contains no targets; "
            "regenerate the frequency-domain workbook."
        )

    common_columns = (
        "Eligibility Method Version",
        "Eligibility Fingerprint",
        "Protocol Version",
        "Protocol Fingerprint",
        "Presentation Rate Exact (Hz)",
        "Oddball Rate Exact (Hz)",
        "Expected Oddball Cycles",
        "Realized Oddball Cycles",
        "Sampling Rate Exact (Hz)",
        "FFT Sample Count",
        "FFT Bin Width Exact (Hz)",
        "Requested High-pass Exact (Hz)",
        "Requested Low-pass Exact (Hz)",
        "Applied High-pass Exact (Hz)",
        "Applied Low-pass Exact (Hz)",
        "Applied Filter Method Version",
        "Nyquist Exact (Hz)",
        "Applied Notch Centers Exact (Hz)",
        "Notch Half-width Exact (Hz)",
        "Applied Notch Method Version",
    )
    first = normalized_rows[0]
    missing = [column for column in common_columns if column not in first]
    if missing:
        raise SpectralEligibilityError(
            "The Spectral Eligibility sheet lacks current method provenance "
            f"({', '.join(missing)}); regenerate the frequency-domain workbook."
        )
    for row in normalized_rows[1:]:
        for column in common_columns:
            if _normalized_export_cell(row.get(column)) != _normalized_export_cell(
                first.get(column)
            ):
                raise SpectralEligibilityError(
                    "The Spectral Eligibility sheet mixes incompatible run metadata; "
                    "regenerate the frequency-domain workbook."
                )

    if str(first["Eligibility Method Version"]).strip() != SPECTRAL_ELIGIBILITY_METHOD_VERSION:
        raise SpectralEligibilityError(
            "The Spectral Eligibility sheet uses an unsupported method version; "
            "regenerate the frequency-domain workbook."
        )
    if str(first["Protocol Version"]).strip() != canonical_protocol.version:
        raise SpectralEligibilityError(
            "The workbook frequency-protocol version does not match the project."
        )
    if str(first["Protocol Fingerprint"]).strip() != canonical_protocol.fingerprint:
        raise SpectralEligibilityError(
            "The workbook frequency protocol does not match the active project; "
            "regenerate the frequency-domain workbook."
        )
    if str(first["Applied Filter Method Version"]).strip() != "mne_fir_nominal_edges_v1":
        raise SpectralEligibilityError(
            "The workbook applied-filter method is unsupported by the current "
            "spectral-eligibility resolver."
        )

    notch_centers_text = str(
        _normalized_export_cell(first["Applied Notch Centers Exact (Hz)"]) or ""
    )
    notch_centers = tuple(
        part.strip() for part in notch_centers_text.split(",") if part.strip()
    )
    result = resolve_spectral_eligibility(
        protocol=canonical_protocol,
        sampling_rate_hz=_required_export_value(first, "Sampling Rate Exact (Hz)"),
        analyzed_samples=_export_positive_int(first, "FFT Sample Count"),
        requested_high_pass_hz=_optional_export_value(
            first, "Requested High-pass Exact (Hz)"
        ),
        requested_low_pass_hz=_optional_export_value(
            first, "Requested Low-pass Exact (Hz)"
        ),
        applied_high_pass_hz=_required_export_value(
            first, "Applied High-pass Exact (Hz)"
        ),
        applied_low_pass_hz=_required_export_value(
            first, "Applied Low-pass Exact (Hz)"
        ),
        applied_notch_centers_hz=notch_centers,
        notch_half_width_hz=_required_export_value(
            first, "Notch Half-width Exact (Hz)"
        ),
        notch_method_version=str(first["Applied Notch Method Version"]).strip(),
    )

    recorded_fingerprint = str(first["Eligibility Fingerprint"]).strip()
    if result.fingerprint != recorded_fingerprint:
        raise SpectralEligibilityError(
            "The Spectral Eligibility fingerprint does not match its recorded "
            "protocol/filter/grid inputs; regenerate the frequency-domain workbook."
        )
    _require_exported_target_rows_match(normalized_rows, result)
    return result


def _require_exported_target_rows_match(
    rows: Sequence[Mapping[str, Any]],
    result: SpectralEligibilityResult,
) -> None:
    expected_rows = {
        int(row["Oddball Harmonic Order"]): row for row in result.to_rows()
    }
    actual_rows: dict[int, Mapping[str, Any]] = {}
    for row in rows:
        order = _export_positive_int(row, "Oddball Harmonic Order")
        if order in actual_rows:
            raise SpectralEligibilityError(
                "The Spectral Eligibility sheet contains a duplicate harmonic order."
            )
        actual_rows[order] = row
    if actual_rows.keys() != expected_rows.keys():
        raise SpectralEligibilityError(
            "The Spectral Eligibility target list does not match the canonical "
            "project/filter/Nyquist domain; regenerate the workbook."
        )

    exact_fields = (
        "Presentation Harmonic Order",
        "Target Frequency Exact (Hz)",
        "Target FFT Bin",
        "Noise Candidate FFT Bins",
        "Target Amplitude Status",
        "BCA Available",
        "SNR Available",
        "Local Z Available",
        "Unavailable Reasons",
    )
    for order, expected in expected_rows.items():
        actual = actual_rows[order]
        missing = [field for field in exact_fields if field not in actual]
        if missing:
            raise SpectralEligibilityError(
                "The Spectral Eligibility sheet lacks current target fields "
                f"({', '.join(missing)}); regenerate the workbook."
            )
        for field in exact_fields:
            if _normalized_export_cell(actual.get(field)) != _normalized_export_cell(
                expected.get(field)
            ):
                raise SpectralEligibilityError(
                    "The Spectral Eligibility decision for oddball harmonic "
                    f"{order} does not match the canonical resolver ({field})."
                )


def _normalized_export_cell(value: Any) -> object:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return str(value).strip()


def _optional_export_value(row: Mapping[str, Any], field_name: str) -> object | None:
    value = _normalized_export_cell(row.get(field_name))
    return None if value == "" else value


def _required_export_value(row: Mapping[str, Any], field_name: str) -> object:
    value = _optional_export_value(row, field_name)
    if value is None:
        raise SpectralEligibilityError(
            f"The Spectral Eligibility sheet is missing {field_name!r}."
        )
    return value


def _export_positive_int(row: Mapping[str, Any], field_name: str) -> int:
    value = _required_export_value(row, field_name)
    try:
        numeric = float(value)
        parsed = int(numeric)
    except (TypeError, ValueError, OverflowError) as exc:
        raise SpectralEligibilityError(
            f"The Spectral Eligibility field {field_name!r} must be an integer."
        ) from exc
    if not math.isfinite(numeric) or parsed <= 0 or float(parsed) != numeric:
        raise SpectralEligibilityError(
            f"The Spectral Eligibility field {field_name!r} must be a positive integer."
        )
    return parsed


def validate_applied_filter_snapshot(
    *,
    sampling_rate_hz: RateValue,
    requested_high_pass_hz: RateValue | None,
    requested_low_pass_hz: RateValue | None,
    applied_high_pass_hz: RateValue | None,
    applied_low_pass_hz: RateValue | None,
) -> AppliedFilterSnapshot:
    """Validate applied nominal filter edges against the immutable run request."""

    sample_rate = _exact_fraction(sampling_rate_hz, field_name="sampling_rate_hz")
    nyquist = sample_rate / 2
    requested_high = _optional_edge(
        requested_high_pass_hz,
        field_name="requested_high_pass_hz",
    )
    requested_low = _optional_edge(
        requested_low_pass_hz,
        field_name="requested_low_pass_hz",
    )
    if applied_high_pass_hz in (None, "") or applied_low_pass_hz in (None, ""):
        raise SpectralEligibilityError(
            "Applied filter metadata is missing; spectral eligibility cannot infer "
            "successful filtering from requested settings."
        )
    try:
        applied_high = Fraction(str(applied_high_pass_hz).strip())
        applied_low = Fraction(str(applied_low_pass_hz).strip())
    except (AttributeError, ValueError, ZeroDivisionError) as exc:
        raise SpectralEligibilityError(
            "Applied filter metadata must contain finite numeric passband edges."
        ) from exc
    if applied_high < 0 or applied_low <= 0 or applied_high >= applied_low:
        raise SpectralEligibilityError(
            "Applied filter metadata must define an ordered non-negative passband."
        )
    if applied_low > nyquist + FILTER_EDGE_REPRESENTATION_TOLERANCE_HZ:
        raise SpectralEligibilityError(
            "Applied low-pass metadata exceeds the realized Nyquist frequency."
        )

    expected_high = requested_high if requested_high is not None else Fraction(0)
    expected_low = requested_low if requested_low is not None else nyquist
    if abs(applied_high - expected_high) > FILTER_EDGE_REPRESENTATION_TOLERANCE_HZ:
        raise SpectralEligibilityError(
            "Applied high-pass metadata does not match the canonical project/run "
            f"setting within {float(FILTER_EDGE_REPRESENTATION_TOLERANCE_HZ):g} Hz."
        )
    if abs(applied_low - expected_low) > FILTER_EDGE_REPRESENTATION_TOLERANCE_HZ:
        raise SpectralEligibilityError(
            "Applied low-pass metadata does not match the canonical project/run "
            f"setting within {float(FILTER_EDGE_REPRESENTATION_TOLERANCE_HZ):g} Hz."
        )
    return AppliedFilterSnapshot(
        requested_high_pass_hz=requested_high,
        requested_low_pass_hz=requested_low,
        applied_high_pass_hz=applied_high,
        applied_low_pass_hz=min(applied_low, nyquist),
        nyquist_hz=nyquist,
    )


def build_applied_notch_snapshot(
    *,
    applied_centers_hz: Iterable[RateValue] = (),
    half_width_hz: RateValue,
    method_version: str,
) -> AppliedNotchSnapshot:
    """Normalize the notch supports that actually transformed the data."""

    half_width = _exact_fraction(half_width_hz, field_name="notch_half_width_hz")
    centers = tuple(
        sorted(
            {
                _exact_fraction(value, field_name="applied_notch_center_hz")
                for value in applied_centers_hz
            }
        )
    )
    version = str(method_version or "").strip()
    if not version:
        raise SpectralEligibilityError(
            "Applied notch metadata requires a method version, including when no "
            "center was effective."
        )
    return AppliedNotchSnapshot(
        applied_centers_hz=centers,
        half_width_hz=half_width,
        method_version=version,
    )


def resolve_spectral_eligibility(
    *,
    protocol: FrequencyProtocol | Mapping[str, Any],
    sampling_rate_hz: RateValue,
    analyzed_samples: int,
    requested_high_pass_hz: RateValue | None,
    requested_low_pass_hz: RateValue | None,
    applied_high_pass_hz: RateValue | None,
    applied_low_pass_hz: RateValue | None,
    applied_notch_centers_hz: Sequence[RateValue] = (),
    notch_half_width_hz: RateValue = Fraction(1, 2),
    notch_method_version: str = "fft_hann_multinotch_v1",
) -> SpectralEligibilityResult:
    """Resolve every technically reachable project harmonic without a ceiling."""

    canonical_protocol = normalize_frequency_protocol(protocol)
    if not canonical_protocol.is_ready or canonical_protocol.oddball_rate_hz is None:
        raise SpectralEligibilityError(
            "A ready project frequency protocol is required for spectral eligibility."
        )
    if isinstance(analyzed_samples, bool) or not isinstance(analyzed_samples, int):
        raise SpectralEligibilityError("analyzed_samples must be a positive integer.")
    if analyzed_samples <= 0:
        raise SpectralEligibilityError("analyzed_samples must be a positive integer.")

    sample_rate = _exact_fraction(sampling_rate_hz, field_name="sampling_rate_hz")
    bin_width = sample_rate / analyzed_samples
    nyquist = sample_rate / 2
    exact_cycles = (
        canonical_protocol.oddball_rate_hz * analyzed_samples / sample_rate
    )
    if exact_cycles.denominator != 1:
        raise SpectralEligibilityError(
            "The realized FFT span does not place the project oddball rate exactly "
            "on a bin; nearest-bin fallback is disabled."
        )
    realized_cycles = int(exact_cycles)
    if (
        canonical_protocol.expected_analyzed_oddball_cycles is None
        or realized_cycles
        != canonical_protocol.expected_analyzed_oddball_cycles
    ):
        raise SpectralEligibilityError(
            "The realized FFT span does not match the project's expected analyzed "
            "oddball-cycle count."
        )

    filter_snapshot = validate_applied_filter_snapshot(
        sampling_rate_hz=sample_rate,
        requested_high_pass_hz=requested_high_pass_hz,
        requested_low_pass_hz=requested_low_pass_hz,
        applied_high_pass_hz=applied_high_pass_hz,
        applied_low_pass_hz=applied_low_pass_hz,
    )
    notch_snapshot = build_applied_notch_snapshot(
        applied_centers_hz=applied_notch_centers_hz,
        half_width_hz=notch_half_width_hz,
        method_version=notch_method_version,
    )

    oddball_rate = canonical_protocol.oddball_rate_hz
    highest_target_bound = min(filter_snapshot.applied_low_pass_hz, nyquist)
    highest_order = int(highest_target_bound // oddball_rate)
    if highest_order > MAX_CANONICAL_HARMONIC_COUNT:
        raise SpectralEligibilityError(
            "The filter-derived harmonic domain exceeds the versioned finite "
            f"implementation guard ({MAX_CANONICAL_HARMONIC_COUNT} harmonics)."
        )
    # Reuse only pure, immutable method inputs after every current request has
    # passed the unchanged strict grid/filter/notch checks. Workbook rows are
    # still independently compared against the resolved result on each read.
    calculate = (
        _cached_eligibility_result
        if highest_order <= _MAX_CACHED_ELIGIBILITY_HARMONICS
        else _calculate_eligibility_result
    )
    return calculate(
        canonical_protocol, sample_rate, analyzed_samples, realized_cycles,
        bin_width, nyquist, filter_snapshot, notch_snapshot, highest_order,
    )


def _calculate_eligibility_result(
    canonical_protocol: FrequencyProtocol, sample_rate: Fraction,
    analyzed_samples: int, realized_cycles: int, bin_width: Fraction,
    nyquist: Fraction, filter_snapshot: AppliedFilterSnapshot,
    notch_snapshot: AppliedNotchSnapshot, highest_order: int,
) -> SpectralEligibilityResult:
    oddball_rate = canonical_protocol.oddball_rate_hz
    if highest_order <= 0:
        targets: tuple[SpectralTargetAvailability, ...] = ()
    else:
        harmonic_targets = enumerate_protocol_harmonics(
            canonical_protocol,
            oddball_rate * highest_order,
        )
        targets = tuple(
            _resolve_target(
                target=target,
                protocol=canonical_protocol,
                realized_cycles=realized_cycles,
                bin_width_hz=bin_width,
                nyquist_hz=nyquist,
                applied_filter=filter_snapshot,
                applied_notch=notch_snapshot,
            )
            for target in harmonic_targets
        )

    return SpectralEligibilityResult(
        protocol=canonical_protocol,
        sampling_rate_hz=sample_rate,
        analyzed_samples=analyzed_samples,
        realized_oddball_cycles=realized_cycles,
        bin_width_hz=bin_width,
        nyquist_hz=nyquist,
        applied_filter=filter_snapshot,
        applied_notch=notch_snapshot,
        targets=targets,
    )


_cached_eligibility_result = lru_cache(maxsize=16)(_calculate_eligibility_result)


def _resolve_target(
    *,
    target: HarmonicTarget,
    protocol: FrequencyProtocol,
    realized_cycles: int,
    bin_width_hz: Fraction,
    nyquist_hz: Fraction,
    applied_filter: AppliedFilterSnapshot,
    applied_notch: AppliedNotchSnapshot,
) -> SpectralTargetAvailability:
    exact_bin = target.frequency_hz / bin_width_hz
    if exact_bin.denominator != 1:  # Defensive: the first harmonic check implies all.
        raise SpectralEligibilityError(
            "A canonical project harmonic is not exactly represented on the FFT grid."
        )
    target_bin = int(exact_bin)
    candidate_indices = tuple(
        target_bin + offset for offset in QC14_NOISE_CANDIDATE_OFFSETS
    )
    candidate_frequencies = tuple(index * bin_width_hz for index in candidate_indices)
    lower = target.frequency_hz - QC14_NOISE_WINDOW_BINS * bin_width_hz
    upper = target.frequency_hz + QC14_NOISE_WINDOW_BINS * bin_width_hz

    reasons: list[str] = []
    if realized_cycles <= MINIMUM_REALIZED_ODDBALL_CYCLES_EXCLUSIVE:
        reasons.append(REASON_INSUFFICIENT_ODDBALL_CYCLES)
    if target.frequency_hz <= 0:
        reasons.append(REASON_TARGET_AT_OR_BELOW_DC)
    if target.frequency_hz >= nyquist_hz:
        reasons.append(REASON_TARGET_AT_OR_ABOVE_NYQUIST)
    if target.frequency_hz < applied_filter.applied_high_pass_hz:
        reasons.append(REASON_TARGET_BELOW_HIGH_PASS)
    if target.frequency_hz > applied_filter.applied_low_pass_hz:
        reasons.append(REASON_TARGET_ABOVE_LOW_PASS)
    if lower <= 0:
        reasons.append(REASON_NOISE_WINDOW_REACHES_DC)
    if upper >= nyquist_hz:
        reasons.append(REASON_NOISE_WINDOW_REACHES_NYQUIST)
    if lower < applied_filter.applied_high_pass_hz:
        reasons.append(REASON_NOISE_WINDOW_BELOW_HIGH_PASS)
    if upper > applied_filter.applied_low_pass_hz:
        reasons.append(REASON_NOISE_WINDOW_ABOVE_LOW_PASS)

    target_notches = tuple(
        center
        for center in applied_notch.applied_centers_hz
        if abs(target.frequency_hz - center) < applied_notch.half_width_hz
    )
    if target_notches:
        reasons.append(REASON_TARGET_NOTCH_COLLISION)
    noise_notches = tuple(
        (index, center)
        for index, frequency in zip(candidate_indices, candidate_frequencies)
        for center in applied_notch.applied_centers_hz
        if abs(frequency - center) < applied_notch.half_width_hz
    )
    if noise_notches:
        reasons.append(REASON_NOISE_NOTCH_COLLISION)

    tagged_collisions = _tagged_noise_collisions(
        candidate_indices=candidate_indices,
        candidate_frequencies_hz=candidate_frequencies,
        protocol=protocol,
    )
    if tagged_collisions:
        reasons.append(REASON_TAGGED_HARMONIC_COLLISION)

    ordered_reasons = tuple(dict.fromkeys(reasons))
    target_inside_static_support = not any(
        reason
        in {
            REASON_TARGET_AT_OR_BELOW_DC,
            REASON_TARGET_AT_OR_ABOVE_NYQUIST,
            REASON_TARGET_BELOW_HIGH_PASS,
            REASON_TARGET_ABOVE_LOW_PASS,
        }
        for reason in ordered_reasons
    )
    target_amplitude_status = (
        TARGET_AMPLITUDE_UNAVAILABLE
        if not target_inside_static_support
        else TARGET_AMPLITUDE_AUDIT_ONLY
        if target_notches
        else TARGET_AMPLITUDE_AVAILABLE
    )
    standard_available = not ordered_reasons
    return SpectralTargetAvailability(
        target=target,
        target_bin_index=target_bin,
        noise_candidate_bin_indices=candidate_indices,
        noise_candidate_frequencies_hz=candidate_frequencies,
        target_amplitude_status=target_amplitude_status,
        bca_available=standard_available,
        snr_available=standard_available,
        local_z_available=standard_available,
        reason_codes=ordered_reasons,
        target_notch_centers_hz=target_notches,
        noise_notch_collisions=noise_notches,
        tagged_noise_collisions=tagged_collisions,
    )


def _tagged_noise_collisions(
    *,
    candidate_indices: Sequence[int],
    candidate_frequencies_hz: Sequence[Fraction],
    protocol: FrequencyProtocol,
) -> tuple[tuple[int, str, int], ...]:
    oddball = protocol.oddball_rate_hz
    presentation = protocol.presentation_rate_hz
    if oddball is None or presentation is None:
        raise SpectralEligibilityError("Canonical project rates are incomplete.")
    collisions: list[tuple[int, str, int]] = []
    for index, frequency in zip(candidate_indices, candidate_frequencies_hz):
        if frequency <= 0:
            continue
        oddball_order = frequency / oddball
        if oddball_order.denominator == 1:
            collisions.append((int(index), "oddball", int(oddball_order)))
            continue
        presentation_order = frequency / presentation
        if presentation_order.denominator == 1:
            collisions.append(
                (int(index), "presentation", int(presentation_order))
            )
    return tuple(collisions)


def intersect_eligible_harmonics(
    results: Sequence[SpectralEligibilityResult],
) -> tuple[HarmonicTarget, ...]:
    """Return the documented standard-metric intersection across FFT inputs."""

    if not results:
        return ()
    protocol_fingerprint = results[0].protocol.fingerprint
    if any(result.protocol.fingerprint != protocol_fingerprint for result in results):
        raise SpectralEligibilityError(
            "Cannot intersect spectral eligibility across different project protocols."
        )
    eligible_orders = {
        item.target.oddball_harmonic_order for item in results[0].eligible_targets
    }
    for result in results[1:]:
        eligible_orders.intersection_update(
            item.target.oddball_harmonic_order for item in result.eligible_targets
        )
    return tuple(
        item.target
        for item in results[0].eligible_targets
        if item.target.oddball_harmonic_order in eligible_orders
    )


__all__ = [
    "FILTER_EDGE_REPRESENTATION_TOLERANCE_HZ",
    "MAX_CANONICAL_HARMONIC_COUNT",
    "MINIMUM_REALIZED_ODDBALL_CYCLES_EXCLUSIVE",
    "QC14_NOISE_CANDIDATE_OFFSETS",
    "QC14_NOISE_WINDOW_BINS",
    "QC14_RETAINED_NOISE_BIN_COUNT",
    "REASON_INSUFFICIENT_ODDBALL_CYCLES",
    "REASON_NOISE_NOTCH_COLLISION",
    "REASON_NOISE_WINDOW_ABOVE_LOW_PASS",
    "REASON_NOISE_WINDOW_BELOW_HIGH_PASS",
    "REASON_NOISE_WINDOW_REACHES_DC",
    "REASON_NOISE_WINDOW_REACHES_NYQUIST",
    "REASON_TAGGED_HARMONIC_COLLISION",
    "REASON_TARGET_ABOVE_LOW_PASS",
    "REASON_TARGET_AT_OR_ABOVE_NYQUIST",
    "REASON_TARGET_AT_OR_BELOW_DC",
    "REASON_TARGET_BELOW_HIGH_PASS",
    "REASON_TARGET_NOTCH_COLLISION",
    "SPECTRAL_ELIGIBILITY_METHOD_VERSION",
    "TARGET_AMPLITUDE_AUDIT_ONLY",
    "TARGET_AMPLITUDE_AVAILABLE",
    "TARGET_AMPLITUDE_UNAVAILABLE",
    "AppliedFilterSnapshot",
    "AppliedNotchSnapshot",
    "SpectralEligibilityError",
    "SpectralEligibilityResult",
    "SpectralTargetAvailability",
    "build_applied_notch_snapshot",
    "intersect_eligible_harmonics",
    "resolve_spectral_eligibility",
    "spectral_eligibility_from_rows",
    "validate_applied_filter_snapshot",
]
