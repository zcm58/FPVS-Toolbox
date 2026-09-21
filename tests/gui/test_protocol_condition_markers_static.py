"""Exercise the actual Protocol editor save adapters without loading Qt."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

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
        protocol_oddball_marker_code_edit=_Edit("55"),
        protocol_oddball_mode_combo=SimpleNamespace(currentData=lambda: ODDBALL_INPUT_MODE_RECURRENCE),
        enabled=True,
        recording_enabled=False, _recording_marker_codes=(),
        _protocol_requires_confirmation=False,
        tabs=SimpleNamespace(currentIndex=lambda: 0), _protocol_tab_index=1,
    )
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
    }
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), *methods], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(SOURCE), "exec"), namespace)
    for method in methods:
        setattr(panel, method.name, namespace[method.name].__get__(panel))
    panel._initial_protocol_editor_values = panel._protocol_editor_values()
    return panel, rows


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
