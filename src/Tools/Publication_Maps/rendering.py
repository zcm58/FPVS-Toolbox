"""Rendering and workbook export for publication scalp maps."""

from __future__ import annotations

import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, is_color_like
import mne
import numpy as np
import pandas as pd

from Main_App.gui.components import matplotlib_font_kwargs
from Tools.Publication_Maps.models import (
    DIAGNOSTICS_SHEET,
    GRAND_AVERAGE_SHEET,
    LONG_VALUES_SHEET,
    PARAMETERS_SHEET,
    SOURCE_WORKBOOK_NAME,
    ColorBounds,
    DEFAULT_BCA_HIGH_COLOR,
    DEFAULT_BCA_HIGH_MID_COLOR,
    DEFAULT_BCA_LOW_COLOR,
    DEFAULT_BCA_LOW_MID_COLOR,
    Diagnostic,
    PublicationMapRequest,
    PublicationMapResult,
    PublicationMetric,
)
from Tools.Publication_Maps.scalp_io import align_render_values

BCA_CMAP = LinearSegmentedColormap.from_list(
    "FpvsLowBlueSequential",
    [
        DEFAULT_BCA_LOW_COLOR,
        DEFAULT_BCA_LOW_MID_COLOR,
        DEFAULT_BCA_HIGH_MID_COLOR,
        DEFAULT_BCA_HIGH_COLOR,
    ],
)
JOURNAL_TEXT_WIDTH_IN = 6.5
SINGLE_MAP_FIGSIZE = (JOURNAL_TEXT_WIDTH_IN, 5.6)
PAIRED_MAP_FIGSIZE = (JOURNAL_TEXT_WIDTH_IN, 3.4)
SNR_COLORBAR_LABEL = "Signal to Noise Ratio"
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
    """Render all grand-average scalp maps in the request."""

    request.output_root.mkdir(parents=True, exist_ok=True)
    rendered: list[Path] = []
    grand = result.grand_average_values
    if grand.empty:
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
        if request.export_svg:
            svg_path = request.output_root / f"{stem}.svg"
            render_topomap(
                montage_group,
                metric=metric,
                title=title,
                output_path=svg_path,
                bounds=bounds,
                dpi=request.png_dpi,
            )
            rendered.append(svg_path)
    if request.export_paired_figures:
        rendered.extend(_render_paired_condition_figures(result, request))
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
        cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
        _style_colorbar(cbar, metric=metric)
        ax.set_title(title, pad=8, **matplotlib_font_kwargs("figure_title"))
        if missing_count:
            ax.text(
                0.5,
                -0.08,
                f"Missing montage values rendered as 0: {missing_count}",
                transform=ax.transAxes,
                ha="center",
                va="top",
                **matplotlib_font_kwargs("figure_note"),
            )
        fig.tight_layout()
        _save_figure(fig, output_path, dpi=dpi)
    finally:
        plt.close(fig)


def colormap_for_metric(metric: PublicationMetric, bounds: ColorBounds | None = None):
    """Return the publication colormap for a metric."""

    _ = metric
    if bounds is None:
        return BCA_CMAP
    low_color = _valid_color(bounds.low_color, DEFAULT_BCA_LOW_COLOR)
    high_color = _valid_color(bounds.high_color, DEFAULT_BCA_HIGH_COLOR)
    return LinearSegmentedColormap.from_list(
        "FpvsLowBlueSequentialCustom",
        [
            low_color,
            DEFAULT_BCA_LOW_MID_COLOR,
            DEFAULT_BCA_HIGH_MID_COLOR,
            high_color,
        ],
    )


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

    for metric in _request_metrics(request):
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
            if request.export_svg:
                svg_path = request.output_root / f"{stem}.svg"
                _render_paired_topomap(
                    first_group,
                    second_group,
                    metric=metric,
                    first_title=str(first),
                    second_title=str(second),
                    output_path=svg_path,
                    bounds=bounds,
                    dpi=request.png_dpi,
                )
                rendered.append(svg_path)
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
        axes[0].set_title(first_title, pad=8, **matplotlib_font_kwargs("figure_title"))
        axes[1].set_title(second_title, pad=8, **matplotlib_font_kwargs("figure_title"))
        if first_missing:
            _add_missing_note(axes[0], first_missing)
        if second_missing:
            _add_missing_note(axes[1], second_missing)
        cbar = fig.colorbar(im, ax=list(axes), fraction=0.035, pad=0.04)
        _style_colorbar(cbar, metric=metric)
        _save_figure(fig, output_path, dpi=dpi)
    finally:
        plt.close(fig)


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
        **matplotlib_font_kwargs("figure_note"),
    )


def colorbar_label_for_metric(metric: PublicationMetric) -> str:
    """Return the publication colorbar label for a metric."""

    if metric is PublicationMetric.BCA:
        return BCA_COLORBAR_LABEL
    if metric is PublicationMetric.SNR:
        return SNR_COLORBAR_LABEL
    return metric.display_name


def _style_colorbar(cbar, *, metric: PublicationMetric) -> None:
    label_kwargs = matplotlib_font_kwargs("figure_axis_label")
    tick_kwargs = matplotlib_font_kwargs("figure_tick")
    cbar.ax.set_ylabel(colorbar_label_for_metric(metric), **label_kwargs)
    cbar.ax.tick_params(labelsize=tick_kwargs["fontsize"])
    for tick_label in cbar.ax.get_yticklabels():
        tick_label.set_fontfamily(str(tick_kwargs["fontfamily"]))
        tick_label.set_fontweight(tick_kwargs["fontweight"])


def _save_figure(fig: plt.Figure, output_path: Path, *, dpi: int) -> None:
    """Save figure with transparent backgrounds for SVG composition workflows."""

    transparent = output_path.suffix.lower() == ".svg"
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
        finite = np.asarray([1.0, 1.5] if metric is PublicationMetric.SNR else [0.0])
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


def _valid_color(value: str, fallback: str) -> str:
    color = str(value).strip()
    if is_color_like(color):
        return color
    return fallback


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
