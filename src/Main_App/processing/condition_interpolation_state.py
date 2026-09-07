"""Durable, explicit condition-electrode repair requests and completion receipts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import tempfile

STATE_KEY = "condition_electrode_interpolation"
STATE_VERSION = "condition_electrode_interpolation_v1"
REPAIR_DECISION = "interpolate_condition_electrode"


class ConditionInterpolationPendingError(RuntimeError):
    """Accepted EEG repairs have not produced validated current outputs yet."""


def request_fingerprint(requests: Mapping) -> str:
    return hashlib.sha256(json.dumps(
        requests, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")).hexdigest()


def _empty_state() -> dict:
    return {"version": STATE_VERSION, "requests": {}, "pending": {},
            "completed": {}, "review_decisions": [], "source_identities": {}, "retired_requests": []}


def _state_from_manifest(manifest: Mapping) -> dict:
    tools = manifest.get("tools") or {}
    state = tools.get(STATE_KEY) if isinstance(tools, Mapping) else None
    if state is None:
        return _empty_state()
    if not isinstance(state, Mapping) or state.get("version") != STATE_VERSION:
        raise ConditionInterpolationPendingError("Condition interpolation metadata is invalid.")
    result = deepcopy(dict(state))
    for key in ("requests", "pending", "completed"):
        result.setdefault(key, {})
        if not isinstance(result[key], dict):
            raise ConditionInterpolationPendingError(f"Condition interpolation {key} is invalid.")
    result.setdefault("review_decisions", [])
    result.setdefault("source_identities", {})
    result.setdefault("retired_requests", [])
    return result


def queue_condition_interpolation_decisions(
    manifest: dict, decisions: Sequence[Mapping], report: Mapping,
) -> None:
    """Update the supplied manifest; its caller owns the single atomic save."""
    from Main_App.io.eeg_geometry import BIOSEMI64_CHANNELS

    state = _state_from_manifest(manifest)
    from Main_App.processing.processing_ledger import load_ledger

    root_text = str(report.get("project_root") or "")
    entries = load_ledger(Path(root_text)).get("entries", {}) if root_text else {}
    canonical = {channel.casefold(): channel for channel in BIOSEMI64_CHANNELS}
    changed: set[str] = set()
    for decision in decisions:
        if decision.get("decision") != REPAIR_DECISION:
            continue
        identity = str(decision.get("recording_id") or decision.get("participant_id") or "").strip()
        condition = str(decision.get("condition") or "").strip()
        electrode = canonical.get(str(decision.get("electrode") or "").strip().casefold())
        if not identity or not condition or electrode is None or decision.get("roi"):
            raise ValueError("Interpolation requires one recording, condition, and scalp electrode.")
        ledger_identity = next((key for key in entries if key.casefold() == identity.casefold()), identity)
        existing_identity = next((key for key in state["requests"] if key.casefold() == identity.casefold()), ledger_identity)
        entry = entries.get(ledger_identity, {})
        source = {key: entry[key] for key in ("raw_file", "raw_size", "raw_mtime_ns") if key in entry}
        if not _source_is_current(source):
            raise ValueError("The reviewed source recording changed or its identity is unavailable. Run Processing before requesting a repair.")
        previous_source = state["source_identities"].get(existing_identity)
        if previous_source is not None and previous_source != source:
            raise ValueError("Previous repairs belong to a different source recording. Run Processing to refresh the review.")
        state["source_identities"][existing_identity] = source
        conditions = state["requests"].setdefault(existing_identity, {})
        channels = conditions.setdefault(condition, [])
        if electrode not in channels:
            channels.append(electrode)
            channels.sort(key=BIOSEMI64_CHANNELS.index)
            changed.add(existing_identity)
        state["review_decisions"].append({
            **deepcopy(dict(decision)),
            "analysis_fingerprint": str(report.get("analysis_fingerprint") or ""),
        })
    now = datetime.now(UTC).isoformat()
    for identity in changed:
        state["pending"][identity] = {
            "request_fingerprint": request_fingerprint(state["requests"][identity]),
            "queued_at": now,
        }
    if changed or state["review_decisions"]:
        manifest.setdefault("tools", {})[STATE_KEY] = state


def load_condition_interpolation_state(project_root: str | Path) -> dict:
    path = Path(project_root) / "project.json"
    if not path.exists():
        return _empty_state()
    with path.open("r", encoding="utf-8") as stream:
        return _state_from_manifest(json.load(stream))


def save_condition_interpolation_state(project_root: str | Path, state: Mapping) -> None:
    """Merge only this feature's state into the latest on-disk project."""
    path = Path(project_root) / "project.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest.setdefault("tools", {})[STATE_KEY] = deepcopy(dict(state))
    atomic_json(path, manifest)


def _source_is_current(source: Mapping) -> bool:
    try:
        stat = Path(source["raw_file"]).stat()
        return stat.st_size == source["raw_size"] and stat.st_mtime_ns == source["raw_mtime_ns"]
    except (KeyError, TypeError, OSError):
        return False


def _source_matches_active_path(source: Mapping, identity: str, current_sources: Mapping | None) -> bool:
    if not _source_is_current(source):
        return False
    if current_sources is None:
        return True
    current = next((value for key, value in current_sources.items() if key.casefold() == identity.casefold()), None)
    return current is None or Path(current).resolve() == Path(source["raw_file"]).resolve()


def active_condition_interpolation_requests(project_root: str | Path, *, current_sources: Mapping | None = None) -> dict:
    """Read-only source guard used by individual child processes."""
    state = load_condition_interpolation_state(project_root)
    return {identity: requests for identity, requests in state["requests"].items()
            if _source_matches_active_path(state["source_identities"].get(identity, {}), identity, current_sources)}


