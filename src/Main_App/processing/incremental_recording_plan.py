"""Carry reviewed per-recording plans and original exports into an incremental run."""

from dataclasses import replace
from typing import Any, Mapping

from Main_App.processing.expected_processing_ledger import (
    EXPECTED_CELL_ACTION_EXCLUDE_CONDITION,
    EXPECTED_PLANNING_STATE_PLANNED,
    EXPECTED_RECORDING_ACTION_EXCLUDE,
    EXPECTED_RECORDING_CONDITION_PLAN_LEDGER_KEY,
    ExpectedRecordingConditionCell,
    ExpectedRecordingConditionPlan,
    ExpectedRecordingConditionPlanError,
    ExpectedRecordingPlan,
)
from Main_App.processing.processing_ledger import (
    ProcessingInputState,
    ProcessingPlan,
    entry_matches_studio_approval,
    raw_file_metadata,
)
from Main_App.processing.recording_condition_outcomes import (
    CELL_BLOCKED,
    RecordingConditionCellOutcome,
    RecordingConditionOutcomeError,
    load_recording_condition_outcomes,
)


def _cell_route(cell: ExpectedRecordingConditionCell) -> tuple:
    return (
        cell.condition_label, cell.condition_code, cell.canonical_condition_id,
        cell.trigger_map_fingerprint, cell.expected_workbook,
    )


def _same_recording(
    old: ExpectedRecordingPlan,
    new: ExpectedRecordingPlan,
    state: ProcessingInputState,
    entry: Mapping[str, Any],
    exclusions: Mapping[str, Any],
) -> bool:
    """Check the current inputs and decisions independently of previous outputs."""
    identity_fields = (
        "processing_id", "participant_id", "group_id", "recording_id", "session_id",
        "session_label", "visit_index", "source_id", "days_from_baseline", "raw_file_identity",
    )
    if any(getattr(old, key) != getattr(new, key) for key in identity_fields):
        return False
    if any(entry.get(key) != value for key, value in raw_file_metadata(state.info.path).items()):
        return False
    if tuple(map(_cell_route, old.cells)) != tuple(map(_cell_route, new.cells)):
        return False
    if old.planning_state != EXPECTED_PLANNING_STATE_PLANNED:
        return False
    if new.marker_plan_identity is not None and new.marker_plan_identity != old.marker_plan_identity:
        return False
    if new.planned_recording_action == EXPECTED_RECORDING_ACTION_EXCLUDE:
        if old.planned_recording_action != EXPECTED_RECORDING_ACTION_EXCLUDE:
            return False
        manual = {"manual_participant_exclusion", "manual_recording_exclusion"}
        old_reasons = (old.no_output_decision or {}).get("evidence", {}).get("reason_codes", ())
        new_reasons = (new.no_output_decision or {}).get("evidence", {}).get("reason_codes", ())
        return manual.intersection(old_reasons) == manual.intersection(new_reasons)
    if old.planned_recording_action == EXPECTED_RECORDING_ACTION_EXCLUDE:
        return False
    excluded = exclusions["participant_conditions"].get(new.participant_id.casefold(), frozenset())
    excluded |= exclusions["recording_conditions"].get(new.processing_id.casefold(), frozenset())
    return all(
        (cell.condition_label.casefold() in excluded)
        == (cell.planned_cell_action == EXPECTED_CELL_ACTION_EXCLUDE_CONDITION)
        for cell in old.cells
    )


def _original_exports(
    recording: ExpectedRecordingPlan,
    entry: Mapping[str, Any],
    outcomes: Mapping[str, RecordingConditionCellOutcome],
) -> dict[str, str] | None:
    """Pin exactly the receipts that contributed to the previous reconciled cells."""
    receipts = entry.get("export_receipts", [])
    if not isinstance(receipts, list):
        return None
    by_condition = {}
    for receipt in receipts:
        if not isinstance(receipt, Mapping):
            return None
        label = receipt.get("condition_label")
        if not isinstance(label, str) or label in by_condition:
            return None
        by_condition[label] = receipt
    pins = {}
    for cell in recording.cells:
        outcome = outcomes.get(cell.cell_id)
        if (
            outcome is None or outcome.status == CELL_BLOCKED
            or outcome.expected_cell_fingerprint != cell.fingerprint
            or outcome.processing_id != recording.processing_id
            or outcome.participant_id != recording.participant_id
            or outcome.group_id != recording.group_id
            or outcome.condition_label != cell.condition_label
            or outcome.condition_code != cell.condition_code
        ):
            return None
        receipt = outcome.export_receipt
        if receipt is not None:
            if not isinstance(receipt.get("fingerprint"), str) or receipt != by_condition.get(cell.condition_label):
                return None
            pins[cell.condition_label] = receipt["fingerprint"]
    return pins


