"""GUI-neutral balanced pooling for adaptive FPVS harmonic selection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

import pandas as pd

SYNTHETIC_SINGLE_GROUP_ID = "all_participants"


@dataclass(frozen=True)
class HarmonicPoolingCell:
    """Coverage and explicit weights for one canonical group x condition cell."""

    group_id: str
    condition: str
    participant_ids: tuple[str, ...]
    participant_count: int
    participant_weight_within_cell: float
    group_weight_within_condition: float
    condition_weight: float
    effective_participant_weight: float
    session_id: str | None = None
    recording_ids: tuple[str, ...] = ()
    session_weight: float | None = None
    task_condition_weight: float | None = None
    cell_weight: float | None = None

    def to_metadata(self) -> dict[str, object]:
        metadata: dict[str, object] = {
            "group_id": self.group_id,
            "condition": self.condition,
            "participant_ids": list(self.participant_ids),
            "participant_count": self.participant_count,
            "participant_weight_within_cell": self.participant_weight_within_cell,
            "group_weight_within_condition": self.group_weight_within_condition,
            "condition_weight": self.condition_weight,
            "effective_participant_weight": self.effective_participant_weight,
        }
        if self.session_id is not None:
            metadata.update(
                {
                    "session_id": self.session_id,
                    "recording_ids": list(self.recording_ids),
                    "session_weight": self.session_weight,
                    "task_condition_weight": self.task_condition_weight,
                    "cell_weight": self.cell_weight,
                }
            )
        return metadata


@dataclass(frozen=True)
class BalancedHarmonicPool:
    """Equal-group condition spectra with participant-first cell means."""

    condition_spectra: dict[str, pd.Series]
    cells: tuple[HarmonicPoolingCell, ...]
    declared_group_ids: tuple[str, ...]
    declared_conditions: tuple[str, ...]
    workbook_count: int
    declared_session_ids: tuple[str, ...] = ()
    analysis_condition_ids: tuple[str, ...] = ()

    @property
    def is_repeated_session(self) -> bool:
        return bool(self.declared_session_ids)


def normalize_group_structure(
    *,
    subjects: Sequence[str],
    participant_group_ids: Mapping[str, str] | None,
    declared_group_ids: Sequence[str] | None,
) -> tuple[dict[str, str], tuple[str, ...]]:
    """Resolve canonical group IDs without inferring membership from paths."""

    ordered_subjects = tuple(dict.fromkeys(str(subject) for subject in subjects))
    if participant_group_ids is None:
        return (
            {subject: SYNTHETIC_SINGLE_GROUP_ID for subject in ordered_subjects},
            (SYNTHETIC_SINGLE_GROUP_ID,),
        )

    lookup = {
        str(subject).strip().casefold(): str(group_id).strip()
        for subject, group_id in participant_group_ids.items()
        if str(subject).strip() and str(group_id).strip()
    }
    assignments: dict[str, str] = {}
    missing: list[str] = []
    for subject in ordered_subjects:
        group_id = lookup.get(subject.strip().casefold())
        if not group_id:
            missing.append(subject)
        else:
            assignments[subject] = group_id
    if missing:
        raise RuntimeError(
            "Balanced harmonic selection requires canonical group assignments for "
            "every selected participant. Missing: " + ", ".join(sorted(missing))
        )

    if declared_group_ids is None:
        groups = tuple(sorted(set(assignments.values()), key=str.casefold))
    else:
        groups = tuple(
            dict.fromkeys(
                str(group_id).strip()
                for group_id in declared_group_ids
                if str(group_id).strip()
            )
        )
    if not groups:
        raise RuntimeError("Balanced harmonic selection requires at least one group.")
    unknown = sorted(set(assignments.values()) - set(groups), key=str.casefold)
    if unknown:
        raise RuntimeError(
            "Participant group assignments are outside the declared project groups: "
            + ", ".join(unknown)
        )
    return assignments, groups


def pool_group_condition_spectra(
    *,
    spectra: Mapping[tuple[str, str], pd.Series],
    subjects: Sequence[str],
    conditions: Sequence[str],
    participant_group_ids: Mapping[str, str] | None = None,
    declared_group_ids: Sequence[str] | None = None,
) -> BalancedHarmonicPool:
    """Pool participants within cells, groups within conditions, then conditions later.

    No entirely missing declared group x condition cell is silently discarded.
    Individual missing observations are allowed and appear in the exported cell N.
    """

    assignments, groups = normalize_group_structure(
        subjects=subjects,
        participant_group_ids=participant_group_ids,
        declared_group_ids=declared_group_ids,
    )
    ordered_conditions = tuple(dict.fromkeys(str(condition) for condition in conditions))
    if not ordered_conditions:
        raise RuntimeError("Balanced harmonic selection requires at least one condition.")

    group_weight = 1.0 / len(groups)
    condition_weight = 1.0 / len(ordered_conditions)
    condition_spectra: dict[str, pd.Series] = {}
    cells: list[HarmonicPoolingCell] = []
    missing_cells: list[str] = []

    for condition in ordered_conditions:
        group_spectra: list[pd.Series] = []
        for group_id in groups:
            cell_subjects = tuple(
                sorted(
                    (
                        subject
                        for subject in subjects
                        if assignments.get(str(subject)) == group_id
                        and (str(subject), condition) in spectra
                        and not spectra[(str(subject), condition)].empty
                    ),
                    key=str.casefold,
                )
            )
            if not cell_subjects:
                missing_cells.append(f"{group_id} x {condition}")
                continue
            cell_frame = pd.concat(
                [spectra[(subject, condition)] for subject in cell_subjects],
                axis=1,
            )
            cell_spectrum = cell_frame.mean(axis=1, skipna=True).sort_index()
            group_spectra.append(cell_spectrum)
            participant_weight = 1.0 / len(cell_subjects)
            cells.append(
                HarmonicPoolingCell(
                    group_id=group_id,
                    condition=condition,
                    participant_ids=cell_subjects,
                    participant_count=len(cell_subjects),
                    participant_weight_within_cell=participant_weight,
                    group_weight_within_condition=group_weight,
                    condition_weight=condition_weight,
                    effective_participant_weight=(
                        participant_weight * group_weight * condition_weight
                    ),
                )
            )
        if len(group_spectra) == len(groups):
            condition_spectra[condition] = pd.concat(
                group_spectra,
                axis=1,
            ).mean(axis=1, skipna=True).sort_index()

    if missing_cells:
        raise RuntimeError(
            "Balanced adaptive harmonic selection cannot proceed because declared "
            "group x condition cells are entirely missing: "
            + ", ".join(missing_cells)
            + ". Complete the dataset or use a fixed/preregistered harmonic profile."
        )
    return BalancedHarmonicPool(
        condition_spectra=condition_spectra,
        cells=tuple(cells),
        declared_group_ids=groups,
        declared_conditions=ordered_conditions,
        workbook_count=len(spectra),
        analysis_condition_ids=ordered_conditions,
    )


def session_condition_cell_id(session_id: object, condition: object) -> str:
    """Return the stable local-Z cell ID for one session x task condition."""

    return f"{str(session_id)}::{str(condition)}"


def pool_group_session_condition_spectra(
    *,
    spectra: Mapping[tuple[str, str], pd.Series],
    recording_ids: Sequence[str],
    conditions: Sequence[str],
    recording_participant_ids: Mapping[str, str],
    recording_session_ids: Mapping[str, str],
    participant_group_ids: Mapping[str, str] | None = None,
    declared_group_ids: Sequence[str] | None = None,
    declared_session_ids: Sequence[str],
) -> BalancedHarmonicPool:
    """Pool a repeated project with one equally weighted local-Z cell per visit.

    Recordings are first averaged within participant inside every declared
    group x session x task-condition cell. Participants are then averaged
    within that cell and declared groups are weighted equally. The returned
    spectra use one opaque ``session::condition`` key per local-Z calculation;
    callers weight all returned spectra equally.
    """

    ordered_recordings = tuple(
        dict.fromkeys(str(recording_id) for recording_id in recording_ids)
    )
    ordered_conditions = tuple(
        dict.fromkeys(str(condition) for condition in conditions)
    )
    ordered_sessions = tuple(
        dict.fromkeys(
            str(session_id).strip()
            for session_id in declared_session_ids
            if str(session_id).strip()
        )
    )
    if not ordered_recordings:
        raise RuntimeError(
            "Repeated-session harmonic selection requires at least one recording."
        )
    if not ordered_conditions:
        raise RuntimeError(
            "Repeated-session harmonic selection requires at least one condition."
        )
    if not ordered_sessions:
        raise RuntimeError(
            "Repeated-session harmonic selection requires declared sessions."
        )

    participant_lookup = {
        str(recording_id).strip().casefold(): str(participant_id).strip()
        for recording_id, participant_id in recording_participant_ids.items()
        if str(recording_id).strip() and str(participant_id).strip()
    }
    session_lookup = {
        str(recording_id).strip().casefold(): str(session_id).strip()
        for recording_id, session_id in recording_session_ids.items()
        if str(recording_id).strip() and str(session_id).strip()
    }
    missing_participants = sorted(
        recording_id
        for recording_id in ordered_recordings
        if recording_id.casefold() not in participant_lookup
    )
    missing_sessions = sorted(
        recording_id
        for recording_id in ordered_recordings
        if recording_id.casefold() not in session_lookup
    )
    if missing_participants or missing_sessions:
        details: list[str] = []
        if missing_participants:
            details.append(
                "participant assignment: " + ", ".join(missing_participants)
            )
        if missing_sessions:
            details.append("session assignment: " + ", ".join(missing_sessions))
        raise RuntimeError(
            "Repeated-session harmonic selection requires canonical recording "
            "assignments for every selected recording. Missing " + "; ".join(details)
        )

    unknown_sessions = sorted(
        {
            session_lookup[recording_id.casefold()]
            for recording_id in ordered_recordings
        }
        - set(ordered_sessions),
        key=str.casefold,
    )
    if unknown_sessions:
        raise RuntimeError(
            "Recording session assignments are outside the declared project sessions: "
            + ", ".join(unknown_sessions)
        )

    participants = tuple(
        dict.fromkeys(
            participant_lookup[recording_id.casefold()]
            for recording_id in ordered_recordings
        )
    )
    assignments, groups = normalize_group_structure(
        subjects=participants,
        participant_group_ids=participant_group_ids,
        declared_group_ids=declared_group_ids,
    )
    group_weight = 1.0 / len(groups)
    session_weight = 1.0 / len(ordered_sessions)
    task_condition_weight = 1.0 / len(ordered_conditions)
    analysis_weight = session_weight * task_condition_weight
    cell_weight = group_weight * analysis_weight

    condition_spectra: dict[str, pd.Series] = {}
    cells: list[HarmonicPoolingCell] = []
    missing_cells: list[str] = []
    analysis_condition_ids: list[str] = []

    for session_id in ordered_sessions:
        for condition in ordered_conditions:
            analysis_id = session_condition_cell_id(session_id, condition)
            analysis_condition_ids.append(analysis_id)
            group_spectra: list[pd.Series] = []
            for group_id in groups:
                recordings_by_participant: dict[str, list[str]] = {}
                for recording_id in ordered_recordings:
                    key = recording_id.casefold()
                    participant_id = participant_lookup[key]
                    if (
                        session_lookup[key] != session_id
                        or assignments.get(participant_id) != group_id
                        or (recording_id, condition) not in spectra
                        or spectra[(recording_id, condition)].empty
                    ):
                        continue
                    recordings_by_participant.setdefault(participant_id, []).append(
                        recording_id
                    )
                if not recordings_by_participant:
                    missing_cells.append(
                        f"{group_id} x {session_id} x {condition}"
                    )
                    continue

                participant_spectra: list[pd.Series] = []
                cell_recordings: list[str] = []
                for participant_id in sorted(
                    recordings_by_participant,
                    key=str.casefold,
                ):
                    participant_recordings = sorted(
                        recordings_by_participant[participant_id],
                        key=str.casefold,
                    )
                    cell_recordings.extend(participant_recordings)
                    participant_spectra.append(
                        pd.concat(
                            [
                                spectra[(recording_id, condition)]
                                for recording_id in participant_recordings
                            ],
                            axis=1,
                        )
                        .mean(axis=1, skipna=True)
                        .sort_index()
                    )
                participant_ids = tuple(
                    sorted(recordings_by_participant, key=str.casefold)
                )
                participant_weight = 1.0 / len(participant_ids)
                group_spectrum = (
                    pd.concat(participant_spectra, axis=1)
                    .mean(axis=1, skipna=True)
                    .sort_index()
                )
                group_spectra.append(group_spectrum)
                cells.append(
                    HarmonicPoolingCell(
                        group_id=group_id,
                        condition=condition,
                        participant_ids=participant_ids,
                        participant_count=len(participant_ids),
                        participant_weight_within_cell=participant_weight,
                        group_weight_within_condition=group_weight,
                        condition_weight=analysis_weight,
                        effective_participant_weight=(
                            participant_weight * cell_weight
                        ),
                        session_id=session_id,
                        recording_ids=tuple(cell_recordings),
                        session_weight=session_weight,
                        task_condition_weight=task_condition_weight,
                        cell_weight=cell_weight,
                    )
                )
            if len(group_spectra) == len(groups):
                condition_spectra[analysis_id] = (
                    pd.concat(group_spectra, axis=1)
                    .mean(axis=1, skipna=True)
                    .sort_index()
                )

    if missing_cells:
        raise RuntimeError(
            "Balanced repeated-session adaptive harmonic selection cannot proceed "
            "because declared group x session x condition cells are entirely "
            "missing: "
            + ", ".join(missing_cells)
            + ". Missing visits remain missing; complete the cell or use a "
            "fixed/preregistered harmonic profile."
        )
    return BalancedHarmonicPool(
        condition_spectra=condition_spectra,
        cells=tuple(cells),
        declared_group_ids=groups,
        declared_conditions=ordered_conditions,
        workbook_count=len(spectra),
        declared_session_ids=ordered_sessions,
        analysis_condition_ids=tuple(analysis_condition_ids),
    )


__all__ = [
    "BalancedHarmonicPool",
    "HarmonicPoolingCell",
    "SYNTHETIC_SINGLE_GROUP_ID",
    "normalize_group_structure",
    "pool_group_condition_spectra",
    "pool_group_session_condition_spectra",
    "session_condition_cell_id",
]
