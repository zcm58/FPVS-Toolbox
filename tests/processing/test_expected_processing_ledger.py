from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from Main_App.io.eeg_geometry import biosemi64_geometry_identity
from Main_App.processing.marker_integrity import (
    MARKER_REVIEW_DECISION_SCHEMA_VERSION,
    MARKER_REVIEWER_IDENTITY_STATUS_NOT_COLLECTED,
    MARKER_REVIEWER_STATE_EXPLICIT_GUI,
    build_marker_integrity_plan,
)
from Main_App.processing.preflight_qc_plan import plan_preflight_qc_events
from Main_App.processing.processing_controller import RawFileInfo
from Main_App.processing.processing_ledger import (
    EXPECTED_CELL_ACTION_EXCLUDE_CONDITION,
    EXPECTED_CELL_ACTION_EXCLUDE_RECORDING,
    EXPECTED_CELL_ACTION_LEGACY_UNKNOWN,
    EXPECTED_CELL_ACTION_PROCESS,
    EXPECTED_PLANNING_STATE_LEGACY_UNKNOWN,
    EXPECTED_PLANNING_STATE_PLANNED,
    EXPECTED_RECORDING_ACTION_EXCLUDE,
    EXPECTED_RECORDING_ACTION_LEGACY_UNKNOWN,
    EXPECTED_RECORDING_ACTION_PROCESS,
    EXPECTED_RECORDING_CONDITION_PLAN_LEDGER_KEY,
    EXPECTED_WORKBOOK_NOT_REQUIRED,
    EXPECTED_WORKBOOK_REQUIRED,
    EXPECTED_WORKBOOK_UNRESOLVED,
    ExpectedRecordingConditionPlan,
    ExpectedRecordingConditionPlanError,
    ProcessingInputState,
    ProcessingPlan,
    build_expected_recording_condition_plan,
    load_expected_recording_condition_plan,
    save_expected_recording_condition_plan,
    save_ledger,
)
from Main_App.projects.frequency_protocol import (
    EXPECTED_CYCLES_SOURCE_MANUAL,
    FrequencyProtocol,
)


def _protocol(*, cycles: int = 2) -> FrequencyProtocol:
    return FrequencyProtocol.from_recurrence(
        5,
        5,
        expected_analyzed_oddball_cycles=cycles,
        expected_analyzed_oddball_cycles_source=EXPECTED_CYCLES_SOURCE_MANUAL,
    )


def _processing_plan(
    tmp_path: Path,
    *,
    event_map: dict[str, int],
    infos: tuple[RawFileInfo, ...] | None = None,
    statuses: tuple[str, ...] | None = None,
) -> ProcessingPlan:
    if infos is None:
        raw_file = tmp_path / "P01.bdf"
        raw_file.write_bytes(b"raw-one")
        infos = (RawFileInfo(raw_file.resolve(), "P01"),)
    if statuses is None:
        statuses = tuple("new" for _info in infos)
    states: list[ProcessingInputState] = []
    for info, status in zip(infos, statuses, strict=True):
        outputs = tuple(
            (
                tmp_path
                / "1 - Excel Data Files"
                / label
                / f"{info.output_stem}_{label}_Results.xlsx"
            ).resolve()
            for label in event_map
        )
        states.append(
            ProcessingInputState(
                info=info,
                participant_id=info.subject_id,
                status=status,
                reason="test",
                expected_outputs=outputs,
            )
        )
    return ProcessingPlan(
        states=tuple(states),
        fingerprint="processing-fingerprint",
        condition_labels=tuple(event_map),
        geometry_identity=biosemi64_geometry_identity(),
    )