def _verified_history(ledger: Mapping):
    payload = ledger.get(EXPECTED_RECORDING_CONDITION_PLAN_LEDGER_KEY)
    if payload is None:
        return None
    previous = ExpectedRecordingConditionPlan.from_payload(payload)
    outcomes = load_recording_condition_outcomes(ledger)
    if outcomes is None:
        return None
    completed = (
        outcomes.expected_plan_fingerprint == previous.fingerprint
        and outcomes.expected_plan_run_id == previous.run_id
    )
    # An interruption can leave a frozen incremental plan alongside its parent's
    # outcomes. Only recordings pinned before that interruption remain eligible.
    if not completed and outcomes.expected_plan_fingerprint != previous.retained_from_plan:
        return None
    cells = {cell.cell_id: cell for cell in outcomes.cells}
    if len(cells) != len(outcomes.cells):
        return None
    return previous, outcomes.expected_plan_fingerprint, completed, cells


def unverified_completed_recordings(ledger: Mapping, states: list[ProcessingInputState]) -> set[str]:
    """Route incomplete native evidence back through this recording's own QC and worker."""
    entries = ledger.get("entries", {})
    candidates = {
        state.processing_id: state for state in states if state.status == "completed"
        and (
            entries[state.processing_id].get("recording_settings")
            or (EXPECTED_RECORDING_CONDITION_PLAN_LEDGER_KEY in ledger and entries[state.processing_id].get("export_receipts"))
        )
    }
    missing = set(candidates)
    if not missing:
        return missing
    try:
        history = _verified_history(ledger)
    except (ExpectedRecordingConditionPlanError, RecordingConditionOutcomeError):
        return missing
    if history is None:
        return missing
    previous, _parent_sha, completed, cells = history
    for row in previous.recordings:
        state = candidates.get(row.processing_id)
        if state is None or [cell.expected_workbook for cell in row.cells] != [str(path) for path in state.expected_outputs]:
            continue
        pins = _original_exports(row, entries[row.processing_id], cells)
        if pins is not None and (completed or previous.retained_export_fingerprints.get(row.processing_id) == pins):
            missing.discard(row.processing_id)
    return missing


def require_retained_studio_sources(processing_plan, prior_ledger, approvals, run_paths):
    """Recheck the ledger read for this freeze before accepting any skipped decision."""
    if not approvals:
        return
    entries = (prior_ledger or {}).get("entries", {})
    for state in processing_plan.states:
        if state.info.path.resolve(strict=False) in run_paths:
            continue
        entry = entries.get(state.processing_id) if isinstance(entries, Mapping) else None
        if not entry_matches_studio_approval(approvals, state.info.path, entry if isinstance(entry, Mapping) else {}):
            raise ExpectedRecordingConditionPlanError(
                f"Prior processing evidence for {state.processing_id} differs from the approved Studio source. "
                "Run Processing again."
            )


def bind_retained_recordings(
    current: ExpectedRecordingConditionPlan,
    processing_plan: ProcessingPlan,
    prior_ledger: Mapping[str, Any],
    exclusions: Mapping[str, Any],
) -> ExpectedRecordingConditionPlan:
    entries = prior_ledger.get("entries")
    if not isinstance(entries, Mapping):
        return current
    history = _verified_history(prior_ledger)
    if history is None:
        return current
    previous, parent_sha, completed_parent, verified_cells = history
    if (
        previous.geometry_identity != current.geometry_identity
        or previous.protocol_fingerprint != current.protocol_fingerprint
        or previous.event_map != current.event_map
    ):
        return current
    previous_by_id = {row.processing_id: row for row in previous.recordings}
    retained = {}
    records = []
    for new, state in zip(current.recordings, processing_plan.states, strict=True):
        old = previous_by_id.get(new.processing_id)
        entry = entries.get(new.processing_id)
        if (
            state.should_run_incremental or old is None or not isinstance(entry, Mapping)
            or entry.get("status") != state.status
            or entry.get("processing_fingerprint_version") != current.processing_fingerprint_version
            or entry.get("processing_fingerprint") != (state.pre_qc_fingerprint or current.processing_fingerprint)
            or not _same_recording(old, new, state, entry, exclusions)
        ):
            records.append(new)
            continue
        pins = _original_exports(old, entry, verified_cells)
        if pins is None or (not completed_parent and pins != previous.retained_export_fingerprints.get(new.processing_id)):
            records.append(new)
            continue
        records.append(old)
        retained[new.processing_id] = pins
    if not retained:
        return current
    return replace(
        current, recordings=tuple(records), retained_export_fingerprints=retained,
        retained_from_plan=parent_sha,
    )
