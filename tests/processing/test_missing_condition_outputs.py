"""Pure backend and AST checks; no Qt application is imported or launched."""

from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from Main_App.processing.expected_processing_ledger import ExpectedRecordingConditionCell
from Main_App.processing.full_fft_grid_qc import audit_project_full_fft_grids
from Main_App.processing.missing_condition_outputs import (
    MissingConditionOutput,
    missing_condition_output_rows,
    missing_output_exclusions_changed,
)
from Main_App.processing.recording_condition_outcomes import (
    RecordingConditionCellOutcome,
    RecordingConditionOutcomeLedger,
)
from Main_App.projects import ProjectDatasetIndex, WorkbookRecord
from Main_App.projects.frequency_protocol import FrequencyProtocol
from Main_App.projects.grouping import GroupInfo, ParticipantInfo
from Main_App.projects.preprocessing_settings import (
    normalize_manual_excluded_participant_conditions,
    normalize_manual_excluded_recording_conditions,
)
from Main_App.projects.recordings import RecordingInfo, SessionInfo


ROOT = Path(__file__).resolve().parents[2]
GUI = ROOT / "src" / "Main_App" / "gui"


def _index(root, *, repeated=False):
    protocol = FrequencyProtocol.from_recurrence(
        6, 5, expected_analyzed_oddball_cycles=144,
        expected_analyzed_oddball_cycles_source="manual",
    )
    return ProjectDatasetIndex(
        project_root=root, excel_root=root / "excel", scan_root=root / "excel",
        manifest={"event_map": {"Neutral Angry": 12, "Faces": 1},
                  "frequency_protocol": protocol.to_manifest()},
        groups={"control": GroupInfo("control", "Current group", "control", root)},
        participants={pid: ParticipantInfo(pid, "control", root / f"{pid}.bdf")
                      for pid in ("P9", "P56", "P19")},
        workbooks=(), excluded_workbooks=(), diagnostics=(),
        sessions={"visit2": SessionInfo("visit2", "Follow-up", 2)} if repeated else {},
        recordings={"P9_visit2": RecordingInfo(
            "P9_visit2", "P9", "visit2", "source", root / "P9.bdf", 2,
        )} if repeated else {},
    )


def _cell(root, *, participant="P9", recording=None, action="process_condition",
          status="blocked", reason="condition_input", count=0, condition="Neutral Angry"):
    identity = recording or participant
    code = 12 if condition == "Neutral Angry" else 1
    decision = None if action == "process_condition" else {
        "decision": "exclude_recording" if action == "exclude_with_recording" else action,
        "reason": "Explicit exclusion", "source": "project_settings",
        "recorded_at_utc": "2026-09-05T12:00:00Z", "reviewer_identity_status": "not_collected",
        "scope": {"processing_id": identity, "condition_label": condition}, "evidence": {},
    }
    expected = ExpectedRecordingConditionCell(
        processing_id=identity, condition_label=condition, condition_code=code,
        expected_workbook=str(root / f"{identity}_{condition}.xlsx"),
        planning_state="planned", planned_cell_action=action,
        planned_workbook_requirement="required" if decision is None else "not_required",
        occurrences=(), no_output_decision=decision,
    )
    ready = status == "ready"
    outcome = RecordingConditionCellOutcome(
        cell_id=expected.cell_id, processing_id=identity, participant_id=participant,
        group_id="obsolete_group", condition_label=condition, condition_code=code,
        status=status, reason_codes=(reason,), planned_occurrence_count=count,
        retained_occurrence_count=count if ready else 0, excluded_occurrence_count=0,
        unavailable_occurrence_count=0, failed_or_unresolved_occurrence_count=0 if ready else count,
        contributor_count=1 if ready else 0, expected_cell_fingerprint=expected.fingerprint,
        export_receipt={"status": "written"} if ready else None,
    )
    return expected, outcome


def _ledger(*pairs):
    outcomes = RecordingConditionOutcomeLedger("run", "expected-fingerprint", tuple(p[1] for p in pairs))
    return {"recording_condition_outcomes": outcomes.to_payload(),
            "expected_recording_condition_plan": {
                "run_id": "run", "fingerprint": "expected-fingerprint",
                "recordings": [{"cells": [p[0].to_payload() for p in pairs]}],
            }}


