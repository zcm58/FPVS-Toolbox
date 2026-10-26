"""Pure adapters between project FPVS protocols and GUI text fields."""

from __future__ import annotations

from dataclasses import dataclass, replace
from collections.abc import Mapping, Sequence
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
from Main_App.projects.preprocessing_settings import PREPROCESSING_DEFAULTS
from Main_App.projects.analysis_window import AnalysisWindowError


ANALYSIS_WINDOW_MODE_CYCLES = "cycles"
ANALYSIS_WINDOW_MODE_DURATION = "manual_duration"
ANALYSIS_WINDOW_MODE_STUDIO = "studio_planned"


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
    condition_oddball_markers_enabled: bool = False
    condition_oddball_marker_codes: tuple[tuple[str, str], ...] = ()
    recording_oddball_markers_enabled: bool = False
    recording_oddball_marker_codes: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = ()
    analysis_window_mode: str = ANALYSIS_WINDOW_MODE_CYCLES
    requested_duration_seconds: str = ""
    target_sampling_rate_hz: str = ""


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
        return "Enter the intended analysis duration"
    exact = _exact_rate_text(value)
    decimal = f"{float(value):.6f}".rstrip("0").rstrip(".")
    if value.denominator == 1:
        return f"{decimal} seconds"
    return f"{decimal} seconds (exactly {exact})"


def editor_values_for_protocol(protocol: FrequencyProtocol) -> ProtocolEditorValues:
    """Map a protocol to editable text without confirming inferred legacy values."""

    protocol = normalize_frequency_protocol(protocol)
    marker_mapping = tuple(
        (str(onset), str(marker))
        for onset, marker in protocol.condition_oddball_marker_codes
    )
    recording_mapping = tuple(
        (recording_id, tuple((str(onset), str(marker)) for onset, marker in codes))
        for recording_id, codes in protocol.recording_oddball_marker_codes
    )
    window = protocol.analysis_window
    analysis_values = {
        "analysis_window_mode": (
            window.mode if window is not None else
            ANALYSIS_WINDOW_MODE_CYCLES if protocol.expected_analyzed_oddball_cycles is not None
            or protocol.status == FREQUENCY_PROTOCOL_STATUS_CONFIRMATION_REQUIRED else
            ANALYSIS_WINDOW_MODE_DURATION
        ),
        "requested_duration_seconds": _editable_rate_text(
            window.requested_duration_seconds if window is not None
            and window.requested_duration_seconds is not None else protocol.derived_analyzed_seconds
        ),
        "target_sampling_rate_hz": _editable_rate_text(window.target_sampling_rate_hz) if window is not None else "",
    }
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
            condition_oddball_markers_enabled=bool(marker_mapping),
            condition_oddball_marker_codes=marker_mapping,
            recording_oddball_markers_enabled=bool(recording_mapping),
            recording_oddball_marker_codes=recording_mapping,
            **analysis_values,
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
        condition_oddball_markers_enabled=bool(marker_mapping),
        condition_oddball_marker_codes=marker_mapping,
        recording_oddball_markers_enabled=bool(recording_mapping),
        recording_oddball_marker_codes=recording_mapping,
        **analysis_values,
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
    condition_oddball_markers_enabled: bool | None = None,
    condition_oddball_marker_codes: Mapping[object, object] | Sequence[tuple[object, object]] | None = None,
    recording_oddball_markers_enabled: bool | None = None,
    recording_oddball_marker_codes: Mapping[object, object] | Sequence[tuple[object, object]] | None = None,
    analysis_window_mode: str | None = None,
    requested_duration_seconds: str | None = None,
    target_sampling_rate_hz: object | None = None,
) -> FrequencyProtocol:
    """Validate editor text and return one immutable canonical protocol."""

    cycles_text = str(expected_analyzed_oddball_cycles).strip()
    existing = (
        normalize_frequency_protocol(existing_protocol)
        if existing_protocol is not None
        else None
    )
    window = existing.analysis_window if existing is not None else None
    mode = analysis_window_mode or (
        window.mode if window is not None
        and cycles_text == str(existing.expected_analyzed_oddball_cycles) else
        ANALYSIS_WINDOW_MODE_CYCLES
    )
    if mode not in (ANALYSIS_WINDOW_MODE_CYCLES, ANALYSIS_WINDOW_MODE_DURATION, ANALYSIS_WINDOW_MODE_STUDIO):
        raise FrequencyProtocolError("Choose an analysis duration, Studio window, or advanced cycle count.")
    cycles: str | None = (cycles_text or None) if mode == ANALYSIS_WINDOW_MODE_CYCLES else None
    source = EXPECTED_CYCLES_SOURCE_MANUAL if cycles is not None else None
    marker_text = str(oddball_marker_code).strip()
    if existing is not None and existing.condition_trigger_maps is not None:
        # The timing constructor still supports legacy shared-marker inputs.
        # Its temporary default is retired when the authoritative maps attach below.
        marker_text = str(DEFAULT_ODDBALL_MARKER_CODE)
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
        and window is None
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

    if condition_oddball_markers_enabled is None:
        marker_mapping = existing.condition_oddball_marker_codes if existing is not None else ()
    elif condition_oddball_markers_enabled:
        marker_mapping = (
            condition_oddball_marker_codes
            if condition_oddball_marker_codes is not None
            else existing.condition_oddball_marker_codes if existing is not None else ()
        )
        if not marker_mapping:
            raise FrequencyProtocolError("Enter an oddball marker for every condition, or turn off condition-specific markers.")
    else:
        marker_mapping = ()
    if marker_mapping:
        protocol = protocol.with_condition_oddball_marker_codes(marker_mapping)

    if recording_oddball_markers_enabled is None:
        recording_mapping = existing.recording_oddball_marker_codes if existing is not None else ()
    elif recording_oddball_markers_enabled:
        recording_mapping = (
            recording_oddball_marker_codes if recording_oddball_marker_codes is not None
            else existing.recording_oddball_marker_codes if existing is not None else ()
        )
        if not recording_mapping:
            raise FrequencyProtocolError("Configure a trigger schema for every recording, or turn off recording-specific trigger schemas.")
    else:
        recording_mapping = ()
    if recording_mapping:
        protocol = protocol.with_recording_oddball_marker_codes(recording_mapping)

    target_rate = (
        target_sampling_rate_hz if target_sampling_rate_hz is not None else
        window.target_sampling_rate_hz if window is not None else
        PREPROCESSING_DEFAULTS["downsample"]
    )
    if mode == ANALYSIS_WINDOW_MODE_STUDIO:
        if window is None or window.mode != ANALYSIS_WINDOW_MODE_STUDIO:
            raise FrequencyProtocolError("Import a Studio project before choosing its automatic analysis window.")
        try:
            updated_window = replace(window, target_sampling_rate_hz=target_rate)
        except AnalysisWindowError as exc:
            raise FrequencyProtocolError(str(exc)) from exc
        protocol = protocol.with_analysis_window(updated_window)
    elif mode == ANALYSIS_WINDOW_MODE_DURATION:
        duration = (
            requested_duration_seconds if requested_duration_seconds is not None else
            window.requested_duration_seconds if window is not None else ""
        )
        if str(duration).strip():
            protocol = protocol.with_analyzed_duration(
                duration, target_sampling_rate_hz=target_rate,
                source_sampling_rates_hz=window.source_sampling_rates_hz if window is not None else (),
            )

    if existing is not None and existing.condition_trigger_maps is not None:
        protocol = protocol.with_condition_trigger_maps(existing.condition_trigger_maps)
    if require_ready and not protocol.is_ready:
        raise FrequencyProtocolError(
            "Enter the expected number of analyzed oddball cycles before saving."
            if mode == ANALYSIS_WINDOW_MODE_CYCLES else
            "Enter the intended analysis duration in seconds before saving."
        )
    return protocol


