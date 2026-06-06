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
DEFAULT_SCALAR_MIN = 0.0
DEFAULT_SCALAR_MAX = 1.0


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


def _valid_limits(vmin: float, vmax: float) -> tuple[float, float]:
    if vmax <= vmin:
        vmax = vmin + 1.0
    return (vmin, vmax)
