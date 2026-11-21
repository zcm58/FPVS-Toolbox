"""Publish the project review flags in the same two passes as a full preflight."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import gzip
import hashlib
import json
from pathlib import Path
from zipfile import BadZipFile

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter

from Main_App.io.atomic_write import atomic_write
from Main_App.io.safe_file import regular_file_info
from Main_App.processing.preflight_qc_pruning import namespace_cache_publication_lock, safe_cache_directory


FLAT_COLUMNS = ("PID", "Group", "Source File", "Flagged Item")
VISIT_COLUMNS = ("Participant", "Recording", "Session / phase-at-visit", "Visit", "Group", "Source File", "Flagged Item")


def write_review_sheet(target: Path, columns: tuple[str, ...], rows) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Review Flags"
    sheet.append(columns)
    for row in rows:
        sheet.append(row)
    alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    widths = [0] * len(columns)
    for row in sheet:
        for index, cell in enumerate(row):
            cell.alignment = alignment
            widths[index] = max(widths[index], len(str(cell.value or "")))
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    sheet.auto_filter.ref = sheet.dimensions
    sheet.freeze_panes = "A2"
    for index, width in enumerate(widths, 1):
        sheet.column_dimensions[get_column_letter(index)].width = min(max(width + 2, 12), 80)
    with atomic_write(target, binary=True) as stream:
        workbook.save(stream)


def _owner(row: Sequence[str]) -> tuple[str, str, str]:
    recording = row[1] if len(row) == len(VISIT_COLUMNS) and row[1] != "Not registered" else ""
    return row[0].casefold(), recording.casefold(), row[-2].casefold()


def _historic_diagnostic(item: str) -> bool:
    # The historical second pass had exactly these three rendering branches.
    return (item.startswith(("Additional signal diagnostics unavailable: ", "Display limit: "))
            or item.endswith("Provisional MNE-based review cue; this does not authorize interpolation or exclusion."))


def _previous_sheet(target: Path, sources: Mapping) -> dict:
    blocks = {key: [[], []] for key in sources}
    if regular_file_info(target) is None:
        return blocks
    book = load_workbook(target, read_only=True, data_only=False)
    try:
        sheet = book["Review Flags"]
        rows = sheet.values
        columns = tuple(next(rows, ()))
        if columns not in (FLAT_COLUMNS, VISIT_COLUMNS, ("PID", "Source File", "Flagged Item")):
            raise ValueError("Unrecognized preflight review columns")
        for row in rows:
            if len(row) != len(columns) or not all(isinstance(row[index], str) for index in (0, -2, -1)):
                raise ValueError("Incomplete historical preflight review row")
            if len(columns) == len(VISIT_COLUMNS) and not isinstance(row[1], str):
                raise ValueError("Missing recording in historical preflight review row")
            key = _owner(row)
            if key in blocks:
                blocks[key][int(_historic_diagnostic(row[-1]))].append(row[-1])
    finally:
        book.close()
    return blocks


def _read_snapshot(path: Path) -> dict:
    doc = json.loads(gzip.decompress(path.read_bytes()))
    records = doc["records"]
    encoded = json.dumps(records, separators=(",", ":"), ensure_ascii=False).encode()
    if doc["version"] != 1 or hashlib.sha256(encoded).hexdigest() != doc["sha256"]:
        raise ValueError("Invalid preflight review snapshot")
    indexed = {}
    for record in records:
        owner = tuple(record["owner"])
        passes = record["passes"]
        if (len(owner) != 3 or not all(isinstance(part, str) for part in owner)
                or owner in indexed or not isinstance(record["source"], dict)
                or not isinstance(passes, list) or len(passes) != 2
                or any(not isinstance(phase, list) or not all(isinstance(item, str) for item in phase)
                       for phase in passes)):
            raise ValueError("Invalid recording in preflight review snapshot")
        indexed[owner] = record
    return indexed


def publish_project_review_flags(target: Path, project_root: Path, sources: Sequence, refreshed: set[Path],
                                 rows: Sequence, first_pass_count: int, columns: tuple[str, ...],
                                 retained: set[Path] | None = None) -> None:
    """Retain previous blocks only for the same unreviewed recording and input generation.

    Each source is (worksheet prefix, raw identity). The caller supplies native
    full-project scan order. A reviewed file with no findings replaces both blocks.
    """
    state_dir = project_root / ".fpvs_processing" / "preflight_review_flags"
    if not safe_cache_directory(project_root, state_dir):
        raise OSError(f"Invalid project processing directory: {state_dir}")
    state_dir.mkdir(parents=True, exist_ok=True)
    with namespace_cache_publication_lock(state_dir) as acquired:
        if not acquired:
            raise OSError("Another process is updating the project review flags.")
        _publish(target, state_dir / "rows_v1.json.gz", sources, refreshed, retained, rows, first_pass_count, columns)


def _publish(target, snapshot, sources, refreshed, retained, rows, first_pass_count, columns):
    try:
        if not 0 <= first_pass_count <= len(rows):
            raise ValueError("Invalid first pass length for preflight review")
        by_owner = {_owner((*prefix, "")): (prefix, identity) for prefix, identity in sources}
        if len(by_owner) != len(sources):
            raise ValueError("Duplicate review-file identity in the current project")
        current = {key for key, (_, identity) in by_owner.items() if Path(identity["raw_file"]) in refreshed}
        keep = {key for key, (_, identity) in by_owner.items() if key not in current
                and (retained is None or Path(identity["raw_file"]) in retained)}
        blocks = {key: [[], []] for key in by_owner}
        known = set(current)
        if keep:
            if regular_file_info(snapshot) is not None:
                stored = _read_snapshot(snapshot)
                for key in keep:
                    record = stored.get(key)
                    if record and record["source"] == by_owner[key][1]:
                        blocks[key] = record["passes"]
                        known.add(key)
            elif regular_file_info(target) is not None:
                legacy = _previous_sheet(target, by_owner)
                for key in keep:
                    blocks[key] = legacy[key]
                    known.add(key)
        for index, row in enumerate(rows):
            key = _owner(row)
            if key not in current:
                raise ValueError("Preflight returned a row outside the reviewed recording scope")
            blocks[key][int(index >= first_pass_count)].append(row[-1])
        records = [{"owner": key, "source": identity, "passes": blocks[key]}
                   for key, (_prefix, identity) in by_owner.items() if key in known]
        encoded = json.dumps(records, ensure_ascii=False, separators=(",", ":")).encode()
        payload = {"version": 1, "sha256": hashlib.sha256(encoded).hexdigest(), "records": records}
        # Commit the complete per-record evidence first. A locked public workbook
        # can be regenerated on retry, including explicit empty recording blocks.
        with atomic_write(snapshot, binary=True) as stream:
            stream.write(gzip.compress(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode(),
                                       compresslevel=1, mtime=0))
        ordered = ((*prefix, item) for phase in range(2) for key, (prefix, _) in by_owner.items()
                   for item in blocks[key][phase])
        if regular_file_info(target) is not None or any(first or second for first, second in blocks.values()):
            write_review_sheet(target, columns, ordered)
    except (BadZipFile, EOFError, KeyError, TypeError, ValueError, IndexError) as exc:
        raise OSError(f"Could not reconstruct project review flags: {exc}") from exc