def condition_marker_editor_rows(
    event_map: Mapping[str, object],
    values: ProtocolEditorValues,
) -> tuple[tuple[str, str, str], ...]:
    """Order editable condition markers by onset code, preserving their identity."""

    saved = dict(values.condition_oddball_marker_codes)
    try:
        labels_by_onset: dict[int, list[str]] = {}
        for label, code in event_map.items():
            onset = int(str(code).strip())
            labels_by_onset.setdefault(onset, []).append(str(label))
    except (TypeError, ValueError) as exc:
        raise FrequencyProtocolError("Condition onset markers must be whole numbers.") from exc
    return tuple(
        (
            " / ".join(labels), str(onset),
            saved.get(str(onset), "" if values.condition_oddball_markers_enabled else values.oddball_marker_code),
        )
        for onset, labels in sorted(labels_by_onset.items())
    )


def protocol_settings_save_requested(
    initial_values: ProtocolEditorValues,
    current_values: ProtocolEditorValues,
    *,
    protocol_tab_active: bool,
) -> bool:
    """Return whether Settings should validate and persist the protocol editor."""

    if not initial_values.condition_oddball_markers_enabled and not current_values.condition_oddball_markers_enabled:
        initial_values = replace(initial_values, condition_oddball_marker_codes=())
        current_values = replace(current_values, condition_oddball_marker_codes=())
    if not initial_values.recording_oddball_markers_enabled and not current_values.recording_oddball_markers_enabled:
        initial_values = replace(initial_values, recording_oddball_marker_codes=())
        current_values = replace(current_values, recording_oddball_marker_codes=())
    if initial_values.analysis_window_mode == current_values.analysis_window_mode:
        if current_values.analysis_window_mode != ANALYSIS_WINDOW_MODE_CYCLES:
            initial_values = replace(initial_values, expected_analyzed_oddball_cycles="")
            current_values = replace(current_values, expected_analyzed_oddball_cycles="")
        if current_values.analysis_window_mode != ANALYSIS_WINDOW_MODE_DURATION:
            initial_values = replace(initial_values, requested_duration_seconds="")
            current_values = replace(current_values, requested_duration_seconds="")
        if current_values.analysis_window_mode == ANALYSIS_WINDOW_MODE_CYCLES:
            initial_values = replace(initial_values, target_sampling_rate_hz="")
            current_values = replace(current_values, target_sampling_rate_hz="")
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
            "Enter the intended analysis duration or advanced analyzed oddball cycles in Settings > Protocol "
            "and save before processing."
        )
    return protocol


__all__ = (
    "ANALYSIS_WINDOW_MODE_CYCLES",
    "ANALYSIS_WINDOW_MODE_DURATION",
    "ANALYSIS_WINDOW_MODE_STUDIO",
    "ProjectProtocolRequiredError",
    "ProtocolEditorValues",
    "build_manual_protocol",
    "condition_marker_editor_rows",
    "duration_summary",
    "editor_values_for_protocol",
    "protocol_settings_save_requested",
    "processing_protocol_snapshot",
    "rate_summary",
)
