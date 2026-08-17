"""Publication scalp-map figure rendering."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import replace
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
from Tools.Publication_Maps.excel_inputs import load_publication_dataset_index
from Tools.Publication_Maps.models import (
    ColorBounds,
    DEFAULT_Z_SCORE_THRESHOLD,
    Diagnostic,
    PublicationMapInputError,
    PublicationMapRequest,
    PublicationMapResult,
    PublicationMetric,
)
from Tools.Publication_Maps.output_contract import PublicationArtifactTransaction
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


def _request_metrics(request: PublicationMapRequest) -> tuple[PublicationMetric, ...]:
    metrics: list[PublicationMetric] = []
    for metric in request.metrics:
        normalized = PublicationMetric(metric)
        if normalized not in metrics:
            metrics.append(normalized)
    return tuple(metrics) or (PublicationMetric.BCA,)


def validate_group_comparison_requests(
    requests: Sequence[PublicationMapRequest],
) -> bool:
    """Validate the exact two-group, one-condition comparison contract."""

    normalized = tuple(requests)
    enabled = tuple(
        bool(request.export_group_comparison_figure) for request in normalized
    )
    comparison_ids_present = any(
        bool(request.group_comparison_ids) for request in normalized
    )
    if not any(enabled):
        if comparison_ids_present:
            raise ValueError(
                "Scalp Maps group comparison IDs require comparison export to be enabled."
            )
        return False
    if len(normalized) != 2 or not all(enabled):
        raise ValueError(
            "Scalp Maps group comparison requires exactly two enabled group requests."
        )
    baseline = replace(
        normalized[0],
        group_id=None,
        group_label=None,
        group_folder=None,
    )
    if any(
        replace(
            request,
            group_id=None,
            group_label=None,
            group_folder=None,
        )
        != baseline
        for request in normalized[1:]
    ):
        raise ValueError(
            "Scalp Maps group comparison requests may differ only by canonical group."
        )
    if any(
        request.export_paired_figures or request.paired_conditions
        for request in normalized
    ):
        raise ValueError(
            "Group comparison cannot be combined with paired-condition figures."
        )
    conditions = tuple(tuple(request.conditions) for request in normalized)
    if any(len(condition_set) != 1 for condition_set in conditions):
        raise ValueError(
            "Scalp Maps group comparison requires exactly one selected condition."
        )
    if conditions[0] != conditions[1]:
        raise ValueError(
            "Scalp Maps group comparison requests must use the same condition."
        )

    request_ids = tuple(str(request.group_id or "").strip() for request in normalized)
    if any(not group_id for group_id in request_ids):
        raise ValueError("Scalp Maps group comparison requires canonical group IDs.")
    if len({group_id.casefold() for group_id in request_ids}) != 2:
        raise ValueError(
            "Scalp Maps group comparison requires two distinct canonical group IDs."
        )
    comparison_ids = tuple(
        str(group_id).strip() for group_id in normalized[0].group_comparison_ids
    )
    if len(comparison_ids) != 2 or tuple(
        group_id.casefold() for group_id in comparison_ids
    ) != tuple(group_id.casefold() for group_id in request_ids):
        raise ValueError(
            "Scalp Maps group comparison IDs must match the ordered canonical group requests."
        )
    if any(
        tuple(
            str(group_id).strip().casefold()
            for group_id in request.group_comparison_ids
        )
        != tuple(group_id.casefold() for group_id in comparison_ids)
        for request in normalized[1:]
    ):
        raise ValueError(
            "Scalp Maps group comparison requests must use the same ordered group IDs."
        )
    if any(not str(request.group_label or "").strip() for request in normalized):
        raise ValueError("Scalp Maps group comparison requires canonical group labels.")
    if any(not str(request.group_folder or "").strip() for request in normalized):
        raise ValueError(
            "Scalp Maps group comparison requires canonical group output folders."
        )
    if any(
        Path(request.output_root).expanduser().resolve(strict=False)
        != Path(normalized[0].output_root).expanduser().resolve(strict=False)
        for request in normalized[1:]
    ):
        raise ValueError(
            "Scalp Maps group comparison requests must share one base output folder."
        )
    if not normalized[0].export_png and not normalized[0].export_pdf:
        raise ValueError("Scalp Maps group comparison requires PNG and/or PDF export.")
    return True


def validate_group_comparison_project_groups(
    requests: Sequence[PublicationMapRequest],
) -> None:
    """Require the request pair to equal the project's full canonical group set."""

    normalized = tuple(requests)
    validate_group_comparison_requests(normalized)
    try:
        index = load_publication_dataset_index(
            normalized[0].input_root,
            project_root=normalized[0].project_root,
        )
    except Exception as exc:
        raise PublicationMapInputError(
            f"Unable to validate Scalp Maps comparison groups: {exc}"
        ) from exc
    canonical_ids = tuple(group.group_id for group in index.ordered_groups)
    requested_ids = tuple(
        str(group_id).strip() for group_id in normalized[0].group_comparison_ids
    )
    if len(canonical_ids) != 2 or tuple(
        group_id.casefold() for group_id in canonical_ids
    ) != tuple(group_id.casefold() for group_id in requested_ids):
        raise PublicationMapInputError(
            "The side-by-side group figure is available only when the project "
            "has exactly two canonical groups, in canonical order. Project "
            f"groups: {', '.join(canonical_ids) or '(none)'}; requested: "
            f"{', '.join(requested_ids)}."
        )


