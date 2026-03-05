#!/usr/bin/env python3
"""
BioSemi-64 schematic headmap (labels only) -> SVG.

Features
--------
- Clean scalp outline (circle + nose + properly-scaled ears)
- BioSemi-64 electrode names in a readable schematic layout
- ROI-based color coding of electrode label text (user-configurable)
- Dynamic ROI legend (auto-built from ROI_DEFINITIONS)
- Landscape-oriented figure (useful when adding a legend)
- Saves an .svg to a hard-coded output path
- Auto-opens the SVG after saving (Windows/macOS/Linux)

Dependencies
------------
    pip install numpy matplotlib
"""

from __future__ import annotations

import os
import sys
import subprocess
from pathlib import Path
from typing import Dict, Tuple, List, Iterable, Optional, Any

import numpy as np
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Polygon, Arc, Patch


# =========================
# USER SETTINGS (EDIT THESE)
# =========================
OUTPUT_DIR = r"C:\Users\zcm58\OneDrive - Mississippi State University\Office Desktop\FPVS Toolbox Project Root\Semantic Categories 3"
OUTPUT_FILENAME = "biosemi64_headmap.svg"

AUTO_OPEN_SVG = True  # opens the saved SVG after generation

# Landscape orientation helps leave room for the ROI legend.
FIGSIZE_INCHES = (12, 8)     # (width, height)
FONT_FAMILY = "Arial"        # change if you prefer (e.g., "DejaVu Sans")
FONT_SIZE = 12

HEAD_RADIUS = 1.0
OUTLINE_LW = 2.2

# Pull all labels inward so none touch the head outline.
# (Decrease to pull inward more; increase toward 1.0 to push outward.)
LABEL_SCALE = 0.90

# True = transparent background; False = white background
TRANSPARENT_BG = True


# ============================================================
# ROI SETTINGS (EDIT THESE)  <-- main configuration requested
# ============================================================
"""
ROI_DEFINITIONS controls both:
1) which electrode labels get colored, and
2) the dynamic legend entries.

How it works:
- Electrode names are case-insensitive ("FCz" == "FCZ").
- Any electrode not listed in any ROI will be drawn with DEFAULT_LABEL_COLOR.
- If an electrode is listed in multiple ROIs, ROI_OVERLAP_POLICY determines
  which ROI "wins" for coloring.

To change ROI membership:
    - Edit the "electrodes" lists below.
To change colors:
    - Edit each ROI's "color" value. Any Matplotlib color is valid:
      "tab:red", "#ff0000", (1.0, 0.0, 0.0), etc.
"""

ROI_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "Central": {
        "color": "tab:red",
        "electrodes": ["FCz", "Cz", "CPz", "CP1", "C1", "FC1"],
    },
    "Left Parietal": {
        "color": "tab:blue",
        "electrodes": ["P3", "P5", "CP3", "CP5", "CP1"],
    },
    "Right Parietal": {
        "color": "tab:green",
        "electrodes": ["P4", "P6", "CP4", "CP6", "CP2"],
    },
    "Left Occipito-Temporal": {
        "color": "tab:purple",
        "electrodes": ["P7", "P9", "PO7", "PO3", "O1"],
    },
}

# What to do if an electrode appears in multiple ROI electrode lists:
# - "first": keep the first ROI (dict order) and ignore later assignments (prints a warning)
# - "last": later ROIs overwrite earlier ones (prints a warning)
# - "raise": abort with a ValueError so you can fix the overlap explicitly
ROI_OVERLAP_POLICY = "first"

# Colors/appearance for non-ROI labels
DEFAULT_LABEL_COLOR = "black"

# Legend settings
SHOW_ROI_LEGEND = True
LEGEND_TITLE = "ROIs"
LEGEND_FONT_SIZE = 12
LEGEND_TITLE_FONT_SIZE = 12
LEGEND_FRAMEON = False

# Place legend to the right of the head (outside axes).
LEGEND_LOC = "center left"
LEGEND_BBOX_TO_ANCHOR = (1.02, 0.5)

# Optional: include electrode counts in legend labels (e.g., "Central (n=6)")
LEGEND_INCLUDE_COUNTS = True

# Print warnings for missing electrodes / overlaps
ROI_VERBOSE_WARNINGS = True


