"""Neutral project-local provenance for processed FullFFT workbooks.

This module owns the source identity used by sibling analyses that consume the
original ``FullFFT Amplitude (uV)`` data, including declared NumPy companions.
It deliberately records no Stats
harmonic-selection state and does not depend on a Summed-BCA cache.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
import hashlib
import json
import math
from pathlib import Path
import re

from Main_App.io.eeg_geometry import (
    BIOSEMI64_CHANNELS,
    BIOSEMI64_MONTAGE_ID,
    biosemi64_geometry_identity,
)

from Main_App.processing.frequency_domain_qc import (
    load_frequency_domain_qc_state,
    resolve_frequency_qc_coverage_decisions,
)
from Main_App.processing.processing_ledger import load_ledger
from Main_App.projects import (
    FrequencyProtocolError,
    ProjectDatasetIndex,
    load_project_dataset_index,
    normalize_manual_excluded_recordings,
    normalize_preprocessing_settings,
    normalize_frequency_protocol,
)


FULL_FFT_PROVENANCE_SCHEMA_VERSION = 3
FULL_FFT_PROVENANCE_METHOD_VERSION = (
    "project_full_fft_provenance_v3_biosemi64_frequency_protocol"
)
REPEATED_FULL_FFT_PROVENANCE_METHOD_VERSION = (
    "project_full_fft_provenance_recording_session_v3_biosemi64_frequency_protocol"
)
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
    frequency_protocol_fingerprint: str
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
    geometry_identity: Mapping[str, object] = field(default_factory=dict)
    geometry_fingerprint: str = ""


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
    geometry_identity: dict[str, object]
    geometry_fingerprint: str


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


def _current_project_frequency_protocol(project_root: Path):
    manifest = _read_manifest(project_root)
    raw_protocol = manifest.get("frequency_protocol")
    if raw_protocol is None:
        raise FullFftProvenanceError(
            "The managed project has no frequency protocol. Confirm the project "
            "presentation rate, oddball recurrence, and analyzed cycle count "
            "before post-processing."
        )
    try:
        protocol = normalize_frequency_protocol(raw_protocol)
    except FrequencyProtocolError as exc:
        raise FullFftProvenanceError(
            f"The managed project frequency protocol is invalid: {exc}"
        ) from exc
    if (
        not protocol.is_ready
        or protocol.presentation_rate_hz is None
        or protocol.oddball_rate_hz is None
    ):
        raise FullFftProvenanceError(
            "The managed project frequency protocol is incomplete. Confirm the "
            "project presentation rate, oddball recurrence, and analyzed cycle "
            "count before post-processing."
        )
    return protocol


def _hash_payload(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _condition_identity_rows(
    values: Iterable[tuple[str, str]],
    *,
    identity_field: str,
) -> list[dict[str, str]]:
    """Return deterministic reviewed condition identities for provenance."""

    normalized = {
        (str(identity).strip().casefold(), str(condition).strip().casefold())
        for identity, condition in values
        if str(identity).strip() and str(condition).strip()
    }
    return [
        {identity_field: identity, "condition": condition}
        for identity, condition in sorted(normalized)
    ]


def _condition_electrode_rows(
    values: Mapping[tuple[str, str], frozenset[str]],
    *,
    identity_field: str,
) -> list[dict[str, object]]:
    """Return deterministic reviewed electrode exclusions without scope widening."""

    normalized: dict[tuple[str, str], set[str]] = {}
    for (identity, condition), electrodes in values.items():
        key = (
            str(identity).strip().casefold(),
            str(condition).strip().casefold(),
        )
        if not all(key):
            continue
        normalized.setdefault(key, set()).update(
            str(electrode).strip().upper()
            for electrode in electrodes
            if str(electrode).strip()
        )
    return [
        {
            identity_field: identity,
            "condition": condition,
            "electrodes": sorted(electrodes),
        }
        for (identity, condition), electrodes in sorted(normalized.items())
        if electrodes
    ]


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


def _manual_excluded_recordings(index: ProjectDatasetIndex) -> set[str]:
    if not index.is_repeated_session:
        return set()
    manifest = index.manifest if isinstance(index.manifest, Mapping) else {}
    raw = manifest.get("preprocessing")
    preprocessing = raw if isinstance(raw, Mapping) else {}
    return {
        str(value).strip().casefold()
        for value in normalize_manual_excluded_recordings(
            preprocessing.get("manual_excluded_recordings")
        )
        if str(value).strip()
    }


def _completed_ledger_state(
    project_root: Path,
    *,
    repeated_session: bool = False,
) -> tuple[set[str], tuple[dict[str, object], ...], bool]:
    ledger = load_ledger(project_root)
    entries = ledger.get("entries") if isinstance(ledger, Mapping) else None
    if not isinstance(entries, Mapping):
        return set(), (), False
    completed_rows: list[dict[str, object]] = []
    completed_keys: set[str] = set()
    for processing_id, entry in entries.items():
        if not isinstance(entry, Mapping):
            continue
        if str(entry.get("status") or "").strip().casefold() != "completed":
            continue
        participant = str(entry.get("participant_id") or processing_id).strip()
        recording_id = str(entry.get("recording_id") or processing_id).strip()
        identity = recording_id if repeated_session else participant
        if not identity:
            continue
        completed_keys.add(identity.casefold())
        row: dict[str, object] = {
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
                "geometry": (
                    dict(entry["geometry"])
                    if isinstance(entry.get("geometry"), Mapping)
                    else None
                ),
            }
        if repeated_session:
            row.update(
                {
                    "recording_id": recording_id,
                    "session_id": str(entry.get("session_id") or ""),
                    "source_id": str(entry.get("source_id") or ""),
                    "visit_index": entry.get("visit_index"),
                    "days_from_baseline": entry.get("days_from_baseline"),
                }
            )
        completed_rows.append(row)
    completed_rows.sort(
        key=lambda row: (
            str(row.get("recording_id") or "").casefold(),
            str(row["participant_id"]).casefold(),
            str(row["participant_id"]),
        )
    )
    return completed_keys, tuple(completed_rows), bool(completed_keys)


def _validated_geometry_identity(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise FullFftProvenanceError(
            "Active processed workbooks have no BioSemi64 geometry identity. "
            "Reprocess the EEG before post-processing or analysis."
        )
    retained = value.get("retained_scalp_channels")
    if not isinstance(retained, Sequence) or isinstance(retained, (str, bytes)):
        raise FullFftProvenanceError(
            "Active processed workbooks have incomplete BioSemi64 geometry "
            "provenance. Reprocess the EEG before analysis."
        )
    try:
        expected = biosemi64_geometry_identity(
            electrode_mapping_profile=value.get("electrode_mapping_profile"),
            retained_channels=[str(channel) for channel in retained],
        )
    except (TypeError, ValueError) as exc:
        raise FullFftProvenanceError(
            f"Active processed workbooks have invalid BioSemi64 geometry: {exc}"
        ) from exc
    if dict(value) != expected:
        raise FullFftProvenanceError(
            "Active processed workbooks use an unknown or legacy electrode "
            "geometry. Reprocess the EEG before analysis."
        )
    return expected


def _active_geometry_identity(
    index: ProjectDatasetIndex,
    active_records: Sequence[object],
    processing_rows: Sequence[Mapping[str, object]],
    *,
    ledger_filter_applied: bool,
) -> dict[str, object]:
    """Require one current geometry across every active workbook owner."""

    if not ledger_filter_applied:
        raise FullFftProvenanceError(
            "Active FullFFT workbooks have no current processing ledger geometry. "
            "Legacy or unknown geometry cannot be analyzed; reprocess the EEG."
        )

    manifest = index.manifest if isinstance(index.manifest, Mapping) else {}
    raw_preprocessing = manifest.get("preprocessing")
    try:
        preprocessing = normalize_preprocessing_settings(
            raw_preprocessing if isinstance(raw_preprocessing, Mapping) else {}
        )
        montage_id = str(preprocessing.get("electrode_montage") or "")
        mapping_profile = preprocessing.get("electrode_mapping_profile")
        expected_limit = int(preprocessing.get("max_chan_idx_keep") or 64)
        expected_count = expected_limit if 0 < expected_limit < 64 else 64
        project_geometry = biosemi64_geometry_identity(
            electrode_mapping_profile=mapping_profile,
            retained_channels=BIOSEMI64_CHANNELS[:expected_count],
        )
    except (TypeError, ValueError) as exc:
        raise FullFftProvenanceError(
            f"Project electrode geometry settings are invalid: {exc}"
        ) from exc
    if montage_id != BIOSEMI64_MONTAGE_ID:
        raise FullFftProvenanceError(
            f"Unsupported project electrode montage {montage_id!r}; only "
            f"{BIOSEMI64_MONTAGE_ID!r} is valid for current processing."
        )

    identity_key = "recording_id" if index.is_repeated_session else "participant_id"
    active_ids = {
        str(getattr(record, identity_key, "") or "").strip().casefold()
        for record in active_records
    }
    active_ids.discard("")
    rows_by_id = {
        str(row.get(identity_key) or "").strip().casefold(): row
        for row in processing_rows
        if str(row.get(identity_key) or "").strip()
    }
    missing = sorted(active_ids.difference(rows_by_id))
    if missing:
        raise FullFftProvenanceError(
            "Active FullFFT workbook owner(s) have no completed processing "
            "geometry record: " + ", ".join(missing)
        )

    validated: list[tuple[str, dict[str, object]]] = []
    for processing_id in sorted(active_ids):
        geometry = _validated_geometry_identity(
            rows_by_id[processing_id].get("geometry")
        )
        validated.append((processing_id, geometry))

    geometry_fingerprints = {
        str(value["geometry_identity_fingerprint"])
        for _processing_id, value in validated
    }
    if len(geometry_fingerprints) != 1:
        raise FullFftProvenanceError(
            "Active FullFFT workbooks contain mixed electrode geometries or retained "
            "scalp sets. Reprocess them under one project geometry before analysis."
        )
    if not validated:
        raise FullFftProvenanceError(
            "No active processing geometry could be matched to FullFFT workbooks."
        )
    for processing_id, geometry in validated:
        if geometry["electrode_mapping_profile"] != project_geometry["electrode_mapping_profile"]:
            raise FullFftProvenanceError(
                f"The processed workbooks for {processing_id} used channel mapping "
                f"{geometry['electrode_mapping_profile']!r}, but Settings > Preprocessing > "
                "Channel mapping profile currently requests "
                f"{project_geometry['electrode_mapping_profile']!r}. Restore the original "
                "mapping setting to reuse these outputs, or reprocess the EEG if the "
                "mapping change was intentional."
            )
        if geometry != project_geometry:
            raise FullFftProvenanceError(
                "Active FullFFT workbook geometry or exact retained scalp set does "
                "not match current project settings for "
                f"{processing_id}. Reprocess the EEG."
            )
    return validated[0][1]


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

    repeated_session = index.is_repeated_session
    completed, processing_rows, ledger_filter_applied = _completed_ledger_state(
        project_root,
        repeated_session=repeated_session,
    )
    manual_excluded = _manual_excluded_participants(index)
    manual_excluded_recordings = _manual_excluded_recordings(index)
    frequency_qc_state = load_frequency_domain_qc_state(project_root)
    frequency_qc = resolve_frequency_qc_coverage_decisions(project_root)
    if bool(frequency_qc_state.get("downstream_outputs_stale", False)):
        stale_reason = str(frequency_qc_state.get("stale_reason") or "").strip()
        if stale_reason:
            raise FullFftProvenanceStaleError(
                "Frequency-domain outputs are not current: "
                f"{stale_reason} Resolve this issue and resume post-processing."
            )
        raise FullFftProvenanceStaleError(
            "Frequency-domain cohort/QC state is stale. Complete the required "
            "post-processing review before using FullFFT analyses."
        )
    if not frequency_qc.review_complete:
        if bool(frequency_qc_state.get("review_complete", False)):
            detail = "no longer has valid decision provenance"
        else:
            detail = "has not been completed with valid review evidence"
        raise FullFftProvenanceStaleError(
            f"The frequency-domain QC review {detail}. Repeat the review "
            "before using FullFFT analyses."
        )
    frequency_excluded = {
        str(value).strip().casefold()
        for value in frequency_qc.excluded_participants
        if str(value).strip()
    }
    frequency_excluded_recordings = {
        str(value).strip().casefold()
        for value in frequency_qc.excluded_recordings
        if str(value).strip()
    }
    frequency_participant_conditions = _condition_identity_rows(
        frequency_qc.excluded_participant_conditions,
        identity_field="participant_id",
    )
    frequency_participant_condition_keys = {
        (row["participant_id"], row["condition"])
        for row in frequency_participant_conditions
    }
    frequency_recording_conditions = _condition_identity_rows(
        frequency_qc.excluded_recording_conditions,
        identity_field="recording_id",
    )
    frequency_recording_condition_keys = {
        (row["recording_id"], row["condition"])
        for row in frequency_recording_conditions
    }
    participant_condition_electrodes = _condition_electrode_rows(
        frequency_qc.excluded_electrodes_by_participant_condition,
        identity_field="participant_id",
    )
    recording_condition_electrodes = _condition_electrode_rows(
        frequency_qc.excluded_electrodes_by_recording_condition,
        identity_field="recording_id",
    )
    active_records = tuple(
        record
        for record in index.workbooks
        if (
            not ledger_filter_applied
            or (
                (
                    str(record.recording_id or "").casefold()
                    if repeated_session
                    else record.participant_id.casefold()
                )
                in completed
            )
        )
        and record.participant_id.casefold() not in manual_excluded
        and record.participant_id.casefold() not in frequency_excluded
        and (record.participant_id.casefold(), record.condition.casefold())
        not in frequency_participant_condition_keys
        and (
            not repeated_session
            or str(record.recording_id or "").casefold()
            not in manual_excluded_recordings
        )
        and (
            not repeated_session
            or str(record.recording_id or "").casefold()
            not in frequency_excluded_recordings
        )
        and (
            not repeated_session
            or (
                str(record.recording_id or "").casefold(),
                record.condition.casefold(),
            )
            not in frequency_recording_condition_keys
        )
    )
    if not active_records:
        raise FullFftProvenanceError(
            "No active indexed FullFFT workbooks remain after project cohort filters."
        )
    geometry_identity = _active_geometry_identity(
        index,
        active_records,
        processing_rows,
        ledger_filter_applied=ledger_filter_applied,
    )

    source_rows: list[dict[str, object]] = []
    from Main_App.io.condition_data import (
        ConditionDataError,
        condition_companion_identity,
    )
    from Main_App.io.spectral_data import (
        SpectralDataError,
        spectral_companion_identity,
    )

    for record in active_records:
        resolved, relative = _manifest_relative_path(project_root, record.path)
        stat = resolved.stat()
        row: dict[str, object] = {
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
        try:
            companion = spectral_companion_identity(resolved)
        except SpectralDataError as exc:
            raise FullFftProvenanceError(
                f"FullFFT spectral companion is invalid for {relative}: {exc}"
            ) from exc
        if companion is not None:
            row["spectral_companion"] = companion
        try:
            condition_companion = condition_companion_identity(resolved)
        except ConditionDataError as exc:
            raise FullFftProvenanceError(
                f"Condition metrics companion is invalid for {relative}: {exc}"
            ) from exc
        if condition_companion is not None:
            row["condition_companion"] = condition_companion
        if repeated_session:
            row.update(
                {
                    "recording_id": str(record.recording_id or ""),
                    "session_id": str(record.session_id or ""),
                    "session_label": str(record.session_label or ""),
                    "visit_index": record.visit_index,
                    "days_from_baseline": record.days_from_baseline,
                    "source_id": str(
                        index.recordings[str(record.recording_id)].source_id
                        if record.recording_id in index.recordings
                        else ""
                    ),
                }
            )
        source_rows.append(row)
    source_rows.sort(
        key=lambda row: (
            str(row["condition"]).casefold(),
            str(row.get("group_id") or "").casefold(),
            str(row["participant_id"]).casefold(),
            str(row.get("session_id") or "").casefold(),
            str(row.get("recording_id") or "").casefold(),
            str(row["path"]).casefold(),
            str(row["path"]),
        )
    )

    # Legacy ``auto_*`` fields remain preserved as inactive suggestions in the
    # frequency-QC state. They are deliberately absent here: only explicit,
    # reviewed exclusions own FullFFT cohort/provenance identity.
    frequency_qc_payload: dict[str, object] = {
        "authority": "reviewed_frequency_domain_qc",
        "review_complete": True,
        "decision_fingerprint": str(frequency_qc.decision_fingerprint),
        "excluded_participants": sorted(frequency_excluded),
        "excluded_participant_conditions": frequency_participant_conditions,
        "excluded_electrodes_by_participant_condition": (
            participant_condition_electrodes
        ),
    }
    if repeated_session:
        frequency_qc_payload.update(
            {
                "excluded_recordings": sorted(frequency_excluded_recordings),
                "excluded_recording_conditions": frequency_recording_conditions,
                "excluded_electrodes_by_recording_condition": (
                    recording_condition_electrodes
                ),
            }
        )
    cohort_keys = [
        "participant_id",
        "condition",
        "group_id",
        "group_label",
        "path",
    ]
    if repeated_session:
        cohort_keys.extend(
            [
                "recording_id",
                "session_id",
                "session_label",
                "visit_index",
                "days_from_baseline",
                "source_id",
            ]
        )
    cohort_rows = [
        {
            key: row[key]
            for key in cohort_keys
        }
        for row in source_rows
    ]
    cohort_payload = {
        "active_workbooks": cohort_rows,
        "ledger_filter_applied": ledger_filter_applied,
        "manual_excluded_participants": sorted(manual_excluded),
        "frequency_qc": frequency_qc_payload,
    }
    if repeated_session:
        cohort_payload.update(
            {
                "identity_scope": "recording",
                "completed_recordings": sorted(completed),
                "manual_excluded_recordings": sorted(
                    manual_excluded_recordings
                ),
            }
        )
    else:
        cohort_payload["completed_participants"] = sorted(completed)
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
        geometry_identity=geometry_identity,
        geometry_fingerprint=str(
            geometry_identity["geometry_identity_fingerprint"]
        ),
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


def require_current_project_workbook_geometry(
    project_root: str | Path,
    *,
    dataset_index: ProjectDatasetIndex | None = None,
) -> dict[str, object]:
    """Require one current BioSemi64 geometry for active processed workbooks.

    This check deliberately does not require a saved neutral FullFFT provenance
    record.  It is the processing-time gate for consumers, such as final
    harmonic selection, that may run before that record has been published.  It
    uses the same canonical dataset-index, cohort, processing-ledger, and
    geometry checks that build and revalidate the neutral FullFFT record.
    """

    root = Path(project_root).expanduser().resolve(strict=False)
    if not root.is_dir() or not (root / "project.json").is_file():
        raise FullFftProvenanceError(
            "project_root must be an existing managed project containing project.json."
        )
    index = _load_dataset_index(root, dataset_index)
    return dict(_source_snapshot(root, index).geometry_identity)


def require_current_project_pre_review_geometry(
    project_root: str | Path,
    *,
    dataset_index: ProjectDatasetIndex | None = None,
) -> dict[str, object]:
    """Check processed candidate geometry before asking for frequency-QC decisions.

    This prerequisite uses the completed processing cohort, preprocessing
    manual exclusions, and any still-valid reviewed frequency exclusions. It
    deliberately does not require frequency review to have finished.
    """
    root = Path(project_root).expanduser().resolve(strict=False)
    if not root.is_dir() or not (root / "project.json").is_file():
        raise FullFftProvenanceError(
            "project_root must be an existing managed project containing project.json."
        )
    index = _load_dataset_index(root, dataset_index)
    repeated_session = index.is_repeated_session
    completed, processing_rows, ledger_filter_applied = _completed_ledger_state(
        root, repeated_session=repeated_session,
    )
    manual_participants = _manual_excluded_participants(index)
    manual_recordings = _manual_excluded_recordings(index)
    reviewed = resolve_frequency_qc_coverage_decisions(root)
    excluded_participants = manual_participants | (
        {str(value).strip().casefold() for value in reviewed.excluded_participants}
        if reviewed.review_complete else set()
    )
    excluded_recordings = manual_recordings | (
        {str(value).strip().casefold() for value in reviewed.excluded_recordings}
        if reviewed.review_complete else set()
    )
    excluded_participant_conditions = {
        (str(identity).strip().casefold(), str(condition).strip().casefold())
        for identity, condition in reviewed.excluded_participant_conditions
    } if reviewed.review_complete else set()
    excluded_recording_conditions = {
        (str(identity).strip().casefold(), str(condition).strip().casefold())
        for identity, condition in reviewed.excluded_recording_conditions
    } if reviewed.review_complete else set()
    active_records = tuple(
        record for record in index.workbooks
        if (
            not ledger_filter_applied
            or str(record.recording_id if repeated_session else record.participant_id).casefold()
            in completed
        )
        and record.participant_id.casefold() not in excluded_participants
        and (not repeated_session or str(record.recording_id or "").casefold() not in excluded_recordings)
        and (record.participant_id.casefold(), record.condition.casefold())
        not in excluded_participant_conditions
        and (not repeated_session or (
            str(record.recording_id or "").casefold(), record.condition.casefold(),
        ) not in excluded_recording_conditions)
    )
    return _active_geometry_identity(
        index, active_records, processing_rows,
        ledger_filter_applied=ledger_filter_applied,
    )


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
    except (TypeError, ValueError, OverflowError) as exc:
        raise FullFftProvenanceStaleError(
            "The saved neutral FullFFT provenance header is invalid. Rerun "
            "EEG preprocessing and post-processing."
        ) from exc
    if schema_version != FULL_FFT_PROVENANCE_SCHEMA_VERSION:
        raise FullFftProvenanceStaleError(
            "The saved neutral FullFFT provenance predates the current "
            "BioSemi64 and project-frequency-protocol contract. Reprocess the "
            "EEG before analysis."
        )
    if method_version not in {
        FULL_FFT_PROVENANCE_METHOD_VERSION,
        REPEATED_FULL_FFT_PROVENANCE_METHOD_VERSION,
    }:
        raise FullFftProvenanceStaleError(
            "The saved neutral FullFFT provenance uses an unsupported geometry "
            "method. Reprocess the EEG before analysis."
        )
    if status != "current":
        reason = str(metadata.get("stale_reason") or "FullFFT inputs changed")
        raise FullFftProvenanceStaleError(
            f"Neutral FullFFT provenance is stale ({reason}). Rerun "
            "post-processing; EEG preprocessing is not required unless the "
            "reason identifies electrode geometry."
        )

    try:
        saved_at = str(metadata.get("saved_at") or "")
        base_hz = float(metadata.get("base_frequency_hz"))
        oddball_hz = float(metadata.get("oddball_frequency_hz"))
        frequency_protocol_fingerprint = str(
            metadata.get("frequency_protocol_fingerprint") or ""
        )
        grid = metadata["grid"]
        sources = metadata["source_workbooks"]
        fingerprints = metadata["fingerprints"]
        geometry = _validated_geometry_identity(metadata.get("geometry"))
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
            frequency_protocol_fingerprint=frequency_protocol_fingerprint,
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
            geometry_identity=geometry,
            geometry_fingerprint=str(fingerprints["geometry"]),
        )
    except FullFftProvenanceError as exc:
        raise FullFftProvenanceStaleError(str(exc)) from exc
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise FullFftProvenanceStaleError(
            "The saved neutral FullFFT provenance is incomplete or invalid. "
            "Reprocess the EEG before analysis."
        ) from exc
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
        or not record.geometry_fingerprint
        or record.geometry_fingerprint
        != record.geometry_identity.get("geometry_identity_fingerprint")
        or not math.isfinite(record.base_frequency_hz)
        or record.base_frequency_hz <= 0.0
        or not math.isfinite(record.oddball_frequency_hz)
        or record.oddball_frequency_hz <= 0.0
        or not record.frequency_protocol_fingerprint
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
    frequency_protocol_fingerprint: str | None = None,
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
    protocol = _current_project_frequency_protocol(root)
    protocol_base_hz = float(protocol.presentation_rate_hz)
    protocol_oddball_hz = float(protocol.oddball_rate_hz)
    if not (
        _same_rate(base_hz, protocol_base_hz)
        and _same_rate(oddball_hz, protocol_oddball_hz)
    ):
        raise FullFftProvenanceError(
            "FullFFT provenance rates must match the current project frequency "
            f"protocol exactly (project base={protocol_base_hz:g} Hz, project "
            f"oddball={protocol_oddball_hz:g} Hz)."
        )
    supplied_protocol_fingerprint = str(
        frequency_protocol_fingerprint or protocol.fingerprint
    ).strip()
    if supplied_protocol_fingerprint != protocol.fingerprint:
        raise FullFftProvenanceError(
            "The supplied frequency-protocol fingerprint is stale relative to "
            "the managed project. Reload the project before post-processing."
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
        "method_version": (
            REPEATED_FULL_FFT_PROVENANCE_METHOD_VERSION
            if index.is_repeated_session
            else FULL_FFT_PROVENANCE_METHOD_VERSION
        ),
        "status": "current",
        "saved_at": datetime.now(UTC).isoformat(),
        "source_sheet": FULL_FFT_SHEET_NAME,
        "base_frequency_hz": base_hz,
        "oddball_frequency_hz": oddball_hz,
        "frequency_protocol_fingerprint": protocol.fingerprint,
        "grid": {
            "fingerprint": grid.fingerprint,
            "frequency_resolution_hz": grid.frequency_resolution_hz,
            "upper_frequency_hz": grid.upper_frequency_hz,
            "frequency_column_count": grid.frequency_column_count,
        },
        "geometry": dict(snapshot.geometry_identity),
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
            "geometry": snapshot.geometry_fingerprint,
        },
    }
    manifest = _read_manifest(root)
    _set_metadata_in_manifest(manifest, metadata)
    _write_manifest_atomic(root, manifest)
    return _record_from_metadata(root, metadata)


def _saved_full_fft_provenance(root: Path) -> FullFftProvenance:
    manifest = _read_manifest(root)
    metadata = _metadata_from_manifest(manifest)
    if metadata is None:
        raise FullFftProvenanceMissingError(
            "Neutral FullFFT provenance is missing. This project predates the "
            "record or its last post-processing run did not finish. Rerun "
            "post-processing; EEG preprocessing is not required."
        )
    return _record_from_metadata(root, metadata)


def _require_current_full_fft_record(
    root: Path,
    record: FullFftProvenance,
    *,
    dataset_index: ProjectDatasetIndex | None,
) -> FullFftProvenance:
    try:
        protocol = _current_project_frequency_protocol(root)
    except FullFftProvenanceError as exc:
        raise FullFftProvenanceStaleError(
            "Neutral FullFFT provenance cannot be validated because the current "
            f"project frequency protocol is unavailable: {exc}"
        ) from exc
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
    if protocol.fingerprint != record.frequency_protocol_fingerprint:
        differences.append("project frequency protocol changed")
    if not (
        _same_rate(record.base_frequency_hz, float(protocol.presentation_rate_hz))
        and _same_rate(
            record.oddball_frequency_hz,
            float(protocol.oddball_rate_hz),
        )
    ):
        differences.append("saved rates do not match the project frequency protocol")
    if current.cohort_fingerprint != record.cohort_fingerprint:
        differences.append("cohort or canonical workbook identity changed")
    if current.source_fingerprint != record.source_fingerprint:
        differences.append(
            "FullFFT workbook path, size, modification time, or condition data companion changed"
        )
    if current.frequency_qc_fingerprint != record.frequency_qc_fingerprint:
        differences.append("frequency-domain cohort/QC exclusions changed")
    if current.processing_export_fingerprint != record.processing_export_fingerprint:
        differences.append("processing/export ledger identity changed")
    if current.geometry_fingerprint != record.geometry_fingerprint:
        differences.append("electrode geometry identity changed")
    if current.source_paths != record.source_paths:
        differences.append("active FullFFT workbook set changed")
    if differences:
        raise FullFftProvenanceStaleError(
            "Neutral FullFFT provenance is stale because "
            + "; ".join(dict.fromkeys(differences))
            + ". Rerun post-processing; EEG preprocessing is not required."
        )
    return record


def require_current_project_full_fft_provenance(
    project_root: str | Path,
    *,
    dataset_index: ProjectDatasetIndex | None = None,
) -> FullFftProvenance:
    """Return the current saved FullFFT identity for a managed project.

    Unlike :func:`validate_project_full_fft_provenance`, this entry point does
    not compare against caller-supplied rates.  It treats the immutable rates
    saved with the processing record as authoritative while validating the
    current cohort, workbook, frequency-QC, and processing/export identities.
    """

    root = Path(project_root).expanduser().resolve(strict=False)
    if not root.is_dir() or not (root / "project.json").is_file():
        raise FullFftProvenanceError(
            "project_root must be an existing managed project containing project.json."
        )
    record = _saved_full_fft_provenance(root)
    return _require_current_full_fft_record(
        root,
        record,
        dataset_index=dataset_index,
    )


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
    record = _saved_full_fft_provenance(root)
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
    return _require_current_full_fft_record(
        root,
        record,
        dataset_index=dataset_index,
    )


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
    "REPEATED_FULL_FFT_PROVENANCE_METHOD_VERSION",
    "FULL_FFT_SHEET_NAME",
    "FullFftProvenance",
    "FullFftProvenanceError",
    "FullFftProvenanceMissingError",
    "FullFftProvenanceStaleError",
    "mark_project_full_fft_provenance_stale",
    "require_current_project_workbook_geometry",
    "require_current_project_pre_review_geometry",
    "require_current_project_full_fft_provenance",
    "validate_project_full_fft_provenance",
    "write_project_full_fft_provenance",
]
