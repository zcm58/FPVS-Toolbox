"""Exercise guided setup ownership without constructing Qt objects."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src/Main_App/gui/pipeline_setup_workflow.py"


def _workflow(**overrides):
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    namespace = {
        "logger": Mock(), "show_info": Mock(), "show_error": Mock(),
        "QDialog": SimpleNamespace(DialogCode=SimpleNamespace(Accepted=1)),
        "has_condition_changes": Mock(return_value=False),
        "_cache_work_is_active": Mock(return_value=False),
        "_set_processing_navigation_locked": Mock(),
        "_set_resume_post_processing_pending": Mock(),
        "clear_group_significant_selection_cache": Mock(),
        "PipelineSetupDialog": Mock(),
        **overrides,
    }
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(SOURCE), "exec"), namespace)
    return namespace


def _settings():
    project = object()
    owner = SimpleNamespace(
        _start_guard=SimpleNamespace(start=Mock(return_value=True), end=Mock()),
        currentProject=project,
    )
    return SimpleNamespace(
        project=project, host=owner, parent=lambda: owner,
        has_unsaved_changes=Mock(return_value=False), accept=Mock(),
        guided_setup_button=Mock(),
    )


@pytest.mark.parametrize("case", ["no_project", "dirty", "condition_dirty", "busy", "no_guard", "different_project"])
def test_unavailable_setup_does_not_open_or_save(case):
    settings = _settings()
    ns = _workflow()
    if case == "no_project":
        settings.project = None
    elif case == "dirty":
        settings.has_unsaved_changes.return_value = True
    elif case == "condition_dirty":
        ns["has_condition_changes"].return_value = True
    elif case == "busy":
        ns["_cache_work_is_active"].return_value = True
    elif case == "no_guard":
        settings.host._start_guard = None
    else:
        settings.host.currentProject = object()
    ns["show_pipeline_setup"](settings)
    ns["PipelineSetupDialog"].assert_not_called()
    ns["show_info"].assert_called_once()
    settings.accept.assert_not_called()
    ns["refresh_guided_setup_availability"](settings)
    settings.guided_setup_button.setEnabled.assert_called_with(False)
    assert settings.guided_setup_button.setToolTip.call_args.args[0]


def test_denied_guard_does_not_release_another_operation():
    settings = _settings()
    settings.host._start_guard.start.return_value = False
    ns = _workflow()
    ns["show_pipeline_setup"](settings)
    ns["PipelineSetupDialog"].assert_not_called()
    settings.host._start_guard.end.assert_not_called()


@pytest.mark.parametrize("outcome", ["save", "cancel", "error"])
def test_modal_handoff_releases_guard_and_retires_settings_only_after_save(outcome):
    settings = _settings()
    dialog = Mock()
    dialog.requires_reprocessing_saved = False
    dialog.exec.return_value = int(outcome == "save")
    if outcome == "error":
        dialog.exec.side_effect = RuntimeError("cannot create dialog")
    ns = _workflow(PipelineSetupDialog=Mock(return_value=dialog))
    ns["show_pipeline_setup"](settings)
    assert [call.args for call in ns["_set_processing_navigation_locked"].call_args_list] == [
        (settings.host, True), (settings.host, False),
    ]
    settings.host._start_guard.end.assert_called_once()
    dialog.deleteLater.assert_called_once()
    assert settings.accept.call_count == int(outcome == "save")
    assert ns["show_error"].call_count == int(outcome == "error")
    ns["_set_resume_post_processing_pending"].assert_not_called()
    # Save-time checking ignores only this modal's own start guard.
    can_save = ns["PipelineSetupDialog"].call_args.kwargs["can_save"]
    assert can_save() == ""
    ns["_cache_work_is_active"].assert_called_with(settings.host, include_start_guard=False)
    settings.has_unsaved_changes.return_value = True
    assert "Save or cancel" in can_save()


def test_changed_pipeline_save_requires_start_processing_instead_of_resume():
    settings = _settings()
    dialog = Mock(requires_reprocessing_saved=True)
    dialog.exec.return_value = 1
    ns = _workflow(PipelineSetupDialog=Mock(return_value=dialog))
    ns["show_pipeline_setup"](settings)
    ns["_set_resume_post_processing_pending"].assert_called_once_with(settings.host, False)
    ns["clear_group_significant_selection_cache"].assert_called_once()
    settings.accept.assert_called_once()


def test_constructor_failure_releases_guard():
    settings = _settings()
    ns = _workflow(PipelineSetupDialog=Mock(side_effect=ValueError("stale project")))
    ns["show_pipeline_setup"](settings)
    settings.host._start_guard.end.assert_called_once()
    ns["show_error"].assert_called_once()
    settings.accept.assert_not_called()


def test_settings_entry_remains_optional_and_tracks_dirty_state():
    page = (ROOT / "src/Main_App/gui/settings_preprocessing_page.py").read_text(encoding="utf-8")
    feedback = (ROOT / "src/Main_App/gui/settings_feedback.py").read_text(encoding="utf-8")
    panel = ast.parse((ROOT / "src/Main_App/gui/settings_panel.py").read_text(encoding="utf-8"))
    settings_class = next(node for node in panel.body if isinstance(node, ast.ClassDef) and node.name == "SettingsDialog")
    show_event = next(node for node in settings_class.body if isinstance(node, ast.FunctionDef) and node.name == "showEvent")
    assert 'tabs.addTab(tab, "Processing")' in page
    assert 'make_action_button("Guided setup", parent=tab)' in page
    assert "self.guided_setup_button.clicked.connect(self._show_pipeline_setup)" in page
    assert 'getattr(self.panel, "_refresh_guided_setup_availability", None)' in feedback
    assert "self._refresh_guided_setup_availability()" in ast.unparse(show_event)
