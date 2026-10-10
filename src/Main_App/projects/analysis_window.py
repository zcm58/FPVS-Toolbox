"""Exact planned-window inputs; observed recording lengths never set the target."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from fractions import Fraction
from math import lcm
from typing import Any


STUDIO_PLANNED_WINDOW = "studio_planned"
MANUAL_DURATION_WINDOW = "manual_duration"


class AnalysisWindowError(ValueError):
    """Raised when a planned window cannot define an exact positive FFT span."""


def _positive_fraction(value: Any, field: str) -> Fraction:
    if isinstance(value, bool):
        raise AnalysisWindowError(f"{field} must be a finite positive number.")
    try:
        result = Fraction(str(value).strip())
    except (ValueError, ZeroDivisionError, TypeError) as exc:
        raise AnalysisWindowError(f"{field} must be a finite positive number.") from exc
    if result <= 0:
        raise AnalysisWindowError(f"{field} must be a finite positive number.")
    return result


@dataclass(frozen=True, slots=True)
class AnalysisWindow:
    """A planned maximum, distinct from the protocol's resolved cycle count."""

    mode: str
    maximum_oddball_cycles: int | None
    requested_duration_seconds: Fraction | None
    target_sampling_rate_hz: Fraction
    source_sampling_rates_hz: tuple[Fraction, ...] = ()

    def __post_init__(self) -> None:
        if self.mode not in (STUDIO_PLANNED_WINDOW, MANUAL_DURATION_WINDOW):
            raise AnalysisWindowError(f"Unsupported analysis window mode {self.mode!r}.")
        target = _positive_fraction(self.target_sampling_rate_hz, "Target sampling rate")
        if not isinstance(self.source_sampling_rates_hz, (tuple, list)):
            raise AnalysisWindowError("Source sampling rates must be a sequence.")
        sources = tuple(sorted({
            _positive_fraction(rate, "Source sampling rate")
            for rate in self.source_sampling_rates_hz
        }))
        if self.mode == STUDIO_PLANNED_WINDOW:
            maximum = _positive_fraction(self.maximum_oddball_cycles, "Planned oddball cycles")
            if maximum.denominator != 1 or self.requested_duration_seconds is not None:
                raise AnalysisWindowError("A Studio window requires only a positive whole-cycle bound.")
            object.__setattr__(self, "maximum_oddball_cycles", int(maximum))
        else:
            if self.maximum_oddball_cycles is not None:
                raise AnalysisWindowError("A duration window cannot also declare a cycle bound.")
            duration = _positive_fraction(self.requested_duration_seconds, "Analysis duration")
            object.__setattr__(self, "requested_duration_seconds", duration)
        object.__setattr__(self, "target_sampling_rate_hz", target)
        object.__setattr__(self, "source_sampling_rates_hz", sources)

    @property
    def sampling_rates_hz(self) -> tuple[Fraction, ...]:
        """Include both grids; preprocessing never upsamples a slower source."""

        if not self.source_sampling_rates_hz:
            return (self.target_sampling_rate_hz,)
        return tuple(sorted({
            *self.source_sampling_rates_hz,
            *(min(rate, self.target_sampling_rate_hz) for rate in self.source_sampling_rates_hz),
        }))

    def resolve_cycles(self, oddball_rate_hz: Any) -> int:
        rate = _positive_fraction(oddball_rate_hz, "Oddball rate")
        maximum = (
            self.maximum_oddball_cycles
            if self.mode == STUDIO_PLANNED_WINDOW
            else int(self.requested_duration_seconds * rate)
        )
        step = lcm(*(int((grid / rate).denominator) for grid in self.sampling_rates_hz))
        cycles = int(maximum) // step * step
        if cycles < 1:
            raise AnalysisWindowError(
                "The planned analysis window is too short for one complete FFT-compatible "
                f"span. Increase the duration to at least {Fraction(step) / rate} seconds."
            )
        return cycles

    def with_sampling_rates(
        self, *, target_sampling_rate_hz: Any, source_sampling_rates_hz: Sequence[Any],
    ) -> AnalysisWindow:
        return replace(
            self,
            target_sampling_rate_hz=target_sampling_rate_hz,
            source_sampling_rates_hz=tuple(source_sampling_rates_hz),
        )

    def to_manifest(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "maximum_oddball_cycles": self.maximum_oddball_cycles,
            "requested_duration_seconds": (
                str(self.requested_duration_seconds)
                if self.requested_duration_seconds is not None else None
            ),
            "target_sampling_rate_hz": str(self.target_sampling_rate_hz),
            "source_sampling_rates_hz": [str(rate) for rate in self.source_sampling_rates_hz],
        }

    @classmethod
    def from_manifest(cls, value: Mapping[str, Any]) -> AnalysisWindow:
        if not isinstance(value, Mapping):
            raise AnalysisWindowError("analysis_window must be an object.")
        expected = {
            "mode", "maximum_oddball_cycles", "requested_duration_seconds",
            "target_sampling_rate_hz", "source_sampling_rates_hz",
        }
        if set(value) != expected:
            raise AnalysisWindowError("analysis_window fields are missing or unsupported.")
        return cls(
            mode=value["mode"],
            maximum_oddball_cycles=value["maximum_oddball_cycles"],
            requested_duration_seconds=value["requested_duration_seconds"],
            target_sampling_rate_hz=value["target_sampling_rate_hz"],
            source_sampling_rates_hz=value["source_sampling_rates_hz"],
        )
