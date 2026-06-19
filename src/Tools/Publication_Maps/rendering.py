"""Rendering and workbook export for publication scalp maps."""

from __future__ import annotations

import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import mne
import numpy as np
import pandas as pd

from Main_App.exports.figure_style import (
    apply_axis_text_style,
    apply_matplotlib_figure_style,
    figure_text_kwargs,
)
from Tools.Publication_Maps.colormaps import scalp_colormap
from Tools.Publication_Maps.models import (
    DIAGNOSTICS_SHEET,
    GRAND_AVERAGE_SHEET,
    LONG_VALUES_SHEET,
    PARAMETERS_SHEET,
    SOURCE_WORKBOOK_NAME,
    ColorBounds,
    DEFAULT_Z_SCORE_THRESHOLD,
    Diagnostic,
    PublicationMapRequest,
    PublicationMapResult,
    PublicationMetric,
)
from Tools.Publication_Maps.scalp_io import align_render_values

apply_matplotlib_figure_style()

BCA_CMAP = scalp_colormap(name="FpvsDetailedScalpSequential")
JOURNAL_TEXT_WIDTH_IN = 6.5
SINGLE_MAP_FIGSIZE = (JOURNAL_TEXT_WIDTH_IN, 5.6)
PAIRED_MAP_FIGSIZE = (JOURNAL_TEXT_WIDTH_IN, 3.4)
COMBINED_PAIRED_MAP_FIGSIZE = (JOURNAL_TEXT_WIDTH_IN, 5.8)
COMBINED_PAIRED_THREE_ROW_MAP_FIGSIZE = (JOURNAL_TEXT_WIDTH_IN, 8.0)
COMBINED_PAIRED_MAP_LEFT = 0.07
COMBINED_PAIRED_MAP_WIDTH = 0.31
COMBINED_PAIRED_SECOND_COL_LEFT = 0.49
COMBINED_PAIRED_COLORBAR_LEFT = 0.86
COMBINED_PAIRED_COLORBAR_WIDTH = 0.025
COMBINED_PAIRED_TOP_ROW_BOTTOM = 0.555
COMBINED_PAIRED_BOTTOM_ROW_BOTTOM = 0.10
SNR_COLORBAR_LABEL = "Signal to Noise Ratio"
ZSCORE_COLORBAR_LABEL = "Z Score"
ZSCORE_UNDER_COLOR = "#ffffff"
COMBINED_PAIRED_METRIC_ORDER = (
    PublicationMetric.BCA,
    PublicationMetric.SNR,
    PublicationMetric.Z_SCORE,
)
BCA_COLORBAR_LABEL = "Baseline-corrected amplitude (µV)"


def export_source_workbook(
    result: PublicationMapResult,
    request: PublicationMapRequest,
) -> Path:
    """Write long values, grand averages, diagnostics, and parameters."""

    request.output_root.mkdir(parents=True, exist_ok=True)
    workbook_path = request.output_root / SOURCE_WORKBOOK_NAME
    diagnostics_df = pd.DataFrame([diag.to_row() for diag in result.diagnostics])
    requested_metrics = _request_metrics(request)
    metric_params = _metric_parameter_rows(request, requested_metrics)
    params_df = pd.DataFrame(
        [
            {"key": "input_root", "value": str(request.input_root)},
            {"key": "output_root", "value": str(request.output_root)},
            {"key": "conditions", "value": "; ".join(request.conditions)},
            {
                "key": "metrics",
                "value": "; ".join(metric.value for metric in requested_metrics),
            },
            {"key": "harmonic_mode", "value": request.harmonic_mode.value},
            {
                "key": "selected_harmonics_hz",
                "value": "; ".join(f"{freq:g}" for freq in result.selected_harmonics_hz),
            },
            {"key": "base_frequency_hz", "value": request.base_frequency_hz},
            {"key": "max_frequency_hz", "value": request.max_frequency_hz or ""},
            *metric_params,
            {"key": "export_paired_figures", "value": request.export_paired_figures},
            {"key": "paired_conditions", "value": "; ".join(request.paired_conditions)},
            {
                "key": "selection_cache_source",
                "value": result.selection_metadata.get("selection_cache_source", ""),
            },
        ]
    )
    with pd.ExcelWriter(workbook_path) as writer:
        result.long_values.to_excel(writer, sheet_name=LONG_VALUES_SHEET, index=False)
        result.grand_average_values.to_excel(writer, sheet_name=GRAND_AVERAGE_SHEET, index=False)
        diagnostics_df.to_excel(writer, sheet_name=DIAGNOSTICS_SHEET, index=False)
        params_df.to_excel(writer, sheet_name=PARAMETERS_SHEET, index=False)
    result.source_workbook_path = workbook_path
    return workbook_path


