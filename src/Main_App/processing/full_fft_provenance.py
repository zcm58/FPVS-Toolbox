"""Neutral project-local provenance for processed FullFFT workbooks.

This module owns the source identity used by sibling analyses that consume the
original ``FullFFT Amplitude (uV)`` sheets.  It deliberately records no Stats
harmonic-selection state and does not depend on a Summed-BCA cache.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import math
from pathlib import Path
import re

from Main_App.processing.frequency_domain_qc import (
    active_frequency_domain_exclusions,
)
from Main_App.processing.processing_ledger import load_ledger
from Main_App.projects import (
    ProjectDatasetIndex,
    load_project_dataset_index,
    normalize_preprocessing_settings,
)


FULL_FFT_PROVENANCE_SCHEMA_VERSION = 1
FULL_FFT_PROVENANCE_METHOD_VERSION = "project_full_fft_provenance_v1"
FULL_FFT_PROVENANCE_MANIFEST_PATH = (
    "tools",
    "processing",
    "full_fft_provenance",
)
FULL_FFT_SHEET_NAME = "FullFFT Amplitude (uV)"

_FREQUENCY_COLUMN = re.compile(
    r"^([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)_Hz$"
)
_RATE_TOLERANCE_HZ = 1e-9
_ZERO_TOLERANCE_HZ = 5e-5
_TARGET_TOLERANCE_HZ = 5e-5
_GRID_TOLERANCE_HZ = 6e-5


class FullFftProvenanceError(ValueError):
    """Base error for missing, stale, or invalid FullFFT provenance."""


class FullFftProvenanceMissingError(FullFftProvenanceError):
    """Raised when a managed project predates neutral FullFFT provenance."""


class FullFftProvenanceStaleError(FullFftProvenanceError):
    """Raised when current FullFFT/cohort inputs differ from the saved record."""


@dataclass(frozen=True, slots=True)
class FullFftProvenance:
    """Validated identity of one current project-wide FullFFT source family."""

    project_root: Path
    saved_at: str
    method_version: str
    base_frequency_hz: float
    oddball_frequency_hz: float
    grid_fingerprint: str
    frequency_resolution_hz: float
    upper_frequency_hz: float
    frequency_column_count: int
    source_workbook_count: int
    source_paths: tuple[str, ...]
    cohort_fingerprint: str
    source_fingerprint: str
    frequency_qc_fingerprint: str
    processing_export_fingerprint: str


@dataclass(frozen=True, slots=True)
class _SourceSnapshot:
    source_rows: tuple[dict[str, object], ...]
    source_paths: tuple[str, ...]
    cohort_state: dict[str, object]
    frequency_qc_state: dict[str, object]
    processing_export_rows: tuple[dict[str, object], ...]
    cohort_fingerprint: str
    source_fingerprint: str
    frequency_qc_fingerprint: str
    processing_export_fingerprint: str


@dataclass(frozen=True, slots=True)
class _GridIdentity:
    fingerprint: str
    frequency_resolution_hz: float
    upper_frequency_hz: float
    frequency_column_count: int


def _positive_frequency(value: object, *, label: str) -> float:
    if isinstance(value, bool):
        raise FullFftProvenanceError(f"{label} must be finite and positive.")
    try:
        frequency = float(value)
    except (TypeError, ValueError) as exc:
        raise FullFftProvenanceError(
            f"{label} must be finite and positive."
        ) from exc
    if not math.isfinite(frequency) or frequency <= 0.0:
        raise FullFftProvenanceError(f"{label} must be finite and positive.")
    return frequency


def _same_rate(left: float, right: float) -> bool:
    return math.isclose(
        float(left),
        float(right),
        rel_tol=0.0,
        abs_tol=_RATE_TOLERANCE_HZ,
    )


def _hash_payload(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _fingerprint_columns(
    columns: Sequence[str],
    frequencies_hz: Sequence[float],
) -> str:
    """Match the exact FullFFT-grid identity used by FHC preparation."""

    digest = hashlib.sha256()
    for column, frequency in zip(columns, frequencies_hz, strict=True):
        digest.update(str(column).encode("utf-8"))
        digest.update(b"\0")
        digest.update(float(frequency).hex().encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _manifest_relative_path(project_root: Path, path: Path) -> tuple[Path, str]:
    resolved = Path(path).resolve(strict=False)
    try:
        relative = resolved.relative_to(project_root)
    except ValueError as exc:
        raise FullFftProvenanceError(
            f"Indexed FullFFT workbook escapes the active project root: {resolved}"
        ) from exc
    if not resolved.is_file():
        raise FullFftProvenanceStaleError(
            f"Indexed FullFFT workbook is missing: {relative.as_posix()}"
        )
    return resolved, relative.as_posix()


def _manual_excluded_participants(index: ProjectDatasetIndex) -> set[str]:
    manifest = index.manifest if isinstance(index.manifest, Mapping) else {}
    raw = manifest.get("preprocessing")
    preprocessing = normalize_preprocessing_settings(
        raw if isinstance(raw, Mapping) else {}
    )
    return {
        str(value).strip().casefold()
        for value in preprocessing.get("manual_excluded_participants", ())
        if str(value).strip()
    }


def _completed_ledger_state(
    project_root: Path,
) -> tuple[set[str], tuple[dict[str, object], ...], bool]:
    ledger = load_ledger(project_root)
    entries = ledger.get("entries") if isinstance(ledger, Mapping) else None
    if not isinstance(entries, Mapping):
        return set(), (), False
    completed_rows: list[dict[str, object]] = []
    completed_keys: set[str] = set()
    for participant_id, entry in entries.items():
        if not isinstance(entry, Mapping):
            continue
        if str(entry.get("status") or "").strip().casefold() != "completed":
            continue
        participant = str(participant_id).strip()
        if not participant:
            continue
        completed_keys.add(participant.casefold())
        completed_rows.append(
            {
                "participant_id": participant,
                "processing_fingerprint_version": str(
                    entry.get("processing_fingerprint_version") or ""
                ),
                "processing_fingerprint": str(
                    entry.get("processing_fingerprint") or ""
                ),
                "condition_completeness": str(
                    entry.get("condition_completeness") or ""
                ),
            }
        )
    completed_rows.sort(
        key=lambda row: (
            str(row["participant_id"]).casefold(),
            str(row["participant_id"]),
        )
    )
    return completed_keys, tuple(completed_rows), bool(completed_keys)


def _source_snapshot(
    project_root: Path,
    index: ProjectDatasetIndex,
) -> _SourceSnapshot:
    if index.project_root.resolve(strict=False) != project_root:
        raise FullFftProvenanceError(
            "The supplied dataset index belongs to a different active project root."
        )
    if index.manifest is None:
        raise FullFftProvenanceError(
            "FullFFT provenance requires a managed project.json manifest."
        )

    completed, processing_rows, ledger_filter_applied = _completed_ledger_state(
        project_root
    )
    manual_excluded = _manual_excluded_participants(index)
    frequency_qc = active_frequency_domain_exclusions(project_root)
    if frequency_qc.downstream_outputs_stale:
        raise FullFftProvenanceStaleError(
            "Frequency-domain cohort/QC state is stale. Complete the required "
            "post-processing review before using FullFFT analyses."
        )
    frequency_excluded = {
        str(value).strip().casefold()
        for value in frequency_qc.excluded_participants
        if str(value).strip()
    }
    active_records = tuple(
        record
        for record in index.workbooks
        if (
            not ledger_filter_applied
            or record.participant_id.casefold() in completed
        )
        and record.participant_id.casefold() not in manual_excluded
        and record.participant_id.casefold() not in frequency_excluded
    )
    if not active_records:
        raise FullFftProvenanceError(
            "No active indexed FullFFT workbooks remain after project cohort filters."
        )

    source_rows: list[dict[str, object]] = []
    for record in active_records:
        resolved, relative = _manifest_relative_path(project_root, record.path)
        stat = resolved.stat()
        source_rows.append(
            {
                "participant_id": str(record.participant_id),
                "condition": str(record.condition),
                "group_id": (
                    str(record.group_id) if record.group_id is not None else None
                ),
                "group_label": (
                    str(record.group_label)
                    if record.group_label is not None
                    else None
                ),
                "path": relative,
                "size_bytes": int(stat.st_size),
                "mtime_ns": int(stat.st_mtime_ns),
            }
        )
    source_rows.sort(
        key=lambda row: (
            str(row["condition"]).casefold(),
            str(row.get("group_id") or "").casefold(),
            str(row["participant_id"]).casefold(),
            str(row["path"]).casefold(),
            str(row["path"]),
        )
    )

    frequency_qc_payload = {
        "excluded_participants": sorted(frequency_excluded),
        "electrode_exclusions": {
            str(participant).strip().casefold(): sorted(
                str(electrode).strip().upper()
                for electrode in electrodes
                if str(electrode).strip()
            )
            for participant, electrodes in sorted(
                frequency_qc.auto_excluded_electrodes_by_participant.items(),
                key=lambda row: str(row[0]).casefold(),
            )
            if str(participant).strip() and electrodes
        },
    }
    cohort_rows = [
        {
            key: row[key]
            for key in (
                "participant_id",
                "condition",
                "group_id",
                "group_label",
                "path",
            )
        }
        for row in source_rows
    ]
    cohort_payload = {
        "active_workbooks": cohort_rows,
        "ledger_filter_applied": ledger_filter_applied,
        "completed_participants": sorted(completed),
        "manual_excluded_participants": sorted(manual_excluded),
        "frequency_qc": frequency_qc_payload,
    }
    return _SourceSnapshot(
        source_rows=tuple(source_rows),
        source_paths=tuple(str(row["path"]) for row in source_rows),
        cohort_state=cohort_payload,
        frequency_qc_state=frequency_qc_payload,
        processing_export_rows=processing_rows,
        cohort_fingerprint=_hash_payload(cohort_payload),
        source_fingerprint=_hash_payload(source_rows),
        frequency_qc_fingerprint=_hash_payload(frequency_qc_payload),
        processing_export_fingerprint=_hash_payload(processing_rows),
    )


def _read_full_fft_header(path: Path) -> list[object]:
    from Main_App.io import read_xlsx_sheet_header

    return read_xlsx_sheet_header(path, sheet_name=FULL_FFT_SHEET_NAME)


def _grid_identity(
    header: Sequence[object],
    *,
    oddball_frequency_hz: float,
) -> _GridIdentity:
    header_names = tuple(str(value or "").strip() for value in header)
    if header_names.count("Electrode") != 1:
        raise FullFftProvenanceError(
            "FullFFT requires exactly one 'Electrode' column."
        )
    columns: list[str] = []
    frequencies: list[float] = []
    for column in header_names:
        match = _FREQUENCY_COLUMN.fullmatch(column)
        if match is None:
            continue
        frequency = float(match.group(1))
        if not math.isfinite(frequency):
            raise FullFftProvenanceError(
                f"FullFFT frequency column {column!r} is not finite."
            )
        columns.append(column)
        frequencies.append(frequency)
    if len(columns) < 2:
        raise FullFftProvenanceError(
            "No usable FullFFT frequency grid was found."
        )
    if len(set(columns)) != len(columns):
        raise FullFftProvenanceError(
            "FullFFT frequency column names must be unique."
        )
    if any(
        right <= left
        for left, right in zip(frequencies, frequencies[1:], strict=False)
    ):
        raise FullFftProvenanceError(
            "FullFFT frequency columns must be strictly increasing."
        )
    if abs(frequencies[0]) > _ZERO_TOLERANCE_HZ:
        raise FullFftProvenanceError(
            "The FullFFT frequency grid must begin at 0 Hz."
        )
    target_positions = [
        index
        for index, frequency in enumerate(frequencies)
        if abs(frequency - oddball_frequency_hz) <= _TARGET_TOLERANCE_HZ
    ]
    if len(target_positions) != 1 or target_positions[0] <= 0:
        raise FullFftProvenanceError(
            "The FullFFT grid must contain exactly one oddball-frequency column."
        )
    oddball_bin = target_positions[0]
    resolution = oddball_frequency_hz / oddball_bin
    if any(
        abs(frequency - index * resolution) > _GRID_TOLERANCE_HZ
        for index, frequency in enumerate(frequencies)
    ):
        raise FullFftProvenanceError(
            "The FullFFT frequency columns are not one uniform zero-based grid."
        )
    return _GridIdentity(
        fingerprint=_fingerprint_columns(columns, frequencies),
        frequency_resolution_hz=float(resolution),
        upper_frequency_hz=float(frequencies[-1]),
        frequency_column_count=len(columns),
    )


def _project_grid_identity(
    project_root: Path,
    snapshot: _SourceSnapshot,
    *,
    oddball_frequency_hz: float,
) -> _GridIdentity:
    common: _GridIdentity | None = None
    for relative in snapshot.source_paths:
        path = (project_root / Path(relative)).resolve(strict=False)
        try:
            header = _read_full_fft_header(path)
            current = _grid_identity(
                header,
                oddball_frequency_hz=oddball_frequency_hz,
            )
        except Exception as exc:
            raise FullFftProvenanceError(
                f"Could not inspect {FULL_FFT_SHEET_NAME!r} in {relative}: {exc}"
            ) from exc
        if common is None:
            common = current
        elif current != common:
            raise FullFftProvenanceError(
                "All active processed workbooks must share one exact FullFFT grid; "
                f"{relative} differs from the first workbook."
            )
    if common is None:  # pragma: no cover - guarded by the source snapshot
        raise FullFftProvenanceError("No FullFFT workbook was available.")
    return common


def _load_dataset_index(
    project_root: Path,
    supplied: ProjectDatasetIndex | None,
) -> ProjectDatasetIndex:
    if supplied is not None:
        if supplied.project_root.resolve(strict=False) != project_root:
            raise FullFftProvenanceError(
                "The supplied dataset index belongs to a different project root."
            )
        return supplied
    try:
        return load_project_dataset_index(project_root)
    except Exception as exc:
        raise FullFftProvenanceError(
            f"Could not build the managed-project dataset index: {exc}"
        ) from exc


def _read_manifest(project_root: Path) -> dict[str, object]:
    manifest_path = project_root / "project.json"
    try:
        value = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FullFftProvenanceError(
            "Could not read the managed project.json manifest."
        ) from exc
    if not isinstance(value, dict):
        raise FullFftProvenanceError("project.json must contain a JSON object.")
    return value


def _metadata_from_manifest(manifest: Mapping[str, object]) -> Mapping[str, object] | None:
    current: object = manifest
    for key in FULL_FFT_PROVENANCE_MANIFEST_PATH:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current if isinstance(current, Mapping) else None


def _set_metadata_in_manifest(
    manifest: dict[str, object],
    metadata: Mapping[str, object],
) -> None:
    current = manifest
    for key in FULL_FFT_PROVENANCE_MANIFEST_PATH[:-1]:
        child = current.get(key)
        if not isinstance(child, dict):
            child = {}
            current[key] = child
        current = child
    current[FULL_FFT_PROVENANCE_MANIFEST_PATH[-1]] = dict(metadata)


def _write_manifest_atomic(project_root: Path, manifest: Mapping[str, object]) -> None:
    manifest_path = project_root / "project.json"
    payload = json.dumps(dict(manifest), indent=2, ensure_ascii=False)
    try:
        current = manifest_path.read_text(encoding="utf-8")
    except OSError:
        current = ""
    if current == payload:
        return
    temporary = manifest_path.with_name(
        f".{manifest_path.name}.full-fft-provenance.tmp"
    )
    try:
        temporary.write_text(payload, encoding="utf-8")
        temporary.replace(manifest_path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _record_from_metadata(
    project_root: Path,
    metadata: Mapping[str, object],
) -> FullFftProvenance:
    try:
        schema_version = int(metadata.get("schema_version"))
        method_version = str(metadata.get("method_version") or "")
        status = str(metadata.get("status") or "")
        saved_at = str(metadata.get("saved_at") or "")
        base_hz = float(metadata.get("base_frequency_hz"))
        oddball_hz = float(metadata.get("oddball_frequency_hz"))
        grid = metadata["grid"]
        sources = metadata["source_workbooks"]
        fingerprints = metadata["fingerprints"]
        if not isinstance(grid, Mapping):
            raise TypeError("grid")
        if not isinstance(sources, Sequence) or isinstance(sources, (str, bytes)):
            raise TypeError("source_workbooks")
        if not isinstance(fingerprints, Mapping):
            raise TypeError("fingerprints")
        source_paths = tuple(
            str(row["path"])
            for row in sources
            if isinstance(row, Mapping) and str(row.get("path") or "")
        )
        record = FullFftProvenance(
            project_root=project_root,
            saved_at=saved_at,
            method_version=method_version,
            base_frequency_hz=base_hz,
            oddball_frequency_hz=oddball_hz,
            grid_fingerprint=str(grid["fingerprint"]),
            frequency_resolution_hz=float(grid["frequency_resolution_hz"]),
            upper_frequency_hz=float(grid["upper_frequency_hz"]),
            frequency_column_count=int(grid["frequency_column_count"]),
            source_workbook_count=len(sources),
            source_paths=source_paths,
            cohort_fingerprint=str(fingerprints["cohort"]),
            source_fingerprint=str(fingerprints["sources"]),
            frequency_qc_fingerprint=str(fingerprints["frequency_qc"]),
            processing_export_fingerprint=str(
                fingerprints["processing_export"]
            ),
        )
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise FullFftProvenanceStaleError(
            "The saved neutral FullFFT provenance is invalid. Rerun "
            "post-processing; EEG preprocessing is not required."
        ) from exc
    if schema_version != FULL_FFT_PROVENANCE_SCHEMA_VERSION:
        raise FullFftProvenanceStaleError(
            "The saved neutral FullFFT provenance schema is unsupported. Rerun "
            "post-processing in the current Toolbox version."
        )
    if method_version != FULL_FFT_PROVENANCE_METHOD_VERSION:
        raise FullFftProvenanceStaleError(
            "The saved neutral FullFFT provenance method is unsupported. Rerun "
            "post-processing in the current Toolbox version."
        )
    if status != "current":
        reason = str(metadata.get("stale_reason") or "FullFFT inputs changed")
        raise FullFftProvenanceStaleError(
            f"Neutral FullFFT provenance is stale ({reason}). Rerun "
            "post-processing; EEG preprocessing is not required."
        )
    if (
        not saved_at
        or not record.grid_fingerprint
        or not record.source_paths
        or record.source_workbook_count != len(record.source_paths)
        or not math.isfinite(record.frequency_resolution_hz)
        or record.frequency_resolution_hz <= 0.0
        or not math.isfinite(record.upper_frequency_hz)
        or record.upper_frequency_hz <= 0.0
        or record.frequency_column_count < 2
        or not record.cohort_fingerprint
        or not record.source_fingerprint
        or not record.frequency_qc_fingerprint
        or not record.processing_export_fingerprint
        or not math.isfinite(record.base_frequency_hz)
        or record.base_frequency_hz <= 0.0
        or not math.isfinite(record.oddball_frequency_hz)
        or record.oddball_frequency_hz <= 0.0
    ):
        raise FullFftProvenanceStaleError(
            "The saved neutral FullFFT provenance is incomplete. Rerun "
            "post-processing; EEG preprocessing is not required."
        )
    return record


def write_project_full_fft_provenance(
    project_root: str | Path,
    *,
    base_frequency_hz: float,
    oddball_frequency_hz: float,
    dataset_index: ProjectDatasetIndex | None = None,
) -> FullFftProvenance:
    """Build and atomically save current neutral FullFFT provenance.

    Call this only after processing-end cohort/QC decisions and workbook export
    have succeeded.  It reads headers but never reads amplitude cells.
    """

    root = Path(project_root).expanduser().resolve(strict=False)
    if not root.is_dir() or not (root / "project.json").is_file():
        raise FullFftProvenanceError(
            "project_root must be an existing managed project containing project.json."
        )
    base_hz = _positive_frequency(base_frequency_hz, label="base_frequency_hz")
    oddball_hz = _positive_frequency(
        oddball_frequency_hz,
        label="oddball_frequency_hz",
    )
    index = _load_dataset_index(root, dataset_index)
    snapshot = _source_snapshot(root, index)
    grid = _project_grid_identity(
        root,
        snapshot,
        oddball_frequency_hz=oddball_hz,
    )
    # Detect ordinary source edits that occurred during the header scan.
    after_headers = _source_snapshot(root, index)
    if after_headers.source_fingerprint != snapshot.source_fingerprint:
        raise FullFftProvenanceStaleError(
            "A FullFFT workbook changed while provenance was being built. "
            "Rerun post-processing after workbook writes have finished."
        )
    metadata: dict[str, object] = {
        "schema_version": FULL_FFT_PROVENANCE_SCHEMA_VERSION,
        "method_version": FULL_FFT_PROVENANCE_METHOD_VERSION,
        "status": "current",
        "saved_at": datetime.now(UTC).isoformat(),
        "source_sheet": FULL_FFT_SHEET_NAME,
        "base_frequency_hz": base_hz,
        "oddball_frequency_hz": oddball_hz,
        "grid": {
            "fingerprint": grid.fingerprint,
            "frequency_resolution_hz": grid.frequency_resolution_hz,
            "upper_frequency_hz": grid.upper_frequency_hz,
            "frequency_column_count": grid.frequency_column_count,
        },
        "source_workbooks": [dict(row) for row in snapshot.source_rows],
        "cohort_state": dict(snapshot.cohort_state),
        "frequency_qc_state": dict(snapshot.frequency_qc_state),
        "processing_export_state": [
            dict(row) for row in snapshot.processing_export_rows
        ],
        "fingerprints": {
            "cohort": snapshot.cohort_fingerprint,
            "sources": snapshot.source_fingerprint,
            "frequency_qc": snapshot.frequency_qc_fingerprint,
            "processing_export": snapshot.processing_export_fingerprint,
        },
    }
    manifest = _read_manifest(root)
    _set_metadata_in_manifest(manifest, metadata)
    _write_manifest_atomic(root, manifest)
    return _record_from_metadata(root, metadata)


def validate_project_full_fft_provenance(
    project_root: str | Path,
    *,
    base_frequency_hz: float,
    oddball_frequency_hz: float,
    dataset_index: ProjectDatasetIndex | None = None,
) -> FullFftProvenance:
    """Validate rates, cohort/QC identity, and FullFFT file freshness."""

    root = Path(project_root).expanduser().resolve(strict=False)
    if not root.is_dir() or not (root / "project.json").is_file():
        raise FullFftProvenanceError(
            "project_root must be an existing managed project containing project.json."
        )
    supplied_base_hz = _positive_frequency(
        base_frequency_hz,
        label="base_frequency_hz",
    )
    supplied_oddball_hz = _positive_frequency(
        oddball_frequency_hz,
        label="oddball_frequency_hz",
    )
    manifest = _read_manifest(root)
    metadata = _metadata_from_manifest(manifest)
    if metadata is None:
        raise FullFftProvenanceMissingError(
            "Neutral FullFFT provenance is missing. This project predates the "
            "record or its last post-processing run did not finish. Rerun "
            "post-processing; EEG preprocessing is not required."
        )
    record = _record_from_metadata(root, metadata)
    if not (
        _same_rate(record.base_frequency_hz, supplied_base_hz)
        and _same_rate(record.oddball_frequency_hz, supplied_oddball_hz)
    ):
        raise FullFftProvenanceStaleError(
            "Current Project Settings rates do not match neutral FullFFT "
            "provenance: current "
            f"base={supplied_base_hz:g} Hz / oddball={supplied_oddball_hz:g} Hz; "
            f"processed base={record.base_frequency_hz:g} Hz / "
            f"oddball={record.oddball_frequency_hz:g} Hz. Restore the processed "
            "rates or rerun post-processing; EEG preprocessing is not required."
        )
    index = _load_dataset_index(root, dataset_index)
    try:
        current = _source_snapshot(root, index)
    except FullFftProvenanceError:
        raise
    except (OSError, ValueError) as exc:
        raise FullFftProvenanceStaleError(
            "Current FullFFT/cohort provenance could not be inspected. Rerun "
            "post-processing; EEG preprocessing is not required."
        ) from exc
    differences: list[str] = []
    if current.cohort_fingerprint != record.cohort_fingerprint:
        differences.append("cohort or canonical workbook identity changed")
    if current.source_fingerprint != record.source_fingerprint:
        differences.append("FullFFT workbook path, size, or modification time changed")
    if current.frequency_qc_fingerprint != record.frequency_qc_fingerprint:
        differences.append("frequency-domain cohort/QC exclusions changed")
    if current.processing_export_fingerprint != record.processing_export_fingerprint:
        differences.append("processing/export ledger identity changed")
    if current.source_paths != record.source_paths:
        differences.append("active FullFFT workbook set changed")
    if differences:
        raise FullFftProvenanceStaleError(
            "Neutral FullFFT provenance is stale because "
            + "; ".join(dict.fromkeys(differences))
            + ". Rerun post-processing; EEG preprocessing is not required."
        )
    return record


def mark_project_full_fft_provenance_stale(
    project_root: str | Path,
    *,
    reason: str,
) -> None:
    """Explicitly stale an existing record without creating a missing one."""

    root = Path(project_root).expanduser().resolve(strict=False)
    manifest = _read_manifest(root)
    metadata = _metadata_from_manifest(manifest)
    if metadata is None:
        return
    updated = dict(metadata)
    updated["status"] = "stale"
    updated["stale_reason"] = str(reason).strip() or "FullFFT inputs changed"
    updated["stale_at"] = datetime.now(UTC).isoformat()
    _set_metadata_in_manifest(manifest, updated)
    _write_manifest_atomic(root, manifest)


__all__ = [
    "FULL_FFT_PROVENANCE_MANIFEST_PATH",
    "FULL_FFT_PROVENANCE_METHOD_VERSION",
    "FULL_FFT_PROVENANCE_SCHEMA_VERSION",
    "FULL_FFT_SHEET_NAME",
    "FullFftProvenance",
    "FullFftProvenanceError",
    "FullFftProvenanceMissingError",
    "FullFftProvenanceStaleError",
    "mark_project_full_fft_provenance_stale",
    "validate_project_full_fft_provenance",
    "write_project_full_fft_provenance",
]
