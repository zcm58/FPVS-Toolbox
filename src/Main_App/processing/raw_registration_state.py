"""Atomic registration freshness updates and read-only processing release guard.

The cumulative registration revision remains after processing. Compact enrollment
completion receipts survive later Single runs, whose expected plan contains only
the selected recording. Neither old per-file flags nor workbook presence proves
that a newly registered input has completed processing.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace

REGISTRATION_STATE_KEY = "pending_raw_registration"
REGISTRATION_STATE_VERSION = 1
_REASON = "New raw recordings were registered. Run Processing before resuming post-processing."


class RawRegistrationPendingError(RuntimeError):
    """Registered additions have not been accounted for by current processing."""


def _read_manifest(root: Path) -> dict:
    try:
        value = json.loads((root / "project.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeError, ValueError) as exc:
        raise RawRegistrationPendingError("Cannot validate raw registration metadata.") from exc
    if not isinstance(value, dict):
        raise RawRegistrationPendingError("Project registration metadata must be an object.")
    return value


def _mapping(value: object) -> dict:
    return deepcopy(dict(value)) if isinstance(value, Mapping) else {}


def _fingerprint(processing_ids: Sequence[str]) -> str:
    payload = {"version": REGISTRATION_STATE_VERSION, "processing_ids": list(processing_ids)}
    return _payload_fingerprint(payload)


def _payload_fingerprint(payload: object) -> str:
    return hashlib.sha256(json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")).hexdigest()


def _registered_ids(manifest: Mapping) -> tuple[str, ...]:
    tools = manifest.get("tools")
    processing = tools.get("processing") if isinstance(tools, Mapping) else None
    state = processing.get(REGISTRATION_STATE_KEY) if isinstance(processing, Mapping) else None
    if state is None:
        return ()
    if (
        not isinstance(state, Mapping)
        or type(state.get("version")) is not int
        or state.get("version") != REGISTRATION_STATE_VERSION
    ):
        raise RawRegistrationPendingError("Raw registration receipt is invalid.")
    ids = state.get("processing_ids")
    if (
        not isinstance(ids, list) or not ids
        or any(not isinstance(item, str) or not item or item != item.strip() for item in ids)
        or ids != sorted(ids)
        or len({item.casefold() for item in ids}) != len(ids)
        or state.get("registration_fingerprint") != _fingerprint(ids)
    ):
        raise RawRegistrationPendingError("Raw registration identity is invalid.")
    return tuple(ids)


def registration_tool_updates(
    project_root: str | Path,
    added_processing_ids: Sequence[str],
) -> dict:
    """Return replacement tool namespaces; the append transaction owns the write."""
    from Main_App.processing.artifact_freshness import (
        ARTIFACT_FRESHNESS_SCHEMA_VERSION,
        HARMONIC_SELECTION_SUMMARY_ARTIFACT,
        SELECTION_DEPENDENT_ARTIFACTS,
        canonical_artifact_path,
    )

    root = Path(project_root).expanduser().resolve(strict=False)
    manifest = _read_manifest(root)
    if not manifest:
        raise ValueError("Raw registration requires an existing project manifest.")
    if isinstance(added_processing_ids, (str, bytes)) or not added_processing_ids:
        raise ValueError("At least one new processing identity is required.")
    additions = list(added_processing_ids)
    if any(not isinstance(item, str) or not item or item != item.strip() for item in additions):
        raise ValueError("New processing identities must be nonblank canonical strings.")
    previous = _registered_ids(manifest)
    identities = [*previous, *additions]
    by_fold: dict[str, str] = {}
    for identity in identities:
        existing = by_fold.setdefault(identity.casefold(), identity)
        if existing != identity:
            raise ValueError("Processing identities differ only by case.")
    ids = sorted(by_fold.values())
    now = datetime.now(UTC).isoformat()
    tools = _mapping(manifest.get("tools"))
    processing = _mapping(tools.get("processing"))
    processing[REGISTRATION_STATE_KEY] = {
        "version": REGISTRATION_STATE_VERSION,
        "processing_ids": ids,
        "registration_fingerprint": _fingerprint(ids),
        "completed": _mapping(_mapping(processing.get(REGISTRATION_STATE_KEY)).get("completed")),
    }
    provenance = processing.get("full_fft_provenance")
    if isinstance(provenance, Mapping):
        processing["full_fft_provenance"] = {
            **deepcopy(dict(provenance)), "status": "stale",
            "stale_reason": _REASON, "stale_at": now,
        }
    qc = _mapping(tools.get("frequency_domain_qc"))
    qc.update(downstream_outputs_stale=True, stale_reason=_REASON, stale_at=now)
    stats = _mapping(tools.get("stats"))
    cache = stats.get("group_significant_harmonics_cache")
    if isinstance(cache, Mapping):
        stats["group_significant_harmonics_cache"] = {**deepcopy(dict(cache)), "entries": {}}
    post = _mapping(tools.get("post_processing"))
    registry = _mapping(post.get("artifact_freshness"))
    artifacts = _mapping(registry.get("artifacts"))
    for artifact_id in (HARMONIC_SELECTION_SUMMARY_ARTIFACT, *SELECTION_DEPENDENT_ARTIFACTS):
        record = _mapping(artifacts.get(artifact_id))
        record.update(
            status="stale",
            path=record.get("path") or canonical_artifact_path(root, artifact_id).relative_to(root).as_posix(),
            built_from_selection_fingerprint=(
                record.get("built_from_selection_fingerprint") or registry.get("selection_fingerprint")
            ),
            required_selection_fingerprint=None,
            updated_at=now, reason=_REASON, last_error="",
            archives=record.get("archives", []),
        )
        artifacts[artifact_id] = record
    registry.update(schema_version=ARTIFACT_FRESHNESS_SCHEMA_VERSION, updated_at=now, artifacts=artifacts)
    post["artifact_freshness"] = registry
    return {"processing": processing, "frequency_domain_qc": qc, "stats": stats, "post_processing": post}


def _canonical_identities(root: Path, manifest: Mapping) -> dict[str, dict]:
    from Main_App.projects import project_recording_context

    context = project_recording_context(SimpleNamespace(
        project_root=root,
        **{key: manifest.get(key, {}) for key in (
            "groups", "participants", "sessions", "recording_sources", "recordings",
        )},
    ))
    participants = {row.participant_id: row for row in context.participants}
    identities = {}
    if context.is_repeated_session:
        for recording in context.recordings:
            session = context.session(recording.session_id)
            identities[recording.recording_id] = {
                "processing_id": recording.recording_id,
                "participant_id": recording.participant_id,
                "group_id": participants[recording.participant_id].group_id,
                "recording_id": recording.recording_id, "session_id": recording.session_id,
                "session_label": session.label, "visit_index": recording.visit_index,
                "source_id": recording.source_id, "days_from_baseline": recording.days_from_baseline,
                "raw_file": str(recording.raw_file),
            }
    else:
        for participant in context.participants:
            identities[participant.participant_id] = {
                "processing_id": participant.participant_id, "participant_id": participant.participant_id,
                "group_id": participant.group_id, "recording_id": None, "session_id": None,
                "session_label": None, "visit_index": None, "source_id": None, "days_from_baseline": None,
                "raw_file": str(participant.raw_file) if participant.raw_file is not None else None,
            }
    return identities


def _planned_identity(recording: object) -> dict:
    return {
        **{key: getattr(recording, key) for key in (
            "processing_id", "participant_id", "group_id", "recording_id", "session_id",
            "session_label", "visit_index", "source_id", "days_from_baseline",
        )},
        "raw_file": str(Path(recording.raw_file_identity["raw_file"]).resolve(strict=False)),
    }


def _canonical_identity_fingerprint(root: Path, identity: Mapping) -> str:
    portable = dict(identity)
    raw_file = identity.get("raw_file")
    if raw_file is not None:
        path = Path(raw_file)
        try:
            portable["raw_file"] = {"project_relative": path.relative_to(root).as_posix()}
        except ValueError:
            portable["raw_file"] = {"external": path.as_posix()}
    return _payload_fingerprint(portable)


def _pending_ids(root: Path, manifest: Mapping) -> tuple[str, ...]:
    ids = _registered_ids(manifest)
    if not ids:
        return ()
    completed = manifest["tools"]["processing"][REGISTRATION_STATE_KEY].get("completed", {})
    if not isinstance(completed, Mapping) or not completed:
        return ids
    identities = _canonical_identities(root, manifest)
    pending = []
    for identity in ids:
        receipt = _mapping(completed.get(identity))
        saved_fingerprint = receipt.pop("fingerprint", None)
        valid = (
            type(receipt.get("version")) is int and receipt.get("version") == 1
            and receipt.get("processing_id") == identity
            and identity in identities
            and receipt.get("canonical_identity_fingerprint") == _canonical_identity_fingerprint(root, identities[identity])
            and all(isinstance(receipt.get(key), str) and receipt[key] for key in (
                "expected_plan_run_id", "expected_plan_fingerprint", "expected_recording_fingerprint",
                "outcomes_fingerprint", "completed_at",
            ))
            and saved_fingerprint == _payload_fingerprint(receipt)
        )
        if not valid:
            pending.append(identity)
    return tuple(pending)


def require_registered_raw_processing_complete(
    project_root: str | Path,
    *,
    manifest: Mapping | None = None,
    ledger: Mapping | None = None,
    outcome_ledger: object | None = None,
) -> None:
    """Reject release until current processing accounts for every registered addition.

    No receipt means no behavior change for existing projects. This guard does
    not require raw files to remain mounted after processing; canonical source
    paths and the plan's validated raw identity remain the processing evidence.
    """
    root = Path(project_root).expanduser().resolve(strict=False)
    current_manifest = _read_manifest(root) if manifest is None else manifest
    ids = _pending_ids(root, current_manifest)
    if not ids:
        return
    _validate_accounting(root, current_manifest, ids, ledger=ledger, outcome_ledger=outcome_ledger)


def _validate_accounting(
    root: Path, manifest: Mapping, ids: Sequence[str], *, ledger: Mapping | None,
    outcome_ledger: object | None, require_all: bool = True,
):
    from Main_App.processing.expected_processing_ledger import (
        EXPECTED_RECORDING_CONDITION_PLAN_LEDGER_KEY,
        ExpectedRecordingConditionPlan,
    )
    from Main_App.processing.processing_ledger import load_ledger
    from Main_App.processing.recording_condition_outcomes import (
        load_recording_condition_outcomes,
        reconcile_recording_condition_outputs,
        require_pre_review_readiness,
    )
    from Main_App.projects.frequency_protocol import normalize_frequency_protocol

    try:
        state = load_ledger(root) if ledger is None else ledger
        plan = ExpectedRecordingConditionPlan.from_payload(state.get(EXPECTED_RECORDING_CONDITION_PLAN_LEDGER_KEY))
        outcomes = load_recording_condition_outcomes(state)
        if outcomes is None or (
            outcomes.expected_plan_run_id != plan.run_id
            or outcomes.expected_plan_fingerprint != plan.fingerprint
        ):
            raise RawRegistrationPendingError("The current plan and outcomes do not belong to the same processing run.")
        if outcome_ledger is not None and outcomes != outcome_ledger:
            raise RawRegistrationPendingError("The supplied outcomes are stale; reload the current processing run.")
        by_id = {recording.processing_id: recording for recording in plan.recordings}
        missing = [identity for identity in ids if identity not in by_id]
        if missing and require_all:
            raise RawRegistrationPendingError(f"Added recordings are absent from the processing plan: {', '.join(missing)}.")
        marked = tuple(by_id[identity] for identity in ids if identity in by_id)
        if not marked:
            return plan, outcomes, marked
        identities = _canonical_identities(root, manifest)
        for recording in marked:
            if identities.get(recording.processing_id) != _planned_identity(recording):
                raise RawRegistrationPendingError("Registered participant/group/session/raw source identity differs from the processing plan.")
        event_map = manifest.get("event_map")
        if not isinstance(event_map, Mapping) or dict(plan.event_map) != dict(event_map):
            raise RawRegistrationPendingError("The processing plan does not cover the current project conditions.")
        if normalize_frequency_protocol(manifest.get("frequency_protocol")).fingerprint != plan.protocol_fingerprint:
            raise RawRegistrationPendingError("The processing plan uses a different project frequency protocol.")
        expected_cells = {cell.cell_id: cell for recording in plan.recordings for cell in recording.cells}
        saved_cells = {cell.cell_id: cell for cell in outcomes.cells}
        if len(saved_cells) != len(outcomes.cells) or set(saved_cells) != set(expected_cells):
            raise RawRegistrationPendingError("The current outcomes do not account for the complete expected condition matrix.")
        for cell_id, cell in expected_cells.items():
            if saved_cells[cell_id].expected_cell_fingerprint != cell.fingerprint:
                raise RawRegistrationPendingError("The current condition outcomes do not match the processing plan.")
        for recording in marked:
            if {(cell.condition_label, cell.condition_code) for cell in recording.cells} != set(plan.event_map):
                raise RawRegistrationPendingError("An added recording has an incomplete expected condition matrix.")
        marked_cells = tuple(saved_cells[cell.cell_id] for recording in marked for cell in recording.cells)
        receipts = [cell.export_receipt for cell in marked_cells if cell.export_receipt is not None]
        # This is enrollment accounting, not a replacement for artifact release.
        # Normal source/release gates retain the complete workbook/companion checks.
        reconciled = reconcile_recording_condition_outputs(
            replace(plan, recordings=marked), receipts, validate_artifacts=False,
        )
        if reconciled.cells != marked_cells:
            raise RawRegistrationPendingError("Added recording outcomes no longer match their processing evidence.")
        require_pre_review_readiness(reconciled)
        return plan, outcomes, marked
    except (KeyError, TypeError, ValueError, RuntimeError, OSError) as exc:
        raise RawRegistrationPendingError(f"{_REASON} {exc}") from exc


def record_registered_raw_processing_completion(
    project_root: str | Path, *, outcome_ledger: object | None = None,
) -> tuple[str, ...]:
    """Persist validated enrollment before review; partial Single runs accumulate.

    This does not release scientific outputs. Missing registered inputs remain
    pending, and the caller must still run the enrollment and normal review gates.
    """
    from Main_App.processing.processing_ledger import ledger_path, load_ledger

    root = Path(project_root).expanduser().resolve(strict=False)
    manifest_path = root / "project.json"
    try:
        before = manifest_path.read_bytes()
    except FileNotFoundError:
        return ()
    manifest = json.loads(before)
    if not isinstance(manifest, Mapping):
        raise RawRegistrationPendingError("Project registration metadata must be an object.")
    ids = _pending_ids(root, manifest)
    if not ids:
        return ()
    processing_path = ledger_path(root)
    ledger_before = processing_path.read_bytes() if processing_path.exists() else None
    plan, outcomes, marked = _validate_accounting(
        root, manifest, ids, ledger=load_ledger(root), outcome_ledger=outcome_ledger, require_all=False,
    )
    if not marked:
        return ()
    state = manifest["tools"]["processing"][REGISTRATION_STATE_KEY]
    completed = _mapping(state.get("completed"))
    for recording in marked:
        receipt = {
            "version": 1, "processing_id": recording.processing_id,
            "canonical_identity_fingerprint": _canonical_identity_fingerprint(root, _planned_identity(recording)),
            "expected_plan_run_id": plan.run_id, "expected_plan_fingerprint": plan.fingerprint,
            "expected_recording_fingerprint": recording.fingerprint,
            "outcomes_fingerprint": _payload_fingerprint([
                cell.fingerprint for cell in outcomes.cells if cell.processing_id == recording.processing_id
            ]),
            "completed_at": datetime.now(UTC).isoformat(),
        }
        completed[recording.processing_id] = {**receipt, "fingerprint": _payload_fingerprint(receipt)}
    state["completed"] = completed
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", prefix=".raw-registration-", suffix=".tmp", dir=root, delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(manifest, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        if manifest_path.read_bytes() != before or (
            (processing_path.read_bytes() if processing_path.exists() else None) != ledger_before
        ):
            raise RawRegistrationPendingError("Project or processing state changed while recording enrollment. Reload the project.")
        os.replace(temporary, manifest_path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return tuple(recording.processing_id for recording in marked)


__all__ = [
    "REGISTRATION_STATE_KEY", "REGISTRATION_STATE_VERSION", "RawRegistrationPendingError",
    "registration_tool_updates", "require_registered_raw_processing_complete",
    "record_registered_raw_processing_completion",
]