def _request_metrics(request: PublicationMapRequest) -> tuple[PublicationMetric, ...]:
    metrics: list[PublicationMetric] = []
    for metric in request.metrics:
        normalized = PublicationMetric(metric)
        if normalized not in metrics:
            metrics.append(normalized)
    return tuple(metrics) or (PublicationMetric.BCA,)


def _metric_parameter_rows(
    request: PublicationMapRequest,
    metrics: tuple[PublicationMetric, ...],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for metric in metrics:
        bounds = request.color_bounds.get(metric, ColorBounds())
        prefix = metric.value
        rows.extend(
            [
                {"key": f"{prefix}_auto_scale", "value": bounds.auto_scale},
                {
                    "key": f"{prefix}_range_min",
                    "value": "" if bounds.vmin is None else bounds.vmin,
                },
                {
                    "key": f"{prefix}_range_max",
                    "value": "" if bounds.vmax is None else bounds.vmax,
                },
                {"key": f"{prefix}_low_color", "value": bounds.low_color},
                {"key": f"{prefix}_high_color", "value": bounds.high_color},
            ]
        )
    return rows


def render_publication_figures(
    result: PublicationMapResult,
    request: PublicationMapRequest,
) -> list[Path]:
    """Render grand-average scalp maps in the request."""

    request.output_root.mkdir(parents=True, exist_ok=True)
    rendered: list[Path] = []
    grand = result.grand_average_values
    if grand.empty:
        return rendered

    if request.export_paired_figures:
        rendered.extend(_render_paired_condition_figures(result, request))
        result.figure_paths = rendered
        return rendered

    group_cols = ["condition", "metric", "map_label"]
    for (condition, metric_value, map_label), group in grand.groupby(group_cols, dropna=False):
        metric = PublicationMetric(metric_value)
        montage_group = group[group["is_montage_electrode"] == True]  # noqa: E712
        if montage_group.empty:
            result.diagnostics.append(
                Diagnostic(
                    level="error",
                    condition=str(condition),
                    message="No BioSemi64 montage electrodes available for rendering.",
                    detail=f"{metric.display_name} {map_label}",
                )
            )
            continue
        title = str(condition)
        stem = sanitize_filename_stem(f"{condition}_{metric.value}_{map_label}")
        bounds = request.color_bounds.get(metric, ColorBounds())
        if request.export_png:
            png_path = request.output_root / f"{stem}.png"
            render_topomap(
                montage_group,
                metric=metric,
                title=title,
                output_path=png_path,
                bounds=bounds,
                dpi=request.png_dpi,
            )
            rendered.append(png_path)
        if request.export_pdf:
            pdf_path = request.output_root / f"{stem}.pdf"
            render_topomap(
                montage_group,
                metric=metric,
                title=title,
                output_path=pdf_path,
                bounds=bounds,
                dpi=request.png_dpi,
            )
            rendered.append(pdf_path)
    result.figure_paths = rendered
    return rendered


def render_topomap(
    values: pd.DataFrame,
    *,
    metric: PublicationMetric,
    title: str,
    output_path: Path,
    bounds: ColorBounds = ColorBounds(),
    dpi: int = 300,
) -> None:
    """Render one MNE topomap from grand-average values."""

    fig, ax = plt.subplots(figsize=SINGLE_MAP_FIGSIZE, dpi=dpi)
    try:
        cmap = colormap_for_metric(metric, bounds)
        im, missing_count = _draw_topomap(
            values,
            ax=ax,
            metric=metric,
            cmap=cmap,
            bounds=bounds,
        )
        cbar = fig.colorbar(
            im,
            ax=ax,
            fraction=0.046,
            pad=0.04,
            extend=_colorbar_extend(metric),
        )
        _style_colorbar(cbar, metric=metric)
        ax.set_title(title, pad=8, **figure_text_kwargs("condition_label"))
        if missing_count:
            ax.text(
                0.5,
                -0.08,
                f"Missing montage values rendered as 0: {missing_count}",
                transform=ax.transAxes,
                ha="center",
                va="top",
                **figure_text_kwargs("small"),
            )
        fig.tight_layout()
        _save_figure(fig, output_path, dpi=dpi)
    finally:
        plt.close(fig)


def colormap_for_metric(metric: PublicationMetric, bounds: ColorBounds | None = None):
    """Return the publication colormap for a metric."""

    if bounds is None:
        cmap = BCA_CMAP
    else:
        cmap = scalp_colormap(
            name="FpvsDetailedScalpSequentialCustom",
            low_color=bounds.low_color,
            high_color=bounds.high_color,
        )
    if metric is PublicationMetric.Z_SCORE:
        cmap = cmap.copy()
        cmap.set_under(ZSCORE_UNDER_COLOR)
        cmap.set_bad(ZSCORE_UNDER_COLOR)
    return cmap


def _render_paired_condition_figures(
    result: PublicationMapResult,
    request: PublicationMapRequest,
) -> list[Path]:
    grand = result.grand_average_values
    if grand.empty:
        return []
    rendered: list[Path] = []
    available_conditions = set(grand["condition"])
    condition_pairs = _paired_condition_pairs(request, available_conditions)
    if not condition_pairs:
        return []

    metrics = _request_metrics(request)
    if PublicationMetric.BCA in metrics and PublicationMetric.SNR in metrics:
        return _render_combined_paired_condition_figures(
            result,
            request,
            condition_pairs=condition_pairs,
        )

    for metric in metrics:
        bounds = request.color_bounds.get(metric, ColorBounds())
        for first, second in condition_pairs:
            first_group = _pair_group(grand, first, metric=metric)
            second_group = _pair_group(grand, second, metric=metric)
            if first_group.empty or second_group.empty:
                result.diagnostics.append(
                    Diagnostic(
                        level="warning",
                        message="Skipped paired scalp-map figure because one condition had no renderable values.",
                        detail=f"{metric.display_name}: {first}; {second}",
                    )
                )
                continue
            stem = sanitize_filename_stem(f"{first}_and_{second}_{metric.value}_paired")
            if request.export_png:
                png_path = request.output_root / f"{stem}.png"
                _render_paired_topomap(
                    first_group,
                    second_group,
                    metric=metric,
                    first_title=str(first),
                    second_title=str(second),
                    output_path=png_path,
                    bounds=bounds,
                    dpi=request.png_dpi,
                )
                rendered.append(png_path)
            if request.export_pdf:
                pdf_path = request.output_root / f"{stem}.pdf"
                _render_paired_topomap(
                    first_group,
                    second_group,
                    metric=metric,
                    first_title=str(first),
                    second_title=str(second),
                    output_path=pdf_path,
                    bounds=bounds,
                    dpi=request.png_dpi,
                )
                rendered.append(pdf_path)
    return rendered


def _render_combined_paired_condition_figures(
    result: PublicationMapResult,
    request: PublicationMapRequest,
    *,
    condition_pairs: list[tuple[str, str]],
) -> list[Path]:
    grand = result.grand_average_values
    rendered: list[Path] = []
    requested_metrics = _request_metrics(request)
    metrics = tuple(
        metric for metric in COMBINED_PAIRED_METRIC_ORDER if metric in requested_metrics
    )
    for first, second in condition_pairs:
        groups: dict[PublicationMetric, tuple[pd.DataFrame, pd.DataFrame]] = {}
        for metric in metrics:
            first_group = _pair_group(grand, first, metric=metric)
            second_group = _pair_group(grand, second, metric=metric)
            if first_group.empty or second_group.empty:
                result.diagnostics.append(
                    Diagnostic(
                        level="warning",
                        message="Skipped combined paired scalp-map figure because one condition had no renderable values.",
                        detail=f"{metric.display_name}: {first}; {second}",
                    )
                )
                groups = {}
                break
            groups[metric] = (first_group, second_group)
        if not groups:
            continue

        metric_stem = "_".join(metric.value for metric in metrics)
        stem = sanitize_filename_stem(f"{first}_and_{second}_{metric_stem}_paired")
        if request.export_png:
            png_path = request.output_root / f"{stem}.png"
            _render_combined_paired_topomap(
                groups,
                metrics=metrics,
                first_title=str(first),
                second_title=str(second),
                output_path=png_path,
                bounds_by_metric=request.color_bounds,
                dpi=request.png_dpi,
            )
            rendered.append(png_path)
        if request.export_pdf:
            pdf_path = request.output_root / f"{stem}.pdf"
            _render_combined_paired_topomap(
                groups,
                metrics=metrics,
                first_title=str(first),
                second_title=str(second),
                output_path=pdf_path,
                bounds_by_metric=request.color_bounds,
                dpi=request.png_dpi,
            )
            rendered.append(pdf_path)
    return rendered


def _paired_condition_pairs(
    request: PublicationMapRequest,
    available_conditions: set[str],
) -> list[tuple[str, str]]:
    if len(request.paired_conditions) >= 2:
        first, second = request.paired_conditions[:2]
        if first in available_conditions and second in available_conditions and first != second:
            return [(first, second)]
        return []

    conditions = [
        condition for condition in request.conditions if condition in available_conditions
    ]
    return list(zip(conditions[0::2], conditions[1::2]))


def _pair_group(
    grand: pd.DataFrame,
    condition: str,
    *,
    metric: PublicationMetric,
) -> pd.DataFrame:
    group = grand[
        (grand["condition"] == condition)
        & (grand["metric"] == metric.value)
        & (grand["is_montage_electrode"] == True)  # noqa: E712
    ]
    return group


def _render_paired_topomap(
    first_values: pd.DataFrame,
    second_values: pd.DataFrame,
    *,
    metric: PublicationMetric,
    first_title: str,
    second_title: str,
    output_path: Path,
    bounds: ColorBounds,
    dpi: int,
) -> None:
    fig, axes = plt.subplots(1, 2, figsize=PAIRED_MAP_FIGSIZE, dpi=dpi)
    cmap = colormap_for_metric(metric, bounds)
    shared_vlim = _paired_vlim(
        first_values,
        second_values,
        metric=metric,
        bounds=bounds,
    )
    try:
        im, first_missing = _draw_topomap(
            first_values,
            ax=axes[0],
            metric=metric,
            cmap=cmap,
            bounds=bounds,
            vlim_override=shared_vlim,
        )
        _, second_missing = _draw_topomap(
            second_values,
            ax=axes[1],
            metric=metric,
            cmap=cmap,
            bounds=bounds,
            vlim_override=shared_vlim,
        )
        axes[0].set_title(first_title, pad=8, **_paired_condition_title_kwargs())
        axes[1].set_title(second_title, pad=8, **_paired_condition_title_kwargs())
        if first_missing:
            _add_missing_note(axes[0], first_missing)
        if second_missing:
            _add_missing_note(axes[1], second_missing)
        cbar = fig.colorbar(
            im,
            ax=list(axes),
            fraction=0.035,
            pad=0.04,
            extend=_colorbar_extend(metric),
        )
        _style_colorbar(cbar, metric=metric)
        _save_figure(fig, output_path, dpi=dpi)
    finally:
        plt.close(fig)


def _render_combined_paired_topomap(
    values_by_metric: dict[PublicationMetric, tuple[pd.DataFrame, pd.DataFrame]],
    *,
    metrics: tuple[PublicationMetric, ...],
    first_title: str,
    second_title: str,
    output_path: Path,
    bounds_by_metric: dict[PublicationMetric, ColorBounds],
    dpi: int,
) -> None:
    fig = plt.figure(figsize=_combined_paired_figsize(metrics), dpi=dpi)
    layout = _combined_paired_layout_rects(metrics=metrics)
    try:
        for row_idx, metric in enumerate(metrics):
            first_values, second_values = values_by_metric[metric]
            row_layout = layout[metric]
            row_axes = [
                fig.add_axes(row_layout["first"]),
                fig.add_axes(row_layout["second"]),
            ]
            cax = fig.add_axes(row_layout["colorbar"])
            bounds = bounds_by_metric.get(metric, ColorBounds())
            cmap = colormap_for_metric(metric, bounds)
            shared_vlim = _paired_vlim(
                first_values,
                second_values,
                metric=metric,
                bounds=bounds,
            )
            im, first_missing = _draw_topomap(
                first_values,
                ax=row_axes[0],
                metric=metric,
                cmap=cmap,
                bounds=bounds,
                vlim_override=shared_vlim,
            )
            _, second_missing = _draw_topomap(
                second_values,
                ax=row_axes[1],
                metric=metric,
                cmap=cmap,
                bounds=bounds,
                vlim_override=shared_vlim,
            )
            if row_idx == 0:
                row_axes[0].set_title(
                    first_title,
                    pad=8,
                    **_paired_condition_title_kwargs(),
                )
                row_axes[1].set_title(
                    second_title,
                    pad=8,
                    **_paired_condition_title_kwargs(),
                )
            if first_missing:
                _add_missing_note(row_axes[0], first_missing)
            if second_missing:
                _add_missing_note(row_axes[1], second_missing)
            cbar = fig.colorbar(im, cax=cax, extend=_colorbar_extend(metric))
            _style_colorbar(cbar, metric=metric)
        _save_figure(fig, output_path, dpi=dpi)
    finally:
        plt.close(fig)


def _combined_paired_layout_rects(
    *,
    metrics: tuple[PublicationMetric, ...] = (
        PublicationMetric.BCA,
        PublicationMetric.SNR,
    ),
) -> dict[PublicationMetric, dict[str, tuple[float, float, float, float]]]:
    figure_size = _combined_paired_figsize(metrics)
    map_height = COMBINED_PAIRED_MAP_WIDTH * (figure_size[0] / figure_size[1])
    if metrics == (PublicationMetric.BCA, PublicationMetric.SNR):
        rows = {
            PublicationMetric.BCA: COMBINED_PAIRED_TOP_ROW_BOTTOM,
            PublicationMetric.SNR: COMBINED_PAIRED_BOTTOM_ROW_BOTTOM,
        }
    else:
        top = 0.94
        bottom = 0.075
        if len(metrics) > 1:
            gap = (top - bottom - (len(metrics) * map_height)) / (len(metrics) - 1)
            gap = max(gap, 0.035)
        else:
            gap = 0.0
        rows = {
            metric: top - map_height - index * (map_height + gap)
            for index, metric in enumerate(metrics)
        }
    return {
        metric: {
            "first": (
                COMBINED_PAIRED_MAP_LEFT,
                bottom,
                COMBINED_PAIRED_MAP_WIDTH,
                map_height,
            ),
            "second": (
                COMBINED_PAIRED_SECOND_COL_LEFT,
                bottom,
                COMBINED_PAIRED_MAP_WIDTH,
                map_height,
            ),
            "colorbar": (
                COMBINED_PAIRED_COLORBAR_LEFT,
                bottom,
                COMBINED_PAIRED_COLORBAR_WIDTH,
                map_height,
            ),
        }
        for metric, bottom in rows.items()
    }


def _combined_paired_figsize(metrics: tuple[PublicationMetric, ...]) -> tuple[float, float]:
    if len(metrics) >= 3:
        return COMBINED_PAIRED_THREE_ROW_MAP_FIGSIZE
    return COMBINED_PAIRED_MAP_FIGSIZE


def _draw_topomap(
    values: pd.DataFrame,
    *,
    ax: plt.Axes,
    metric: PublicationMetric,
    cmap,
    bounds: ColorBounds,
    vlim_override: tuple[float, float] | None = None,
):
    data, info, missing_count, diagnostics = align_render_values(values)
    _ = diagnostics
    vlim = vlim_override or _metric_limits(data, metric=metric, bounds=bounds)
    im = _plot_topomap_compat(
        data=data,
        info=info,
        ax=ax,
        cmap=cmap,
        vlim=vlim,
    )
    return im, missing_count


def _paired_vlim(
    first_values: pd.DataFrame,
    second_values: pd.DataFrame,
    *,
    metric: PublicationMetric,
    bounds: ColorBounds,
) -> tuple[float, float]:
    first_data, _first_info, _first_missing, _first_diag = align_render_values(first_values)
    second_data, _second_info, _second_missing, _second_diag = align_render_values(second_values)
    data = np.concatenate([first_data, second_data])
    return _metric_limits(data, metric=metric, bounds=bounds)


def _add_missing_note(ax: plt.Axes, missing_count: int) -> None:
    ax.text(
        0.5,
        -0.08,
        f"Missing montage values rendered as 0: {missing_count}",
        transform=ax.transAxes,
        ha="center",
        va="top",
        **figure_text_kwargs("small"),
    )


def colorbar_label_for_metric(metric: PublicationMetric) -> str:
    """Return the publication colorbar label for a metric."""

    if metric is PublicationMetric.BCA:
        return BCA_COLORBAR_LABEL
    if metric is PublicationMetric.SNR:
        return SNR_COLORBAR_LABEL
    if metric is PublicationMetric.Z_SCORE:
        return ZSCORE_COLORBAR_LABEL
    return metric.display_name


def _colorbar_extend(metric: PublicationMetric) -> str:
    if metric is PublicationMetric.Z_SCORE:
        return "min"
    return "neither"


def _style_colorbar(
    cbar,
    *,
    metric: PublicationMetric,
    label_position: str = "right",
) -> None:
    label_kwargs = _colorbar_text_kwargs()
    cbar.ax.set_ylabel(colorbar_label_for_metric(metric), **label_kwargs)
    cbar.ax.yaxis.set_label_position(label_position)
    cbar.ax.yaxis.set_ticks_position("right")
    apply_axis_text_style(cbar.ax)


def _paired_condition_title_kwargs() -> dict[str, object]:
    """Return bold, larger title styling for paired scalp-map column headers."""

    return figure_text_kwargs("panel_label")


def _colorbar_text_kwargs() -> dict[str, object]:
    """Return bold colorbar text styling for scalp-map legends."""

    kwargs = figure_text_kwargs("axis_label")
    kwargs["fontweight"] = "bold"
    return kwargs


def _save_figure(fig: plt.Figure, output_path: Path, *, dpi: int) -> None:
    """Save figure with transparent backgrounds for PDF composition workflows."""

    transparent = output_path.suffix.lower() == ".pdf"
    if transparent:
        fig.patch.set_alpha(0)
        for ax in fig.axes:
            ax.set_facecolor("none")
            ax.patch.set_alpha(0)
    fig.savefig(output_path, dpi=dpi, transparent=transparent)


def sanitize_filename_stem(value: str) -> str:
    """Return a Windows-safe filename stem."""

    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value)).strip("._")
    return stem or "scalp_map"


