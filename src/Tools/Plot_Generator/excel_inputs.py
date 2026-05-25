"""Pure Excel input helpers for Plot Generator workers."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, Sequence

_PID_PATTERN = re.compile(r"(?:[A-Za-z]*)?(P\d+)", re.IGNORECASE)


def _infer_subject_id_from_path(
    excel_path: Path,
    known_subjects: Iterable[str] | None = None,
) -> str | None:
    """Return a best-effort subject identifier inferred from the file name."""

    cleaned = excel_path.stem.strip()
    if not cleaned:
        return None
    stem_upper = cleaned.upper()
    if known_subjects is not None:
        candidates = sorted(
            {
                str(subject).strip().upper()
                for subject in known_subjects
                if str(subject).strip()
            },
            key=len,
            reverse=True,
        )
        for candidate in candidates:
            if stem_upper == candidate or stem_upper.startswith(f"{candidate}_"):
                return candidate

    match = _PID_PATTERN.search(excel_path.stem)
    if match:
        return match.group(1).upper()
    return stem_upper


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
