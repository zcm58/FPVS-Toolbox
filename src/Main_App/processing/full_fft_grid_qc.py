"""Project-wide FullFFT grid compatibility checks.

The group-significant harmonic method requires one common FFT grid so every
candidate and neighboring-noise column has the same scientific meaning.  This
module inspects workbook headers only; it does not read amplitudes or change the
locked harmonic-selection calculation.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Mapping, Sequence
from xml.etree import ElementTree
import zipfile

from Main_App.Shared.fft_crop_utils import ODDBALL_FREQ
from Main_App.processing.frequency_domain_qc import (
    active_frequency_domain_exclusions,
)
from Main_App.processing.processing_ledger import load_ledger
from Main_App.projects import WorkbookRecord, load_project_dataset_index

FULL_FFT_GRID_QC_METHOD_VERSION = "full_fft_oddball_bin_index_v1"
FULL_FFT_SHEET_NAME = "FullFFT Amplitude (uV)"
_FREQUENCY_COLUMN = re.compile(r"^\s*(-?\d+(?:\.\d+)?)_Hz\s*$")


@dataclass(frozen=True, slots=True)
class FullFftGridObservation:
    """One participant-condition workbook's FFT-grid identity."""

    participant_id: str
    condition: str
    path: Path
    group_id: str | None
    group_label: str | None
    oddball_cycles: int | None
    duration_s: float | None
    bin_spacing_hz: float | None
    frequency_column_count: int
    issue: str | None
    already_excluded: bool

    @property
    def pair_key(self) -> tuple[str, str]:
        return self.participant_id.casefold(), self.condition.casefold()


@dataclass(frozen=True, slots=True)
class FullFftGridAudit:
    """Strict-majority FFT-grid reference plus all inspected workbooks."""

    observations: tuple[FullFftGridObservation, ...]
    reference_oddball_cycles: int | None
    reference_support: int
    reference_total: int
    method_version: str = FULL_FFT_GRID_QC_METHOD_VERSION

    @property
    def reference_duration_s(self) -> float | None:
        if self.reference_oddball_cycles is None:
            return None
        return self.reference_oddball_cycles / float(ODDBALL_FREQ)

    @property
    def review_candidates(self) -> tuple[FullFftGridObservation, ...]:
        """Return active invalid or non-reference participant-condition grids."""

        return tuple(
            observation
            for observation in self.observations
            if not observation.already_excluded
            and (
                observation.issue is not None
                or (
                    self.reference_oddball_cycles is not None
                    and observation.oddball_cycles
                    != self.reference_oddball_cycles
                )
            )
        )

    @property
    def has_unresolved_grid_conflict(self) -> bool:
        """Return whether active valid workbooks have multiple grids but no mode."""

        return (
            self.reference_oddball_cycles is None
            and len(
                {
                    observation.oddball_cycles
                    for observation in self.observations
                    if not observation.already_excluded
                    and observation.issue is None
                    and observation.oddball_cycles is not None
                }
            )
            > 1
        )

    def is_compatible_with_exclusions(
        self,
        exclusions: Mapping[str, Sequence[str]],
    ) -> bool:
        """Return whether a proposed cohort has one valid FullFFT grid."""

        excluded_pairs = {
            (str(participant).strip().casefold(), str(condition).strip().casefold())
            for participant, conditions in exclusions.items()
            for condition in conditions
            if str(participant).strip() and str(condition).strip()
        }
        active = tuple(
            observation
            for observation in self.observations
            if observation.pair_key not in excluded_pairs
        )
        if not active or any(observation.issue is not None for observation in active):
            return False
        return (
            len(
                {
                    observation.oddball_cycles
                    for observation in active
                    if observation.oddball_cycles is not None
                }
            )
            == 1
        )


def audit_project_full_fft_grids(
    project_root: str | Path,
) -> FullFftGridAudit:
    """Inspect every managed FullFFT header, including already excluded pairs."""

    root = Path(project_root).resolve(strict=False)
    dataset_index = load_project_dataset_index(root)
    active_paths = _harmonic_active_workbook_paths(
        root,
        dataset_index.workbooks,
    )
    active_records = tuple(
        record
        for record in dataset_index.workbooks
        if record.path.resolve(strict=False) in active_paths
    )
    records = tuple(
        sorted(
            (*active_records, *dataset_index.excluded_workbooks),
            key=lambda record: (
                record.group_label.casefold() if record.group_label else "",
                record.participant_id.casefold(),
                record.condition.casefold(),
                str(record.path),
            ),
        )
    )
    observations = tuple(
        _inspect_workbook_grid(
            record,
            already_excluded=record.path.resolve(strict=False) not in active_paths,
        )
        for record in records
    )
    reference, support, total = strict_majority_oddball_cycles(
        observations
    )
    return FullFftGridAudit(
        observations=observations,
        reference_oddball_cycles=reference,
        reference_support=support,
        reference_total=total,
    )


