"""GUI-neutral management of explicit whole-dataset exclusion scopes."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from Main_App.projects import (
    infer_raw_participant_id,
    load_project_dataset_index,
    normalize_preprocessing_settings,
)

from .artifact_freshness import (
    HARMONIC_SELECTION_SUMMARY_ARTIFACT,
    SELECTION_DEPENDENT_ARTIFACTS,
)
from .frequency_domain_qc import (
    DECISION_EXCLUDE_PARTICIPANT,
    DECISION_EXCLUDE_RECORDING,
    frequency_domain_exclusions_from_state,
)


@dataclass(frozen=True, slots=True)
class DatasetExclusionRow:
    identity: str
    participant_id: str
    recording_id: str
    group_label: str
    has_processed_data: bool
    scope: str
    reason: str
    details: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DatasetExclusionsSnapshot:
    rows: tuple[DatasetExclusionRow, ...]
    revision: str
    project_root: Path
    processing_excluded_participants: tuple[str, ...] = ()
    processing_excluded_recordings: tuple[str, ...] = ()
    downstream_outputs_stale: bool = False


class DatasetExclusionsConflictError(ValueError):
    """The project or processed dataset changed after the manager was loaded."""


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain an object.")
    return value


def _entries(state: Mapping[str, Any], key: str) -> list[dict[str, Any]]:
    value = state.get(key, [])
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise ValueError(f"Saved {key} must contain a list of objects.")
    return value


def _identity(participant_id: str, recording_id: str = "") -> str:
    return f"recording:{recording_id.casefold()}" if recording_id else f"participant:{participant_id.casefold()}"


def _scope(processing: bool, analysis: bool) -> str:
    if processing and analysis:
        return "both"
    if processing:
        return "skip_processing"
    return "exclude_analysis" if analysis else "include"


def _read_manifest(root: Path) -> tuple[bytes, dict[str, Any]]:
    content = (root / "project.json").read_bytes()
    return content, _mapping(json.loads(content.decode("utf-8")), "Project manifest")


def _load_context(root: Path):
    content, manifest = _read_manifest(root)
    index = load_project_dataset_index(root)
    if index.project_root != root or index.manifest is None:
        raise ValueError("Dataset exclusions require the active project's project.json.")
    snapshot = _snapshot_from_manifest(root, content, manifest, index)
    if _read_manifest(root)[0] != content:
        raise DatasetExclusionsConflictError("The project changed while exclusions were loading. Reload the manager.")
    return snapshot, content, manifest, index


def _snapshot_from_manifest(root: Path, content: bytes, manifest: dict, index):
    preprocessing = _mapping(manifest.get("preprocessing", {}), "Preprocessing settings")
    normalized = normalize_preprocessing_settings(preprocessing, allow_legacy_inversion=True)
    tools = _mapping(manifest.get("tools", {}), "Project tool settings")
    state = _mapping(tools.get("frequency_domain_qc", {}), "Frequency-domain QC settings")
    manager = _mapping(tools.get("dataset_exclusions", {}), "Dataset exclusion settings")
    reasons = _mapping(manager.get("reasons", {}), "Dataset exclusion reasons")
    exclusions = frequency_domain_exclusions_from_state(state)
    processing_participants = {pid.casefold() for pid in normalized["manual_excluded_participants"]}
    processing_recordings = {rid.casefold() for rid in normalized["manual_excluded_recordings"]}
    analysis_participants = {pid.casefold() for pid in exclusions.excluded_participants}
    analysis_recordings = {rid.casefold() for rid in exclusions.excluded_recordings}
    participant_ids = {pid.casefold(): pid for pid in index.participants}
    recording_ids = {rid.casefold(): rid for rid in index.recordings}
    recording_participants = {rid.casefold(): record.participant_id for rid, record in index.recordings.items()}
    processed_participants: set[str] = set()
    processed_recordings: set[str] = set()
    files = []
    raw_groups = {}
    # Before first processing, flat projects may not have participant metadata.
    # Use the processing-owned identity parser and canonical registered group
    # folders; never derive group identity from generated output folders.
    if not index.recordings and not index.recording_sources:
        if index.groups:
            raw_folders = [(group.group_id, group.raw_input_folder) for group in index.groups.values()]
        else:
            folder = Path(manifest.get("input_folder") or "Input")
            raw_folders = [(None, folder if folder.is_absolute() else root / folder)]
        raw_seen = {}
        for group_id, folder in raw_folders:
            if not folder.is_dir():
                continue
            for path in sorted(folder.iterdir()):
                if not path.is_file() or path.suffix.casefold() != ".bdf":
                    continue
                pid = infer_raw_participant_id(path)
                key = pid.casefold()
                if key in raw_seen:
                    raise ValueError(f"Duplicate raw participant identity {pid}; review the project sources first.")
                raw_seen[key] = path
                participant_ids.setdefault(key, pid)
                raw_groups[key] = group_id
                stat = path.stat()
                files.append((str(path), stat.st_size, stat.st_mtime_ns))
    for record in (*index.workbooks, *index.excluded_workbooks):
        participant_ids.setdefault(record.participant_id.casefold(), record.participant_id)
        processed_participants.add(record.participant_id.casefold())
        if record.recording_id:
            recording_ids.setdefault(record.recording_id.casefold(), record.recording_id)
            recording_participants.setdefault(record.recording_id.casefold(), record.participant_id)
            processed_recordings.add(record.recording_id.casefold())
        stat = record.path.stat()
        files.append((str(record.path), stat.st_size, stat.st_mtime_ns))
    manual_participants = _entries(state, "manual_participant_exclusions")
    manual_recordings = _entries(state, "manual_recording_exclusions")
    review_decisions = _entries(state, "review_decisions")
    for pid in (*normalized["manual_excluded_participants"], *exclusions.excluded_participants):
        participant_ids.setdefault(pid.casefold(), pid)
    for rid in (*normalized["manual_excluded_recordings"], *exclusions.excluded_recordings):
        recording_ids.setdefault(rid.casefold(), rid)
    for entry in (*manual_recordings, *review_decisions):
        rid = str(entry.get("recording_id") or "")
        if rid:
            recording_participants.setdefault(rid.casefold(), str(entry.get("participant_id") or ""))

    def make_row(pid: str, rid: str = "") -> DatasetExclusionRow:
        key = (rid or pid).casefold()
        processing = key in (processing_recordings if rid else processing_participants)
        analysis = key in (analysis_recordings if rid else analysis_participants)
        identity = _identity(pid, rid)
        participant = index.participants.get(participant_ids.get(pid.casefold(), pid))
        group = index.groups.get(participant.group_id if participant is not None else raw_groups.get(pid.casefold()))
        details = []
        if processing:
            details.append("Saved preprocessing exclusion: this dataset is skipped during processing.")
        if analysis:
            details.append("Saved frequency-domain exclusion: this dataset is excluded from analysis.")
        if rid:
            inherited = _scope(pid.casefold() in processing_participants, pid.casefold() in analysis_participants)
            if inherited != "include":
                details.append(
                    f"Whole-participant scope is {inherited}; change the participant row to remove this inherited exclusion."
                )
        if participant is None:
            details.append("Participant is not registered in the current project metadata.")
        conditions = set()
        for owner, values in normalized["manual_excluded_participant_conditions"].items():
            if owner.casefold() == pid.casefold():
                conditions.update(f"{condition} (participant)" for condition in values)
        if rid:
            for owner, values in normalized["manual_excluded_recording_conditions"].items():
                if owner.casefold() == rid.casefold():
                    conditions.update(f"{condition} (recording)" for condition in values)
        conditions.update(
            f"{condition} (QC participant)"
            for owner, condition in exclusions.excluded_participant_conditions
            if owner.casefold() == pid.casefold()
        )
        if rid:
            conditions.update(
                f"{condition} (QC recording)"
                for owner, condition in exclusions.excluded_recording_conditions
                if owner.casefold() == rid.casefold()
            )
        if conditions:
            details.append("Condition exclusions remain unchanged: " + ", ".join(sorted(conditions)))
        field = "recording_id" if rid else "participant_id"
        action = DECISION_EXCLUDE_RECORDING if rid else DECISION_EXCLUDE_PARTICIPANT
        previous_reasons = [
            str(entry.get("reason") or "")
            for entry in (*(manual_recordings if rid else manual_participants), *review_decisions)
            if str(entry.get(field) or "").casefold() == key
            and ("decision" not in entry or entry.get("decision") == action)
        ]
        reason = (
            str(reasons[identity]) if identity in reasons else "; ".join(dict.fromkeys(filter(None, previous_reasons)))
        )
        return DatasetExclusionRow(
            identity,
            pid,
            rid,
            group.label if group else "",
            key in (processed_recordings if rid else processed_participants),
            _scope(processing, analysis),
            reason,
            tuple(details),
        )

    rows = [make_row(pid) for pid in participant_ids.values()]
    rows.extend(make_row(recording_participants.get(key, ""), rid) for key, rid in recording_ids.items())
    rows.sort(key=lambda row: (row.participant_id.casefold(), bool(row.recording_id), row.recording_id.casefold()))
    revision = hashlib.sha256(content + json.dumps(sorted(files)).encode("utf-8")).hexdigest()
    snapshot = DatasetExclusionsSnapshot(
        tuple(rows),
        revision,
        root,
        tuple(normalized["manual_excluded_participants"]),
        tuple(normalized["manual_excluded_recordings"]),
        bool(state.get("downstream_outputs_stale", False)),
    )
    return snapshot


def load_dataset_exclusions(project_root: str | Path) -> DatasetExclusionsSnapshot:
    """Read canonical owners, processed availability, and both exclusion stores."""

    return _load_context(Path(project_root).expanduser().resolve())[0]


def _set_processing_scope(preprocessing: dict, row: DatasetExclusionRow, enabled: bool) -> bool:
    key = "manual_excluded_recordings" if row.recording_id else "manual_excluded_participants"
    normalized = normalize_preprocessing_settings(preprocessing, allow_legacy_inversion=True)
    owner = row.recording_id or row.participant_id
    existing = list(normalized[key])
    retained = [value for value in existing if value.casefold() != owner.casefold()]
    if enabled:
        retained.append(owner)
    if {value.casefold() for value in existing} == {value.casefold() for value in retained}:
        return False
    preprocessing[key] = sorted(retained, key=str.casefold)
    return True


def _set_analysis_scope(
    state: dict, row: DatasetExclusionRow, enabled: bool, now: str, index
) -> tuple[bool, list[dict]]:
    field = "recording_id" if row.recording_id else "participant_id"
    owner = row.recording_id or row.participant_id
    key = "manual_recording_exclusions" if row.recording_id else "manual_participant_exclusions"
    action = DECISION_EXCLUDE_RECORDING if row.recording_id else DECISION_EXCLUDE_PARTICIPANT

    def matches(entry):
        return str(entry.get(field) or "").casefold() == owner.casefold()

    manual = _entries(state, key)
    decisions = _entries(state, "review_decisions")
    if enabled:
        if row.scope in {"exclude_analysis", "both"}:
            return False, []
        entry = {
            field: owner if row.recording_id else owner.upper(),
            "reason": "Other reviewed concern",
            "source": "dataset_exclusions_manager",
            "added_at": now,
        }
        if row.recording_id:
            recording = index.recordings.get(row.recording_id)
            entry.update(participant_id=row.participant_id, session_id=recording.session_id if recording else "")
        state[key] = [*manual, entry]
        return True, []
    removed_manual = [entry for entry in manual if matches(entry)]
    removed_decisions = [entry for entry in decisions if matches(entry) and entry.get("decision") == action]
    if not removed_manual and not removed_decisions:
        return False, []
    state[key] = [entry for entry in manual if not matches(entry)]
    state["review_decisions"] = [
        entry for entry in decisions if not (matches(entry) and entry.get("decision") == action)
    ]
    if removed_decisions:
        retired = _entries(state, "retired_review_decisions")
        state["retired_review_decisions"] = [*retired, *removed_decisions]
    return True, removed_manual


def _invalidate_outputs(tools: dict, state: dict, now: str) -> None:
    reason = "Dataset exclusion scopes changed. Resume post-processing before downstream analysis."
    state.update(downstream_outputs_stale=True, stale_reason=reason, stale_at=now)
    last_review = state.pop("last_review", None)
    if last_review is not None:
        manager = tools["dataset_exclusions"]
        retired = manager.setdefault("retired_review_receipts", [])
        if not isinstance(retired, list):
            raise ValueError("Retired dataset review receipts must contain a list.")
        retired.append({"retired_at": now, "reason": reason, "last_review": last_review})
    stats = tools.get("stats")
    if isinstance(stats, dict):
        cache = stats.get("group_significant_harmonics_cache")
        if isinstance(cache, dict):
            cache["entries"] = {}
    post_processing = tools.get("post_processing")
    registry = post_processing.get("artifact_freshness") if isinstance(post_processing, dict) else None
    if isinstance(registry, dict):
        artifacts = registry.get("artifacts")
        if isinstance(artifacts, dict):
            for artifact_id in (HARMONIC_SELECTION_SUMMARY_ARTIFACT, *SELECTION_DEPENDENT_ARTIFACTS):
                record = artifacts.get(artifact_id)
                if isinstance(record, dict):
                    record.update(status="stale", required_selection_fingerprint=None, updated_at=now, reason=reason)
            registry["updated_at"] = now


def _publish_manifest(root: Path, content: bytes, payload: bytes) -> None:
    path = root / "project.json"
    descriptor, temporary_name = tempfile.mkstemp(prefix=".project.json.dataset-exclusions-", suffix=".tmp", dir=root)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
        if path.read_bytes() != content:
            raise DatasetExclusionsConflictError(
                "The project changed before exclusions could be saved. Reload the manager."
            )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def save_dataset_exclusions(
    project_root: str | Path,
    snapshot: DatasetExclusionsSnapshot,
    changes: Mapping[str, str],
    *,
    reasons: Mapping[str, str] | None = None,
) -> DatasetExclusionsSnapshot:
    """Atomically patch explicitly changed whole-owner scopes, retaining history.

    ``both`` may retain an existing overlap but cannot create a new overlap.
    Condition exclusions are outside this API and are never removed by Include.
    """

    root = Path(project_root).expanduser().resolve()
    if root != snapshot.project_root:
        raise ValueError("The exclusion snapshot belongs to another project.")
    current, content, manifest, index = _load_context(root)
    if current.revision != snapshot.revision:
        raise DatasetExclusionsConflictError(
            "The project or processed files changed. Reload the manager before saving."
        )
    rows = {row.identity: row for row in current.rows}
    reasons = dict(reasons or {})
    if (set(changes) | set(reasons)) - rows.keys():
        raise ValueError("An exclusion change refers to an unknown dataset.")
    for identity, scope in changes.items():
        row = rows[identity]
        if scope not in {"include", "skip_processing", "exclude_analysis", "both"}:
            raise ValueError(f"Unknown dataset exclusion scope: {scope}.")
        if scope == "both" and row.scope != "both":
            raise ValueError("Choose one exclusion scope; new overlapping exclusions are not supported.")
        if scope == "exclude_analysis" and not row.has_processed_data and row.scope not in {"exclude_analysis", "both"}:
            raise ValueError(
                f"{row.recording_id or row.participant_id} has no processed data to exclude from analysis."
            )
    tools = manifest.setdefault("tools", {})
    state = tools.get("frequency_domain_qc", {})
    manager = tools.setdefault("dataset_exclusions", {})
    stored_reasons = manager.setdefault("reasons", {})
    history = _entries(manager, "history")
    preprocessing = manifest.get("preprocessing", {})
    now = datetime.now(UTC).replace(microsecond=0).isoformat()
    changed_scope = False
    events = []
    for identity in sorted(set(changes) | set(reasons)):
        row = rows[identity]
        scope = changes.get(identity, row.scope)
        scope_changed = False
        removed_manual = []
        if identity in changes and scope != row.scope:
            processing_changed = _set_processing_scope(preprocessing, row, scope in {"skip_processing", "both"})
            if processing_changed:
                manifest["preprocessing"] = preprocessing
            analysis_changed, removed_manual = _set_analysis_scope(
                state, row, scope in {"exclude_analysis", "both"}, now, index
            )
            scope_changed = processing_changed or analysis_changed
        reason = str(reasons.get(identity, row.reason)).strip()
        reason_changed = identity in reasons and reason != row.reason
        if not scope_changed and not reason_changed:
            continue
        changed_scope |= scope_changed
        if identity in reasons:
            stored_reasons[identity] = reason
        events.append(
            {
                "identity": identity,
                "participant_id": row.participant_id,
                "recording_id": row.recording_id,
                "previous_scope": row.scope,
                "scope": scope,
                "reason": reason,
                "changed_at": now,
                "removed_manual_analysis_exclusions": removed_manual,
            }
        )
    if not events:
        return current
    manager.update(schema_version=1, history=[*history, *events])
    if changed_scope:
        tools["frequency_domain_qc"] = state
        _invalidate_outputs(tools, state, now)
    payload = (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    saved_snapshot = _snapshot_from_manifest(root, payload, manifest, index)
    _publish_manifest(root, content, payload)
    return saved_snapshot


__all__ = [
    "DatasetExclusionRow",
    "DatasetExclusionsSnapshot",
    "DatasetExclusionsConflictError",
    "load_dataset_exclusions",
    "save_dataset_exclusions",
]
