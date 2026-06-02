"""Harmonic selection helpers for publication scalp maps."""

from __future__ import annotations

import math
from collections.abc import Callable

from Tools.Stats.analysis.dv_policy_group_significant import (
    GROUP_SIGNIFICANT_BASE_TOLERANCE_HZ,
)
from Tools.Stats.analysis.dv_policy_settings import LOCKED_ODDBALL_FREQUENCY_HZ


def parse_frequency_list(text: str) -> tuple[float, ...]:
    """Parse a comma-separated frequency list, preserving sorted unique values."""

    values: list[float] = []
    for token in str(text).split(","):
        item = token.strip()
        if not item:
            continue
        try:
            value = float(item)
        except ValueError as exc:
            raise ValueError(f"Invalid frequency value: {item}") from exc
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"Frequency must be positive and finite: {item}")
        values.append(round(value, 4))
    unique = sorted(set(values))
    if not unique:
        raise ValueError("Provide at least one frequency.")
    return tuple(unique)


def is_base_overlap(
    frequency_hz: float,
    base_frequency_hz: float,
    *,
    tolerance_hz: float = GROUP_SIGNIFICANT_BASE_TOLERANCE_HZ,
) -> bool:
    """Return whether a frequency overlaps a base-rate harmonic."""

    if base_frequency_hz <= 0:
        return False
    multiple = round(float(frequency_hz) / float(base_frequency_hz))
    if multiple <= 0:
        return False
    return abs(float(frequency_hz) - multiple * float(base_frequency_hz)) < float(tolerance_hz)


def expand_highest_oddball_harmonics(
    highest_frequency_hz: float,
    *,
    base_frequency_hz: float,
    oddball_frequency_hz: float = LOCKED_ODDBALL_FREQUENCY_HZ,
    tolerance_hz: float = GROUP_SIGNIFICANT_BASE_TOLERANCE_HZ,
) -> tuple[float, ...]:
    """Expand locked oddball harmonics up to a user-entered highest frequency."""

    highest = float(highest_frequency_hz)
    oddball = float(oddball_frequency_hz)
    if not math.isfinite(highest) or highest <= 0:
        raise ValueError("Highest harmonic frequency must be positive.")
    if not math.isfinite(oddball) or oddball <= 0:
        raise ValueError("Oddball frequency must be positive.")

    harmonics: list[float] = []
    harmonic_index = 1
    while True:
        frequency = round(oddball * harmonic_index, 4)
        if frequency > highest + tolerance_hz:
            break
        if not is_base_overlap(
            frequency,
            base_frequency_hz,
            tolerance_hz=tolerance_hz,
        ):
            harmonics.append(frequency)
        harmonic_index += 1
    if not harmonics:
        raise ValueError("No oddball harmonics remain after base-rate exclusion.")
    return tuple(harmonics)


def stats_selected_harmonics(
    selector: Callable[..., object],
    **selection_kwargs: object,
) -> tuple[float, ...]:
    """Call the Stats harmonic-selection path and return selected harmonics."""

    selection = selector(**selection_kwargs)
    values = getattr(selection, "selected_harmonics_hz", None)
    if values is None:
        raise ValueError("Stats harmonic selector did not return selected_harmonics_hz.")
    parsed = tuple(round(float(value), 4) for value in values)
    if not parsed:
        raise ValueError("Stats harmonic selector returned no harmonics.")
    return parsed
