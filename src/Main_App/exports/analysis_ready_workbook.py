"""Full-audit, analysis-ready Summed BCA workbook export.

The export deliberately preserves every observed canonical processed workbook,
including records that the Toolbox currently excludes from downstream analyses.
Exclusions and data-quality concerns are represented as flags so that an
external analyst can make an independent decision without reconstructing the
processed data.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import tempfile
from collections.abc import Callable, Mapping, Sequence
from copy import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from Main_App.io import read_xlsx_sheet_selected_columns
from Main_App.processing.frequency_domain_qc import load_frequency_domain_qc_state
from Main_App.processing.roi_coverage import (
    ROI_VALUE_AVAILABLE,
    RecordingConditionRoiCoverage,
    RoiCoverageLedger,
    require_canonical_released_dataset_index,
    require_project_final_release,
)
from Main_App.projects import (
    ProjectDatasetIndex,
    STATS_SUBFOLDER_NAME,
    normalize_manual_excluded_participant_conditions,
    normalize_manual_excluded_participants,
    normalize_manual_excluded_recording_conditions,
    normalize_manual_excluded_recordings,
)
from Tools.Stats.io.harmonic_selection_export import (
    build_harmonic_selection_frames,
)

logger = logging.getLogger(__name__)

ANALYSIS_READY_WORKBOOK_NAME = "Analysis_Ready_Summed_BCA_Full_Audit.xlsx"
ANALYSIS_READY_RELATIVE_PATH = Path(STATS_SUBFOLDER_NAME) / ANALYSIS_READY_WORKBOOK_NAME
_SINGLE_GROUP_LABEL = "single group"

ROI_LONG_SHEET = "ROI Long"
RAW_WIDE_SHEET = "Raw BCA Wide"
RMS_WIDE_SHEET = "RMS Normalized Wide"
SIGNED_MEAN_WIDE_SHEET = "Signed Mean Normalized Wide"
ELECTRODE_LONG_SHEET = "Electrode Long"
WHOLE_SCALP_SHEET = "Whole Scalp Values"
RMS_HARMONIC_SCALES_SHEET = "RMS Harmonic Scales"
QC_FLAGS_SHEET = "QC Flags"
ROI_DEFINITIONS_SHEET = "ROI Definitions"
ROI_COVERAGE_SHEET = "ROI Coverage"
SELECTION_SUMMARY_SHEET = "Selection Summary"
HARMONIC_SELECTION_SHEET = "Harmonic Selection"
ANALYSIS_NOTES_SHEET = "Analysis Notes"

_ROI_LONG_COLUMNS = [
    "PID",
    "Group",
    "Condition",
    "ROI",
    "Raw Summed BCA",
    "RMS Normalized BCA",
    "Signed Mean Normalized BCA",
    "Current Toolbox Exclusion",
    "QC Flag",
    "QC Notes",
]
_ELECTRODE_LONG_COLUMNS = [
    "PID",
    "Group",
    "Condition",
    "Electrode",
    "Raw Summed BCA",
    "RMS Normalized BCA",
    "Signed Mean Normalized BCA",
    "Current Toolbox Exclusion",
    "QC Flag",
    "QC Notes",
]
_WHOLE_SCALP_COLUMNS = [
    "PID",
    "Group",
    "Condition",
    "Source Electrode Count",
    "Finite Summed BCA Electrode Count",
    "Descriptive Post-Sum RMS (Not Used for Normalization)",
    "Whole Scalp Signed Mean Summed BCA",
    "Current Toolbox Exclusion",
    "QC Flag",
    "QC Notes",
]
_RMS_HARMONIC_SCALE_COLUMNS = [
    "PID",
    "Group",
    "Condition",
    "Harmonic (Hz)",
    "Source Electrode Count",
    "Finite Electrode Count",
    "Scalp Vector Length",
    "Used for RMS Normalization",
    "Current Toolbox Exclusion",
    "QC Notes",
]
_QC_FLAG_COLUMNS = [
    "PID",
    "Group",
    "Condition",
    "ROI",
    "Electrode",
    "Flag Type",
    "Flag Scope",
    "Current Toolbox Exclusion",
    "QC Notes",
]
_ROI_COVERAGE_COLUMNS = [
    "PID",
    "Recording ID",
    "Condition",
    "Coverage Type",
    "ROI",
    "Status",
    "Decision Reasons",
    "Expected Electrodes",
    "Observed Electrodes",
    "Excluded Electrodes",
    "Interpolated Electrodes",
    "Used Electrodes",
    "Expected Count",
    "Observed Count",
    "Excluded Count",
    "Interpolated Count",
    "Used Count",
    "All Members Interpolated Warning",
    "Coverage Fingerprint",
]
_REPEATED_IDENTITY_COLUMNS = [
    "PID",
    "Recording ID",
    "Session ID",
    "Session",
    "Visit Index",
    "Days From Baseline",
    "Group ID",
    "Group",
    "Condition",
]


def _session_columns(legacy_columns: Sequence[str]) -> list[str]:
    return [
        *_REPEATED_IDENTITY_COLUMNS,
        *[
            column
            for column in legacy_columns
            if column not in {"PID", "Group", "Condition"}
        ],
    ]


@dataclass(frozen=True, slots=True)
class AnalysisReadyWorkbookResult:
    """Summary of one successful full-audit workbook export."""

    path: Path
    row_count: int
    sheet_count: int
    participant_count: int
    condition_count: int
    flag_count: int

    @property
    def workbook_path(self) -> Path:
        """Compatibility alias for callers that prefer an explicit name."""

        return self.path

    @property
    def roi_row_count(self) -> int:
        """Return the number of rows in the primary ROI Long sheet."""

        return self.row_count


@dataclass(frozen=True, slots=True)
class _ExclusionContext:
    manual_participants: frozenset[str]
    manual_participant_conditions: frozenset[tuple[str, str]]
    manual_recordings: frozenset[str]
    manual_recording_conditions: frozenset[tuple[str, str]]
    frequency_auto_participants: frozenset[str]
    frequency_manual_participants: frozenset[str]
    frequency_auto_recordings: frozenset[str]
    frequency_manual_recordings: frozenset[str]
    auto_electrodes_by_participant: Mapping[str, frozenset[str]]
    auto_electrodes_by_recording: Mapping[str, frozenset[str]]
    notes_by_participant: Mapping[tuple[str, str], str]
    notes_by_recording: Mapping[tuple[str, str], str]
    auto_electrode_notes: Mapping[tuple[str, str], str]
    auto_recording_electrode_notes: Mapping[tuple[str, str], str]


def default_analysis_ready_workbook_path(project_root: str | Path) -> Path:
    """Return the canonical full-audit workbook path for a project."""

    return (
        Path(project_root).expanduser().resolve(strict=False)
        / ANALYSIS_READY_RELATIVE_PATH
    )


def write_analysis_ready_workbook(
    project_root: str | Path,
    *,
    dataset_index: ProjectDatasetIndex | None = None,
    selection_metadata: Mapping[str, object] | None = None,
    log_callback: Callable[[str], None] | None = None,
) -> AnalysisReadyWorkbookResult:
    """Write the project's final-release-authorized Summed BCA audit workbook.

    Harmonics always come from the current persisted canonical processing
    selection; caller-supplied metadata must match it exactly. Reviewed
    exclusions blank canonical ROI and normalized derivatives, while raw
    electrode values remain available as explicitly labeled audit evidence.
    """

    root = Path(project_root).expanduser().resolve(strict=False)
    if dataset_index is not None and (
        Path(dataset_index.project_root).expanduser().resolve(strict=False) != root
    ):
        raise ValueError(
            "The supplied dataset index belongs to a different project root."
        )

    final_coverage, release_fingerprint = _require_analysis_ready_release(root)
    index = require_canonical_released_dataset_index(
        root,
        dataset_index,
        final_coverage=final_coverage,
    )
    records = _full_audit_records(index, final_coverage=final_coverage)
    if not records:
        raise RuntimeError("Analysis-ready export found no released processed workbooks.")
    rois = {
        roi.name: list(roi.electrodes)
        for roi in final_coverage.roi_snapshot.rois
    }
    selection_frames, selection_source = _load_selection_frames(
        root,
        selection_metadata=selection_metadata,
        expected_release_fingerprint=release_fingerprint,
    )
    selected_harmonics = _selected_harmonics_from_frames(selection_frames)
    if not selected_harmonics:
        raise RuntimeError(
            "Analysis-ready export found no harmonics marked for inclusion in the saved harmonic selection."
        )
    selected_columns = [f"{frequency:.4f}_Hz" for frequency in selected_harmonics]

    _log_status(
        log_callback,
        "Preparing the full-audit analysis-ready workbook from "
        f"{len(records)} observed participant-condition workbooks.",
    )
    logger.debug(
        "analysis_ready_export_started",
        extra={
            "project_root": str(root),
            "workbook_count": len(records),
            "roi_count": len(rois),
            "harmonic_count": len(selected_harmonics),
            "selection_source": selection_source,
        },
    )

    exclusion_context, metadata_flag_rows = _build_exclusion_context(index, records)
    roi_rows: list[dict[str, object]] = []
    electrode_rows: list[dict[str, object]] = []
    whole_scalp_rows: list[dict[str, object]] = []
    rms_harmonic_scale_rows: list[dict[str, object]] = []
    issue_flag_rows: list[dict[str, object]] = []

    for record in records:
        starts = (
            len(roi_rows),
            len(electrode_rows),
            len(whole_scalp_rows),
            len(rms_harmonic_scale_rows),
            len(issue_flag_rows),
        )
        _append_record_rows(
            record=record,
            coverage_cell=_coverage_cell_for_record(final_coverage, record),
            rois=rois,
            selected_columns=selected_columns,
            exclusion_context=exclusion_context,
            roi_rows=roi_rows,
            electrode_rows=electrode_rows,
            whole_scalp_rows=whole_scalp_rows,
            rms_harmonic_scale_rows=rms_harmonic_scale_rows,
            issue_flag_rows=issue_flag_rows,
        )
        if record.recording_id is not None:
            identity = _record_session_identity(record)
            for rows, start in zip(
                (
                    roi_rows,
                    electrode_rows,
                    whole_scalp_rows,
                    rms_harmonic_scale_rows,
                    issue_flag_rows,
                ),
                starts,
            ):
                for row in rows[start:]:
                    row.update(identity)

    repeated_session = index.is_repeated_session
    roi_long_columns = (
        _session_columns(_ROI_LONG_COLUMNS)
        if repeated_session
        else _ROI_LONG_COLUMNS
    )
    roi_long = pd.DataFrame(roi_rows, columns=roi_long_columns)
    if roi_long.empty or not np.isfinite(pd.to_numeric(roi_long["Raw Summed BCA"], errors="coerce")).any():
        raise RuntimeError(
            "Analysis-ready export requires at least one finite ROI-level "
            "Summed BCA value. The previous export, if any, was left unchanged."
        )

    condition_order = _ordered_unique(record.condition for record in records)
    roi_order = list(rois)
    frames: dict[str, pd.DataFrame] = {
        ROI_LONG_SHEET: roi_long,
        RAW_WIDE_SHEET: _build_wide_frame(
            roi_long,
            value_column="Raw Summed BCA",
            conditions=condition_order,
            rois=roi_order,
        ),
        RMS_WIDE_SHEET: _build_wide_frame(
            roi_long,
            value_column="RMS Normalized BCA",
            conditions=condition_order,
            rois=roi_order,
        ),
        SIGNED_MEAN_WIDE_SHEET: _build_wide_frame(
            roi_long,
            value_column="Signed Mean Normalized BCA",
            conditions=condition_order,
            rois=roi_order,
        ),
        ELECTRODE_LONG_SHEET: pd.DataFrame(
            electrode_rows,
            columns=(
                _session_columns(_ELECTRODE_LONG_COLUMNS)
                if repeated_session
                else _ELECTRODE_LONG_COLUMNS
            ),
        ),
        WHOLE_SCALP_SHEET: pd.DataFrame(
            whole_scalp_rows,
            columns=(
                _session_columns(_WHOLE_SCALP_COLUMNS)
                if repeated_session
                else _WHOLE_SCALP_COLUMNS
            ),
        ),
        RMS_HARMONIC_SCALES_SHEET: pd.DataFrame(
            rms_harmonic_scale_rows,
            columns=(
                _session_columns(_RMS_HARMONIC_SCALE_COLUMNS)
                if repeated_session
                else _RMS_HARMONIC_SCALE_COLUMNS
            ),
        ),
        QC_FLAGS_SHEET: _finalize_qc_flags(
            [*metadata_flag_rows, *issue_flag_rows],
            repeated_session=repeated_session,
        ),
        ROI_DEFINITIONS_SHEET: _build_roi_definitions_frame(rois),
        ROI_COVERAGE_SHEET: _build_roi_coverage_frame(final_coverage),
        SELECTION_SUMMARY_SHEET: _clean_selection_summary_frame(selection_frames),
        HARMONIC_SELECTION_SHEET: _clean_harmonic_selection_frame(selection_frames),
        ANALYSIS_NOTES_SHEET: _build_analysis_notes_frame(
            selection_source=selection_source,
            selected_harmonics=selected_harmonics,
            workbook_count=len(records),
            roi_count=len(rois),
            repeated_session=repeated_session,
        ),
    }

    target = default_analysis_ready_workbook_path(root)
    _write_frames_atomically(target, frames)
    participants = {record.participant_id.casefold() for record in records}
    conditions = {record.condition.casefold() for record in records}
    flag_count = len(frames[QC_FLAGS_SHEET])
    result = AnalysisReadyWorkbookResult(
        path=target,
        row_count=len(roi_long),
        sheet_count=len(frames),
        participant_count=len(participants),
        condition_count=len(conditions),
        flag_count=flag_count,
    )
    logger.debug(
        "analysis_ready_export_completed",
        extra={
            "path": str(target),
            "row_count": result.row_count,
            "sheet_count": result.sheet_count,
            "participant_count": result.participant_count,
            "condition_count": result.condition_count,
            "flag_count": result.flag_count,
        },
    )
    _log_status(
        log_callback,
        "Analysis-ready full-audit workbook exported: "
        f"{target} ({result.participant_count} participants, "
        f"{result.condition_count} conditions).",
    )
    return result


# Keep the verb used by earlier export callers while the processing pipeline
# uses the more explicit ``write_...`` entry point.
export_analysis_ready_workbook = write_analysis_ready_workbook


def _require_analysis_ready_release(
    project_root: Path,
) -> tuple[RoiCoverageLedger, str]:
    _outcomes, coverage, receipt = require_project_final_release(project_root)
    return coverage, receipt.fingerprint


def _full_audit_records(
    index: ProjectDatasetIndex,
    *,
    final_coverage: RoiCoverageLedger,
) -> list[Any]:
    combined = [*index.workbooks, *index.excluded_workbooks]
    ordered = sorted(
        combined,
        key=lambda record: (
            _natural_key(record.participant_id),
            record.visit_index if record.visit_index is not None else 0,
            record.condition.casefold(),
            str(record.path).casefold(),
        ),
    )
    unique: dict[tuple[str, str], Any] = {}
    for record in ordered:
        identity = record.recording_id or record.participant_id
        unique.setdefault(
            (identity.casefold(), record.condition.casefold()),
            record,
        )
    released = {
        (cell.recording_id.casefold(), cell.condition_label.casefold()): cell
        for cell in final_coverage.cells
        if cell.source_evidence is not None
    }
    missing = sorted(set(released).difference(unique))
    if missing:
        raise RuntimeError(
            "Analysis-ready export could not find the QC-20 released workbook "
            f"for recording-condition cell(s): {missing!r}."
        )
    records = [unique[key] for key in released]
    for record in records:
        key = (
            str(record.recording_id or record.participant_id).casefold(),
            str(record.condition).casefold(),
        )
        expected_path = Path(released[key].workbook_path).resolve(strict=False)
        if Path(record.path).resolve(strict=False) != expected_path:
            raise RuntimeError(
                "Analysis-ready export found a workbook path different from the "
                f"QC-20 release receipt for {key[0]}/{key[1]}."
            )
    records.sort(
        key=lambda record: (
            _natural_key(record.participant_id),
            record.visit_index if record.visit_index is not None else 0,
            record.condition.casefold(),
            str(record.path).casefold(),
        )
    )
    if index.has_group_metadata:
        missing = sorted(
            {record.participant_id for record in records if not str(record.group_label or "").strip()},
            key=_natural_key,
        )
        if missing:
            raise RuntimeError("Canonical group labels are missing for observed participant(s): " + ", ".join(missing))
    return records


def _coverage_cell_for_record(
    coverage: RoiCoverageLedger,
    record: Any,
) -> RecordingConditionRoiCoverage:
    identity = record.recording_id or record.participant_id
    cell = coverage.cell_for(identity, record.condition)
    if cell is None or cell.source_evidence is None:
        raise RuntimeError(
            "Analysis-ready export lacks final QC-21 coverage for "
            f"{identity}/{record.condition}."
        )
    return cell


def _record_session_identity(record: Any) -> dict[str, object]:
    return {
        "PID": str(record.participant_id),
        "Recording ID": str(record.recording_id or ""),
        "Session ID": str(record.session_id or ""),
        "Session": str(record.session_label or ""),
        "Visit Index": record.visit_index if record.visit_index is not None else "",
        "Days From Baseline": (
            record.days_from_baseline
            if record.days_from_baseline is not None
            else ""
        ),
        "Group ID": str(record.group_id or ""),
        "Group": str(record.group_label or _SINGLE_GROUP_LABEL),
        "Condition": str(record.condition),
    }


def _load_selection_frames(
    project_root: Path,
    *,
    selection_metadata: Mapping[str, object] | None,
    expected_release_fingerprint: str,
) -> tuple[dict[str, pd.DataFrame], str]:
    accepted_metadata = _load_current_processing_selection_metadata(project_root)
    source = "processing-time metadata"
    if selection_metadata is None:
        selection_metadata = accepted_metadata
        source = "saved processing-time metadata"
    elif _semantic_metadata_json(selection_metadata) != _semantic_metadata_json(
        accepted_metadata
    ):
        raise RuntimeError(
            "Analysis-ready export rejected caller-supplied harmonic metadata "
            "because it differs from the current persisted accepted selection."
        )
    recorded_release = str(
        selection_metadata.get("final_release_receipt_fingerprint") or ""
    )
    if recorded_release != expected_release_fingerprint:
        raise RuntimeError(
            "Analysis-ready export requires harmonic selection produced from "
            "the current QC-20 final-release receipt. Recalculate harmonics."
        )
    frames = build_harmonic_selection_frames(selection_metadata)
    return {str(name): frame.copy() for name, frame in frames.items()}, source


def _load_current_processing_selection_metadata(
    project_root: Path,
) -> dict[str, object]:
    from Main_App.processing.harmonic_selection_qc import (
        load_processing_harmonic_selection_metadata,
    )
    from Main_App.projects.project import Project

    return load_processing_harmonic_selection_metadata(Project.load(project_root))


def _semantic_metadata_json(value: Mapping[str, object]) -> str:
    try:
        return json.dumps(
            dict(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=True,
        )
    except (TypeError, ValueError) as error:
        raise RuntimeError("Harmonic selection metadata is not serializable.") from error


def _selection_frame(
    frames: Mapping[str, pd.DataFrame],
    *candidate_names: str,
) -> pd.DataFrame:
    wanted = {_normalized_header(name) for name in candidate_names}
    for name, frame in frames.items():
        if _normalized_header(name) in wanted:
            return frame.copy()
    return pd.DataFrame()


def _selected_harmonics_from_frames(
    frames: Mapping[str, pd.DataFrame],
) -> list[float]:
    harmonic_frame = _selection_frame(
        frames,
        "Harmonic_Selection",
        HARMONIC_SELECTION_SHEET,
    )
    frequencies: list[float] = []
    if not harmonic_frame.empty:
        frequency_column = _find_column(
            harmonic_frame,
            "requested_harmonic_hz",
            "harmonic_hz",
            "harmonic (hz)",
            "requested_frequency_hz",
        )
        included_column = _find_column(
            harmonic_frame,
            "included_in_summation",
            "included in summed bca",
            "included",
        )
        if frequency_column is not None and included_column is not None:
            for _, row in harmonic_frame.iterrows():
                if not _truthy(row.get(included_column)):
                    continue
                frequency = _finite_float(row.get(frequency_column))
                if frequency is not None and frequency > 0:
                    frequencies.append(frequency)

    summary = _selection_frame(
        frames,
        "Selection_Summary",
        SELECTION_SUMMARY_SHEET,
    )
    item_column = _find_column(summary, "Summary Item", "Item")
    value_column = _find_column(summary, "Value")
    if item_column is not None and value_column is not None:
        accepted_items = {
            _normalized_header("Included harmonic frequencies (Hz)"),
            _normalized_header("Selected harmonics (Hz)"),
        }
        for _, row in summary.iterrows():
            if _normalized_header(row.get(item_column)) not in accepted_items:
                continue
            frequencies.extend(_frequency_list(row.get(value_column)))
    return sorted({round(float(value), 4) for value in frequencies})


def _coverage_cell_decision_note(
    coverage_cell: RecordingConditionRoiCoverage,
) -> str:
    reasons = [str(reason) for reason in coverage_cell.decision_reason_codes if reason]
    if reasons:
        return (
            "reviewed whole-cell exclusion; decision reason code(s): "
            + ", ".join(reasons)
        )
    return "reviewed whole-cell exclusion"


def _append_record_rows(
    *,
    record: Any,
    coverage_cell: RecordingConditionRoiCoverage,
    rois: Mapping[str, list[str]],
    selected_columns: Sequence[str],
    exclusion_context: _ExclusionContext,
    roi_rows: list[dict[str, object]],
    electrode_rows: list[dict[str, object]],
    whole_scalp_rows: list[dict[str, object]],
    rms_harmonic_scale_rows: list[dict[str, object]],
    issue_flag_rows: list[dict[str, object]],
) -> None:
    pid = str(record.participant_id)
    group = str(record.group_label or _SINGLE_GROUP_LABEL)
    condition = str(record.condition)
    pid_key = pid.casefold()
    condition_key = condition.casefold()
    recording_key = str(record.recording_id or "").casefold()
    base_notes, _legacy_context_excluded = _record_exclusion_notes(
        exclusion_context,
        pid_key=pid_key,
        condition_key=condition_key,
        recording_key=recording_key,
    )
    cell_excluded = bool(coverage_cell.downstream_cell_excluded)
    decision_note = _coverage_cell_decision_note(coverage_cell)
    if cell_excluded:
        base_notes.append(decision_note)
        _append_flag(
            issue_flag_rows,
            pid=pid,
            group=group,
            condition=condition,
            flag_type="Reviewed recording-condition exclusion",
            flag_scope="Participant-condition",
            current_exclusion=True,
            notes=decision_note,
        )
    base_excluded = cell_excluded
    participant_auto_electrodes = exclusion_context.auto_electrodes_by_participant.get(
        pid_key,
        frozenset(),
    )
    recording_auto_electrodes = exclusion_context.auto_electrodes_by_recording.get(
        recording_key,
        frozenset(),
    )
    reviewed_excluded_electrodes = frozenset(
        coverage_cell.whole_scalp_normalization.excluded_channels
        if coverage_cell.whole_scalp_normalization is not None
        else ()
    )
    auto_electrodes = (
        participant_auto_electrodes
        | recording_auto_electrodes
        | reviewed_excluded_electrodes
    )

    if coverage_cell.source_evidence is None:
        raise RuntimeError(
            f"Final QC-21 source evidence is missing for {pid}/{condition}."
        )
    normalization_coverage = coverage_cell.whole_scalp_normalization
    if normalization_coverage is None:
        raise RuntimeError(
            f"Final QC-21 normalization coverage is missing for {pid}/{condition}."
        )
    normalization_available = (
        normalization_coverage.status == ROI_VALUE_AVAILABLE
        and not cell_excluded
    )
    frame = read_xlsx_sheet_selected_columns(
        record.path,
        sheet_name="BCA (uV)",
        required_columns=["Electrode", *selected_columns],
        require_all=True,
    )
    prepared, record_issue_notes, harmonic_scales = _prepare_electrode_values(
        frame,
        selected_columns=selected_columns,
        expected_scalp_channels=normalization_coverage.expected_channels,
        normalization_available=normalization_available,
    )
    if cell_excluded:
        prepared["RMS Normalized BCA"] = math.nan
        prepared["Signed Mean Normalized BCA"] = math.nan

    if record_issue_notes:
        _append_flag(
            issue_flag_rows,
            pid=pid,
            group=group,
            condition=condition,
            flag_type="Non-finite or duplicate source values",
            flag_scope="Participant-condition",
            current_exclusion=False,
            notes="; ".join(record_issue_notes),
        )

    finite_raw = pd.to_numeric(prepared["Raw Summed BCA"], errors="coerce")
    finite_raw = finite_raw[np.isfinite(finite_raw)]
    descriptive_rms = (
        float(np.sqrt(np.mean(np.square(finite_raw.to_numpy(dtype=float))))) if not finite_raw.empty else math.nan
    )
    signed_mean = float(finite_raw.mean()) if not finite_raw.empty else math.nan
    normalization_notes: list[str] = []
    if not normalization_available:
        if cell_excluded:
            normalization_notes.append(
                "Whole-scalp-normalized values were not calculated because "
                + decision_note
            )
        elif normalization_coverage.excluded_channels:
            normalization_notes.append(
                "Whole-scalp-normalized ROI values were not calculated because "
                "the frozen whole-scalp set has a reviewed unavailable member: "
                + ", ".join(normalization_coverage.excluded_channels)
            )
        else:
            normalization_notes.append(
                "Whole-scalp-normalized ROI values were not calculated; QC-21 "
                "coverage reason code(s): "
                + ", ".join(normalization_coverage.reason_codes)
            )
    if not all(bool(scale["Used for RMS Normalization"]) for scale in harmonic_scales):
        normalization_notes.append(
            "At least one selected harmonic lacked a complete, positive "
            "whole-scalp vector length; publication-style RMS-normalized "
            "values are blank."
        )
    if not normalization_available:
        signed_mean = math.nan
        prepared["Signed Mean Normalized BCA"] = math.nan
    elif not math.isfinite(signed_mean) or signed_mean == 0.0:
        normalization_notes.append(
            "Whole-scalp signed mean was zero or unavailable; signed-mean-normalized values are blank."
        )
        prepared["Signed Mean Normalized BCA"] = math.nan
    else:
        prepared["Signed Mean Normalized BCA"] = prepared["Raw Summed BCA"] / signed_mean
    if normalization_notes:
        _append_flag(
            issue_flag_rows,
            pid=pid,
            group=group,
            condition=condition,
            flag_type="Normalization denominator unavailable",
            flag_scope="Participant-condition",
            current_exclusion=False,
            notes="; ".join(normalization_notes),
        )

    for _, electrode_row in prepared.iterrows():
        electrode = str(electrode_row["Electrode"])
        electrode_key = electrode.upper()
        electrode_notes = list(base_notes)
        electrode_excluded = base_excluded
        if electrode_key in reviewed_excluded_electrodes:
            electrode_excluded = True
            electrode_notes.append(
                "Reviewed frequency-domain exclusion for this recording-condition."
            )
        if electrode_key in participant_auto_electrodes:
            electrode_notes.append(
                exclusion_context.auto_electrode_notes.get(
                    (pid_key, electrode_key),
                    "Automatic frequency-domain electrode exclusion.",
                )
            )
        if cell_excluded:
            electrode_notes.append(
                "Audit-only raw electrode value; canonical ROI and normalized "
                "values are blank for this excluded recording-condition."
            )
        if electrode_key in recording_auto_electrodes:
            electrode_notes.append(
                exclusion_context.auto_recording_electrode_notes.get(
                    (recording_key, electrode_key),
                    "Automatic frequency-domain recording-electrode exclusion.",
                )
            )
        missing_columns = electrode_row.get("Missing Selected Harmonics", "")
        if missing_columns:
            electrode_notes.append("Non-finite selected BCA cell(s): " + str(missing_columns))
        electrode_rows.append(
            {
                "PID": pid,
                "Group": group,
                "Condition": condition,
                "Electrode": electrode,
                "Raw Summed BCA": electrode_row["Raw Summed BCA"],
                "RMS Normalized BCA": electrode_row["RMS Normalized BCA"],
                "Signed Mean Normalized BCA": electrode_row["Signed Mean Normalized BCA"],
                "Current Toolbox Exclusion": _yes_no(electrode_excluded),
                "QC Flag": _yes_no(bool(electrode_notes)),
                "QC Notes": "; ".join(_ordered_unique(electrode_notes)),
            }
        )

    all_record_notes = [*base_notes, *record_issue_notes, *normalization_notes]
    if auto_electrodes:
        all_record_notes.append(
            "Current Toolbox automatic electrode exclusion(s), retained in this "
            "full-audit export: " + ", ".join(sorted(auto_electrodes))
        )
    for scale in harmonic_scales:
        rms_harmonic_scale_rows.append(
            _rms_harmonic_scale_row(
                pid=pid,
                group=group,
                condition=condition,
                selected_column=str(scale["Selected Column"]),
                source_count=int(scale["Source Electrode Count"]),
                finite_count=int(scale["Finite Electrode Count"]),
                vector_length=(
                    math.nan if cell_excluded else scale["Scalp Vector Length"]
                ),
                used=(
                    bool(scale["Used for RMS Normalization"])
                    and not cell_excluded
                ),
                excluded=base_excluded or not normalization_available,
                notes=[
                    *base_notes,
                    *record_issue_notes,
                    str(scale["QC Notes"] or ""),
                ],
            )
        )
    whole_scalp_rows.append(
        _whole_scalp_row(
            pid=pid,
            group=group,
            condition=condition,
            source_count=len(prepared),
            finite_count=len(finite_raw),
            descriptive_rms=(math.nan if cell_excluded else descriptive_rms),
            signed_mean=(math.nan if cell_excluded else signed_mean),
            excluded=base_excluded or not normalization_available,
            notes=all_record_notes,
        )
    )

    indexed = prepared.set_index("Electrode", drop=False)
    indexed.index = indexed.index.astype(str).str.upper()
    coverage_by_roi = {
        membership.roi_name.casefold(): membership
        for membership in coverage_cell.roi_memberships
    }
    for roi, configured_electrodes in rois.items():
        membership = coverage_by_roi.get(roi.casefold())
        if membership is None:
            raise RuntimeError(
                f"Final QC-21 coverage is missing ROI {roi!r} for {pid}/{condition}."
            )
        if tuple(configured_electrodes) != membership.expected_channels:
            raise RuntimeError(
                f"Frozen ROI membership changed for {roi!r} in {pid}/{condition}."
            )
        roi_notes = list(base_notes)
        roi_excluded = base_excluded or membership.status != ROI_VALUE_AVAILABLE
        if membership.status != ROI_VALUE_AVAILABLE:
            if cell_excluded:
                roi_notes.append(
                    "Primary ROI value was not calculated because " + decision_note
                )
            elif membership.excluded_channels:
                roi_notes.append(
                    "Primary ROI value was not calculated because reviewed required "
                    "electrode(s) were unavailable: "
                    + ", ".join(membership.excluded_channels)
                )
            else:
                roi_notes.append(
                    "Primary ROI value was not calculated; QC-21 coverage reason "
                    "code(s): " + ", ".join(membership.reason_codes)
                )
            _append_flag(
                issue_flag_rows,
                pid=pid,
                group=group,
                condition=condition,
                roi=roi,
                flag_type="Required ROI electrode unavailable",
                flag_scope="Participant-condition-ROI",
                current_exclusion=True,
                notes=roi_notes[-1],
            )
            raw = rms_normalized = signed_normalized = math.nan
        else:
            roi_frame = indexed.loc[list(membership.used_channels)]
            if isinstance(roi_frame, pd.Series):
                roi_frame = roi_frame.to_frame().T
            raw = float(roi_frame["Raw Summed BCA"].mean(skipna=False))
            rms_normalized = float(
                roi_frame["RMS Normalized BCA"].mean(skipna=False)
            )
            signed_normalized = float(
                roi_frame["Signed Mean Normalized BCA"].mean(skipna=False)
            )
            if membership.interpolated_channels:
                roi_notes.append(
                    "Successfully interpolated configured electrode(s) were "
                    "included: " + ", ".join(membership.interpolated_channels)
                )
            if membership.all_members_interpolated_warning:
                roi_notes.append(
                    "Manual review warning: every configured ROI electrode was interpolated."
                )
        roi_rows.append(
            _roi_row(
                pid=pid,
                group=group,
                condition=condition,
                roi=roi,
                raw=raw,
                rms_normalized=rms_normalized,
                signed_normalized=signed_normalized,
                excluded=roi_excluded,
                notes=[*roi_notes, *record_issue_notes, *normalization_notes],
            )
        )


def _prepare_electrode_values(
    frame: pd.DataFrame,
    *,
    selected_columns: Sequence[str],
    expected_scalp_channels: Sequence[str],
    normalization_available: bool,
) -> tuple[pd.DataFrame, list[str], list[dict[str, object]]]:
    if "Electrode" not in frame.columns:
        raise RuntimeError("The BCA (uV) sheet is missing the exact 'Electrode' column.")
    source = frame.loc[:, ["Electrode", *selected_columns]].copy()
    source["Electrode"] = source["Electrode"].astype(str).str.strip().str.upper()
    source = source[source["Electrode"].ne("") & source["Electrode"].ne("NAN")]
    if source.empty:
        raise RuntimeError("The BCA (uV) sheet contains no electrode rows.")
    expected = tuple(str(channel).strip().upper() for channel in expected_scalp_channels)
    if not expected or len(expected) != len(set(expected)):
        raise RuntimeError(
            "Analysis-ready export requires a nonempty unique frozen scalp set."
        )
    duplicate_mask = source["Electrode"].duplicated(keep=False)
    if duplicate_mask.any():
        duplicate_names = sorted(set(source.loc[duplicate_mask, "Electrode"]))
        raise RuntimeError(
            "Analysis-ready export forbids duplicate source electrode rows: "
            + ", ".join(duplicate_names)
        )
    indexed = source.set_index("Electrode")
    missing_electrodes = [channel for channel in expected if channel not in indexed.index]
    if missing_electrodes:
        raise RuntimeError(
            "Analysis-ready export requires every frozen scalp electrode row. Missing: "
            + ", ".join(missing_electrodes)
        )
    numeric = indexed.loc[list(expected), list(selected_columns)].apply(
        pd.to_numeric,
        errors="coerce",
    )
    numeric = numeric.replace([np.inf, -np.inf], np.nan)
    if not np.isfinite(numeric.to_numpy(dtype=float)).all():
        raise RuntimeError(
            "Analysis-ready export requires finite BCA values for every selected "
            "harmonic and frozen scalp electrode; partial harmonic sums are forbidden."
        )
    notes: list[str] = []

    missing_mask = numeric.isna()
    prepared = pd.DataFrame({"Electrode": numeric.index.astype(str)})
    prepared["Missing Selected Harmonics"] = [
        ", ".join(column for column in selected_columns if bool(mask[column])) for _, mask in missing_mask.iterrows()
    ]
    prepared["Raw Summed BCA"] = numeric.sum(
        axis=1,
        min_count=len(selected_columns),
    ).to_numpy()

    source_count = len(numeric)
    finite_counts = numeric.notna().sum(axis=0)
    vector_lengths = np.sqrt(np.square(numeric).sum(axis=0, min_count=1))
    valid_scales = (
        bool(normalization_available)
        & finite_counts.eq(source_count)
        & np.isfinite(vector_lengths)
        & vector_lengths.gt(0.0)
    )
    safe_scales = vector_lengths.where(valid_scales)
    normalized = numeric.div(safe_scales, axis="columns")
    prepared["RMS Normalized BCA"] = normalized.sum(
        axis=1,
        min_count=len(selected_columns),
    ).to_numpy()

    harmonic_scales: list[dict[str, object]] = []
    for selected_column in selected_columns:
        finite_count = int(finite_counts[selected_column])
        vector_length = float(vector_lengths[selected_column])
        used = bool(valid_scales[selected_column])
        scale_notes: list[str] = []
        if finite_count != source_count:
            scale_notes.append(
                f"Complete scalp coverage unavailable ({finite_count}/{source_count} finite electrodes)."
            )
        if not math.isfinite(vector_length) or vector_length <= 0.0:
            scale_notes.append("Scalp vector length was zero or non-finite.")
        if not normalization_available:
            scale_notes.append(
                "Frozen whole-scalp normalization set has a reviewed unavailable member."
            )
        harmonic_scales.append(
            {
                "Selected Column": selected_column,
                "Source Electrode Count": source_count,
                "Finite Electrode Count": finite_count,
                "Scalp Vector Length": vector_length,
                "Used for RMS Normalization": used,
                "QC Notes": "; ".join(scale_notes),
            }
        )
    return prepared, notes, harmonic_scales


def _build_exclusion_context(
    index: ProjectDatasetIndex,
    records: Sequence[Any],
) -> tuple[_ExclusionContext, list[dict[str, object]]]:
    manifest = index.manifest if isinstance(index.manifest, Mapping) else {}
    preprocessing = manifest.get("preprocessing")
    preprocessing = preprocessing if isinstance(preprocessing, Mapping) else {}
    manual_participants_display = normalize_manual_excluded_participants(
        preprocessing.get("manual_excluded_participants")
    )
    manual_conditions_display = normalize_manual_excluded_participant_conditions(
        preprocessing.get("manual_excluded_participant_conditions")
    )
    manual_recordings_display = normalize_manual_excluded_recordings(
        preprocessing.get("manual_excluded_recordings")
    )
    manual_recording_conditions_display = (
        normalize_manual_excluded_recording_conditions(
            preprocessing.get("manual_excluded_recording_conditions")
        )
    )
    manual_participants = frozenset(pid.casefold() for pid in manual_participants_display)
    manual_participant_conditions = frozenset(
        (pid.casefold(), condition.casefold())
        for pid, conditions in manual_conditions_display.items()
        for condition in conditions
    )
    manual_recordings = frozenset(
        recording_id.casefold() for recording_id in manual_recordings_display
    )
    manual_recording_conditions = frozenset(
        (recording_id.casefold(), condition.casefold())
        for recording_id, conditions in manual_recording_conditions_display.items()
        for condition in conditions
    )

    state = load_frequency_domain_qc_state(index.project_root)
    auto_participant_entries = _mapping_entries(state.get("auto_participant_exclusions"))
    manual_frequency_entries = _mapping_entries(state.get("manual_participant_exclusions"))
    auto_electrode_entries = _mapping_entries(state.get("auto_participant_electrode_exclusions"))
    auto_recording_entries = _mapping_entries(
        state.get("auto_recording_exclusions")
    )
    manual_frequency_recording_entries = _mapping_entries(
        state.get("manual_recording_exclusions")
    )
    auto_recording_electrode_entries = _mapping_entries(
        state.get("auto_recording_electrode_exclusions")
    )
    frequency_auto_participants = frozenset(
        _pid_key(entry.get("participant_id"))
        for entry in auto_participant_entries
        if _pid_key(entry.get("participant_id"))
    )
    frequency_manual_participants = frozenset(
        _pid_key(entry.get("participant_id"))
        for entry in manual_frequency_entries
        if _pid_key(entry.get("participant_id"))
    )
    frequency_auto_recordings = frozenset(
        _pid_key(entry.get("recording_id"))
        for entry in auto_recording_entries
        if _pid_key(entry.get("recording_id"))
    )
    frequency_manual_recordings = frozenset(
        _pid_key(entry.get("recording_id"))
        for entry in manual_frequency_recording_entries
        if _pid_key(entry.get("recording_id"))
    )
    auto_electrodes: dict[str, set[str]] = {}
    auto_electrode_notes: dict[tuple[str, str], str] = {}
    for entry in auto_electrode_entries:
        pid_key = _pid_key(entry.get("participant_id"))
        electrode = str(entry.get("electrode") or "").strip().upper()
        if not pid_key or not electrode:
            continue
        auto_electrodes.setdefault(pid_key, set()).add(electrode)
        reason = str(entry.get("reason") or "Automatic frequency-domain electrode exclusion.")
        auto_electrode_notes[(pid_key, electrode)] = reason

    auto_recording_electrodes: dict[str, set[str]] = {}
    auto_recording_electrode_notes: dict[tuple[str, str], str] = {}
    for entry in auto_recording_electrode_entries:
        recording_key = _pid_key(entry.get("recording_id"))
        electrode = str(entry.get("electrode") or "").strip().upper()
        if not recording_key or not electrode:
            continue
        auto_recording_electrodes.setdefault(recording_key, set()).add(electrode)
        reason = str(
            entry.get("reason")
            or "Automatic frequency-domain recording-electrode exclusion."
        )
        auto_recording_electrode_notes[(recording_key, electrode)] = reason

    participant_notes: dict[tuple[str, str], str] = {}
    for entry in [*auto_participant_entries, *manual_frequency_entries]:
        pid_key = _pid_key(entry.get("participant_id"))
        if not pid_key:
            continue
        source = (
            "Automatic frequency-domain participant exclusion"
            if entry in auto_participant_entries
            else "Manual frequency-domain participant exclusion"
        )
        reason = str(entry.get("reason") or "").strip()
        participant_notes[(pid_key, source)] = f"{source}: {reason}" if reason else source

    recording_notes: dict[tuple[str, str], str] = {}
    for entries, source in (
        (
            auto_recording_entries,
            "Automatic frequency-domain recording exclusion",
        ),
        (
            manual_frequency_recording_entries,
            "Manual frequency-domain recording exclusion",
        ),
    ):
        for entry in entries:
            recording_key = _pid_key(entry.get("recording_id"))
            if not recording_key:
                continue
            reason = str(entry.get("reason") or "").strip()
            recording_notes[(recording_key, source)] = (
                f"{source}: {reason}" if reason else source
            )

    context = _ExclusionContext(
        manual_participants=manual_participants,
        manual_participant_conditions=manual_participant_conditions,
        manual_recordings=manual_recordings,
        manual_recording_conditions=manual_recording_conditions,
        frequency_auto_participants=frequency_auto_participants,
        frequency_manual_participants=frequency_manual_participants,
        frequency_auto_recordings=frequency_auto_recordings,
        frequency_manual_recordings=frequency_manual_recordings,
        auto_electrodes_by_participant={pid: frozenset(electrodes) for pid, electrodes in auto_electrodes.items()},
        auto_electrodes_by_recording={
            recording_id: frozenset(electrodes)
            for recording_id, electrodes in auto_recording_electrodes.items()
        },
        notes_by_participant=participant_notes,
        notes_by_recording=recording_notes,
        auto_electrode_notes=auto_electrode_notes,
        auto_recording_electrode_notes=auto_recording_electrode_notes,
    )
    group_by_pid = _group_label_lookup(index, records)
    flags: list[dict[str, object]] = []
    for raw_pid in manual_participants_display:
        _append_flag(
            flags,
            pid=raw_pid,
            group=group_by_pid.get(raw_pid.casefold(), ""),
            flag_type="Manual preprocessing participant exclusion",
            flag_scope="Participant",
            current_exclusion=True,
            notes="Participant is currently excluded by preprocessing settings.",
        )
    for raw_pid, conditions in manual_conditions_display.items():
        for condition in conditions:
            _append_flag(
                flags,
                pid=raw_pid,
                group=group_by_pid.get(raw_pid.casefold(), ""),
                condition=condition,
                flag_type="Manual preprocessing participant-condition exclusion",
                flag_scope="Participant-condition",
                current_exclusion=True,
                notes="Participant-condition is currently excluded by preprocessing settings.",
            )
    records_by_recording = {
        str(record.recording_id).casefold(): record
        for record in records
        if record.recording_id
    }
    for raw_recording_id in manual_recordings_display:
        record = records_by_recording.get(raw_recording_id.casefold())
        if record is None:
            continue
        _append_flag(
            flags,
            pid=record.participant_id,
            group=str(record.group_label or ""),
            flag_type="Manual preprocessing recording exclusion",
            flag_scope="Recording",
            current_exclusion=True,
            notes="Recording is currently excluded by preprocessing settings.",
        )
        flags[-1].update(_record_session_identity(record))
        flags[-1]["Condition"] = ""
    for raw_recording_id, conditions in manual_recording_conditions_display.items():
        record = records_by_recording.get(raw_recording_id.casefold())
        if record is None:
            continue
        for condition in conditions:
            _append_flag(
                flags,
                pid=record.participant_id,
                group=str(record.group_label or ""),
                condition=condition,
                flag_type="Manual preprocessing recording-condition exclusion",
                flag_scope="Recording-condition",
                current_exclusion=True,
                notes=(
                    "Recording-condition is currently excluded by "
                    "preprocessing settings."
                ),
            )
            flags[-1].update(_record_session_identity(record))
            flags[-1]["Condition"] = condition
    configured_participant_pairs = {
        (pid.casefold(), condition.casefold())
        for pid, conditions in manual_conditions_display.items()
        for condition in conditions
    }
    configured_recording_pairs = {
        (recording_id.casefold(), condition.casefold())
        for recording_id, conditions in manual_recording_conditions_display.items()
        for condition in conditions
    }
    for record in index.excluded_workbooks:
        participant_key = (
            record.participant_id.casefold(),
            record.condition.casefold(),
        )
        recording_key = (
            str(record.recording_id or "").casefold(),
            record.condition.casefold(),
        )
        if (
            participant_key in configured_participant_pairs
            or recording_key[0] in manual_recordings
            or recording_key in configured_recording_pairs
        ):
            continue
        _append_flag(
            flags,
            pid=record.participant_id,
            group=str(record.group_label or ""),
            condition=record.condition,
            flag_type=(
                "Current recording-condition exclusion"
                if record.recording_id
                else "Current participant-condition exclusion"
            ),
            flag_scope=(
                "Recording-condition"
                if record.recording_id
                else "Participant-condition"
            ),
            current_exclusion=True,
            notes="Canonical dataset index marks this observed workbook as excluded.",
        )
        if record.recording_id:
            flags[-1].update(_record_session_identity(record))
    for entry in auto_participant_entries:
        pid = str(entry.get("participant_id") or "").strip()
        if not pid:
            continue
        _append_flag(
            flags,
            pid=pid,
            group=group_by_pid.get(pid.casefold(), ""),
            flag_type="Automatic frequency-domain participant exclusion",
            flag_scope="Participant",
            current_exclusion=True,
            notes=str(entry.get("reason") or "Automatic frequency-domain QC exclusion."),
        )
    for entry in manual_frequency_entries:
        pid = str(entry.get("participant_id") or "").strip()
        if not pid:
            continue
        _append_flag(
            flags,
            pid=pid,
            group=group_by_pid.get(pid.casefold(), ""),
            flag_type="Manual frequency-domain participant exclusion",
            flag_scope="Participant",
            current_exclusion=True,
            notes=str(entry.get("reason") or "Manual frequency-domain QC exclusion."),
        )
    for entry in auto_electrode_entries:
        pid = str(entry.get("participant_id") or "").strip()
        electrode = str(entry.get("electrode") or "").strip().upper()
        if not pid or not electrode:
            continue
        triggering = entry.get("triggering_conditions")
        trigger_note = ""
        if isinstance(triggering, (list, tuple, set)) and triggering:
            trigger_note = "; triggering conditions: " + ", ".join(map(str, triggering))
        _append_flag(
            flags,
            pid=pid,
            group=group_by_pid.get(pid.casefold(), ""),
            electrode=electrode,
            flag_type="Automatic frequency-domain electrode exclusion",
            flag_scope="Participant-electrode",
            current_exclusion=True,
            notes=str(entry.get("reason") or "Automatic frequency-domain QC exclusion.") + trigger_note,
        )
    for entries, flag_type, default_note in (
        (
            auto_recording_entries,
            "Automatic frequency-domain recording exclusion",
            "Automatic frequency-domain recording exclusion.",
        ),
        (
            manual_frequency_recording_entries,
            "Manual frequency-domain recording exclusion",
            "Manual frequency-domain recording exclusion.",
        ),
    ):
        for entry in entries:
            recording_id = str(entry.get("recording_id") or "").strip()
            record = records_by_recording.get(recording_id.casefold())
            if not recording_id or record is None:
                continue
            _append_flag(
                flags,
                pid=record.participant_id,
                group=str(record.group_label or ""),
                flag_type=flag_type,
                flag_scope="Recording",
                current_exclusion=True,
                notes=str(entry.get("reason") or default_note),
            )
            flags[-1].update(_record_session_identity(record))
            flags[-1]["Condition"] = ""
    for entry in auto_recording_electrode_entries:
        recording_id = str(entry.get("recording_id") or "").strip()
        electrode = str(entry.get("electrode") or "").strip().upper()
        record = records_by_recording.get(recording_id.casefold())
        if not recording_id or not electrode or record is None:
            continue
        triggering = entry.get("triggering_conditions")
        trigger_note = ""
        if isinstance(triggering, (list, tuple, set)) and triggering:
            trigger_note = "; triggering conditions: " + ", ".join(
                map(str, triggering)
            )
        _append_flag(
            flags,
            pid=record.participant_id,
            group=str(record.group_label or ""),
            electrode=electrode,
            flag_type="Automatic frequency-domain recording-electrode exclusion",
            flag_scope="Recording-electrode",
            current_exclusion=True,
            notes=(
                str(
                    entry.get("reason")
                    or "Automatic frequency-domain recording-electrode exclusion."
                )
                + trigger_note
            ),
        )
        flags[-1].update(_record_session_identity(record))
        flags[-1]["Condition"] = ""
    return context, flags


def _record_exclusion_notes(
    context: _ExclusionContext,
    *,
    pid_key: str,
    condition_key: str,
    recording_key: str = "",
) -> tuple[list[str], bool]:
    notes: list[str] = []
    if pid_key in context.manual_participants:
        notes.append("Manual preprocessing participant exclusion.")
    if (pid_key, condition_key) in context.manual_participant_conditions:
        notes.append("Manual preprocessing participant-condition exclusion.")
    if recording_key in context.manual_recordings:
        notes.append("Manual preprocessing recording exclusion.")
    if (recording_key, condition_key) in context.manual_recording_conditions:
        notes.append("Manual preprocessing recording-condition exclusion.")
    if pid_key in context.frequency_auto_participants:
        notes.append(
            context.notes_by_participant.get(
                (pid_key, "Automatic frequency-domain participant exclusion"),
                "Automatic frequency-domain participant exclusion.",
            )
        )
    if pid_key in context.frequency_manual_participants:
        notes.append(
            context.notes_by_participant.get(
                (pid_key, "Manual frequency-domain participant exclusion"),
                "Manual frequency-domain participant exclusion.",
            )
        )
    if recording_key in context.frequency_auto_recordings:
        notes.append(
            context.notes_by_recording.get(
                (recording_key, "Automatic frequency-domain recording exclusion"),
                "Automatic frequency-domain recording exclusion.",
            )
        )
    if recording_key in context.frequency_manual_recordings:
        notes.append(
            context.notes_by_recording.get(
                (recording_key, "Manual frequency-domain recording exclusion"),
                "Manual frequency-domain recording exclusion.",
            )
        )
    return notes, bool(notes)


def _roi_row(
    *,
    pid: str,
    group: str,
    condition: str,
    roi: str,
    raw: object,
    rms_normalized: object,
    signed_normalized: object,
    excluded: bool,
    notes: Sequence[str],
) -> dict[str, object]:
    combined = "; ".join(_ordered_unique(note for note in notes if note))
    return {
        "PID": pid,
        "Group": group,
        "Condition": condition,
        "ROI": roi,
        "Raw Summed BCA": raw,
        "RMS Normalized BCA": rms_normalized,
        "Signed Mean Normalized BCA": signed_normalized,
        "Current Toolbox Exclusion": _yes_no(excluded),
        "QC Flag": _yes_no(bool(combined)),
        "QC Notes": combined,
    }


def _whole_scalp_row(
    *,
    pid: str,
    group: str,
    condition: str,
    source_count: int,
    finite_count: int,
    descriptive_rms: object,
    signed_mean: object,
    excluded: bool,
    notes: Sequence[str],
) -> dict[str, object]:
    combined = "; ".join(_ordered_unique(note for note in notes if note))
    return {
        "PID": pid,
        "Group": group,
        "Condition": condition,
        "Source Electrode Count": source_count,
        "Finite Summed BCA Electrode Count": finite_count,
        "Descriptive Post-Sum RMS (Not Used for Normalization)": descriptive_rms,
        "Whole Scalp Signed Mean Summed BCA": signed_mean,
        "Current Toolbox Exclusion": _yes_no(excluded),
        "QC Flag": _yes_no(bool(combined)),
        "QC Notes": combined,
    }


def _rms_harmonic_scale_row(
    *,
    pid: str,
    group: str,
    condition: str,
    selected_column: str,
    source_count: int,
    finite_count: int,
    vector_length: object,
    used: bool,
    excluded: bool,
    notes: Sequence[str],
) -> dict[str, object]:
    combined = "; ".join(_ordered_unique(note for note in notes if note))
    frequency = _finite_float(str(selected_column).removesuffix("_Hz"))
    return {
        "PID": pid,
        "Group": group,
        "Condition": condition,
        "Harmonic (Hz)": frequency if frequency is not None else math.nan,
        "Source Electrode Count": source_count,
        "Finite Electrode Count": finite_count,
        "Scalp Vector Length": vector_length,
        "Used for RMS Normalization": _yes_no(used),
        "Current Toolbox Exclusion": _yes_no(excluded),
        "QC Notes": combined,
    }


def _build_wide_frame(
    roi_long: pd.DataFrame,
    *,
    value_column: str,
    conditions: Sequence[str],
    rois: Sequence[str],
) -> pd.DataFrame:
    identity_columns = (
        [
            "PID",
            "Recording ID",
            "Session ID",
            "Session",
            "Visit Index",
            "Days From Baseline",
            "Group ID",
            "Group",
        ]
        if "Recording ID" in roi_long.columns
        else ["PID", "Group"]
    )
    base = roi_long.loc[:, identity_columns].drop_duplicates().copy()
    base["_Sort"] = base["PID"].map(_natural_key)
    sort_columns = ["_Sort"]
    if "Visit Index" in base.columns:
        sort_columns.append("Visit Index")
    base = base.sort_values(sort_columns, kind="stable").drop(columns="_Sort")
    for condition in conditions:
        for roi in rois:
            column = f"{condition} | {roi}"
            values = roi_long.loc[
                roi_long["Condition"].eq(condition) & roi_long["ROI"].eq(roi),
                [*identity_columns, value_column],
            ].rename(columns={value_column: column})
            base = base.merge(
                values,
                on=identity_columns,
                how="left",
                sort=False,
            )
    return base


def _build_roi_definitions_frame(rois: Mapping[str, list[str]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ROI": name,
                "Electrode Count": len(electrodes),
                "Electrodes": ", ".join(electrodes),
                "Aggregation": "Arithmetic mean of the complete frozen electrode set",
            }
            for name, electrodes in rois.items()
        ]
    )


def _build_roi_coverage_frame(coverage: RoiCoverageLedger) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for cell in coverage.cells:
        if not cell.roi_memberships:
            rows.append(
                {
                    "PID": cell.participant_id,
                    "Recording ID": cell.recording_id,
                    "Condition": cell.condition_label,
                    "Coverage Type": "Recording-condition",
                    "ROI": "",
                    "Status": f"not_calculated:{cell.outcome_status}",
                    "Decision Reasons": ", ".join(cell.decision_reason_codes),
                    "Expected Electrodes": "",
                    "Observed Electrodes": "",
                    "Excluded Electrodes": "",
                    "Interpolated Electrodes": "",
                    "Used Electrodes": "",
                    "Expected Count": 0,
                    "Observed Count": 0,
                    "Excluded Count": 0,
                    "Interpolated Count": 0,
                    "Used Count": 0,
                    "All Members Interpolated Warning": "No",
                    "Coverage Fingerprint": cell.fingerprint,
                }
            )
            continue
        for membership in cell.roi_memberships:
            rows.append(
                {
                    "PID": cell.participant_id,
                    "Recording ID": cell.recording_id,
                    "Condition": cell.condition_label,
                    "Coverage Type": "ROI",
                    "ROI": membership.roi_name,
                    "Status": membership.status,
                    "Decision Reasons": ", ".join(
                        (*cell.decision_reason_codes, *membership.reason_codes)
                    ),
                    "Expected Electrodes": ", ".join(membership.expected_channels),
                    "Observed Electrodes": ", ".join(membership.observed_channels),
                    "Excluded Electrodes": ", ".join(membership.excluded_channels),
                    "Interpolated Electrodes": ", ".join(
                        membership.interpolated_channels
                    ),
                    "Used Electrodes": ", ".join(membership.used_channels),
                    "Expected Count": len(membership.expected_channels),
                    "Observed Count": len(membership.observed_channels),
                    "Excluded Count": len(membership.excluded_channels),
                    "Interpolated Count": membership.interpolated_count,
                    "Used Count": len(membership.used_channels),
                    "All Members Interpolated Warning": _yes_no(
                        membership.all_members_interpolated_warning
                    ),
                    "Coverage Fingerprint": membership.fingerprint,
                }
            )
        normalization = cell.whole_scalp_normalization
        if normalization is not None:
            rows.append(
                {
                    "PID": cell.participant_id,
                    "Recording ID": cell.recording_id,
                    "Condition": cell.condition_label,
                    "Coverage Type": "Whole-scalp normalization",
                    "ROI": "",
                    "Status": normalization.status,
                    "Decision Reasons": ", ".join(
                        (*cell.decision_reason_codes, *normalization.reason_codes)
                    ),
                    "Expected Electrodes": ", ".join(
                        normalization.expected_channels
                    ),
                    "Observed Electrodes": ", ".join(
                        normalization.observed_channels
                    ),
                    "Excluded Electrodes": ", ".join(
                        normalization.excluded_channels
                    ),
                    "Interpolated Electrodes": ", ".join(
                        normalization.interpolated_channels
                    ),
                    "Used Electrodes": ", ".join(normalization.used_channels),
                    "Expected Count": len(normalization.expected_channels),
                    "Observed Count": len(normalization.observed_channels),
                    "Excluded Count": len(normalization.excluded_channels),
                    "Interpolated Count": len(
                        normalization.interpolated_channels
                    ),
                    "Used Count": len(normalization.used_channels),
                    "All Members Interpolated Warning": "No",
                    "Coverage Fingerprint": normalization.fingerprint,
                }
            )
    return pd.DataFrame(rows, columns=_ROI_COVERAGE_COLUMNS)


def _clean_selection_summary_frame(
    frames: Mapping[str, pd.DataFrame],
) -> pd.DataFrame:
    frame = _selection_frame(frames, "Selection_Summary", SELECTION_SUMMARY_SHEET)
    if frame.empty:
        return pd.DataFrame(columns=["Summary Item", "Value"])
    item = _find_column(frame, "Summary Item", "Item")
    value = _find_column(frame, "Value")
    if item is None or value is None:
        return _humanize_headers(frame)
    return frame.loc[:, [item, value]].rename(columns={item: "Summary Item", value: "Value"})


def _clean_harmonic_selection_frame(
    frames: Mapping[str, pd.DataFrame],
) -> pd.DataFrame:
    frame = _selection_frame(frames, "Harmonic_Selection", HARMONIC_SELECTION_SHEET)
    if frame.empty:
        return pd.DataFrame(columns=["Harmonic (Hz)", "Included in Summed BCA"])
    rename_by_normalized = {
        _normalized_header("requested_harmonic_hz"): "Harmonic (Hz)",
        _normalized_header("requested_frequency_hz"): "Harmonic (Hz)",
        _normalized_header("z_score"): "Z Score",
        _normalized_header("target_amplitude_uv"): "Target Amplitude (uV)",
        _normalized_header("noise_mean_uv"): "Noise Mean (uV)",
        _normalized_header("noise_std_uv"): "Noise SD (uV)",
        _normalized_header("selected"): "Significant",
        _normalized_header("included_in_summation"): "Included in Summed BCA",
        _normalized_header("excluded_base_rate"): "Excluded Base Rate",
        _normalized_header("exclusion_reason"): "Exclusion Reason",
        _normalized_header("warning"): "Warning",
    }
    renamed = frame.rename(
        columns={
            column: rename_by_normalized.get(
                _normalized_header(column),
                _human_header(column),
            )
            for column in frame.columns
        }
    )
    if "Harmonic (Hz)" in renamed.columns:
        renamed["Harmonic (Hz)"] = pd.to_numeric(renamed["Harmonic (Hz)"], errors="coerce")
        renamed = renamed.sort_values("Harmonic (Hz)", kind="stable")
    return renamed.reset_index(drop=True)


def _build_analysis_notes_frame(
    *,
    selection_source: str,
    selected_harmonics: Sequence[float],
    workbook_count: int,
    roi_count: int,
    repeated_session: bool = False,
) -> pd.DataFrame:
    frequencies = ", ".join(f"{frequency:g}" for frequency in selected_harmonics)
    observed_grain = (
        "recording-condition" if repeated_session else "participant-condition"
    )
    roi_grain = (
        "participant-recording-session-condition"
        if repeated_session
        else "participant-condition"
    )
    rows = [
        (
            "Purpose",
            "Analysis-ready full-audit export for independent downstream statistics.",
        ),
        (
            "Data scope",
            f"All {workbook_count} current QC-20 released {observed_grain} workbooks were included; reviewed exclusions remain visible in coverage and audit columns.",
        ),
        (
            "ROI Long grain",
            f"One row per released {roi_grain} workbook and each of {roi_count} frozen ROIs. Accounted no-output conditions are recorded in ROI Coverage and remain blank in numerical tables.",
        ),
        (
            "Raw Summed BCA",
            "Every frozen scalp electrode required a finite BCA value at every saved selected harmonic. Harmonics were summed per electrode, then the complete frozen ROI set was averaged without dropping members.",
        ),
        (
            "RMS Normalized BCA",
            "For each participant, condition, and selected harmonic, each "
            "electrode BCA was divided by the scalp vector length "
            "sqrt(sum of squared BCA across all source electrodes). These "
            "dimensionless electrode values were then summed across harmonics "
            "and averaged within ROI, matching the sequence in Dzhelyova et "
            "al. (2017) and the vector-normalization method of McCarthy and "
            "Wood (1985).",
        ),
        (
            "RMS terminology",
            "The cited FPVS publication calls this denominator RMS, but its "
            "stated calculation is root-sum-square (scalp vector length), not "
            "the conventional root mean square. No division by electrode "
            "count was applied.",
        ),
        (
            "Signed Mean Normalized BCA",
            "Each electrode's Raw Summed BCA was divided by the signed arithmetic mean across all finite source electrodes for that participant-condition, then averaged within ROI.",
        ),
        (
            "Harmonic selection",
            f"The existing selection was consumed from {selection_source}; selection was not recomputed. Included frequencies (Hz): {frequencies}.",
        ),
        (
            "QC fields",
            "QC and current-exclusion columns are annotations only. No flagged participant, condition, ROI, or electrode was removed from this export.",
        ),
        (
            "RMS Harmonic Scales",
            "This audit sheet records the harmonic-specific scalp vector "
            "lengths used before harmonic summation. The post-sum RMS retained "
            "in Whole Scalp Values is descriptive only and was not used for "
            "normalization.",
        ),
        (
            "External analysis",
            "Review QC Flags before modeling. Missing values were left blank and were not imputed.",
        ),
    ]
    if repeated_session:
        rows.append(
            (
                "Session/phase-at-visit interpretation",
                "Session and visit identity are retained on every observation. "
                "When phase is always aligned with visit order, phase cannot be "
                "separated from elapsed time, repetition, practice, or habituation.",
            )
        )
    return pd.DataFrame(rows, columns=["Note", "Explanation"])


def _write_frames_atomically(
    target: Path,
    frames: Mapping[str, pd.DataFrame],
) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{target.stem}.",
            suffix=".tmp.xlsx",
            dir=target.parent,
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
        with pd.ExcelWriter(temporary_path, engine="openpyxl") as writer:
            for sheet_name, frame in frames.items():
                frame.to_excel(writer, sheet_name=sheet_name, index=False)
            _format_workbook(writer.book)
            writer.book.active = writer.book.sheetnames.index(ROI_LONG_SHEET)
        os.replace(temporary_path, target)
    except Exception:  # Atomic publish boundary: clean up every writer failure.
        logger.exception(
            "analysis_ready_export_write_failed",
            extra={"target": str(target)},
        )
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                logger.warning(
                    "analysis_ready_export_temp_cleanup_failed",
                    extra={"temporary_path": str(temporary_path)},
                    exc_info=True,
                )
        raise


def _format_workbook(workbook: Any) -> None:
    header_fill = PatternFill(fill_type="solid", fgColor="595959")
    stripe_fill = PatternFill(fill_type="solid", fgColor="F2F2F2")
    header_font = Font(color="FFFFFF", bold=True)
    alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for worksheet in workbook.worksheets:
        worksheet.freeze_panes = "A2"
        if worksheet.max_row >= 1 and worksheet.max_column >= 1:
            worksheet.auto_filter.ref = worksheet.dimensions
        worksheet.sheet_view.showGridLines = False
        headers = worksheet[1]
        widths = [len(str(cell.value or "")) for cell in headers]
        number_formats = []
        for cell in headers:
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = alignment
            header = str(cell.value or "")
            if any(
                token in header
                for token in (
                    "BCA", "RMS", "Signed Mean", "Amplitude",
                    "Noise Mean", "Noise SD", "Z Score",
                )
            ):
                number_formats.append("0.000000")
            elif "Hz" in header:
                number_formats.append("0.0000")
            else:
                number_formats.append(None)
        styles = {}
        for row_number, row in enumerate(
            worksheet.iter_rows(min_row=2),
            start=2,
        ):
            striped = row_number % 2 == 0
            for column_index, cell in enumerate(row):
                number_format = number_formats[column_index]
                # Reuse the complete derived style, retaining any existing
                # pandas date, font, border, or protection settings.
                key = (cell._style, striped, number_format)
                style = styles.get(key)
                if style is None:
                    cell._style = copy(cell._style)
                    cell.alignment = alignment
                    if striped:
                        cell.fill = stripe_fill
                    if number_format is not None:
                        cell.number_format = number_format
                    style = styles[key] = cell._style
                else:
                    cell._style = style
                widths[column_index] = max(
                    widths[column_index], len(str(cell.value or ""))
                )
        worksheet.row_dimensions[1].height = 30
        for column_number, max_length in enumerate(widths, start=1):
            width = min(max(max_length + 2, 12), 60)
            worksheet.column_dimensions[get_column_letter(column_number)].width = width


def _finalize_qc_flags(
    rows: Sequence[dict[str, object]],
    *,
    repeated_session: bool = False,
) -> pd.DataFrame:
    columns = (
        _session_columns(_QC_FLAG_COLUMNS)
        if repeated_session
        else _QC_FLAG_COLUMNS
    )
    if not rows:
        return pd.DataFrame(columns=columns)
    frame = pd.DataFrame(rows, columns=columns).drop_duplicates()
    sort_columns = ["PID"]
    if repeated_session:
        sort_columns.extend(["Visit Index", "Recording ID"])
    sort_columns.extend(["Condition", "ROI", "Electrode", "Flag Type"])
    return frame.sort_values(sort_columns, kind="stable", na_position="last").reset_index(drop=True)


def _append_flag(
    rows: list[dict[str, object]],
    *,
    pid: str,
    group: str,
    flag_type: str,
    flag_scope: str,
    current_exclusion: bool,
    notes: str,
    condition: str = "",
    roi: str = "",
    electrode: str = "",
) -> None:
    rows.append(
        {
            "PID": str(pid),
            "Group": str(group),
            "Condition": str(condition),
            "ROI": str(roi),
            "Electrode": str(electrode),
            "Flag Type": str(flag_type),
            "Flag Scope": str(flag_scope),
            "Current Toolbox Exclusion": _yes_no(current_exclusion),
            "QC Notes": str(notes),
        }
    )


def _group_label_lookup(
    index: ProjectDatasetIndex,
    records: Sequence[Any],
) -> dict[str, str]:
    lookup = {
        record.participant_id.casefold(): str(
            record.group_label or _SINGLE_GROUP_LABEL
        )
        for record in records
    }
    lookup.update(
        {
            str(pid).casefold(): str(label)
            for pid, label in index.participant_group_label_map().items()
        }
    )
    return lookup


def _mapping_entries(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, (list, tuple)):
        return []
    return [entry for entry in value if isinstance(entry, Mapping)]


def _find_column(frame: pd.DataFrame, *candidates: str) -> object | None:
    lookup = {_normalized_header(column): column for column in frame.columns}
    for candidate in candidates:
        column = lookup.get(_normalized_header(candidate))
        if column is not None:
            return column
    return None


def _humanize_headers(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.rename(columns={column: _human_header(column) for column in frame.columns})


def _human_header(value: object) -> str:
    text = str(value or "").strip().replace("_", " ")
    return " ".join(part.capitalize() for part in text.split())


def _normalized_header(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _frequency_list(value: object) -> list[float]:
    if isinstance(value, (list, tuple, set)):
        values = value
    else:
        values = re.findall(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)", str(value or ""))
    frequencies: list[float] = []
    for item in values:
        number = _finite_float(item)
        if number is not None and number > 0:
            frequencies.append(number)
    return frequencies


def _finite_float(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _finite_mean(values: pd.Series) -> float:
    numeric = pd.to_numeric(values, errors="coerce")
    finite = numeric[np.isfinite(numeric)]
    return float(finite.mean()) if not finite.empty else math.nan


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return bool(value)
    return str(value or "").strip().casefold() in {
        "1",
        "true",
        "yes",
        "y",
        "included",
    }


def _pid_key(value: object) -> str:
    return str(value or "").strip().casefold()


def _natural_key(value: object) -> tuple[object, ...]:
    parts = re.split(r"(\d+)", str(value or "").casefold())
    return tuple(int(part) if part.isdigit() else part for part in parts)


def _ordered_unique(values: Any) -> list[Any]:
    seen: set[Any] = set()
    result: list[Any] = []
    for value in values:
        key = value.casefold() if isinstance(value, str) else value
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _combine_notes(*groups: Sequence[str]) -> list[str]:
    return _ordered_unique(note for group in groups for note in group if str(note or "").strip())


def _yes_no(value: bool) -> str:
    return "Yes" if value else "No"


def _log_status(
    callback: Callable[[str], None] | None,
    message: str,
) -> None:
    if callback is None:
        return
    try:
        callback(str(message))
    except Exception:  # Callback boundary: status logging must not abort export.
        logger.warning("analysis_ready_export_log_callback_failed", exc_info=True)


__all__ = [
    "ANALYSIS_READY_RELATIVE_PATH",
    "ANALYSIS_READY_WORKBOOK_NAME",
    "AnalysisReadyWorkbookResult",
    "default_analysis_ready_workbook_path",
    "export_analysis_ready_workbook",
    "write_analysis_ready_workbook",
]
