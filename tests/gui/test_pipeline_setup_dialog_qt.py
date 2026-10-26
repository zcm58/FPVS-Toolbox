"""CI-only guided processing workflow checks; do not execute Qt locally."""
from __future__ import annotations

from copy import deepcopy
from threading import Event

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QDialog, QScrollArea

from Main_App.gui import pipeline_setup_dialog as setup_gui
from Main_App.projects import ExperimentalQcSettings, FrequencyProtocol
from Main_App.projects.hardware import confirm_hardware_selection
from Main_App.projects.pipeline_setup import PIPELINE_SETUP_PAGES
from Main_App.projects.project import Project


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("FPVS_CONFIG_HOME", str(tmp_path / "config"))
    root = tmp_path / "project"
    root.mkdir()
    value = Project.load(root)
    value.update_frequency_protocol(FrequencyProtocol.from_recurrence(
        "6", 5, expected_analyzed_oddball_cycles=144,
        expected_analyzed_oddball_cycles_source="manual", oddball_marker_code=55,
        oddball_marker_code_source="manual",
    ))
    value.confirm_removed_electrode_detection_choice("off")
    value.update_experimental_qc_settings(ExperimentalQcSettings.for_new_project())
    value.save()
    return value


def _dialog(qtbot, project, **kwargs):
    dialog = setup_gui.PipelineSetupDialog(project, **kwargs)
    qtbot.addWidget(dialog)
    return dialog


def test_cancel_discards_parameter_and_hardware_drafts(qtbot, project, monkeypatch):
    original = project.manifest_path.read_bytes()
    settings = deepcopy(project.preprocessing)
    dialog = _dialog(qtbot, project)
    monkeypatch.setattr(setup_gui, "confirm_hardware_change", lambda *_: True)
    dialog.hardware_combo.setCurrentIndex(dialog.hardware_combo.findData("brain_products"))
    dialog._choose_hardware()
    dialog._fields["high_pass"].setText("0.5")
    dialog.reject()
    assert dialog.result() == QDialog.Rejected
    assert project.preprocessing == settings
    assert project.manifest_path.read_bytes() == original


def test_next_rejects_invalid_filter_without_writing(qtbot, project):
    original = project.manifest_path.read_bytes()
    dialog = _dialog(qtbot, project)
    dialog._navigate(2)
    dialog._fields["high_pass"].setText("80")
    dialog._fields["low_pass"].setText("50")
    qtbot.mouseClick(dialog.next_button, Qt.LeftButton)
    assert dialog.pages.currentIndex() == 2
    assert not dialog.error_banner.isHidden()
    assert project.manifest_path.read_bytes() == original


def test_review_save_persists_once_and_reopens(qtbot, project, monkeypatch):
    dialog = _dialog(qtbot, project)
    original = project.manifest_path.read_bytes()
    calls = []
    save = dialog.draft.save
    monkeypatch.setattr(dialog.draft, "save", lambda value: calls.append(value) or save(value))
    dialog._navigate(2)
    dialog._fields["low_pass"].setText("40")
    dialog._navigate(6)
    assert dialog.pages.currentIndex() == 6
    assert dialog.review_table.rowCount() >= 19
    assert dialog.changes_table.rowCount() > 0
    assert not dialog.review_notice.isHidden()
    assert project.manifest_path.read_bytes() == original
    dialog._save()
    qtbot.waitUntil(lambda: dialog._save_worker is None)
    assert dialog.result() == QDialog.Accepted
    assert len(calls) == 1
    assert dialog.requires_reprocessing_saved
    assert Project.load(project.project_root).preprocessing["low_pass"] == 40


def test_hardware_change_cancel_restores_previous_controls(qtbot, project, monkeypatch):
    dialog = _dialog(qtbot, project)
    monkeypatch.setattr(setup_gui, "confirm_hardware_change", lambda *_: False)
    dialog.hardware_combo.setCurrentIndex(dialog.hardware_combo.findData("unicorn"))
    dialog._choose_hardware()
    assert dialog.hardware_combo.currentData() == "biosemi"
    assert dialog._fields["downsample"].isEnabled()
    assert dialog._fields["max_chan_idx_keep"].isEnabled()


