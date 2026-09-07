"""Project-wide FullFFT grid compatibility checks.

The group-significant harmonic method requires one common FFT grid so every
candidate and neighboring-noise column has the same scientific meaning.  This
module inspects workbook headers only; it does not read amplitudes or change the
locked harmonic-selection calculation.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from fractions import Fraction
from functools import lru_cache
import math
from pathlib import Path
import re
from typing import Mapping, Sequence
from xml.etree import ElementTree
import zipfile

from Main_App.processing.frequency_domain_qc import (
    active_frequency_domain_exclusions,
)
from Main_App.processing.processing_ledger import load_ledger
from Main_App.processing.missing_condition_outputs import (
    MissingConditionOutput,
    missing_condition_output_rows,
)
from Main_App.projects import WorkbookRecord, load_project_dataset_index
from Main_App.projects.frequency_protocol import (
    FrequencyProtocol,
    normalize_frequency_protocol,
)

FULL_FFT_GRID_QC_METHOD_VERSION = "project_protocol_full_fft_bin_index_v2"
FULL_FFT_SHEET_NAME = "FullFFT Amplitude (uV)"
_FREQUENCY_COLUMN = re.compile(r"^\s*(-?\d+(?:\.\d+)?)_Hz\s*$")
_DISPLAY_FREQUENCY_TOLERANCE_HZ = Fraction(1, 20_000)
_GRID_FREQUENCY_TOLERANCE_HZ = Fraction(3, 50_000)
_MAX_CACHED_GRID_LABELS = 32_768


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
    recording_id: str | None = None
    session_id: str | None = None
    session_label: str | None = None
    visit_index: int | None = None

    @property
    def pair_key(self) -> tuple[str, str]:
        identity = self.recording_id or self.participant_id
        return identity.casefold(), self.condition.casefold()

    @property
    def participant_pair_key(self) -> tuple[str, str]:
        return self.participant_id.casefold(), self.condition.casefold()

    @property
    def recording_pair_key(self) -> tuple[str, str] | None:
        if not self.recording_id:
            return None
        return self.recording_id.casefold(), self.condition.casefold()


@dataclass(frozen=True, slots=True)
class FullFftGridAudit:
    """Strict-majority FFT-grid reference plus all inspected workbooks."""

    observations: tuple[FullFftGridObservation, ...]
    reference_oddball_cycles: int | None
    reference_support: int
    reference_total: int
    oddball_frequency_hz: float
    frequency_protocol_fingerprint: str = ""
    method_version: str = FULL_FFT_GRID_QC_METHOD_VERSION
    missing_condition_outputs: tuple[MissingConditionOutput, ...] = ()

    @property
    def review_rows(self) -> tuple[MissingConditionOutput | FullFftGridObservation, ...]:
        """Missing outputs are choices to review, never members of the FFT grid."""
        return (*self.missing_condition_outputs, *self.observations)

    def __post_init__(self) -> None:
        oddball_frequency_hz = float(self.oddball_frequency_hz)
        if not math.isfinite(oddball_frequency_hz) or oddball_frequency_hz <= 0.0:
            raise ValueError(
                "FullFFT grid QC requires an explicit positive project oddball rate."
            )
        object.__setattr__(self, "oddball_frequency_hz", oddball_frequency_hz)

    @property
    def reference_duration_s(self) -> float | None:
        if self.reference_oddball_cycles is None:
            return None
        return self.reference_oddball_cycles / self.oddball_frequency_hz

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
        *,
        recording_exclusions: Mapping[str, Sequence[str]] | None = None,
    ) -> bool:
        """Return whether a proposed cohort has one valid FullFFT grid."""

        excluded_pairs = {
            (str(participant).strip().casefold(), str(condition).strip().casefold())
            for participant, conditions in exclusions.items()
            for condition in conditions
            if str(participant).strip() and str(condition).strip()
        }
        excluded_recording_pairs = {
            (str(recording).strip().casefold(), str(condition).strip().casefold())
            for recording, conditions in (recording_exclusions or {}).items()
            for condition in conditions
            if str(recording).strip() and str(condition).strip()
        }
        active = tuple(
            observation
            for observation in self.observations
            if observation.participant_pair_key not in excluded_pairs
            and (
                observation.recording_pair_key is None
                or observation.recording_pair_key not in excluded_recording_pairs
            )
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
    protocol = _require_project_frequency_protocol(dataset_index.manifest)
    ledger = load_ledger(root)
    exclusions = active_frequency_domain_exclusions(root)
    active_paths = _harmonic_active_workbook_paths(
        dataset_index.workbooks,
        ledger=ledger,
        excluded_participants=exclusions.excluded_participants,
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
                record.visit_index if record.visit_index is not None else 0,
                record.recording_id.casefold() if record.recording_id else "",
                record.condition.casefold(),
                str(record.path),
            ),
        )
    )
    observations = tuple(
        _inspect_workbook_grid(
            record,
            already_excluded=record.path.resolve(strict=False) not in active_paths,
            oddball_frequency_hz=protocol.oddball_rate_hz,
        )
        for record in records
    )
    reference = int(protocol.expected_analyzed_oddball_cycles)
    active_valid_cycles = tuple(
        observation.oddball_cycles
        for observation in observations
        if not observation.already_excluded
        and observation.issue is None
        and observation.oddball_cycles is not None
    )
    support = sum(cycles == reference for cycles in active_valid_cycles)
    total = len(active_valid_cycles)
    from Main_App.projects import (
        normalize_manual_excluded_participants,
        normalize_manual_excluded_recordings,
    )

    preprocessing = (dataset_index.manifest or {}).get("preprocessing") or {}
    missing_rows = missing_condition_output_rows(
        dataset_index, ledger,
        excluded_participants=tuple(exclusions.excluded_participants) + tuple(
            normalize_manual_excluded_participants(preprocessing.get("manual_excluded_participants"))
        ),
        excluded_recordings=tuple(exclusions.excluded_recordings) + tuple(
            normalize_manual_excluded_recordings(preprocessing.get("manual_excluded_recordings"))
        ),
    )
    return FullFftGridAudit(
        observations=observations,
        reference_oddball_cycles=reference,
        reference_support=support,
        reference_total=total,
        oddball_frequency_hz=float(protocol.oddball_rate_hz),
        frequency_protocol_fingerprint=protocol.fingerprint,
        missing_condition_outputs=missing_rows,
    )


def _require_project_frequency_protocol(
    manifest: Mapping[str, object] | None,
) -> FrequencyProtocol:
    raw_protocol = manifest.get("frequency_protocol") if manifest is not None else None
    if raw_protocol is None:
        raise RuntimeError(
            "FullFFT grid QC requires the project's confirmed frequency protocol; "
            "confirm the project rates and expected analyzed oddball cycles first."
        )
    try:
        protocol = normalize_frequency_protocol(raw_protocol)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            "FullFFT grid QC cannot use the project's invalid frequency protocol."
        ) from exc
    if (
        not protocol.is_ready
        or protocol.oddball_rate_hz is None
        or protocol.expected_analyzed_oddball_cycles is None
    ):
        raise RuntimeError(
            "FullFFT grid QC requires confirmed project rates and an expected "
            "analyzed oddball-cycle count."
        )
    return protocol


def _harmonic_active_workbook_paths(
    records: Sequence[WorkbookRecord],
    *,
    ledger: Mapping,
    excluded_participants: Sequence[str],
) -> set[Path]:
    """Mirror the participant-level cohort filters used by harmonic selection."""

    completed_identities: set[str] = set()
    entries = ledger.get("entries") if isinstance(ledger, Mapping) else None
    if isinstance(entries, Mapping):
        completed_identities = {
            str(identity).strip().casefold()
            for identity, entry in entries.items()
            if isinstance(entry, Mapping)
            and str(entry.get("status") or "") == "completed"
            and str(identity).strip()
        }
    excluded_participants = {
        str(participant_id).strip().casefold()
        for participant_id in excluded_participants
        if str(participant_id).strip()
    }
    return {
        record.path.resolve(strict=False)
        for record in records
        if (
            not completed_identities
            or (record.recording_id or record.participant_id).casefold()
            in completed_identities
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
    oddball_frequency_hz: Fraction,
) -> FullFftGridObservation:
    try:
        from Main_App.io import read_xlsx_sheet_header

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
        ) = _grid_from_header(
            header,
            oddball_frequency_hz=oddball_frequency_hz,
        )
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
        recording_id=record.recording_id,
        session_id=record.session_id,
        session_label=record.session_label,
        visit_index=record.visit_index,
    )


def _grid_from_header(
    header: Sequence[object],
    *,
    oddball_frequency_hz: Fraction,
) -> tuple[int | None, float | None, float | None, int, str | None]:
    # Only immutable text and the exact rate define this pure calculation.
    # File reads and companion validation still occur for every workbook.
    if (
        isinstance(header, (list, tuple))
        and len(header) <= _MAX_CACHED_GRID_LABELS
        and all(type(value) is str for value in header)
        and isinstance(oddball_frequency_hz, Fraction)
    ):
        return _cached_grid_from_header(tuple(header), oddball_frequency_hz)
    return _calculate_grid_from_header(header, oddball_frequency_hz=oddball_frequency_hz)


@lru_cache(maxsize=8)
def _cached_grid_from_header(
    header: tuple[str, ...], oddball_frequency_hz: Fraction,
) -> tuple[int | None, float | None, float | None, int, str | None]:
    return _calculate_grid_from_header(header, oddball_frequency_hz=oddball_frequency_hz)


def _calculate_grid_from_header(
    header: Sequence[object], *, oddball_frequency_hz: Fraction,
) -> tuple[int | None, float | None, float | None, int, str | None]:
    frequencies: list[Fraction] = []
    for value in header:
        match = _FREQUENCY_COLUMN.fullmatch(str(value or ""))
        if match is None:
            continue
        frequencies.append(Fraction(match.group(1)))
    count = len(frequencies)
    if count < 2:
        return None, None, None, count, "No usable FullFFT frequency grid was found."
    if abs(frequencies[0]) > _DISPLAY_FREQUENCY_TOLERANCE_HZ:
        return None, None, None, count, "The FullFFT grid does not begin at 0 Hz."
    if len(set(frequencies)) != count:
        return (
            None,
            None,
            None,
            count,
            "Rounded FullFFT frequency labels collide and cannot identify one grid.",
        )

    target_positions = [
        index
        for index, frequency in enumerate(frequencies)
        if abs(frequency - oddball_frequency_hz)
        <= _DISPLAY_FREQUENCY_TOLERANCE_HZ
    ]
    if len(target_positions) != 1 or target_positions[0] <= 0:
        return (
            None,
            None,
            None,
            count,
            "The FullFFT grid does not contain one displayed project oddball "
            f"target near {float(oddball_frequency_hz):.4f} Hz.",
        )

    cycles = int(target_positions[0])
    spacing = oddball_frequency_hz / cycles
    if any(
        abs(frequencies[index] - index * spacing)
        > _GRID_FREQUENCY_TOLERANCE_HZ
        for index in range(count)
    ):
        return (
            None,
            None,
            None,
            count,
            "The FullFFT frequency columns are not a uniform zero-based grid.",
        )
    duration_s = Fraction(cycles, 1) / oddball_frequency_hz
    return cycles, float(duration_s), float(spacing), count, None


__all__ = [
    "FULL_FFT_GRID_QC_METHOD_VERSION",
    "FullFftGridAudit",
    "FullFftGridObservation",
    "audit_project_full_fft_grids",
    "strict_majority_oddball_cycles",
]
