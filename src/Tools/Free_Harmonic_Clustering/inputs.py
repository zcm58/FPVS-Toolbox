"""Managed-project input adapter for Free Harmonic Clustering Analysis."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np

from config import DEFAULT_ELECTRODE_NAMES_64
from Main_App.io import (
    read_xlsx_sheet_header,
    read_xlsx_sheet_selected_columns,
)
from Main_App.processing.frequency_domain_qc import (
    FrequencyDomainCoverageDecisions,
    load_frequency_domain_qc_state,
    resolve_frequency_qc_coverage_decisions,
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
from .models import (
    AnalysisDesign,
    CohortWorkbook,
    FreeHarmonicCancelledError,
    FreeHarmonicInputError,
    FreeHarmonicMethodSpec,
    FreeHarmonicPreparationError,
    FrequencyWindowPlan,
    NoHarmonicsSelectedError,
    ParticipantConditionExclusion,
    PreparationProvenance,
    PreparedContrast,
    PreparedRepeatedSessionBatch,
    PreparedRepeatedSessionContrast,
    ProjectGroupOption,
    ProjectContrastRequest,
    ProjectSessionOption,
    RepeatedSessionBatchRequest,
    RepeatedSessionCohortAuditRow,
    RepeatedSessionContrastFamily,
    RepeatedSessionTensorSemantics,
    SharedHarmonicSelectionAudit,
)
from .preparation import (
    build_frequency_window_plan,
    compute_participant_snr,
    l2_normalize_snr,
    select_harmonics,
    select_harmonics_across_cells,
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
    participant_condition_exclusions: tuple[ParticipantConditionExclusion, ...]


@dataclass(frozen=True, slots=True)
class _RepeatedBatchCohort:
    conditions: tuple[str, ...]
    groups: tuple[ProjectGroupOption, ProjectGroupOption]
    sessions: tuple[ProjectSessionOption, ProjectSessionOption]
    source_records: tuple[WorkbookRecord, ...]
    record_by_cell: Mapping[tuple[str, str, str], WorkbookRecord]
    complete_participants: Mapping[tuple[str, str], tuple[str, ...]]
    audit_rows: tuple[RepeatedSessionCohortAuditRow, ...]
    ledger_filter_applied: bool
    completed_recordings: tuple[str, ...]
    ledger_excluded_recordings: tuple[str, ...]
    manual_excluded_participants: tuple[str, ...]
    frequency_qc_excluded_participants: tuple[str, ...]
    frequency_qc_excluded_recordings: tuple[str, ...]


def _read_fullfft_header(path: Path) -> list[object]:
    """Read the complete declared companion or legacy worksheet header."""

    return read_xlsx_sheet_header(path, sheet_name=FULL_FFT_SHEET)


def _read_fullfft_selected_columns(
    path: Path,
    required_columns: Sequence[str],
    timing_details: dict[str, float],
) -> Any:
    """Read exact bins through the shared companion-aware workbook adapter."""

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
        raise FreeHarmonicCancelledError("Free Harmonic Clustering preparation was cancelled.")


def _notify_progress(
    callback: _ProgressCallback | None,
    completed: int,
    total: int,
) -> None:
    if callback is not None:
        callback(int(completed), int(total))


def _casefold_ids(values: Sequence[object]) -> set[str]:
    return {str(value).strip().casefold() for value in values if str(value).strip()}


def _sort_ids(values: Sequence[object] | set[str]) -> tuple[str, ...]:
    unique = {str(value).strip() for value in values if str(value).strip()}
    return tuple(sorted(unique, key=lambda value: (value.casefold(), value)))


def _condition_identity_keys(
    values: Iterable[tuple[str, str]],
) -> set[tuple[str, str]]:
    """Normalize participant/recording condition identities for exact matching."""

    return {
        (str(identity).strip().casefold(), str(condition).strip().casefold())
        for identity, condition in values
        if str(identity).strip() and str(condition).strip()
    }


def _condition_electrode_map(
    values: Mapping[tuple[str, str], frozenset[str]],
) -> dict[tuple[str, str], tuple[str, ...]]:
    """Normalize reviewed condition-electrode exclusions without widening scope."""

    normalized: defaultdict[tuple[str, str], set[str]] = defaultdict(set)
    for (identity, condition), electrodes in values.items():
        key = (
            str(identity).strip().casefold(),
            str(condition).strip().casefold(),
        )
        if not all(key):
            continue
        normalized[key].update(
            str(electrode).strip()
            for electrode in electrodes
            if str(electrode).strip()
        )
    return {
        key: tuple(sorted(electrodes, key=lambda value: (value.casefold(), value)))
        for key, electrodes in normalized.items()
        if electrodes
    }


def _reviewed_frequency_qc(
    project_root: Path,
) -> FrequencyDomainCoverageDecisions:
    """Resolve only fingerprint-valid reviewed decisions for FHC cohort use."""

    state = load_frequency_domain_qc_state(project_root)
    decisions = resolve_frequency_qc_coverage_decisions(project_root)
    if bool(state.get("downstream_outputs_stale", False)):
        raise FreeHarmonicInputError(
            "Frequency-domain QC marks downstream outputs stale; rerun the "
            "required processing/QC workflow before this analysis."
        )
    if not decisions.review_complete:
        if bool(state.get("review_complete", False)):
            detail = "no longer has valid decision provenance"
        else:
            detail = "has not been completed with valid review evidence"
        raise FreeHarmonicInputError(
            f"The frequency-domain QC review {detail}. Repeat the review "
            "before this analysis."
        )
    return decisions


def _manifest_manual_exclusions(index: ProjectDatasetIndex) -> tuple[str, ...]:
    manifest = index.manifest if isinstance(index.manifest, Mapping) else {}
    raw = manifest.get("preprocessing")
    preprocessing = normalize_preprocessing_settings(raw if isinstance(raw, Mapping) else {})
    return _sort_ids(preprocessing.get("manual_excluded_participants", ()))


def _relevant_participant_condition_exclusions(
    index: ProjectDatasetIndex,
    request: ProjectContrastRequest,
    *,
    frequency_qc: FrequencyDomainCoverageDecisions,
    relevant_records: Sequence[WorkbookRecord],
) -> tuple[ParticipantConditionExclusion, ...]:
    conditions = {request.condition_a.casefold()}
    if request.condition_b is not None:
        conditions.add(request.condition_b.casefold())
    group_keys = {group_id.casefold() for group_id in request.group_ids}
    rows = {
        (record.participant_id.casefold(), record.condition.casefold()): (
            record.participant_id,
            record.condition,
            "Project participant-condition exclusion",
        )
        for record in index.excluded_workbooks
        if record.condition.casefold() in conditions
        and (not group_keys or (record.group_id is not None and record.group_id.casefold() in group_keys))
    }
    relevant_lookup = {
        (record.participant_id.casefold(), record.condition.casefold()): (
            record.participant_id,
            record.condition,
        )
        for record in relevant_records
    }
    for participant_id, condition in frequency_qc.excluded_participant_conditions:
        key = (
            str(participant_id).strip().casefold(),
            str(condition).strip().casefold(),
        )
        canonical = relevant_lookup.get(key)
        if canonical is not None:
            rows.setdefault(
                key,
                (
                    canonical[0],
                    canonical[1],
                    "Reviewed frequency-domain condition exclusion",
                ),
            )
    return tuple(
        ParticipantConditionExclusion(
            participant_id=participant_id,
            condition=condition,
            reason=reason,
        )
        for participant_id, condition, reason in sorted(
            rows.values(),
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
        if isinstance(entry, Mapping) and str(entry.get("status") or "").strip().casefold() == "completed"
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
    matches = [group for group_id, group in index.groups.items() if str(group_id).casefold() == key]
    if len(matches) != 1:
        raise FreeHarmonicInputError(f"Unknown canonical project group_id {requested_group_id!r}.")
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
                f"More than one processed workbook matched participant {record.participant_id!r} in {arm_label}."
            )
        result[key] = record
    return result


def _select_cohort(
    index: ProjectDatasetIndex,
    request: ProjectContrastRequest,
    project_root: Path,
) -> _SelectedCohort:
    if index.manifest is None:
        raise FreeHarmonicInputError("Free Harmonic Clustering requires a managed project.json manifest.")
    if request.design is AnalysisDesign.INDEPENDENT_GROUPS:
        if not index.has_group_metadata:
            raise FreeHarmonicInputError(
                "Independent-groups Free Harmonic Clustering requires canonical project group metadata."
            )
        try:
            index.require_group_assignments()
        except Exception as exc:
            raise FreeHarmonicInputError(str(exc)) from exc
    elif request.group_ids and not index.has_group_metadata:
        raise FreeHarmonicInputError("A paired-condition group filter requires canonical project group metadata.")

    completed, ledger_filter_applied = _completed_ledger_participants(project_root)
    completed_keys = _casefold_ids(completed)
    manual = _manifest_manual_exclusions(index)
    manual_keys = _casefold_ids(manual)
    frequency_qc = _reviewed_frequency_qc(project_root)
    frequency_excluded = _sort_ids(frequency_qc.excluded_participants)
    frequency_keys = _casefold_ids(frequency_excluded)
    frequency_recording_keys = _casefold_ids(frequency_qc.excluded_recordings)
    frequency_participant_condition_keys = _condition_identity_keys(
        frequency_qc.excluded_participant_conditions
    )
    frequency_recording_condition_keys = _condition_identity_keys(
        frequency_qc.excluded_recording_conditions
    )

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
        raise FreeHarmonicInputError("No indexed FullFFT workbooks matched the requested contrast.")
    relevant_participants = {record.participant_id.casefold() for record in relevant}
    ledger_excluded_keys = relevant_participants - completed_keys if ledger_filter_applied else set()
    participant_condition_exclusions = _relevant_participant_condition_exclusions(
        index,
        request,
        frequency_qc=frequency_qc,
        relevant_records=relevant,
    )

    active_records = tuple(
        record
        for record in relevant
        if (not ledger_filter_applied or record.participant_id.casefold() in completed_keys)
        and record.participant_id.casefold() not in manual_keys
        and record.participant_id.casefold() not in frequency_keys
        and str(record.recording_id or "").casefold() not in frequency_recording_keys
        and (record.participant_id.casefold(), record.condition.casefold())
        not in frequency_participant_condition_keys
        and (
            str(record.recording_id or "").casefold(),
            record.condition.casefold(),
        )
        not in frequency_recording_condition_keys
    )

    if request.design is AnalysisDesign.INDEPENDENT_GROUPS:
        group_a_key = group_a_id.casefold()
        group_b_key = group_b_id.casefold()
        records_a = tuple(
            record
            for record in active_records
            if record.group_id is not None and record.group_id.casefold() == group_a_key
        )
        records_b = tuple(
            record
            for record in active_records
            if record.group_id is not None and record.group_id.casefold() == group_b_key
        )
        map_a = _record_map(records_a, arm_label=group_a_label)
        map_b = _record_map(records_b, arm_label=group_b_label)
        overlap = set(map_a).intersection(map_b)
        if overlap:
            participants = ", ".join(sorted(map_a[key].participant_id for key in overlap))
            raise FreeHarmonicInputError("Independent contrast arms share participant(s): " + participants)
        ordered_a = tuple(map_a[key] for key in sorted(map_a))
        ordered_b = tuple(map_b[key] for key in sorted(map_b))
        incomplete_pairs: tuple[str, ...] = ()
    else:
        condition_a_key = request.condition_a.casefold()
        condition_b_key = str(request.condition_b).casefold()
        records_a = tuple(record for record in active_records if record.condition.casefold() == condition_a_key)
        records_b = tuple(record for record in active_records if record.condition.casefold() == condition_b_key)
        map_a = _record_map(records_a, arm_label=request.condition_a)
        map_b = _record_map(records_b, arm_label=str(request.condition_b))
        common = set(map_a).intersection(map_b)
        incomplete_keys = set(map_a).symmetric_difference(map_b)
        incomplete_pairs = _sort_ids([(map_a.get(key) or map_b[key]).participant_id for key in incomplete_keys])
        ordered_keys = sorted(common)
        ordered_a = tuple(map_a[key] for key in ordered_keys)
        ordered_b = tuple(map_b[key] for key in ordered_keys)
        for record_a, record_b in zip(ordered_a, ordered_b, strict=True):
            if (record_a.group_id or "").casefold() != (record_b.group_id or "").casefold():
                raise FreeHarmonicInputError(
                    "Paired workbook group identity changed between conditions for "
                    f"participant {record_a.participant_id}."
                )

    if not ordered_a or not ordered_b:
        raise FreeHarmonicInputError("Participant exclusions left one or both requested contrast arms empty.")
    if len(ordered_a) < 2 or len(ordered_b) < 2:
        if request.design is AnalysisDesign.PAIRED_CONDITIONS:
            detail = f"paired common cohort n={len(ordered_a)}"
        else:
            detail = f"independent arm sizes n={len(ordered_a)} and n={len(ordered_b)}"
        raise FreeHarmonicInputError(
            "Free Harmonic Clustering requires at least two participants in "
            f"each analysis arm after exclusions ({detail})."
        )

    participant_electrodes = _condition_electrode_map(
        frequency_qc.excluded_electrodes_by_participant_condition
    )
    recording_electrodes = _condition_electrode_map(
        frequency_qc.excluded_electrodes_by_recording_condition
    )
    electrode_exclusions: dict[tuple[str, str], set[str]] = defaultdict(set)
    for record in (*ordered_a, *ordered_b):
        condition_key = record.condition.casefold()
        electrode_exclusions[(record.participant_id, record.condition)].update(
            participant_electrodes.get(
                (record.participant_id.casefold(), condition_key),
                (),
            )
        )
        electrode_exclusions[(record.participant_id, record.condition)].update(
            recording_electrodes.get(
                (str(record.recording_id or "").casefold(), condition_key),
                (),
            )
        )
    electrode_exclusions = {
        identity: electrodes
        for identity, electrodes in electrode_exclusions.items()
        if electrodes
    }
    if electrode_exclusions:
        details = "; ".join(
            f"{participant} / {condition}: {', '.join(sorted(electrodes))}"
            for (participant, condition), electrodes in sorted(
                electrode_exclusions.items(),
                key=lambda row: (
                    row[0][0].casefold(),
                    row[0][1].casefold(),
                ),
            )
        )
        raise FreeHarmonicInputError(
            "Free Harmonic Clustering requires the complete BioSemi64 sensor "
            "domain; included participants have active electrode exclusions: " + details
        )

    ledger_display = {
        record.participant_id for record in relevant if record.participant_id.casefold() in ledger_excluded_keys
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
        participant_condition_exclusions=participant_condition_exclusions,
    )


def _completed_ledger_recordings(
    project_root: Path,
    index: ProjectDatasetIndex,
) -> tuple[tuple[str, ...], bool]:
    """Resolve completed repeated-session ledger keys without PID fallback."""

    ledger = load_ledger(project_root)
    entries = ledger.get("entries") if isinstance(ledger, Mapping) else None
    if not isinstance(entries, Mapping):
        return (), False
    known = {recording_id.casefold(): recording_id for recording_id in index.recordings}
    completed = _sort_ids(
        known[str(key).casefold()]
        for key, entry in entries.items()
        if str(key).casefold() in known
        and isinstance(entry, Mapping)
        and str(entry.get("status") or "").strip().casefold() == "completed"
    )
    return completed, bool(completed)


def _canonical_conditions(
    index: ProjectDatasetIndex,
    requested: Sequence[str],
) -> tuple[str, ...]:
    lookup = {condition.casefold(): condition for condition in index.conditions}
    result: list[str] = []
    for value in requested:
        canonical = lookup.get(str(value).strip().casefold())
        if canonical is None:
            raise FreeHarmonicInputError(f"Unknown indexed project condition {value!r}.")
        result.append(canonical)
    return tuple(result)


def _resolve_session(
    index: ProjectDatasetIndex,
    requested_session_id: str,
) -> ProjectSessionOption:
    key = requested_session_id.casefold()
    matches = [session for session_id, session in index.sessions.items() if str(session_id).casefold() == key]
    if len(matches) != 1:
        raise FreeHarmonicInputError(f"Unknown canonical project session_id {requested_session_id!r}.")
    session = matches[0]
    return ProjectSessionOption(
        session_id=str(session.session_id),
        label=str(session.label),
        visit_index=int(session.visit_index),
    )


def _select_repeated_batch_cohort(
    index: ProjectDatasetIndex,
    request: RepeatedSessionBatchRequest,
    project_root: Path,
) -> _RepeatedBatchCohort:
    """Freeze complete per-condition pairs and a recording-aware audit."""

    if index.manifest is None or not index.is_repeated_session:
        raise FreeHarmonicInputError("Repeated-session FHC requires a managed repeated-session project.")
    try:
        index.require_group_assignments()
        index.require_recording_assignments()
        index.require_session_assignments()
    except Exception as exc:
        raise FreeHarmonicInputError(str(exc)) from exc

    groups = tuple(
        ProjectGroupOption(group_id=group_id, label=group_label)
        for group_id, group_label in (_resolve_group(index, requested) for requested in request.group_ids)
    )
    sessions = tuple(_resolve_session(index, value) for value in request.session_ids)
    conditions = _canonical_conditions(index, request.conditions)
    group_keys = {row.group_id.casefold() for row in groups}
    session_keys = {row.session_id.casefold() for row in sessions}
    condition_keys = {value.casefold() for value in conditions}

    known_recordings = {recording_id.casefold(): recording_id for recording_id in index.recordings}
    unknown_exclusions = [
        row.recording_id for row in request.recording_exclusions if row.recording_id.casefold() not in known_recordings
    ]
    if unknown_exclusions:
        raise FreeHarmonicInputError(
            "Analysis-only exclusions reference unknown canonical recording_id(s): "
            + ", ".join(unknown_exclusions)
            + "."
        )

    frequency_qc = _reviewed_frequency_qc(project_root)
    completed, ledger_filter_applied = _completed_ledger_recordings(
        project_root,
        index,
    )
    completed_keys = _casefold_ids(completed)
    manual = _manifest_manual_exclusions(index)
    manual_keys = _casefold_ids(manual)
    frequency_participants = _sort_ids(frequency_qc.excluded_participants)
    frequency_participant_keys = _casefold_ids(frequency_participants)
    frequency_recordings = _sort_ids(frequency_qc.excluded_recordings)
    frequency_recording_keys = _casefold_ids(frequency_recordings)
    frequency_participant_condition_keys = _condition_identity_keys(
        frequency_qc.excluded_participant_conditions
    )
    frequency_recording_condition_keys = _condition_identity_keys(
        frequency_qc.excluded_recording_conditions
    )
    request_exclusion_reason = {row.recording_id.casefold(): row.reason for row in request.recording_exclusions}

    all_relevant = tuple(
        record
        for record in (*index.workbooks, *index.excluded_workbooks)
        if record.group_id is not None
        and record.group_id.casefold() in group_keys
        and record.session_id is not None
        and record.session_id.casefold() in session_keys
        and record.condition.casefold() in condition_keys
        and record.recording_id is not None
    )
    excluded_index_keys = {
        (str(record.recording_id).casefold(), record.condition.casefold())
        for record in index.excluded_workbooks
        if record.recording_id is not None
    }
    exclusion_reasons: defaultdict[tuple[str, str], set[str]] = defaultdict(set)
    for record in all_relevant:
        recording_key = str(record.recording_id).casefold()
        condition_key = record.condition.casefold()
        identity = (recording_key, condition_key)
        if identity in excluded_index_keys:
            exclusion_reasons[identity].add("Project recording/condition exclusion")
        if recording_key in request_exclusion_reason:
            exclusion_reasons[identity].add("Analysis-only exclusion: " + request_exclusion_reason[recording_key])
        if ledger_filter_applied and recording_key not in completed_keys:
            exclusion_reasons[identity].add("Processing ledger status is not completed")
        if record.participant_id.casefold() in manual_keys:
            exclusion_reasons[identity].add("Project manual participant exclusion")
        if record.participant_id.casefold() in frequency_participant_keys:
            exclusion_reasons[identity].add("Frequency-domain participant exclusion")
        if recording_key in frequency_recording_keys:
            exclusion_reasons[identity].add("Frequency-domain recording exclusion")
        if (
            record.participant_id.casefold(),
            condition_key,
        ) in frequency_participant_condition_keys:
            exclusion_reasons[identity].add(
                "Frequency-domain participant-condition exclusion"
            )
        if identity in frequency_recording_condition_keys:
            exclusion_reasons[identity].add(
                "Frequency-domain recording-condition exclusion"
            )
    participant_group_lookup = {
        participant.participant_id.casefold(): ("" if participant.group_id is None else participant.group_id.casefold())
        for participant in index.participants.values()
    }
    for recording in index.recordings.values():
        recording_key = recording.recording_id.casefold()
        if (
            recording.session_id.casefold() not in session_keys
            or participant_group_lookup.get(recording.participant_id.casefold(), "") not in group_keys
        ):
            continue
        for condition in conditions:
            identity = (recording_key, condition.casefold())
            if recording_key in request_exclusion_reason:
                exclusion_reasons[identity].add("Analysis-only exclusion: " + request_exclusion_reason[recording_key])
            if ledger_filter_applied and recording_key not in completed_keys:
                exclusion_reasons[identity].add("Processing ledger status is not completed")
            if recording.participant_id.casefold() in manual_keys:
                exclusion_reasons[identity].add("Project manual participant exclusion")
            if recording.participant_id.casefold() in frequency_participant_keys:
                exclusion_reasons[identity].add("Frequency-domain participant exclusion")
            if recording_key in frequency_recording_keys:
                exclusion_reasons[identity].add("Frequency-domain recording exclusion")
            if (
                recording.participant_id.casefold(),
                condition.casefold(),
            ) in frequency_participant_condition_keys:
                exclusion_reasons[identity].add(
                    "Frequency-domain participant-condition exclusion"
                )
            if identity in frequency_recording_condition_keys:
                exclusion_reasons[identity].add(
                    "Frequency-domain recording-condition exclusion"
                )

    active_records = tuple(
        record
        for record in index.workbooks
        if record.group_id is not None
        and record.group_id.casefold() in group_keys
        and record.session_id is not None
        and record.session_id.casefold() in session_keys
        and record.condition.casefold() in condition_keys
        and record.recording_id is not None
        and not exclusion_reasons.get((str(record.recording_id).casefold(), record.condition.casefold()))
    )
    record_by_cell: dict[tuple[str, str, str], WorkbookRecord] = {}
    for record in active_records:
        key = (
            record.participant_id.casefold(),
            str(record.session_id).casefold(),
            record.condition.casefold(),
        )
        if key in record_by_cell:
            raise FreeHarmonicInputError(
                "More than one canonical recording workbook matched participant "
                f"{record.participant_id!r}, session {record.session_id!r}, and "
                f"condition {record.condition!r}."
            )
        record_by_cell[key] = record

    recording_by_participant_session = {
        (recording.participant_id.casefold(), recording.session_id.casefold()): (recording.recording_id)
        for recording in index.recordings.values()
    }
    participant_rows = tuple(
        participant
        for participant in index.participants.values()
        if participant.group_id is not None and participant.group_id.casefold() in group_keys
    )
    audit_rows: list[RepeatedSessionCohortAuditRow] = []
    complete_participants: dict[tuple[str, str], tuple[str, ...]] = {}
    for condition in conditions:
        condition_key = condition.casefold()
        for group in groups:
            participants = sorted(
                (
                    participant.participant_id
                    for participant in participant_rows
                    if participant.group_id is not None and participant.group_id.casefold() == group.group_id.casefold()
                ),
                key=lambda value: (value.casefold(), value),
            )
            complete: list[str] = []
            for participant_id in participants:
                participant_key = participant_id.casefold()
                available: list[str] = []
                missing: list[str] = []
                recording_rows: list[tuple[str, str]] = []
                excluded_recordings: list[str] = []
                excluded_sessions: list[str] = []
                excluded_reasons: list[str] = []
                for session in sessions:
                    key = (participant_key, session.session_id.casefold(), condition_key)
                    record = record_by_cell.get(key)
                    if record is not None:
                        available.append(session.session_id)
                        recording_rows.append((session.session_id, str(record.recording_id)))
                        continue
                    missing.append(session.session_id)
                    recording_id = recording_by_participant_session.get(
                        (participant_key, session.session_id.casefold())
                    )
                    if recording_id is None:
                        continue
                    reasons = exclusion_reasons.get(
                        (recording_id.casefold(), condition_key),
                        set(),
                    )
                    if reasons:
                        excluded_recordings.append(recording_id)
                        excluded_sessions.append(session.session_id)
                        excluded_reasons.append("; ".join(sorted(reasons)))
                included = len(available) == len(sessions)
                if included:
                    complete.append(participant_id)
                audit_rows.append(
                    RepeatedSessionCohortAuditRow(
                        participant_id=participant_id,
                        group_id=group.group_id,
                        condition=condition,
                        available_session_ids=tuple(available),
                        missing_session_ids=tuple(missing),
                        recording_ids_by_session=tuple(recording_rows),
                        excluded_recording_ids=tuple(excluded_recordings),
                        excluded_session_ids=tuple(excluded_sessions),
                        exclusion_reasons=tuple(excluded_reasons),
                        included_complete_pair=included,
                    )
                )
            complete_participants[(condition_key, group.group_id.casefold())] = tuple(complete)
            if len(complete) < 2:
                raise FreeHarmonicInputError(
                    "Repeated-session FHC requires at least two complete, "
                    "phase-balanced participants in every group x condition cell; "
                    f"{group.label} / {condition} has n={len(complete)}."
                )

    source_records: list[WorkbookRecord] = []
    seen_sources: set[tuple[str, str]] = set()
    for condition in conditions:
        for group in groups:
            participants = complete_participants[(condition.casefold(), group.group_id.casefold())]
            for session in sessions:
                for participant_id in participants:
                    record = record_by_cell[
                        (
                            participant_id.casefold(),
                            session.session_id.casefold(),
                            condition.casefold(),
                        )
                    ]
                    identity = (
                        str(record.recording_id).casefold(),
                        record.condition.casefold(),
                    )
                    if identity not in seen_sources:
                        source_records.append(record)
                        seen_sources.add(identity)

    participant_electrodes = _condition_electrode_map(
        frequency_qc.excluded_electrodes_by_participant_condition
    )
    recording_electrodes = _condition_electrode_map(
        frequency_qc.excluded_electrodes_by_recording_condition
    )
    electrode_exclusions: dict[tuple[str, str], set[str]] = defaultdict(set)
    for record in source_records:
        condition_key = record.condition.casefold()
        identity = (str(record.recording_id), record.condition)
        electrode_exclusions[identity].update(
            participant_electrodes.get(
                (record.participant_id.casefold(), condition_key),
                (),
            )
        )
        electrode_exclusions[identity].update(
            recording_electrodes.get(
                (str(record.recording_id).casefold(), condition_key),
                (),
            )
        )
    electrode_exclusions = {
        identity: electrodes
        for identity, electrodes in electrode_exclusions.items()
        if electrodes
    }
    if electrode_exclusions:
        details = [
            f"{recording_id} / {condition}: {', '.join(sorted(electrodes))}"
            for (recording_id, condition), electrodes in sorted(
                electrode_exclusions.items(),
                key=lambda row: (
                    row[0][0].casefold(),
                    row[0][1].casefold(),
                ),
            )
        ]
        raise FreeHarmonicInputError(
            "Free Harmonic Clustering requires the complete BioSemi64 sensor "
            "domain; included repeated-session recordings have active electrode "
            "exclusions: " + "; ".join(details)
        )

    relevant_recording_keys = {str(record.recording_id).casefold() for record in all_relevant}
    ledger_excluded = _sort_ids(
        str(record.recording_id)
        for record in all_relevant
        if ledger_filter_applied and str(record.recording_id).casefold() not in completed_keys
    )
    return _RepeatedBatchCohort(
        conditions=conditions,
        groups=(groups[0], groups[1]),
        sessions=(sessions[0], sessions[1]),
        source_records=tuple(source_records),
        record_by_cell=record_by_cell,
        complete_participants=complete_participants,
        audit_rows=tuple(audit_rows),
        ledger_filter_applied=ledger_filter_applied,
        completed_recordings=_sort_ids(
            recording_id for recording_id in completed if recording_id.casefold() in relevant_recording_keys
        ),
        ledger_excluded_recordings=ledger_excluded,
        manual_excluded_participants=manual,
        frequency_qc_excluded_participants=frequency_participants,
        frequency_qc_excluded_recordings=frequency_recordings,
    )


def _resolved_source_path(path: Path, project_root: Path) -> tuple[Path, str]:
    resolved = Path(path).resolve(strict=False)
    try:
        relative = resolved.relative_to(project_root)
    except ValueError as exc:
        raise FreeHarmonicInputError(f"Indexed workbook escapes the active project root: {resolved}") from exc
    if not resolved.is_file():
        raise FreeHarmonicInputError(f"Indexed workbook is missing: {resolved}")
    return resolved, relative.as_posix()


def _validate_sensor_matrix(frame: Any, path: Path, plan: FrequencyWindowPlan) -> np.ndarray:
    try:
        electrodes = tuple(str(value).strip().upper() for value in frame["Electrode"])
    except Exception as exc:
        raise FreeHarmonicInputError(f"Could not read the Electrode column from {path.name}.") from exc
    expected = tuple(str(value).strip().upper() for value in DEFAULT_ELECTRODE_NAMES_64)
    if electrodes != expected:
        raise FreeHarmonicInputError(f"{path.name} does not use the exact canonical BioSemi64 sensor order.")
    try:
        matrix = np.ascontiguousarray(
            frame.loc[:, list(plan.selected_frequency_columns)].to_numpy(
                dtype=np.float64,
                copy=True,
            ),
            dtype=np.float64,
        )
    except Exception as exc:
        raise FreeHarmonicInputError(f"Selected FullFFT amplitudes in {path.name} are not numeric.") from exc
    expected_shape = (len(expected), len(plan.selected_frequency_columns))
    if matrix.shape != expected_shape:
        raise FreeHarmonicInputError(
            f"Selected FullFFT matrix in {path.name} has shape {matrix.shape}; expected {expected_shape}."
        )
    if not np.all(np.isfinite(matrix)):
        raise FreeHarmonicInputError(f"Selected FullFFT amplitudes in {path.name} contain non-finite values.")
    if np.any(matrix < 0.0):
        raise FreeHarmonicInputError(f"Selected FullFFT amplitudes in {path.name} contain negative values.")
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
    selected-column amplitude read through the neutral companion-aware adapter.
    Selected frames are converted to
    contiguous NumPy matrices immediately and are never cached run-wide.
    """

    started = perf_counter()
    if not isinstance(request, ProjectContrastRequest):
        raise TypeError("request must be a ProjectContrastRequest.")
    if not isinstance(spec, FreeHarmonicMethodSpec):
        raise TypeError("spec must be a FreeHarmonicMethodSpec.")
    project_root = request.project_root.expanduser().resolve(strict=False)
    if not project_root.is_dir() or not (project_root / "project.json").is_file():
        raise FreeHarmonicInputError("project_root must be an existing managed project containing project.json.")
    _check_cancel(cancel_check)
    try:
        index = load_project_dataset_index(project_root)
    except Exception as exc:
        raise FreeHarmonicInputError(f"Could not build the managed-project dataset index: {exc}") from exc
    if index.project_root.resolve(strict=False) != project_root:
        raise FreeHarmonicInputError("The dataset index resolved to a different active project root.")
    if index.is_repeated_session:
        raise FreeHarmonicInputError(
            "The legacy one-contrast Free Harmonic Clustering route is disabled "
            "for repeated-session projects. Use the repeated-session batch so "
            "visits remain paired and recordings are never treated as independent "
            "participants."
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
        *(("a", cohort.arm_a_label, record) for record in cohort.arm_a_records),
        *(("b", cohort.arm_b_label, record) for record in cohort.arm_b_records),
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
            raise FreeHarmonicInputError(f"Could not read {FULL_FFT_SHEET!r} header from {path.name}: {exc}") from exc
        header_seconds = perf_counter() - header_started
        try:
            workbook_plan = build_frequency_window_plan(header, spec)
        except FreeHarmonicPreparationError as exc:
            raise FreeHarmonicInputError(f"Invalid FullFFT grid in {relative}: {exc}") from exc
        if plan is None:
            plan = workbook_plan
        elif (
            workbook_plan.grid_fingerprint != plan.grid_fingerprint
            or workbook_plan.selected_columns_fingerprint != plan.selected_columns_fingerprint
        ):
            raise FreeHarmonicInputError(
                f"All consumed workbooks must share one exact FullFFT grid; {relative} differs from the first workbook."
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

    sensor_count = len(DEFAULT_ELECTRODE_NAMES_64)
    candidate_harmonic_count = int(plan.candidate_orders.size)
    candidate_shape = (sensor_count, candidate_harmonic_count)
    numeric_started = perf_counter()
    candidate_snr_a = np.empty(
        (len(cohort.arm_a_records), *candidate_shape),
        dtype=np.float64,
    )
    candidate_snr_b = np.empty(
        (len(cohort.arm_b_records), *candidate_shape),
        dtype=np.float64,
    )
    numeric_seconds_total = perf_counter() - numeric_started
    next_snr_row = {"a": 0, "b": 0}
    raw_sum_by_arm = {
        "a": np.zeros(len(plan.selected_frequency_columns), dtype=np.float64),
        "b": np.zeros(len(plan.selected_frequency_columns), dtype=np.float64),
    }
    source_workbooks: list[CohortWorkbook] = []
    reader_phase_seconds: defaultdict[str, float] = defaultdict(float)
    amplitude_seconds_total = 0.0
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
            raise FreeHarmonicInputError(f"Could not read selected FullFFT columns from {relative}: {exc}") from exc
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
            raise FreeHarmonicInputError(f"Could not compute participant SNR from {relative}: {exc}") from exc
        participant_index = next_snr_row[arm]
        target_snr = candidate_snr_a if arm == "a" else candidate_snr_b
        target_snr[participant_index] = participant_snr
        next_snr_row[arm] = participant_index + 1
        del participant_snr, target_snr
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
    grand_a = raw_sum_by_arm["a"] / (candidate_snr_a.shape[0] * sensor_count)
    grand_b = raw_sum_by_arm["b"] / (candidate_snr_b.shape[0] * sensor_count)
    selection = select_harmonics(grand_a, grand_b, plan, spec)
    selected_snr_a = select_snr_harmonics(candidate_snr_a, selection)
    selected_snr_b = select_snr_harmonics(candidate_snr_b, selection)
    del candidate_snr_a, candidate_snr_b
    normalized_a = l2_normalize_snr(selected_snr_a)
    normalized_b = l2_normalize_snr(selected_snr_b)
    numeric_seconds_total += perf_counter() - numeric_started

    diagnostics = tuple(f"{diagnostic.code}: {diagnostic.message}" for diagnostic in index.diagnostics)
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
        frequency_qc_excluded_participants=(cohort.frequency_qc_excluded_participants),
        incomplete_pair_participants=cohort.incomplete_pair_participants,
        participant_condition_exclusions=cohort.participant_condition_exclusions,
        dataset_diagnostics=diagnostics,
        full_fft_provenance_method_version=(full_fft_provenance.method_version),
        full_fft_source_fingerprint=full_fft_provenance.source_fingerprint,
        full_fft_cohort_fingerprint=full_fft_provenance.cohort_fingerprint,
        full_fft_frequency_qc_fingerprint=(full_fft_provenance.frequency_qc_fingerprint),
        full_fft_processing_export_fingerprint=(full_fft_provenance.processing_export_fingerprint),
    )
    return PreparedContrast(
        request=request,
        method=spec,
        project_root=project_root,
        arm_a_label=cohort.arm_a_label,
        arm_b_label=cohort.arm_b_label,
        participant_ids_a=tuple(record.participant_id for record in cohort.arm_a_records),
        participant_ids_b=tuple(record.participant_id for record in cohort.arm_b_records),
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


def _repeated_shared_domain_fingerprint(
    *,
    request: RepeatedSessionBatchRequest,
    plan: FrequencyWindowPlan,
    selected_orders: np.ndarray,
    selection_audit: SharedHarmonicSelectionAudit,
    full_fft_source_fingerprint: str,
) -> str:
    payload = {
        "batch_version": request.batch_version,
        "conditions": list(request.conditions),
        "group_ids": list(request.group_ids),
        "session_ids": list(request.session_ids),
        "grid_fingerprint": plan.grid_fingerprint,
        "selected_columns_fingerprint": plan.selected_columns_fingerprint,
        "selected_orders": [int(value) for value in selected_orders],
        "selector_cells": [
            {
                "label": label,
                "group_id": group_id,
                "session_id": session_id,
                "condition": condition,
                "participant_count": int(count),
                "z_hex": [float(value).hex() for value in z_values],
            }
            for label, group_id, session_id, condition, count, z_values in zip(
                selection_audit.cell_labels,
                selection_audit.cell_group_ids,
                selection_audit.cell_session_ids,
                selection_audit.cell_conditions,
                selection_audit.cell_participant_counts,
                selection_audit.z_scores,
                strict=True,
            )
        ],
        "full_fft_source_fingerprint": full_fft_source_fingerprint,
        "request_recording_exclusions": [
            {"recording_id": row.recording_id, "reason": row.reason} for row in request.recording_exclusions
        ],
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _repeated_contrast_sources(
    source_workbooks: Sequence[CohortWorkbook],
    *,
    condition: str,
    groups: tuple[ProjectGroupOption, ProjectGroupOption],
    sessions: tuple[ProjectSessionOption, ProjectSessionOption],
    family: RepeatedSessionContrastFamily,
    group_id: str | None = None,
) -> tuple[CohortWorkbook, ...]:
    rows = [
        row
        for row in source_workbooks
        if row.condition.casefold() == condition.casefold()
        and (group_id is None or (row.group_id or "").casefold() == group_id.casefold())
    ]
    result: list[CohortWorkbook] = []
    for row in rows:
        if family is RepeatedSessionContrastFamily.PAIRED_SESSIONS_WITHIN_GROUP:
            arm = "a" if (row.session_id or "").casefold() == sessions[0].session_id.casefold() else "b"
            arm_label = sessions[0].label if arm == "a" else sessions[1].label
        else:
            arm = "a" if (row.group_id or "").casefold() == groups[0].group_id.casefold() else "b"
            arm_label = groups[0].label if arm == "a" else groups[1].label
        result.append(replace(row, arm=arm, arm_label=arm_label))
    return tuple(result)


def prepare_repeated_session_batch(
    request: RepeatedSessionBatchRequest,
    spec: FreeHarmonicMethodSpec,
    *,
    progress_callback: _ProgressCallback | None = None,
    cancel_check: _CancelCheck | None = None,
) -> PreparedRepeatedSessionBatch:
    """Prepare four prespecified contrasts per condition from complete pairs.

    Source workbooks are read once for the whole batch. A single selector
    domain is resolved from equally weighted participant-mean
    group x session x condition cells and then reused without reselection.
    """

    started = perf_counter()
    if not isinstance(request, RepeatedSessionBatchRequest):
        raise TypeError("request must be a RepeatedSessionBatchRequest.")
    if not isinstance(spec, FreeHarmonicMethodSpec):
        raise TypeError("spec must be a FreeHarmonicMethodSpec.")
    project_root = request.project_root.expanduser().resolve(strict=False)
    if not project_root.is_dir() or not (project_root / "project.json").is_file():
        raise FreeHarmonicInputError("project_root must be an existing managed project containing project.json.")
    _check_cancel(cancel_check)
    try:
        index = load_project_dataset_index(project_root)
    except Exception as exc:
        raise FreeHarmonicInputError(f"Could not build the managed-project dataset index: {exc}") from exc
    if index.project_root.resolve(strict=False) != project_root:
        raise FreeHarmonicInputError("The dataset index resolved to a different active project root.")
    if not index.is_repeated_session:
        raise FreeHarmonicInputError(
            "prepare_repeated_session_batch requires canonical repeated-session recording metadata."
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
    cohort = _select_repeated_batch_cohort(index, request, project_root)
    canonical_request = replace(
        request,
        conditions=cohort.conditions,
        group_ids=(cohort.groups[0].group_id, cohort.groups[1].group_id),
        session_ids=(cohort.sessions[0].session_id, cohort.sessions[1].session_id),
    )
    total_workbooks = len(cohort.source_records)
    progress_total = total_workbooks * 2

    plan: FrequencyWindowPlan | None = None
    header_seconds_by_path: dict[Path, float] = {}
    resolved_rows: list[tuple[WorkbookRecord, Path, str]] = []
    for index_number, record in enumerate(cohort.source_records, start=1):
        _check_cancel(cancel_check)
        path, relative = _resolved_source_path(record.path, project_root)
        header_started = perf_counter()
        try:
            header = _read_fullfft_header(path)
        except Exception as exc:
            raise FreeHarmonicInputError(f"Could not read {FULL_FFT_SHEET!r} header from {path.name}: {exc}") from exc
        header_seconds = perf_counter() - header_started
        try:
            workbook_plan = build_frequency_window_plan(header, spec)
        except FreeHarmonicPreparationError as exc:
            raise FreeHarmonicInputError(f"Invalid FullFFT grid in {relative}: {exc}") from exc
        if plan is None:
            plan = workbook_plan
        elif (
            workbook_plan.grid_fingerprint != plan.grid_fingerprint
            or workbook_plan.selected_columns_fingerprint != plan.selected_columns_fingerprint
        ):
            raise FreeHarmonicInputError(
                "All repeated-session batch workbooks must share one exact "
                f"FullFFT grid; {relative} differs from the first workbook."
            )
        header_seconds_by_path[path] = header_seconds
        resolved_rows.append((record, path, relative))
        _notify_progress(progress_callback, index_number, progress_total)
    if plan is None:  # pragma: no cover - cohort minimums guarantee sources
        raise FreeHarmonicInputError("No workbooks were available for preparation.")
    if plan.grid_fingerprint != full_fft_provenance.grid_fingerprint:
        raise FreeHarmonicInputError(
            "The repeated-session FullFFT grid does not match saved neutral "
            "FullFFT provenance. Rerun post-processing; EEG preprocessing is "
            "not required."
        )

    sensor_count = len(DEFAULT_ELECTRODE_NAMES_64)
    candidate_count = int(plan.candidate_orders.size)
    candidate_snr = np.empty(
        (total_workbooks, sensor_count, candidate_count),
        dtype=np.float64,
    )
    row_by_identity: dict[tuple[str, str], int] = {}
    cell_raw_sums: defaultdict[tuple[str, str, str], np.ndarray] = defaultdict(
        lambda: np.zeros(
            len(plan.selected_frequency_columns),
            dtype=np.float64,
        )
    )
    cell_recording_counts: defaultdict[tuple[str, str, str], int] = defaultdict(int)
    source_workbooks: list[CohortWorkbook] = []
    reader_phase_seconds: defaultdict[str, float] = defaultdict(float)
    amplitude_seconds_total = 0.0
    numeric_seconds_total = 0.0
    for read_number, (record, path, relative) in enumerate(resolved_rows, start=1):
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
            raise FreeHarmonicInputError(f"Could not read selected FullFFT columns from {relative}: {exc}") from exc
        amplitude_seconds = perf_counter() - amplitude_started
        amplitude_seconds_total += amplitude_seconds
        for phase, seconds in timing_details.items():
            reader_phase_seconds[str(phase)] += float(seconds)

        numeric_started = perf_counter()
        matrix = _validate_sensor_matrix(frame, path, plan)
        del frame
        try:
            candidate_snr[read_number - 1] = compute_participant_snr(matrix, plan)
        except FreeHarmonicPreparationError as exc:
            raise FreeHarmonicInputError(f"Could not compute participant SNR from {relative}: {exc}") from exc
        identity = (
            str(record.recording_id).casefold(),
            record.condition.casefold(),
        )
        row_by_identity[identity] = read_number - 1
        cell_key = (
            str(record.group_id).casefold(),
            str(record.session_id).casefold(),
            record.condition.casefold(),
        )
        cell_raw_sums[cell_key] += np.sum(matrix, axis=0, dtype=np.float64)
        cell_recording_counts[cell_key] += 1
        del matrix
        numeric_seconds_total += perf_counter() - numeric_started
        group_index = 0 if str(record.group_id).casefold() == cohort.groups[0].group_id.casefold() else 1
        source_workbooks.append(
            CohortWorkbook(
                arm="a" if group_index == 0 else "b",
                arm_label=cohort.groups[group_index].label,
                participant_id=record.participant_id,
                condition=record.condition,
                group_id=record.group_id,
                group_label=record.group_label,
                source_path=path,
                project_relative_path=relative,
                header_read_seconds=header_seconds_by_path[path],
                amplitude_read_seconds=amplitude_seconds,
                recording_id=record.recording_id,
                session_id=record.session_id,
                session_label=record.session_label,
                visit_index=record.visit_index,
            )
        )
        _notify_progress(
            progress_callback,
            total_workbooks + read_number,
            progress_total,
        )

    numeric_started = perf_counter()
    cell_labels: list[str] = []
    cell_group_ids: list[str] = []
    cell_session_ids: list[str] = []
    cell_conditions: list[str] = []
    cell_counts: list[int] = []
    cell_grands: list[np.ndarray] = []
    for condition in cohort.conditions:
        for group in cohort.groups:
            for session in cohort.sessions:
                cell_key = (
                    group.group_id.casefold(),
                    session.session_id.casefold(),
                    condition.casefold(),
                )
                count = cell_recording_counts[cell_key]
                if count < 1:
                    raise FreeHarmonicInputError(
                        "The shared harmonic selector requires every declared "
                        "group x session x condition cell; missing "
                        f"{group.label} / {session.label} / {condition}."
                    )
                cell_labels.append(f"{group.label} | {session.label} | {condition}")
                cell_group_ids.append(group.group_id)
                cell_session_ids.append(session.session_id)
                cell_conditions.append(condition)
                cell_counts.append(count)
                cell_grands.append(cell_raw_sums[cell_key] / (count * sensor_count))
    try:
        selection, cell_z, cell_detected = select_harmonics_across_cells(
            np.ascontiguousarray(cell_grands, dtype=np.float64),
            plan,
            spec,
        )
    except NoHarmonicsSelectedError:
        raise
    except FreeHarmonicPreparationError as exc:
        raise FreeHarmonicInputError(f"Could not resolve the repeated-session shared harmonic domain: {exc}") from exc
    selection_audit = SharedHarmonicSelectionAudit(
        cell_labels=tuple(cell_labels),
        cell_group_ids=tuple(cell_group_ids),
        cell_session_ids=tuple(cell_session_ids),
        cell_conditions=tuple(cell_conditions),
        cell_participant_counts=tuple(cell_counts),
        z_scores=cell_z,
        detected=cell_detected,
    )
    shared_domain_fingerprint = _repeated_shared_domain_fingerprint(
        request=canonical_request,
        plan=plan,
        selected_orders=selection.selected_orders,
        selection_audit=selection_audit,
        full_fft_source_fingerprint=full_fft_provenance.source_fingerprint,
    )
    numeric_seconds_total += perf_counter() - numeric_started

    diagnostics = tuple(f"{diagnostic.code}: {diagnostic.message}" for diagnostic in index.diagnostics)
    project_condition_exclusions = tuple(
        ParticipantConditionExclusion(
            participant_id=participant_id,
            condition=condition,
            reason="Project recording/condition exclusion in repeated-session batch",
        )
        for participant_id, condition in sorted(
            {
                (record.participant_id, record.condition)
                for record in index.excluded_workbooks
                if record.condition.casefold() in {value.casefold() for value in cohort.conditions}
                and record.group_id is not None
                and record.group_id.casefold() in {value.group_id.casefold() for value in cohort.groups}
            },
            key=lambda row: (row[1].casefold(), row[0].casefold()),
        )
    )
    incomplete_participants = _sort_ids(
        row.participant_id for row in cohort.audit_rows if not row.included_complete_pair
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
        completed_recordings=cohort.completed_recordings,
        ledger_excluded_recordings=cohort.ledger_excluded_recordings,
        manual_excluded_participants=cohort.manual_excluded_participants,
        frequency_qc_excluded_participants=(cohort.frequency_qc_excluded_participants),
        frequency_qc_excluded_recordings=(cohort.frequency_qc_excluded_recordings),
        incomplete_pair_participants=incomplete_participants,
        participant_condition_exclusions=project_condition_exclusions,
        dataset_diagnostics=diagnostics,
        full_fft_provenance_method_version=full_fft_provenance.method_version,
        full_fft_source_fingerprint=full_fft_provenance.source_fingerprint,
        full_fft_cohort_fingerprint=full_fft_provenance.cohort_fingerprint,
        full_fft_frequency_qc_fingerprint=(full_fft_provenance.frequency_qc_fingerprint),
        full_fft_processing_export_fingerprint=(full_fft_provenance.processing_export_fingerprint),
        repeated_session_batch_version=request.batch_version,
        shared_domain_fingerprint=shared_domain_fingerprint,
        request_recording_exclusions=request.recording_exclusions,
        repeated_session_cohort_audit=cohort.audit_rows,
    )

    tensor_started = perf_counter()

    def candidate_maps(
        participant_ids: Sequence[str],
        session: ProjectSessionOption,
        condition: str,
    ) -> np.ndarray:
        rows = []
        for participant_id in participant_ids:
            record = cohort.record_by_cell[
                (
                    participant_id.casefold(),
                    session.session_id.casefold(),
                    condition.casefold(),
                )
            ]
            rows.append(
                row_by_identity[
                    (
                        str(record.recording_id).casefold(),
                        record.condition.casefold(),
                    )
                ]
            )
        return np.ascontiguousarray(candidate_snr[np.asarray(rows, dtype=np.int64)])

    runs: list[PreparedRepeatedSessionContrast] = []
    for condition in cohort.conditions:
        group_participants = tuple(
            cohort.complete_participants[(condition.casefold(), group.group_id.casefold())] for group in cohort.groups
        )
        candidates: dict[tuple[int, int], np.ndarray] = {}
        selected: dict[tuple[int, int], np.ndarray] = {}
        normalized: dict[tuple[int, int], np.ndarray] = {}
        for group_index, participant_ids in enumerate(group_participants):
            for session_index, session in enumerate(cohort.sessions):
                key = (group_index, session_index)
                candidates[key] = candidate_maps(
                    participant_ids,
                    session,
                    condition,
                )
                selected[key] = select_snr_harmonics(candidates[key], selection)
                normalized[key] = l2_normalize_snr(selected[key])

        averaged_selected = tuple(
            select_snr_harmonics(
                (candidates[(group_index, 0)] + candidates[(group_index, 1)]) / 2.0,
                selection,
            )
            for group_index in range(2)
        )
        averaged_values = tuple(l2_normalize_snr(value) for value in averaged_selected)
        pooled_family_id = RepeatedSessionContrastFamily.SESSION_AVERAGED_GROUPS.value
        pooled_request = ProjectContrastRequest(
            project_root=project_root,
            design=AnalysisDesign.INDEPENDENT_GROUPS,
            condition_a=condition,
            group_ids=(cohort.groups[0].group_id, cohort.groups[1].group_id),
            session_ids=(cohort.sessions[0].session_id, cohort.sessions[1].session_id),
            contrast_family_id=pooled_family_id,
        )
        pooled_prepared = PreparedContrast(
            request=pooled_request,
            method=spec,
            project_root=project_root,
            arm_a_label=cohort.groups[0].label,
            arm_b_label=cohort.groups[1].label,
            participant_ids_a=group_participants[0],
            participant_ids_b=group_participants[1],
            sensor_names=tuple(DEFAULT_ELECTRODE_NAMES_64),
            harmonic_orders=selection.selected_orders,
            harmonics_hz=selection.selected_harmonics_hz,
            snr_a=averaged_selected[0],
            snr_b=averaged_selected[1],
            values_a=averaged_values[0],
            values_b=averaged_values[1],
            selection=selection,
            frequency_plan=plan,
            source_workbooks=_repeated_contrast_sources(
                source_workbooks,
                condition=condition,
                groups=cohort.groups,
                sessions=cohort.sessions,
                family=RepeatedSessionContrastFamily.SESSION_AVERAGED_GROUPS,
            ),
            provenance=provenance,
        )
        runs.append(
            PreparedRepeatedSessionContrast(
                family=RepeatedSessionContrastFamily.SESSION_AVERAGED_GROUPS,
                family_id=pooled_family_id,
                family_label="Session-averaged groups",
                condition=condition,
                tensor_semantics=(RepeatedSessionTensorSemantics.SESSION_AVERAGED_NORMALIZED_PROFILE),
                prepared=pooled_prepared,
            )
        )

        for group_index, group in enumerate(cohort.groups):
            family_id = f"{RepeatedSessionContrastFamily.PAIRED_SESSIONS_WITHIN_GROUP.value}:{group.group_id}"
            paired_request = ProjectContrastRequest(
                project_root=project_root,
                design=AnalysisDesign.PAIRED_CONDITIONS,
                condition_a=condition,
                condition_b=condition,
                group_ids=(group.group_id,),
                session_ids=(
                    cohort.sessions[0].session_id,
                    cohort.sessions[1].session_id,
                ),
                contrast_family_id=family_id,
            )
            paired_prepared = PreparedContrast(
                request=paired_request,
                method=spec,
                project_root=project_root,
                arm_a_label=cohort.sessions[0].label,
                arm_b_label=cohort.sessions[1].label,
                participant_ids_a=group_participants[group_index],
                participant_ids_b=group_participants[group_index],
                sensor_names=tuple(DEFAULT_ELECTRODE_NAMES_64),
                harmonic_orders=selection.selected_orders,
                harmonics_hz=selection.selected_harmonics_hz,
                snr_a=selected[(group_index, 0)],
                snr_b=selected[(group_index, 1)],
                values_a=normalized[(group_index, 0)],
                values_b=normalized[(group_index, 1)],
                selection=selection,
                frequency_plan=plan,
                source_workbooks=_repeated_contrast_sources(
                    source_workbooks,
                    condition=condition,
                    groups=cohort.groups,
                    sessions=cohort.sessions,
                    family=(RepeatedSessionContrastFamily.PAIRED_SESSIONS_WITHIN_GROUP),
                    group_id=group.group_id,
                ),
                provenance=provenance,
            )
            runs.append(
                PreparedRepeatedSessionContrast(
                    family=(RepeatedSessionContrastFamily.PAIRED_SESSIONS_WITHIN_GROUP),
                    family_id=family_id,
                    family_label=f"Paired sessions within {group.label}",
                    condition=condition,
                    group_id=group.group_id,
                    tensor_semantics=(RepeatedSessionTensorSemantics.SESSION_NORMALIZED_PAIRED_PROFILE),
                    prepared=paired_prepared,
                )
            )

        change_family_id = RepeatedSessionContrastFamily.GROUP_SESSION_CHANGE.value
        raw_changes = tuple(selected[(group_index, 0)] - selected[(group_index, 1)] for group_index in range(2))
        normalized_changes = tuple(
            normalized[(group_index, 0)] - normalized[(group_index, 1)] for group_index in range(2)
        )
        change_request = ProjectContrastRequest(
            project_root=project_root,
            design=AnalysisDesign.INDEPENDENT_GROUPS,
            condition_a=condition,
            group_ids=(cohort.groups[0].group_id, cohort.groups[1].group_id),
            session_ids=(cohort.sessions[0].session_id, cohort.sessions[1].session_id),
            contrast_family_id=change_family_id,
        )
        change_prepared = PreparedContrast(
            request=change_request,
            method=spec,
            project_root=project_root,
            arm_a_label=(f"{cohort.groups[0].label}: {cohort.sessions[0].label} - {cohort.sessions[1].label}"),
            arm_b_label=(f"{cohort.groups[1].label}: {cohort.sessions[0].label} - {cohort.sessions[1].label}"),
            participant_ids_a=group_participants[0],
            participant_ids_b=group_participants[1],
            sensor_names=tuple(DEFAULT_ELECTRODE_NAMES_64),
            harmonic_orders=selection.selected_orders,
            harmonics_hz=selection.selected_harmonics_hz,
            snr_a=raw_changes[0],
            snr_b=raw_changes[1],
            values_a=normalized_changes[0],
            values_b=normalized_changes[1],
            selection=selection,
            frequency_plan=plan,
            source_workbooks=_repeated_contrast_sources(
                source_workbooks,
                condition=condition,
                groups=cohort.groups,
                sessions=cohort.sessions,
                family=RepeatedSessionContrastFamily.GROUP_SESSION_CHANGE,
            ),
            provenance=provenance,
        )
        runs.append(
            PreparedRepeatedSessionContrast(
                family=RepeatedSessionContrastFamily.GROUP_SESSION_CHANGE,
                family_id=change_family_id,
                family_label=(f"Group difference in {cohort.sessions[0].label} - {cohort.sessions[1].label} change"),
                condition=condition,
                tensor_semantics=(RepeatedSessionTensorSemantics.NORMALIZED_SESSION_CHANGE),
                prepared=change_prepared,
            )
        )

    numeric_seconds_total += perf_counter() - tensor_started
    provenance = replace(
        provenance,
        numeric_preparation_seconds=numeric_seconds_total,
        total_seconds=perf_counter() - started,
    )
    runs = [replace(row, prepared=replace(row.prepared, provenance=provenance)) for row in runs]

    return PreparedRepeatedSessionBatch(
        request=canonical_request,
        method=spec,
        project_root=project_root,
        conditions=cohort.conditions,
        groups=cohort.groups,
        sessions=cohort.sessions,
        contrast_runs=tuple(runs),
        shared_selection=selection,
        shared_selection_audit=selection_audit,
        frequency_plan=plan,
        sensor_names=tuple(DEFAULT_ELECTRODE_NAMES_64),
        shared_domain_fingerprint=shared_domain_fingerprint,
        source_workbooks=tuple(source_workbooks),
        cohort_audit=cohort.audit_rows,
        provenance=provenance,
    )


__all__ = [
    "FULL_FFT_SHEET",
    "prepare_project_contrast",
    "prepare_repeated_session_batch",
]
