"""Review-only missing condition identities; never synthetic FFT observations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from Main_App.processing.expected_processing_ledger import (
    EXPECTED_CELL_ACTION_EXCLUDE_CONDITION,
    EXPECTED_CELL_ACTION_PROCESS,
    EXPECTED_RECORDING_CONDITION_PLAN_LEDGER_KEY,
    ExpectedRecordingConditionCell,
)
from Main_App.processing.recording_condition_outcomes import (
    CELL_BLOCKED,
    CELL_EXCLUDED,
    CELL_UNAVAILABLE,
    load_recording_condition_outcomes,
)
from Main_App.projects import ProjectDatasetIndex


@dataclass(frozen=True, slots=True)
class MissingConditionOutput:
    participant_id: str
    condition: str
    group_id: str | None
    group_label: str | None
    outcome_status: str
    recording_id: str | None = None
    session_id: str | None = None
    session_label: str | None = None
    visit_index: int | None = None

    @property
    def pair_key(self) -> tuple[str, str]:
        return (self.recording_id or self.participant_id).casefold(), self.condition.casefold()

    @property
    def participant_pair_key(self) -> tuple[str, str]:
        return self.participant_id.casefold(), self.condition.casefold()

    @property
    def recording_pair_key(self) -> tuple[str, str] | None:
        return (self.recording_id.casefold(), self.condition.casefold()) if self.recording_id else None

    @property
    def requires_processing(self) -> bool:
        return self.outcome_status not in {CELL_EXCLUDED, CELL_UNAVAILABLE}


def missing_condition_output_rows(
    index: ProjectDatasetIndex,
    ledger: Mapping,
    *,
    excluded_participants: Sequence[str] = (),
    excluded_recordings: Sequence[str] = (),
) -> tuple[MissingConditionOutput, ...]:
    """Expose known missing cells while preserving current canonical identities."""
    outcomes = load_recording_condition_outcomes(ledger)
    if outcomes is None:
        return ()
    expected = ledger.get(EXPECTED_RECORDING_CONDITION_PLAN_LEDGER_KEY)
    if not isinstance(expected, Mapping) or (
        expected.get("run_id") != outcomes.expected_plan_run_id
        or expected.get("fingerprint") != outcomes.expected_plan_fingerprint
    ):
        return ()
    # Reuse the loaded ledger and validate only candidate cells, not its large
    # recording/marker payloads. The outcome pins each expected-cell fingerprint.
    expected_cells = {
        cell.get("cell_id"): cell
        for recording in expected.get("recordings", ()) if isinstance(recording, Mapping)
        for cell in recording.get("cells", ()) if isinstance(cell, Mapping)
    }
    present = {
        ((record.recording_id or record.participant_id).casefold(), record.condition.casefold())
        for record in (*index.workbooks, *index.excluded_workbooks)
    }
    participants = {key.casefold(): value for key, value in index.participants.items()}
    recordings = {key.casefold(): value for key, value in index.recordings.items()}
    participant_exclusions = {str(value).casefold() for value in excluded_participants}
    recording_exclusions = {str(value).casefold() for value in excluded_recordings}
    event_map = (index.manifest or {}).get("event_map")
    if not isinstance(event_map, Mapping):
        return ()  # Only currently declared project conditions can be selected.
    declared_conditions = {
        str(label).casefold(): (str(label), int(code)) for label, code in event_map.items()
    }
    rows = []
    for cell in outcomes.cells:
        identity = cell.processing_id.casefold()
        participant_key = cell.participant_id.casefold()
        condition_key = cell.condition_label.casefold()
        declaration = declared_conditions.get(condition_key)
        if (
            (identity, condition_key) in present
            or participant_key in participant_exclusions
            or identity in recording_exclusions
            or declaration is None or declaration[1] != cell.condition_code
            or cell.planned_occurrence_count != 0
            or cell.status not in {CELL_BLOCKED, CELL_EXCLUDED, CELL_UNAVAILABLE}
            or (cell.status == CELL_BLOCKED and "condition_input" not in cell.reason_codes)
        ):
            continue
        expected_payload = expected_cells.get(cell.cell_id)
        if not isinstance(expected_payload, Mapping) or expected_payload.get("occurrences"):
            continue
        expected_cell = ExpectedRecordingConditionCell.from_payload(expected_payload)
        expected_action = (
            EXPECTED_CELL_ACTION_PROCESS if cell.status == CELL_BLOCKED
            else EXPECTED_CELL_ACTION_EXCLUDE_CONDITION
        )
        if (expected_cell.fingerprint != cell.expected_cell_fingerprint
                or expected_cell.planned_cell_action != expected_action):
            continue  # Whole-recording technical exclusions are not condition choices.
        participant = participants.get(participant_key)
        if participant is None:
            continue  # A removed project participant must not be resurrected.
        recording = recordings.get(identity) if index.is_repeated_session else None
        if index.is_repeated_session and (
            recording is None or recording.participant_id.casefold() != participant_key
        ):
            continue
        group = index.groups.get(participant.group_id)
        session = index.sessions.get(recording.session_id) if recording else None
        rows.append(MissingConditionOutput(
            participant_id=participant.participant_id,
            condition=declaration[0],
            group_id=participant.group_id,
            group_label=group.label if group else None,
            outcome_status=cell.status,
            recording_id=recording.recording_id if recording else None,
            session_id=recording.session_id if recording else None,
            session_label=session.label if session else None,
            visit_index=recording.visit_index if recording else None,
        ))
    return tuple(sorted(rows, key=lambda row: (
        row.participant_id.casefold(), row.visit_index or 0,
        row.recording_id or "", row.condition.casefold(),
    )))


def missing_output_exclusions_changed(
    rows: Sequence[MissingConditionOutput],
    before_participants: Mapping[str, Sequence[str]],
    after_participants: Mapping[str, Sequence[str]],
    before_recordings: Mapping[str, Sequence[str]],
    after_recordings: Mapping[str, Sequence[str]],
) -> bool:
    """Changing a missing cell's scope or decision requires a fresh processing run."""
    def pairs(values):
        return {(str(identity).casefold(), str(condition).casefold())
                for identity, conditions in values.items() for condition in conditions}

    changed_participants = pairs(before_participants) ^ pairs(after_participants)
    changed_recordings = pairs(before_recordings) ^ pairs(after_recordings)
    return any(row.participant_pair_key in changed_participants
               or row.recording_pair_key in changed_recordings for row in rows)
