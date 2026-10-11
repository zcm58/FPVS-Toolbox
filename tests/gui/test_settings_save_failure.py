"""Run the Settings save transaction with real project persistence and no Qt."""

from __future__ import annotations

import ast
import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from Main_App.Shared.settings_manager import SettingsManager
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
    }
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    owner = next(node for node in tree.body
                 if isinstance(node, ast.ClassDef) and node.name == "SettingsDialog")
    namespace = {"copy": copy, "json": json, "config": SimpleNamespace(DEFAULT_STIM_CHANNEL="Status"),
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