def test_missing_row_uses_current_canonical_identity_and_has_no_fft(tmp_path):
    index = _index(tmp_path, repeated=True)
    ledger = _ledger(_cell(tmp_path, recording="P9_visit2"))
    (row,) = missing_condition_output_rows(index, ledger)
    assert (row.participant_id, row.recording_id, row.session_label, row.visit_index) == (
        "P9", "P9_visit2", "Follow-up", 2,
    )
    assert row.group_id == "control" and row.group_label == "Current group"
    assert row.requires_processing
    assert not hasattr(row, "path") and not hasattr(row, "oddball_cycles")
    assert missing_condition_output_rows(index, ledger, excluded_recordings=["p9_VISIT2"]) == ()


@pytest.mark.parametrize("kwargs", [
    {"count": 1},  # Missing data from an observed occurrence is a different review.
    {"reason": "workbook_write"},
    {"status": "ready", "reason": "validated_current_receipt", "count": 1},
    {"action": "exclude_with_recording", "status": "excluded", "reason": "explicit_no_output_exclusion"},
])
def test_missing_files_and_whole_recording_failures_are_not_condition_choices(tmp_path, kwargs):
    assert missing_condition_output_rows(_index(tmp_path), _ledger(_cell(tmp_path, **kwargs))) == ()


def test_prior_condition_exclusion_remains_editable_but_global_exclusions_do_not(tmp_path):
    index = _index(tmp_path)
    ledger = _ledger(
        _cell(tmp_path, action="exclude_condition", status="excluded", reason="explicit_no_output_exclusion"),
        _cell(tmp_path, participant="P56"),
        _cell(tmp_path, participant="P19", action="exclude_with_recording", status="excluded",
              reason="explicit_no_output_exclusion"),
    )
    (row,) = missing_condition_output_rows(index, ledger, excluded_participants=["p56"])
    assert row.participant_id == "P9" and not row.requires_processing
    assert missing_output_exclusions_changed((row,), {"P9": ["Neutral Angry"]}, {}, {}, {})
    assert not missing_output_exclusions_changed((row,), {"P9": ["Neutral Angry"]},
                                                 {"p9": ["neutral angry"]}, {}, {})


def test_current_project_and_present_workbook_filter_stale_missing_rows(tmp_path):
    index = _index(tmp_path)
    ledger = _ledger(_cell(tmp_path))
    assert missing_condition_output_rows(replace(index, participants={}), ledger) == ()
    assert missing_condition_output_rows(replace(index, manifest={"event_map": {"Faces": 1}}), ledger) == ()
    assert missing_condition_output_rows(replace(index, manifest={"event_map": {"Neutral Angry": 13}}), ledger) == ()
    present = WorkbookRecord("P9", "Neutral Angry", tmp_path / "stale.xlsx", "control",
                             "Current group", "flat", None)
    assert missing_condition_output_rows(replace(index, workbooks=(present,)), ledger) == ()
    assert missing_condition_output_rows(replace(index, excluded_workbooks=(present,)), ledger) == ()
    ledger["expected_recording_condition_plan"]["run_id"] = "other_run"
    assert missing_condition_output_rows(index, ledger) == ()


def test_audit_reuses_ledger_and_keeps_missing_rows_out_of_grid_math(tmp_path, monkeypatch):
    from Main_App.processing import full_fft_grid_qc as qc
    from Main_App.processing.full_fft_grid_qc import FullFftGridObservation

    index = _index(tmp_path)
    record = WorkbookRecord("P56", "Faces", tmp_path / "P56_Faces.xlsx", "control",
                            "Current group", "flat", None)
    index = replace(index, workbooks=(record,))
    ledger = _ledger(_cell(tmp_path))
    load = Mock(return_value=ledger)
    exclusions = Mock(return_value=SimpleNamespace(excluded_participants=(), excluded_recordings=()))
    monkeypatch.setattr(qc, "load_project_dataset_index", lambda _root: index)
    monkeypatch.setattr(qc, "load_ledger", load)
    monkeypatch.setattr(qc, "active_frequency_domain_exclusions", exclusions)
    observation = FullFftGridObservation("P56", "Faces", record.path, "control", "Current group",
                                         144, 120.0, 1 / 120, 156, None, False)
    monkeypatch.setattr(qc, "_inspect_workbook_grid", lambda *_args, **_kwargs: observation)
    audit = audit_project_full_fft_grids(tmp_path)
    assert (audit.reference_oddball_cycles, audit.reference_support, audit.reference_total) == (144, 1, 1)
    assert audit.observations == (observation,) and audit.review_candidates == ()
    assert len(audit.review_rows) == 2 and audit.review_rows[0].participant_id == "P9"
    assert audit.is_compatible_with_exclusions({})
    assert audit.is_compatible_with_exclusions({"P9": ["Neutral Angry"]})
    load.assert_called_once_with(tmp_path)
    exclusions.assert_called_once_with(tmp_path)


