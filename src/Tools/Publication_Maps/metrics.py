"""Metric builders for publication scalp maps."""

from __future__ import annotations

from functools import partial
from pathlib import Path

import numpy as np
import pandas as pd

from Tools.Stats.analysis.dv_policy_group_significant import (
    build_group_significant_harmonic_selection,
)
from Tools.Stats.analysis.dv_policy_settings import DVPolicySettings
from Tools.Publication_Maps.excel_inputs import (
    ELECTRODE_COLUMN,
    discover_workbooks,
)
from Tools.Publication_Maps.models import (
    Diagnostic,
    PublicationMapRequest,
    PublicationMapResult,
    PublicationMetric,
    WorkbookEntry,
)
from Tools.Publication_Maps.scalp_io import biosemi64_names_upper, normalize_electrode_name
from Tools.Publication_Maps.xlsx_metric_reader import read_metric_sheet_selected_columns

LONG_COLUMNS = [
    "condition",
    "subject_id",
    "workbook_path",
    "electrode",
    "original_electrode",
    "is_montage_electrode",
    "metric",
    "metric_label",
    "harmonic_hz",
    "source_sheet",
    "source_column",
    "source_column_hz",
    "exact_column_label",
    "value",
]

GRAND_COLUMNS = [
    "condition",
    "electrode",
    "is_montage_electrode",
    "metric",
    "metric_label",
    "map_harmonic_hz",
    "map_label",
    "selected_harmonics_hz",
    "aggregate_value",
    "render_value",
    "valid_subject_count",
]


def build_publication_map_result(request: PublicationMapRequest) -> PublicationMapResult:
    """Build selected metric frames using Stats-selected harmonics."""

    diagnostics: list[Diagnostic] = []
    requested_metrics = _request_metrics(request)
    workbooks = discover_workbooks(
        request.input_root,
        request.conditions,
        excluded_subjects=request.subject_exclusions,
    )
    if not workbooks:
        diagnostics.append(
            Diagnostic(
                level="error",
                message="No Excel workbooks were found for the selected conditions.",
                detail=str(request.input_root),
            )
        )
        return PublicationMapResult(
            long_values=pd.DataFrame(columns=LONG_COLUMNS),
            grand_average_values=pd.DataFrame(columns=GRAND_COLUMNS),
            diagnostics=diagnostics,
        )

    selected_harmonics, selection_metadata = _select_stats_significant_harmonics(
        request=request,
        workbooks=workbooks,
        diagnostics=diagnostics,
    )
    long_rows: list[dict[str, object]] = []
    for metric in requested_metrics:
        long_rows.extend(
            _collect_metric_rows(
                metric=metric,
                workbooks=workbooks,
                harmonics_hz=selected_harmonics,
                diagnostics=diagnostics,
            )
        )
    long_df = pd.DataFrame(long_rows, columns=LONG_COLUMNS)
    grand_df = _build_grand_average_frame(long_df, selected_harmonics)
    if grand_df.empty and not any(diag.level == "error" for diag in diagnostics):
        diagnostics.append(Diagnostic(level="error", message="No renderable scalp-map values were found."))
    return PublicationMapResult(
        long_values=long_df,
        grand_average_values=grand_df,
        diagnostics=diagnostics,
        selected_harmonics_hz=selected_harmonics,
        selection_metadata=selection_metadata,
    )


def _request_metrics(request: PublicationMapRequest) -> tuple[PublicationMetric, ...]:
    metrics: list[PublicationMetric] = []
    for metric in request.metrics:
        normalized = PublicationMetric(metric)
        if normalized not in metrics:
            metrics.append(normalized)
    return tuple(metrics) or (PublicationMetric.BCA,)


