"""Descriptive harmonic scalp maps with discrete, existing FHC memberships.

The color surface uses piecewise-linear interpolation of the inference-ready
mean contrast, restricted to the measured-sensor convex hull and head outline.
It cannot overshoot the sensor values and does not interpolate significance.
ROI-selector coordinates are presentation geometry, never the inference graph.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from math import ceil
from pathlib import Path
import textwrap

from matplotlib import colormaps, rc_context
from matplotlib.axes import Axes
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.cm import ScalarMappable
from matplotlib.colors import Normalize
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import Circle, PathPatch
from matplotlib.path import Path as ArtistPath
from matplotlib.tri import LinearTriInterpolator, Triangulation
import numpy as np

from Main_App.exports.figure_style import (
    FIGURE_EXPORT_DPI,
    FIGURE_OUTPUT_FORMATS,
    apply_axis_text_style,
    figure_legend_kwargs,
    figure_text_kwargs,
    matplotlib_figure_rcparams,
)
from Main_App.gui.roi_electrode_selector_state import (
    BIOSEMI64_POLAR_COORDINATES,
    electrode_logical_position,
)
from Tools.Free_Harmonic_Clustering.models import FreeHarmonicCancelledError
from Tools.Free_Harmonic_Clustering.visualization import ClusterMapData


PAPER_DOI = "https://doi.org/10.1111/psyp.70361"
HARMONICS_PER_PAGE = 12
_GRID_SIZE = 257


def sensor_positions(sensor_names: Sequence[str]) -> np.ndarray:
    """Return ROI-map positions in sensor order, with anterior at positive y."""

    catalog = {
        label.casefold(): electrode_logical_position(theta, phi)
        for label, theta, phi in BIOSEMI64_POLAR_COORDINATES
    }
    positions = []
    for label in sensor_names:
        key = str(label).strip().casefold()
        if key not in catalog:
            raise ValueError(f"No BioSemi64 map position for sensor {label!r}.")
        x, y = catalog[key]
        positions.append(((x - 320.0) / 195.0, (300.0 - y) / 195.0))
    return np.asarray(positions, dtype=np.float64)


def _descriptive_surface(positions: np.ndarray, values: np.ndarray) -> np.ma.MaskedArray:
    """Interpolate scalar values linearly, without extrapolation or overshoot."""

    if len(positions) < 3 or np.linalg.matrix_rank(positions - positions.mean(axis=0)) < 2:
        raise ValueError("A scalp surface requires at least three non-collinear sensors.")
    coordinates = np.linspace(-1.0, 1.0, _GRID_SIZE)
    x_grid, y_grid = np.meshgrid(coordinates, coordinates)
    triangles = Triangulation(positions[:, 0], positions[:, 1])
    field = LinearTriInterpolator(triangles, values)(x_grid, y_grid)
    field = np.ma.masked_where(x_grid * x_grid + y_grid * y_grid > 1.0, field)
    # Linear interpolation is bounded analytically; clipping removes only
    # floating-point roundoff at the extrema and is not a statistical mask.
    return np.ma.clip(field, float(np.min(values)), float(np.max(values)))


def _draw_head(ax: Axes) -> None:
    ax.add_patch(Circle((0.0, 0.0), 1.0, fill=False, edgecolor="#333333", linewidth=0.8))
    outline = ArtistPath(
        [
            (-31 / 195, 192 / 195), (0, 223 / 195), (31 / 195, 192 / 195),
            (-197 / 195, 38 / 195), (-228 / 195, 33 / 195),
            (-229 / 195, -33 / 195), (-197 / 195, -38 / 195),
            (197 / 195, 38 / 195), (228 / 195, 33 / 195),
            (229 / 195, -33 / 195), (197 / 195, -38 / 195),
        ],
        [
            ArtistPath.MOVETO, ArtistPath.LINETO, ArtistPath.LINETO,
            ArtistPath.MOVETO, ArtistPath.CURVE4, ArtistPath.CURVE4, ArtistPath.CURVE4,
            ArtistPath.MOVETO, ArtistPath.CURVE4, ArtistPath.CURVE4, ArtistPath.CURVE4,
        ],
    )
    ax.add_patch(PathPatch(outline, fill=False, edgecolor="#333333", linewidth=0.8))


def draw_harmonic_map(
    ax: Axes,
    data: ClusterMapData,
    harmonic_index: int,
    *,
    cluster_id: int | None = None,
    show_sensor_names: bool = False,
) -> ScalarMappable:
    """Draw one exact harmonic slice; cluster filtering affects dots only.

    Black dots mark positive significant-cluster members and white dots with
    black edges mark negative members. Untested pointwise claims are never
    generated. The full-run color scale survives harmonic or cluster changes.
    """

    if isinstance(harmonic_index, bool) or not 0 <= harmonic_index < len(data.harmonic_orders):
        raise ValueError("harmonic_index is outside the retained harmonic domain.")
    significant_ids = {cluster.cluster_id for cluster in data.clusters if cluster.significant}
    if cluster_id is not None and cluster_id not in significant_ids:
        raise ValueError("cluster_id must identify an existing significant cluster.")
    positions = sensor_positions(data.sensor_names)
    values = np.asarray(data.mean_difference[:, harmonic_index], dtype=np.float64)
    field = _descriptive_surface(positions, values)
    ax.clear()
    image = ax.imshow(
        field,
        origin="lower",
        extent=(-1.0, 1.0, -1.0, 1.0),
        interpolation="nearest",
        cmap=colormaps["RdBu_r"],
        norm=Normalize(vmin=-data.color_limit, vmax=data.color_limit),
        zorder=0,
    )
    image.set_gid("fhc-response-surface")
    ax.scatter(
        positions[:, 0], positions[:, 1], s=3, c="#737373", linewidths=0,
        zorder=2, gid="fhc-sensors",
    )
    labels = np.asarray(data.cluster_labels[:, harmonic_index])
    for sign, face, suffix in ((1, "black", "positive"), (-1, "white", "negative")):
        ids = {value for value in significant_ids if (value > 0) == (sign > 0)}
        if cluster_id is not None:
            ids.intersection_update((cluster_id,))
        selected = np.isin(labels, tuple(ids))
        ax.scatter(
            positions[selected, 0], positions[selected, 1], s=19,
            facecolors=face, edgecolors="black", linewidths=0.65,
            zorder=3, gid=f"fhc-cluster-{suffix}",
        )
    if show_sensor_names:
        for label, (x, y) in zip(data.sensor_names, positions, strict=True):
            ax.annotate(
                label, (x, y), xytext=(0, 4), textcoords="offset points",
                ha="center", va="bottom", zorder=4, **figure_text_kwargs("small"),
            )
    _draw_head(ax)
    ax.set_title(
        f"H{data.harmonic_orders[harmonic_index]} · {data.harmonics_hz[harmonic_index]:g} Hz",
        pad=3, **figure_text_kwargs("condition_label"),
    )
    ax.set_xlim(-1.35, 1.35)
    ax.set_ylim(-1.40, 1.26)
    ax.set_aspect("equal")
    ax.set_axis_off()
    return image


def cluster_map_caption(data: ClusterMapData) -> str:
    """Return the complete interpretation for metadata and external captions."""

    zero_note = (
        " Every displayed difference is zero; the symmetric ±1 color limits are "
        "a display fallback and the colorbar marks only zero."
        if not np.any(data.mean_difference) else ""
    )
    return (
        f"{data.run_label}. A = {data.arm_a_label}; B = {data.arm_b_label}. "
        f"Color: {data.value_label}. At each electrode and retained harmonic, "
        "the displayed value is mean(A) − mean(B) from the exact inference-ready "
        "participant tensors, including the run's defined normalized-response "
        "or repeated-session composite semantics. The surface is descriptive "
        "piecewise-linear interpolation of these values, bounded by the sensor "
        "convex hull and scalp outline, without extrapolation or overshoot. "
        "One symmetric diverging scale covers every retained harmonic in the run, "
        "including harmonics on other pages. Black dots show electrodes belonging "
        "to positive significant clusters at this exact harmonic; white dots with "
        "black edges show negative significant-cluster membership. Dots show "
        "existing cluster membership, not independently significant electrodes or "
        "harmonics. Cluster-level inference concerns the whole connected "
        "sensor × harmonic cluster; spatially separated regions in one slice "
        "may connect through other harmonics. Colors are never masked by "
        "significance and p-values are not interpolated. "
        f"{data.multiplicity_note} "
        "Nose is anterior/up; left on the map is participant left. BioSemi64 "
        "positions reuse the Toolbox ROI-selector geometry, independently of "
        "the fixed FHC inference adjacency. Presentation follows the difference "
        "maps and signed membership markers in Hermann, Ching and Stothart "
        f"(2026), Figures 7 and 10 ({PAPER_DOI}); the layout and linear "
        "interpolation are Toolbox choices, not a reproduction of the authors' "
        "MATLAB renderer or layout." + zero_note
    )


def create_harmonic_figure(
    data: ClusterMapData,
    *,
    harmonic_indices: Sequence[int] | None = None,
    cluster_id: int | None = None,
    columns: int = 4,
) -> Figure:
    """Create a publication figure; supplied harmonic order is preserved."""

    indices = tuple(range(len(data.harmonic_orders))) if harmonic_indices is None else tuple(harmonic_indices)
    if not indices or len(set(indices)) != len(indices):
        raise ValueError("Choose at least one harmonic, without duplicate indices.")
    if isinstance(columns, bool) or not isinstance(columns, int) or columns < 1:
        raise ValueError("columns must be a positive integer.")
    columns = min(columns, len(indices))
    rows = ceil(len(indices) / columns)
    width = max(3.4, 2.0 * columns)
    wrap_width = max(24, int(width * 10))
    header = "\n".join(
        textwrap.fill(text, width=wrap_width)
        for text in (data.run_label, f"A: {data.arm_a_label}; B: {data.arm_b_label}")
        if text.strip()
    )
    color_label = textwrap.fill(f"{data.value_label} (A − B)", width=wrap_width) + "\n(dimensionless)"
    top_margin = 0.46 + 0.17 * len(header.splitlines())
    bottom_margin = 1.15 + 0.15 * (len(color_label.splitlines()) - 1) + (0.18 if columns == 1 else 0)
    height = 2.0 * rows + top_margin + bottom_margin
    figure = Figure(figsize=(width, height), facecolor="white")
    FigureCanvasAgg(figure)
    figure.text(
        0.5, 1.0 - 0.10 / height, header, ha="center", va="top",
        linespacing=1.2, **figure_text_kwargs("condition_label"),
    )
    grid = figure.add_gridspec(
        rows, columns, left=0.025, right=0.975,
        bottom=bottom_margin / height, top=1.0 - top_margin / height, wspace=0.04, hspace=0.20,
    )
    mappable = None
    for position, harmonic_index in enumerate(indices):
        ax = figure.add_subplot(grid[position // columns, position % columns])
        mappable = draw_harmonic_map(ax, data, harmonic_index, cluster_id=cluster_id)
    color_ax = figure.add_axes((0.22, (bottom_margin - 0.35) / height, 0.56, 0.12 / height))
    ticks = (-data.color_limit, 0.0, data.color_limit) if np.any(data.mean_difference) else (0.0,)
    colorbar = figure.colorbar(mappable, cax=color_ax, orientation="horizontal", ticks=ticks)
    colorbar.set_label(color_label, labelpad=3, **figure_text_kwargs("axis_label"))
    colorbar.ax.xaxis.set_major_formatter("{x:.3g}")
    apply_axis_text_style(colorbar.ax)
    legend_handles = [
        Line2D([], [], marker="o", linestyle="none", markersize=4.5,
               markerfacecolor=face, markeredgecolor="black", label=f"{sign} cluster")
        for sign, face in (("Positive", "black"), ("Negative", "white"))
    ]
    figure.legend(
        handles=legend_handles, loc="lower center", bbox_to_anchor=(0.5, 0.11 / height),
        ncol=2 if columns > 1 else 1, frameon=False, handletextpad=0.45,
        columnspacing=1.5, **figure_legend_kwargs(),
    )
    return figure


def export_cluster_map_figures(
    data: ClusterMapData,
    output_dir: Path,
    *,
    cancel_check: Callable[[], bool] | None = None,
) -> tuple[Path, ...]:
    """Write paired 600-dpi PNG/single-page PDF files into a staged directory.

    The calling exporter owns transaction publication and removal on failure.
    Captions stay outside the artwork, in file metadata and the run sidecar.
    """

    def check_cancelled() -> None:
        if cancel_check is not None and cancel_check():
            raise FreeHarmonicCancelledError("Cluster-map figure export cancelled.")

    check_cancelled()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    written = []
    caption = cluster_map_caption(data)
    for start in range(0, len(data.harmonic_orders), HARMONICS_PER_PAGE):
        check_cancelled()
        page = start // HARMONICS_PER_PAGE + 1
        indices = range(start, min(start + HARMONICS_PER_PAGE, len(data.harmonic_orders)))
        figure = create_harmonic_figure(data, harmonic_indices=indices)
        try:
            for suffix in FIGURE_OUTPUT_FORMATS:
                check_cancelled()
                path = output_dir / f"FHC_Harmonic_Cluster_Maps_{page:02d}.{suffix}"
                if path.exists():
                    raise FileExistsError(f"Cluster-map figure already exists: {path}")
                metadata = (
                    {"Title": data.run_label, "Subject": caption, "Keywords": PAPER_DOI}
                    if suffix == "pdf" else
                    {"Title": data.run_label, "Description": caption, "Software": "FPVS Toolbox"}
                )
                with rc_context(matplotlib_figure_rcparams()):
                    figure.savefig(path, format=suffix, dpi=FIGURE_EXPORT_DPI, metadata=metadata)
                written.append(path)
        finally:
            figure.clear()
    check_cancelled()
    return tuple(written)


__all__ = [
    "cluster_map_caption",
    "create_harmonic_figure",
    "draw_harmonic_map",
    "export_cluster_map_figures",
    "sensor_positions",
]
