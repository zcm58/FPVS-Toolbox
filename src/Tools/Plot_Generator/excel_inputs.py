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
