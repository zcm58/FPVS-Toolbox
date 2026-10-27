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


def _save_dialog(worker_factory):
    source = ROOT / "src/Main_App/gui/pipeline_setup_dialog.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    dialog_class = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "PipelineSetupDialog")
    methods = [node for node in dialog_class.body if isinstance(node, ast.FunctionDef)
               and node.name in {"_save", "_save_finished", "_set_saving"}]
    for method in methods:
        method.decorator_list = []
    namespace = {
        "PIPELINE_SETUP_PAGES": [object()],
        "_PipelineSaveWorker": worker_factory,
        "logger": Mock(),
    }
    exec(compile(ast.Module(body=methods, type_ignores=[]), str(source), "exec"), namespace)
    dialog = SimpleNamespace(
        _current_page=0, _save_worker=None, _can_save=None,
        _collect_all=Mock(), draft=SimpleNamespace(requires_reprocessing=True),
        project=object(), error_banner=Mock(), _error=Mock(), accept=Mock(),
        requires_reprocessing_saved=False,
        **{name: Mock() for name in (
            "navigation", "pages", "cancel_button", "back_button", "next_button", "save_button",
        )},
    )
    for method in methods:
        setattr(dialog, method.name, namespace[method.name].__get__(dialog))
    return dialog


@pytest.mark.parametrize("failure_stage", ["construct", "connect", "start", "native_start"])
def test_pipeline_save_startup_failure_restores_editable_draft_and_allows_retry(failure_stage):
    worker = Mock(error="")
    factory = Mock(return_value=worker)
    failure = RuntimeError("cannot start save worker")
    if failure_stage == "construct":
        factory.side_effect = failure
    elif failure_stage == "connect":
        worker.finished.connect.side_effect = failure
    elif failure_stage == "start":
        worker.start.side_effect = failure
    else:
        failure = RuntimeError("Could not start the pipeline save thread.")
        worker.isRunning.return_value = False
        worker.isFinished.return_value = False
    dialog = _save_dialog(factory)
    original_draft = dialog.draft
    original_project = dialog.project

    dialog._save()

    assert dialog._save_worker is None
    assert dialog.draft is original_draft
    assert dialog.project is original_project
    assert not dialog.requires_reprocessing_saved
    dialog.accept.assert_not_called()
    dialog._error.assert_called_once_with(str(failure))
    assert worker.deleteLater.call_count == int(failure_stage != "construct")
    for name in ("navigation", "pages", "cancel_button", "back_button", "next_button", "save_button"):
        assert [call.args[0] for call in getattr(dialog, name).setEnabled.call_args_list] == [False, True]
    dialog.save_button.setText.assert_called_with("Save pipeline")

    retry_worker = Mock(error="")
    factory.side_effect = None
    factory.return_value = retry_worker
    dialog._save()

    assert dialog._save_worker is retry_worker
    retry_worker.start.assert_called_once()
    dialog.accept.assert_not_called()
    dialog._save_finished()
    assert dialog._save_worker is None
    assert dialog.requires_reprocessing_saved
    retry_worker.deleteLater.assert_called_once()
    dialog.accept.assert_called_once()


@pytest.mark.parametrize("already_finished", [False, True])
def test_pipeline_save_waits_for_finished_delivery_even_when_thread_finishes_quickly(already_finished):
    worker = Mock(error="")
    worker.isRunning.return_value = not already_finished
    worker.isFinished.return_value = already_finished
    dialog = _save_dialog(Mock(return_value=worker))

    dialog._save()

    assert dialog._save_worker is worker
    dialog._error.assert_not_called()
    dialog.accept.assert_not_called()
    worker.deleteLater.assert_not_called()
    dialog.cancel_button.setEnabled.assert_called_once_with(False)

    dialog._save_finished()

    assert dialog._save_worker is None
    assert dialog.requires_reprocessing_saved
    dialog.accept.assert_called_once()
    worker.deleteLater.assert_called_once()