# =========================
# BioSemi-64 label layout
# =========================
# Row format: (list_of_labels, y_position, x_span)
# x positions are linearly spaced from -x_span to +x_span.
ROWS: List[Tuple[List[str], float, float]] = [
    (["FP1", "FPZ", "FP2"], 0.78, 0.55),
    (["AF7", "AF3", "AFZ", "AF4", "AF8"], 0.66, 0.70),
    (["F7", "F5", "F3", "F1", "FZ", "F2", "F4", "F6", "F8"], 0.52, 0.86),
    (["FT7", "FC5", "FC3", "FC1", "FCZ", "FC2", "FC4", "FC6", "FT8"], 0.34, 0.92),
    (["T7", "C5", "C3", "C1", "CZ", "C2", "C4", "C6", "T8"], 0.06, 0.95),
    (["TP7", "CP5", "CP3", "CP1", "CPZ", "CP2", "CP4", "CP6", "TP8"], -0.18, 0.95),
    (["P7", "P5", "P3", "P1", "PZ", "P2", "P4", "P6", "P8"], -0.44, 0.90),
    (["P9", "P10"], -0.60, 0.78),
    (["PO7", "PO3", "POZ", "PO4", "PO8"], -0.72, 0.72),
    (["O1", "OZ", "O2"], -0.86, 0.45),
    (["IZ"], -0.96, 0.00),
]


def normalize_label(name: str) -> str:
    """
    Normalize an electrode label for matching.

    The plot uses the BioSemi-64 labels as defined in ROWS (typically uppercase).
    ROI definitions are treated case-insensitively, so "FCz" and "FCZ" match.

    This function is intentionally conservative:
    - strips whitespace
    - uppercases
    """
    return name.strip().upper()


def build_label_positions(scale: float = 1.0) -> Dict[str, Tuple[float, float]]:
    """Create 2D label positions from the ROWS definition."""
    coords: Dict[str, Tuple[float, float]] = {}
    for names, y, x_span in ROWS:
        n = len(names)
        xs = np.array([0.0]) if n == 1 else np.linspace(-x_span, x_span, n)
        for name, x in zip(names, xs):
            coords[normalize_label(name)] = (float(x * scale), float(y * scale))

    # Sanity check (BioSemi-64)
    if len(coords) != 64:
        raise ValueError(f"Expected 64 labels, but got {len(coords)}. Check ROWS.")
    return coords


def draw_head_outline(ax: plt.Axes) -> Tuple[float, float]:
    """
    Draw scalp outline and return (ear_width, nose_height) so we can set limits cleanly.
    """
    r = HEAD_RADIUS
    lw = OUTLINE_LW

    # Head circle
    ax.add_patch(Circle((0.0, 0.0), r, fill=False, lw=lw, color="black"))

    # Nose (simple triangle)
    nose_w = 0.18 * r
    nose_h = 0.12 * r
    ax.add_patch(
        Polygon(
            [(-nose_w / 2, r), (0.0, r + nose_h), (nose_w / 2, r)],
            closed=True,
            fill=False,
            lw=lw,
            color="black",
            joinstyle="miter",
        )
    )

    # Ears (clean parenthesis arcs, scaled to head radius)
    ear_w = 0.20 * r
    ear_h = 0.40 * r
    inner_scale = 0.55
    inner_shift = 0.02 * r

    # Left ear: left half of ellipse
    cx_l = -r - ear_w / 2
    ax.add_patch(Arc((cx_l, 0.0), ear_w, ear_h, theta1=90, theta2=270, lw=lw, color="black"))
    ax.add_patch(
        Arc(
            (cx_l - inner_shift, 0.0),
            ear_w * inner_scale,
            ear_h * (inner_scale + 0.10),
            theta1=90,
            theta2=270,
            lw=lw * 0.8,
            color="black",
        )
    )

    # Right ear: right half of ellipse
    cx_r = r + ear_w / 2
    ax.add_patch(Arc((cx_r, 0.0), ear_w, ear_h, theta1=-90, theta2=90, lw=lw, color="black"))
    ax.add_patch(
        Arc(
            (cx_r + inner_shift, 0.0),
            ear_w * inner_scale,
            ear_h * (inner_scale + 0.10),
            theta1=-90,
            theta2=90,
            lw=lw * 0.8,
            color="black",
        )
    )

    return ear_w, nose_h


