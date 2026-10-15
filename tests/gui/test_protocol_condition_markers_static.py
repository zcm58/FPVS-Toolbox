"""Exercise the actual Protocol editor save adapters without loading Qt."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from Main_App.gui.project_protocol import (
    ProtocolEditorValues,
    build_manual_protocol,
    protocol_settings_save_requested,
)
from Main_App.projects import FrequencyProtocol, FrequencyProtocolError, ODDBALL_INPUT_MODE_RECURRENCE


SOURCE = Path(__file__).resolve().parents[2] / "src/Main_App/gui/settings_panel.py"


class _Edit:
    def __init__(self, value):
        self.value = value

    def text(self):
        return self.value

    def data(self, _role):
        return self.value


def _editor():
    protocol = FrequencyProtocol.from_recurrence(
        "6", 5, expected_analyzed_oddball_cycles=144,
        expected_analyzed_oddball_cycles_source="manual",
    ).with_condition_oddball_marker_codes({1: 51, 2: 52})
    rows = [(_Edit("2"), _Edit("52")), (_Edit("1"), _Edit("51"))]
    panel = SimpleNamespace(
        project=SimpleNamespace(frequency_protocol=protocol),
        protocol_presentation_rate_edit=_Edit("6"),
        protocol_oddball_every_n_edit=_Edit("5"),
        protocol_direct_oddball_rate_edit=_Edit("1.2"),
        protocol_expected_cycles_edit=_Edit("144"),
        protocol_requested_duration_edit=_Edit("120"),
        analysis_mode="cycles", preproc_edits=[_Edit("256")],
        protocol_oddball_marker_code_edit=_Edit("55"),
        protocol_oddball_mode_combo=SimpleNamespace(currentData=lambda: ODDBALL_INPUT_MODE_RECURRENCE),
        enabled=True,
        recording_enabled=False, _recording_marker_codes=(),
        _protocol_requires_confirmation=False,
        tabs=SimpleNamespace(currentIndex=lambda: 0), _protocol_tab_index=1,
    )
    panel.protocol_analysis_window_mode_combo = SimpleNamespace(currentData=lambda: panel.analysis_mode)
    panel.protocol_condition_markers_check = SimpleNamespace(isChecked=lambda: panel.enabled)
    panel.protocol_recording_markers_check = SimpleNamespace(isChecked=lambda: panel.recording_enabled)
    panel.protocol_condition_markers_table = SimpleNamespace(
        rowCount=lambda: len(rows), item=lambda row, column: rows[row][0 if column == 0 else 1],
    )
    names = {"_protocol_input_mode", "_protocol_editor_values", "_protocol_from_editor", "_protocol_save_requested", "_project_protocol_signature"}
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    owner = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "SettingsDialog")
    methods = [node for node in owner.body if isinstance(node, ast.FunctionDef) and node.name in names]
    assert {node.name for node in methods} == names
    namespace = {
        "Qt": SimpleNamespace(UserRole=object()), "ProtocolEditorValues": ProtocolEditorValues,
        "build_manual_protocol": build_manual_protocol, "FrequencyProtocolError": FrequencyProtocolError,
        "ODDBALL_INPUT_MODE_RECURRENCE": ODDBALL_INPUT_MODE_RECURRENCE,
        "protocol_settings_save_requested": protocol_settings_save_requested,
        "PREPROCESSING_FIELDS": ("downsample",),
    }
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), *methods], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(SOURCE), "exec"), namespace)
    for method in methods:
        setattr(panel, method.name, namespace[method.name].__get__(panel))
    panel._initial_protocol_editor_values = panel._protocol_editor_values()
    return panel, rows


def test_duration_and_target_grid_use_the_actual_settings_adapter():
    panel, _ = _editor()
    panel.analysis_mode = "manual_duration"
    panel.protocol_requested_duration_edit.value = "121"
    protocol = panel._protocol_from_editor(require_ready=True)
    assert protocol.expected_analyzed_oddball_cycles == 144
    panel.project.frequency_protocol = protocol
    panel._initial_protocol_editor_values = panel._protocol_editor_values()
    panel.preproc_edits[0].value = "300"
    assert panel._protocol_save_requested()
    updated = panel._protocol_from_editor(require_ready=True)
    assert updated.expected_analyzed_oddball_cycles == 145
    assert updated.condition_oddball_marker_codes == ((1, 51), (2, 52))


def test_inactive_duration_drafts_do_not_rewrite_saved_fixed_cycles():
    panel, _ = _editor()
    panel.protocol_requested_duration_edit.value = "77"
    panel.preproc_edits[0].value = "300"
    assert not panel._protocol_save_requested()
    assert panel._protocol_from_editor(require_ready=True).fingerprint == panel.project.frequency_protocol.fingerprint


def test_editor_preserves_mapping_keys_even_when_rows_are_reordered():
    panel, _ = _editor()
    assert panel._protocol_editor_values().condition_oddball_marker_codes == (("2", "52"), ("1", "51"))
    assert panel._protocol_from_editor(require_ready=True).condition_oddball_marker_codes == ((1, 51), (2, 52))
    assert not panel._protocol_save_requested()
    panel.protocol_expected_cycles_edit.value = "120"
    assert panel._protocol_save_requested()
    assert panel._protocol_from_editor(require_ready=True).condition_oddball_marker_codes == ((1, 51), (2, 52))


def test_editor_disable_is_an_explicit_save_and_clears_the_active_mapping():
    panel, _ = _editor()
    previous = panel._project_protocol_signature()
    panel.enabled = False
    assert panel._protocol_save_requested()
    assert panel._protocol_from_editor(require_ready=True).condition_oddball_marker_codes == ()
    assert panel._project_protocol_signature() != previous


def test_invalid_mapping_drafts_still_invalidate_the_editor_signature():
    panel, rows = _editor()
    rows[0][1].value = "invalid marker"
    previous = panel._project_protocol_signature()
    rows[0][1].value = "other invalid marker"
    assert panel._project_protocol_signature() != previous
    assert panel._protocol_save_requested()


def test_recording_schema_drafts_survive_unrelated_save_and_require_explicit_opt_out():
    panel, _ = _editor()
    panel.recording_enabled = True
    panel._recording_marker_codes = (("P01", ((1, 51), (2, 52))), ("P22", ((1, 55), (2, 55))))
    protocol = panel._protocol_from_editor(require_ready=True)
    assert protocol.recording_marker_codes("P01") == ((1, 51), (2, 52))
    assert protocol.recording_marker_codes("P22") == ((1, 55), (2, 55))
    panel.protocol_expected_cycles_edit.value = "120"
    assert panel._protocol_from_editor(require_ready=True).recording_oddball_marker_codes == protocol.recording_oddball_marker_codes
    template = panel._protocol_from_editor(require_ready=True, include_recordings=False)
    assert template.recording_oddball_marker_codes == ()
    panel.recording_enabled = False
    assert panel._protocol_from_editor(require_ready=True).recording_oddball_marker_codes == ()


@pytest.mark.parametrize("message, field_name, section", [
    ("Presentation rate must be positive", "protocol_presentation_rate_edit", 0),
    ("Oddball marker code is invalid", "protocol_oddball_marker_code_edit", 1),
])
def test_invalid_protocol_reveals_the_section_containing_the_field(message, field_name, section):
    owner = next(node for node in ast.parse(SOURCE.read_text(encoding="utf-8")).body
                 if isinstance(node, ast.ClassDef) and node.name == "SettingsDialog")
    method = next(node for node in owner.body if isinstance(node, ast.FunctionDef)
                  and node.name == "_validated_project_protocol")
    namespace = {
        "FrequencyProtocol": FrequencyProtocol, "FrequencyProtocolError": FrequencyProtocolError,
        "ODDBALL_INPUT_MODE_DIRECT_HZ": "oddball_rate_hz", "mark_invalid": Mock(),
    }
    exec(compile(ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])), str(SOURCE), "exec"), namespace)
    panel = SimpleNamespace(
        project=object(), tabs=Mock(), protocol_tabs=Mock(), _protocol_tab_index=1,
        _show_settings_validation=Mock(),
        _protocol_from_editor=Mock(side_effect=FrequencyProtocolError(message)),
        _protocol_input_mode=lambda: ODDBALL_INPUT_MODE_RECURRENCE,
        **{name: Mock() for name in (
            "protocol_presentation_rate_edit", "protocol_requested_duration_edit",
            "protocol_expected_cycles_edit", "protocol_oddball_marker_code_edit",
            "protocol_direct_oddball_rate_edit", "protocol_oddball_every_n_edit",
        )},
    )

    assert namespace[method.name](panel) is None
    panel.tabs.setCurrentIndex.assert_called_once_with(panel._protocol_tab_index)
    panel.protocol_tabs.setCurrentIndex.assert_called_once_with(section)
    field = getattr(panel, field_name)
    field.setFocus.assert_called_once_with()
    field.selectAll.assert_called_once_with()
    namespace["mark_invalid"].assert_called_once_with(field, message)
