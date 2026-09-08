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


def _registration_fixture(tmp_path: Path, *, repeated: bool = False, exclude: bool = True):
    """Actual expected-plan/outcome schemas, with no EEG or GUI execution."""
    from Main_App.processing.raw_registration_state import registration_tool_updates
    from Main_App.processing.recording_condition_outcomes import reconcile_recording_condition_outputs

    event_map = {"Condition A": 1}
    infos = []
    participants = {}
    recordings = {}
    sessions = {}
    sources = {}
    for visit in (1, 2):
        participant = "P01" if repeated else f"P{visit:02d}"
        raw_root = tmp_path / f"visit_{visit}" if repeated else tmp_path
        raw_root.mkdir(exist_ok=True)
        raw_file = raw_root / f"P{visit:02d}.bdf"
        raw_file.write_bytes(f"raw-{visit}".encode())
        participants[participant] = {"group_id": "control"}
        if repeated:
            session_id = f"visit_{visit}"
            source_id = f"control_v{visit}"
            recording_id = f"rec_p01_v{visit}"
            sessions[session_id] = {"label": f"Visit {visit}", "visit_index": visit}
            sources[source_id] = {"group_id": "control", "session_id": session_id, "raw_input_folder": str(raw_root)}
            recordings[recording_id] = {
                "participant_id": participant, "session_id": session_id,
                "source_id": source_id, "raw_file": str(raw_file), "visit_index": visit,
            }
            infos.append(RawFileInfo(raw_file, participant, "control", recording_id, session_id, f"Visit {visit}", visit, source_id))
        else:
            participants[participant]["raw_file"] = str(raw_file)
            infos.append(RawFileInfo(raw_file, participant, "control"))
    processing = _processing_plan(tmp_path, event_map=event_map, infos=tuple(infos))
    event_plan = _approved_event_plan(event_map=event_map, events=[[0, 0, 1], [10, 0, 55], [20, 0, 55], [30, 0, 55]])
    ids = tuple(info.recording_id or info.subject_id for info in infos)
    expected = build_expected_recording_condition_plan(
        processing_plan=processing, event_map=event_map, frequency_protocol=_protocol(),
        approved_event_plans={} if exclude else {identity: event_plan for identity in ids},
        planning_settings=(
            {"manual_excluded_recordings" if repeated else "manual_excluded_participants": list(ids)} if exclude else {}
        ),
    )
    manifest = {
        "groups": {"control": {"label": "Control", "folder_name": "Control", "raw_input_folder": str(tmp_path)}},
        "participants": participants, "event_map": event_map,
        "sessions": sessions, "recording_sources": sources, "recordings": recordings,
        "frequency_protocol": _protocol().to_manifest(),
        "tools": {
            "frequency_domain_qc": {"review_complete": True, "review_decisions": [{"decision": "retain"}], "last_review": {"saved": "history"}},
            "processing": {"full_fft_provenance": {"status": "current", "source_fingerprint": "old"}},
            "stats": {"group_significant_harmonics_cache": {"entries": {"old": {"preserve": True}}}},
        },
    }
    manifest_path = tmp_path / "project.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    manifest["tools"].update(registration_tool_updates(tmp_path, [ids[-1]]))
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    receipts = [] if exclude else _registration_receipts(expected)
    outcomes = reconcile_recording_condition_outputs(expected, receipts, validate_artifacts=False)
    ledger = {"entries": {ids[0]: {"status": "completed", "untouched": True}},
              EXPECTED_RECORDING_CONDITION_PLAN_LEDGER_KEY: expected.to_payload(),
              "recording_condition_outcomes": outcomes.to_payload()}
    save_ledger(tmp_path, ledger)
    return manifest, expected, outcomes, ledger