def _function(path, name, namespace):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)
    node.decorator_list = []
    node.body = [n for n in node.body if not isinstance(n, ast.Nonlocal)]
    module = ast.Module(body=[ast.ImportFrom("__future__", [ast.alias("annotations")], 0), node],
                        type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(path), "exec"), namespace)
    return namespace[name]


def test_missing_dialog_rows_start_unchecked_and_keep_existing_decisions():
    tree = ast.parse((GUI / "participant_condition_exclusions_dialog.py").read_text(encoding="utf-8"))
    expression = next(n.value for n in ast.walk(tree) if isinstance(n, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == "should_check" for t in n.targets))
    row = MissingConditionOutput("P9", "Neutral Angry", None, None, "blocked")
    namespace = {"observation": row, "participant_pair": row.participant_pair_key,
                 "recording_pair": None, "existing_pairs": set(), "existing_recording_pairs": set(),
                 "candidate_pairs": {row.pair_key}, "MissingConditionOutput": MissingConditionOutput}
    code = compile(ast.Expression(expression), "dialog check state", "eval")
    assert eval(code, namespace) is False
    namespace["existing_pairs"] = {row.participant_pair_key}
    assert eval(code, namespace) is True
    from Main_App.gui.condition_exclusion_review_model import status_label

    assert status_label(row, None) == "Missing output"


@pytest.mark.parametrize("selected", [False, True])
@pytest.mark.parametrize("recalculate", [False, True])
def test_saving_missing_decision_requires_processing_and_never_resumes_postprocessing(selected, recalculate):
    row = MissingConditionOutput("P9", "Neutral Angry", None, None, "blocked")
    proposed = {"P9": ["Neutral Angry"]} if selected else {}
    owner = SimpleNamespace()
    panel = SimpleNamespace(
        _manual_excluded_participant_conditions={}, _manual_excluded_recording_conditions={},
        _restore_harmonic_settings_after_cancel=Mock(), _clear_harmonic_settings_rollback=Mock(),
        _set_harmonic_recalculation_status=Mock(), _save_participant_condition_exclusions=Mock(return_value=True),
        _start_harmonic_recalculation=Mock(),
    )
    dialog = SimpleNamespace(exec=lambda: 1, excluded_participant_conditions=lambda: proposed)
    resume = Mock()
    namespace = {"self": panel, "owner": owner, "recalculate_after": recalculate,
                 "accept_on_success": False, "activity_handed_off": False,
                 "resume_frequency_postprocessing_after_release": False,
                 "ParticipantConditionExclusionsDialog": lambda *_a, **_k: dialog,
                 "QDialog": SimpleNamespace(Accepted=1),
                 "normalize_manual_excluded_participant_conditions": normalize_manual_excluded_participant_conditions,
                 "normalize_manual_excluded_recording_conditions": normalize_manual_excluded_recording_conditions,
                 "missing_output_exclusions_changed": missing_output_exclusions_changed,
                 "_resume_frequency_postprocessing_once": resume}
    handler = _function(GUI / "settings_panel.py", "_handle_finished", namespace)
    audit = SimpleNamespace(missing_condition_outputs=(row,), review_candidates=(), observations=(),
                            has_unresolved_grid_conflict=False, is_compatible_with_exclusions=Mock())
    handler(audit)
    assert panel._save_participant_condition_exclusions.call_count == int(selected)
    if selected:
        panel._save_participant_condition_exclusions.assert_called_once_with(
            proposed, recording_exclusions={}, invalidate_outputs=True,
        )
    message, level = panel._set_harmonic_recalculation_status.call_args.args
    assert "rerun Processing" in message or "Rerun Processing" in message
    assert "exclu" in message and level == "warning" and "ledger" not in message
    audit.is_compatible_with_exclusions.assert_not_called()
    panel._start_harmonic_recalculation.assert_not_called()
    resume.assert_not_called()
    assert not namespace["activity_handed_off"]
