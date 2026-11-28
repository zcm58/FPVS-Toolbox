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

# Approximate the printed magnitude legend in Feuerriegel et al. (2018),
# Fig. 5A, DOI 10.1016/j.biopsycho.2018.09.002. Positions are fractions of
# the selected metric range. Preserve zero/threshold handling in the caller.
SURFACE_COLORMAP_STOPS: tuple[tuple[float, str], ...] = (
    (0.00, "#222a86"),
    (0.10, "#314daa"),
    (0.20, "#3662b6"),
    (0.30, "#36c4f8"),
    (0.36, "#6dd2e6"),
    (0.44, "#7fd298"),
    (0.50, "#a3d762"),
    (0.57, "#d4e61e"),
    (0.625, "#fcf805"),
    (0.69, "#feb807"),
    (0.75, "#fe7a20"),
    (0.82, "#f83413"),
    (0.89, "#f2151a"),
    (1.00, "#700809"),
)

_STOPS_BY_VIEW = {"2d": SCALP_COLORMAP_STOPS, "3d": SURFACE_COLORMAP_STOPS, "3d_2d": SURFACE_COLORMAP_STOPS}


def scalp_color_endpoints(
    scalp_view: str, low_color: str | None = None, high_color: str | None = None,
) -> tuple[str, str]:
    """Resolve the two displayed swatches and map endpoints from the same defaults."""
    stops = _STOPS_BY_VIEW[scalp_view]
    return _valid_color(low_color, stops[0][1]), _valid_color(high_color, stops[-1][1])


def scalp_colormap(
    *,
    name: str = "FpvsDetailedScalpSequential",
    low_color: str | None = None,
    high_color: str | None = None,
    scalp_view: str = "2d",
) -> LinearSegmentedColormap:
    """Return the chosen view's color ramp with exact user-selected endpoints."""

    low, high = scalp_color_endpoints(scalp_view, low_color, high_color)
    stops = (
        (0.00, low),
        *_STOPS_BY_VIEW[scalp_view][1:-1],
        (1.00, high),
    )
    return LinearSegmentedColormap.from_list(name, stops, N=256 if scalp_view == "2d" else 1024)


def _valid_color(value: str | None, fallback: str) -> str:
    if value is None:
        return fallback
    color = str(value).strip()
    if is_color_like(color):
        return color
    return fallback
