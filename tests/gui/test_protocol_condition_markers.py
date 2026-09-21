"""CI-only visible Protocol editor smoke without the remaining Settings tools."""

from types import SimpleNamespace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QScrollArea, QTabWidget, QVBoxLayout

from Main_App.gui.settings_panel import SettingsDialog
from Main_App.projects import FrequencyProtocol


class _ProtocolDialog(QDialog):
    _init_protocol_tab = SettingsDialog._init_protocol_tab
    _protocol_input_mode = SettingsDialog._protocol_input_mode
    _protocol_editor_values = SettingsDialog._protocol_editor_values
    _protocol_from_editor = SettingsDialog._protocol_from_editor
    _refresh_protocol_preview = SettingsDialog._refresh_protocol_preview
    _configure_recording_marker_schemas = SettingsDialog._configure_recording_marker_schemas
    _validate_recording_marker_configuration = SettingsDialog._validate_recording_marker_configuration

    def _add_settings_footer(self, *_args):
        pass


def _dialog(qtbot, protocol):
    dialog = _ProtocolDialog()
    dialog.project = SimpleNamespace(
        frequency_protocol=protocol,
        event_map={"Mixed Response 2": 5, "Semantic Response": 3, "Color Response 1": 1, "Mixed Response 1": 4, "Color Response 2": 2},
    )
    layout = QVBoxLayout(dialog)
    dialog.tabs = QTabWidget(dialog)
    layout.addWidget(dialog.tabs)
    dialog._init_protocol_tab(dialog.tabs)
    qtbot.addWidget(dialog)
    dialog.resize(1100, 850)
    dialog.show()
    qtbot.waitExposed(dialog)
    return dialog


def _ready_protocol():
    return FrequencyProtocol.from_recurrence(
        "6", 5, expected_analyzed_oddball_cycles=144,
        expected_analyzed_oddball_cycles_source="manual",
    )


def test_condition_mapping_is_opt_in_and_disabling_restores_shared_code(qtbot):
    dialog = _dialog(qtbot, _ready_protocol())
    assert not dialog.protocol_condition_markers_check.isChecked()
    assert not dialog.protocol_condition_markers_table.isVisible()
    assert dialog.protocol_oddball_marker_code_edit.isEnabled()
    assert dialog._protocol_from_editor(require_ready=True).condition_oddball_marker_codes == ()
    qtbot.mouseClick(dialog.protocol_condition_markers_check, Qt.LeftButton)
    table = dialog.protocol_condition_markers_table
    assert table.isVisible()
    assert table.height() == 168
    assert dialog.findChildren(QScrollArea) == []
    assert not dialog.protocol_oddball_marker_code_edit.isEnabled()
    assert [table.item(row, 1).text() for row in range(5)] == ["1", "2", "3", "4", "5"]
    for row in range(5):
        assert not table.item(row, 0).flags() & Qt.ItemIsEditable
        assert not table.item(row, 1).flags() & Qt.ItemIsEditable
        table.item(row, 2).setText(str(51 + row))
    assert dialog._protocol_from_editor(require_ready=True).condition_oddball_marker_codes == tuple((code, code + 50) for code in range(1, 6))
    assert "5 condition-specific" in dialog.protocol_status.text()
    qtbot.mouseClick(dialog.protocol_condition_markers_check, Qt.LeftButton)
    assert not table.isVisible()
    assert dialog.protocol_oddball_marker_code_edit.isEnabled()
    assert dialog._protocol_from_editor(require_ready=True).condition_oddball_marker_codes == ()
    qtbot.mouseClick(dialog.protocol_condition_markers_check, Qt.LeftButton)
    assert table.item(0, 2).text() == "51"


def test_existing_mapping_reopens_by_onset_and_survives_other_protocol_edits(qtbot):
    protocol = _ready_protocol().with_condition_oddball_marker_codes({code: code + 50 for code in range(1, 6)})
    dialog = _dialog(qtbot, protocol)
    assert dialog.protocol_condition_markers_check.isChecked()
    assert dialog.protocol_condition_markers_table.isVisible()
    assert dialog.protocol_condition_markers_table.item(0, 0).text() == "Color Response 1"
    assert dialog.protocol_condition_markers_table.item(0, 2).text() == "51"
    assert dialog._protocol_from_editor(require_ready=True).fingerprint == protocol.fingerprint
    dialog.protocol_expected_cycles_edit.setText("120")
    assert dialog._protocol_from_editor(require_ready=True).condition_oddball_marker_codes == protocol.condition_oddball_marker_codes


def test_recording_schema_dialog_requires_new_recording_assignment_and_preserves_custom_maps(qtbot):
    from Main_App.gui.recording_marker_schemas import RecordingMarkerIdentity
    from Main_App.gui.recording_marker_schemas_dialog import RecordingMarkerSchemasDialog

    protocol = _ready_protocol().with_condition_oddball_marker_codes({1: 51, 2: 52})
    saved = (("P01", ((1, 71), (2, 72))), ("P22", ((1, 55), (2, 55))))
    identities = tuple(RecordingMarkerIdentity(recording, recording) for recording in ("P01", "P22", "P31"))
    dialog = RecordingMarkerSchemasDialog(identities, protocol, (1, 2), saved)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)
    assert not dialog.apply_button.isEnabled()
    assert dialog._selectors[0].currentText() == "Custom saved markers"
    assert dialog._selectors[2].currentData() == "unassigned"
    assert "P31" in dialog.status.text()
    dialog._selectors[2].setCurrentIndex(dialog._selectors[2].findData("project"))
    assert dialog.apply_button.isEnabled()
    assert dialog.marker_codes()[0] == saved[0]
    assert dialog.marker_codes()[2] == ("P31", ((1, 51), (2, 52)))
    dialog._shared_edits[1].setText("66")
    assert dialog.marker_codes()[1] == ("P22", ((1, 66), (2, 66)))
    assert saved[1] == ("P22", ((1, 55), (2, 55)))


def test_recording_schema_bulk_action_is_explicit_and_cancel_keeps_original_drafts(qtbot):
    from Main_App.gui.recording_marker_schemas import RecordingMarkerIdentity
    from Main_App.gui.recording_marker_schemas_dialog import RecordingMarkerSchemasDialog

    protocol = _ready_protocol().with_condition_oddball_marker_codes({1: 51, 2: 52})
    identities = (RecordingMarkerIdentity("P01", "P01"), RecordingMarkerIdentity("P22", "P22"))
    dialog = RecordingMarkerSchemasDialog(identities, protocol, (1, 2), ())
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)
    assert not dialog.apply_button.isEnabled()
    qtbot.mouseClick(dialog.select_all_button, Qt.LeftButton)
    qtbot.mouseClick(dialog.shared_button, Qt.LeftButton)
    assert dialog.apply_button.isEnabled()
    assert dialog.marker_codes() == (("P01", ((1, 55), (2, 55))), ("P22", ((1, 55), (2, 55))))
    qtbot.mouseClick(dialog.cancel_button, Qt.LeftButton)
    assert dialog.result() == QDialog.DialogCode.Rejected
