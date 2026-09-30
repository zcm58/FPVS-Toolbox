"""Explicit Unicorn-only unit interpretation for modular recording inspection.

Input samples are original BDF digital integers, never MNE data already in SI
units. This boundary does not mutate a Raw object or participate in BioSemi
loading. Software unit compatibility is not hardware amplitude calibration.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from fractions import Fraction
import math

from Main_App.io.acquisition_profiles import (
    BUILTIN_REGISTRY, ResolvedAcquisitionContract, UNICORN_FACTORY_RECORDED_LABEL_MAP,
    UNICORN_RECORDER_SOURCE_URL,
)
from Main_App.io.bdf_format import BdfHeader, BdfInspection, BdfSignal


class UnicornUnitError(ValueError):
    """The explicit Unicorn unit contract cannot safely interpret this source."""


def require_unicorn_contract(contract: ResolvedAcquisitionContract) -> None:
    """Reject legacy defaults, BioSemi and lookalike/custom profiles before I/O."""
    if (not isinstance(contract, ResolvedAcquisitionContract)
            or contract.legacy_default
            or contract.profile != BUILTIN_REGISTRY.lookup("profiles", "unicorn_hybrid_black", "1.0")
            or contract.montage != BUILTIN_REGISTRY.lookup("montages", "unicorn8", "1.0")
            or contract.format_adapter != BUILTIN_REGISTRY.lookup("format_adapters", "bdf", "1.0")):
        raise UnicornUnitError("Unit correction requires the explicit built-in Unicorn acquisition contract; never BioSemi.")


@dataclass(frozen=True)
class UnicornChannelUnit:
    source_label: str
    recorded_unit: str
    interpreted_unit: str
    physical_to_volts: float
    recorder_label_correction: bool


@dataclass(frozen=True)
class UnicornUnitPolicy:
    channels: tuple[UnicornChannelUnit, ...]

    def summary(self) -> dict:
        return {
            "id": "unicorn_recorder_eeg_units", "version": "1.0",
            "reference": UNICORN_RECORDER_SOURCE_URL,
            "input": "original_bdf_digital_samples", "output_unit": "V",
            "conversion_order": "bdf_digital_to_physical_then_volts",
            "channels": [asdict(channel) for channel in self.channels],
            "hardware_amplitude_calibration": "unverified",
        }


def _physical_calibration(signal: BdfSignal, factor: float) -> tuple[float, float]:
    try:
        span = signal.digital_maximum - signal.digital_minimum
        gain = float((Fraction(signal.physical_maximum) - Fraction(signal.physical_minimum)) / span)
        offset = float(signal.physical_minimum)
    except OverflowError as exc:
        raise UnicornUnitError("BDF calibration exceeds finite EEG precision.") from exc
    if (not math.isfinite(gain) or gain <= 0 or gain * factor == 0
            or not math.isfinite(offset) or not math.isfinite(offset + span * gain)):
        raise UnicornUnitError("BDF calibration cannot be represented as finite, nonzero-scale EEG volts.")
    return gain, offset


def resolve_unicorn_unit_policy(
    contract: ResolvedAcquisitionContract, header: BdfHeader,
) -> UnicornUnitPolicy:
    """Interpret valid SI prefixes or the specifically observed Recorder defect.

    The literal ``?V`` exception is limited to the retained Recorder 1.24.02
    header pattern. Neither channel count nor filename can select this policy.
    """
    require_unicorn_contract(contract)
    selected = {name.casefold() for name, _ in contract.source_to_canonical_items}
    signals = tuple(signal for signal in header.signals
                    if not signal.is_annotation and signal.label.casefold() in selected)
    if len(signals) != 8 or {signal.label.casefold() for signal in signals} != selected:
        raise UnicornUnitError("Unicorn unit interpretation requires all eight explicitly mapped EEG channels.")
    if any(Fraction(signal.samples_per_record) / Fraction(header.record_duration) != 250 for signal in signals):
        raise UnicornUnitError("Unicorn unit interpretation requires the native 250 Hz EEG grid.")
    if any(signal.physical_minimum >= signal.physical_maximum for signal in signals):
        raise UnicornUnitError("Unicorn EEG physical calibration ranges must be increasing.")
    if any(signal.physical_dimension == "?V" for signal in signals):
        # Do not generalize the malformed label to renamed channels or other
        # calibration ranges without separately reviewed Recorder evidence.
        expected = set(UNICORN_FACTORY_RECORDED_LABEL_MAP)
        ordinary = {signal.label for signal in header.signals if not signal.is_annotation}
        if ({signal.label for signal in signals} != expected
                or not ordinary <= expected | {"CNT", "VALID", "DT", "Status"}
                or any(signal.physical_dimension != "?V"
                       or signal.physical_minimum != -750000 or signal.physical_maximum != 750000
                       or signal.digital_minimum != -8388608 or signal.digital_maximum != 8388607
                       for signal in signals)):
            raise UnicornUnitError("The ?V correction requires the verified Unicorn Recorder EEG header pattern.")
    units = {"uV": 1e-6, "mV": 1e-3, "V": 1.0, "?V": 1e-6}
    result = []
    for signal in signals:
        if signal.physical_dimension not in units:
            raise UnicornUnitError(f"Unsupported Unicorn EEG unit {signal.physical_dimension!r} for {signal.label!r}.")
        _physical_calibration(signal, units[signal.physical_dimension])
        result.append(UnicornChannelUnit(
            signal.label, signal.physical_dimension,
            "uV" if signal.physical_dimension == "?V" else signal.physical_dimension,
            units[signal.physical_dimension], signal.physical_dimension == "?V",
        ))
    return UnicornUnitPolicy(tuple(result))


def unicorn_eeg_samples_in_volts(
    contract: ResolvedAcquisitionContract, source: BdfInspection,
) -> tuple[tuple[str, tuple[float, ...]], ...]:
    """Convert retained original digital EEG once, without touching other signals.

    Each call derives a fresh result from digital source samples. It cannot
    compound a previous conversion or rescale an already loaded BioSemi Raw.
    """
    policy = resolve_unicorn_unit_policy(contract, source.header)
    if source.processing_blockers:
        raise UnicornUnitError("Continuous recorded samples are required for a Unicorn EEG sample view.")
    digital = dict(source.digital_signals)
    signals = {signal.label: signal for signal in source.header.signals if not signal.is_annotation}
    result = []
    for channel in policy.channels:
        signal = signals[channel.source_label]
        values = digital.get(channel.source_label)
        if values is None or len(values) != signal.samples_per_record * source.header.data_records:
            raise UnicornUnitError(f"Original digital samples are missing for {channel.source_label!r}.")
        if any(type(value) is not int or not signal.digital_minimum <= value <= signal.digital_maximum
               for value in values):
            raise UnicornUnitError("Unit conversion accepts only original integer samples within BDF digital limits.")
        gain, offset = _physical_calibration(signal, channel.physical_to_volts)
        volts = tuple((offset + (value - signal.digital_minimum) * gain) * channel.physical_to_volts
                      for value in values)
        if not all(math.isfinite(value) for value in volts):
            raise UnicornUnitError("BDF calibration cannot be represented as finite, nonzero-scale EEG volts.")
        result.append((channel.source_label, volts))
    return tuple(result)
