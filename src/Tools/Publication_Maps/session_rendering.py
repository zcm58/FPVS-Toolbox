"""Render canonical group-column × session-row publication scalp maps."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from matplotlib.lines import Line2D
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
    two_row_height_in: float = 6.5
    three_row_height_in: float = 9.0
    left: float = 0.04
    right: float = 0.87
    bottom: float = 0.035
    two_row_top: float = 0.78
    three_row_top: float = 0.82
    two_row_hspace: float = 0.50
    three_row_hspace: float = 0.65
    wspace: float = 0.18
    suptitle_y: float = 0.985
    column_header_y: float = 0.92
    column_text_padding: float = 0.012
    panel_title_pad: float = 7.0
    divider_color: str = "#B3B3B3"
    divider_linewidth: float = 0.8
    divider_gid: str = "repeated-session-group-divider"
    column_header_gid_prefix: str = "repeated-session-group-header"

    def figsize(self, *, include_difference: bool) -> tuple[float, float]:
        height = (
            self.three_row_height_in
            if include_difference
            else self.two_row_height_in
        )
        return self.width_in, height

    def top(self, *, include_difference: bool) -> float:
        return self.three_row_top if include_difference else self.two_row_top

    def hspace(self, *, include_difference: bool) -> float:
        return (
            self.three_row_hspace
            if include_difference
            else self.two_row_hspace
        )


REPEATED_SESSION_LAYOUT = _RepeatedSessionLayoutProfile()


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


def _column_text_width_pixels(fig, axes, column: int, divider_x: float) -> float:
    center = sum(
        axes[row, column].get_position().x0
        + axes[row, column].get_position().x1
        for row in range(axes.shape[0])
    ) / (2.0 * axes.shape[0])
    outer_left = REPEATED_SESSION_LAYOUT.left if column == 0 else divider_x
    outer_right = divider_x if column == 0 else REPEATED_SESSION_LAYOUT.right
    half_width = min(center - outer_left, outer_right - center)
    half_width -= REPEATED_SESSION_LAYOUT.column_text_padding
    return max(1.0, 2.0 * half_width * fig.bbox.width)


def _apply_repeated_session_titles(
    fig,
    axes,
    panel_set: SessionMapPanelSet,
    panel_title_sections: dict[object, tuple[str, ...]],
) -> None:
    """Apply wrapped matrix headers and session-specific panel titles."""

    divider_x = _group_column_divider_x(axes)
    title_kwargs = figure_text_kwargs("condition_label")
    header_kwargs = dict(title_kwargs)
    header_kwargs["fontweight"] = "bold"
    suptitle = fig._suptitle
    if suptitle is not None:
        suptitle.set_text(
            _wrap_text_to_width(
                fig,
                suptitle.get_text(),
                max_width_pixels=(1.0 - 2.0 * REPEATED_SESSION_LAYOUT.left)
                * fig.bbox.width,
                text_kwargs=figure_text_kwargs("panel_label"),
            )
        )

    for column, group_id in enumerate(panel_set.group_ids):
        max_width_pixels = _column_text_width_pixels(
            fig,
            axes,
            column,
            divider_x,
        )
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
                group_label,
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
        for ax in axes[:, column]:
            wrapped_sections = tuple(
                _wrap_text_to_width(
                    fig,
                    section,
                    max_width_pixels=max_width_pixels,
                    text_kwargs=title_kwargs,
                )
                for section in panel_title_sections[ax]
            )
            ax.set_title(
                "\n".join(wrapped_sections),
                pad=REPEATED_SESSION_LAYOUT.panel_title_pad,
                **title_kwargs,
            )


def _add_group_column_divider(fig, axes) -> None:
    """Add one neutral divider centered in the rendered group-column gutter."""

    divider_x = _group_column_divider_x(axes)
    grid_bottom = min(ax.get_position().y0 for ax in axes.flat)
    grid_top = max(ax.get_position().y1 for ax in axes.flat)
    divider = Line2D(
        (divider_x, divider_x),
        (grid_bottom, grid_top),
        transform=fig.transFigure,
        color=REPEATED_SESSION_LAYOUT.divider_color,
        linewidth=REPEATED_SESSION_LAYOUT.divider_linewidth,
        solid_capstyle="butt",
        clip_on=False,
    )
    divider.set_gid(REPEATED_SESSION_LAYOUT.divider_gid)
    fig.add_artist(divider)


def _render_session_panel_set(
    panel_set: SessionMapPanelSet,
    request: PublicationMapRequest,
    *,
    output_path: Path,
    cancel_check: Callable[[], None] | None,
) -> None:
    if cancel_check is not None:
        cancel_check()
    include_difference = request.export_paired_session_difference
    row_count = 3 if include_difference else 2
    fig, axes = plt.subplots(
        row_count,
        2,
        squeeze=False,
        figsize=REPEATED_SESSION_LAYOUT.figsize(
            include_difference=include_difference
        ),
        dpi=request.png_dpi,
    )
    metric = panel_set.metric
    bounds = request.color_bounds.get(metric, ColorBounds())
    cmap = colormap_for_metric(metric, bounds)
    main_vlim = _main_vlim(panel_set, bounds)
    main_images = []
    panel_title_sections: dict[object, tuple[str, ...]] = {}
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
                panel_title_sections[ax] = (
                    panel.session_label,
                    f"(Visit {panel.visit_index}, n={panel.participant_n})",
                )
                if missing:
                    _add_missing_note(ax, missing)
        main_cbar = fig.colorbar(
            main_images[0],
            ax=list(axes[:2, :].flat),
            fraction=0.025,
            pad=0.025,
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
                panel_title_sections[ax] = (
                    f"{difference.comparison_session_label} − "
                    f"{difference.reference_session_label}",
                    f"(paired n={difference.paired_n})",
                )
                if missing:
                    _add_missing_note(ax, missing)
            difference_cbar = fig.colorbar(
                difference_images[0],
                ax=list(axes[2, :].flat),
                fraction=0.025,
                pad=0.025,
            )
            difference_label_kwargs = figure_text_kwargs("axis_label")
            difference_label_kwargs["fontweight"] = "bold"
            difference_cbar.ax.set_ylabel(
                f"{metric.display_name}: comparison − reference",
                **difference_label_kwargs,
            )
            apply_axis_text_style(difference_cbar.ax)

        fig.suptitle(
            f"{panel_set.condition} — {metric.display_name}",
            y=REPEATED_SESSION_LAYOUT.suptitle_y,
            **figure_text_kwargs("panel_label"),
        )
        fig.subplots_adjust(
            left=REPEATED_SESSION_LAYOUT.left,
            right=REPEATED_SESSION_LAYOUT.right,
            bottom=REPEATED_SESSION_LAYOUT.bottom,
            top=REPEATED_SESSION_LAYOUT.top(
                include_difference=include_difference
            ),
            hspace=REPEATED_SESSION_LAYOUT.hspace(
                include_difference=include_difference
            ),
            wspace=REPEATED_SESSION_LAYOUT.wspace,
        )
        _apply_repeated_session_titles(
            fig,
            axes,
            panel_set,
            panel_title_sections,
        )
        _add_group_column_divider(fig, axes)
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
    """Render one shared-limit 2×2 grid per condition and requested metric."""

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
            for suffix, enabled in (
                (".png", request.export_png),
                (".pdf", request.export_pdf),
            ):
                if not enabled:
                    continue
                if cancel_check is not None:
                    cancel_check()
                final_path = base_output / f"{stem}{suffix}"
                staged_path = active_transaction.stage_path(final_path)
                _render_session_panel_set(
                    panel_set,
                    request,
                    output_path=staged_path,
                    cancel_check=cancel_check,
                )
                rendered.append(final_path)
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
