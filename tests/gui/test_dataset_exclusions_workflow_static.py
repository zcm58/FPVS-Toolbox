"""Exercise exclusion management integration without constructing Qt objects."""

from __future__ import annotations

import ast
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from Main_App.projects import Project


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src/Main_App/gui/dataset_exclusions_workflow.py"


def _function(name, namespace):
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    namespace.update(Path=Path, logger=Mock())
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(SOURCE), "exec"), namespace)
    return namespace[name]


def test_saved_exclusions_cannot_return_on_later_unrelated_settings_save(tmp_path):
    manifest = {"preprocessing": {"manual_excluded_participants": ["P01"]}}
    path = tmp_path / "project.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    project = Project(tmp_path, manifest)
    project.preprocessing["high_pass"] = 0.25
    project.preprocessing["manual_excluded_participant_conditions"] = {"P02": ["Happy"]}
    settings = SimpleNamespace(
        project=project, host=object(),
        _project_cache={**project.preprocessing, "unsaved_editor_value": "keep"},
    )
    # The worker has already saved the explicit dataset choice independently.
    saved = deepcopy(manifest)
    saved["preprocessing"]["manual_excluded_participants"] = []
    path.write_text(json.dumps(saved), encoding="utf-8")
    original_bytes = path.read_bytes()
    snapshot = SimpleNamespace(
        project_root=tmp_path, processing_excluded_participants=(),
        processing_excluded_recordings=(), downstream_outputs_stale=False,
    )
    sync = _function("_sync_saved_exclusions", {})
    sync(settings, snapshot)
    assert path.read_bytes() == original_bytes  # GUI synchronization does no I/O.
    assert settings._manual_excluded_participants == []
    assert settings._project_cache["manual_excluded_participants"] == []
    assert settings._project_cache["unsaved_editor_value"] == "keep"
    project.save()
    after = json.loads(path.read_text(encoding="utf-8"))["preprocessing"]
    assert after["manual_excluded_participants"] == []
    assert after["high_pass"] == 0.25
    assert after["manual_excluded_participant_conditions"] == {"P02": ["Happy"]}


def test_saved_dataset_choices_never_apply_to_a_different_project(tmp_path):
    settings = SimpleNamespace(project=SimpleNamespace(project_root=tmp_path / "other"))
    before = dict(vars(settings.project))
    sync = _function("_sync_saved_exclusions", {})
    sync(settings, SimpleNamespace(project_root=tmp_path / "saved"))
    assert vars(settings.project) == before


@pytest.mark.parametrize("stale", [False, True])
def test_saved_scope_changes_clear_memory_cache_without_discarding_other_settings(tmp_path, stale):
    manifest = {"preprocessing": {}, "tools": {"stats": {
        "group_significant_harmonics_cache": {"entries": {"old": {}}}, "alpha": 0.05,
    }}}
    project = SimpleNamespace(project_root=tmp_path, preprocessing={}, manifest=manifest)
    settings = SimpleNamespace(project=project, host=None, parent=lambda: None)
    snapshot = SimpleNamespace(
        project_root=tmp_path, processing_excluded_participants=(),
        processing_excluded_recordings=(), downstream_outputs_stale=stale,
    )
    clear_memory = Mock()
    sync = _function("_sync_saved_exclusions", {"clear_group_significant_selection_cache": clear_memory})
    sync(settings, snapshot)
    assert clear_memory.call_count == int(stale)
    assert manifest["tools"]["stats"]["alpha"] == 0.05
    assert ("group_significant_harmonics_cache" in manifest["tools"]["stats"]) is not stale


@pytest.mark.parametrize("case", ["no_project", "busy", "no_guard", "guard_denied"])
def test_editor_never_opens_without_idle_project_ownership(case, tmp_path):
    guard = SimpleNamespace(start=Mock(return_value=case != "guard_denied"), end=Mock())
    owner = SimpleNamespace(_start_guard=None if case == "no_guard" else guard)
    settings = SimpleNamespace(
        host=owner, project=None if case == "no_project" else SimpleNamespace(project_root=tmp_path),
    )
    factory = Mock()
    show_info = Mock()
    show = _function("show_dataset_exclusions", {
        "show_info": show_info, "_cache_work_is_active": lambda _owner: case == "busy",
        "DatasetExclusionsDialog": factory,
    })
    show(settings)
    factory.assert_not_called()
    show_info.assert_called_once()
    guard.end.assert_not_called()


@pytest.mark.parametrize("raises", [False, True])
def test_navigation_and_start_guard_release_when_modal_finishes_or_fails(raises, tmp_path):
    guard = SimpleNamespace(start=Mock(return_value=True), end=Mock())
    owner = SimpleNamespace(_start_guard=guard)
    settings = SimpleNamespace(host=owner, project=SimpleNamespace(project_root=tmp_path))
    dialog = SimpleNamespace(
        exclusions_changed=SimpleNamespace(connect=Mock()),
        exec=Mock(side_effect=RuntimeError("dialog failure") if raises else None),
        deleteLater=Mock(),
    )
    factory = Mock(return_value=dialog)
    lock = Mock()
    sync = Mock()
    show = _function("show_dataset_exclusions", {
        "_cache_work_is_active": lambda _owner: False, "show_info": Mock(),
        "DatasetExclusionsDialog": factory, "_set_processing_navigation_locked": lock,
        "_sync_saved_exclusions": sync,
    })
    if raises:
        with pytest.raises(RuntimeError, match="dialog failure"):
            show(settings)
    else:
        show(settings)
    factory.assert_called_once_with(tmp_path, settings)
    assert [call.args for call in lock.call_args_list] == [(owner, True), (owner, False)]
    guard.end.assert_called_once()
    dialog.deleteLater.assert_called_once()
    sync.assert_not_called()  # Closing without a successful save changes no exclusions.
    snapshot = object()
    dialog.exclusions_changed.connect.call_args.args[0](snapshot)
    sync.assert_called_once_with(settings, snapshot)


def test_settings_has_one_participant_exclusion_management_surface():
    source = (ROOT / "src/Main_App/gui/settings_panel.py").read_text(encoding="utf-8")
    assert '"Manage Dataset Exclusions…"' in source
    assert "self._manage_dataset_exclusions" in source
    assert "settings_manual_participant_exclusions_edit" not in source
    assert "settings_clear_frequency_domain_manual_exclusions" not in source
