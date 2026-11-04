"""Read a bounded project-local history without inspecting EEG or output files."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import logging
import os
from pathlib import Path
from typing import Literal


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CompletedProcessingRun:
    """A completed data-processing run, not a downstream analysis release."""

    timestamp: datetime
    participant_count: int | None
    successful_recording_count: int


@dataclass(frozen=True, slots=True)
class ProcessingHistoryStatus:
    state: Literal["completed", "missing", "unavailable"]
    latest_completed_run: CompletedProcessingRun | None = None
    history_incomplete: bool = False


def _count(value: object) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result.astimezone(UTC) if result.tzinfo is not None else None
    except (ValueError, OverflowError):
        return None


def _participant_count(record: Mapping, successful_files: int) -> int | None:
    # Explicit run-scoped identities avoid counting visits or conditions as people.
    identities = record.get("successful_participant_ids")
    if identities is not None:
        if not isinstance(identities, list) or not identities or any(
            not isinstance(value, str) or not value.strip() for value in identities
        ):
            return None
        count = len({value.strip().casefold() for value in identities})
        stored_count = record.get("successful_participant_count", count)
        return count if _count(stored_count) == count <= successful_files else None
    stored_count = _count(record.get("successful_participant_count"))
    if stored_count is not None:
        return stored_count if 0 < stored_count <= successful_files else None

    outcomes = record.get("recording_condition_outcomes")
    cells = outcomes.get("cells") if isinstance(outcomes, Mapping) else None
    if not isinstance(cells, list):
        return None
    people: set[str] = set()
    recordings: dict[str, str] = {}
    for cell in cells:
        if not isinstance(cell, Mapping):
            return None
        contributor = _count(cell.get("contributor_count"))
        if contributor == 0:
            continue
        if contributor != 1:
            return None
        status = cell.get("status")
        if not isinstance(status, str) or status not in {"ready", "partially_retained"}:
            return None
        participant, recording = cell.get("participant_id"), cell.get("processing_id")
        if (not isinstance(participant, str) or not participant.strip()
                or not isinstance(recording, str) or not recording.strip()):
            return None
        participant, recording = participant.strip().casefold(), recording.strip().casefold()
        if recording in recordings and recordings[recording] != participant:
            return None
        recordings[recording] = participant
        people.add(participant)
    # Do not count an entire expected cohort when only part was processed now.
    return len(people) if people and len(recordings) == successful_files else None


def _completed_run(record: Mapping) -> CompletedProcessingRun | None:
    timestamp = _timestamp(record.get("timestamp"))
    successful = _count(record.get("successful_files"))
    run_files = _count(record.get("run_files"))
    failed = _count(record.get("failed_files"))
    excluded = _count(record.get("excluded_files", 0))
    warnings = _count(record.get("condition_warning_files", 0))
    if (timestamp is None or record.get("cancelled") is not False
            or successful is None or successful == 0 or run_files is None
            or failed != 0 or warnings != 0 or excluded is None
            or successful + excluded != run_files):
        return None
    outcomes = record.get("recording_condition_outcomes")
    if outcomes is not None and (
        not isinstance(outcomes, Mapping)
        or outcomes.get("reconciliation_status") != "complete"
        or outcomes.get("is_pre_review_ready") is not True
    ):
        return None
    return CompletedProcessingRun(timestamp, _participant_count(record, successful), successful)


def latest_completed_processing_run(records: Iterable[Mapping]) -> CompletedProcessingRun | None:
    """Select by the saved aware completion time; unavailable counts stay unknown."""
    latest: CompletedProcessingRun | None = None
    for record in records:
        candidate = _completed_run(record)
        if candidate is not None and (latest is None or candidate.timestamp > latest.timestamp):
            latest = candidate
    return latest


def _read_tail(path: Path, max_bytes: int) -> tuple[bytes, bool]:
    from Main_App.io.safe_file import regular_file_info

    expected = regular_file_info(path)
    if expected is None:
        raise FileNotFoundError(path)
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        if (opened.st_dev, opened.st_ino) != (expected.st_dev, expected.st_ino):
            raise OSError("Processing history changed while opening")
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        start = max(0, size - max_bytes)
        boundary = True
        if start:
            stream.seek(start - 1)
            boundary = stream.read(1) == b"\n"
        stream.seek(start)
        data = stream.read(max_bytes)
    limited = size > max_bytes
    if limited and not boundary:
        # The leading bytes may belong to a record whose beginning was not read.
        _partial, separator, data = data.partition(b"\n")
        if not separator:
            data = b""
    return data, limited


def load_processing_history(
    project_root: Path, *, max_bytes: int = 16 * 1024 * 1024, max_records: int = 128,
) -> ProcessingHistoryStatus:
    """Read recent native run records, with finite I/O and no project mutation.

    Call from a worker: historical records can include sizeable QC provenance.
    Missing historical participant identities never become recording counts.
    """
    if type(max_bytes) is not int or max_bytes < 1 or type(max_records) is not int or max_records < 1:
        raise ValueError("Processing history limits must be positive integers")
    from Main_App.processing.preflight_qc_pruning import safe_cache_directory
    from Main_App.processing.processing_ledger import runs_path

    root = Path(project_root)
    path = runs_path(root)
    if not safe_cache_directory(root, path.parent):
        return ProcessingHistoryStatus("unavailable")
    try:
        data, limited = _read_tail(path, max_bytes)
    except FileNotFoundError:
        return ProcessingHistoryStatus("missing")
    except OSError:
        logger.warning("processing_history_unreadable", extra={"path": str(path)}, exc_info=True)
        return ProcessingHistoryStatus("unavailable")
    lines = [line for line in data.splitlines() if line.strip()]
    limited = limited or len(lines) > max_records
    records: list[Mapping] = []
    malformed = False
    for line in lines[-max_records:]:
        try:
            record = json.loads(line)
        except (UnicodeDecodeError, ValueError, RecursionError):
            # Corrupt records can exceed JSON's nesting or integer limits.
            # Keep other readable completions instead of losing the whole tail.
            malformed = True
            continue
        if not isinstance(record, Mapping):
            malformed = True
            continue
        if (_timestamp(record.get("timestamp")) is None
                or type(record.get("cancelled")) is not bool
                or any(_count(record.get(key)) is None
                       for key in ("run_files", "successful_files", "failed_files"))
                or any(_count(record.get(key, 0)) is None
                       for key in ("excluded_files", "condition_warning_files"))):
            malformed = True
            continue
        records.append(record)
    latest = latest_completed_processing_run(records)
    if malformed:
        logger.warning("processing_history_invalid_records", extra={"path": str(path)})
    if latest is not None:
        return ProcessingHistoryStatus("completed", latest, limited or malformed)
    return ProcessingHistoryStatus("unavailable" if limited or malformed else "missing", history_incomplete=limited or malformed)
