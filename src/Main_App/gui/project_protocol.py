"""Pure adapters between project FPVS protocols and GUI text fields."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from Main_App.projects import (
    DEFAULT_ODDBALL_EVERY_N,
    DEFAULT_ODDBALL_MARKER_CODE,
    DEFAULT_PRESENTATION_RATE_HZ,
    EXPECTED_CYCLES_SOURCE_MANUAL,
    FREQUENCY_PROTOCOL_STATUS_CONFIRMATION_REQUIRED,
    FREQUENCY_PROTOCOL_STATUS_INCOMPLETE,
    FrequencyProtocol,
    FrequencyProtocolError,
    ODDBALL_INPUT_MODE_DIRECT_HZ,
    ODDBALL_INPUT_MODE_RECURRENCE,
    ODDBALL_MARKER_SOURCE_LEGACY_DEFAULT_55,
    ODDBALL_MARKER_SOURCE_MANUAL,
    normalize_frequency_protocol,
)


class ProjectProtocolRequiredError(ValueError):
    """Raised when a project cannot provide a processing-ready protocol."""


@dataclass(frozen=True, slots=True)
class ProtocolEditorValues:
    """Text values used to initialize the project protocol editor."""

    presentation_rate_hz: str
    oddball_input_mode: str
    oddball_every_n: str
    entered_oddball_rate_hz: str
    expected_analyzed_oddball_cycles: str
    oddball_marker_code: str
    requires_confirmation: bool


def _exact_rate_text(value: Fraction | None) -> str:
    if value is None:
        return ""
    if value.denominator == 1:
        return str(value.numerator)
    return f"{value.numerator}/{value.denominator}"


def _editable_rate_text(value: Fraction | None) -> str:
    if value is None:
        return ""
    decimal = format(float(value), ".12g")
    if Fraction(decimal) == value:
        return decimal
    return _exact_rate_text(value)


def rate_summary(value: Fraction | None) -> str:
    """Return a concise readable rate while preserving recurring identities."""

    if value is None:
        return "—"
    exact = _exact_rate_text(value)
    if value.denominator == 1:
        return f"{exact} Hz"
    decimal = f"{float(value):.8f}".rstrip("0").rstrip(".")
    return f"{decimal} Hz (exactly {exact} Hz)"


def duration_summary(value: Fraction | None) -> str:
    """Return exact/decimal duration text for a protocol preview."""

    if value is None:
        return "Enter the expected cycle count"
    exact = _exact_rate_text(value)
    decimal = f"{float(value):.6f}".rstrip("0").rstrip(".")
    if value.denominator == 1:
        return f"{decimal} seconds"
    return f"{decimal} seconds (exactly {exact})"


def editor_values_for_protocol(protocol: FrequencyProtocol) -> ProtocolEditorValues:
    """Map a protocol to editable text without confirming inferred legacy values."""

    protocol = normalize_frequency_protocol(protocol)
    if protocol.status == FREQUENCY_PROTOCOL_STATUS_CONFIRMATION_REQUIRED:
        presentation_rate = (
            protocol.presentation_rate_hz or DEFAULT_PRESENTATION_RATE_HZ
        )
        input_mode = protocol.oddball_input_mode or ODDBALL_INPUT_MODE_RECURRENCE
        recurrence = protocol.oddball_every_n or DEFAULT_ODDBALL_EVERY_N
        canonical_oddball_rate = (
            protocol.oddball_rate_hz
            or DEFAULT_PRESENTATION_RATE_HZ / DEFAULT_ODDBALL_EVERY_N
        )
        entered_oddball_rate = (
            str(protocol.entered_oddball_rate_hz or "")
            if input_mode == ODDBALL_INPUT_MODE_DIRECT_HZ
            else _editable_rate_text(canonical_oddball_rate)
        )
        return ProtocolEditorValues(
            presentation_rate_hz=_editable_rate_text(presentation_rate),
            oddball_input_mode=input_mode,
            oddball_every_n=str(recurrence),
            entered_oddball_rate_hz=entered_oddball_rate,
            expected_analyzed_oddball_cycles=(
                str(protocol.expected_analyzed_oddball_cycles)
                if protocol.expected_analyzed_oddball_cycles is not None
                else ""
            ),
            oddball_marker_code=str(DEFAULT_ODDBALL_MARKER_CODE),
            requires_confirmation=True,
        )

    direct_rate = (
        str(protocol.entered_oddball_rate_hz or "")
        if protocol.oddball_input_mode == ODDBALL_INPUT_MODE_DIRECT_HZ
        else _editable_rate_text(protocol.oddball_rate_hz)
    )
    return ProtocolEditorValues(
        presentation_rate_hz=_editable_rate_text(protocol.presentation_rate_hz),
        oddball_input_mode=str(protocol.oddball_input_mode),
        oddball_every_n=str(protocol.oddball_every_n or ""),
        entered_oddball_rate_hz=direct_rate,
        expected_analyzed_oddball_cycles=(
            str(protocol.expected_analyzed_oddball_cycles)
            if protocol.expected_analyzed_oddball_cycles is not None
            else ""
        ),
        oddball_marker_code=str(protocol.oddball_marker_code or ""),
        requires_confirmation=False,
    )


def build_manual_protocol(
    *,
    presentation_rate_hz: str,
    oddball_input_mode: str,
    oddball_every_n: str,
    oddball_rate_hz: str,
    expected_analyzed_oddball_cycles: str,
    oddball_marker_code: str,
    existing_protocol: FrequencyProtocol | None = None,
    require_ready: bool = False,
) -> FrequencyProtocol:
    """Validate editor text and return one immutable canonical protocol."""

    cycles_text = str(expected_analyzed_oddball_cycles).strip()
    cycles: str | None = cycles_text or None
    existing = (
        normalize_frequency_protocol(existing_protocol)
        if existing_protocol is not None
        else None
    )
    source = EXPECTED_CYCLES_SOURCE_MANUAL if cycles is not None else None
    marker_text = str(oddball_marker_code).strip()
    if oddball_input_mode == ODDBALL_INPUT_MODE_RECURRENCE:
        protocol = FrequencyProtocol.from_recurrence(
            presentation_rate_hz,
            oddball_every_n,
            expected_analyzed_oddball_cycles=cycles,
            expected_analyzed_oddball_cycles_source=source,
            oddball_marker_code=marker_text,
            oddball_marker_code_source=ODDBALL_MARKER_SOURCE_MANUAL,
        )
    elif oddball_input_mode == ODDBALL_INPUT_MODE_DIRECT_HZ:
        protocol = FrequencyProtocol.from_direct_hz(
            presentation_rate_hz,
            oddball_rate_hz,
            expected_analyzed_oddball_cycles=cycles,
            expected_analyzed_oddball_cycles_source=source,
            oddball_marker_code=marker_text,
            oddball_marker_code_source=ODDBALL_MARKER_SOURCE_MANUAL,
        )
    else:
        raise FrequencyProtocolError(
            "Choose whether oddballs occur every N stimuli or at a direct frequency."
        )

    if (
        existing is not None
        and protocol.expected_analyzed_oddball_cycles is not None
        and protocol.expected_analyzed_oddball_cycles
        == existing.expected_analyzed_oddball_cycles
        and existing.expected_analyzed_oddball_cycles_source is not None
    ):
        protocol = protocol.with_expected_cycles(
            protocol.expected_analyzed_oddball_cycles,
            source=existing.expected_analyzed_oddball_cycles_source,
        )
    if (
        existing is not None
        and existing.oddball_marker_code is not None
        and protocol.oddball_marker_code == existing.oddball_marker_code
        and existing.oddball_marker_code_source is not None
    ):
        protocol = protocol.with_oddball_marker_code(
            protocol.oddball_marker_code,
            source=existing.oddball_marker_code_source,
        )
    elif (
        existing is not None
        and existing.status == FREQUENCY_PROTOCOL_STATUS_CONFIRMATION_REQUIRED
        and existing.oddball_marker_code is None
        and protocol.oddball_marker_code == DEFAULT_ODDBALL_MARKER_CODE
    ):
        protocol = protocol.with_oddball_marker_code(
            protocol.oddball_marker_code,
            source=ODDBALL_MARKER_SOURCE_LEGACY_DEFAULT_55,
        )

    if require_ready and not protocol.is_ready:
        raise FrequencyProtocolError(
            "Enter the expected number of analyzed oddball cycles before saving."
        )
    return protocol


def protocol_settings_save_requested(
    initial_values: ProtocolEditorValues,
    current_values: ProtocolEditorValues,
    *,
    protocol_tab_active: bool,
) -> bool:
    """Return whether Settings should validate and persist the protocol editor."""

    return bool(protocol_tab_active or current_values != initial_values)


def processing_protocol_snapshot(project: Any) -> FrequencyProtocol:
    """Return the project's immutable ready protocol or a concise GUI-facing error."""

    raw_protocol = getattr(project, "frequency_protocol", None)
    if raw_protocol is None:
        raise ProjectProtocolRequiredError(
            "Confirm this project's FPVS protocol in Settings > Protocol before processing."
        )
    try:
        protocol = normalize_frequency_protocol(raw_protocol)
    except (FrequencyProtocolError, TypeError, ValueError) as exc:
        raise ProjectProtocolRequiredError(
            "This project's FPVS protocol is invalid. Correct it in Settings > Protocol "
            f"before processing. Details: {exc}"
        ) from exc
    if protocol.status == FREQUENCY_PROTOCOL_STATUS_CONFIRMATION_REQUIRED:
        raise ProjectProtocolRequiredError(
            "Confirm this project's FPVS protocol in Settings > Protocol before processing."
        )
    if protocol.status == FREQUENCY_PROTOCOL_STATUS_INCOMPLETE or not protocol.is_ready:
        raise ProjectProtocolRequiredError(
            "Enter the expected number of analyzed oddball cycles in Settings > Protocol "
            "and save before processing."
        )
    return protocol


__all__ = (
    "ProjectProtocolRequiredError",
    "ProtocolEditorValues",
    "build_manual_protocol",
    "duration_summary",
    "editor_values_for_protocol",
    "protocol_settings_save_requested",
    "processing_protocol_snapshot",
    "rate_summary",
)