def _approved_event_plan(
    *,
    event_map: dict[str, int],
    events: list[list[int]],
    protocol: FrequencyProtocol | None = None,
    decisions: dict[str, dict[str, object]] | None = None,
    n_times: int = 100,
    first_samp: int = 0,
) -> dict[str, object]:
    resolved_protocol = protocol or _protocol()
    event_array = np.asarray(events, dtype=np.int64)
    review_scope = {
        "source_file_path": str(Path("marker-review-fixture.bdf").resolve()),
        "participant_id": "P01",
        "recording_id": None,
        "session_id": None,
        "session_label": None,
    }
    audited_decisions: dict[str, dict[str, object]] | None = None
    if decisions:
        marker_plan = build_marker_integrity_plan(
            events=event_array,
            event_map=event_map,
            sampling_rate_hz=10.0,
            n_times=n_times,
            first_samp=first_samp,
            protocol=resolved_protocol,
        )
        occurrences = {
            occurrence.occurrence_key: occurrence
            for occurrence in marker_plan.occurrences
        }
        audited_decisions = {}
        for occurrence_key, raw_decision in decisions.items():
            occurrence = occurrences[occurrence_key]
            audited_decisions[occurrence_key] = {
                **raw_decision,
                "schema_version": MARKER_REVIEW_DECISION_SCHEMA_VERSION,
                "reason": "Exclude this occurrence in the QC-20 fixture.",
                "reviewed_at_utc": "2026-09-04T12:00:00Z",
                "reviewer_state": MARKER_REVIEWER_STATE_EXPLICIT_GUI,
                "reviewer_identity": None,
                "reviewer_identity_status": (
                    MARKER_REVIEWER_IDENTITY_STATUS_NOT_COLLECTED
                ),
                **review_scope,
                "condition_label": occurrence.condition_label,
                "condition_code": occurrence.condition_code,
                "repetition_index": occurrence.repetition_index,
                "occurrence_key": occurrence.occurrence_key,
                "reviewed_marker_plan_fingerprint": marker_plan.fingerprint,
                "reviewed_occurrence_fingerprint": occurrence.fingerprint,
            }
    return plan_preflight_qc_events(
        events=event_array,
        event_map=event_map,
        sfreq=10.0,
        n_times=n_times,
        first_samp=first_samp,
        frequency_protocol=resolved_protocol,
        marker_review_decisions=audited_decisions,
        marker_review_scope=review_scope,
    ).to_payload()


def test_expected_matrix_preserves_nonzero_source_sample_origin(
    tmp_path: Path,
) -> None:
    event_map = {"Condition A": 1}
    processing_plan = _processing_plan(tmp_path, event_map=event_map)
    event_plan = _approved_event_plan(
        event_map=event_map,
        events=[
            [100, 0, 1],
            [110, 0, 55],
            [120, 0, 55],
            [130, 0, 55],
        ],
        first_samp=100,
    )

    expected = build_expected_recording_condition_plan(
        processing_plan=processing_plan,
        event_map=event_map,
        frequency_protocol=_protocol(),
        approved_event_plans={"P01": event_plan},
    )

    recording = expected.recordings[0]
    assert recording.marker_plan_identity is not None
    assert recording.marker_plan_identity["first_samp"] == 100
    occurrence = recording.cells[0].occurrences[0]
    assert (occurrence.source_start_sample, occurrence.source_stop_sample) == (
        110,
        130,
    )