def test_unicorn_locks_native_grid_and_disables_repairs(qtbot, project):
    project.update_preprocessing(confirm_hardware_selection(project.preprocessing, "unicorn", confirmed_change=True))
    project.save()
    dialog = _dialog(qtbot, project)
    assert dialog._fields["downsample"].text() == "250"
    assert dialog._fields["max_chan_idx_keep"].text() == "8"
    for key in ("downsample", "max_chan_idx_keep", "electrode_montage",
                "kurtosis_screening_enabled", "raw_signal_screening_enabled",
                "manual_removed_electrodes_enabled", "removed_electrode_detection_mode"):
        assert not dialog._fields[key].isEnabled()
    assert dialog._fields["electrode_mapping_profile"].isEnabled()
    assert not dialog._forms["reference"].isRowVisible(dialog._fields["initial_reference"])


def test_save_error_preserves_draft_and_project(qtbot, project, monkeypatch):
    original = project.manifest_path.read_bytes()
    dialog = _dialog(qtbot, project)
    dialog._fields["low_pass"].setText("40")
    dialog._navigate(6)
    def fail(_):
        raise PermissionError("Project is read-only")
    monkeypatch.setattr(dialog.draft, "save", fail)
    dialog._save()
    qtbot.waitUntil(lambda: dialog._save_worker is None)
    assert "read-only" in dialog.error_banner.text()
    assert dialog._fields["low_pass"].text() == "40"
    assert dialog.save_button.isEnabled()
    assert dialog.result() != QDialog.Accepted
    assert project.manifest_path.read_bytes() == original


def test_active_run_guard_prevents_save_worker(qtbot, project):
    original = project.manifest_path.read_bytes()
    dialog = _dialog(qtbot, project, can_save=lambda: "Wait for processing to finish.")
    dialog._navigate(6)
    dialog._save()
    assert dialog._save_worker is None
    assert "processing" in dialog.error_banner.text()
    assert project.manifest_path.read_bytes() == original


def test_save_worker_keeps_event_loop_responsive_and_blocks_cancel(qtbot, project, monkeypatch):
    dialog = _dialog(qtbot, project)
    dialog._navigate(6)
    started, release = Event(), Event()
    def slow_save(_):
        started.set()
        assert release.wait(5)
    monkeypatch.setattr(dialog.draft, "save", slow_save)
    dialog._save()
    try:
        qtbot.waitUntil(started.is_set)
        assert not dialog.navigation.isEnabled()
        assert not dialog.cancel_button.isEnabled()
        dialog.reject()
        assert dialog._save_worker is not None
    finally:
        release.set()
        qtbot.waitUntil(lambda: dialog._save_worker is None)
    assert dialog.result() == QDialog.Accepted


def test_compact_pages_expose_current_methods_without_single_option_selectors(qtbot, project):
    dialog = _dialog(qtbot, project)
    dialog.show()
    qtbot.waitExposed(dialog)
    assert dialog.width() <= 1100 and dialog.height() <= 780
    assert not dialog.findChildren(QScrollArea)
    assert dialog.pages.count() == 7
    assert len(PIPELINE_SETUP_PAGES) == 7
    assert sum(table.rowCount() for table in dialog._method_tables.values()) == 19
    assert all(control.count() > 1 for control in dialog.findChildren(QComboBox))
    for index in range(dialog.pages.count()):
        dialog._navigate(index)
        assert dialog.pages.currentWidget().height() <= dialog.pages.height()


