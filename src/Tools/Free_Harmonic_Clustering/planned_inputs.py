"""Source-immutable preparation for the versioned FHC analysis plan."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter
from typing import Callable

import numpy as np

from config import DEFAULT_ELECTRODE_NAMES_64

from . import inputs
from .analysis_plan import AnalysisFamily, AnalysisPlan, PlannedComparison, build_analysis_plan
from .models import (
    CohortWorkbook,
    FreeHarmonicInputError,
    FreeHarmonicMethodSpec,
    FrequencyWindowPlan,
    HarmonicSelection,
    ParticipantConditionExclusion,
    PreparationProvenance,
    PreparedContrast,
    ProjectContrastRequest,
    RepeatedSessionCohortAuditRow,
    SharedHarmonicSelectionAudit,
)
from .preparation import (
    build_frequency_window_plan,
    compute_participant_snr,
    l2_normalize_snr,
    select_harmonics_across_cells,
    select_snr_harmonics,
)


@dataclass(frozen=True, slots=True)
class PreparedAnalysisPlan:
    plan: AnalysisPlan
    method: FreeHarmonicMethodSpec
    contrasts: tuple[PreparedContrast, ...]
    shared_selection: HarmonicSelection
    shared_selection_audit: SharedHarmonicSelectionAudit
    frequency_plan: FrequencyWindowPlan
    provenance: PreparationProvenance
    source_workbooks: tuple[CohortWorkbook, ...]
    cohort_audit: tuple[RepeatedSessionCohortAuditRow, ...]

    def __post_init__(self) -> None:
        if len(self.contrasts) != len(self.plan.comparisons):
            raise ValueError("Every planned comparison must have one prepared contrast.")
        if any(row.project_root != self.plan.project_root for row in self.contrasts):
            raise ValueError("Prepared comparisons must belong to the plan's managed project.")
        for comparison, contrast in zip(self.plan.comparisons, self.contrasts, strict=True):
            if contrast.request != _request(self.plan, comparison):
                raise ValueError("Prepared contrast request does not match its planned comparison order and identity.")
            if contrast.method != self.method:
                raise ValueError("Prepared comparisons must share the frozen plan method.")
            if (
                contrast.frequency_plan.grid_fingerprint != self.frequency_plan.grid_fingerprint
                or contrast.provenance.shared_domain_fingerprint != self.provenance.shared_domain_fingerprint
                or not np.array_equal(contrast.harmonic_orders, self.shared_selection.selected_orders)
                or not np.array_equal(contrast.harmonics_hz, self.shared_selection.selected_harmonics_hz)
                or contrast.sensor_names != self.contrasts[0].sensor_names
            ):
                raise ValueError("Prepared comparisons must share the frozen grid, domain, and sensor set.")

    @property
    def project_root(self) -> Path:
        return self.plan.project_root

    @property
    def shared_domain_fingerprint(self) -> str:
        return self.provenance.shared_domain_fingerprint


@dataclass(frozen=True, slots=True)
class _Arm:
    label: str
    participants: tuple[str, ...]
    # Each participant has one source, or two ordered visit sources.
    samples: tuple[tuple[object, ...], ...]


def _request(plan: AnalysisPlan, comparison: PlannedComparison) -> ProjectContrastRequest:
    return ProjectContrastRequest(
        project_root=plan.project_root,
        design=comparison.design,
        condition_a=comparison.condition_a,
        condition_b=comparison.condition_b,
        group_ids=comparison.group_ids,
        session_ids=comparison.session_ids,
        contrast_family_id=comparison.comparison_id if comparison.session_ids else None,
    )


def _comparison_arms(
    plan: AnalysisPlan, index: object
) -> tuple[tuple[tuple[_Arm, _Arm], ...], object | None, tuple[object, ...]]:
    """Resolve all eligibility before any amplitude read; no dropped tests."""
    groups = dict(zip(plan.group_ids, plan.group_labels, strict=True))
    arms: list[tuple[_Arm, _Arm]] = []
    flat_cohorts: list[object] = []
    repeated = None
    if plan.session_ids:
        repeated = inputs._select_repeated_batch_cohort(
            index,
            plan,
            plan.project_root,
            validate_electrodes=False,
        )

        def participants(group: str, condition: str) -> tuple[str, ...]:
            return repeated.complete_participants[(condition.casefold(), group.casefold())]

        def arm(group: str, condition: str, cohort: tuple[str, ...], sessions: tuple[str, ...], label: str) -> _Arm:
            return _Arm(
                label,
                cohort,
                tuple(
                    tuple(
                        repeated.record_by_cell[(pid.casefold(), visit.casefold(), condition.casefold())]
                        for visit in sessions
                    )
                    for pid in cohort
                ),
            )

        for comparison in plan.comparisons:
            a = comparison.condition_a
            if comparison.kind is AnalysisFamily.WITHIN_GROUP_VISITS:
                group = comparison.group_ids[0]
                cohort = participants(group, a)
                arms.append(
                    tuple(
                        arm(group, a, cohort, (visit,), label)
                        for visit, label in zip(plan.session_ids, plan.session_labels, strict=True)
                    )
                )
            elif comparison.kind is AnalysisFamily.BETWEEN_CONDITIONS:
                group = comparison.group_ids[0]
                b = str(comparison.condition_b)
                common = {pid.casefold() for pid in participants(group, b)}
                cohort = tuple(pid for pid in participants(group, a) if pid.casefold() in common)
                arms.append((arm(group, a, cohort, plan.session_ids, a), arm(group, b, cohort, plan.session_ids, b)))
            else:
                arms.append(
                    tuple(
                        arm(
                            group,
                            a,
                            participants(group, a),
                            plan.session_ids,
                            groups[group]
                            + (
                                ": " + " - ".join(plan.session_labels)
                                if comparison.kind is AnalysisFamily.GROUP_VISIT_CHANGE
                                else ""
                            ),
                        )
                        for group in comparison.group_ids
                    )
                )
    else:
        excluded = {row.recording_id.casefold() for row in plan.recording_exclusions}
        filtered_index = (
            replace(
                index,
                workbooks=tuple(
                    row for row in index.workbooks if str(row.recording_id or "").casefold() not in excluded
                ),
                excluded_workbooks=(
                    *index.excluded_workbooks,
                    *(row for row in index.workbooks if str(row.recording_id or "").casefold() in excluded),
                ),
            )
            if excluded
            else index
        )
        for comparison in plan.comparisons:
            cohort = inputs._select_cohort(filtered_index, _request(plan, comparison), plan.project_root)
            flat_cohorts.append(cohort)
            arms.append(
                tuple(
                    _Arm(label, tuple(row.participant_id for row in records), tuple((row,) for row in records))
                    for label, records in (
                        (cohort.arm_a_label, cohort.arm_a_records),
                        (cohort.arm_b_label, cohort.arm_b_records),
                    )
                )
            )
    for comparison, (arm_a, arm_b) in zip(plan.comparisons, arms, strict=True):
        if len(arm_a.participants) < 2 or len(arm_b.participants) < 2:
            raise FreeHarmonicInputError(
                f"The complete analysis plan cannot run: {comparison.label} has eligible n={len(arm_a.participants)} and n={len(arm_b.participants)}. "
                "At least two participants per arm are required. No planned comparisons were removed."
            )
    return tuple(arms), repeated, tuple(flat_cohorts)


def _validate_retained_electrodes(project_root: Path, records: tuple[object, ...]) -> None:
    qc = inputs._reviewed_frequency_qc(project_root)
    participants = inputs._condition_electrode_map(qc.excluded_electrodes_by_participant_condition)
    recordings = inputs._condition_electrode_map(qc.excluded_electrodes_by_recording_condition)
    invalid = []
    for record in records:
        condition = record.condition.casefold()
        excluded = set(participants.get((record.participant_id.casefold(), condition), ()))
        excluded.update(recordings.get((str(record.recording_id or "").casefold(), condition), ()))
        if excluded:
            invalid.append(
                f"{record.recording_id or record.participant_id} / {record.condition}: {', '.join(sorted(excluded))}"
            )
    if invalid:
        raise FreeHarmonicInputError(
            "Free Harmonic Clustering requires the complete BioSemi64 sensor domain; retained inputs have active electrode exclusions: "
            + "; ".join(invalid)
        )


def prepare_analysis_plan(
    plan: AnalysisPlan,
    spec: FreeHarmonicMethodSpec,
    *,
    progress_callback: Callable[[int, int], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> PreparedAnalysisPlan:
    """Freeze complete cohorts, read each source once, and share one domain."""
    if not isinstance(plan, AnalysisPlan) or not isinstance(spec, FreeHarmonicMethodSpec):
        raise TypeError("Expected AnalysisPlan and FreeHarmonicMethodSpec.")
    started = perf_counter()
    inputs._check_cancel(cancel_check)
    canonical_plan = build_analysis_plan(
        plan.project_root,
        group_ids=plan.group_ids,
        conditions=plan.conditions,
        session_ids=plan.session_ids,
        families=plan.families,
        condition_pairs=plan.condition_pairs,
        recording_exclusions=plan.recording_exclusions,
    )
    if canonical_plan.to_dict() != plan.to_dict():
        raise FreeHarmonicInputError(
            "The analysis plan no longer matches its complete canonical comparison list. Review the plan before running."
        )
    index = inputs.load_project_dataset_index(plan.project_root)
    if index.project_root.resolve(strict=False) != plan.project_root:
        raise FreeHarmonicInputError("The dataset index resolved to a different active project root.")
    try:
        neutral = inputs.validate_project_full_fft_provenance(
            plan.project_root,
            base_frequency_hz=spec.base_frequency_hz,
            oddball_frequency_hz=spec.oddball_frequency_hz,
            dataset_index=index,
        )
    except inputs.FullFftProvenanceError as exc:
        raise FreeHarmonicInputError(str(exc)) from exc
    arms, repeated, flat_cohorts = _comparison_arms(plan, index)
    records_by_path = {
        record.path: record for pair in arms for arm in pair for sample in arm.samples for record in sample
    }
    records = tuple(records_by_path[path] for path in sorted(records_by_path, key=lambda value: str(value).casefold()))
    _validate_retained_electrodes(plan.project_root, records)
    frequency_plan = None
    sources = []
    total = 2 * len(records)
    for number, record in enumerate(records, 1):
        inputs._check_cancel(cancel_check)
        path, relative = inputs._resolved_source_path(record.path, plan.project_root)
        start_header = perf_counter()
        try:
            header = inputs._read_fullfft_header(path)
            current = build_frequency_window_plan(header, spec)
        except Exception as exc:
            raise FreeHarmonicInputError(f"Could not read the planned FullFFT grid from {relative}: {exc}") from exc
        seconds = perf_counter() - start_header
        if frequency_plan is None:
            frequency_plan = current
        elif (current.grid_fingerprint, current.selected_columns_fingerprint) != (
            frequency_plan.grid_fingerprint,
            frequency_plan.selected_columns_fingerprint,
        ):
            raise FreeHarmonicInputError(f"All planned FullFFT sources must share one exact grid; {relative} differs.")
        sources.append((record, path, relative, seconds))
        inputs._notify_progress(progress_callback, number, total)
    if frequency_plan is None:
        raise FreeHarmonicInputError("No complete sources were available for the analysis plan.")
    if frequency_plan.grid_fingerprint != neutral.grid_fingerprint:
        raise FreeHarmonicInputError(
            "The planned FullFFT grid differs from its saved provenance. Rerun post-processing; EEG preprocessing is not required."
        )
    sensor_count = len(DEFAULT_ELECTRODE_NAMES_64)
    snr = np.empty((len(records), sensor_count, len(frequency_plan.candidate_orders)), dtype=np.float64)
    source_rows = []
    row_by_path = {}
    raw_sums = defaultdict(lambda: np.zeros(len(frequency_plan.selected_frequency_columns), dtype=np.float64))
    counts = defaultdict(int)
    phase_seconds = defaultdict(float)
    numeric_seconds = 0.0
    for number, (record, path, relative, header_seconds) in enumerate(sources, 1):
        inputs._check_cancel(cancel_check)
        read_started = perf_counter()
        timings = {}
        try:
            frame = inputs._read_fullfft_selected_columns(path, frequency_plan.required_columns, timings)
        except Exception as exc:
            raise FreeHarmonicInputError(f"Could not read planned FullFFT amplitudes from {relative}: {exc}") from exc
        read_seconds = perf_counter() - read_started
        numeric_started = perf_counter()
        matrix = inputs._validate_sensor_matrix(frame, path, frequency_plan)
        del frame
        snr[number - 1] = compute_participant_snr(matrix, frequency_plan)
        row_by_path[record.path] = number - 1
        cell = (record.group_id or "all_participants", record.session_id or "single_session", record.condition)
        raw_sums[cell] += np.sum(matrix, axis=0, dtype=np.float64)
        counts[cell] += 1
        del matrix
        numeric_seconds += perf_counter() - numeric_started
        for key, value in timings.items():
            phase_seconds[key] += value
        source_rows.append(
            CohortWorkbook(
                arm="a",
                arm_label=record.group_label or "All participants",
                participant_id=record.participant_id,
                condition=record.condition,
                group_id=record.group_id,
                group_label=record.group_label,
                source_path=path,
                project_relative_path=relative,
                header_read_seconds=header_seconds,
                amplitude_read_seconds=read_seconds,
                recording_id=record.recording_id,
                session_id=record.session_id,
                session_label=record.session_label,
                visit_index=record.visit_index,
            )
        )
        inputs._notify_progress(progress_callback, len(records) + number, total)
    numeric_started = perf_counter()
    cells = tuple(sorted(counts, key=lambda row: tuple(value.casefold() for value in row)))
    grands = np.ascontiguousarray([raw_sums[cell] / (counts[cell] * sensor_count) for cell in cells])
    selection, z, detected = select_harmonics_across_cells(grands, frequency_plan, spec)
    audit = SharedHarmonicSelectionAudit(
        cell_labels=tuple(" | ".join(cell) for cell in cells),
        cell_group_ids=tuple(cell[0] for cell in cells),
        cell_session_ids=tuple(cell[1] for cell in cells),
        cell_conditions=tuple(cell[2] for cell in cells),
        cell_participant_counts=tuple(counts[cell] for cell in cells),
        z_scores=z,
        detected=detected,
    )
    domain_fingerprint = sha256(
        json.dumps(
            {
                "version": plan.version,
                "source_fingerprint": neutral.source_fingerprint,
                "grid": frequency_plan.grid_fingerprint,
                "source_paths": [row.project_relative_path for row in source_rows],
                "cells": cells,
                "counts": [counts[cell] for cell in cells],
                "selected_orders": selection.selected_orders.tolist(),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    numeric_seconds += perf_counter() - numeric_started

    def union(field: str) -> tuple[str, ...]:
        cohorts = (repeated,) if repeated is not None else flat_cohorts
        return tuple(sorted({value for cohort in cohorts for value in getattr(cohort, field, ())}, key=str.casefold))

    condition_exclusions = {
        (row.participant_id.casefold(), row.condition.casefold()): row
        for cohort in flat_cohorts
        for row in cohort.participant_condition_exclusions
    }
    for record in index.excluded_workbooks:
        if record.condition in plan.conditions and (not plan.group_ids or record.group_id in plan.group_ids):
            condition_exclusions.setdefault(
                (record.participant_id.casefold(), record.condition.casefold()),
                ParticipantConditionExclusion(
                    participant_id=record.participant_id,
                    condition=record.condition,
                    reason="Project recording/condition exclusion",
                ),
            )
    cohort_audit = repeated.audit_rows if repeated is not None else ()
    provenance = PreparationProvenance(
        source_sheet=inputs.FULL_FFT_SHEET,
        grid_fingerprint=frequency_plan.grid_fingerprint,
        selected_columns_fingerprint=frequency_plan.selected_columns_fingerprint,
        frequency_resolution_hz=frequency_plan.frequency_resolution_hz,
        full_frequency_column_count=len(frequency_plan.full_frequency_columns),
        selected_frequency_column_count=len(frequency_plan.selected_frequency_columns),
        workbook_count=len(source_rows),
        header_read_seconds=sum(row.header_read_seconds for row in source_rows),
        amplitude_read_seconds=sum(row.amplitude_read_seconds for row in source_rows),
        numeric_preparation_seconds=numeric_seconds,
        total_seconds=perf_counter() - started,
        reader_phase_seconds=tuple(sorted(phase_seconds.items())),
        ledger_filter_applied=any(
            cohort.ledger_filter_applied for cohort in ((repeated,) if repeated else flat_cohorts)
        ),
        completed_participants=union("completed_participants"),
        ledger_excluded_participants=union("ledger_excluded_participants"),
        manual_excluded_participants=union("manual_excluded_participants"),
        frequency_qc_excluded_participants=union("frequency_qc_excluded_participants"),
        completed_recordings=union("completed_recordings"),
        ledger_excluded_recordings=union("ledger_excluded_recordings"),
        frequency_qc_excluded_recordings=union("frequency_qc_excluded_recordings"),
        incomplete_pair_participants=tuple(
            sorted(
                set(union("incomplete_pair_participants"))
                | {row.participant_id for row in cohort_audit if not row.included_complete_pair},
                key=str.casefold,
            )
        ),
        participant_condition_exclusions=tuple(condition_exclusions.values()),
        dataset_diagnostics=tuple(f"{row.code}: {row.message}" for row in index.diagnostics),
        full_fft_provenance_method_version=neutral.method_version,
        full_fft_source_fingerprint=neutral.source_fingerprint,
        full_fft_cohort_fingerprint=neutral.cohort_fingerprint,
        full_fft_frequency_qc_fingerprint=neutral.frequency_qc_fingerprint,
        full_fft_processing_export_fingerprint=neutral.processing_export_fingerprint,
        repeated_session_batch_version=plan.version,
        shared_domain_fingerprint=domain_fingerprint,
        request_recording_exclusions=plan.recording_exclusions,
        repeated_session_cohort_audit=cohort_audit,
    )

    def tensors(arm: _Arm, kind: AnalysisFamily) -> tuple[np.ndarray, np.ndarray]:
        candidate = np.asarray([[snr[row_by_path[record.path]] for record in sample] for sample in arm.samples])
        if candidate.shape[1] == 1:
            selected = select_snr_harmonics(candidate[:, 0], selection)
            return selected, l2_normalize_snr(selected)
        if kind is AnalysisFamily.GROUP_VISIT_CHANGE:
            first = select_snr_harmonics(candidate[:, 0], selection)
            second = select_snr_harmonics(candidate[:, 1], selection)
            return first - second, l2_normalize_snr(first) - l2_normalize_snr(second)
        selected = select_snr_harmonics((candidate[:, 0] + candidate[:, 1]) / 2.0, selection)
        return selected, l2_normalize_snr(selected)

    contrasts = []
    for comparison, (arm_a, arm_b) in zip(plan.comparisons, arms, strict=True):
        inputs._check_cancel(cancel_check)
        snr_a, values_a = tensors(arm_a, comparison.kind)
        snr_b, values_b = tensors(arm_b, comparison.kind)
        arm_paths = {
            record.path: (letter, arm.label)
            for letter, arm in (("a", arm_a), ("b", arm_b))
            for sample in arm.samples
            for record in sample
        }
        contrast_sources = tuple(
            replace(
                row, arm=arm_paths[records[index_number].path][0], arm_label=arm_paths[records[index_number].path][1]
            )
            for index_number, row in enumerate(source_rows)
            if records[index_number].path in arm_paths
        )
        contrasts.append(
            PreparedContrast(
                request=_request(plan, comparison),
                method=spec,
                project_root=plan.project_root,
                arm_a_label=arm_a.label,
                arm_b_label=arm_b.label,
                participant_ids_a=arm_a.participants,
                participant_ids_b=arm_b.participants,
                sensor_names=tuple(DEFAULT_ELECTRODE_NAMES_64),
                harmonic_orders=selection.selected_orders,
                harmonics_hz=selection.selected_harmonics_hz,
                snr_a=snr_a,
                snr_b=snr_b,
                values_a=values_a,
                values_b=values_b,
                selection=selection,
                frequency_plan=frequency_plan,
                source_workbooks=contrast_sources,
                provenance=provenance,
            )
        )
    provenance = replace(provenance, total_seconds=perf_counter() - started)
    return PreparedAnalysisPlan(
        plan,
        spec,
        tuple(replace(row, provenance=provenance) for row in contrasts),
        selection,
        audit,
        frequency_plan,
        provenance,
        tuple(source_rows),
        tuple(cohort_audit),
    )