def test_expected_matrix_binds_every_condition_and_exact_approved_span(
    tmp_path: Path,
) -> None:
    event_map = {"Condition A": 1, "Condition B": 2}
    processing_plan = _processing_plan(tmp_path, event_map=event_map)
    event_plan = _approved_event_plan(
        event_map=event_map,
        events=[
            [0, 0, 1],
            [10, 0, 55],
            [20, 0, 55],
            [30, 0, 55],
            [50, 0, 2],
            [60, 0, 55],
            [70, 0, 55],
            [80, 0, 55],
        ],
    )

    expected = build_expected_recording_condition_plan(
        processing_plan=processing_plan,
        event_map=event_map,
        frequency_protocol=_protocol(),
        approved_event_plans={"P01": event_plan},
        run_id="run-001",
        created_at="2026-09-04T12:00:00Z",
    )

    assert expected.run_id == "run-001"
    assert expected.protocol_fingerprint == _protocol().fingerprint
    assert expected.event_map == (("Condition A", 1), ("Condition B", 2))
    recording = expected.recordings[0]
    assert recording.processing_id == "P01"
    assert recording.planning_state == EXPECTED_PLANNING_STATE_PLANNED
    assert recording.planned_recording_action == EXPECTED_RECORDING_ACTION_PROCESS
    assert recording.marker_plan_identity is not None
    assert [cell.condition_label for cell in recording.cells] == [
        "Condition A",
        "Condition B",
    ]
    assert all(
        cell.planned_workbook_requirement == EXPECTED_WORKBOOK_REQUIRED
        for cell in recording.cells
    )
    assert all(
        cell.planned_cell_action == EXPECTED_CELL_ACTION_PROCESS
        for cell in recording.cells
    )
    assert [
        (
            cell.occurrences[0].source_start_sample,
            cell.occurrences[0].source_stop_sample,
            cell.occurrences[0].source_sample_count,
        )
        for cell in recording.cells
    ] == [(10, 30, 20), (60, 80, 20)]
    assert all(cell.to_payload()["final_outcome"] is None for cell in recording.cells)
    assert all(
        cell.occurrences[0].to_payload()["final_outcome"] is None
        for cell in recording.cells
    )


def test_expected_matrix_preserves_missing_condition_as_unresolved_cell(
    tmp_path: Path,
) -> None:
    event_map = {"Condition A": 1, "Condition B": 2}
    processing_plan = _processing_plan(tmp_path, event_map=event_map)
    event_plan = _approved_event_plan(
        event_map=event_map,
        events=[
            [0, 0, 1],
            [10, 0, 55],
            [20, 0, 55],
            [30, 0, 55],
        ],
    )

    expected = build_expected_recording_condition_plan(
        processing_plan=processing_plan,
        event_map=event_map,
        frequency_protocol=_protocol(),
        approved_event_plans={"P01": event_plan},
    )

    missing = expected.recordings[0].cells[1]
    assert missing.condition_label == "Condition B"
    assert missing.planning_state == EXPECTED_PLANNING_STATE_PLANNED
    assert missing.planned_workbook_requirement == EXPECTED_WORKBOOK_UNRESOLVED
    assert missing.occurrences == ()
    assert missing.planning_issues == (
        "no_marker_occurrence_for_expected_condition",
    )


def test_marker_review_exclusion_plans_no_workbook_but_not_a_final_outcome(
    tmp_path: Path,
) -> None:
    event_map = {"Condition A": 1}
    processing_plan = _processing_plan(tmp_path, event_map=event_map)
    event_plan = _approved_event_plan(
        event_map=event_map,
        events=[
            [0, 0, 1],
            [10, 0, 55],
            [12, 0, 55],
            [20, 0, 55],
            [30, 0, 55],
        ],
        decisions={"1:0": {"decision": "exclude_occurrence"}},
    )

    expected = build_expected_recording_condition_plan(
        processing_plan=processing_plan,
        event_map=event_map,
        frequency_protocol=_protocol(),
        approved_event_plans={"P01": event_plan},
    )

    cell = expected.recordings[0].cells[0]
    occurrence = cell.occurrences[0]
    assert cell.planned_workbook_requirement == EXPECTED_WORKBOOK_NOT_REQUIRED
    assert cell.planned_excluded_occurrence_count == 1
    assert occurrence.planned_disposition == "exclude_occurrence"
    assert occurrence.source_start_sample is None
    assert occurrence.source_stop_sample is None
    assert occurrence.to_payload()["final_outcome"] is None


