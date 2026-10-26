"""Run the Settings save transaction with real project persistence and no Qt."""

from __future__ import annotations

import ast
import copy
import json
import logging
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from Main_App.settings.settings_manager import SettingsManager
from Main_App.processing.frequency_domain_qc import is_frequency_domain_output_stale
from Main_App.projects import FrequencyProtocol
from Main_App.projects import project as project_module
from Main_App.projects.project import Project
from Main_App.projects.preprocessing_settings import (
    PREPROCESSING_DEFAULTS, new_project_preprocessing_settings,
)


SOURCE = Path(__file__).resolve().parents[2] / "src/Main_App/gui/settings_panel.py"


def _panel(tmp_path):
    project = Project.load(tmp_path / "project", manifest={
        "preprocessing": new_project_preprocessing_settings(),
    })
    project.save()
    manager = SettingsManager(str(tmp_path / "settings.ini"))
    manager.save()
    methods = {
        "_save", "_restore_failed_project_settings_save",
        "_capture_harmonic_settings_rollback", "_clear_harmonic_settings_rollback",
        "_experimental_qc_changes_after_processing", "_mark_frequency_analysis_outputs_stale",
        "_trigger_protocol_is_current", "_save_project_with_trigger_guard",
    }
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    owner = next(node for node in tree.body
                 if isinstance(node, ast.ClassDef) and node.name == "SettingsDialog")
    namespace = {"copy": copy, "json": json, "logger": logging.getLogger(__name__),
                 "config": SimpleNamespace(DEFAULT_STIM_CHANNEL="Status"),
                 "PREPROCESSING_DEFAULTS": PREPROCESSING_DEFAULTS,
                 "QMessageBox": SimpleNamespace(
        warning=Mock(), critical=Mock(), information=Mock(),
    )}
    module = ast.Module(body=[ast.ImportFrom(
        module="__future__", names=[ast.alias(name="annotations")], level=0,
    ), *(node for node in owner.body if getattr(node, "name", None) in methods)],
        type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(SOURCE), "exec"), namespace)
    payload = dict(project.preprocessing, low_pass=45.0)
    panel = SimpleNamespace(
        project=project, manager=manager, _project_cache=dict(project.preprocessing),
        _trigger_protocol_baseline=(project.frequency_protocol.to_manifest(), copy.deepcopy(project.event_map)),
        _trigger_maps_payload=None, _initial_trigger_maps_payload=None,
        _show_settings_validation=Mock(),
        alpha_edit=SimpleNamespace(text=lambda: "0.025"),
        roi_editor=SimpleNamespace(get_pairs=lambda: [("Audit", ["O1"]) ]),
        preproc_edits=[],
        debug_check=SimpleNamespace(isChecked=lambda: False),
        beta_tools_check=SimpleNamespace(isChecked=lambda: False),
        _manual_excluded_participant_conditions={},
        _manual_excluded_recording_conditions={},
        _full_fft_grid_review_is_running=lambda: False,
        _harmonic_recalculation_is_running=lambda: False,
        _protocol_save_requested=lambda: True,
        _validated_project_protocol=lambda: FrequencyProtocol.from_recurrence(
            "6", 5, expected_analyzed_oddball_cycles=144,
            expected_analyzed_oddball_cycles_source="manual",
        ),
        _validated_experimental_qc_settings=lambda: project.experimental_qc_settings,
        _validated_preproc_payload=lambda: payload,
        _validate_roi_draft=lambda: True,
        _confirm_parallel_worker_override=lambda _payload: True,
        _harmonic_settings_changed_after_processing=lambda _payload: False,
        _frequency_analysis_settings_changed_after_processing=lambda: False,
        _project_protocol_changed_after_processing=lambda: False,
        _project_has_processed_outputs=lambda: True,
        _ask_recalculate_harmonics_after_settings_change=lambda: True,
        _current_roi_montage=lambda: "biosemi64",
        _removed_electrode_choice_should_be_confirmed=lambda: True,
        _removed_electrode_detection_mode=lambda: "off",
        _sync_electrode_geometry_controls=Mock(),
        _refresh_roi_consumers=Mock(), _mark_harmonic_derivatives_stale=Mock(),
        accept=Mock(),
    )
    for name in methods:
        setattr(panel, name, namespace[name].__get__(panel))
    return panel, namespace["QMessageBox"]


