"""Metric builders for publication scalp maps."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from functools import partial
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from Main_App.projects import (
    DatasetDiagnostic,
    DatasetIndexError,
    ProjectDatasetIndex,
    WorkbookRecord,
)
from Main_App.processing.frequency_domain_qc import (
    FREQUENCY_DOMAIN_QC_METHOD_VERSION,
    active_frequency_domain_exclusions,
)
from Tools.Stats.analysis.canonical_harmonics import load_project_processing_harmonics
from Tools.Publication_Maps.excel_inputs import (
    ELECTRODE_COLUMN,
    load_publication_dataset_index,
    select_publication_workbooks,
)
from Tools.Publication_Maps.models import (
    Diagnostic,
    ExcludedCohortEntry,
    PublicationMapCohortError,
    PublicationMapInputError,
    PublicationMapRequest,
    PublicationMapResult,
    PublicationMetric,
    WorkbookEntry,
)
from Tools.Publication_Maps.scalp_io import biosemi64_names_upper, normalize_electrode_name
from Tools.Publication_Maps.xlsx_metric_reader import read_metric_sheet_selected_columns

LONG_COLUMNS = [
    "condition",
    "group_id",
    "group_label",
    "group_folder",
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
    "group_id",
    "group_label",
    "group_folder",
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

_FATAL_DATASET_DIAGNOSTIC_CODES = frozenset(
    {
        "unassigned_participant",
        "unresolved_condition",
        "unresolved_participant",
    }
)
_CONDITION_SCOPED_FATAL_DATASET_DIAGNOSTIC_CODES = frozenset(
    {
        "unassigned_participant",
        "unresolved_participant",
    }
)
_HASH_CHUNK_BYTES = 1024 * 1024


def build_publication_map_result(
    request: PublicationMapRequest,
    *,
    cancel_check: Callable[[], None] | None = None,
) -> PublicationMapResult:
    """Build selected metric frames using Stats-selected harmonics."""

    _cancellation_checkpoint(cancel_check)
    diagnostics: list[Diagnostic] = []
    requested_metrics = _request_metrics(request)
    frequency_exclusions = active_frequency_domain_exclusions(request.project_root)
    qc_provenance = _applied_frequency_exclusion_provenance(frequency_exclusions)
    _cancellation_checkpoint(cancel_check)
    request_subject_exclusions = {
        str(subject).strip().upper() for subject in request.subject_exclusions if str(subject).strip()
    }
    frequency_subject_exclusions = {
        str(subject).strip().upper() for subject in frequency_exclusions.excluded_participants if str(subject).strip()
    }
    subject_exclusions = request_subject_exclusions | frequency_subject_exclusions
    try:
        dataset_index = load_publication_dataset_index(
            request.input_root,
            project_root=request.project_root,
        )
    except DatasetIndexError as exc:
        raise PublicationMapCohortError(f"Unable to index Scalp Maps workbooks: {exc}") from exc
    _cancellation_checkpoint(cancel_check)
    dataset_diagnostics = _dataset_diagnostics(
        dataset_index,
        conditions=request.conditions,
    )
    diagnostics.extend(dataset_diagnostics)
    fatal_diagnostics = [
        diagnostic
        for diagnostic in dataset_diagnostics
        if diagnostic.code in _FATAL_DATASET_DIAGNOSTIC_CODES and diagnostic.level == "error"
    ]
    if fatal_diagnostics:
        detail = "; ".join(f"{diagnostic.code}: {diagnostic.message}" for diagnostic in fatal_diagnostics)
        raise PublicationMapCohortError("Scalp Maps cannot use an unassigned or ambiguous workbook cohort. " + detail)
    try:
        workbooks, group = select_publication_workbooks(
            dataset_index,
            request.conditions,
            excluded_subjects=subject_exclusions,
            group_id=request.group_id,
            group_label=request.group_label,
            group_folder=request.group_folder,
            session_ids=request.session_ids or None,
        )
    except DatasetIndexError as exc:
        raise PublicationMapCohortError(str(exc)) from exc
    group_id = None if group is None else group.group_id
    group_label = None if group is None else group.label
    group_folder = None if group is None else group.folder_name
    excluded_cohort = _excluded_cohort_entries(
        dataset_index,
        conditions=request.conditions,
        group_id=group_id,
        group_folder=group_folder,
        request_subject_exclusions=request_subject_exclusions,
        frequency_subject_exclusions=frequency_subject_exclusions,
    )
    diagnostics.extend(_excluded_cohort_diagnostics(excluded_cohort))

    _cancellation_checkpoint(cancel_check)
    selected_harmonics, selection_metadata = _select_stats_significant_harmonics(
        request=request,
        diagnostics=diagnostics,
    )
    _cancellation_checkpoint(cancel_check)
    workbooks = _capture_workbook_identities(
        workbooks,
        cancel_check=cancel_check,
    )
    long_rows: list[dict[str, object]] = []
    for metric in requested_metrics:
        _cancellation_checkpoint(cancel_check)
        long_rows.extend(
            _collect_metric_rows(
                metric=metric,
                workbooks=list(workbooks),
                harmonics_hz=selected_harmonics,
                diagnostics=diagnostics,
                excluded_electrodes_by_subject=frequency_exclusions.auto_excluded_electrodes_by_participant,
                cancel_check=cancel_check,
            )
        )
    verify_publication_workbooks_unchanged(workbooks, cancel_check=cancel_check)
    long_df = pd.DataFrame(long_rows, columns=LONG_COLUMNS)
    if long_df.empty:
        raise PublicationMapInputError("No exact electrode values were available from the requested workbooks.")
    grand_df = _build_grand_average_frame(
        long_df,
        selected_harmonics,
        cancel_check=cancel_check,
    )
    if grand_df.empty:
        raise PublicationMapInputError("No renderable scalp-map values were found.")
    _cancellation_checkpoint(cancel_check)
    return PublicationMapResult(
        long_values=long_df,
        grand_average_values=grand_df,
        diagnostics=diagnostics,
        selected_harmonics_hz=selected_harmonics,
        selection_metadata=selection_metadata,
        group_id=group_id,
        group_label=group_label,
        group_folder=group_folder,
        included_workbooks=workbooks,
        excluded_cohort=excluded_cohort,
        qc_provenance=qc_provenance,
    )


def _cancellation_checkpoint(cancel_check: Callable[[], None] | None) -> None:
    if cancel_check is not None:
        cancel_check()


def _applied_frequency_exclusion_provenance(exclusions: object) -> dict[str, object]:
    """Freeze the exact QC exclusions applied to this numerical result."""

    applied: dict[str, object] = {
        "method_version": FREQUENCY_DOMAIN_QC_METHOD_VERSION,
        "excluded_participants": sorted(str(value) for value in exclusions.excluded_participants),
        "auto_excluded_participants": sorted(str(value) for value in exclusions.auto_excluded_participants),
        "manual_excluded_participants": sorted(str(value) for value in exclusions.manual_excluded_participants),
        "auto_excluded_electrodes_by_participant": {
            str(participant_id): sorted(str(value) for value in electrodes)
            for participant_id, electrodes in sorted(
                exclusions.auto_excluded_electrodes_by_participant.items(),
                key=lambda item: str(item[0]).casefold(),
            )
        },
        "downstream_outputs_stale": bool(exclusions.downstream_outputs_stale),
    }
    applied["auto_participant_exclusion_n"] = len(applied["auto_excluded_participants"])
    applied["manual_participant_exclusion_n"] = len(applied["manual_excluded_participants"])
    applied["auto_participant_electrode_exclusion_n"] = sum(
        len(electrodes) for electrodes in applied["auto_excluded_electrodes_by_participant"].values()
    )
    encoded = json.dumps(
        applied,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    applied["applied_exclusions_sha256"] = hashlib.sha256(encoded).hexdigest()
    return applied


def _capture_workbook_identities(
    workbooks: tuple[WorkbookEntry, ...],
    *,
    cancel_check: Callable[[], None] | None,
) -> tuple[WorkbookEntry, ...]:
    return tuple(_capture_workbook_identity(workbook, cancel_check=cancel_check) for workbook in workbooks)


def _capture_workbook_identity(
    workbook: WorkbookEntry,
    *,
    cancel_check: Callable[[], None] | None,
) -> WorkbookEntry:
    _cancellation_checkpoint(cancel_check)
    try:
        before = workbook.path.stat()
        before_signature = (
            int(before.st_dev),
            int(before.st_ino),
            int(before.st_size),
            int(before.st_mtime_ns),
        )
        digest = hashlib.sha256()
        with workbook.path.open("rb") as stream:
            while True:
                _cancellation_checkpoint(cancel_check)
                chunk = stream.read(_HASH_CHUNK_BYTES)
                if not chunk:
                    break
                digest.update(chunk)
        after = workbook.path.stat()
        after_signature = (
            int(after.st_dev),
            int(after.st_ino),
            int(after.st_size),
            int(after.st_mtime_ns),
        )
    except OSError as exc:
        raise PublicationMapInputError(f"Unable to fingerprint active workbook {workbook.path.name}: {exc}") from exc
    if before_signature != after_signature:
        raise PublicationMapInputError(
            f"Active workbook changed while its input fingerprint was captured: "
            f"{workbook.path.name}. Restart Scalp Maps after workbook writes finish."
        )
    return replace(
        workbook,
        sha256=digest.hexdigest(),
        size_bytes=after_signature[2],
        mtime_ns=after_signature[3],
    )


def verify_publication_workbooks_unchanged(
    workbooks: tuple[WorkbookEntry, ...],
    *,
    cancel_check: Callable[[], None] | None = None,
) -> None:
    """Reject source workbooks changed since their analysis-time snapshot."""

    for workbook in workbooks:
        current = _capture_workbook_identity(
            workbook,
            cancel_check=cancel_check,
        )
        if (
            current.sha256 != workbook.sha256
            or current.size_bytes != workbook.size_bytes
            or current.mtime_ns != workbook.mtime_ns
        ):
            raise PublicationMapInputError(
                f"Active workbook changed while Scalp Maps data were being read: "
                f"{workbook.path.name}. Restart generation after workbook writes "
                "finish."
            )


def _dataset_diagnostics(
    index: ProjectDatasetIndex,
    *,
    conditions: tuple[str, ...],
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    for row in index.diagnostics:
        diagnostic_conditions = _dataset_diagnostic_conditions(index, row)
        is_fatal = _dataset_diagnostic_is_fatal(
            row,
            diagnostic_conditions=diagnostic_conditions,
            requested_conditions=conditions,
        )
        if is_fatal:
            level = "error"
        elif row.code == "excluded_participant_condition":
            level = "info"
        else:
            level = "warning"
        diagnostics.append(
            Diagnostic(
                level=level,
                code=row.code,
                condition=", ".join(diagnostic_conditions),
                workbook=", ".join(path.name for path in row.paths[:4]),
                message=row.message,
                detail="; ".join(_dataset_diagnostic_path_identity(index, path) for path in row.paths),
            )
        )
    return diagnostics


def _dataset_diagnostic_path_identity(
    index: ProjectDatasetIndex,
    path: Path,
) -> str:
    """Return a portable diagnostic path without leaking the machine root."""

    resolved = path.resolve(strict=False)
    try:
        return resolved.relative_to(index.project_root.resolve(strict=False)).as_posix()
    except (OSError, ValueError):
        return f"external:{resolved.name}"


def _dataset_diagnostic_conditions(
    index: ProjectDatasetIndex,
    row: DatasetDiagnostic,
) -> tuple[str, ...]:
    """Return condition folder identities represented by one index diagnostic."""

    excel_root = index.excel_root.resolve(strict=False)
    condition_names: list[str] = []
    for path in row.paths:
        try:
            relative = path.resolve(strict=False).relative_to(excel_root)
        except (OSError, ValueError):
            continue
        if len(relative.parts) < 2:
            continue
        condition = relative.parts[0]
        if condition.casefold() not in {value.casefold() for value in condition_names}:
            condition_names.append(condition)
    return tuple(condition_names)


def _dataset_diagnostic_is_fatal(
    row: DatasetDiagnostic,
    *,
    diagnostic_conditions: tuple[str, ...],
    requested_conditions: tuple[str, ...],
) -> bool:
    if row.code not in _FATAL_DATASET_DIAGNOSTIC_CODES:
        return False
    if row.code not in _CONDITION_SCOPED_FATAL_DATASET_DIAGNOSTIC_CODES:
        return True
    if not diagnostic_conditions:
        return True
    requested = {str(condition).strip().casefold() for condition in requested_conditions if str(condition).strip()}
    return any(condition.casefold() in requested for condition in diagnostic_conditions)


def _excluded_cohort_entries(
    index: ProjectDatasetIndex,
    *,
    conditions: tuple[str, ...],
    group_id: str | None,
    group_folder: str | None,
    request_subject_exclusions: set[str],
    frequency_subject_exclusions: set[str],
) -> tuple[ExcludedCohortEntry, ...]:
    condition_keys = {str(condition).strip().casefold() for condition in conditions}

    def selected_scope(record: WorkbookRecord) -> bool:
        if record.condition.casefold() not in condition_keys:
            return False
        if group_id is None:
            return record.group_id is None
        return record.group_id is not None and record.group_id.casefold() == group_id.casefold()

    excluded: list[ExcludedCohortEntry] = []
    for record in index.excluded_workbooks:
        if not selected_scope(record):
            continue
        excluded.append(
            ExcludedCohortEntry(
                participant_id=record.participant_id,
                condition=record.condition,
                reason="project participant-condition exclusion",
                path=record.path,
                group_id=record.group_id,
                group_label=record.group_label,
                group_folder=group_folder,
            )
        )
    for record in index.workbooks:
        if not selected_scope(record):
            continue
        participant_id = record.participant_id.upper()
        reasons: list[str] = []
        if participant_id in request_subject_exclusions:
            reasons.append("request participant exclusion")
        if participant_id in frequency_subject_exclusions:
            reasons.append("frequency-domain participant exclusion")
        if not reasons:
            continue
        excluded.append(
            ExcludedCohortEntry(
                participant_id=record.participant_id,
                condition=record.condition,
                reason="; ".join(reasons),
                path=record.path,
                group_id=record.group_id,
                group_label=record.group_label,
                group_folder=group_folder,
            )
        )
    return tuple(
        sorted(
            excluded,
            key=lambda row: (
                row.condition.casefold(),
                row.participant_id.casefold(),
                "" if row.path is None else str(row.path).casefold(),
            ),
        )
    )


def _excluded_cohort_diagnostics(
    excluded: tuple[ExcludedCohortEntry, ...],
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    for row in excluded:
        if row.reason == "project participant-condition exclusion":
            continue
        diagnostics.append(
            Diagnostic(
                level="info",
                code="excluded_participant",
                condition=row.condition,
                workbook="" if row.path is None else row.path.name,
                message=f"Excluded {row.participant_id} from Scalp Maps.",
                detail=row.reason,
            )
        )
    return diagnostics


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
    diagnostics: list[Diagnostic],
) -> tuple[tuple[float, ...], dict[str, object]]:
    def log_func(message: str) -> None:
        diagnostics.append(Diagnostic(level="info", message=message))

    selection = load_project_processing_harmonics(
        project_root=request.project_root,
        log_func=log_func,
    )
    metadata = dict(selection.metadata)
    metadata.setdefault(
        "selection_fingerprint",
        selection.fingerprint.get("selection_fingerprint", ""),
    )
    metadata.setdefault("selection_fingerprint_text", selection.fingerprint_text)
    selected = tuple(round(float(value), 4) for value in selection.selected_harmonics_hz)
    diagnostics.append(
        Diagnostic(
            level="info",
            message="Processing-time significant harmonics loaded for scalp maps.",
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
    excluded_electrodes_by_subject: dict[str, frozenset[str]],
    cancel_check: Callable[[], None] | None = None,
) -> list[dict[str, object]]:
    montage_names = biosemi64_names_upper()
    rows: list[dict[str, object]] = []
    source_sheet = metric.source_sheet
    selected_columns = [f"{float(freq):.4f}_Hz" for freq in harmonics_hz]
    required_columns = [ELECTRODE_COLUMN, *selected_columns]
    for workbook in workbooks:
        _cancellation_checkpoint(cancel_check)
        try:
            df_metric = read_metric_sheet_selected_columns(
                workbook.path,
                sheet_name=source_sheet,
                required_columns=required_columns,
            )
        except Exception as exc:
            raise PublicationMapInputError(
                f"Unable to read requested {source_sheet} sheet from "
                f"{workbook.path.name} ({workbook.subject_id} / "
                f"{workbook.condition}): {exc}"
            ) from exc
        _cancellation_checkpoint(cancel_check)
        if df_metric.empty:
            raise PublicationMapInputError(
                f"Requested {source_sheet} sheet is empty in "
                f"{workbook.path.name} ({workbook.subject_id} / "
                f"{workbook.condition})."
            )
        if ELECTRODE_COLUMN not in df_metric.columns:
            raise PublicationMapInputError(
                f"Missing Electrode column in requested {source_sheet} sheet: "
                f"{workbook.path.name} ({workbook.subject_id} / "
                f"{workbook.condition})."
            )
        missing_columns = [column for column in selected_columns if column not in df_metric.columns]
        if missing_columns:
            raise PublicationMapInputError(
                f"Missing exact selected {metric.display_name} harmonic columns "
                f"in {workbook.path.name} ({workbook.subject_id} / "
                f"{workbook.condition}): {', '.join(missing_columns)}"
            )
        normalized_electrodes = df_metric[ELECTRODE_COLUMN].map(normalize_electrode_name)
        duplicate_electrodes = sorted(
            set(normalized_electrodes[normalized_electrodes.ne("") & normalized_electrodes.duplicated(keep=False)]),
            key=str.casefold,
        )
        if duplicate_electrodes:
            raise PublicationMapInputError(
                f"Duplicate normalized electrode rows in requested {source_sheet} "
                f"sheet: {workbook.path.name} ({workbook.subject_id} / "
                f"{workbook.condition}): {', '.join(duplicate_electrodes)}. "
                "Each electrode must appear exactly once."
            )
        excluded_electrodes = excluded_electrodes_by_subject.get(
            workbook.subject_id.upper(),
            frozenset(),
        )
        if excluded_electrodes:
            df_metric = df_metric.loc[~normalized_electrodes.astype(str).str.upper().isin(excluded_electrodes)].copy()
        active_electrodes = df_metric[ELECTRODE_COLUMN].map(normalize_electrode_name)
        montage_rows = df_metric.loc[active_electrodes.isin(montage_names)]
        numeric_values = montage_rows[selected_columns].apply(
            pd.to_numeric,
            errors="coerce",
        )
        finite_values = numeric_values.to_numpy(dtype=float, na_value=np.nan)
        if finite_values.size == 0 or not np.isfinite(finite_values).any():
            raise PublicationMapInputError(
                f"No finite BioSemi64 values remain in requested {source_sheet} "
                f"sheet for the selected harmonics: {workbook.path.name} "
                f"({workbook.subject_id} / {workbook.condition}). Check blank or "
                "nonnumeric cells and frequency-domain electrode exclusions."
            )
        unmapped = sorted(
            {
                normalize_electrode_name(electrode)
                for electrode in df_metric[ELECTRODE_COLUMN]
                if normalize_electrode_name(electrode) and normalize_electrode_name(electrode) not in montage_names
            }
        )
        if unmapped:
            diagnostics.append(
                Diagnostic(
                    level="warning",
                    code="unmapped_electrode",
                    condition=workbook.condition,
                    workbook=workbook.path.name,
                    message="Workbook contains electrodes outside BioSemi64 montage.",
                    detail=", ".join(unmapped[:12]),
                )
            )
        workbook_row_count = len(rows)
        for harmonic in harmonics_hz:
            _cancellation_checkpoint(cancel_check)
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
                    group_id=workbook.group_id,
                    group_label=workbook.group_label,
                    group_folder=workbook.group_folder,
                    cancel_check=cancel_check,
                )
            )
        if len(rows) == workbook_row_count:
            raise PublicationMapInputError(
                f"No electrode rows were available in requested {source_sheet} "
                f"sheet: {workbook.path.name} ({workbook.subject_id} / "
                f"{workbook.condition})."
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
    group_id: str | None = None,
    group_label: str | None = None,
    group_folder: str | None = None,
    cancel_check: Callable[[], None] | None = None,
) -> list[dict[str, object]]:
    _cancellation_checkpoint(cancel_check)
    values = pd.to_numeric(df[source_column], errors="coerce")
    rows: list[dict[str, object]] = []
    for original_electrode, value in zip(df[ELECTRODE_COLUMN], values):
        electrode = normalize_electrode_name(original_electrode)
        if not electrode:
            continue
        rows.append(
            {
                "condition": condition,
                "group_id": group_id,
                "group_label": group_label,
                "group_folder": group_folder,
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
    _cancellation_checkpoint(cancel_check)
    return rows


def _build_grand_average_frame(
    long_df: pd.DataFrame,
    selected_harmonics_hz: tuple[float, ...],
    *,
    cancel_check: Callable[[], None] | None = None,
) -> pd.DataFrame:
    _cancellation_checkpoint(cancel_check)
    if long_df.empty:
        return pd.DataFrame(columns=GRAND_COLUMNS)
    metric_df = long_df.copy()
    metric_df["value"] = pd.to_numeric(metric_df["value"], errors="coerce")
    frames: list[pd.DataFrame] = []
    for metric_value, group in metric_df.groupby("metric", dropna=False):
        _cancellation_checkpoint(cancel_check)
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
                [
                    "condition",
                    "group_id",
                    "group_label",
                    "group_folder",
                    "subject_id",
                    "electrode",
                    "is_montage_electrode",
                ],
                dropna=False,
            )["value"]
            .agg(subject_aggregator)
            .reset_index(name="subject_value")
        )
        grouped = (
            subject_values.groupby(
                [
                    "condition",
                    "group_id",
                    "group_label",
                    "group_folder",
                    "electrode",
                    "is_montage_electrode",
                ],
                dropna=False,
            )["subject_value"]
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
        _cancellation_checkpoint(cancel_check)
    if not frames:
        return pd.DataFrame(columns=GRAND_COLUMNS)
    result = pd.concat(frames, ignore_index=True)[GRAND_COLUMNS]
    _cancellation_checkpoint(cancel_check)
    return result


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
