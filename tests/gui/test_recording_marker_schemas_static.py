"""Exercise canonical recording choices and real dialog validation without Qt."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from Main_App.gui.recording_marker_schemas import RecordingMarkerIdentity, recording_marker_editor_rows, validate_recording_marker_assignments
from Main_App.projects import FrequencyProtocol, FrequencyProtocolError, validate_protocol_condition_codes


def test_flat_editor_uses_canonical_participants_without_raw_file_discovery(tmp_path):
    project = SimpleNamespace(project_root=tmp_path, participants={"P22": {}, "P2": {}, "P01": {}})
    rows = recording_marker_editor_rows(project)
    assert [row.recording_id for row in rows] == ["P01", "P2", "P22"]


def test_repeated_editor_uses_registered_recording_ids_without_fabricating_missing_visits(tmp_path, monkeypatch):
    from Main_App.gui import recording_marker_schemas as module
    from Main_App.projects import ProjectRecordingContext, RecordingInfo, SessionInfo

    context = ProjectRecordingContext(
        tmp_path, (SessionInfo("v1", "Visit 1", 1), SessionInfo("v2", "Visit 2", 2)), (),
        (RecordingInfo("P1_v2", "P1", "v2", "source", tmp_path / "visit2.bdf", 2),),
    )
    monkeypatch.setattr(module, "project_recording_context", lambda _project: context)
    assert recording_marker_editor_rows(object()) == (RecordingMarkerIdentity("P1_v2", "P1 · Visit 2"),)


def _dialog(schemas=("project", "shared"), shared="55", saved=()):
    source = Path(__file__).resolve().parents[2] / "src/Main_App/gui/recording_marker_schemas_dialog.py"
    owner = next(node for node in ast.parse(source.read_text(encoding="utf-8")).body if isinstance(node, ast.ClassDef))
    methods = [node for node in owner.body if isinstance(node, ast.FunctionDef) and node.name in {"_row_codes", "marker_codes"}]
    namespace = {"validate_recording_marker_assignments": validate_recording_marker_assignments, "validate_protocol_condition_codes": validate_protocol_condition_codes}
    exec(compile(ast.fix_missing_locations(ast.Module(body=methods, type_ignores=[])), str(source), "exec"), namespace)
    protocol = FrequencyProtocol.from_recurrence("6", 5).with_condition_oddball_marker_codes({1: 51, 2: 52})
    dialog = SimpleNamespace(
        _identities=(RecordingMarkerIdentity("P01", "P01"), RecordingMarkerIdentity("P22", "P22")),
        _protocol=protocol, _onsets=(1, 2), _project_codes=((1, 51), (2, 52)),
        _saved=dict(saved), _selectors=[SimpleNamespace(currentData=lambda schema=schema: schema) for schema in schemas],
        _shared_edits=[SimpleNamespace(text=lambda: shared) for _ in schemas],
    )
    for node in methods:
        setattr(dialog, node.name, namespace[node.name].__get__(dialog))
    return dialog


def test_dialog_materializes_complete_literal_schemas_for_each_recording():
    assert _dialog().marker_codes() == (("P01", ((1, 51), (2, 52))), ("P22", ((1, 55), (2, 55))))


def test_new_recording_is_unassigned_until_an_explicit_choice():
    with pytest.raises(FrequencyProtocolError, match="Not configured: P22"):
        _dialog(schemas=("project", "unassigned")).marker_codes()


def test_dialog_retains_custom_saved_schema_without_replacing_it_with_new_project_template():
    custom = ((1, 71), (2, 72))
    codes = _dialog(schemas=("custom", "shared"), saved=(("p01", custom),)).marker_codes()
    assert codes[0] == ("P01", custom)


def test_dialog_rejects_shared_code_colliding_with_a_condition_onset():
    with pytest.raises(FrequencyProtocolError, match="condition-onset"):
        _dialog(shared="1").marker_codes()
