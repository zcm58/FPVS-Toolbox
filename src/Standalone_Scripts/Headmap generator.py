"""
BioSemi-64 schematic headmap (labels only) -> SVG

Run this script to generate a top-down 2D headmap with the electrode names. Useful for publications or illustration.

IMPORTANT:
OUTPUT_SVG must be a FULL FILE PATH including the filename, not just a folder.
"""

from __future__ import annotations

import os
import math
from typing import Dict, List, Tuple

import numpy as np
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Polygon, PathPatch
from matplotlib.path import Path


# =========================
# USER CONFIG
# =========================
OUTPUT_SVG = r"C:\Users\zackm\OneDrive - Mississippi State University\Office Desktop\Thesis Defense Figures\biosemi64_headmap.svg"

FIGSIZE_IN = (6.0, 6.0)       # figure size in inches
HEAD_RADIUS = 1.0             # head circle radius in data units
HEAD_LINEWIDTH = 2.0          # outline thickness
LABEL_FONTSIZE = 12           # label size
INNER_MARGIN = 0.08           # keeps labels inside the head circle
TRANSPARENT_BG = True         # False -> white background

# If you want small dots at electrode locations, set to True
SHOW_ELECTRODE_DOTS = False
DOT_SIZE = 10  # points


# =========================
# STYLE (SVG-friendly)
# =========================
mpl.rcParams["svg.fonttype"] = "none"     # keep text editable in the SVG
mpl.rcParams["font.family"] = "Arial"    # on Windows this is usually available; fallback occurs if not
mpl.rcParams["font.size"] = LABEL_FONTSIZE


# =========================
# BIOSEMI-64 SCHEMATIC ROWS
# (Matches the common 10-20-ish schematic arrangement people use in figures)
# Edit these rows if you want to add/remove channels.
# =========================
ROWS: List[Tuple[float, List[str]]] = [
    (0.82, ["FP1", "FPZ", "FP2"]),
    (0.70, ["AF7", "AF3", "AFZ", "AF4", "AF8"]),
    (0.55, ["F7", "F5", "F3", "F1", "FZ", "F2", "F4", "F6", "F8"]),
    (0.35, ["FT7", "FC5", "FC3", "FC1", "FCZ", "FC2", "FC4", "FC6", "FT8"]),
    (0.10, ["T7", "C5", "C3", "C1", "CZ", "C2", "C4", "C6", "T8"]),
    (-0.15, ["TP7", "CP5", "CP3", "CP1", "CPZ", "CP2", "CP4", "CP6", "TP8"]),
    (-0.40, ["P7", "P5", "P3", "P1", "PZ", "P2", "P4", "P6", "P8"]),
    (-0.52, ["P9", "P10"]),
    (-0.68, ["PO7", "PO3", "POZ", "PO4", "PO8"]),
    (-0.82, ["O1", "OZ", "O2"]),
    (-0.93, ["IZ"]),
]


def _row_positions(
    y: float,
    labels: List[str],
    radius: float,
    margin: float,
) -> List[Tuple[str, float, float]]:
    """Evenly space labels across the available head width at vertical position y."""
    # max half-width inside circle at this y, with a little margin
    xmax = math.sqrt(max(radius * radius - y * y, 0.0)) - margin
    xmax = max(xmax, 0.0)

    n = len(labels)
    if n == 1:
        xs = [0.0]
    elif n == 2:
        xs = [-xmax, xmax]
    else:
        xs = np.linspace(-xmax, xmax, n)

    return [(lab, float(x), float(y)) for lab, x in zip(labels, xs)]


def make_positions(
    rows: List[Tuple[float, List[str]]],
    radius: float,
    margin: float,
) -> Dict[str, Tuple[float, float]]:
    """Build name->(x,y) positions from row definitions."""
    pos: Dict[str, Tuple[float, float]] = {}
    for y, labs in rows:
        for lab, x, yy in _row_positions(y, labs, radius, margin):
            pos[lab] = (x, yy)
    return pos