def test_current_run_rejects_unresolved_or_missing_marker_plan(tmp_path: Path) -> None:
    event_map = {"Condition A": 1}
    processing_plan = _processing_plan(tmp_path, event_map=event_map)
    unresolved = _approved_event_plan(
        event_map=event_map,
        events=[
            [0, 0, 1],
            [10, 0, 55],
            [12, 0, 55],
            [20, 0, 55],
            [30, 0, 55],
        ],
    )

    with pytest.raises(
        ExpectedRecordingConditionPlanError,
        match="reviewed before building",
    ):
        build_expected_recording_condition_plan(
            processing_plan=processing_plan,
            event_map=event_map,
            frequency_protocol=_protocol(),
            approved_event_plans={"P01": unresolved},
        )

    with pytest.raises(
        ExpectedRecordingConditionPlanError,
        match="no reviewed marker plan",
    ):
        build_expected_recording_condition_plan(
            processing_plan=processing_plan,
            event_map=event_map,
            frequency_protocol=_protocol(),
            approved_event_plans={},
        )


def test_current_recording_exclusion_is_planned_without_marker_or_workbook(
    tmp_path: Path,
) -> None:
    event_map = {"Condition A": 1, "Condition B": 2}
    processing_plan = _processing_plan(tmp_path, event_map=event_map)

    expected = build_expected_recording_condition_plan(
        processing_plan=processing_plan,
        event_map=event_map,
        frequency_protocol=_protocol(),
        approved_event_plans={},
        planning_settings={"manual_excluded_participants": ["P01"]},
        created_at="2026-09-04T12:00:00Z",
    )

    recording = expected.recordings[0]
    assert recording.planning_state == EXPECTED_PLANNING_STATE_PLANNED
    assert recording.planned_recording_action == EXPECTED_RECORDING_ACTION_EXCLUDE
    assert recording.marker_plan_identity is None
    assert recording.no_output_decision is not None
    assert recording.no_output_decision["reviewer_identity"] is None
    assert (
        recording.no_output_decision["reviewer_identity_status"]
        == "not_collected"
    )
    assert all(
        cell.planned_cell_action == EXPECTED_CELL_ACTION_EXCLUDE_RECORDING
        and cell.planned_workbook_requirement == EXPECTED_WORKBOOK_NOT_REQUIRED
        and cell.no_output_decision == recording.no_output_decision
        for cell in recording.cells
    )


@pytest.mark.parametrize("has_condition_input", [True, False])
def test_current_condition_exclusion_preserves_occurrences_but_plans_no_output(
    tmp_path: Path,
    has_condition_input: bool,
) -> None:
    event_map = {"Condition A": 1, "Condition B": 2}
    processing_plan = _processing_plan(tmp_path, event_map=event_map)
    event_plan = _approved_event_plan(
        event_map=event_map,
        events=[
            [0, 0, 1],
            [10, 0, 55],
            [20, 0, 55],
            [30, 0, 55],
        ] + ([[50, 0, 2], [60, 0, 55], [70, 0, 55], [80, 0, 55]]
             if has_condition_input else []),
    )

    expected = build_expected_recording_condition_plan(
        processing_plan=processing_plan,
        event_map=event_map,
        frequency_protocol=_protocol(),
        approved_event_plans={"P01": event_plan},
        planning_settings={
            "manual_excluded_participant_conditions": {
                "P01": ["Condition B"]
            }
        },
        created_at="2026-09-04T12:00:00Z",
    )

    retained, excluded = expected.recordings[0].cells
    assert retained.planned_cell_action == EXPECTED_CELL_ACTION_PROCESS
    assert retained.planned_workbook_requirement == EXPECTED_WORKBOOK_REQUIRED
    assert excluded.planned_cell_action == EXPECTED_CELL_ACTION_EXCLUDE_CONDITION
    assert excluded.planned_workbook_requirement == EXPECTED_WORKBOOK_NOT_REQUIRED
    assert excluded.planned_occurrence_count == int(has_condition_input)
    assert excluded.planned_contributing_occurrence_count == 0
    assert excluded.planned_excluded_occurrence_count == int(has_condition_input)
    assert excluded.no_output_decision is not None
    assert excluded.no_output_decision["decision"] == "exclude_condition"
    from Main_App.processing.recording_condition_outcomes import reconcile_recording_condition_outputs

    outcomes = reconcile_recording_condition_outputs(expected, [])
    assert outcomes.cells[1].status == "excluded"
    assert outcomes.cells[1].contributor_count == 0
    assert outcomes.cells[0].status == "blocked"  # Other cells still require valid outputs.

