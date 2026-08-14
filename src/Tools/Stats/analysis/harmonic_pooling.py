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

    def to_metadata(self) -> dict[str, object]:
        return {
            "group_id": self.group_id,
            "condition": self.condition,
            "participant_ids": list(self.participant_ids),
            "participant_count": self.participant_count,
            "participant_weight_within_cell": self.participant_weight_within_cell,
            "group_weight_within_condition": self.group_weight_within_condition,
            "condition_weight": self.condition_weight,
            "effective_participant_weight": self.effective_participant_weight,
        }


@dataclass(frozen=True)
class BalancedHarmonicPool:
    """Equal-group condition spectra with participant-first cell means."""

    condition_spectra: dict[str, pd.Series]
    cells: tuple[HarmonicPoolingCell, ...]
    declared_group_ids: tuple[str, ...]
    declared_conditions: tuple[str, ...]
    workbook_count: int


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
    )


__all__ = [
    "BalancedHarmonicPool",
    "HarmonicPoolingCell",
    "SYNTHETIC_SINGLE_GROUP_ID",
    "normalize_group_structure",
    "pool_group_condition_spectra",
]