def _group_comparison_identity(
    requests: Sequence[PublicationMapRequest],
) -> tuple[str, str, str]:
    normalized = tuple(requests)
    validate_group_comparison_requests(normalized)
    condition = str(normalized[0].conditions[0])
    first_id, second_id = (
        str(group_id).strip() for group_id in normalized[0].group_comparison_ids
    )
    return condition, first_id, second_id


def _validate_group_comparison_results(
    results: Sequence[PublicationMapResult],
    requests: Sequence[PublicationMapRequest],
) -> None:
    normalized_results = tuple(results)
    normalized_requests = tuple(requests)
    validate_group_comparison_requests(normalized_requests)
    if len(normalized_results) != 2:
        raise ValueError(
            "Scalp Maps group comparison requires exactly two completed group results."
        )
    condition = normalized_requests[0].conditions[0]
    expected_metrics = {
        metric.value for metric in _request_metrics(normalized_requests[0])
    }
    harmonic_sets = {
        tuple(result.selected_harmonics_hz) for result in normalized_results
    }
    selection_fingerprints = {
        str(result.selection_metadata.get("selection_fingerprint", ""))
        for result in normalized_results
    }
    qc_fingerprints = {
        str(result.qc_provenance.get("applied_exclusions_sha256", ""))
        for result in normalized_results
    }
    if (
        len(harmonic_sets) != 1
        or not next(iter(harmonic_sets), ())
        or len(selection_fingerprints) != 1
        or not next(iter(selection_fingerprints), "")
    ):
        raise PublicationMapInputError(
            "Group comparison results used different saved harmonic selections. Rerun the complete comparison batch."
        )
    if len(qc_fingerprints) != 1 or not next(iter(qc_fingerprints), ""):
        raise PublicationMapInputError(
            "Group comparison results used different QC exclusion snapshots. Rerun the complete comparison batch."
        )
    for result, request in zip(
        normalized_results,
        normalized_requests,
        strict=True,
    ):
        _request_with_result_group(request, result)
        request_id = str(request.group_id or "")
        result_id = str(result.group_id or "")
        if result_id.casefold() != request_id.casefold():
            raise PublicationMapInputError(
                "Scalp Maps comparison result group identity does not match its "
                f"canonical request: {result_id!r} != {request_id!r}."
            )
        grand = result.grand_average_values
        if grand.empty:
            raise PublicationMapInputError(
                f"No renderable values are available for group {request_id}."
            )
        conditions = {str(value) for value in grand["condition"].dropna().unique()}
        if conditions != {condition}:
            raise PublicationMapInputError(
                "Group comparison results must contain exactly the selected "
                f"condition {condition!r}; found {sorted(conditions)!r}."
            )
        metrics = {str(value) for value in grand["metric"].dropna().unique()}
        if not expected_metrics.issubset(metrics):
            missing = sorted(expected_metrics - metrics)
            raise PublicationMapInputError(
                f"Group {request_id} is missing comparison metric(s): "
                + ", ".join(missing)
            )
        if "group_id" in grand.columns:
            frame_ids = {
                str(value)
                for value in grand["group_id"].dropna().unique()
                if str(value).strip()
            }
            if {value.casefold() for value in frame_ids} != {request_id.casefold()}:
                raise PublicationMapInputError(
                    "Scalp Maps comparison data contain a mismatched or pooled "
                    f"group identity for {request_id}: {sorted(frame_ids)!r}."
                )