def add_ear_open(
    ax: plt.Axes,
    side: int,
    radius: float,
    lw: float,
    color: str = "black",
) -> None:
    """Draw a clean (open) ear shape on left (-1) or right (+1)."""
    s = float(side)
    x0 = s * radius

    ear_w = 0.16 * radius
    ear_h = 0.22 * radius

    # Outer ear: two quadratic Beziers
    verts = [
        (x0,  ear_h),
        (x0 + s * ear_w,  ear_h),
        (x0 + s * ear_w,  0.0),
        (x0 + s * ear_w, -ear_h),
        (x0, -ear_h),
    ]
    codes = [Path.MOVETO, Path.CURVE3, Path.CURVE3, Path.CURVE3, Path.CURVE3]
    ax.add_patch(
        PathPatch(
            Path(verts, codes),
            fill=False,
            lw=lw,
            edgecolor=color,
            capstyle="round",
            joinstyle="round",
        )
    )

    # Inner ear
    ear_w2 = ear_w * 0.55
    ear_h2 = ear_h * 0.65
    verts2 = [
        (x0,  ear_h2),
        (x0 + s * ear_w2,  ear_h2),
        (x0 + s * ear_w2,  0.0),
        (x0 + s * ear_w2, -ear_h2),
        (x0, -ear_h2),
    ]
    ax.add_patch(
        PathPatch(
            Path(verts2, codes),
            fill=False,
            lw=lw * 0.8,
            edgecolor=color,
            capstyle="round",
            joinstyle="round",
        )
    )


def draw_head_outline(
    ax: plt.Axes,
    radius: float,
    lw: float,
    color: str = "black",
) -> None:
    """Head circle + nose + ears."""
    ax.add_patch(Circle((0.0, 0.0), radius, fill=False, lw=lw, edgecolor=color))

    # Nose (triangle pointing upward)
    nose_w = 0.22 * radius
    nose_h = 0.12 * radius
    ax.add_patch(
        Polygon(
            [[-nose_w / 2, radius], [0, radius + nose_h], [nose_w / 2, radius]],
            closed=True,
            fill=False,
            lw=lw,
            edgecolor=color,
            joinstyle="round",
        )
    )

    add_ear_open(ax, -1, radius, lw, color)
    add_ear_open(ax, +1, radius, lw, color)


def plot_headmap(
    output_svg: str,
    rows: List[Tuple[float, List[str]]],
    figsize_in: Tuple[float, float],
    radius: float,
    outline_lw: float,
    label_fontsize: int,
    margin: float,
    transparent_bg: bool,
    show_dots: bool,
    dot_size: int,
) -> None:
    # ---- Safety checks for the output path
    if not output_svg.lower().endswith(".svg"):
        raise ValueError(f"OUTPUT_SVG must end with .svg (got: {output_svg!r})")
    if os.path.isdir(output_svg):
        raise ValueError(
            "OUTPUT_SVG points to a folder. It must be a full filename, e.g., "
            r"C:\...\Thesis Defense Figures\biosemi64_headmap.svg"
        )

    out_dir = os.path.dirname(output_svg)
    if out_dir and not os.path.exists(out_dir):
        os.makedirs(out_dir, exist_ok=True)

    # ---- Build positions
    pos = make_positions(rows=rows, radius=radius, margin=margin)

    # ---- Plot
    fig, ax = plt.subplots(figsize=figsize_in)
    ax.set_aspect("equal")
    ax.axis("off")

    draw_head_outline(ax, radius=radius, lw=outline_lw, color="black")

    # Labels
    for name, (x, y) in pos.items():
        # Clamp to stay inside circle (extra safety)
        r = math.sqrt(x * x + y * y)
        max_r = radius - margin / 2
        if r > max_r and r > 0:
            x *= max_r / r
            y *= max_r / r

        # Align edge labels inward so they don't spill outside the head
        ha = "center"
        if abs(x) > 0.72 * radius:
            ha = "right" if x > 0 else "left"

        ax.text(x, y, name, ha=ha, va="center", fontsize=label_fontsize, color="black")

        if show_dots:
            ax.plot([x], [y], marker="o", markersize=dot_size / 2, color="black")

    # Tight framing
    pad = 0.18
    ax.set_xlim(-radius - pad, radius + pad)
    ax.set_ylim(-radius - pad, radius + 0.25)

    fig.savefig(
        output_svg,
        format="svg",
        bbox_inches="tight",
        pad_inches=0.01,
        transparent=transparent_bg,
    )
    plt.close(fig)


def main() -> None:
    plot_headmap(
        output_svg=OUTPUT_SVG,
        rows=ROWS,
        figsize_in=FIGSIZE_IN,
        radius=HEAD_RADIUS,
        outline_lw=HEAD_LINEWIDTH,
        label_fontsize=LABEL_FONTSIZE,
        margin=INNER_MARGIN,
        transparent_bg=TRANSPARENT_BG,
        show_dots=SHOW_ELECTRODE_DOTS,
        dot_size=DOT_SIZE,
    )


if __name__ == "__main__":
    main()