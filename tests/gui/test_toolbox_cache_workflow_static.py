"""Execute cache workflow control logic without importing or starting Qt."""

from __future__ import annotations

import ast
from copy import deepcopy
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / "src/Main_App/gui/toolbox_cache_workflow.py"
WORKER = ROOT / "src/Main_App/workers/toolbox_cache_worker.py"


def _load_function(path, name, namespace, *, class_name=None):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    body = tree.body
    if class_name:
        body = next(node for node in body if isinstance(node, ast.ClassDef) and node.name == class_name).body
    node = next(node for node in body if isinstance(node, ast.FunctionDef) and node.name == name)
    node.decorator_list = []
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), namespace)
    return namespace[name]


def _owner(**values):
    return SimpleNamespace(findChildren=lambda _kind: [], **values)


@pytest.mark.parametrize(
    "case", ["idle", "run", "guard", "global_pool", "child_thread", "tool_thread",
             "tool_generation", "tool_pool", "invalid_page", "deleted_thread"],
)
def test_busy_guard_covers_processing_tools_threads_and_uncertain_ownership(case):
    owner = _owner(_run_active=case == "run")
    pool = SimpleNamespace(activeThreadCount=lambda: int(case == "global_pool"))
    if case == "child_thread":
        owner.findChildren = lambda _kind: [SimpleNamespace(isRunning=lambda: True)]
    if case.startswith("tool_"):
        page = _owner()
        owner._stats_page = page
        if case == "tool_thread":
            page.worker_thread = SimpleNamespace(isRunning=lambda: True)
        elif case == "tool_generation":
            page.has_active_generation = lambda: True
        else:
            page.pool = SimpleNamespace(activeThreadCount=lambda: 1)
    if case == "invalid_page":
        owner._stats_page = object()
    if case == "deleted_thread":
        owner.worker = SimpleNamespace(isRunning=Mock(side_effect=RuntimeError("deleted")))
    function = _load_function(WORKFLOW, "_cache_work_is_active", {
        "QThread": object,
        "QThreadPool": SimpleNamespace(globalInstance=lambda: pool),
        "_processing_cache_reset_is_busy": lambda _owner: case == "guard",
    })
    assert function(owner) is (case != "idle")
    if case == "guard":
        assert function(owner, include_start_guard=False) is False


@pytest.mark.parametrize("active_cleared", [False, True])
def test_manifest_refresh_preserves_all_unsaved_noncache_state(tmp_path, active_cleared):
    manifest = {
        "name": "Unsaved project name",
        "tools": {"stats": {"group_significant_harmonics_cache": {"cache": 1}, "roi": "unsaved"},
                  "plot": {"color": "unsaved"}},
    }
    original = deepcopy(manifest)
    project = SimpleNamespace(project_root=tmp_path / "active", manifest=manifest)
    refresh = _load_function(WORKFLOW, "_refresh_active_manifest_cache", {"Path": Path})
    refresh(project, [project.project_root if active_cleared else tmp_path / "other"])
    if active_cleared:
        original["tools"]["stats"].pop("group_significant_harmonics_cache")
    assert manifest == original