def _metric_limits(
    data: np.ndarray,
    *,
    metric: PublicationMetric,
    bounds: ColorBounds,
) -> tuple[float, float]:
    finite = data[np.isfinite(data)]
    if not len(finite):
        if metric is PublicationMetric.Z_SCORE:
            finite = np.asarray([DEFAULT_Z_SCORE_THRESHOLD])
        else:
            finite = np.asarray([1.0, 1.5] if metric is PublicationMetric.SNR else [0.0])
    if metric is PublicationMetric.Z_SCORE:
        vmin = (
            float(bounds.vmin)
            if bounds.vmin is not None
            else DEFAULT_Z_SCORE_THRESHOLD
        )
        vmax = float(np.nanmax(finite))
        if vmax <= vmin:
            vmax = vmin + 1.0
        return (vmin, vmax)
    if not bounds.auto_scale and bounds.vmin is not None and bounds.vmax is not None:
        vmin = float(bounds.vmin)
        vmax = float(bounds.vmax)
    else:
        if metric is PublicationMetric.SNR:
            vmin = float(np.nanmin(finite))
            vmax = float(np.nanmax(finite))
        else:
            vmin = 0.0
            vmax = float(np.nanmax(finite))
            if vmax <= 0:
                vmax = 1.0
    if vmax <= vmin:
        vmax = vmin + 1.0
    return (vmin, vmax)


def _plot_topomap_compat(
    *,
    data: np.ndarray,
    info: mne.io.Info,
    ax: plt.Axes,
    cmap,
    vlim: tuple[float, float],
):
    try:
        im, _ = mne.viz.plot_topomap(
            data,
            info,
            axes=ax,
            cmap=cmap,
            vlim=vlim,
            contours=0,
            sensors=True,
            show=False,
            outlines="head",
        )
        return im
    except TypeError:
        im, _ = mne.viz.plot_topomap(
            data,
            info,
            axes=ax,
            cmap=cmap,
            vmin=vlim[0],
            vmax=vlim[1],
            contours=0,
            sensors=True,
            show=False,
            outlines="head",
        )
        return im