def _select_stats_significant_harmonics(
    *,
    request: PublicationMapRequest,
    workbooks: list[WorkbookEntry],
    diagnostics: list[Diagnostic],
) -> tuple[tuple[float, ...], dict[str, object]]:
    subject_data: dict[str, dict[str, str]] = {}
    for workbook in workbooks:
        subject_data.setdefault(workbook.subject_id, {})[workbook.condition] = str(workbook.path)
    subjects = sorted(subject_data)
    conditions = list(request.conditions)
    rois = {"All scalp electrodes": sorted(biosemi64_names_upper())}

    def log_func(message: str) -> None:
        diagnostics.append(Diagnostic(level="info", message=message))

    selection = build_group_significant_harmonic_selection(
        subjects=subjects,
        conditions=conditions,
        subject_data=subject_data,
        base_frequency_hz=float(request.base_frequency_hz),
        rois=rois,
        log_func=log_func,
        settings=DVPolicySettings(),
        max_freq=request.max_frequency_hz,
        project_root=request.project_root,
    )
    metadata = selection.to_metadata()
    selected = tuple(round(float(value), 4) for value in selection.selected_harmonics_hz)
    diagnostics.append(
        Diagnostic(
            level="info",
            message="Stats group-significant harmonics selected for scalp maps.",
            detail=", ".join(f"{freq:g} Hz" for freq in selected),
        )
    )
    return selected, metadata


def _collect_metric_rows(
    *,
    metric: PublicationMetric,
    workbooks: list[WorkbookEntry],
    harmonics_hz: tuple[float, ...],
    diagnostics: list[Diagnostic],
) -> list[dict[str, object]]:
    montage_names = biosemi64_names_upper()
    rows: list[dict[str, object]] = []
    source_sheet = metric.source_sheet
    selected_columns = [f"{float(freq):.4f}_Hz" for freq in harmonics_hz]
    required_columns = [ELECTRODE_COLUMN, *selected_columns]
    for workbook in workbooks:
        try:
            df_metric = read_metric_sheet_selected_columns(
                workbook.path,
                sheet_name=source_sheet,
                required_columns=required_columns,
            )
        except Exception as exc:
            diagnostics.append(
                Diagnostic(
                    level="error",
                    condition=workbook.condition,
                    workbook=workbook.path.name,
                    message=f"Failed reading sheet: {source_sheet}.",
                    detail=str(exc),
                )
            )
            continue
        if ELECTRODE_COLUMN not in df_metric.columns:
            diagnostics.append(
                Diagnostic(
                    level="error",
                    condition=workbook.condition,
                    workbook=workbook.path.name,
                    message=f"Missing Electrode column in {source_sheet}.",
                )
            )
            continue
        missing_columns = [column for column in selected_columns if column not in df_metric.columns]
        if missing_columns:
            diagnostics.append(
                Diagnostic(
                    level="error",
                    condition=workbook.condition,
                    workbook=workbook.path.name,
                    message=f"Missing exact selected {metric.display_name} harmonic columns.",
                    detail=", ".join(missing_columns[:8]),
                )
            )
            continue
        unmapped = sorted(
            {
                normalize_electrode_name(electrode)
                for electrode in df_metric[ELECTRODE_COLUMN]
                if normalize_electrode_name(electrode)
                and normalize_electrode_name(electrode) not in montage_names
            }
        )
        if unmapped:
            diagnostics.append(
                Diagnostic(
                    level="warning",
                    condition=workbook.condition,
                    workbook=workbook.path.name,
                    message="Workbook contains electrodes outside BioSemi64 montage.",
                    detail=", ".join(unmapped[:12]),
                )
            )
        for harmonic in harmonics_hz:
            source_column = f"{float(harmonic):.4f}_Hz"
            rows.extend(
                _rows_for_frequency(
                    df=df_metric,
                    metric=metric,
                    source_sheet=source_sheet,
                    workbook_path=workbook.path,
                    condition=workbook.condition,
                    subject_id=workbook.subject_id,
                    source_column=source_column,
                    harmonic_hz=harmonic,
                    montage_names=montage_names,
                )
            )
    return rows