@pytest.mark.parametrize("clearing", [False, True])
@pytest.mark.parametrize("fails", [False, True])
def test_worker_uses_only_service_and_always_releases_thread(clearing, fails, tmp_path):
    result = object()
    service = Mock(side_effect=OSError("unavailable") if fails else None, return_value=result)
    inspect = service if not clearing else Mock()
    clear = service if clearing else Mock()
    inventory = object() if clearing else None
    worker = SimpleNamespace(
        inventory=inventory, active_project_root=tmp_path / "active",
        projects_root=tmp_path, cancel_requested=Event(),
        finished=SimpleNamespace(emit=Mock()), failed=SimpleNamespace(emit=Mock()),
        done=SimpleNamespace(emit=Mock()),
    )
    run = _load_function(WORKER, "run", {
        "inspect_toolbox_caches": inspect, "clear_toolbox_caches": clear,
        "logger": SimpleNamespace(exception=Mock()),
    }, class_name="ToolboxCacheWorker")
    run(worker)
    worker.done.emit.assert_called_once_with()
    if clearing:
        inspect.assert_not_called()
        assert service.call_args.args == (inventory,)
    else:
        clear.assert_not_called()
        assert service.call_args.kwargs["active_project_root"] == worker.active_project_root
        assert service.call_args.kwargs["projects_root"] == tmp_path
    cancelled = service.call_args.kwargs["should_cancel"]
    assert cancelled() is False
    worker.cancel_requested.set()
    assert cancelled() is True
    if fails:
        worker.finished.emit.assert_not_called()
        worker.failed.emit.assert_called_once_with("unavailable")
    else:
        worker.finished.emit.assert_called_once_with(result)
        worker.failed.emit.assert_not_called()


@pytest.mark.parametrize("busy", [False, True])
def test_clear_rechecks_running_work_before_service_start(busy):
    owner = object()
    dialog = SimpleNamespace(
        owner=owner, thread=None, inventory=object(), _clearing=False,
        status=SimpleNamespace(set_text=Mock(), set_variant=Mock()),
        clear_button=SimpleNamespace(setEnabled=Mock()),
        close_button=SimpleNamespace(setText=Mock()), _start_worker=Mock(),
    )
    guard = Mock(return_value=busy)
    clear = _load_function(WORKFLOW, "_clear", {"_cache_work_is_active": guard}, class_name="ToolboxCacheDialog")
    clear(dialog)
    guard.assert_called_once_with(owner, include_start_guard=False)
    assert dialog._start_worker.call_count == (0 if busy else 1)
    assert dialog._clearing is (not busy)


@pytest.mark.parametrize("raises", [False, True])
def test_modal_workflow_releases_navigation_and_start_guard(raises, tmp_path):
    guard = SimpleNamespace(start=Mock(return_value=True), end=Mock())
    owner = _owner(_start_guard=guard)
    settings = SimpleNamespace(host=owner, project=object(), manager=SimpleNamespace(get_project_root=lambda: str(tmp_path)))
    dialog = SimpleNamespace(begin=Mock(), exec=Mock(side_effect=RuntimeError("dialog") if raises else None), deleteLater=Mock())
    factory = Mock(return_value=dialog)
    locked = Mock()
    show = _load_function(WORKFLOW, "show_toolbox_cache_clear", {
        "Path": Path, "_cache_work_is_active": lambda _owner: False,
        "show_info": Mock(), "ToolboxCacheDialog": factory,
        "_set_processing_cache_reset_ui_locked": locked,
    })
    if raises:
        with pytest.raises(RuntimeError, match="dialog"):
            show(settings)
    else:
        show(settings)
    assert [call.args[1] for call in locked.call_args_list] == [True, False]
    guard.end.assert_called_once_with()
    dialog.deleteLater.assert_called_once_with()
    assert factory.call_args.kwargs["projects_root"] == tmp_path
    assert factory.call_args.kwargs["project"] is settings.project


def test_settings_exposes_cache_action_and_worker_imports_no_widgets():
    settings = ast.parse((ROOT / "src/Main_App/gui/settings_panel.py").read_text(encoding="utf-8"))
    dialog = next(node for node in settings.body if isinstance(node, ast.ClassDef) and node.name == "SettingsDialog")
    advanced = next(node for node in dialog.body if isinstance(node, ast.FunctionDef) and node.name == "_init_advanced_tab")
    assert any(isinstance(node, ast.Constant) and node.value == "Clear Toolbox Cache…" for node in ast.walk(advanced))
    assert "self._clear_toolbox_cache" in ast.unparse(advanced)
    worker = ast.parse(WORKER.read_text(encoding="utf-8"))
    assert all(node.module not in {"PySide6.QtWidgets", "PySide6.QtGui"} for node in ast.walk(worker) if isinstance(node, ast.ImportFrom))
