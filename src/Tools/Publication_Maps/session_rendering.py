"""Render canonical group-column × session-row publication scalp maps."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

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
from Tools.Publication_Maps.session_controls import FIXED_ORDER_CAVEAT
from Tools.Publication_Maps.session_panels import (
    PairedSessionDifferenceMap,
    SessionMapPanel,
    SessionMapPanelSet,
)
from Tools.Publication_Maps.session_workflow import (
    build_session_panel_sets,
    validate_session_grid_requests,
)


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
        figsize=(6.5, 8.0 if include_difference else 5.8),
        dpi=request.png_dpi,
    )
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
                ax.set_title(
                    f"{panel.group_label}\n{panel.session_label} "
                    f"(Visit {panel.visit_index}, n={panel.participant_n})",
                    pad=7,
                    **figure_text_kwargs("condition_label"),
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
                ax.set_title(
                    f"{difference.group_label}\n"
                    f"{difference.comparison_session_label} − "
                    f"{difference.reference_session_label} "
                    f"(paired n={difference.paired_n})",
                    pad=7,
                    **figure_text_kwargs("condition_label"),
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
            y=0.985,
            **figure_text_kwargs("panel_label"),
        )
        fig.text(
            0.5,
            0.012,
            FIXED_ORDER_CAVEAT,
            ha="center",
            va="bottom",
            wrap=True,
            **figure_text_kwargs("small"),
        )
        fig.subplots_adjust(
            left=0.04,
            right=0.87,
            bottom=0.07,
            top=0.91,
            hspace=0.42,
            wspace=0.18,
        )
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