def _rows_for_frequency(
    *,
    df: pd.DataFrame,
    metric: PublicationMetric,
    source_sheet: str,
    workbook_path: Path,
    condition: str,
    subject_id: str,
    source_column: str,
    harmonic_hz: float,
    montage_names: frozenset[str],
) -> list[dict[str, object]]:
    values = pd.to_numeric(df[source_column], errors="coerce")
    rows: list[dict[str, object]] = []
    for original_electrode, value in zip(df[ELECTRODE_COLUMN], values):
        electrode = normalize_electrode_name(original_electrode)
        if not electrode:
            continue
        rows.append(
            {
                "condition": condition,
                "subject_id": subject_id,
                "workbook_path": str(workbook_path),
                "electrode": electrode,
                "original_electrode": original_electrode,
                "is_montage_electrode": electrode in montage_names,
                "metric": metric.value,
                "metric_label": metric.display_name,
                "harmonic_hz": round(float(harmonic_hz), 4),
                "source_sheet": source_sheet,
                "source_column": source_column,
                "source_column_hz": round(float(harmonic_hz), 4),
                "exact_column_label": True,
                "value": float(value) if pd.notna(value) else np.nan,
            }
        )
    return rows


def _build_grand_average_frame(
    long_df: pd.DataFrame,
    selected_harmonics_hz: tuple[float, ...],
) -> pd.DataFrame:
    if long_df.empty:
        return pd.DataFrame(columns=GRAND_COLUMNS)
    metric_df = long_df.copy()
    metric_df["value"] = pd.to_numeric(metric_df["value"], errors="coerce")
    frames: list[pd.DataFrame] = []
    for metric_value, group in metric_df.groupby("metric", dropna=False):
        metric = PublicationMetric(metric_value)
        if metric is PublicationMetric.BCA:
            subject_aggregator = _safe_sum
        elif metric is PublicationMetric.Z_SCORE:
            subject_aggregator = partial(
                _safe_normalized_sum,
                harmonic_count=len(selected_harmonics_hz),
            )
        else:
            subject_aggregator = _safe_mean
        subject_values = (
            group.groupby(
                ["condition", "subject_id", "electrode", "is_montage_electrode"],
                dropna=False,
            )["value"]
            .agg(subject_aggregator)
            .reset_index(name="subject_value")
        )
        grouped = (
            subject_values.groupby(["condition", "electrode", "is_montage_electrode"], dropna=False)[
                "subject_value"
            ]
            .agg(aggregate_value=_safe_mean, valid_subject_count=_finite_count)
            .reset_index()
        )
        grouped["metric"] = metric.value
        grouped["metric_label"] = metric.display_name
        grouped["map_harmonic_hz"] = np.nan
        grouped["map_label"] = _map_label(metric)
        grouped["selected_harmonics_hz"] = ", ".join(f"{freq:g}" for freq in selected_harmonics_hz)
        if metric is PublicationMetric.BCA:
            grouped["render_value"] = grouped["aggregate_value"].clip(lower=0)
        else:
            grouped["render_value"] = grouped["aggregate_value"]
        frames.append(grouped[GRAND_COLUMNS])
    if not frames:
        return pd.DataFrame(columns=GRAND_COLUMNS)
    return pd.concat(frames, ignore_index=True)[GRAND_COLUMNS]


def _map_label(metric: PublicationMetric) -> str:
    if metric is PublicationMetric.Z_SCORE:
        return "Z-score significant-harmonic sum"
    if metric is PublicationMetric.SNR:
        return "SNR significant-harmonic mean"
    return "BCA significant-harmonic sum"


def _safe_sum(values: pd.Series) -> float:
    numeric = pd.to_numeric(values, errors="coerce")
    finite = numeric[np.isfinite(numeric)]
    return float(finite.sum()) if len(finite) else float("nan")


def _safe_normalized_sum(values: pd.Series, *, harmonic_count: int) -> float:
    numeric = pd.to_numeric(values, errors="coerce")
    finite = numeric[np.isfinite(numeric)]
    if harmonic_count <= 0 or len(finite) != harmonic_count:
        return float("nan")
    return float(finite.sum() / np.sqrt(float(harmonic_count)))


def _safe_mean(values: pd.Series) -> float:
    numeric = pd.to_numeric(values, errors="coerce")
    finite = numeric[np.isfinite(numeric)]
    return float(finite.mean()) if len(finite) else float("nan")


def _finite_count(values: pd.Series) -> int:
    numeric = pd.to_numeric(values, errors="coerce")
    return int(np.isfinite(numeric).sum())
