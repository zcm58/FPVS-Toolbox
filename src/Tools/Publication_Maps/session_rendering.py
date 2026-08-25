"""Render canonical group-column × session-row publication scalp maps."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle
import numpy as np
import pandas as pd

from Main_App.exports.figure_style import apply_axis_text_style, figure_text_kwargs
from Tools.Publication_Maps.models import (
    ColorBounds,
    PublicationMapInputError,
    PublicationMapRequest,
)
from Tools.Publication_Maps.output_contract import PublicationArtifactTransaction
from Tools.Publication_Maps.rendering import (
    _add_missing_note,
    _draw_topomap,
    _save_figure,
    _style_colorbar,
    colormap_for_metric,
    plt,
    sanitize_filename_stem,
)
from Tools.Publication_Maps.session_panels import (
    PairedSessionDifferenceMap,
    SessionMapPanel,
    SessionMapPanelSet,
)
from Tools.Publication_Maps.session_workflow import (
    build_session_panel_sets,
    validate_session_grid_requests,
)


@dataclass(frozen=True)
class _RepeatedSessionLayoutProfile:
    """Figure geometry owned only by the repeated-session renderer."""

    width_in: float = 6.5
    two_row_height_in: float = 4.2
    three_row_height_in: float = 5.9
    left: float = 0.025
    right: float = 0.86
    bottom: float = 0.025
    top: float = 0.89
    hspace: float = 0.08
    wspace: float = 0.08
    width_ratios: tuple[float, float, float, float] = (0.20, 1.0, 1.0, 0.065)
    column_header_y: float = 0.945
    paired_colorbar_gap: float = 0.02
    divider_color: str = "#B3B3B3"
    divider_linewidth: float = 0.8
    divider_gid: str = "repeated-session-group-divider"
    grid_frame_gid: str = "repeated-session-grid-frame"
    row_divider_gid_prefix: str = "repeated-session-row-divider"
    column_header_gid_prefix: str = "repeated-session-group-header"
    row_label_gid_prefix: str = "repeated-session-row-label"
    map_axis_gid_prefix: str = "repeated-session-map"
    colorbar_axis_gid_prefix: str = "repeated-session-colorbar"

    def figsize(self, *, include_difference: bool) -> tuple[float, float]:
        height = (
            self.three_row_height_in
            if include_difference
            else self.two_row_height_in
        )
        return self.width_in, height

REPEATED_SESSION_LAYOUT = _RepeatedSessionLayoutProfile()


@dataclass(frozen=True, slots=True)
class _MapGridGeometry:
    """Fixed frame boundaries retained while map axes are centered within cells."""

    left: float
    right: float
    bottom: float
    top: float
    column_divider: float
    row_dividers: tuple[float, ...]


def _panel_frame(panel: SessionMapPanel) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "electrode": value.electrode,
                "render_value": value.render_value,
                "is_montage_electrode": value.is_montage_electrode,
            }
            for value in panel.values
        ]
    )


def _difference_frame(panel: PairedSessionDifferenceMap) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "electrode": value.electrode,
                "render_value": value.aggregate_difference,
                "is_montage_electrode": value.is_montage_electrode,
            }
            for value in panel.values
        ]
    )


def _main_vlim(
    panel_set: SessionMapPanelSet,
    bounds: ColorBounds,
) -> tuple[float, float]:
    if not bounds.auto_scale and bounds.vmin is not None and bounds.vmax is not None:
        return float(bounds.vmin), float(bounds.vmax)
    return panel_set.common_vmin, panel_set.common_vmax


def _group_column_divider_x(axes) -> float:
    left_column_right = max(ax.get_position().x1 for ax in axes[:, 0])
    right_column_left = min(ax.get_position().x0 for ax in axes[:, 1])
    return (left_column_right + right_column_left) / 2.0


def _wrap_text_to_width(
    fig,
    value: str,
    *,
    max_width_pixels: float,
    text_kwargs: dict[str, object],
) -> str:
    """Wrap complete labels using their rendered width without truncation."""

    renderer = fig.canvas.get_renderer()
    probe = fig.text(0.0, 0.0, "", ha="left", va="bottom", **text_kwargs)

    def fits(candidate: str) -> bool:
        probe.set_text(candidate)
        return probe.get_window_extent(renderer).width <= max_width_pixels

    def split_token(token: str) -> list[str]:
        chunks: list[str] = []
        current = ""
        for character in token:
            candidate = f"{current}{character}"
            if current and not fits(candidate):
                chunks.append(current)
                current = character
            else:
                current = candidate
        if current:
            chunks.append(current)
        return chunks or [token]

    try:
        lines: list[str] = []
        for paragraph in str(value).splitlines() or [""]:
            words = paragraph.split()
            if not words:
                lines.append("")
                continue
            current = ""
            for word in words:
                candidate = f"{current} {word}".strip()
                if current and fits(candidate):
                    current = candidate
                    continue
                if current:
                    lines.append(current)
                chunks = split_token(word)
                lines.extend(chunks[:-1])
                current = chunks[-1]
            if current:
                lines.append(current)
        return "\n".join(lines)
    finally:
        probe.remove()


def _column_text_width_pixels(fig, axes, column: int) -> float:
    return max(
        1.0,
        min(ax.get_position().width for ax in axes[:, column]) * fig.bbox.width,
    )


def _apply_repeated_session_labels(
    fig,
    axes,
    row_label_axes,
    panel_set: SessionMapPanelSet,
) -> None:
    """Apply agnostic group headers and one external label per matrix row."""

    header_kwargs = figure_text_kwargs("panel_label")
    for column, group_id in enumerate(panel_set.group_ids):
        max_width_pixels = _column_text_width_pixels(fig, axes, column)
        column_center = (
            axes[0, column].get_position().x0
            + axes[0, column].get_position().x1
        ) / 2.0
        group_label = panel_set.panel(group_id, panel_set.session_ids[0]).group_label
        header = fig.text(
            column_center,
            REPEATED_SESSION_LAYOUT.column_header_y,
            _wrap_text_to_width(
                fig,
                f"({chr(ord('A') + column)}) {group_label}",
                max_width_pixels=max_width_pixels,
                text_kwargs=header_kwargs,
            ),
            ha="center",
            va="center",
            **header_kwargs,
        )
        header.set_gid(
            f"{REPEATED_SESSION_LAYOUT.column_header_gid_prefix}-{column}"
        )

    row_labels = [
        panel_set.panel(panel_set.group_ids[0], session_id).session_label
        for session_id in panel_set.session_ids
    ]
    if len(row_label_axes) > len(row_labels):
        difference = panel_set.paired_difference(panel_set.group_ids[0])
        row_labels.append(
            f"{difference.comparison_session_label} − "
            f"{difference.reference_session_label}"
        )

    label_kwargs = figure_text_kwargs("condition_label")
    for row, (label_ax, label) in enumerate(zip(row_label_axes, row_labels, strict=True)):
        max_height_pixels = label_ax.get_position().height * fig.bbox.height
        text = label_ax.text(
            0.5,
            0.5,
            _wrap_text_to_width(
                fig,
                label,
                max_width_pixels=max_height_pixels,
                text_kwargs=label_kwargs,
            ),
            ha="center",
            va="center",
            rotation=90,
            **label_kwargs,
        )
        text.set_gid(
            f"{REPEATED_SESSION_LAYOUT.row_label_gid_prefix}-{row}"
        )


def _center_map_axes_in_grid_cells(axes, row_label_axes) -> _MapGridGeometry:
    """Center every map and row label within the existing framed matrix cells."""

    grid_left = min(ax.get_position().x0 for ax in axes.flat)
    grid_right = max(ax.get_position().x1 for ax in axes.flat)
    grid_bottom = min(ax.get_position().y0 for ax in axes.flat)
    grid_top = max(ax.get_position().y1 for ax in axes.flat)
    column_divider = _group_column_divider_x(axes)
    row_dividers = tuple(
        (
            min(ax.get_position().y0 for ax in axes[row, :])
            + max(ax.get_position().y1 for ax in axes[row + 1, :])
        )
        / 2.0
        for row in range(len(axes) - 1)
    )
    geometry = _MapGridGeometry(
        left=grid_left,
        right=grid_right,
        bottom=grid_bottom,
        top=grid_top,
        column_divider=column_divider,
        row_dividers=row_dividers,
    )

    column_bounds = (
        (geometry.left, geometry.column_divider),
        (geometry.column_divider, geometry.right),
    )
    row_bounds = (
        geometry.top,
        *geometry.row_dividers,
        geometry.bottom,
    )
    for row in range(len(axes)):
        target_y = (row_bounds[row] + row_bounds[row + 1]) / 2.0
        for column in range(axes.shape[1]):
            position = axes[row, column].get_position()
            target_x = sum(column_bounds[column]) / 2.0
            axes[row, column].set_position(
                (
                    position.x0 + target_x - (position.x0 + position.x1) / 2.0,
                    position.y0 + target_y - (position.y0 + position.y1) / 2.0,
                    position.width,
                    position.height,
                )
            )

        label_position = row_label_axes[row].get_position()
        row_label_axes[row].set_position(
            (
                label_position.x0,
                label_position.y0
                + target_y
                - (label_position.y0 + label_position.y1) / 2.0,
                label_position.width,
                label_position.height,
            )
        )
    return geometry


def _add_map_grid_frame(fig, geometry: _MapGridGeometry) -> None:
    """Box the map matrix and separate its group columns and session rows."""

    frame = Rectangle(
        (geometry.left, geometry.bottom),
        geometry.right - geometry.left,
        geometry.top - geometry.bottom,
        transform=fig.transFigure,
        fill=False,
        edgecolor=REPEATED_SESSION_LAYOUT.divider_color,
        linewidth=REPEATED_SESSION_LAYOUT.divider_linewidth,
        clip_on=False,
    )
    frame.set_gid(REPEATED_SESSION_LAYOUT.grid_frame_gid)
    fig.add_artist(frame)

    divider = Line2D(
        (geometry.column_divider, geometry.column_divider),
        (geometry.bottom, geometry.top),
        transform=fig.transFigure,
        color=REPEATED_SESSION_LAYOUT.divider_color,
        linewidth=REPEATED_SESSION_LAYOUT.divider_linewidth,
        solid_capstyle="butt",
        clip_on=False,
    )
    divider.set_gid(REPEATED_SESSION_LAYOUT.divider_gid)
    fig.add_artist(divider)

    for row, divider_y in enumerate(geometry.row_dividers):
        row_divider = Line2D(
            (geometry.left, geometry.right),
            (divider_y, divider_y),
            transform=fig.transFigure,
            color=REPEATED_SESSION_LAYOUT.divider_color,
            linewidth=REPEATED_SESSION_LAYOUT.divider_linewidth,
            solid_capstyle="butt",
            clip_on=False,
        )
        row_divider.set_gid(
            f"{REPEATED_SESSION_LAYOUT.row_divider_gid_prefix}-{row}"
        )
        fig.add_artist(row_divider)


def _render_session_panel_set(
    panel_set: SessionMapPanelSet,
    request: PublicationMapRequest,
    *,
    output_paths: Sequence[Path],
    cancel_check: Callable[[], None] | None,
) -> None:
    if cancel_check is not None:
        cancel_check()
    include_difference = request.export_paired_session_difference
    row_count = 3 if include_difference else 2
    fig = plt.figure(
        figsize=REPEATED_SESSION_LAYOUT.figsize(
            include_difference=include_difference
        ),
        dpi=request.png_dpi,
    )
    grid = fig.add_gridspec(
        row_count * 2,
        4,
        left=REPEATED_SESSION_LAYOUT.left,
        right=REPEATED_SESSION_LAYOUT.right,
        bottom=REPEATED_SESSION_LAYOUT.bottom,
        top=REPEATED_SESSION_LAYOUT.top,
        hspace=REPEATED_SESSION_LAYOUT.hspace,
        wspace=REPEATED_SESSION_LAYOUT.wspace,
        width_ratios=REPEATED_SESSION_LAYOUT.width_ratios,
    )
    axes = []
    row_label_axes = []
    for row in range(row_count):
        row_slice = slice(row * 2, (row + 1) * 2)
        label_ax = fig.add_subplot(grid[row_slice, 0])
        label_ax.set_axis_off()
        row_label_axes.append(label_ax)
        row_axes = []
        for column in range(2):
            ax = fig.add_subplot(grid[row_slice, column + 1])
            ax.set_gid(
                f"{REPEATED_SESSION_LAYOUT.map_axis_gid_prefix}-{row}-{column}"
            )
            row_axes.append(ax)
        axes.append(row_axes)
    axes = np.asarray(axes, dtype=object)
    metric = panel_set.metric
    bounds = request.color_bounds.get(metric, ColorBounds())
    cmap = colormap_for_metric(metric, bounds)
    main_vlim = _main_vlim(panel_set, bounds)
    main_images = []
    try:
        for row, session_id in enumerate(panel_set.session_ids):
            for column, group_id in enumerate(panel_set.group_ids):
                if cancel_check is not None:
                    cancel_check()
                panel = panel_set.panel(group_id, session_id)
                ax = axes[row, column]
                image, missing = _draw_topomap(
                    _panel_frame(panel),
                    ax=ax,
                    metric=metric,
                    cmap=cmap,
                    bounds=bounds,
                    vlim_override=main_vlim,
                )
                main_images.append(image)
                if missing:
                    _add_missing_note(ax, missing)
        main_cbar_ax = fig.add_subplot(grid[:4, 3])
        main_cbar_ax.set_gid(
            f"{REPEATED_SESSION_LAYOUT.colorbar_axis_gid_prefix}-main"
        )
        main_cbar = fig.colorbar(
            main_images[0],
            cax=main_cbar_ax,
        )
        _style_colorbar(main_cbar, metric=metric)

        if include_difference:
            difference_limit = max(
                abs(float(panel_set.difference_vmin or 0.0)),
                abs(float(panel_set.difference_vmax or 0.0)),
            )
            if difference_limit <= 0:
                difference_limit = 1.0
            difference_images = []
            for column, group_id in enumerate(panel_set.group_ids):
                if cancel_check is not None:
                    cancel_check()
                difference = panel_set.paired_difference(group_id)
                ax = axes[2, column]
                image, missing = _draw_topomap(
                    _difference_frame(difference),
                    ax=ax,
                    metric=metric,
                    cmap=plt.get_cmap("RdBu_r"),
                    bounds=ColorBounds(),
                    vlim_override=(-difference_limit, difference_limit),
                )
                difference_images.append(image)
                if missing:
                    _add_missing_note(ax, missing)
            difference_cbar_ax = fig.add_subplot(grid[4:6, 3])
            difference_cbar_ax.set_gid(
                f"{REPEATED_SESSION_LAYOUT.colorbar_axis_gid_prefix}-difference"
            )
            difference_cbar = fig.colorbar(
                difference_images[0],
                cax=difference_cbar_ax,
            )
            difference_label_kwargs = figure_text_kwargs("axis_label")
            difference_label_kwargs["fontweight"] = "bold"
            difference_cbar.ax.set_ylabel(
                f"{metric.display_name}: comparison − reference",
                **difference_label_kwargs,
            )
            apply_axis_text_style(difference_cbar.ax)
            main_position = main_cbar_ax.get_position()
            difference_position = difference_cbar_ax.get_position()
            half_gap = REPEATED_SESSION_LAYOUT.paired_colorbar_gap / 2.0
            main_cbar_ax.set_position(
                (
                    main_position.x0,
                    main_position.y0 + half_gap,
                    main_position.width,
                    main_position.height - half_gap,
                )
            )
            difference_cbar_ax.set_position(
                (
                    difference_position.x0,
                    difference_position.y0,
                    difference_position.width,
                    difference_position.height - half_gap,
                )
            )

        grid_geometry = _center_map_axes_in_grid_cells(axes, row_label_axes)
        _apply_repeated_session_labels(
            fig,
            axes,
            row_label_axes,
            panel_set,
        )
        _add_map_grid_frame(fig, grid_geometry)
        for output_path in output_paths:
            _save_figure(
                fig,
                output_path,
                dpi=request.png_dpi,
                cancel_check=cancel_check,
            )
    finally:
        plt.close(fig)


def render_session_grid_figures(
    results,
    requests: Sequence[PublicationMapRequest],
    *,
    cancel_check: Callable[[], None] | None = None,
    transaction: PublicationArtifactTransaction | None = None,
) -> list[Path]:
    """Render one compact shared-limit session matrix per condition and metric."""

    normalized = tuple(requests)
    validate_session_grid_requests(normalized)
    panel_sets = build_session_panel_sets(
        tuple(results),
        normalized,
        cancel_check=cancel_check,
    )
    owns_transaction = transaction is None
    active_transaction = transaction or PublicationArtifactTransaction(normalized[0])
    rendered: list[Path] = []
    try:
        for request in normalized:
            active_transaction.ensure_request_target(request)
        request = normalized[0]
        base_output = Path(request.output_root).expanduser().resolve(strict=False)
        group_stem = "_and_".join(panel_sets[0].group_ids)
        planned_panels: list[tuple[SessionMapPanelSet, str]] = []
        seen_stems: dict[str, str] = {}
        for panel_set in panel_sets:
            raw_stem = (
                f"{panel_set.condition}_{group_stem}_"
                f"{panel_set.metric.value}_session_grid"
            )
            stem = sanitize_filename_stem(raw_stem)
            prior = seen_stems.get(stem.casefold())
            if prior is not None:
                raise PublicationMapInputError(
                    "Scalp Maps output names collide after Windows-safe filename "
                    f"normalization: {prior!r} and {raw_stem!r}. Rename the "
                    "conditions so each requested figure has a distinct name."
                )
            seen_stems[stem.casefold()] = raw_stem
            planned_panels.append((panel_set, stem))

        for panel_set, stem in planned_panels:
            staged_paths: list[Path] = []
            final_paths: list[Path] = []
            # Keep PNG first: PDF export applies transparent patch styling in place.
            for suffix, enabled in (
                (".png", request.export_png),
                (".pdf", request.export_pdf),
            ):
                if not enabled:
                    continue
                if cancel_check is not None:
                    cancel_check()
                final_path = base_output / f"{stem}{suffix}"
                final_paths.append(final_path)
                staged_paths.append(active_transaction.stage_path(final_path))
            if staged_paths:
                _render_session_panel_set(
                    panel_set,
                    request,
                    output_paths=tuple(staged_paths),
                    cancel_check=cancel_check,
                )
                rendered.extend(final_paths)
        if not rendered:
            raise PublicationMapInputError(
                "No repeated-session scalp-map grids were rendered."
            )
        if owns_transaction:
            active_transaction.commit(cancel_check=cancel_check)
        return rendered
    except Exception:  # Transaction boundary: abort staging for any render/publish failure.
        if owns_transaction:
            active_transaction.abort()
        raise


__all__ = ["render_session_grid_figures"]
