"""Shared publication figure style constants and helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

FIGURE_EXPORT_DPI = 600
FIGURE_OUTPUT_FORMATS = ("pdf", "png")

FIGURE_FONT_FAMILY = "Arial"
FIGURE_FONT_FALLBACKS = ("Arial", "Helvetica", "DejaVu Sans")

FIGURE_TEXT_SIZE_PT = 10
FIGURE_PANEL_LABEL_SIZE_PT = 12
FIGURE_SMALL_TEXT_MIN_SIZE_PT = 7
FIGURE_SUBSCRIPT_SUPERSCRIPT_MIN_SIZE_PT = 7
FIGURE_LINE_WIDTH_PT = 1.0

FigureTextRole = Literal[
    "axis_label",
    "tick_label",
    "legend",
    "annotation",
    "condition_label",
    "panel_label",
    "small",
]


@dataclass(frozen=True)
class FigureTextSpec:
    point_size: int
    weight: str = "normal"


FIGURE_TEXT_SPECS: dict[FigureTextRole, FigureTextSpec] = {
    "axis_label": FigureTextSpec(FIGURE_TEXT_SIZE_PT),
    "tick_label": FigureTextSpec(FIGURE_TEXT_SIZE_PT),
    "legend": FigureTextSpec(FIGURE_TEXT_SIZE_PT),
    "annotation": FigureTextSpec(FIGURE_TEXT_SIZE_PT),
    "condition_label": FigureTextSpec(FIGURE_TEXT_SIZE_PT),
    "panel_label": FigureTextSpec(FIGURE_PANEL_LABEL_SIZE_PT, "bold"),
    "small": FigureTextSpec(FIGURE_SMALL_TEXT_MIN_SIZE_PT),
}


def figure_text_spec(role: FigureTextRole) -> FigureTextSpec:
    """Return the shared publication figure text spec for a role."""

    return FIGURE_TEXT_SPECS[role]


def figure_text_kwargs(
    role: FigureTextRole,
    *,
    include_family: bool = True,
) -> dict[str, object]:
    """Return Matplotlib text kwargs for the publication figure style."""

    spec = figure_text_spec(role)
    kwargs: dict[str, object] = {
        "fontsize": spec.point_size,
        "fontweight": spec.weight,
    }
    if include_family:
        kwargs["fontfamily"] = FIGURE_FONT_FAMILY
    return kwargs


def figure_legend_kwargs() -> dict[str, object]:
    """Return Matplotlib legend kwargs that keep legend text on the figure style."""

    spec = figure_text_spec("legend")
    return {
        "prop": {
            "family": FIGURE_FONT_FAMILY,
            "size": spec.point_size,
            "weight": spec.weight,
        }
    }


def figure_tick_kwargs() -> dict[str, object]:
    """Return Matplotlib tick-label kwargs."""

    return figure_text_kwargs("tick_label")


def matplotlib_figure_rcparams() -> dict[str, object]:
    """Return rcParams that make Matplotlib figures follow the publication style."""

    fallback_list = list(FIGURE_FONT_FALLBACKS)
    return {
        "font.family": FIGURE_FONT_FAMILY,
        "font.sans-serif": fallback_list,
        "font.size": FIGURE_TEXT_SIZE_PT,
        "axes.titlesize": FIGURE_TEXT_SIZE_PT,
        "axes.labelsize": FIGURE_TEXT_SIZE_PT,
        "xtick.labelsize": FIGURE_TEXT_SIZE_PT,
        "ytick.labelsize": FIGURE_TEXT_SIZE_PT,
        "legend.fontsize": FIGURE_TEXT_SIZE_PT,
        "lines.linewidth": FIGURE_LINE_WIDTH_PT,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
        "axes.unicode_minus": False,
    }


def apply_matplotlib_figure_style() -> None:
    """Apply the publication figure style to Matplotlib rcParams."""

    import matplotlib.pyplot as plt

    plt.rcParams.update(matplotlib_figure_rcparams())


def apply_axis_text_style(ax) -> None:
    """Apply shared font family and tick sizing to an existing Matplotlib axis."""

    tick_kwargs = figure_tick_kwargs()
    fontsize = tick_kwargs["fontsize"]
    fontfamily = str(tick_kwargs["fontfamily"])
    fontweight = tick_kwargs["fontweight"]
    ax.tick_params(labelsize=fontsize)
    for tick_label in [*ax.get_xticklabels(), *ax.get_yticklabels()]:
        tick_label.set_fontfamily(fontfamily)
        tick_label.set_fontweight(fontweight)
        tick_label.set_fontsize(fontsize)


def pil_font_candidates(*, bold: bool) -> tuple[str, ...]:
    """Return local font candidates for PIL text rendering, Arial first."""

    if bold:
        return (
            "arialbd.ttf",
            "Arial Bold.ttf",
            "Helvetica Bold.ttf",
            "DejaVuSans-Bold.ttf",
        )
    return (
        "arial.ttf",
        "Arial.ttf",
        "Helvetica.ttf",
        "DejaVuSans.ttf",
    )
