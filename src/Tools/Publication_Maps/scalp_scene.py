"""Prepare interactive surface panels from the same qualified tables and limits as export."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import matplotlib
import mne
import numpy as np
from matplotlib.colors import Colormap, Normalize

from Main_App.projects import validate_group_folder_name
from Tools.Publication_Maps.models import (
    ColorBounds, PublicationMapInputError, PublicationMapRequest, PublicationMapResult,
    PublicationMetric, WorkbookEntry,
)
from Tools.Publication_Maps.rendering import (
    _colorbar_extend, _comparison_metric_group, _group_comparison_titles,
    _metric_limits, _pair_group, _paired_condition_pairs, _paired_vlim, _request_metrics,
    _request_with_result_group, _validate_group_comparison_results, colorbar_label_for_metric,
    colormap_for_metric,
)
from Tools.Publication_Maps.scalp_io import align_render_values
from Tools.Publication_Maps.session_rendering import (
    _difference_frame, _difference_limit, _main_vlim, _panel_frame,
)
from Tools.Publication_Maps.session_workflow import build_session_panel_sets


@dataclass(frozen=True, slots=True)
class ScalpSurfacePanel:
    """Finite montage values, figure scale and frozen evidence for a camera view."""

    label: str
    metric: PublicationMetric
    colorbar_label: str
    data: np.ndarray
    info: mne.Info
    cmap: Colormap
    norm: Normalize
    extend: str
    missing_count: int
    title: str
    input_root: Path
    output_root: Path
    output_base_root: Path
    source_workbooks: tuple[WorkbookEntry, ...]
    project_root: Path | None
    release_fingerprint: str


def build_surface_panels(
    results: Sequence[PublicationMapResult], requests: Sequence[PublicationMapRequest], *,
    cancel_check: Callable[[], None],
) -> tuple[ScalpSurfacePanel, ...]:
    first = requests[0]
    panels: list[ScalpSurfacePanel] = []
    source_workbooks = tuple(entry for result in results for entry in result.included_workbooks)
    release_fingerprints = {
        str(result.selection_metadata.get("final_release_receipt_fingerprint", ""))
        for result in results
    }
    if len(release_fingerprints) != 1:
        raise PublicationMapInputError(
            "Scalp Maps groups used different final QC releases. Reopen the viewer with current data."
        )
    release_fingerprint, = release_fingerprints

    def add(
        frame, names, metric, bounds, *, geometry, limits=None, difference=False,
        output_root=first.output_root,
    ) -> None:
        cancel_check()
        data, info, missing, _ = align_render_values(frame, geometry=geometry)
        vlim = limits or _metric_limits(data, metric=metric, bounds=bounds)
        data.flags.writeable = False
        title = " · ".join(str(name) for name in names if name)
        label = f"{title} · {metric.display_name}"
        panels.append(ScalpSurfacePanel(
            label=label,
            title=title,
            metric=metric,
            colorbar_label=colorbar_label_for_metric(metric),
            data=data,
            info=info,
            cmap=matplotlib.colormaps["RdBu_r"] if difference else colormap_for_metric(metric, bounds, scalp_view="3d"),
            norm=Normalize(*vlim),
            extend="neither" if difference else _colorbar_extend(metric),
            missing_count=missing,
            input_root=first.input_root,
            output_root=output_root,
            output_base_root=first.output_root,
            source_workbooks=source_workbooks,
            project_root=first.project_root,
            release_fingerprint=release_fingerprint,
        ))

    if first.export_session_grid_figure:
        for panel_set in build_session_panel_sets(results, requests, cancel_check=cancel_check):
            metric = panel_set.metric
            bounds = first.color_bounds.get(metric, ColorBounds())
            limits = _main_vlim(panel_set, bounds)
            for session in panel_set.session_ids:
                for group_id in panel_set.group_ids:
                    panel = panel_set.panel(group_id, session)
                    add(
                        _panel_frame(panel), (panel_set.condition, panel.group_label, panel.session_label),
                        metric, bounds, geometry=panel_set.geometry, limits=limits,
                    )
            if first.export_paired_session_difference:
                limit = _difference_limit(panel_set)
                for group_id in panel_set.group_ids:
                    diff = panel_set.paired_difference(group_id)
                    contrast = f"{diff.comparison_session_label} − {diff.reference_session_label}"
                    add(
                        _difference_frame(diff), (panel_set.condition, diff.group_label, contrast),
                        metric, bounds, geometry=panel_set.geometry, limits=(-limit, limit), difference=True,
                    )
    elif first.export_group_comparison_figure:
        geometry = _validate_group_comparison_results(results, requests)
        condition, = first.conditions
        titles = _group_comparison_titles(requests)
        for metric in _request_metrics(first):
            frames = [
                _comparison_metric_group(result.grand_average_values, condition=condition,
                                         group_id=request.group_id, metric=metric)
                for result, request in zip(results, requests, strict=True)
            ]
            bounds = first.color_bounds.get(metric, ColorBounds())
            limits = _paired_vlim(*frames, metric=metric, bounds=bounds, geometry=geometry)
            for title, frame in zip(titles, frames, strict=True):
                add(frame, (condition, title), metric, bounds, geometry=geometry, limits=limits)
    else:
        for result, request in zip(results, requests, strict=True):
            grand = result.grand_average_values
            context = (result.group_label, *request.session_ids)
            resolved_request = _request_with_result_group(request, result)
            output_root = resolved_request.output_root
            if resolved_request.group_folder:
                output_root /= validate_group_folder_name(resolved_request.group_folder)
            if request.export_paired_figures:
                for conditions in _paired_condition_pairs(request, set(grand["condition"])):
                    for metric in _request_metrics(request):
                        frames = [_pair_group(grand, condition, metric=metric) for condition in conditions]
                        bounds = request.color_bounds.get(metric, ColorBounds())
                        limits = _paired_vlim(*frames, metric=metric, bounds=bounds, geometry=result.geometry)
                        for condition, frame in zip(conditions, frames, strict=True):
                            add(
                                frame, (condition, *context), metric, bounds,
                                geometry=result.geometry, limits=limits, output_root=output_root,
                            )
            else:
                for (condition, metric_value, _), frame in grand.groupby(["condition", "metric", "map_label"], dropna=False):
                    metric = PublicationMetric(metric_value)
                    add(frame[frame["is_montage_electrode"]], (condition, *context), metric,
                        request.color_bounds.get(metric, ColorBounds()), geometry=result.geometry, output_root=output_root)
    if not panels:
        raise PublicationMapInputError("No scalp values are available for the selected 3D views.")
    return tuple(panels)