def _group_comparison_stem(
    *,
    condition: str,
    first_id: str,
    second_id: str,
    metric_stem: str,
) -> str:
    return sanitize_filename_stem(
        f"{condition}_{first_id}_and_{second_id}_{metric_stem}_group_comparison"
    )


def _group_comparison_titles(
    requests: Sequence[PublicationMapRequest],
) -> tuple[str, str]:
    first, second = tuple(requests)
    first_label = str(first.group_label or "").strip()
    second_label = str(second.group_label or "").strip()
    if first_label.casefold() == second_label.casefold():
        return (
            f"{first_label} ({first.group_id})",
            f"{second_label} ({second.group_id})",
        )
    return first_label, second_label


def _request_with_result_group(
    request: PublicationMapRequest,
    result: PublicationMapResult,
) -> PublicationMapRequest:
    """Fill blank request identity from a backend-resolved sole group."""

    updates: dict[str, object] = {}
    for name in ("group_id", "group_label", "group_folder"):
        if not hasattr(request, name):
            continue
        request_value = getattr(request, name, None)
        result_value = getattr(result, name, None)
        if (
            request_value not in (None, "")
            and result_value not in (None, "")
            and request_value != result_value
        ):
            raise PublicationMapInputError(
                "Scalp Maps group identity changed between analysis and output "
                f"for {name}: request={request_value!r}, result={result_value!r}."
            )
        if request_value in (None, "") and result_value not in (None, ""):
            updates[name] = result_value
    return replace(request, **updates) if updates else request


def render_publication_figures(
    result: PublicationMapResult,
    request: PublicationMapRequest,
    *,
    cancel_check: Callable[[], None] | None = None,
    transaction: PublicationArtifactTransaction | None = None,
) -> list[Path]:
    """Stage every requested figure and publish the batch atomically."""

    effective_request = _request_with_result_group(request, result)
    owns_transaction = transaction is None
    active_transaction = transaction or PublicationArtifactTransaction(effective_request)
    try:
        active_transaction.ensure_request_target(effective_request)
        staging_root = active_transaction.staging_output_root_for(effective_request)
        staging_updates: dict[str, object] = {"output_root": staging_root}
        if hasattr(effective_request, "group_folder"):
            staging_updates["group_folder"] = None
        staging_request = replace(effective_request, **staging_updates)
        staged_paths = _render_publication_figures_staged(
            result,
            staging_request,
            cancel_check=cancel_check,
        )
        _checkpoint(cancel_check)
        final_paths = [
            active_transaction.register_staged_path(path)
            for path in staged_paths
        ]
        result.figure_paths = final_paths
        if owns_transaction:
            active_transaction.commit(cancel_check=cancel_check)
        return final_paths
    except Exception:  # Transaction boundary: discard staging for any render/cancel failure.
        if owns_transaction:
            active_transaction.abort()
        raise