def _harmonic_active_workbook_paths(
    project_root: Path,
    records: Sequence[WorkbookRecord],
) -> set[Path]:
    """Mirror the participant-level cohort filters used by harmonic selection."""

    completed_participants: set[str] = set()
    ledger = load_ledger(project_root)
    entries = ledger.get("entries") if isinstance(ledger, Mapping) else None
    if isinstance(entries, Mapping):
        completed_participants = {
            str(participant_id).strip().casefold()
            for participant_id, entry in entries.items()
            if isinstance(entry, Mapping)
            and str(entry.get("status") or "") == "completed"
            and str(participant_id).strip()
        }
    excluded_participants = {
        str(participant_id).strip().casefold()
        for participant_id in active_frequency_domain_exclusions(
            project_root
        ).excluded_participants
        if str(participant_id).strip()
    }
    return {
        record.path.resolve(strict=False)
        for record in records
        if (
            not completed_participants
            or record.participant_id.casefold() in completed_participants
        )
        and record.participant_id.casefold() not in excluded_participants
    }


def strict_majority_oddball_cycles(
    observations: Sequence[FullFftGridObservation],
) -> tuple[int | None, int, int]:
    """Return a unique strict-majority grid from active valid observations."""

    cycles = [
        int(observation.oddball_cycles)
        for observation in observations
        if not observation.already_excluded
        and observation.issue is None
        and observation.oddball_cycles is not None
    ]
    total = len(cycles)
    if total < 2:
        return None, 0, total
    counts = Counter(cycles)
    reference, support = counts.most_common(1)[0]
    if support < 2 or support * 2 <= total:
        return None, support, total
    return int(reference), int(support), total


def _inspect_workbook_grid(
    record: WorkbookRecord,
    *,
    already_excluded: bool,
) -> FullFftGridObservation:
    try:
        from Tools.Stats.io.xlsx_selected_reader import read_xlsx_sheet_header

        header = read_xlsx_sheet_header(
            record.path,
            sheet_name=FULL_FFT_SHEET_NAME,
        )
        (
            oddball_cycles,
            duration_s,
            bin_spacing_hz,
            frequency_column_count,
            issue,
        ) = _grid_from_header(header)
    except (
        OSError,
        ValueError,
        KeyError,
        zipfile.BadZipFile,
        ElementTree.ParseError,
    ) as exc:
        oddball_cycles = None
        duration_s = None
        bin_spacing_hz = None
        frequency_column_count = 0
        issue = f"FullFFT header could not be inspected: {exc}"
    return FullFftGridObservation(
        participant_id=record.participant_id,
        condition=record.condition,
        path=record.path,
        group_id=record.group_id,
        group_label=record.group_label,
        oddball_cycles=oddball_cycles,
        duration_s=duration_s,
        bin_spacing_hz=bin_spacing_hz,
        frequency_column_count=frequency_column_count,
        issue=issue,
        already_excluded=already_excluded,
    )


def _grid_from_header(
    header: Sequence[object],
) -> tuple[int | None, float | None, float | None, int, str | None]:
    frequencies: list[float] = []
    for value in header:
        match = _FREQUENCY_COLUMN.fullmatch(str(value or ""))
        if match is None:
            continue
        frequencies.append(float(match.group(1)))
    count = len(frequencies)
    if count < 2:
        return None, None, None, count, "No usable FullFFT frequency grid was found."
    if abs(frequencies[0]) > 5e-5:
        return None, None, None, count, "The FullFFT grid does not begin at 0 Hz."

    oddball_hz = float(ODDBALL_FREQ)
    target_positions = [
        index
        for index, frequency in enumerate(frequencies)
        if abs(frequency - oddball_hz) <= 5e-5
    ]
    if len(target_positions) != 1 or target_positions[0] <= 0:
        return (
            None,
            None,
            None,
            count,
            "The FullFFT grid does not contain one exact 1.2000 Hz target column.",
        )

    cycles = int(target_positions[0])
    spacing = oddball_hz / cycles
    if any(
        abs(frequencies[index] - index * spacing) > 6e-5
        for index in range(count)
    ):
        return (
            None,
            None,
            None,
            count,
            "The FullFFT frequency columns are not a uniform zero-based grid.",
        )
    duration_s = cycles / oddball_hz
    return cycles, duration_s, 1.0 / duration_s, count, None


__all__ = [
    "FULL_FFT_GRID_QC_METHOD_VERSION",
    "FullFftGridAudit",
    "FullFftGridObservation",
    "audit_project_full_fft_grids",
    "strict_majority_oddball_cycles",
]