def reconcile_condition_interpolation_sources(project_root: str | Path, *, current_sources: Mapping | None = None) -> tuple[dict, list[str]]:
    """Retire old-source approvals once in the parent runner before child writes."""
    state = load_condition_interpolation_state(project_root)
    warnings = []
    for identity in list(state["requests"]):
        source = state["source_identities"].get(identity, {})
        if _source_matches_active_path(source, identity, current_sources):
            continue
        state["retired_requests"].append({
            "processing_id": identity, "requests": state["requests"].pop(identity),
            "source_identity": state["source_identities"].pop(identity, {}),
            "reason": "source_recording_changed_or_unavailable", "retired_at": datetime.now(UTC).isoformat(),
            "completion": state["completed"].pop(identity, None),
        })
        state["pending"].pop(identity, None)
        warnings.append(f"{identity}: previous condition-electrode repair approvals were retired because the source recording changed. Review any new QC findings.")
    if warnings:
        save_condition_interpolation_state(project_root, state)
        from Main_App.processing.frequency_domain_qc import mark_frequency_domain_outputs_stale

        mark_frequency_domain_outputs_stale(
            project_root, reason="Condition-repair approvals were retired after a source recording changed. Run Processing and review the new data.",
        )
    return state["requests"], warnings


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", prefix=f".{path.stem}.", suffix=".tmp",
            dir=path.parent, delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def artifact_identity(path: str | Path, *, project_root: str | Path | None = None) -> dict:
    target = Path(path).resolve()
    digest = hashlib.sha256()
    with target.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    stat = target.stat()
    stored_path = str(target.relative_to(Path(project_root).resolve())) if project_root is not None else str(target)
    return {"path": stored_path, "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns, "sha256": digest.hexdigest()}


def active_condition_requests(expected, identity: str, requests: Mapping) -> dict:
    """Only explicit exclusions suspend approved repairs; missing input does not."""
    if expected is None:
        return dict(requests)
    recording = next((row for row in expected.recordings
                      if row.processing_id.casefold() == identity.casefold()), None)
    excluded = {cell.condition_label.casefold() for cell in recording.cells
                if cell.planned_cell_action in {"exclude_condition", "exclude_with_recording"}} if recording else set()
    return {condition: channels for condition, channels in requests.items() if condition.casefold() not in excluded}


def project_processing_identity(project_root: str | Path) -> str:
    """Track processing-affecting project settings separately from review metadata."""
    from Main_App.processing.processing_ledger import _DOWNSTREAM_ONLY_PREPROCESSING_KEYS

    manifest = json.loads((Path(project_root) / "project.json").read_text(encoding="utf-8"))
    preprocessing = manifest.get("preprocessing") or {}
    payload = {key: manifest.get(key) for key in (
        "frequency_protocol", "options", "subfolders", "groups", "participants", "sessions", "recording_sources", "recordings",
    )}
    payload["preprocessing"] = {key: value for key, value in preprocessing.items()
                                if key not in _DOWNSTREAM_ONLY_PREPROCESSING_KEYS}
    return request_fingerprint(payload)


def completion_is_current(project_root: str | Path, identity: str, state: Mapping) -> bool:
    completed = state.get("completed", {}).get(identity)
    requests = state.get("requests", {}).get(identity)
    if not isinstance(completed, Mapping) or not requests:
        return False
    if completed.get("request_fingerprint") != request_fingerprint(requests):
        return False
    if not _source_is_current(state.get("source_identities", {}).get(identity, {})):
        return False
    from Main_App.io.condition_data import condition_companion_identity
    from Main_App.io.spectral_data import spectral_companion_identity
    from Main_App.processing.processing_ledger import load_ledger
    from Main_App.processing.expected_processing_ledger import load_expected_recording_condition_plan

    entries = load_ledger(Path(project_root)).get("entries", {})
    entry = next((row for key, row in entries.items() if key.casefold() == identity.casefold()), {})
    if completed.get("processing_fingerprint") != entry.get("processing_fingerprint"):
        return False
    try:
        if completed.get("project_processing_identity") != project_processing_identity(project_root):
            return False
        expected = load_expected_recording_condition_plan(Path(project_root))
        active = active_condition_requests(expected, identity, requests)
        if set(completed.get("excluded_conditions", [])) != set(requests) - set(active):
            return False
        raw = completed["raw_file_identity"]
        stat = Path(raw["raw_file"]).stat()
        if stat.st_size != raw["raw_size"] or stat.st_mtime_ns != raw["raw_mtime_ns"]:
            return False
        for output in completed["outputs"]:
            path = (Path(project_root) / output["artifact"]["path"]).resolve()
            if Path(project_root).resolve() not in path.parents:
                return False
            if artifact_identity(path, project_root=project_root) != output["artifact"]:
                return False
            if condition_companion_identity(path) != output.get("condition_companion"):
                return False
            if spectral_companion_identity(path) != output.get("spectral_companion"):
                return False
        return bool(completed["outputs"]) or not active
    except (KeyError, OSError, TypeError, ValueError):
        return False


def require_no_pending_condition_interpolation(project_root: str | Path) -> None:
    state = load_condition_interpolation_state(project_root)
    unresolved = [identity for identity in state["requests"]
                  if identity in state["pending"] or not completion_is_current(project_root, identity, state)]
    if unresolved:
        raise ConditionInterpolationPendingError(
            "Condition-electrode interpolation must finish before analysis continues: "
            + ", ".join(unresolved) + ". Resume processing to apply the accepted repairs."
        )