def render_group_comparison_figures(
    results: Sequence[PublicationMapResult],
    requests: Sequence[PublicationMapRequest],
    *,
    cancel_check: Callable[[], None] | None = None,
    transaction: PublicationArtifactTransaction | None = None,
    _project_groups_validated: bool = False,
) -> list[Path]:
    """Render one condition across two independent canonical group results."""

    normalized_results = tuple(results)
    normalized_requests = tuple(requests)
    _validate_group_comparison_results(
        normalized_results,
        normalized_requests,
    )
    if not _project_groups_validated:
        validate_group_comparison_project_groups(normalized_requests)
    owns_transaction = transaction is None
    active_transaction = transaction or PublicationArtifactTransaction(
        normalized_requests[0]
    )
    try:
        for request in normalized_requests:
            active_transaction.ensure_request_target(request)
        condition, first_id, second_id = _group_comparison_identity(normalized_requests)
        first_result, second_result = normalized_results
        first_request, second_request = normalized_requests
        first_title, second_title = _group_comparison_titles(normalized_requests)
        metrics = _request_metrics(first_request)
        first_grand = first_result.grand_average_values
        second_grand = second_result.grand_average_values
        base_output = Path(first_request.output_root).expanduser().resolve(strict=False)
        rendered: list[Path] = []

        if PublicationMetric.BCA in metrics and PublicationMetric.SNR in metrics:
            ordered_metrics = tuple(
                metric for metric in COMBINED_PAIRED_METRIC_ORDER if metric in metrics
            )
            values_by_metric = {
                metric: (
                    _comparison_metric_group(
                        first_grand,
                        condition=condition,
                        group_id=first_id,
                        metric=metric,
                    ),
                    _comparison_metric_group(
                        second_grand,
                        condition=condition,
                        group_id=second_id,
                        metric=metric,
                    ),
                )
                for metric in ordered_metrics
            }
            metric_stem = "_".join(metric.value for metric in ordered_metrics)
            stem = _group_comparison_stem(
                condition=condition,
                first_id=first_id,
                second_id=second_id,
                metric_stem=metric_stem,
            )
            for suffix, enabled in (
                (".png", first_request.export_png),
                (".pdf", first_request.export_pdf),
            ):
                if not enabled:
                    continue
                _checkpoint(cancel_check)
                final_path = base_output / f"{stem}{suffix}"
                staged_path = active_transaction.stage_path(final_path)
                _render_combined_paired_topomap(
                    values_by_metric,
                    metrics=ordered_metrics,
                    first_title=first_title,
                    second_title=second_title,
                    output_path=staged_path,
                    bounds_by_metric=first_request.color_bounds,
                    dpi=first_request.png_dpi,
                    cancel_check=cancel_check,
                    figure_title=condition,
                )
                rendered.append(final_path)
        else:
            for metric in metrics:
                first_values = _comparison_metric_group(
                    first_grand,
                    condition=condition,
                    group_id=first_id,
                    metric=metric,
                )
                second_values = _comparison_metric_group(
                    second_grand,
                    condition=condition,
                    group_id=second_id,
                    metric=metric,
                )
                stem = _group_comparison_stem(
                    condition=condition,
                    first_id=first_id,
                    second_id=second_id,
                    metric_stem=metric.value,
                )
                bounds = first_request.color_bounds.get(metric, ColorBounds())
                for suffix, enabled in (
                    (".png", first_request.export_png),
                    (".pdf", first_request.export_pdf),
                ):
                    if not enabled:
                        continue
                    _checkpoint(cancel_check)
                    final_path = base_output / f"{stem}{suffix}"
                    staged_path = active_transaction.stage_path(final_path)
                    _render_paired_topomap(
                        first_values,
                        second_values,
                        metric=metric,
                        first_title=first_title,
                        second_title=second_title,
                        output_path=staged_path,
                        bounds=bounds,
                        dpi=first_request.png_dpi,
                        cancel_check=cancel_check,
                        figure_title=condition,
                    )
                    rendered.append(final_path)
        _checkpoint(cancel_check)
        if not rendered:
            raise PublicationMapInputError(
                "No two-group comparison figures were rendered."
            )
        if owns_transaction:
            active_transaction.commit(cancel_check=cancel_check)
        return rendered
    except Exception:  # Transaction boundary: discard staging for any render/cancel failure.
        if owns_transaction:
            active_transaction.abort()
        raise


def _comparison_metric_group(
    grand: pd.DataFrame,
    *,
    condition: str,
    group_id: str,
    metric: PublicationMetric,
) -> pd.DataFrame:
    selected = grand[
        (grand["condition"] == condition)
        & (grand["metric"] == metric.value)
        & (grand["is_montage_electrode"] == True)  # noqa: E712
    ]
    if selected.empty:
        raise PublicationMapInputError(
            f"Group {group_id} has no renderable {metric.display_name} values for condition {condition}."
        )
    if "group_id" in selected.columns:
        selected_ids = {
            str(value).casefold()
            for value in selected["group_id"].dropna().unique()
            if str(value).strip()
        }
        if selected_ids != {group_id.casefold()}:
            raise PublicationMapInputError(
                f"Comparison values for group {group_id} contain mismatched or pooled canonical group IDs."
            )
    return selected


