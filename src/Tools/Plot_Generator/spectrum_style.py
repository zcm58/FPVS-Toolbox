"""Publication spectrum axes and original-value base-response highlighting."""

from __future__ import annotations

import math

import numpy as np
from matplotlib.collections import LineCollection

from Main_App.exports.figure_style import apply_axis_text_style, figure_text_kwargs

SNR_TRACE_COLOR = "#3210e8"
SNR_SECOND_TRACE_COLOR = "#d62728"
BASE_RESPONSE_COLOR = "#202020"


def _rates(owner) -> tuple[float, float]:
    return float(owner._analysis_base_freq), float(owner._analysis_oddball_freq)


def _harmonics(rate: float, lower: float, upper: float) -> list[float]:
    if not math.isfinite(rate) or rate <= 0:
        return []
    lower_ratio, upper_ratio = lower / rate, upper / rate
    # Decimal rates can put exact boundary harmonics just across an integer.
    if math.isclose(lower_ratio, round(lower_ratio), rel_tol=1e-12, abs_tol=1e-12):
        lower_ratio = round(lower_ratio)
    if math.isclose(upper_ratio, round(upper_ratio), rel_tol=1e-12, abs_tol=1e-12):
        upper_ratio = round(upper_ratio)
    return [index * rate for index in range(max(1, math.ceil(lower_ratio)), math.floor(upper_ratio) + 1)]


def style_spectrum_axis(ax, owner, oddball_frequencies) -> None:
    """Label each protocol's eligible harmonics with their actual Hz values."""
    base, _oddball = _rates(owner)
    ax.set_xlim(owner.x_min, owner.x_max)
    ax.set_ylim(owner.y_min, owner.y_max)
    ax.set_xlabel(owner.xlabel, **figure_text_kwargs("axis_label"))
    ax.set_ylabel(owner.ylabel, **figure_text_kwargs("axis_label"))
    base_ticks = _harmonics(base, owner.x_min, owner.x_max)
    odd_ticks = [value for value in oddball_frequencies if owner.x_min <= value <= owner.x_max]
    # Thin labels in wide domains, without changing the data or peak markers.
    # Give the base family priority, and leave enough physical space for text.
    minimum_gap = (owner.x_max - owner.x_min) / 16
    ticks = []
    for value in base_ticks:
        if not ticks or min(abs(value - existing) for existing in ticks) >= minimum_gap:
            ticks.append(value)
    for value in odd_ticks:
        if not ticks or min(abs(value - existing) for existing in ticks) >= minimum_gap:
            ticks.append(value)
    if ticks:
        positions = sorted(ticks)
        ax.set_xticks(positions, [f"{value:g}" for value in positions])
    ax.spines[["top", "right"]].set_visible(False)
    for side in ("bottom", "left"):
        ax.spines[side].set_color(BASE_RESPONSE_COLOR)
        ax.spines[side].set_linewidth(1.2)
    ax.tick_params(direction="in", length=3, width=0.8, color=BASE_RESPONSE_COLOR)
    ax.grid(False)
    if not owner.use_matlab_style:
        ax.axhline(1.0, color="0.7", linestyle="--", linewidth=0.4, zorder=0)
    apply_axis_text_style(ax)


def highlight_base_responses(ax, frequencies, values, owner) -> None:
    """Overdraw original spectral segments at F; never manufacture peak heights."""
    frequencies = np.asarray(frequencies, dtype=float)
    values = np.asarray(values, dtype=float)
    if frequencies.size < 2:
        return
    base, _oddball = _rates(owner)
    segments = []
    for target in _harmonics(base, max(owner.x_min, frequencies.min()), min(owner.x_max, frequencies.max())):
        index = int(np.abs(frequencies - target).argmin())
        start, end = max(0, index - 1), min(frequencies.size, index + 2)
        segment = np.column_stack((frequencies[start:end], values[start:end]))
        segments.append(segment)
    if segments:
        ax.add_collection(LineCollection(segments, colors=BASE_RESPONSE_COLOR, linewidths=0.8, zorder=3))
