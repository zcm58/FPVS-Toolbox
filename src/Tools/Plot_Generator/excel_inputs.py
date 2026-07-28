"""Pure Excel input helpers for Plot Generator workers."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Iterable, Sequence

from Main_App.projects import infer_workbook_participant_id


def _infer_subject_id_from_path(
    excel_path: Path,
    known_subjects: Iterable[str] | None = None,
) -> str | None:
    """Delegate legacy subject matching to the shared dataset identity owner."""

    return infer_workbook_participant_id(
        excel_path,
        known_participant_ids=known_subjects or (),
        fallback_to_stem=True,
    )


def _frequency_pairs_from_columns(columns: Iterable[object]) -> list[tuple[float, str]]:
    freq_pairs: list[tuple[float, str]] = []
    for col in columns:
        if isinstance(col, str) and col.endswith("_Hz"):
            try:
                freq_pairs.append((float(col.split("_")[0]), col))
            except ValueError:
                continue
    freq_pairs.sort(key=lambda item: item[0])
    return freq_pairs


def _select_frequency_pairs(
    freq_pairs: Sequence[tuple[float, str]],
    *,
    x_min: float,
    x_max: float,
) -> tuple[list[float], list[str]]:
    tolerance = 1e-3
    selected = [
        (freq, col)
        for freq, col in freq_pairs
        if (x_min - tolerance) <= freq <= (x_max + tolerance)
    ]
    return [freq for freq, _ in selected], [col for _, col in selected]


def _frequency_grids_match(
    reference: Sequence[float],
    candidate: Sequence[float],
    *,
    tolerance: float = 1e-9,
) -> bool:
    """Return whether two ordered FullSNR grids are positionally compatible."""

    return len(reference) == len(candidate) and all(
        math.isclose(
            float(reference_value),
            float(candidate_value),
            rel_tol=0.0,
            abs_tol=tolerance,
        )
        for reference_value, candidate_value in zip(
            reference,
            candidate,
            strict=True,
        )
    )