def _render_publication_figures_staged(
    result: PublicationMapResult,
    request: PublicationMapRequest,
    *,
    cancel_check: Callable[[], None] | None,
) -> list[Path]:
    """Render a complete figure batch below a transaction staging root."""

    request.output_root.mkdir(parents=True, exist_ok=True)
    rendered: list[Path] = []
    grand = result.grand_average_values
    if grand.empty:
        return rendered
    _assert_unique_figure_stems(result, request)

    if request.export_paired_figures:
        rendered.extend(
            _render_paired_condition_figures(
                result,
                request,
                cancel_check=cancel_check,
            )
        )
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
            _checkpoint(cancel_check)
            png_path = request.output_root / f"{stem}.png"
            render_topomap(
                montage_group,
                metric=metric,
                title=title,
                output_path=png_path,
                bounds=bounds,
                dpi=request.png_dpi,
                cancel_check=cancel_check,
            )
            rendered.append(png_path)
        if request.export_pdf:
            _checkpoint(cancel_check)
            pdf_path = request.output_root / f"{stem}.pdf"
            render_topomap(
                montage_group,
                metric=metric,
                title=title,
                output_path=pdf_path,
                bounds=bounds,
                dpi=request.png_dpi,
                cancel_check=cancel_check,
            )
            rendered.append(pdf_path)
    return rendered


def _assert_unique_figure_stems(
    result: PublicationMapResult,
    request: PublicationMapRequest,
) -> None:
    """Reject lossy filename collisions before any staged figure is written."""

    grand = result.grand_average_values
    raw_stems: list[str] = []
    if request.export_paired_figures:
        pairs = _paired_condition_pairs(request, set(grand["condition"]))
        metrics = _request_metrics(request)
        if PublicationMetric.BCA in metrics and PublicationMetric.SNR in metrics:
            ordered = tuple(
                metric
                for metric in COMBINED_PAIRED_METRIC_ORDER
                if metric in metrics
            )
            metric_stem = "_".join(metric.value for metric in ordered)
            raw_stems.extend(
                f"{first}_and_{second}_{metric_stem}_paired"
                for first, second in pairs
            )
        else:
            raw_stems.extend(
                f"{first}_and_{second}_{metric.value}_paired"
                for metric in metrics
                for first, second in pairs
            )
    else:
        raw_stems.extend(
            f"{condition}_{metric_value}_{map_label}"
            for condition, metric_value, map_label in grand[
                ["condition", "metric", "map_label"]
            ].drop_duplicates().itertuples(index=False, name=None)
        )

    seen: dict[str, str] = {}
    for raw_stem in raw_stems:
        safe_stem = sanitize_filename_stem(raw_stem)
        prior = seen.get(safe_stem.casefold())
        if prior is not None:
            raise PublicationMapInputError(
                "Scalp Maps output names collide after Windows-safe filename "
                f"normalization: {prior!r} and {raw_stem!r}. Rename the "
                "conditions so each requested figure has a distinct name."
            )
        seen[safe_stem.casefold()] = raw_stem


def render_topomap(
    values: pd.DataFrame,
    *,
    metric: PublicationMetric,
    title: str,
    output_path: Path,
    bounds: ColorBounds = ColorBounds(),
    dpi: int = 300,
    cancel_check: Callable[[], None] | None = None,
) -> None:
    """Render one MNE topomap from grand-average values."""

    fig, ax = plt.subplots(figsize=SINGLE_MAP_FIGSIZE, dpi=dpi)
    try:
        _checkpoint(cancel_check)
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
                f"Missing montage values omitted: {missing_count}",
                transform=ax.transAxes,
                ha="center",
                va="top",
                **figure_text_kwargs("small"),
            )
        fig.tight_layout()
        _save_figure(fig, output_path, dpi=dpi, cancel_check=cancel_check)
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
    *,
    cancel_check: Callable[[], None] | None,
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
            cancel_check=cancel_check,
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
                _checkpoint(cancel_check)
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
                    cancel_check=cancel_check,
                )
                rendered.append(png_path)
            if request.export_pdf:
                _checkpoint(cancel_check)
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
                    cancel_check=cancel_check,
                )
                rendered.append(pdf_path)
    return rendered


