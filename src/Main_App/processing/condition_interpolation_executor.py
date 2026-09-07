"""Resume accepted condition repairs through the normal, process-based runner."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import UTC, datetime
import json
from pathlib import Path
from queue import SimpleQueue

from Main_App.processing.condition_interpolation_state import (
    ConditionInterpolationPendingError, artifact_identity, atomic_json,
    completion_is_current, load_condition_interpolation_state, request_fingerprint,
    save_condition_interpolation_state, active_condition_requests,
    reconcile_condition_interpolation_sources,
    project_processing_identity,
)

SNAPSHOT_VERSION = "condition_interpolation_run_snapshot_v1"


class ConditionInterpolationProcessingRequired(ConditionInterpolationPendingError):
    """A normal Processing run is needed to refresh the reviewed run snapshot."""


def _snapshot_path(root: Path) -> Path:
    return root / ".fpvs_processing" / "condition_interpolation_run.json"


def _json_value(value):
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if callable(getattr(value, "to_manifest", None)):
        return _json_value(value.to_manifest())
    if callable(getattr(value, "item", None)):
        return value.item()
    return value


def build_condition_interpolation_run_snapshot(settings, event_map, plan, save_folder) -> dict:
    """Capture plain reviewed run inputs without doing GUI-thread file I/O."""
    records = []
    for state in plan.states:
        info = _json_value(asdict(state.info))
        records.append({
            "info": info, "processing_id": state.processing_id,
            "expected_outputs": [str(path) for path in state.expected_outputs],
        })
    return {
        "version": SNAPSHOT_VERSION,
        "settings": _json_value(settings), "event_map": dict(event_map),
        "processing_fingerprint": plan.fingerprint,
        "save_folder": str(save_folder), "records": records,
    }


def persist_condition_interpolation_run_snapshot(project_root, snapshot) -> None:
    """Publish reviewed marker plans from the background runner, before processing."""
    root = Path(project_root).resolve()
    payload = deepcopy(snapshot)
    payload["project_root"] = str(root)
    payload["project_processing_identity"] = project_processing_identity(root)
    payload["save_folder"] = str(Path(payload["save_folder"]).resolve())
    for record in payload["records"]:
        source = Path(record["info"]["path"]).resolve()
        stat = source.stat()
        record["raw_file_identity"] = {
            "raw_file": str(source), "raw_size": stat.st_size, "raw_mtime_ns": stat.st_mtime_ns,
        }
    # Fail before publishing if any transient value cannot be stored losslessly.
    json.dumps(payload, allow_nan=False)
    atomic_json(_snapshot_path(root), payload)


def _load_snapshot(root: Path) -> dict:
    try:
        snapshot = json.loads(_snapshot_path(root).read_text(encoding="utf-8"))
        if snapshot.get("version") != SNAPSHOT_VERSION or snapshot.get("project_root") != str(root):
            raise ValueError("snapshot identity mismatch")
        if snapshot.get("project_processing_identity") != project_processing_identity(root):
            raise ValueError("processing settings changed")
        return snapshot
    except (OSError, ValueError, TypeError) as exc:
        raise ConditionInterpolationProcessingRequired(
            "Accepted condition repairs are waiting for their reviewed processing inputs. "
            "Run Processing again; the saved repairs will be applied automatically."
        ) from exc


def _run_recording(root, snapshot, record, requests, *, log_func):
    from Main_App.workers.process_runner import RunParams, run_project_parallel

    settings = deepcopy(snapshot["settings"])
    identity = record["processing_id"]
    info = record["info"]
    source = str(Path(info["path"]).resolve())
    settings["condition_electrode_interpolation_requests"] = requests
    requested = next(value for key, value in requests.items() if key.casefold() == identity.casefold())
    settings["_fpvs_export_only_conditions"] = list(requested)
    for field, key in (
        ("subject_id", "participant_id"), ("recording_id", "recording_id"),
        ("session_id", "session_id"), ("session_label", "session_label"),
        ("visit_index", "visit_index"), ("days_from_baseline", "days_from_baseline"),
        ("group", "group_id"),
    ):
        if info.get(field) is not None:
            settings.setdefault(f"_fpvs_{key}_by_file", {})[source] = info[field]
    settings.setdefault("_fpvs_output_stem_by_file", {})[source] = info.get("recording_id") or info["subject_id"]
    queue = SimpleQueue()
    run_project_parallel(RunParams(
        project_root=root, data_files=[Path(source)], settings=settings,
        event_map=snapshot["event_map"], save_folder=Path(snapshot["save_folder"]), max_workers=1,
    ), progress_queue=queue)
    results = []
    while not queue.empty():
        message = queue.get()
        if isinstance(message, dict) and isinstance(message.get("result"), dict):
            results.append(message["result"])
    if len(results) != 1 or results[0].get("status") not in {"ok", "success"}:
        detail = next((str(result.get("error")) for result in results if result.get("error")), "processing did not return one successful recording")
        raise ConditionInterpolationPendingError(f"Condition repair failed for {identity}: {detail}")
    log_func(f"Condition-electrode repair processed {identity}.")
    return results[0]


def execute_pending_condition_interpolations(project_root, *, log_func=None) -> bool:
    """Repair pending recordings, validate receipts, then allow QC to recompute."""
    root = Path(project_root).resolve()
    log = log_func or (lambda _message: None)
    state = load_condition_interpolation_state(root)
    if not state["requests"]:
        return False
    _requests, retired = reconcile_condition_interpolation_sources(root)
    if retired:
        for message in retired:
            log(message)
        raise ConditionInterpolationProcessingRequired(
            "A source recording changed; its previous condition repairs were retired. Run Processing again."
        )
    from Main_App.io.result_manifest import result_manifest_path
    from Main_App.processing.processing_ledger import load_ledger, save_ledger
    from Main_App.processing.expected_processing_ledger import (
        load_expected_recording_condition_plan, save_expected_recording_condition_plan,
    )
    from Main_App.processing.recording_condition_outcomes import (
        reconcile_recording_condition_outputs, require_pre_review_readiness,
        RECORDING_CONDITION_OUTCOME_LEDGER_KEY,
        RecordingConditionOutcomeError,
    )

    needed = [identity for identity in state["requests"]
              if identity in state["pending"] or not completion_is_current(root, identity, state)]
    if not needed:
        return False
    expected = load_expected_recording_condition_plan(root)
    adopted = False
    # A full normal Processing run may already have applied these requests.
    # Accept its current reconciled receipts instead of processing it twice.
    if expected is not None:
        ledger = load_ledger(root)
        payload = ledger.get(RECORDING_CONDITION_OUTCOME_LEDGER_KEY, {})
        try:
            all_receipts = [cell["export_receipt"] for cell in payload.get("cells", []) if cell.get("export_receipt")]
            require_pre_review_readiness(reconcile_recording_condition_outputs(expected, all_receipts))
            adoption_ready = payload.get("reconciliation_status") == "complete"
        except RecordingConditionOutcomeError:
            adoption_ready = False
        for identity in list(needed):
            active = active_condition_requests(expected, identity, state["requests"][identity])
            receipts = [cell.get("export_receipt", {}) for cell in payload.get("cells", [])
                        if str(cell.get("processing_id") or "").casefold() == identity.casefold()
                        and cell.get("condition_label") in active]
            # Snapshot verification also prevents adopting old receipts after
            # project filter/protocol changes that have not been processed yet.
            try:
                _load_snapshot(root)
                snapshot_current = True
            except ConditionInterpolationProcessingRequired:
                snapshot_current = False
            if adoption_ready and snapshot_current and _receipts_match_requests(
                receipts, active, expected,
            ):
                try:
                    _complete_receipts(root, identity, state, expected, receipts,
                                       next((row for key, row in ledger.get("entries", {}).items()
                                             if key.casefold() == identity.casefold()), {}))
                except (KeyError, OSError, TypeError, ValueError):
                    continue
                save_condition_interpolation_state(root, state)
                needed.remove(identity)
                adopted = True
    if not needed:
        return adopted
    snapshot = _load_snapshot(root)
    if expected is None or expected.processing_fingerprint != snapshot["processing_fingerprint"]:
        raise ConditionInterpolationProcessingRequired("Processing settings changed. Run Processing again before applying condition repairs.")
    records = {row["processing_id"].casefold(): row for row in snapshot["records"]}
    save_folder = Path(snapshot["save_folder"]).resolve()
    if save_folder == root or root not in save_folder.parents:
        raise ConditionInterpolationPendingError("The repair output folder must remain inside this project.")
    for identity in needed:
        record = records.get(identity.casefold())
        if record is None:
            raise ConditionInterpolationProcessingRequired(f"No reviewed processing input is saved for {identity}. Run Processing again.")
        raw = record["raw_file_identity"]
        stat = Path(raw["raw_file"]).stat()
        if stat.st_size != raw["raw_size"] or stat.st_mtime_ns != raw["raw_mtime_ns"]:
            raise ConditionInterpolationProcessingRequired(f"The source recording changed for {identity}. Run Processing again.")
    # Persist intent before any output changes. Errors/cancellation leave it pending.
    for identity in needed:
        state["pending"].setdefault(identity, {"request_fingerprint": request_fingerprint(state["requests"][identity])})
    save_condition_interpolation_state(root, state)
    for identity in needed:
        active = active_condition_requests(expected, identity, state["requests"][identity])
        conditions = set(active)
        recording = next((row for row in expected.recordings if row.processing_id.casefold() == identity.casefold()), None)
        if recording is None or not conditions <= {cell.condition_label for cell in recording.cells}:
            raise ConditionInterpolationPendingError(f"Repair conditions do not match the reviewed marker plan for {identity}.")
        updated_recording = replace(recording, cells=tuple(
            replace(cell, expected_workbook=str(result_manifest_path(cell.expected_workbook)))
            if cell.condition_label in conditions else cell for cell in recording.cells
        ))
        expected = replace(expected, recordings=tuple(
            updated_recording if row is recording else row for row in expected.recordings
        ))
        save_expected_recording_condition_plan(root, expected)
        snapshot["settings"]["_fpvs_expected_plan_run_id"] = expected.run_id
        snapshot["settings"]["_fpvs_processing_fingerprint"] = expected.processing_fingerprint
        snapshot["settings"]["_fpvs_processing_fingerprint_version"] = expected.processing_fingerprint_version
        log(f"Applying condition-electrode repairs for {identity}: {', '.join(sorted(conditions))}…")
        if not active:
            raise ConditionInterpolationPendingError("Run Processing again to reconcile the explicit recording-condition exclusions.")
        result = _run_recording(root, snapshot, records[identity.casefold()], {identity: active}, log_func=log)
        receipts = result.get("export_receipts") or result.get("audit", {}).get("export_receipts") or []
        if not _receipts_match_requests(receipts, active, expected):
            raise ConditionInterpolationPendingError(f"Not every requested condition was exported for {identity}.")
        ledger = load_ledger(root)
        original_outcomes = ledger.get(RECORDING_CONDITION_OUTCOME_LEDGER_KEY, {}).get("cells", [])
        merged = [cell["export_receipt"] for cell in original_outcomes
                  if cell.get("export_receipt") and not (
                      str(cell.get("processing_id") or "").casefold() == identity.casefold()
                      and cell.get("condition_label") in conditions)]
        merged.extend(receipts)
        outcomes = reconcile_recording_condition_outputs(expected, merged)
        require_pre_review_readiness(outcomes)
        entry = ledger["entries"][recording.processing_id]
        entry["export_receipts"] = [row for row in merged if str(
            row.get("recording_id") or row.get("processing_id") or row.get("participant_id") or ""
        ).casefold() == identity.casefold()]
        entry["expected_outputs"] = [cell.expected_workbook for cell in updated_recording.cells]
        entry["condition_electrode_interpolation"] = result.get("condition_electrode_interpolation", {})
        for key in ("source_derivative_status", "source_derivative_manifest", "source_derivative_outputs", "source_derivative_warning"):
            if key in result:
                entry[key] = result[key]
        ledger[RECORDING_CONDITION_OUTCOME_LEDGER_KEY] = {**outcomes.to_payload(), "reconciliation_status": "complete"}
        save_ledger(root, ledger)
        state = load_condition_interpolation_state(root)
        _complete_receipts(root, identity, state, expected, receipts,
                           records[identity.casefold()]["raw_file_identity"])
        save_condition_interpolation_state(root, state)
    return True


def _receipts_match_requests(receipts, requests, expected) -> bool:
    from Main_App.processing.condition_electrode_interpolation import CONDITION_INTERPOLATION_VERSION
    if len(receipts) != len(requests) or {row.get("condition_label") for row in receipts} != set(requests):
        return False
    for receipt in receipts:
        proof = receipt.get("condition_electrode_interpolation") or {}
        if (receipt.get("status") != "written" or receipt.get("run_id") != expected.run_id
                or receipt.get("processing_fingerprint") != expected.processing_fingerprint
                or proof.get("status") != "completed"
                or proof.get("version") != CONDITION_INTERPOLATION_VERSION
                or set(proof.get("requested_channels", [])) != set(requests[receipt["condition_label"]])
                or not proof.get("spans")):
            return False
    return True


def _complete_receipts(root, identity, state, expected, receipts, raw):
    from Main_App.io.condition_data import condition_companion_identity
    from Main_App.io.spectral_data import spectral_companion_identity

    raw_path = Path(raw["raw_file"])
    stat = raw_path.stat()
    if stat.st_size != raw["raw_size"] or stat.st_mtime_ns != raw["raw_mtime_ns"]:
        raise ValueError("Raw recording no longer matches the completed repair.")
    state["completed"][identity] = {
        "request_fingerprint": request_fingerprint(state["requests"][identity]),
        "processing_fingerprint": expected.processing_fingerprint,
        "project_processing_identity": project_processing_identity(root),
        "raw_file_identity": {key: raw[key] for key in ("raw_file", "raw_size", "raw_mtime_ns")},
        "completed_at": datetime.now(UTC).isoformat(),
        "excluded_conditions": sorted(set(state["requests"][identity]) - set(
            active_condition_requests(expected, identity, state["requests"][identity]))),
        "outputs": [{"artifact": artifact_identity(row["path"], project_root=root),
                     "condition_companion": condition_companion_identity(row["path"]),
                     "spectral_companion": spectral_companion_identity(row["path"])} for row in receipts],
    }
    state["pending"].pop(identity, None)