def _registration_receipts(plan):
    """Valid accounting evidence; normal release must still reject absent files."""
    from Main_App.Shared.post_process import _fingerprinted_export_receipt
    from Main_App.processing.output_integrity import OutputIntegrityReceipt

    receipts = []
    for recording in plan.recordings:
        for cell in recording.cells:
            spans = [occurrence.approved_span_fingerprint for occurrence in cell.occurrences if occurrence.plans_workbook_contribution]
            receipts.append(_fingerprinted_export_receipt({
                "version": "recording_condition_export_receipt_v1", "status": "written",
                "run_id": plan.run_id, "processing_fingerprint": plan.processing_fingerprint,
                "processing_fingerprint_version": plan.processing_fingerprint_version,
                "recording_id": recording.processing_id, "condition_label": cell.condition_label,
                "protocol_fingerprint": plan.protocol_fingerprint, "geometry": dict(plan.geometry_identity),
                "path": cell.expected_workbook, "spectral_eligibility_fingerprint": "eligibility",
                "retained_occurrence_count": len(spans),
                "retained_occurrences": [{"approved_span_fingerprint": span} for span in spans],
                "workbook_write": {"version": "workbook_write_receipt_v1", "status": "written", "schema_validation": {"status": "passed"}},
                "finite_integrity": [OutputIntegrityReceipt(
                    stage=stage, recording_id=recording.processing_id,
                    condition_label=cell.condition_label, value_category=category,
                    inspected_value_count=1,
                ).to_payload() for stage, category in (("retained_signal", "retained_eeg"), ("computable_bca", "bca"))],
            }))
    return receipts


@pytest.mark.parametrize("repeated", [False, True])
@pytest.mark.parametrize("exclude", [False, True])
def test_registration_gate_accepts_current_accounting_without_mutating_history(tmp_path, monkeypatch, repeated, exclude):
    from Main_App.processing import recording_condition_outcomes
    from Main_App.processing.processing_ledger import ledger_path
    from Main_App.processing.raw_registration_state import require_registered_raw_processing_complete

    _manifest, _plan, outcomes, _ledger = _registration_fixture(tmp_path, repeated=repeated, exclude=exclude)
    assert outcomes.is_pre_review_ready
    before = [(path, path.read_bytes()) for path in (tmp_path / "project.json", ledger_path(tmp_path))]
    monkeypatch.setattr(recording_condition_outcomes, "_artifact_identity", lambda *_args: pytest.fail("registration gate must not hash workbooks"))
    require_registered_raw_processing_complete(tmp_path)
    require_registered_raw_processing_complete(tmp_path)
    assert all(path.read_bytes() == contents for path, contents in before)


def test_registration_metadata_accounting_does_not_weaken_normal_artifact_release(tmp_path):
    from Main_App.processing.recording_condition_outcomes import CELL_BLOCKED, reconcile_recording_condition_outputs

    _manifest, plan, outcomes, _ledger = _registration_fixture(tmp_path, exclude=False)
    assert outcomes.is_pre_review_ready
    checked = reconcile_recording_condition_outputs(plan, [cell.export_receipt for cell in outcomes.cells])
    assert all(cell.status == CELL_BLOCKED for cell in checked.cells)
    assert all("workbook_artifact_not_current" in cell.reason_codes for cell in checked.cells)


@pytest.mark.parametrize("repeated", [False, True])
def test_registration_gate_rejects_old_completed_subset(tmp_path, repeated):
    from Main_App.processing.raw_registration_state import RawRegistrationPendingError, require_registered_raw_processing_complete
    from Main_App.processing.recording_condition_outcomes import reconcile_recording_condition_outputs

    _manifest, expected, _outcomes, ledger = _registration_fixture(tmp_path, repeated=repeated)
    old = replace(expected, recordings=expected.recordings[:1])
    ledger[EXPECTED_RECORDING_CONDITION_PLAN_LEDGER_KEY] = old.to_payload()
    ledger["recording_condition_outcomes"] = reconcile_recording_condition_outputs(old, []).to_payload()
    save_ledger(tmp_path, ledger)
    with pytest.raises(RawRegistrationPendingError, match="absent from the processing plan"):
        require_registered_raw_processing_complete(tmp_path)


