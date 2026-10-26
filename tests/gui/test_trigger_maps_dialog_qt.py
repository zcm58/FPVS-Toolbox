"""CI-only source-map editor smoke tests; never launch offscreen Qt locally."""

from __future__ import annotations

from copy import deepcopy

import pytest
from PySide6.QtWidgets import QComboBox, QScrollArea

from Main_App.gui.source_participant_registration import SourceParticipantRegistrationDialog
from Main_App.gui.trigger_maps_dialog import TriggerMapsDialog
from Main_App.projects import FrequencyProtocol, Project


@pytest.fixture
def project(tmp_path):
    value = Project.load(tmp_path)
    value.groups = {"a": {"label": "Adolescents", "output_folder": "Adolescents", "raw_input_folder": tmp_path / "a"},
                    "b": {"label": "Adults", "output_folder": "Adults", "raw_input_folder": tmp_path / "b"}}
    value.participants = {"ACRP1": {"group_id": "a", "raw_file": "a/p1.bdf"}, "MCCTRP1": {"group_id": "b", "raw_file": "b/p1.bdf"}}
    maps = {"schema_version": "1.0", "canonical_conditions": {"angry": {"label": "Angry"}},
            "profiles": {"acr": {"label": "ACR", "conditions": {"angry": {"onset_code": 11, "oddball_code": 55}}, "boundary_only_onset_codes": [12]},
                         "adult": {"label": "MCCTR", "conditions": {"angry": {"onset_code": 12, "oddball_code": 55}}, "boundary_only_onset_codes": [3]}},
            "recording_assignments": {"ACRP1": "acr", "MCCTRP1": "adult"},
            "registration_group_defaults": {"a": "acr", "b": "adult"}}
    protocol = FrequencyProtocol.from_recurrence(6, 5, expected_analyzed_oddball_cycles=144, expected_analyzed_oddball_cycles_source="manual")
    value.update_frequency_protocol(protocol.with_condition_trigger_maps(maps))
    value.save()
    return value


def test_mapped_mode_is_one_way_and_cancel_is_detached(qtbot, project):
    original = project.manifest_path.read_bytes()
    dialog = TriggerMapsDialog(project, apply_to_settings=True)
    qtbot.addWidget(dialog)
    assert dialog.mode.text() == "Source maps"
    assert not isinstance(dialog.mode, QComboBox)
    assert dialog.apply_button.text() == "Apply to Settings"
    assert not dialog.findChildren(QScrollArea)
    dialog.conditions.item(0, 2).setText("19")
    assert dialog.maps().resolve("ACRP1").event_map == {"Angry": 19}
    dialog.reject()
    assert project.manifest_path.read_bytes() == original


def test_missing_assignment_or_local_marker_collision_blocks_apply(qtbot, project):
    dialog = TriggerMapsDialog(project)
    qtbot.addWidget(dialog)
    dialog.conditions.item(0, 2).setText("55")
    assert not dialog.apply_button.isEnabled()
    dialog.conditions.item(0, 2).setText("11")
    assert dialog.apply_button.isEnabled()
    dialog._assignment_combos[0].setCurrentIndex(0)
    assert not dialog.apply_button.isEnabled()


def test_group_default_never_reassigns_existing_recordings(qtbot, project):
    dialog = TriggerMapsDialog(project)
    qtbot.addWidget(dialog)
    before = deepcopy(dialog.payload["recording_assignments"])
    dialog._set_default("b", "acr")
    assert dialog.payload["recording_assignments"] == before
    assert dict(dialog.maps().registration_group_defaults)["b"] == "acr"


def test_source_registration_separates_p1_and_preserves_existing_id(qtbot):
    dialog = SourceParticipantRegistrationDialog([
        {"raw_file": "a/p1.bdf", "source_study_id": "acr", "source_participant_id": "P1", "group_id": "a"},
        {"raw_file": "b/p1.bdf", "source_study_id": "mcctr", "source_participant_id": "P1", "group_id": "b"},
        {"raw_file": "b/p2.bdf", "source_study_id": None, "source_participant_id": None, "participant_id": "ExistingP2", "existing": True},
    ])
    qtbot.addWidget(dialog)
    assert [row["participant_id"] for row in dialog.registrations()] == ["ACRP1", "MCCTRP1", "ExistingP2"]
    dialog.table.item(1, 0).setText("acr_p1")
    assert not dialog.apply_button.isEnabled()
    dialog.table.item(1, 0).setText("CON")
    assert not dialog.apply_button.isEnabled()


def test_new_source_participant_needs_explicit_saved_profile(qtbot, project):
    from Main_App.projects.source_registration import prepare_source_registration_review
    maps = project.frequency_protocol.condition_trigger_maps.to_manifest()
    maps["registration_group_defaults"] = {}
    project.update_frequency_protocol(project.frequency_protocol.with_condition_trigger_maps(maps))
    project.save()
    for group in project.groups.values():
        folder = group["raw_input_folder"]
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "p1.bdf").write_bytes(b"registered")
        (folder / "p2.bdf").write_bytes(b"new")
    review = prepare_source_registration_review(project)
    dialog = SourceParticipantRegistrationDialog(review.editor_rows(), project=project, review=review)
    qtbot.addWidget(dialog)
    assert not dialog.apply_button.isEnabled()
    for selector in dialog._map_selectors.values():
        selector.setCurrentIndex(selector.findData("acr"))
    assert dialog.apply_button.isEnabled()
    assert len(dialog.trigger_map_assignments()) == 2


def test_source_registration_io_runs_outside_gui_thread_and_reports_failure(qtbot):
    import threading
    from PySide6.QtWidgets import QWidget
    from Main_App.projects.project_manager import _run_source_registration_work

    parent = QWidget()
    qtbot.addWidget(parent)
    gui_thread = threading.get_ident()
    worker_thread = _run_source_registration_work(parent, threading.get_ident, "Checking source participants…")
    assert worker_thread != gui_thread

    def failing_operation():
        raise ValueError("Changed manifest")

    with pytest.raises(RuntimeError, match="Changed manifest"):
        _run_source_registration_work(parent, failing_operation, "Checking source participants…")


def test_source_exclusion_labels_preserve_canonical_selection(qtbot, project):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QWidget
    from Main_App.gui.manual_participant_exclusions_dialog import ManualParticipantExclusionsDialog

    project.source_studies = {"acr": {"label": "ACR"}, "mcctr": {"label": "MCCTR"}}
    for participant_id, source in (("ACRP1", "acr"), ("MCCTRP1", "mcctr")):
        project.participants[participant_id].update(source_study_id=source, source_participant_id="P1")
    parent = QWidget()
    parent.currentProject = project
    qtbot.addWidget(parent)
    dialog = ManualParticipantExclusionsDialog(["ACRP1", "MCCTRP1"], parent=parent)
    qtbot.addWidget(dialog)
    assert "ACR / P1" in dialog.table.item(0, 0).text()
    assert "MCCTR / P1" in dialog.table.item(1, 0).text()
    dialog.table.item(0, 1).setCheckState(Qt.Checked)
    assert dialog.excluded_participants() == ["ACRP1"]
