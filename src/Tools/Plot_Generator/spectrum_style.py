"""Publication spectrum axes and illustrative FPVS timing key."""

from __future__ import annotations

import math

import numpy as np
from matplotlib.collections import LineCollection

from Main_App.exports.figure_style import apply_axis_text_style, figure_text_kwargs

SNR_TRACE_COLOR = "#3210e8"
SNR_SECOND_TRACE_COLOR = "#d62728"
SCHEMATIC_HEIGHT_IN = 1.05
BASE_RESPONSE_COLOR = "#202020"


def _rates(owner) -> tuple[float, float]:
    return float(owner._analysis_base_freq), float(owner._analysis_oddball_freq)


def _harmonics(rate: float, lower: float, upper: float) -> list[float]:
    if not math.isfinite(rate) or rate <= 0:
        return []
    return [index * rate for index in range(max(1, math.ceil(lower / rate)), math.floor(upper / rate) + 1)]


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


def _pulse_train(ax, indices, count: int, *, y: float, color: str) -> None:
    x_values, y_values = [0.0], [y]
    for index in indices:
        start = index + 0.25
        end = index + 0.75
        x_values.extend((start, start, end, end))
        y_values.extend((y, y + 0.19, y + 0.19, y))
    x_values.append(float(count))
    y_values.append(y)
    ax.plot(x_values, y_values, color=color, linewidth=1.2)


def add_stimulation_schematic(fig, owner) -> None:
    """Append a rate-derived key without shrinking data axes or their legends."""
    base, oddball = _rates(owner)
    width, height = fig.get_size_inches()
    new_height = height + SCHEMATIC_HEIGHT_IN
    positions = [(axis, axis.get_position().frozen()) for axis in fig.axes]
    fig.set_size_inches(width, new_height)
    for axis, position in positions:
        axis.set_position([position.x0, (position.y0 * height + SCHEMATIC_HEIGHT_IN) / new_height,
                           position.width, position.height * height / new_height])
    for annotation in fig.texts:
        x, y = annotation.get_position()
        annotation.set_position((x, (y * height + SCHEMATIC_HEIGHT_IN) / new_height))
    for legend in fig.legends:
        # External legends have already been measured and anchored in figure coordinates.
        anchor = legend.get_bbox_to_anchor().transformed(fig.transFigure.inverted())
        legend.set_bbox_to_anchor((anchor.x0, (anchor.y0 * height + SCHEMATIC_HEIGHT_IN) / new_height),
                                  transform=fig.transFigure)

    key = fig.add_axes([0.08, 0.08 / new_height, 0.88, 0.87 / new_height], label="stimulation_schematic")
    key.set_axis_off()
    key.set_ylim(-0.26, 1.1)
    ratio = base / oddball
    periodic_sequence = math.isclose(ratio, round(ratio), rel_tol=1e-7) and 2 <= round(ratio) <= 12
    count = 2 * round(ratio) if periodic_sequence else 12
    key.set_xlim(0, count / 0.64)
    text_x = count / 0.64 * 0.68
    if periodic_sequence:
        odd_indices = list(range(round(ratio) - 1, count, round(ratio)))
        _pulse_train(key, range(count), count, y=0.35, color=BASE_RESPONSE_COLOR)
        _pulse_train(key, odd_indices, count, y=-0.03, color=SNR_TRACE_COLOR)
        for index in range(count):
            key.text(index + 0.5, 0.85, "O" if index in odd_indices else "S", ha="center",
                     color="#c52b28", **figure_text_kwargs("annotation"))
    else:
        # Only depict a repeating every-Nth-stimulus sequence at readable ratios.
        key.text(0, 0.7, f"Base: {base:g} Hz; Oddball: {oddball:g} Hz", **figure_text_kwargs("annotation"))
        key.text(0, 0.2, "Rates shown without a timing sequence", **figure_text_kwargs("small"))
    for y, label, color in (
        (0.85, "S: Standard; O: Oddball", "#c52b28"),
        (0.38, f"Base response ({base:g} Hz)", BASE_RESPONSE_COLOR),
        (-0.04, f"Oddball response ({oddball:g} Hz)", SNR_TRACE_COLOR),
    ):
        key.text(text_x, y, label, va="center", color=color, **figure_text_kwargs("annotation"))
    key.text(0, -0.25, "Illustrative timing", va="bottom", color="0.4", **figure_text_kwargs("small"))