def test_stale_settings_cannot_overwrite_protocol_saved_elsewhere(tmp_path):
    panel, _messages = _panel(tmp_path)
    other = Project.load(panel.project.project_root)
    other.update_frequency_protocol(FrequencyProtocol.from_recurrence(
        6, 5, expected_analyzed_oddball_cycles=120,
        expected_analyzed_oddball_cycles_source="manual",
    ))
    other.save()
    saved = other.manifest_path.read_bytes()
    panel._save()
    assert panel.project.manifest_path.read_bytes() == saved
    panel.accept.assert_not_called()
    assert "Reopen Settings" in panel._show_settings_validation.call_args.args[0]


def test_settings_map_conversion_retires_legacy_map_only_when_saved(tmp_path):
    from Main_App.projects import migrate_legacy_trigger_maps

    panel, _messages = _panel(tmp_path)
    project = panel.project
    project.event_map = {"Angry": 11}
    project.participants = {"P1": {"raw_file": project.input_folder / "p1.bdf"}}
    project.update_frequency_protocol(panel._validated_project_protocol())
    project.save()
    panel._trigger_protocol_baseline = (project.frequency_protocol.to_manifest(), copy.deepcopy(project.event_map))
    before = project.manifest_path.read_bytes()
    maps = migrate_legacy_trigger_maps(project)
    mapped_protocol = project.frequency_protocol.with_condition_trigger_maps(maps)
    panel._trigger_maps_payload = maps.to_manifest()
    panel._validated_project_protocol = lambda: mapped_protocol
    assert project.manifest_path.read_bytes() == before
    assert project.event_map == {"Angry": 11}
    panel._save()
    reopened = Project.load(project.project_root)
    assert reopened.event_map == {}
    assert reopened.frequency_protocol.condition_trigger_maps == maps
    assert reopened.manifest["tools"]["trigger_map_migration"]["legacy_event_map"] == {"Angry": 11}


@pytest.mark.parametrize("error_type", [OSError, ValueError])
@pytest.mark.parametrize("recalculate", [False, True])
def test_failed_project_save_restores_live_state_without_retry(
    tmp_path, monkeypatch, error_type, recalculate,
):
    panel, messages = _panel(tmp_path)
    panel._harmonic_settings_changed_after_processing = lambda _payload: recalculate
    project = panel.project
    previous_project = copy.deepcopy(vars(project))
    previous_config = copy.deepcopy(panel.manager.config)
    previous_cache = copy.deepcopy(panel._project_cache)
    manifest_path = project.project_root / "project.json"
    previous_bytes = manifest_path.read_bytes()
    ini_bytes = Path(panel.manager.ini_path).read_bytes()
    write = Mock(side_effect=error_type("Synthetic persistence failure"))
    with monkeypatch.context() as failure:
        failure.setattr(project_module, "_write_manifest_if_changed", write)
        panel._save()

    assert vars(project) == previous_project
    assert panel.manager.config == previous_config
    assert panel._project_cache == previous_cache
    assert manifest_path.read_bytes() == previous_bytes
    assert Path(panel.manager.ini_path).read_bytes() == ini_bytes
    assert write.call_count == 1
    assert not hasattr(panel, "_harmonic_settings_rollback")
    panel.accept.assert_not_called()
    panel._sync_electrode_geometry_controls.assert_not_called()
    panel._refresh_roi_consumers.assert_not_called()
    message = messages.warning if error_type is ValueError else messages.critical
    assert message.call_args.args[1] == (
        "Invalid Settings" if error_type is ValueError else "Save Error"
    )

    # A subsequent successful save must still commit the same retained draft.
    panel._harmonic_settings_changed_after_processing = lambda _payload: False
    panel._save()
    assert Project.load(project.project_root).preprocessing["low_pass"] == 45.0
    assert project.frequency_protocol.is_ready
    assert panel.manager.get("analysis", "alpha") == "0.025"
    panel.accept.assert_called_once()


