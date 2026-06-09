"""Read FullFFT target and neighboring-bin topographies for source z-scores.

This Phase 6D project adapter reads existing project workbooks only. It does
not write project files, change preprocessing/Stats exports, calculate inverse
solutions, or render payloads.
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
from Tools.LORETA_Visualizer.source_producers.l2_mne_hauk_zscore import (
    DEFAULT_HAUK_ZSCORE_EXCLUDED_OFFSETS,
    DEFAULT_HAUK_ZSCORE_MIN_NOISE_BINS,
    DEFAULT_HAUK_ZSCORE_NOISE_WINDOW_BINS,
    L2MNEHaukHarmonicBins,
    L2MNEHaukZScoreCondition,
)
from Tools.LORETA_Visualizer.source_producers.project_inputs import (
    ProjectConditionTopographySummary,
    _condition_workbook_paths,
    _read_selected_harmonics,
    _read_subject_list,
    _resolve_conditions,
    _subject_from_workbook_name,
)

FULL_FFT_AMPLITUDE_SHEET_NAME = "FullFFT Amplitude (uV)"
FREQUENCY_COLUMN_PATTERN = re.compile(r"^(-?\d+(?:\.\d+)?)_Hz$")


class ProjectFullFftInputError(RuntimeError):
    """Raised when project FullFFT inputs cannot support source z-scores."""


@dataclass(frozen=True)
class ProjectFullFftNoiseBinPlan:
    """One neighboring-bin column used for source-space z-score noise."""

    offset: int
    bin_index: int
    frequency_hz: float
    column: str


@dataclass(frozen=True)
class ProjectFullFftHarmonicBinPlan:
    """FullFFT target and neighboring-bin read plan for one selected harmonic."""

    harmonic_hz: float
    target_bin_index: int
    target_frequency_hz: float
    target_column: str
    noise_bins: tuple[ProjectFullFftNoiseBinPlan, ...]

    @property
    def required_columns(self) -> tuple[str, ...]:
        """Return target and neighboring-bin columns for this harmonic."""
        return (self.target_column, *(noise.column for noise in self.noise_bins))


@dataclass(frozen=True)
class ProjectFullFftBinPlan:
    """FullFFT read plan shared by all included workbooks."""

    harmonic_plans: tuple[ProjectFullFftHarmonicBinPlan, ...]
    frequency_resolution_hz: float | None
    noise_window_bins: int
    excluded_offsets: tuple[int, ...]
    min_noise_bins: int

    @property
    def required_columns(self) -> tuple[str, ...]:
        """Return de-duplicated FullFFT columns required by the plan."""
        out: list[str] = []
        seen: set[str] = set()
        for harmonic in self.harmonic_plans:
            for column in harmonic.required_columns:
                if column not in seen:
                    out.append(column)
                    seen.add(column)
        return tuple(out)


@dataclass(frozen=True)
class ProjectSourceFrequencyBinInputSet:
    """Source z-score-ready condition inputs assembled from FullFFT workbooks."""

    project_root: Path
    sheet_name: str
    selected_harmonics_hz: tuple[float, ...]
    electrode_names: tuple[str, ...]
    conditions: tuple[L2MNEHaukZScoreCondition, ...]
    summaries: tuple[ProjectConditionTopographySummary, ...]
    excluded_subjects: tuple[str, ...]
    flagged_subjects: tuple[str, ...]
    bin_plan: ProjectFullFftBinPlan
    diagnostics: tuple[str, ...]


@dataclass(frozen=True)
class _WorkbookFullFftTopographies:
    plan: ProjectFullFftBinPlan
    target_by_harmonic: dict[float, np.ndarray]
    noise_by_harmonic_offset: dict[float, dict[int, np.ndarray]]


def build_l2_mne_hauk_zscore_conditions_from_project(
    project_root: str | Path,
    *,
    conditions: Sequence[str] | None = None,
    include_flagged_subjects: bool = False,
    noise_window_bins: int = DEFAULT_HAUK_ZSCORE_NOISE_WINDOW_BINS,
    excluded_offsets: Sequence[int] = DEFAULT_HAUK_ZSCORE_EXCLUDED_OFFSETS,
    min_noise_bins: int = DEFAULT_HAUK_ZSCORE_MIN_NOISE_BINS,
) -> ProjectSourceFrequencyBinInputSet:
    """Build group-level target/noise FullFFT topographies for source z-scores."""
    root = Path(project_root)
    if not root.is_dir():
        raise FileNotFoundError(f"Project root does not exist: {root}")
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
    source_conditions: list[L2MNEHaukZScoreCondition] = []
    summaries: list[ProjectConditionTopographySummary] = []
    shared_plan: ProjectFullFftBinPlan | None = None
    excluded_offsets_tuple = tuple(sorted({int(offset) for offset in excluded_offsets}))

    for condition in requested_conditions:
        condition_dir = root / "1 - Excel Data Files" / condition
        if not condition_dir.is_dir():
            diagnostics.append(f"Missing condition workbook folder: {condition}")
            continue
        workbooks = _condition_workbook_paths(condition_dir)
        target_vectors: dict[float, list[np.ndarray]] = {harmonic: [] for harmonic in selected_harmonics}
        noise_vectors: dict[float, dict[int, list[np.ndarray]]] = {harmonic: {} for harmonic in selected_harmonics}
        included_subjects: list[str] = []
        condition_plan: ProjectFullFftBinPlan | None = None
        for workbook_path in workbooks:
            subject_id = _subject_from_workbook_name(workbook_path.name)
            if subject_id in excluded_lookup:
                continue
            workbook_values = _read_fullfft_topographies(
                workbook_path,
                selected_harmonics=selected_harmonics,
                expected_electrodes=expected_electrodes,
                plan=shared_plan,
                noise_window_bins=int(noise_window_bins),
                excluded_offsets=excluded_offsets_tuple,
                min_noise_bins=int(min_noise_bins),
            )
            if shared_plan is None:
                shared_plan = workbook_values.plan
            if condition_plan is None:
                condition_plan = workbook_values.plan
            elif condition_plan != workbook_values.plan:
                raise ProjectFullFftInputError(
                    f"{workbook_path.name} has a different FullFFT target/noise-bin plan."
                )
            included_subjects.append(subject_id)
            for harmonic in selected_harmonics:
                target_vectors[harmonic].append(workbook_values.target_by_harmonic[harmonic])
                for offset, vector in workbook_values.noise_by_harmonic_offset[harmonic].items():
                    noise_vectors[harmonic].setdefault(offset, []).append(vector)
        if not included_subjects:
            diagnostics.append(f"No included workbooks for condition: {condition}")
            continue
        if condition_plan is None:
            raise ProjectFullFftInputError(f"No FullFFT bin plan was assembled for condition: {condition}")

        harmonic_bins: dict[float, L2MNEHaukHarmonicBins] = {}
        plan_by_harmonic = {plan.harmonic_hz: plan for plan in condition_plan.harmonic_plans}
        for harmonic in selected_harmonics:
            plan = plan_by_harmonic[harmonic]
            noise_means: dict[int, np.ndarray] = {}
            for noise in plan.noise_bins:
                vectors = noise_vectors[harmonic].get(noise.offset, [])
                if len(vectors) != len(included_subjects):
                    raise ProjectFullFftInputError(
                        f"Condition {condition!r} harmonic {harmonic:g} Hz offset {noise.offset} "
                        "is missing participant topographies."
                    )
                noise_means[noise.offset] = np.mean(np.vstack(vectors), axis=0).astype(float)
            harmonic_bins[harmonic] = L2MNEHaukHarmonicBins(
                harmonic_hz=harmonic,
                target_topography=np.mean(np.vstack(target_vectors[harmonic]), axis=0).astype(float),
                target_frequency_hz=plan.target_frequency_hz,
                target_bin_index=plan.target_bin_index,
                target_column=plan.target_column,
                noise_topographies_by_offset=noise_means,
                noise_frequencies_hz_by_offset={noise.offset: noise.frequency_hz for noise in plan.noise_bins},
                noise_bin_indices_by_offset={noise.offset: noise.bin_index for noise in plan.noise_bins},
                noise_columns_by_offset={noise.offset: noise.column for noise in plan.noise_bins},
            )

        condition_flagged = tuple(subject for subject in included_subjects if subject in flagged_subjects)
        source_conditions.append(
            L2MNEHaukZScoreCondition(
                condition_id=condition,
                label=condition,
                harmonic_bins=harmonic_bins,
                sensor_value_unit="raw FFT amplitude uV",
                metadata={
                    "project_root_name": root.name,
                    "source_sheet": FULL_FFT_AMPLITUDE_SHEET_NAME,
                    "selected_harmonics_hz": list(selected_harmonics),
                    "included_subject_count": len(included_subjects),
                    "include_flagged_subjects": include_flagged_subjects,
                    "flagged_subjects_included": list(condition_flagged),
                    "source_ready_input": True,
                    "project_input_assembly": "phase_6d_fullfft_neighbor_bins_read_only",
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

    if shared_plan is None:
        raise ProjectFullFftInputError("No included FullFFT workbooks were found for source-space z-score assembly.")

    return ProjectSourceFrequencyBinInputSet(
        project_root=root,
        sheet_name=FULL_FFT_AMPLITUDE_SHEET_NAME,
        selected_harmonics_hz=selected_harmonics,
        electrode_names=expected_electrodes,
        conditions=tuple(source_conditions),
        summaries=tuple(summaries),
        excluded_subjects=tuple(excluded_subjects),
        flagged_subjects=tuple(flagged_subjects),
        bin_plan=shared_plan,
        diagnostics=tuple(diagnostics),
    )


def _read_fullfft_topographies(
    workbook_path: Path,
    *,
    selected_harmonics: tuple[float, ...],
    expected_electrodes: tuple[str, ...],
    plan: ProjectFullFftBinPlan | None,
    noise_window_bins: int,
    excluded_offsets: tuple[int, ...],
    min_noise_bins: int,
) -> _WorkbookFullFftTopographies:
    workbook = openpyxl.load_workbook(workbook_path, read_only=True, data_only=True)
    try:
        try:
            worksheet = workbook[FULL_FFT_AMPLITUDE_SHEET_NAME]
        except KeyError as exc:
            raise ProjectFullFftInputError(
                f"Phase 6D source-space z-score mode requires the "
                f"'{FULL_FFT_AMPLITUDE_SHEET_NAME}' sheet in every included participant workbook. "
                f"Missing in: {workbook_path.name}."
            ) from exc
        rows = worksheet.iter_rows(values_only=True)
        try:
            header = [str(value) if value is not None else "" for value in next(rows)]
        except StopIteration as exc:
            raise ProjectFullFftInputError(f"{workbook_path.name} FullFFT sheet is empty.") from exc
        workbook_plan = plan or _build_fullfft_bin_plan(
            header,
            selected_harmonics=selected_harmonics,
            workbook_path=workbook_path,
            noise_window_bins=noise_window_bins,
            excluded_offsets=excluded_offsets,
            min_noise_bins=min_noise_bins,
        )
        if plan is not None:
            _validate_fullfft_plan_columns(header, plan=plan, workbook_path=workbook_path)
        columns = ("Electrode", *workbook_plan.required_columns)
        indexes = _column_indexes(header, columns, workbook_path=workbook_path)
        data: list[list[object]] = []
        for row in rows:
            if row is None or row[indexes[0]] is None:
                continue
            data.append([row[index] for index in indexes])
    finally:
        workbook.close()

    frame = pd.DataFrame(data, columns=columns)
    if len(frame) != len(expected_electrodes):
        raise ProjectFullFftInputError(
            f"{workbook_path.name} {FULL_FFT_AMPLITUDE_SHEET_NAME} expected "
            f"{len(expected_electrodes)} electrode rows."
        )
    electrodes = tuple(str(value).strip().upper() for value in frame["Electrode"].tolist())
    if electrodes != expected_electrodes:
        raise ProjectFullFftInputError(
            f"{workbook_path.name} {FULL_FFT_AMPLITUDE_SHEET_NAME} does not match the expected BioSemi64 electrode order."
        )
    values = frame[list(workbook_plan.required_columns)].to_numpy(dtype=float)
    if not np.all(np.isfinite(values)):
        raise ProjectFullFftInputError(f"{workbook_path.name} FullFFT source z-score columns contain non-finite values.")

    column_data = {
        column: values[:, column_index].astype(float)
        for column_index, column in enumerate(workbook_plan.required_columns)
    }
    target_by_harmonic: dict[float, np.ndarray] = {}
    noise_by_harmonic_offset: dict[float, dict[int, np.ndarray]] = {}
    for harmonic_plan in workbook_plan.harmonic_plans:
        harmonic = harmonic_plan.harmonic_hz
        target_by_harmonic[harmonic] = column_data[harmonic_plan.target_column]
        noise_by_harmonic_offset[harmonic] = {
            noise.offset: column_data[noise.column]
            for noise in harmonic_plan.noise_bins
        }
    return _WorkbookFullFftTopographies(
        plan=workbook_plan,
        target_by_harmonic=target_by_harmonic,
        noise_by_harmonic_offset=noise_by_harmonic_offset,
    )


def _build_fullfft_bin_plan(
    header: Sequence[str],
    *,
    selected_harmonics: tuple[float, ...],
    workbook_path: Path,
    noise_window_bins: int,
    excluded_offsets: tuple[int, ...],
    min_noise_bins: int,
) -> ProjectFullFftBinPlan:
    frequency_columns = _parse_frequency_columns(header)
    if not frequency_columns:
        raise ProjectFullFftInputError(
            f"Phase 6D source-space z-score mode found no frequency columns in "
            f"'{FULL_FFT_AMPLITUDE_SHEET_NAME}' for {workbook_path.name}."
        )
    column_by_bin = {int(bin_index): column for _freq, column, bin_index in frequency_columns}
    frequency_by_bin = {int(bin_index): float(freq) for freq, _column, bin_index in frequency_columns}
    available_indices = set(column_by_bin)
    harmonic_plans: list[ProjectFullFftHarmonicBinPlan] = []
    for harmonic in selected_harmonics:
        match = _find_exact_frequency_column(frequency_columns, harmonic)
        if match is None:
            raise ProjectFullFftInputError(
                "Phase 6D source-space z-score mode requires exact selected harmonic "
                f"columns in FullFFT. Missing {harmonic:.4f}_Hz in {workbook_path.name}."
            )
        target_frequency, target_column, target_bin_index = match
        noise_bins: list[ProjectFullFftNoiseBinPlan] = []
        for noise_index in _noise_indices_for_bin(
            target_bin_index,
            available_indices=available_indices,
            window_size=noise_window_bins,
        ):
            offset = int(noise_index) - int(target_bin_index)
            if offset in excluded_offsets:
                continue
            noise_bins.append(
                ProjectFullFftNoiseBinPlan(
                    offset=offset,
                    bin_index=int(noise_index),
                    frequency_hz=float(frequency_by_bin[noise_index]),
                    column=str(column_by_bin[noise_index]),
                )
            )
        if len(noise_bins) < min_noise_bins:
            raise ProjectFullFftInputError(
                f"Phase 6D source-space z-score mode requires at least {min_noise_bins} "
                f"neighboring FullFFT bins around {harmonic:g} Hz; found {len(noise_bins)} "
                f"in {workbook_path.name}."
            )
        harmonic_plans.append(
            ProjectFullFftHarmonicBinPlan(
                harmonic_hz=float(harmonic),
                target_bin_index=int(target_bin_index),
                target_frequency_hz=float(target_frequency),
                target_column=str(target_column),
                noise_bins=tuple(noise_bins),
            )
        )
    return ProjectFullFftBinPlan(
        harmonic_plans=tuple(harmonic_plans),
        frequency_resolution_hz=_frequency_resolution([freq for freq, _column, _idx in frequency_columns]),
        noise_window_bins=int(noise_window_bins),
        excluded_offsets=tuple(excluded_offsets),
        min_noise_bins=int(min_noise_bins),
    )


def _validate_fullfft_plan_columns(
    header: Sequence[str],
    *,
    plan: ProjectFullFftBinPlan,
    workbook_path: Path,
) -> None:
    missing = [column for column in plan.required_columns if column not in header]
    if missing:
        raise ProjectFullFftInputError(
            f"{workbook_path.name} is missing Phase 6D FullFFT source z-score columns: "
            f"{', '.join(missing[:8])}"
        )


def _parse_frequency_columns(columns: Sequence[object]) -> list[tuple[float, str, int]]:
    out: list[tuple[float, str, int]] = []
    frequency_index = 0
    for column_name in columns:
        if not isinstance(column_name, str):
            continue
        match = FREQUENCY_COLUMN_PATTERN.match(column_name)
        if match is None:
            continue
        try:
            out.append((float(match.group(1)), column_name, frequency_index))
            frequency_index += 1
        except ValueError:
            continue
    return sorted(out, key=lambda item: item[0])


def _find_exact_frequency_column(
    frequency_columns: Sequence[tuple[float, str, int]],
    target_frequency_hz: float,
) -> tuple[float, str, int] | None:
    for frequency, column, bin_index in frequency_columns:
        if abs(float(frequency) - float(target_frequency_hz)) <= 1e-9:
            return float(frequency), str(column), int(bin_index)
    return None


def _noise_indices_for_bin(
    target_index: int,
    *,
    available_indices: set[int],
    window_size: int,
) -> list[int]:
    low = max(0, int(target_index) - int(window_size))
    high = int(target_index) + int(window_size)
    excluded = {int(target_index) - 1, int(target_index), int(target_index) + 1}
    return [
        index
        for index in range(low, high + 1)
        if index in available_indices and index not in excluded
    ]


def _frequency_resolution(frequencies: Sequence[float]) -> float | None:
    unique = sorted(set(float(frequency) for frequency in frequencies))
    if len(unique) < 2:
        return None
    diffs = np.diff(np.asarray(unique, dtype=float))
    diffs = diffs[np.isfinite(diffs) & (diffs > 0)]
    if diffs.size == 0:
        return None
    return float(np.median(diffs))


def _column_indexes(
    header: Sequence[str],
    columns: Sequence[str],
    *,
    workbook_path: Path,
) -> list[int]:
    indexes: list[int] = []
    missing: list[str] = []
    for column in columns:
        if column in header:
            indexes.append(header.index(column))
        else:
            missing.append(column)
    if missing:
        raise ProjectFullFftInputError(
            f"{workbook_path.name} {FULL_FFT_AMPLITUDE_SHEET_NAME} is missing columns: {', '.join(missing)}"
        )
    return indexes