def test_unchanged_protocol_and_detector_source_are_preserved(qtbot, project):
    original = project.manifest_path.read_bytes()
    dialog = _dialog(qtbot, project)
    protocol = project.frequency_protocol.to_manifest()
    source = project.preprocessing["removed_electrode_detection_choice_source"]
    dialog._navigate(6)
    assert dialog.draft.frequency_protocol.to_manifest() == protocol
    assert dialog.draft.preprocessing["removed_electrode_detection_choice_source"] == source
    assert dialog.draft.review_changes() == ()
    assert not dialog.draft.requires_reprocessing
    assert dialog.review_notice.isHidden()
    dialog._save()
    qtbot.waitUntil(lambda: dialog._save_worker is None)
    assert dialog.result() == QDialog.Accepted
    assert not dialog.requires_reprocessing_saved
    assert project.manifest_path.read_bytes() == original


@pytest.mark.parametrize("platform", ("biosemi", "biosemi_active_three", "brain_products", "unicorn"))
def test_all_hardware_profiles_can_review_without_false_changes(qtbot, project, platform):
    project.update_preprocessing(confirm_hardware_selection(project.preprocessing, platform, confirmed_change=True))
    project.save()
    dialog = _dialog(qtbot, project)
    dialog._navigate(6)
    assert dialog.pages.currentIndex() == 6
    assert dialog.error_banner.isHidden()
    assert dialog.draft.review_changes() == ()
    assert not dialog.draft.requires_reprocessing
    expected_limit = "" if platform in {"brain_products", "biosemi_active_three"} else "8" if platform == "unicorn" else "64"
    assert dialog._fields["max_chan_idx_keep"].text() == expected_limit
    policy = dialog.draft.control_policy
    assert dialog._fields["max_chan_idx_keep"].isEnabled() == policy.channel_limit_editable
    assert dialog._fields["electrode_montage"].isEnabled() == policy.montage_editable
    assert dialog._fields["electrode_mapping_profile"].isEnabled() == policy.mapping_editable


def test_condition_marker_overrides_survive_guided_protocol_edit(qtbot, project):
    project.event_map = {"Faces": 1, "Objects": 2}
    project.update_frequency_protocol(project.frequency_protocol.with_condition_oddball_marker_codes({1: 55, 2: 56}))
    project.save()
    dialog = _dialog(qtbot, project)
    dialog._fields["expected_analyzed_oddball_cycles"].setText("72")
    dialog._navigate(6)
    assert dialog.pages.currentIndex() == 6
    assert dialog.draft.frequency_protocol.condition_oddball_marker_codes == project.frequency_protocol.condition_oddball_marker_codes
    assert dialog.draft.frequency_protocol.expected_analyzed_oddball_cycles == 72


def test_back_allows_correction_elsewhere_and_keeps_unfinished_text(qtbot, project, monkeypatch):
    dialog = _dialog(qtbot, project)
    dialog._navigate(5)
    dialog._fields["presentation_rate_hz"].setText("unfinished")
    dialog._navigate(0)
    assert dialog.pages.currentIndex() == 0
    monkeypatch.setattr(setup_gui, "confirm_hardware_change", lambda *_: True)
    dialog.hardware_combo.setCurrentIndex(dialog.hardware_combo.findData("brain_products"))
    dialog._choose_hardware()
    assert dialog._fields["presentation_rate_hz"].text() == "unfinished"
    dialog._navigate(6)
    assert dialog.pages.currentIndex() == 5
    assert not dialog.error_banner.isHidden()


def test_unconfirmed_hardware_is_confirmed_by_recording_next(qtbot, project):
    settings = confirm_hardware_selection(project.preprocessing, "unicorn", confirmed_change=True)
    settings["hardware_confirmed"] = False
    project.update_preprocessing(settings)
    project.save()
    original = project.manifest_path.read_bytes()
    dialog = _dialog(qtbot, project)
    dialog._navigate(1)
    assert dialog.pages.currentIndex() == 1
    assert dialog.draft.preprocessing["hardware_confirmed"]
    assert not project.preprocessing["hardware_confirmed"]
    assert project.manifest_path.read_bytes() == original