def build_roi_assignment(
    roi_definitions: Dict[str, Dict[str, Any]],
    valid_labels: Iterable[str],
    *,
    overlap_policy: str = "first",
    verbose: bool = True,
) -> Tuple[Dict[str, str], Dict[str, List[str]]]:
    """
    Build a per-electrode ROI assignment and an ROI->electrodes table.

    Parameters
    ----------
    roi_definitions:
        Mapping of ROI name -> dict with keys:
            - "color": Matplotlib color
            - "electrodes": list/tuple of electrode names (case-insensitive)
        Example:
            {"Central": {"color": "tab:red", "electrodes": ["FCz", "Cz"]}}

    valid_labels:
        Electrode labels that exist in the plot (e.g., coords.keys()).

    overlap_policy:
        What to do if an electrode is listed in multiple ROIs:
            - "first": first ROI wins (dict order); later ones ignored (warn)
            - "last": last ROI wins; overwrites earlier (warn)
            - "raise": raise ValueError on first overlap
        Any other value raises ValueError.

    verbose:
        If True, print warnings for:
            - ROI electrodes not found in the BioSemi-64 layout
            - electrodes that appear in multiple ROIs

    Returns
    -------
    electrode_to_roi:
        Dict mapping electrode label (uppercase) -> ROI name.

    roi_to_electrodes_assigned:
        Dict mapping ROI name -> list of electrodes that ended up assigned to that ROI
        (after resolving overlaps using overlap_policy). Order follows the ROI's
        electrode list.
    """
    valid = {normalize_label(x) for x in valid_labels}

    # Normalize electrode lists (dedupe while preserving order)
    roi_requested: Dict[str, List[str]] = {}
    for roi_name, spec in roi_definitions.items():
        raw_list = spec.get("electrodes", [])
        if not isinstance(raw_list, (list, tuple)):
            raise TypeError(f'ROI "{roi_name}" -> "electrodes" must be a list/tuple.')

        seen: set[str] = set()
        normalized_unique: List[str] = []
        for e in raw_list:
            e_norm = normalize_label(str(e))
            if not e_norm or e_norm in seen:
                continue
            seen.add(e_norm)
            normalized_unique.append(e_norm)

        roi_requested[roi_name] = normalized_unique

    electrode_to_roi: Dict[str, str] = {}
    overlaps: List[Tuple[str, str, str]] = []
    missing: List[Tuple[str, str]] = []

    # Assign electrodes according to policy
    for roi_name, electrodes in roi_requested.items():
        for e in electrodes:
            if e not in valid:
                missing.append((roi_name, e))
                continue

            if e in electrode_to_roi:
                prev = electrode_to_roi[e]
                overlaps.append((e, prev, roi_name))

                if overlap_policy == "raise":
                    raise ValueError(
                        f'Electrode "{e}" is listed in multiple ROIs: "{prev}" and "{roi_name}". '
                        "Resolve the overlap or change ROI_OVERLAP_POLICY."
                    )
                elif overlap_policy == "first":
                    # Keep the existing assignment
                    continue
                elif overlap_policy == "last":
                    electrode_to_roi[e] = roi_name
                else:
                    raise ValueError(
                        f'Unknown overlap_policy="{overlap_policy}". Use "first", "last", or "raise".'
                    )
            else:
                electrode_to_roi[e] = roi_name

    # Build ROI -> electrodes (post-policy) in requested order
    roi_to_electrodes_assigned: Dict[str, List[str]] = {roi: [] for roi in roi_requested}
    for roi_name, electrodes in roi_requested.items():
        for e in electrodes:
            if electrode_to_roi.get(e) == roi_name:
                roi_to_electrodes_assigned[roi_name].append(e)

    if verbose:
        if missing:
            missing_str = ", ".join([f"{roi}:{e}" for roi, e in missing])
            print(f"[WARN] ROI electrodes not found in layout (ignored): {missing_str}")

        if overlaps:
            # Deduplicate overlap messages (same electrode could overlap more than once)
            seen_overlap: set[Tuple[str, str, str]] = set()
            unique = []
            for t in overlaps:
                if t not in seen_overlap:
                    unique.append(t)
                    seen_overlap.add(t)

            overlap_str = ", ".join([f"{e} ({a} vs {b})" for e, a, b in unique])
            print(
                f"[WARN] Electrode(s) listed in multiple ROIs: {overlap_str}. "
                f'Using ROI_OVERLAP_POLICY="{overlap_policy}".'
            )

    return electrode_to_roi, roi_to_electrodes_assigned