@pytest.mark.parametrize("change", ["run", "fingerprint", "missing_cell", "duplicate_cell", "wrong_source", "wrong_group", "condition", "protocol", "blocked", "invented_exclusion"])
def test_registration_gate_rejects_stale_or_incomplete_accounting(tmp_path, change):
    from Main_App.processing.raw_registration_state import RawRegistrationPendingError, require_registered_raw_processing_complete
    from Main_App.processing.recording_condition_outcomes import CELL_EXCLUDED, reconcile_recording_condition_outputs

    manifest, plan, outcomes, ledger = _registration_fixture(tmp_path, exclude=change != "invented_exclusion")
    if change == "run":
        outcomes = replace(outcomes, expected_plan_run_id="old-run")
    elif change == "fingerprint":
        outcomes = replace(outcomes, expected_plan_fingerprint="old-plan")
    elif change == "missing_cell":
        outcomes = replace(outcomes, cells=outcomes.cells[:1])
    elif change == "duplicate_cell":
        outcomes = replace(outcomes, cells=(*outcomes.cells, outcomes.cells[-1]))
    elif change == "wrong_source":
        manifest["participants"]["P02"]["raw_file"] = str(tmp_path / "different.bdf")
    elif change == "wrong_group":
        manifest["participants"]["P02"]["group_id"] = "unknown"
    elif change == "condition":
        manifest["event_map"]["Condition B"] = 2
    elif change == "protocol":
        manifest["frequency_protocol"] = _protocol(cycles=3).to_manifest()
    elif change == "blocked":
        plan = replace(plan, recordings=tuple(replace(recording, cells=tuple(
            replace(cell, planning_issues=("missing_input",)) for cell in recording.cells
        )) for recording in plan.recordings))
        # A valid excluded plan with stale cell fingerprints cannot masquerade as
        # the original run after its source planning evidence changed.
        ledger[EXPECTED_RECORDING_CONDITION_PLAN_LEDGER_KEY] = plan.to_payload()
    elif change == "invented_exclusion":
        cells = tuple(replace(cell, status=CELL_EXCLUDED, contributor_count=0, retained_occurrence_count=0,
                              excluded_occurrence_count=cell.planned_occurrence_count, export_receipt=None) for cell in outcomes.cells)
        outcomes = replace(outcomes, cells=cells)
        assert not reconcile_recording_condition_outputs(plan, []).is_pre_review_ready
    ledger["recording_condition_outcomes"] = outcomes.to_payload()
    save_ledger(tmp_path, ledger)
    (tmp_path / "project.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(RawRegistrationPendingError):
        require_registered_raw_processing_complete(tmp_path)


def test_registration_tool_updates_are_read_only_cumulative_and_preserve_decisions(tmp_path):
    from Main_App.processing.artifact_freshness import HARMONIC_SELECTION_SUMMARY_ARTIFACT, SELECTION_DEPENDENT_ARTIFACTS
    from Main_App.processing.raw_registration_state import registration_tool_updates

    manifest, _plan, _outcomes, _ledger = _registration_fixture(tmp_path)
    path = tmp_path / "project.json"
    before = path.read_bytes()
    updates = registration_tool_updates(tmp_path, ["P03"])
    assert path.read_bytes() == before
    state = updates["processing"]["pending_raw_registration"]
    assert state["processing_ids"] == ["P02", "P03"]
    assert state["registration_fingerprint"] != manifest["tools"]["processing"]["pending_raw_registration"]["registration_fingerprint"]
    assert updates["frequency_domain_qc"]["review_decisions"] == manifest["tools"]["frequency_domain_qc"]["review_decisions"]
    assert updates["frequency_domain_qc"]["last_review"] == {"saved": "history"}
    assert updates["frequency_domain_qc"]["downstream_outputs_stale"] is True
    assert updates["processing"]["full_fft_provenance"]["status"] == "stale"
    assert updates["stats"]["group_significant_harmonics_cache"]["entries"] == {}
    artifacts = updates["post_processing"]["artifact_freshness"]["artifacts"]
    assert all(artifacts[key]["status"] == "stale" for key in (HARMONIC_SELECTION_SUMMARY_ARTIFACT, *SELECTION_DEPENDENT_ARTIFACTS))
    updates["frequency_domain_qc"]["review_decisions"].clear()
    assert json.loads(path.read_text())["tools"]["frequency_domain_qc"]["review_decisions"]


def test_registration_gate_preserves_legacy_no_marker_path(tmp_path, monkeypatch):
    from Main_App.processing import processing_ledger
    from Main_App.processing.raw_registration_state import require_registered_raw_processing_complete

    monkeypatch.setattr(processing_ledger, "load_ledger", lambda *_args: pytest.fail("no marker requires no completion read"))
    require_registered_raw_processing_complete(tmp_path)


@pytest.mark.parametrize("change", ["empty", "fingerprint", "version", "case_duplicate", "session"])
def test_registration_gate_rejects_invalid_registration_receipt_or_session(tmp_path, change):
    from Main_App.processing.raw_registration_state import RawRegistrationPendingError, require_registered_raw_processing_complete

    manifest, _plan, _outcomes, _ledger = _registration_fixture(tmp_path, repeated=True)
    marker = manifest["tools"]["processing"]["pending_raw_registration"]
    if change == "empty":
        marker["processing_ids"] = []
    elif change == "fingerprint":
        marker["registration_fingerprint"] = "old"
    elif change == "version":
        marker["version"] = True
    elif change == "case_duplicate":
        marker["processing_ids"].append(marker["processing_ids"][0].upper())
    else:
        manifest["sessions"]["visit_2"]["label"] = "Changed session"
    (tmp_path / "project.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(RawRegistrationPendingError):
        require_registered_raw_processing_complete(tmp_path)


def test_registration_gate_rejects_supplied_old_outcomes(tmp_path):
    from Main_App.processing.raw_registration_state import RawRegistrationPendingError, require_registered_raw_processing_complete

    _manifest, _plan, outcomes, ledger = _registration_fixture(tmp_path)
    with pytest.raises(RawRegistrationPendingError, match="supplied outcomes are stale"):
        require_registered_raw_processing_complete(tmp_path, ledger=ledger, outcome_ledger=replace(outcomes, cells=outcomes.cells[:1]))


def test_registration_completion_does_not_require_raw_files_to_remain_mounted(tmp_path):
    from Main_App.processing.raw_registration_state import require_registered_raw_processing_complete

    _manifest, plan, _outcomes, _ledger = _registration_fixture(tmp_path)
    for recording in plan.recordings:
        Path(recording.raw_file_identity["raw_file"]).unlink()
    require_registered_raw_processing_complete(tmp_path)


def _save_single_registration_plan(root, plan, index):
    from Main_App.processing.recording_condition_outcomes import reconcile_recording_condition_outputs

    single = replace(plan, recordings=(plan.recordings[index],))
    outcomes = reconcile_recording_condition_outputs(single, [])
    ledger = {"entries": {"old": {"status": "completed"}},
              EXPECTED_RECORDING_CONDITION_PLAN_LEDGER_KEY: single.to_payload(),
              "recording_condition_outcomes": outcomes.to_payload()}
    save_ledger(root, ledger)
    return outcomes


@pytest.mark.parametrize("repeated", [False, True])
def test_registration_completion_accumulates_single_runs_then_allows_later_single(tmp_path, repeated):
    from Main_App.processing.raw_registration_state import (
        RawRegistrationPendingError, record_registered_raw_processing_completion,
        registration_tool_updates, require_registered_raw_processing_complete,
    )

    manifest, plan, _outcomes, _ledger = _registration_fixture(tmp_path, repeated=repeated)
    ids = tuple(recording.processing_id for recording in plan.recordings)
    manifest["tools"].update(registration_tool_updates(tmp_path, [ids[0]]))
    path = tmp_path / "project.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    revision = manifest["tools"]["processing"]["pending_raw_registration"]["registration_fingerprint"]
    first = _save_single_registration_plan(tmp_path, plan, 0)
    assert record_registered_raw_processing_completion(tmp_path, outcome_ledger=first) == (ids[0],)
    with pytest.raises(RawRegistrationPendingError, match="absent from the processing plan"):
        require_registered_raw_processing_complete(tmp_path)
    # A is safely accounted for although B still prevents post-processing.
    marker = json.loads(path.read_text())["tools"]["processing"]["pending_raw_registration"]
    assert set(marker["completed"]) == {ids[0]}
    assert marker["registration_fingerprint"] == revision
    second = _save_single_registration_plan(tmp_path, plan, 1)
    assert record_registered_raw_processing_completion(tmp_path, outcome_ledger=second) == (ids[1],)
    require_registered_raw_processing_complete(tmp_path)
    before = path.read_bytes()
    later = _save_single_registration_plan(tmp_path, plan, 0)
    assert record_registered_raw_processing_completion(tmp_path, outcome_ledger=later) == ()
    require_registered_raw_processing_complete(tmp_path)
    assert path.read_bytes() == before


def test_new_append_preserves_prior_completion_but_old_subset_cannot_complete_addition(tmp_path):
    from Main_App.processing.raw_registration_state import (
        RawRegistrationPendingError, record_registered_raw_processing_completion,
        registration_tool_updates, require_registered_raw_processing_complete,
    )

    _manifest, plan, _outcomes, _ledger = _registration_fixture(tmp_path)
    record_registered_raw_processing_completion(tmp_path)
    path = tmp_path / "project.json"
    manifest = json.loads(path.read_text())
    completed = manifest["tools"]["processing"]["pending_raw_registration"]["completed"]
    # Register the other fixture identity in a later append transaction.
    manifest["tools"].update(registration_tool_updates(tmp_path, ["P01"]))
    assert manifest["tools"]["processing"]["pending_raw_registration"]["completed"] == completed
    path.write_text(json.dumps(manifest), encoding="utf-8")
    _save_single_registration_plan(tmp_path, plan, 1)
    before = path.read_bytes()
    assert record_registered_raw_processing_completion(tmp_path) == ()
    assert path.read_bytes() == before
    with pytest.raises(RawRegistrationPendingError, match="absent from the processing plan"):
        require_registered_raw_processing_complete(tmp_path)
    _save_single_registration_plan(tmp_path, plan, 0)
    assert record_registered_raw_processing_completion(tmp_path) == ("P01",)
    require_registered_raw_processing_complete(tmp_path)


def test_registration_completion_save_failure_preserves_manifest_and_ledger(tmp_path, monkeypatch):
    from Main_App.processing import raw_registration_state as registration
    from Main_App.processing.processing_ledger import ledger_path

    _manifest, _plan, _outcomes, _ledger = _registration_fixture(tmp_path)
    paths = (tmp_path / "project.json", ledger_path(tmp_path))
    before = [path.read_bytes() for path in paths]
    def fail_replace(*_args):
        raise PermissionError("registration save denied")
    monkeypatch.setattr(registration.os, "replace", fail_replace)
    with pytest.raises(PermissionError, match="registration save denied"):
        registration.record_registered_raw_processing_completion(tmp_path)
    assert [path.read_bytes() for path in paths] == before
    assert not list(tmp_path.glob(".raw-registration-*.tmp"))


@pytest.mark.parametrize("changed_file", ["manifest", "ledger"])
def test_registration_completion_rejects_concurrent_state_change(tmp_path, monkeypatch, changed_file):
    from Main_App.processing import raw_registration_state as registration
    from Main_App.processing.processing_ledger import ledger_path

    _manifest, _plan, _outcomes, _ledger = _registration_fixture(tmp_path)
    manifest_path = tmp_path / "project.json"
    before = manifest_path.read_bytes()
    target = manifest_path if changed_file == "manifest" else ledger_path(tmp_path)
    def concurrent_write(_descriptor):
        value = json.loads(target.read_text())
        value["concurrent_change"] = True
        target.write_text(json.dumps(value), encoding="utf-8")
    monkeypatch.setattr(registration.os, "fsync", concurrent_write)
    with pytest.raises(registration.RawRegistrationPendingError, match="state changed"):
        registration.record_registered_raw_processing_completion(tmp_path)
    assert json.loads(target.read_text())["concurrent_change"] is True
    if changed_file == "ledger":
        assert manifest_path.read_bytes() == before
    assert not json.loads(manifest_path.read_text())["tools"]["processing"]["pending_raw_registration"]["completed"]
    assert not list(tmp_path.glob(".raw-registration-*.tmp"))


def test_registration_completion_is_portable_for_internal_raw_paths(tmp_path):
    from Main_App.processing.raw_registration_state import record_registered_raw_processing_completion, require_registered_raw_processing_complete

    manifest, _plan, _outcomes, _ledger = _registration_fixture(tmp_path)
    manifest["groups"]["control"]["raw_input_folder"] = "."
    for participant in manifest["participants"].values():
        participant["raw_file"] = Path(participant["raw_file"]).relative_to(tmp_path).as_posix()
    path = tmp_path / "project.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    record_registered_raw_processing_completion(tmp_path)
    moved = tmp_path / "copied-project"
    moved.mkdir()
    (moved / "project.json").write_bytes(path.read_bytes())
    # The copied project needs neither the old absolute root nor a full plan to
    # prove historical enrollment. Scientific release still validates its files.
    require_registered_raw_processing_complete(moved)


def test_corrupt_completion_cannot_satisfy_an_absent_registration(tmp_path):
    from Main_App.processing.raw_registration_state import RawRegistrationPendingError, record_registered_raw_processing_completion, require_registered_raw_processing_complete

    _manifest, plan, _outcomes, _ledger = _registration_fixture(tmp_path)
    record_registered_raw_processing_completion(tmp_path)
    path = tmp_path / "project.json"
    manifest = json.loads(path.read_text())
    manifest["tools"]["processing"]["pending_raw_registration"]["completed"]["P02"]["outcomes_fingerprint"] = "corrupt"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    _save_single_registration_plan(tmp_path, plan, 0)
    with pytest.raises(RawRegistrationPendingError, match="absent from the processing plan"):
        require_registered_raw_processing_complete(tmp_path)


def test_nonpersisting_pre_review_keeps_registration_receipts_read_only(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from Main_App.processing import raw_registration_state, roi_coverage

    _manifest, _plan, outcomes, ledger = _registration_fixture(tmp_path)
    path = tmp_path / "project.json"
    before = path.read_bytes()
    monkeypatch.setattr(raw_registration_state, "record_registered_raw_processing_completion", lambda *_args, **_kwargs: pytest.fail("persist=False must not write enrollment"))
    with pytest.raises(roi_coverage.RoiCoverageGateError, match="At least one frozen ROI"):
        roi_coverage.build_pre_review_roi_coverage(
            SimpleNamespace(project_root=tmp_path), outcome_ledger=outcomes,
            processing_ledger=ledger, roi_snapshot=SimpleNamespace(rois=()), persist=False,
        )
    assert path.read_bytes() == before


@pytest.mark.parametrize("consumer", ["canonical", "pre_review", "final", "full_fft", "current"])
def test_pending_registration_blocks_all_release_seams_before_side_effects(tmp_path, monkeypatch, consumer):
    from types import SimpleNamespace
    from Main_App.processing import frequency_domain_qc, full_fft_provenance, roi_coverage
    from Main_App.processing import post_processing_context
    from Main_App.processing.raw_registration_state import RawRegistrationPendingError

    _manifest, _plan, outcomes, ledger = _registration_fixture(tmp_path)
    ledger.pop(EXPECTED_RECORDING_CONDITION_PLAN_LEDGER_KEY)
    save_ledger(tmp_path, ledger)
    before = (tmp_path / "project.json").read_bytes()
    monkeypatch.setattr(post_processing_context, "cached_validation", lambda *_args: pytest.fail("pending enrollment must precede cache lookup"))
    monkeypatch.setattr(roi_coverage, "persist_roi_coverage", lambda *_args: pytest.fail("pending enrollment must precede coverage writes"))
    with pytest.raises((RawRegistrationPendingError, full_fft_provenance.FullFftProvenanceStaleError)):
        if consumer == "canonical":
            roi_coverage.require_canonical_released_dataset_index(tmp_path)
        elif consumer == "pre_review":
            roi_coverage.build_pre_review_roi_coverage(SimpleNamespace(project_root=tmp_path), outcome_ledger=outcomes)
        elif consumer == "final":
            roi_coverage.require_current_final_release(tmp_path, expected_decision_fingerprint="old")
        elif consumer == "full_fft":
            full_fft_provenance._source_snapshot(tmp_path, SimpleNamespace())
        else:
            frequency_domain_qc.mark_frequency_domain_outputs_current(tmp_path)
    assert (tmp_path / "project.json").read_bytes() == before