@pytest.mark.parametrize("changed_setting", [
    "raw_signal_screening_enabled", "interpolation_burden_review_enabled",
])
def test_failed_application_save_marks_committed_qc_changes_stale(
    tmp_path, monkeypatch, changed_setting,
):
    panel, messages = _panel(tmp_path)
    previous_config = copy.deepcopy(panel.manager.config)
    settings = panel.project.experimental_qc_settings
    changed = replace(settings, **{changed_setting: not getattr(settings, changed_setting)})
    panel._validated_experimental_qc_settings = lambda: changed
    monkeypatch.setattr(
        panel.manager, "save", Mock(side_effect=OSError("Synthetic application write failure")),
    )
    assert not is_frequency_domain_output_stale(panel.project.project_root)

    panel._save()

    committed = Project.load(panel.project.project_root)
    assert committed.experimental_qc_settings == changed
    assert panel.manager.config == previous_config
    assert is_frequency_domain_output_stale(panel.project.project_root)
    assert "Synthetic application write failure" in messages.critical.call_args.args[2]
    panel.accept.assert_not_called()


@pytest.mark.parametrize("protocol_changed", [False, True])
def test_failed_application_save_invalidates_only_committed_frequency_inputs(
    tmp_path, monkeypatch, protocol_changed,
):
    panel, messages = _panel(tmp_path)
    previous_config = copy.deepcopy(panel.manager.config)
    previous_protocol = panel.project.frequency_protocol
    panel._validated_preproc_payload = lambda: dict(panel.project.preprocessing)
    panel._protocol_save_requested = lambda: protocol_changed
    panel._project_protocol_changed_after_processing = lambda: protocol_changed
    # The ROI draft changes the frequency signature, but remains application
    # state and must be rolled back when its settings file cannot be written.
    assert panel.roi_editor.get_pairs() != panel.manager.get_roi_pairs()
    panel._frequency_analysis_settings_changed_after_processing = lambda: True
    monkeypatch.setattr(
        panel.manager, "save", Mock(side_effect=OSError("Synthetic application write failure")),
    )
    assert not is_frequency_domain_output_stale(panel.project.project_root)

    panel._save()

    assert panel.manager.config == previous_config
    committed = Project.load(panel.project.project_root)
    assert (committed.frequency_protocol != previous_protocol) is protocol_changed
    assert is_frequency_domain_output_stale(panel.project.project_root) is protocol_changed
    assert "Synthetic application write failure" in messages.critical.call_args.args[2]
    panel.accept.assert_not_called()


@pytest.mark.parametrize("using_project", [False, True])
@pytest.mark.parametrize("recalculate", [False, True])
def test_failed_application_save_restores_config_and_retains_committed_project(
    tmp_path, monkeypatch, using_project, recalculate,
):
    panel, messages = _panel(tmp_path)
    project = panel.project
    if not using_project:
        panel.project = None
        panel._protocol_save_requested = lambda: False
    panel._harmonic_settings_changed_after_processing = lambda _payload: (
        using_project and recalculate
    )
    previous_config = copy.deepcopy(panel.manager.config)
    ini_bytes = Path(panel.manager.ini_path).read_bytes()
    save = Mock(side_effect=OSError("Synthetic application write failure"))
    with monkeypatch.context() as failure:
        failure.setattr(panel.manager, "save", save)
        panel._save()

    assert panel.manager.config == previous_config
    assert Path(panel.manager.ini_path).read_bytes() == ini_bytes
    assert save.call_count == 1
    assert not hasattr(panel, "_harmonic_settings_rollback")
    panel.accept.assert_not_called()
    panel._refresh_roi_consumers.assert_not_called()
    assert messages.critical.call_args.args[1] == "Save Error"
    if using_project:
        committed = Project.load(project.project_root)
        assert project.preprocessing == committed.preprocessing
        assert panel._project_cache == committed.preprocessing
        assert project.preprocessing["low_pass"] == 45.0
        assert project.frequency_protocol.is_ready
        assert "project settings were saved" in messages.critical.call_args.args[2]
        if recalculate:
            panel._mark_harmonic_derivatives_stale.assert_called_once()

    panel._harmonic_settings_changed_after_processing = lambda _payload: False
    panel._save()
    assert panel.manager.get("analysis", "alpha") == "0.025"
    panel.accept.assert_called_once()
