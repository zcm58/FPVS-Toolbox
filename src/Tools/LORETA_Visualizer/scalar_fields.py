"""Scalar-gradient helpers for LORETA source rendering."""

from __future__ import annotations

import numpy as np

LORETA_SCALAR_COLORS: tuple[str, ...] = (
    "#2166ac",
    "#67a9cf",
    "#1a9850",
    "#fee08b",
    "#fdae61",
    "#b2182b",
)
LORETA_SMOOTH_SCALAR_COLOR_COUNT = 256
CORTICAL_PAINT_BASE_COLOR = "#c9cdd2"
DEFAULT_SCALAR_MIN = 0.0
DEFAULT_SCALAR_MAX = 1.0


def format_scalar_value(value: float) -> str:
    """Format source-map scalar values for compact UI scale labels."""
    numeric = float(value)
    magnitude = abs(numeric)
    if numeric == 0.0:
        return "0"
    if magnitude >= 10_000.0 or magnitude < 0.001:
        return f"{numeric:.3e}"
    if magnitude < 1.0:
        return f"{numeric:.4f}".rstrip("0").rstrip(".")
    return f"{numeric:.3f}".rstrip("0").rstrip(".")


def resolve_scalar_limits(
    values: np.ndarray,
    *,
    auto_scale: bool,
    manual_min: float = DEFAULT_SCALAR_MIN,
    manual_max: float = DEFAULT_SCALAR_MAX,
) -> tuple[float, float]:
    """Resolve scalar color limits using scalp-map style auto/fixed bounds."""
    if not auto_scale:
        return _valid_limits(float(manual_min), float(manual_max))

    data = np.asarray(values, dtype=float).reshape(-1)
    finite = data[np.isfinite(data)]
    if not len(finite):
        return (DEFAULT_SCALAR_MIN, DEFAULT_SCALAR_MAX)

    min_value = float(np.nanmin(finite))
    max_value = float(np.nanmax(finite))
    vmin = 0.0 if min_value >= 0.0 else min_value
    return _valid_limits(vmin, max_value)


def interpolate_scalar_colors(
    colors: tuple[str, ...] = LORETA_SCALAR_COLORS,
    *,
    count: int = LORETA_SMOOTH_SCALAR_COLOR_COUNT,
) -> tuple[str, ...]:
    """Return a dense linearly interpolated color ramp."""
    sample_count = max(2, int(count))
    if len(colors) < 2:
        return tuple(colors)
    ramp = np.asarray([_hex_to_rgb(color) for color in colors], dtype=float)
    source_positions = np.linspace(0.0, 1.0, len(ramp), dtype=float)
    target_positions = np.linspace(0.0, 1.0, sample_count, dtype=float)
    channels = [
        np.interp(target_positions, source_positions, ramp[:, channel])
        for channel in range(3)
    ]
    interpolated = np.column_stack(channels)
    return tuple(_rgb_to_hex(row) for row in interpolated)


def _valid_limits(vmin: float, vmax: float) -> tuple[float, float]:
    if vmax <= vmin:
        vmax = vmin + 1.0
    return (vmin, vmax)


def _hex_to_rgb(color: str) -> tuple[float, float, float]:
    value = color.strip().lstrip("#")
    if len(value) != 6:
        raise ValueError(f"Scalar color must be a 6-digit hex color: {color!r}")
    return (
        int(value[0:2], 16) / 255.0,
        int(value[2:4], 16) / 255.0,
        int(value[4:6], 16) / 255.0,
    )


def _rgb_to_hex(rgb: np.ndarray) -> str:
    clipped = np.clip(np.rint(np.asarray(rgb, dtype=float) * 255.0), 0, 255).astype(int)
    return f"#{clipped[0]:02x}{clipped[1]:02x}{clipped[2]:02x}"


LORETA_SMOOTH_SCALAR_COLORS: tuple[str, ...] = interpolate_scalar_colors()