def _render_combined_paired_condition_figures(
    result: PublicationMapResult,
    request: PublicationMapRequest,
    *,
    condition_pairs: list[tuple[str, str]],
    cancel_check: Callable[[], None] | None,
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
            _checkpoint(cancel_check)
            png_path = request.output_root / f"{stem}.png"
            _render_combined_paired_topomap(
                groups,
                metrics=metrics,
                first_title=str(first),
                second_title=str(second),
                output_path=png_path,
                bounds_by_metric=request.color_bounds,
                dpi=request.png_dpi,
                cancel_check=cancel_check,
            )
            rendered.append(png_path)
        if request.export_pdf:
            _checkpoint(cancel_check)
            pdf_path = request.output_root / f"{stem}.pdf"
            _render_combined_paired_topomap(
                groups,
                metrics=metrics,
                first_title=str(first),
                second_title=str(second),
                output_path=pdf_path,
                bounds_by_metric=request.color_bounds,
                dpi=request.png_dpi,
                cancel_check=cancel_check,
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
    cancel_check: Callable[[], None] | None,
    figure_title: str | None = None,
) -> None:
    _checkpoint(cancel_check)
    fig, axes = plt.subplots(1, 2, figsize=PAIRED_MAP_FIGSIZE, dpi=dpi)
    try:
        cmap = colormap_for_metric(metric, bounds)
        shared_vlim = _paired_vlim(
            first_values,
            second_values,
            metric=metric,
            bounds=bounds,
        )
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
        if figure_title:
            fig.suptitle(
                str(figure_title),
                y=0.98,
                **figure_text_kwargs("condition_label"),
            )
            fig.subplots_adjust(top=0.78)
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
        _save_figure(fig, output_path, dpi=dpi, cancel_check=cancel_check)
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
    cancel_check: Callable[[], None] | None,
    figure_title: str | None = None,
) -> None:
    _checkpoint(cancel_check)
    fig = plt.figure(figsize=_combined_paired_figsize(metrics), dpi=dpi)
    layout = _combined_paired_layout_rects(
        metrics=metrics,
        reserve_figure_title=bool(figure_title),
    )
    try:
        if figure_title:
            fig.suptitle(
                str(figure_title),
                y=0.985,
                **figure_text_kwargs("condition_label"),
            )
        for row_idx, metric in enumerate(metrics):
            _checkpoint(cancel_check)
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
        _save_figure(fig, output_path, dpi=dpi, cancel_check=cancel_check)
    finally:
        plt.close(fig)


def _combined_paired_layout_rects(
    *,
    metrics: tuple[PublicationMetric, ...] = (
        PublicationMetric.BCA,
        PublicationMetric.SNR,
    ),
    reserve_figure_title: bool = False,
) -> dict[PublicationMetric, dict[str, tuple[float, float, float, float]]]:
    figure_size = _combined_paired_figsize(metrics)
    map_height = COMBINED_PAIRED_MAP_WIDTH * (figure_size[0] / figure_size[1])
    if reserve_figure_title:
        top = 0.87
        bottom = 0.065
        gap = (top - bottom - (len(metrics) * map_height)) / max(len(metrics) - 1, 1)
        gap = max(gap, 0.012)
        rows = {
            metric: top - map_height - index * (map_height + gap)
            for index, metric in enumerate(metrics)
        }
    elif metrics == (PublicationMetric.BCA, PublicationMetric.SNR):
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
        f"Missing montage values omitted: {missing_count}",
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


def _save_figure(
    fig: plt.Figure,
    output_path: Path,
    *,
    dpi: int,
    cancel_check: Callable[[], None] | None = None,
) -> None:
    """Save figure with transparent backgrounds for PDF composition workflows."""

    _checkpoint(cancel_check)
    transparent = output_path.suffix.lower() == ".pdf"
    if transparent:
        fig.patch.set_alpha(0)
        for ax in fig.axes:
            ax.set_facecolor("none")
            ax.patch.set_alpha(0)
    fig.savefig(output_path, dpi=dpi, transparent=transparent)
    _checkpoint(cancel_check)


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


def _checkpoint(cancel_check: Callable[[], None] | None) -> None:
    if cancel_check is not None:
        cancel_check()