def test_expected_matrix_rejects_stale_protocol_and_span_evidence(tmp_path: Path) -> None:
    event_map = {"Condition A": 1}
    processing_plan = _processing_plan(tmp_path, event_map=event_map)
    event_plan = _approved_event_plan(
        event_map=event_map,
        events=[
            [0, 0, 1],
            [10, 0, 55],
            [20, 0, 55],
            [30, 0, 55],
        ],
    )

    with pytest.raises(
        ExpectedRecordingConditionPlanError,
        match="different project protocol",
    ):
        build_expected_recording_condition_plan(
            processing_plan=processing_plan,
            event_map=event_map,
            frequency_protocol=_protocol(cycles=3),
            approved_event_plans={"P01": event_plan},
        )

    stale_span_plan = json.loads(json.dumps(event_plan))
    stale_span_plan["spans"][0]["time_stop_sample"] = 29
    with pytest.raises(
        ExpectedRecordingConditionPlanError,
        match="analyzed-interval plan is missing or stale",
    ):
        build_expected_recording_condition_plan(
            processing_plan=processing_plan,
            event_map=event_map,
            frequency_protocol=_protocol(),
            approved_event_plans={"P01": stale_span_plan},
        )

    stale_embedded_plan = json.loads(json.dumps(event_plan))
    stale_embedded_plan["source_analysis_span_plan"]["spans"][0][
        "source_coordinates"
    ]["stop_sample"] = 29
    with pytest.raises(
        ExpectedRecordingConditionPlanError,
        match="analyzed-interval plan is missing or stale",
    ):
        build_expected_recording_condition_plan(
            processing_plan=processing_plan,
            event_map=event_map,
            frequency_protocol=_protocol(),
            approved_event_plans={"P01": stale_embedded_plan},
        )


def test_repeated_sessions_keep_recording_identity_and_do_not_collapse_visits(
    tmp_path: Path,
) -> None:
    event_map = {"Condition A": 1}
    raw_one = tmp_path / "P01_visit_1.bdf"
    raw_two = tmp_path / "P01_visit_2.bdf"
    raw_one.write_bytes(b"visit-one")
    raw_two.write_bytes(b"visit-two")
    infos = (
        RawFileInfo(
            raw_one.resolve(),
            "P01",
            "control",
            "rec_p01_v1",
            "visit_1",
            "Visit 1",
            1,
            "control_v1",
        ),
        RawFileInfo(
            raw_two.resolve(),
            "P01",
            "control",
            "rec_p01_v2",
            "visit_2",
            "Visit 2",
            2,
            "control_v2",
        ),
    )
    processing_plan = _processing_plan(
        tmp_path,
        event_map=event_map,
        infos=infos,
    )
    event_plan = _approved_event_plan(
        event_map=event_map,
        events=[
            [0, 0, 1],
            [10, 0, 55],
            [20, 0, 55],
            [30, 0, 55],
        ],
    )

    expected = build_expected_recording_condition_plan(
        processing_plan=processing_plan,
        event_map=event_map,
        frequency_protocol=_protocol(),
        approved_event_plans={
            "rec_p01_v1": event_plan,
            str(raw_two.resolve()): event_plan,
        },
    )

    assert [recording.processing_id for recording in expected.recordings] == [
        "rec_p01_v1",
        "rec_p01_v2",
    ]
    assert [recording.participant_id for recording in expected.recordings] == [
        "P01",
        "P01",
    ]
    assert [recording.session_id for recording in expected.recordings] == [
        "visit_1",
        "visit_2",
    ]


