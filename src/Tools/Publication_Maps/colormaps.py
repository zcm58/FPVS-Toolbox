"""Shared colormaps for FPVS scalp-map renderers."""

from __future__ import annotations

from matplotlib.colors import LinearSegmentedColormap, is_color_like

from Tools.Publication_Maps.models import (
    DEFAULT_BCA_HIGH_COLOR,
    DEFAULT_BCA_HIGH_MID_COLOR,
    DEFAULT_BCA_LOW_COLOR,
    DEFAULT_BCA_LOW_MID_COLOR,
    DEFAULT_BCA_MID_COLOR,
    DEFAULT_BCA_UPPER_MID_COLOR,
)

SCALP_COLORMAP_STOPS: tuple[tuple[float, str], ...] = (
    (0.00, DEFAULT_BCA_LOW_COLOR),
    (0.25, DEFAULT_BCA_LOW_MID_COLOR),
    (0.40, DEFAULT_BCA_MID_COLOR),
    (0.60, DEFAULT_BCA_UPPER_MID_COLOR),
    (0.80, DEFAULT_BCA_HIGH_MID_COLOR),
    (1.00, DEFAULT_BCA_HIGH_COLOR),
)


def scalp_colormap(
    *,
    name: str = "FpvsDetailedScalpSequential",
    low_color: str = DEFAULT_BCA_LOW_COLOR,
    high_color: str = DEFAULT_BCA_HIGH_COLOR,
) -> LinearSegmentedColormap:
    """Return the detailed FPVS scalp-map colormap with customizable endpoints."""

    low = _valid_color(low_color, DEFAULT_BCA_LOW_COLOR)
    high = _valid_color(high_color, DEFAULT_BCA_HIGH_COLOR)
    stops = (
        (0.00, low),
        *SCALP_COLORMAP_STOPS[1:-1],
        (1.00, high),
    )
    return LinearSegmentedColormap.from_list(name, stops)


def _valid_color(value: str, fallback: str) -> str:
    color = str(value).strip()
    if is_color_like(color):
        return color
    return fallback
