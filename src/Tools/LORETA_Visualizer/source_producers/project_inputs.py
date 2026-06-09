"""Read source-ready FPVS topographies from an existing project.

This module is the Phase 6B bridge from project workbook outputs to source
producer inputs. It reads existing files only and returns condition topographies
for calculation producers. It does not render, import GUI payloads, write
project files, or change preprocessing/Stats behavior.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np
import openpyxl
import pandas as pd

from config import DEFAULT_ELECTRODE_NAMES_64
from Tools.LORETA_Visualizer.source_producers.l2_mne_cortical import L2MNEFPVSCondition

SOURCE_TOPOGRAPHY_METRIC_BCA = "bca"
SOURCE_TOPOGRAPHY_METRIC_FFT_AMPLITUDE = "fft_amplitude"

_METRIC_TO_SHEET = {
    SOURCE_TOPOGRAPHY_METRIC_BCA: "BCA (uV)",
    SOURCE_TOPOGRAPHY_METRIC_FFT_AMPLITUDE: "FFT Amplitude (uV)",
}


@dataclass(frozen=True)
class ProjectConditionTopographySummary:
    """Read-only assembly summary for one condition."""

    condition: str
    workbook_count: int
    included_subject_count: int
    included_subjects: tuple[str, ...]
    flagged_subjects: tuple[str, ...]


@dataclass(frozen=True)
class ProjectSourceTopographyInputSet:
    """Source-ready topographies assembled from project workbooks."""

    project_root: Path
    metric: str
    sheet_name: str
    selected_harmonics_hz: tuple[float, ...]
    electrode_names: tuple[str, ...]
    conditions: tuple[L2MNEFPVSCondition, ...]
    summaries: tuple[ProjectConditionTopographySummary, ...]
    excluded_subjects: tuple[str, ...]
    flagged_subjects: tuple[str, ...]
    diagnostics: tuple[str, ...]


def build_l2_mne_conditions_from_project(
    project_root: str | Path,
    *,
    metric: str = SOURCE_TOPOGRAPHY_METRIC_BCA,
    conditions: Sequence[str] | None = None,
    include_flagged_subjects: bool = False,
) -> ProjectSourceTopographyInputSet:
    """Build group-level condition topographies from existing project workbooks.

    The returned ``L2MNEFPVSCondition`` objects are source-ready inputs for the
    beta L2-MNE producer. Each harmonic topography is a 64-channel group mean
    over included participants.
    """
    root = Path(project_root)
    if not root.is_dir():
        raise FileNotFoundError(f"Project root does not exist: {root}")
    sheet_name = _sheet_for_metric(metric)
    stats_ready = root / "3 - Statistical Analysis Results" / "Stats_Ready_Summed_BCA.xlsx"
    selected_harmonics = _read_selected_harmonics(stats_ready)
    requested_conditions = _resolve_conditions(stats_ready, conditions=conditions)
    excluded_subjects = _read_subject_list(root / "3 - Statistical Analysis Results" / "Excluded Participants.xlsx")
    flagged_subjects = _read_subject_list(root / "3 - Statistical Analysis Results" / "Flagged Participants.xlsx")
    excluded_lookup = set(excluded_subjects)
    if not include_flagged_subjects:
        excluded_lookup.update(flagged_subjects)

    expected_electrodes = tuple(name.upper() for name in DEFAULT_ELECTRODE_NAMES_64)
    diagnostics: list[str] = []
    source_conditions: list[L2MNEFPVSCondition] = []
    summaries: list[ProjectConditionTopographySummary] = []
    for condition in requested_conditions:
        condition_dir = root / "1 - Excel Data Files" / condition
        if not condition_dir.is_dir():
            diagnostics.append(f"Missing condition workbook folder: {condition}")
            continue
        workbooks = _condition_workbook_paths(condition_dir)
        harmonic_vectors: dict[float, list[np.ndarray]] = {harmonic: [] for harmonic in selected_harmonics}
        included_subjects: list[str] = []
        for workbook_path in workbooks:
            subject_id = _subject_from_workbook_name(workbook_path.name)
            if subject_id in excluded_lookup:
                continue
            sheet_values = _read_metric_sheet(
                workbook_path,
                sheet_name=sheet_name,
                selected_harmonics=selected_harmonics,
                expected_electrodes=expected_electrodes,
            )
            included_subjects.append(subject_id)
            for harmonic, vector in sheet_values.items():
                harmonic_vectors[harmonic].append(vector)
        if not included_subjects:
            diagnostics.append(f"No included workbooks for condition: {condition}")
            continue
        harmonic_topographies = {
            harmonic: np.mean(np.vstack(vectors), axis=0).astype(float)
            for harmonic, vectors in harmonic_vectors.items()
            if vectors
        }
        if set(harmonic_topographies) != set(selected_harmonics):
            missing = sorted(set(selected_harmonics) - set(harmonic_topographies))
            diagnostics.append(f"Condition {condition!r} is missing harmonic topographies: {missing}")
            continue
        condition_flagged = tuple(subject for subject in included_subjects if subject in flagged_subjects)
        source_conditions.append(
            L2MNEFPVSCondition(
                condition_id=condition,
                label=condition,
                harmonic_topographies=harmonic_topographies,
                sensor_value_unit=_sensor_value_unit(metric),
                metadata={
                    "project_root_name": root.name,
                    "metric": metric,
                    "source_sheet": sheet_name,
                    "selected_harmonics_hz": list(selected_harmonics),
                    "included_subject_count": len(included_subjects),
                    "include_flagged_subjects": include_flagged_subjects,
                    "flagged_subjects_included": list(condition_flagged),
                    "source_ready_input": True,
                    "project_input_assembly": "phase_6b_read_only",
                },
            )
        )
        summaries.append(
            ProjectConditionTopographySummary(
                condition=condition,
                workbook_count=len(workbooks),
                included_subject_count=len(included_subjects),
                included_subjects=tuple(included_subjects),
                flagged_subjects=condition_flagged,
            )
        )

    return ProjectSourceTopographyInputSet(
        project_root=root,
        metric=metric,
        sheet_name=sheet_name,
        selected_harmonics_hz=selected_harmonics,
        electrode_names=expected_electrodes,
        conditions=tuple(source_conditions),
        summaries=tuple(summaries),
        excluded_subjects=tuple(excluded_subjects),
        flagged_subjects=tuple(flagged_subjects),
        diagnostics=tuple(diagnostics),
    )


def _sheet_for_metric(metric: str) -> str:
    normalized = str(metric).strip().lower()
    if normalized not in _METRIC_TO_SHEET:
        raise ValueError(f"Unsupported source topography metric: {metric!r}.")
    return _METRIC_TO_SHEET[normalized]


def _sensor_value_unit(metric: str) -> str:
    if metric == SOURCE_TOPOGRAPHY_METRIC_BCA:
        return "summed BCA uV"
    return "summed FFT amplitude uV"


def _condition_workbook_paths(condition_dir: Path) -> tuple[Path, ...]:
    """Return flat and condition/group participant workbook paths."""
    paths = [
        path
        for pattern in ("*.xlsx", "*/*.xlsx")
        for path in condition_dir.glob(pattern)
        if path.is_file() and not path.name.startswith("~$")
    ]
    return tuple(sorted(paths))


def _read_selected_harmonics(stats_ready_path: Path) -> tuple[float, ...]:
    if not stats_ready_path.is_file():
        raise FileNotFoundError(f"Stats-ready workbook is required for selected harmonics: {stats_ready_path}")
    harmonic_df = pd.read_excel(stats_ready_path, sheet_name="Harmonic_Selection")
    if "selected" not in harmonic_df.columns or "harmonic_hz" not in harmonic_df.columns:
        raise ValueError("Stats-ready Harmonic_Selection sheet must include 'selected' and 'harmonic_hz'.")
    selected = harmonic_df.loc[harmonic_df["selected"] == True, "harmonic_hz"].dropna()  # noqa: E712
    harmonics = tuple(round(float(value), 4) for value in selected)
    if not harmonics:
        raise ValueError("Stats-ready workbook has no selected harmonics.")
    return harmonics


def _resolve_conditions(stats_ready_path: Path, *, conditions: Sequence[str] | None) -> tuple[str, ...]:
    if conditions is not None:
        resolved = tuple(str(condition).strip() for condition in conditions if str(condition).strip())
        if not resolved:
            raise ValueError("At least one condition is required.")
        return resolved
    long_df = pd.read_excel(stats_ready_path, sheet_name="Long_Format", usecols=["condition"])
    resolved = tuple(sorted(str(condition) for condition in long_df["condition"].dropna().unique()))
    if not resolved:
        raise ValueError("Stats-ready Long_Format sheet did not contain conditions.")
    return resolved


def _read_subject_list(path: Path) -> tuple[str, ...]:
    if not path.is_file():
        return ()
    try:
        df = pd.read_excel(path, sheet_name=0)
    except Exception:
        return ()
    if "participant_id" not in df.columns:
        return ()
    subjects = {_normalize_subject_id(value) for value in df["participant_id"].dropna()}
    return tuple(sorted(subject for subject in subjects if subject))


def _read_metric_sheet(
    workbook_path: Path,
    *,
    sheet_name: str,
    selected_harmonics: tuple[float, ...],
    expected_electrodes: tuple[str, ...],
) -> dict[float, np.ndarray]:
    columns = ["Electrode", *(f"{harmonic:.4f}_Hz" for harmonic in selected_harmonics)]
    workbook = openpyxl.load_workbook(workbook_path, read_only=True, data_only=True)
    try:
        worksheet = workbook[sheet_name]
        rows = worksheet.iter_rows(values_only=True)
        header = [str(value) if value is not None else "" for value in next(rows)]
        indexes = _column_indexes(header, columns, workbook_path=workbook_path, sheet_name=sheet_name)
        data: list[list[object]] = []
        for row in rows:
            if row is None or row[indexes[0]] is None:
                continue
            data.append([row[index] for index in indexes])
    finally:
        workbook.close()

    frame = pd.DataFrame(data, columns=columns)
    if len(frame) != len(expected_electrodes):
        raise ValueError(f"{workbook_path.name} {sheet_name} expected {len(expected_electrodes)} electrode rows.")
    electrodes = tuple(str(value).upper() for value in frame["Electrode"].tolist())
    if electrodes != expected_electrodes:
        raise ValueError(f"{workbook_path.name} {sheet_name} does not match the expected BioSemi64 electrode order.")
    values = frame[columns[1:]].to_numpy(dtype=float)
    if not np.all(np.isfinite(values)):
        raise ValueError(f"{workbook_path.name} {sheet_name} contains non-finite source topography values.")
    return {
        harmonic: values[:, index].astype(float)
        for index, harmonic in enumerate(selected_harmonics)
    }


def _column_indexes(
    header: Sequence[str],
    columns: Sequence[str],
    *,
    workbook_path: Path,
    sheet_name: str,
) -> list[int]:
    indexes: list[int] = []
    missing: list[str] = []
    for column in columns:
        if column in header:
            indexes.append(header.index(column))
        else:
            missing.append(column)
    if missing:
        raise ValueError(f"{workbook_path.name} {sheet_name} is missing columns: {', '.join(missing)}")
    return indexes


def _subject_from_workbook_name(file_name: str) -> str:
    prefix = file_name.split("_", 1)[0]
    return _normalize_subject_id(prefix)


def _normalize_subject_id(value: object) -> str:
    text = str(value).strip().upper()
    if not text:
        return ""
    match = re.search(r"(\d+)$", text)
    if match:
        return f"P{int(match.group(1))}"
    return text