def add_roi_legend(
    ax: plt.Axes,
    roi_definitions: Dict[str, Dict[str, Any]],
    roi_to_electrodes_assigned: Dict[str, List[str]],
) -> Optional[mpl.legend.Legend]:
    """
    Add a legend mapping ROI names -> colors.

    The legend entries are created dynamically from ROI_DEFINITIONS.
    ROIs with zero assigned electrodes are omitted.
    """
    handles: List[Patch] = []
    labels: List[str] = []

    for roi_name, spec in roi_definitions.items():
        assigned = roi_to_electrodes_assigned.get(roi_name, [])
        if not assigned:
            continue

        color = spec.get("color", "black")
        handles.append(Patch(facecolor=color, edgecolor="none"))

        if LEGEND_INCLUDE_COUNTS:
            labels.append(f"{roi_name} (n={len(assigned)})")
        else:
            labels.append(roi_name)

    if not handles:
        return None

    legend = ax.legend(
        handles=handles,
        labels=labels,
        title=LEGEND_TITLE,
        loc=LEGEND_LOC,
        bbox_to_anchor=LEGEND_BBOX_TO_ANCHOR,
        frameon=LEGEND_FRAMEON,
        fontsize=LEGEND_FONT_SIZE,
        title_fontsize=LEGEND_TITLE_FONT_SIZE,
        borderaxespad=0.0,
        handlelength=1.0,
        handleheight=1.0,
    )
    return legend


def open_file(path: str) -> None:
    """Open a file in the system default viewer."""
    if not AUTO_OPEN_SVG:
        return

    try:
        if sys.platform.startswith("win"):
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.run(["open", path], check=False)
        else:
            subprocess.run(["xdg-open", path], check=False)
    except Exception as exc:
        print(f"[WARN] Could not auto-open SVG: {exc}")


def main() -> None:
    # Keep SVG text as editable text (not converted to paths)
    mpl.rcParams["svg.fonttype"] = "none"
    mpl.rcParams["font.family"] = FONT_FAMILY

    out_dir = Path(OUTPUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)

    out_svg = out_dir / OUTPUT_FILENAME
    if out_svg.suffix.lower() != ".svg":
        out_svg = out_svg.with_suffix(".svg")

    coords = build_label_positions(scale=LABEL_SCALE)

    electrode_to_roi, roi_to_electrodes_assigned = build_roi_assignment(
        ROI_DEFINITIONS,
        coords.keys(),
        overlap_policy=ROI_OVERLAP_POLICY,
        verbose=ROI_VERBOSE_WARNINGS,
    )

    fig, ax = plt.subplots(figsize=FIGSIZE_INCHES)
    ax.set_aspect("equal")
    ax.axis("off")

    ear_w, nose_h = draw_head_outline(ax)

    # Draw electrode labels, coloring by ROI when applicable
    for name, (x, y) in coords.items():
        roi_name = electrode_to_roi.get(name)
        if roi_name is None:
            color = DEFAULT_LABEL_COLOR
        else:
            color = ROI_DEFINITIONS.get(roi_name, {}).get("color", DEFAULT_LABEL_COLOR)

        ax.text(
            x,
            y,
            name,
            ha="center",
            va="center",
            fontsize=FONT_SIZE,
            family=FONT_FAMILY,
            color=color,
        )

    legend = None
    if SHOW_ROI_LEGEND:
        legend = add_roi_legend(ax, ROI_DEFINITIONS, roi_to_electrodes_assigned)

    # Limits with padding (prevents clipping and keeps it looking centered)
    pad = 0.22
    r = HEAD_RADIUS
    ax.set_xlim(-(r + ear_w + pad), (r + ear_w + pad))
    ax.set_ylim(-(r + pad), (r + nose_h + pad))

    # Ensure the legend is included in the "tight" bounding box if it sits outside the axes.
    savefig_kwargs: Dict[str, Any] = dict(
        format="svg",
        bbox_inches="tight",
        pad_inches=0.05,
        transparent=TRANSPARENT_BG,
    )
    if legend is not None:
        savefig_kwargs["bbox_extra_artists"] = (legend,)

    fig.savefig(str(out_svg), **savefig_kwargs)
    plt.close(fig)

    print(f"Saved SVG: {out_svg}")
    open_file(str(out_svg))


if __name__ == "__main__":
    main()