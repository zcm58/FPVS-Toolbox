"""Managed-project input adapter for Free Harmonic Clustering Analysis."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np

from config import DEFAULT_ELECTRODE_NAMES_64
from Main_App.processing.frequency_domain_qc import (
    active_frequency_domain_exclusions,
)
from Main_App.processing.full_fft_provenance import (
    FullFftProvenanceError,
    validate_project_full_fft_provenance,
)
from Main_App.processing.processing_ledger import load_ledger
from Main_App.projects import (
    ProjectDatasetIndex,
    WorkbookRecord,
    load_project_dataset_index,
    normalize_preprocessing_settings,
)
from Tools.Stats.io.xlsx_selected_reader import (
    read_xlsx_sheet_header,
    read_xlsx_sheet_selected_columns,
)

from .models import (
    AnalysisDesign,
    CohortWorkbook,
    FreeHarmonicCancelledError,
    FreeHarmonicInputError,
    FreeHarmonicMethodSpec,
    FreeHarmonicPreparationError,
    FrequencyWindowPlan,
    ParticipantConditionExclusion,
    PreparationProvenance,
    PreparedContrast,
    ProjectContrastRequest,
)
from .preparation import (
    build_frequency_window_plan,
    compute_participant_snr,
    l2_normalize_snr,
    select_harmonics,
    select_snr_harmonics,
)


FULL_FFT_SHEET = "FullFFT Amplitude (uV)"
_ProgressCallback = Callable[[int, int], None]
_CancelCheck = Callable[[], bool]


@dataclass(frozen=True, slots=True)
class _SelectedCohort:
    arm_a_records: tuple[WorkbookRecord, ...]
    arm_b_records: tuple[WorkbookRecord, ...]
    arm_a_label: str
    arm_b_label: str
    ledger_filter_applied: bool
    completed_participants: tuple[str, ...]
    ledger_excluded_participants: tuple[str, ...]
    manual_excluded_participants: tuple[str, ...]
    frequency_qc_excluded_participants: tuple[str, ...]
    incomplete_pair_participants: tuple[str, ...]


def _read_fullfft_header(path: Path) -> list[object]:
    """Private seam around the existing streaming Stats XML header reader."""

    return read_xlsx_sheet_header(path, sheet_name=FULL_FFT_SHEET)


def _read_fullfft_selected_columns(
    path: Path,
    required_columns: Sequence[str],
    timing_details: dict[str, float],
) -> Any:
    """Private seam around one exact selected-column XML worksheet read."""

    return read_xlsx_sheet_selected_columns(
        path,
        sheet_name=FULL_FFT_SHEET,
        required_columns=required_columns,
        require_all=True,
        electrode_column="Electrode",
        timing_details=timing_details,
    )


def _check_cancel(cancel_check: _CancelCheck | None) -> None:
    if cancel_check is not None and cancel_check():
        raise FreeHarmonicCancelledError(
            "Free Harmonic Clustering preparation was cancelled."
        )


def _notify_progress(
    callback: _ProgressCallback | None,
    completed: int,
    total: int,
) -> None:
    if callback is not None:
        callback(int(completed), int(total))


def _casefold_ids(values: Sequence[object]) -> set[str]:
    return {
        str(value).strip().casefold()
        for value in values
        if str(value).strip()
    }


def _sort_ids(values: Sequence[object] | set[str]) -> tuple[str, ...]:
    unique = {str(value).strip() for value in values if str(value).strip()}
    return tuple(sorted(unique, key=lambda value: (value.casefold(), value)))


def _manifest_manual_exclusions(index: ProjectDatasetIndex) -> tuple[str, ...]:
    manifest = index.manifest if isinstance(index.manifest, Mapping) else {}
    raw = manifest.get("preprocessing")
    preprocessing = normalize_preprocessing_settings(
        raw if isinstance(raw, Mapping) else {}
    )
    return _sort_ids(preprocessing.get("manual_excluded_participants", ()))


def _relevant_participant_condition_exclusions(
    index: ProjectDatasetIndex,
    request: ProjectContrastRequest,
) -> tuple[ParticipantConditionExclusion, ...]:
    conditions = {request.condition_a.casefold()}
    if request.condition_b is not None:
        conditions.add(request.condition_b.casefold())
    group_keys = {group_id.casefold() for group_id in request.group_ids}
    rows = {
        (record.participant_id, record.condition)
        for record in index.excluded_workbooks
        if record.condition.casefold() in conditions
        and (
            not group_keys
            or (
                record.group_id is not None
                and record.group_id.casefold() in group_keys
            )
        )
    }
    return tuple(
        ParticipantConditionExclusion(
            participant_id=participant_id,
            condition=condition,
        )
        for participant_id, condition in sorted(
            rows,
            key=lambda row: (
                row[1].casefold(),
                row[0].casefold(),
                row[1],
                row[0],
            ),
        )
    )


def _completed_ledger_participants(
    project_root: Path,
) -> tuple[tuple[str, ...], bool]:
    ledger = load_ledger(project_root)
    entries = ledger.get("entries") if isinstance(ledger, Mapping) else None
    if not isinstance(entries, Mapping):
        return (), False
    completed = _sort_ids(
        participant_id
        for participant_id, entry in entries.items()
        if isinstance(entry, Mapping)
        and str(entry.get("status") or "").strip().casefold() == "completed"
    )
    # Preserve the established processed-workbook compatibility rule: a ledger
    # filters only when it records at least one completed participant.  Empty or
    # absent ledgers support older managed projects without ledger state.
    return completed, bool(completed)


def _resolve_group(
    index: ProjectDatasetIndex,
    requested_group_id: str,
) -> tuple[str, str]:
    key = requested_group_id.casefold()
    matches = [
        group
        for group_id, group in index.groups.items()
        if str(group_id).casefold() == key
    ]
    if len(matches) != 1:
        raise FreeHarmonicInputError(
            f"Unknown canonical project group_id {requested_group_id!r}."
        )
    group = matches[0]
    return str(group.group_id), str(group.label)


def _record_map(
    records: Sequence[WorkbookRecord],
    *,
    arm_label: str,
) -> dict[str, WorkbookRecord]:
    result: dict[str, WorkbookRecord] = {}
    for record in records:
        key = record.participant_id.casefold()
        if key in result:
            raise FreeHarmonicInputError(
                "More than one processed workbook matched participant "
                f"{record.participant_id!r} in {arm_label}."
            )
        result[key] = record
    return result


def _select_cohort(
    index: ProjectDatasetIndex,
    request: ProjectContrastRequest,
    project_root: Path,
) -> _SelectedCohort:
    if index.manifest is None:
        raise FreeHarmonicInputError(
            "Free Harmonic Clustering requires a managed project.json manifest."
        )
    if request.design is AnalysisDesign.INDEPENDENT_GROUPS:
        if not index.has_group_metadata:
            raise FreeHarmonicInputError(
                "Independent-groups Free Harmonic Clustering requires "
                "canonical project group metadata."
            )
        try:
            index.require_group_assignments()
        except Exception as exc:
            raise FreeHarmonicInputError(str(exc)) from exc
    elif request.group_ids and not index.has_group_metadata:
        raise FreeHarmonicInputError(
            "A paired-condition group filter requires canonical project group "
            "metadata."
        )

    completed, ledger_filter_applied = _completed_ledger_participants(project_root)
    completed_keys = _casefold_ids(completed)
    manual = _manifest_manual_exclusions(index)
    manual_keys = _casefold_ids(manual)
    frequency_qc = active_frequency_domain_exclusions(project_root)
    if frequency_qc.downstream_outputs_stale:
        raise FreeHarmonicInputError(
            "Frequency-domain QC marks downstream outputs stale; rerun the "
            "required processing/QC workflow before this analysis."
        )
    frequency_excluded = _sort_ids(frequency_qc.excluded_participants)
    frequency_keys = _casefold_ids(frequency_excluded)

    requested_group_ids = request.group_ids
    if request.design is AnalysisDesign.INDEPENDENT_GROUPS:
        group_a_id, group_a_label = _resolve_group(index, requested_group_ids[0])
        group_b_id, group_b_label = _resolve_group(index, requested_group_ids[1])
        try:
            relevant = index.select(
                conditions=(request.condition_a,),
                group_ids=(group_a_id, group_b_id),
                require_nonempty_groups=True,
            )
        except Exception as exc:
            raise FreeHarmonicInputError(str(exc)) from exc
    else:
        group_a_label = request.condition_a
        group_b_label = str(request.condition_b)
        group_filter: tuple[str, ...] | None = None
        if requested_group_ids:
            group_id, _group_label = _resolve_group(index, requested_group_ids[0])
            group_filter = (group_id,)
        try:
            relevant = index.select(
                conditions=(request.condition_a, str(request.condition_b)),
                group_ids=group_filter,
                require_nonempty_groups=bool(group_filter),
            )
        except Exception as exc:
            raise FreeHarmonicInputError(str(exc)) from exc

    if not relevant:
        raise FreeHarmonicInputError(
            "No indexed FullFFT workbooks matched the requested contrast."
        )
    relevant_participants = {record.participant_id.casefold() for record in relevant}
    ledger_excluded_keys = (
        relevant_participants - completed_keys if ledger_filter_applied else set()
    )

    active_records = tuple(
        record
        for record in relevant
        if (not ledger_filter_applied or record.participant_id.casefold() in completed_keys)
        and record.participant_id.casefold() not in manual_keys
        and record.participant_id.casefold() not in frequency_keys
    )

    if request.design is AnalysisDesign.INDEPENDENT_GROUPS:
        group_a_key = group_a_id.casefold()
        group_b_key = group_b_id.casefold()
        records_a = tuple(
            record
            for record in active_records
            if record.group_id is not None
            and record.group_id.casefold() == group_a_key
        )
        records_b = tuple(
            record
            for record in active_records
            if record.group_id is not None
            and record.group_id.casefold() == group_b_key
        )
        map_a = _record_map(records_a, arm_label=group_a_label)
        map_b = _record_map(records_b, arm_label=group_b_label)
        overlap = set(map_a).intersection(map_b)
        if overlap:
            participants = ", ".join(
                sorted(map_a[key].participant_id for key in overlap)
            )
            raise FreeHarmonicInputError(
                "Independent contrast arms share participant(s): " + participants
            )
        ordered_a = tuple(map_a[key] for key in sorted(map_a))
        ordered_b = tuple(map_b[key] for key in sorted(map_b))
        incomplete_pairs: tuple[str, ...] = ()
    else:
        condition_a_key = request.condition_a.casefold()
        condition_b_key = str(request.condition_b).casefold()
        records_a = tuple(
            record
            for record in active_records
            if record.condition.casefold() == condition_a_key
        )
        records_b = tuple(
            record
            for record in active_records
            if record.condition.casefold() == condition_b_key
        )
        map_a = _record_map(records_a, arm_label=request.condition_a)
        map_b = _record_map(records_b, arm_label=str(request.condition_b))
        common = set(map_a).intersection(map_b)
        incomplete_keys = set(map_a).symmetric_difference(map_b)
        incomplete_pairs = _sort_ids(
            [
                (map_a.get(key) or map_b[key]).participant_id
                for key in incomplete_keys
            ]
        )
        ordered_keys = sorted(common)
        ordered_a = tuple(map_a[key] for key in ordered_keys)
        ordered_b = tuple(map_b[key] for key in ordered_keys)
        for record_a, record_b in zip(ordered_a, ordered_b, strict=True):
            if (record_a.group_id or "").casefold() != (
                record_b.group_id or ""
            ).casefold():
                raise FreeHarmonicInputError(
                    "Paired workbook group identity changed between conditions for "
                    f"participant {record_a.participant_id}."
                )

    if not ordered_a or not ordered_b:
        raise FreeHarmonicInputError(
            "Participant exclusions left one or both requested contrast arms empty."
        )
    if len(ordered_a) < 2 or len(ordered_b) < 2:
        if request.design is AnalysisDesign.PAIRED_CONDITIONS:
            detail = f"paired common cohort n={len(ordered_a)}"
        else:
            detail = f"independent arm sizes n={len(ordered_a)} and n={len(ordered_b)}"
        raise FreeHarmonicInputError(
            "Free Harmonic Clustering requires at least two participants in "
            f"each analysis arm after exclusions ({detail})."
        )

    included_keys = {
        record.participant_id.casefold() for record in (*ordered_a, *ordered_b)
    }
    electrode_exclusions = {
        str(participant_id): tuple(sorted(str(value) for value in electrodes))
        for participant_id, electrodes in (
            frequency_qc.auto_excluded_electrodes_by_participant or {}
        ).items()
        if str(participant_id).casefold() in included_keys and electrodes
    }
    if electrode_exclusions:
        details = "; ".join(
            f"{participant}: {', '.join(electrodes)}"
            for participant, electrodes in sorted(
                electrode_exclusions.items(),
                key=lambda row: row[0].casefold(),
            )
        )
        raise FreeHarmonicInputError(
            "Free Harmonic Clustering requires the complete BioSemi64 sensor "
            "domain; included participants have active electrode exclusions: "
            + details
        )

    ledger_display = {
        record.participant_id
        for record in relevant
        if record.participant_id.casefold() in ledger_excluded_keys
    }
    return _SelectedCohort(
        arm_a_records=ordered_a,
        arm_b_records=ordered_b,
        arm_a_label=group_a_label,
        arm_b_label=group_b_label,
        ledger_filter_applied=ledger_filter_applied,
        completed_participants=completed,
        ledger_excluded_participants=_sort_ids(ledger_display),
        manual_excluded_participants=manual,
        frequency_qc_excluded_participants=frequency_excluded,
        incomplete_pair_participants=incomplete_pairs,
    )


def _resolved_source_path(path: Path, project_root: Path) -> tuple[Path, str]:
    resolved = Path(path).resolve(strict=False)
    try:
        relative = resolved.relative_to(project_root)
    except ValueError as exc:
        raise FreeHarmonicInputError(
            f"Indexed workbook escapes the active project root: {resolved}"
        ) from exc
    if not resolved.is_file():
        raise FreeHarmonicInputError(f"Indexed workbook is missing: {resolved}")
    return resolved, relative.as_posix()


def _validate_sensor_matrix(frame: Any, path: Path, plan: FrequencyWindowPlan) -> np.ndarray:
    try:
        electrodes = tuple(str(value).strip().upper() for value in frame["Electrode"])
    except Exception as exc:
        raise FreeHarmonicInputError(
            f"Could not read the Electrode column from {path.name}."
        ) from exc
    expected = tuple(str(value).strip().upper() for value in DEFAULT_ELECTRODE_NAMES_64)
    if electrodes != expected:
        raise FreeHarmonicInputError(
            f"{path.name} does not use the exact canonical BioSemi64 sensor order."
        )
    try:
        matrix = np.ascontiguousarray(
            frame.loc[:, list(plan.selected_frequency_columns)].to_numpy(
                dtype=np.float64,
                copy=True,
            ),
            dtype=np.float64,
        )
    except Exception as exc:
        raise FreeHarmonicInputError(
            f"Selected FullFFT amplitudes in {path.name} are not numeric."
        ) from exc
    expected_shape = (len(expected), len(plan.selected_frequency_columns))
    if matrix.shape != expected_shape:
        raise FreeHarmonicInputError(
            f"Selected FullFFT matrix in {path.name} has shape {matrix.shape}; "
            f"expected {expected_shape}."
        )
    if not np.all(np.isfinite(matrix)):
        raise FreeHarmonicInputError(
            f"Selected FullFFT amplitudes in {path.name} contain non-finite values."
        )
    if np.any(matrix < 0.0):
        raise FreeHarmonicInputError(
            f"Selected FullFFT amplitudes in {path.name} contain negative values."
        )
    return matrix


def prepare_project_contrast(
    request: ProjectContrastRequest,
    spec: FreeHarmonicMethodSpec,
    *,
    progress_callback: _ProgressCallback | None = None,
    cancel_check: _CancelCheck | None = None,
) -> PreparedContrast:
    """Load, validate, and prepare one managed-project two-arm contrast.

    Each consumed workbook receives one header-only read and exactly one
    selected-column XML amplitude read.  Selected frames are converted to
    contiguous NumPy matrices immediately and are never cached run-wide.
    """

    started = perf_counter()
    if not isinstance(request, ProjectContrastRequest):
        raise TypeError("request must be a ProjectContrastRequest.")
    if not isinstance(spec, FreeHarmonicMethodSpec):
        raise TypeError("spec must be a FreeHarmonicMethodSpec.")
    project_root = request.project_root.expanduser().resolve(strict=False)
    if not project_root.is_dir() or not (project_root / "project.json").is_file():
        raise FreeHarmonicInputError(
            "project_root must be an existing managed project containing project.json."
        )
    _check_cancel(cancel_check)
    try:
        index = load_project_dataset_index(project_root)
    except Exception as exc:
        raise FreeHarmonicInputError(
            f"Could not build the managed-project dataset index: {exc}"
        ) from exc
    if index.project_root.resolve(strict=False) != project_root:
        raise FreeHarmonicInputError(
            "The dataset index resolved to a different active project root."
        )
    try:
        full_fft_provenance = validate_project_full_fft_provenance(
            project_root,
            base_frequency_hz=spec.base_frequency_hz,
            oddball_frequency_hz=spec.oddball_frequency_hz,
            dataset_index=index,
        )
    except FullFftProvenanceError as exc:
        raise FreeHarmonicInputError(str(exc)) from exc
    cohort = _select_cohort(index, request, project_root)
    arm_rows = (
        *(('a', cohort.arm_a_label, record) for record in cohort.arm_a_records),
        *(('b', cohort.arm_b_label, record) for record in cohort.arm_b_records),
    )
    total_workbooks = len(arm_rows)
    progress_total = total_workbooks * 2

    plan: FrequencyWindowPlan | None = None
    header_seconds_by_path: dict[Path, float] = {}
    resolved_rows: list[tuple[str, str, WorkbookRecord, Path, str]] = []
    for index_number, (arm, arm_label, record) in enumerate(arm_rows, start=1):
        _check_cancel(cancel_check)
        path, relative = _resolved_source_path(record.path, project_root)
        header_started = perf_counter()
        try:
            header = _read_fullfft_header(path)
        except Exception as exc:
            raise FreeHarmonicInputError(
                f"Could not read {FULL_FFT_SHEET!r} header from {path.name}: {exc}"
            ) from exc
        header_seconds = perf_counter() - header_started
        try:
            workbook_plan = build_frequency_window_plan(header, spec)
        except FreeHarmonicPreparationError as exc:
            raise FreeHarmonicInputError(
                f"Invalid FullFFT grid in {relative}: {exc}"
            ) from exc
        if plan is None:
            plan = workbook_plan
        elif (
            workbook_plan.grid_fingerprint != plan.grid_fingerprint
            or workbook_plan.selected_columns_fingerprint
            != plan.selected_columns_fingerprint
        ):
            raise FreeHarmonicInputError(
                "All consumed workbooks must share one exact FullFFT grid; "
                f"{relative} differs from the first workbook."
            )
        header_seconds_by_path[path] = header_seconds
        resolved_rows.append((arm, arm_label, record, path, relative))
        _notify_progress(
            progress_callback,
            index_number,
            progress_total,
        )
    if plan is None:  # pragma: no cover - guarded by non-empty cohort
        raise FreeHarmonicInputError("No workbooks were available for preparation.")
    if plan.grid_fingerprint != full_fft_provenance.grid_fingerprint:
        raise FreeHarmonicInputError(
            "The selected-cohort FullFFT grid does not match saved neutral "
            "FullFFT provenance. Rerun post-processing; EEG preprocessing is "
            "not required."
        )

    snr_by_arm: dict[str, list[np.ndarray]] = {"a": [], "b": []}
    raw_sum_by_arm = {
        "a": np.zeros(len(plan.selected_frequency_columns), dtype=np.float64),
        "b": np.zeros(len(plan.selected_frequency_columns), dtype=np.float64),
    }
    source_workbooks: list[CohortWorkbook] = []
    reader_phase_seconds: defaultdict[str, float] = defaultdict(float)
    amplitude_seconds_total = 0.0
    numeric_seconds_total = 0.0
    for read_number, (arm, arm_label, record, path, relative) in enumerate(
        resolved_rows,
        start=1,
    ):
        _check_cancel(cancel_check)
        timing_details: dict[str, float] = {}
        amplitude_started = perf_counter()
        try:
            frame = _read_fullfft_selected_columns(
                path,
                plan.required_columns,
                timing_details,
            )
        except Exception as exc:
            raise FreeHarmonicInputError(
                f"Could not read selected FullFFT columns from {relative}: {exc}"
            ) from exc
        amplitude_seconds = perf_counter() - amplitude_started
        amplitude_seconds_total += amplitude_seconds
        for phase, seconds in timing_details.items():
            reader_phase_seconds[str(phase)] += float(seconds)

        numeric_started = perf_counter()
        matrix = _validate_sensor_matrix(frame, path, plan)
        del frame
        try:
            participant_snr = compute_participant_snr(matrix, plan)
        except FreeHarmonicPreparationError as exc:
            raise FreeHarmonicInputError(
                f"Could not compute participant SNR from {relative}: {exc}"
            ) from exc
        snr_by_arm[arm].append(participant_snr)
        raw_sum_by_arm[arm] += np.sum(matrix, axis=0, dtype=np.float64)
        del matrix
        numeric_seconds_total += perf_counter() - numeric_started
        source_workbooks.append(
            CohortWorkbook(
                arm=arm,
                arm_label=arm_label,
                participant_id=record.participant_id,
                condition=record.condition,
                group_id=record.group_id,
                group_label=record.group_label,
                source_path=path,
                project_relative_path=relative,
                header_read_seconds=header_seconds_by_path[path],
                amplitude_read_seconds=amplitude_seconds,
            )
        )
        _notify_progress(
            progress_callback,
            total_workbooks + read_number,
            progress_total,
        )
        _check_cancel(cancel_check)

    numeric_started = perf_counter()
    candidate_snr_a = np.ascontiguousarray(np.stack(snr_by_arm["a"], axis=0))
    candidate_snr_b = np.ascontiguousarray(np.stack(snr_by_arm["b"], axis=0))
    sensor_count = len(DEFAULT_ELECTRODE_NAMES_64)
    grand_a = raw_sum_by_arm["a"] / (
        candidate_snr_a.shape[0] * sensor_count
    )
    grand_b = raw_sum_by_arm["b"] / (
        candidate_snr_b.shape[0] * sensor_count
    )
    selection = select_harmonics(grand_a, grand_b, plan, spec)
    selected_snr_a = select_snr_harmonics(candidate_snr_a, selection)
    selected_snr_b = select_snr_harmonics(candidate_snr_b, selection)
    normalized_a = l2_normalize_snr(selected_snr_a)
    normalized_b = l2_normalize_snr(selected_snr_b)
    numeric_seconds_total += perf_counter() - numeric_started

    diagnostics = tuple(
        f"{diagnostic.code}: {diagnostic.message}"
        for diagnostic in index.diagnostics
    )
    total_seconds = perf_counter() - started
    provenance = PreparationProvenance(
        source_sheet=FULL_FFT_SHEET,
        grid_fingerprint=plan.grid_fingerprint,
        selected_columns_fingerprint=plan.selected_columns_fingerprint,
        frequency_resolution_hz=plan.frequency_resolution_hz,
        full_frequency_column_count=len(plan.full_frequency_columns),
        selected_frequency_column_count=len(plan.selected_frequency_columns),
        workbook_count=total_workbooks,
        header_read_seconds=sum(header_seconds_by_path.values()),
        amplitude_read_seconds=amplitude_seconds_total,
        numeric_preparation_seconds=numeric_seconds_total,
        total_seconds=total_seconds,
        reader_phase_seconds=tuple(sorted(reader_phase_seconds.items())),
        ledger_filter_applied=cohort.ledger_filter_applied,
        completed_participants=cohort.completed_participants,
        ledger_excluded_participants=cohort.ledger_excluded_participants,
        manual_excluded_participants=cohort.manual_excluded_participants,
        frequency_qc_excluded_participants=(
            cohort.frequency_qc_excluded_participants
        ),
        incomplete_pair_participants=cohort.incomplete_pair_participants,
        participant_condition_exclusions=(
            _relevant_participant_condition_exclusions(index, request)
        ),
        dataset_diagnostics=diagnostics,
        full_fft_provenance_method_version=(
            full_fft_provenance.method_version
        ),
        full_fft_source_fingerprint=full_fft_provenance.source_fingerprint,
        full_fft_cohort_fingerprint=full_fft_provenance.cohort_fingerprint,
        full_fft_frequency_qc_fingerprint=(
            full_fft_provenance.frequency_qc_fingerprint
        ),
        full_fft_processing_export_fingerprint=(
            full_fft_provenance.processing_export_fingerprint
        ),
    )
    return PreparedContrast(
        request=request,
        method=spec,
        project_root=project_root,
        arm_a_label=cohort.arm_a_label,
        arm_b_label=cohort.arm_b_label,
        participant_ids_a=tuple(
            record.participant_id for record in cohort.arm_a_records
        ),
        participant_ids_b=tuple(
            record.participant_id for record in cohort.arm_b_records
        ),
        sensor_names=tuple(DEFAULT_ELECTRODE_NAMES_64),
        harmonic_orders=selection.selected_orders,
        harmonics_hz=selection.selected_harmonics_hz,
        snr_a=selected_snr_a,
        snr_b=selected_snr_b,
        values_a=normalized_a,
        values_b=normalized_b,
        selection=selection,
        frequency_plan=plan,
        source_workbooks=tuple(source_workbooks),
        provenance=provenance,
    )


__all__ = ["FULL_FFT_SHEET", "prepare_project_contrast"]