def test_skipped_legacy_entry_stays_unknown_and_partial_is_never_upgraded(
    tmp_path: Path,
) -> None:
    event_map = {"Condition A": 1}
    current = _processing_plan(tmp_path, event_map=event_map)
    skipped_state = replace(current.states[0], status="completed")
    skipped_plan = replace(current, states=(skipped_state,))

    expected = build_expected_recording_condition_plan(
        processing_plan=skipped_plan,
        event_map=event_map,
        frequency_protocol=_protocol(),
        approved_event_plans={},
    )

    cell = expected.recordings[0].cells[0]
    assert expected.recordings[0].planning_state == EXPECTED_PLANNING_STATE_LEGACY_UNKNOWN
    assert (
        expected.recordings[0].planned_recording_action
        == EXPECTED_RECORDING_ACTION_LEGACY_UNKNOWN
    )
    assert cell.planning_state == EXPECTED_PLANNING_STATE_LEGACY_UNKNOWN
    assert cell.planned_cell_action == EXPECTED_CELL_ACTION_LEGACY_UNKNOWN
    assert cell.planned_workbook_requirement == EXPECTED_WORKBOOK_UNRESOLVED
    assert "partially_retained" not in json.dumps(expected.to_payload())

    project_root = tmp_path / "legacy-project"
    save_ledger(
        project_root,
        {
            "schema_version": 1,
            "entries": {
                "P01": {
                    "status": "completed",
                    "condition_completeness": "partial",
                    "completion_warning": "missing_expected_outputs",
                }
            },
        },
    )
    assert load_expected_recording_condition_plan(project_root) is None


def test_expected_matrix_round_trips_atomically_and_detects_tampering(
    tmp_path: Path,
) -> None:
    event_map = {"Condition A": 1}
    processing_plan = _processing_plan(tmp_path, event_map=event_map)
    event_plan = _approved_event_plan(
        event_map=event_map,
        events=[
            [0, 0, 1],
            [10, 0, 55],
            [20, 0, 55],
            [30, 0, 55],
        ],
    )
    expected = build_expected_recording_condition_plan(
        processing_plan=processing_plan,
        event_map=event_map,
        frequency_protocol=_protocol(),
        approved_event_plans={"P01": event_plan},
        run_id="round-trip",
        created_at="2026-09-04T12:00:00Z",
    )
    project_root = tmp_path / "project"

    save_expected_recording_condition_plan(project_root, expected)

    reloaded = load_expected_recording_condition_plan(project_root)
    assert reloaded == expected
    payload = json.loads(
        (
            project_root / ".fpvs_processing" / "processing_ledger.json"
        ).read_text(encoding="utf-8")
    )
    assert payload[EXPECTED_RECORDING_CONDITION_PLAN_LEDGER_KEY][
        "fingerprint"
    ] == expected.fingerprint

    stored = payload[EXPECTED_RECORDING_CONDITION_PLAN_LEDGER_KEY]
    stored["recordings"][0]["cells"][0]["expected_workbook"] = str(
        (tmp_path / "wrong.xlsx").resolve()
    )
    (
        project_root / ".fpvs_processing" / "processing_ledger.json"
    ).write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(
        ExpectedRecordingConditionPlanError,
        match="fingerprint mismatch",
    ):
        load_expected_recording_condition_plan(project_root)


def test_current_payload_cannot_be_loaded_with_invented_final_outcome(
    tmp_path: Path,
) -> None:
    event_map = {"Condition A": 1}
    processing_plan = _processing_plan(tmp_path, event_map=event_map)
    event_plan = _approved_event_plan(
        event_map=event_map,
        events=[
            [0, 0, 1],
            [10, 0, 55],
            [20, 0, 55],
            [30, 0, 55],
        ],
    )
    expected = build_expected_recording_condition_plan(
        processing_plan=processing_plan,
        event_map=event_map,
        frequency_protocol=_protocol(),
        approved_event_plans={"P01": event_plan},
    )
    payload = expected.to_payload()
    payload["recordings"][0]["cells"][0]["final_outcome"] = "ready"

    with pytest.raises(
        ExpectedRecordingConditionPlanError,
        match="cannot claim a final processing outcome",
    ):
        ExpectedRecordingConditionPlan.from_payload(payload)
