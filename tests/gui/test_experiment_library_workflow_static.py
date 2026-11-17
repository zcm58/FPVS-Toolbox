"""Widget-free regression checks for library handoff and cancellation."""

from __future__ import annotations

import ast
import __future__
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock


def _controller():
    path = Path(__file__).resolve().parents[2] / "src/Main_App/gui/experiment_library_workflow.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef))
    namespace = {
        "QObject": object,
        "Slot": lambda *_args: lambda method: method,
        "Path": Path,
        "PublicDataset": object,
        "CatalogSnapshot": type("CatalogSnapshot", (), {}),
    }
    # Compile only the controller so these orchestration checks never initialize Qt.
    exec(compile(ast.Module([cls], type_ignores=[]), str(path), "exec", flags=__future__.annotations.compiler_flag), namespace)
    controller = object.__new__(namespace[cls.name])
    controller.page = Mock()
    controller.thread = None
    controller._installed = {}
    controller._catalog_failed = False
    return controller


def test_catalog_retry_refreshes_instead_of_downloading_a_stale_selection():
    controller = _controller()
    controller._catalog_failed = True
    controller.page.selected_dataset = SimpleNamespace(item_id="demo", version="1.0.0")
    controller.refresh = Mock()
    controller._open = Mock()
    controller._primary()
    controller.refresh.assert_called_once()
    controller._open.assert_not_called()


def test_canceling_feedback_survives_an_already_queued_phase():
    controller = _controller()
    controller._cancel_event = Event()
    controller._cancel_event.set()
    controller._phase("setup")
    controller.page.show_canceling.assert_called_once()
    controller.page.show_status.assert_not_called()


def test_an_active_run_preserves_the_project_when_installation_finishes():
    controller = _controller()
    controller.host = SimpleNamespace(_run_active=True)
    controller._open(Path("demo"))
    controller.page.show_status.assert_called_once_with(
        "Project ready", "Finish the current operation, then open this project.",
    )
    controller.page.primary_button.setText.assert_called_once_with("Open project")


def test_late_cancel_preserves_finished_install_without_opening_it():
    controller = _controller()
    item = SimpleNamespace(item_id="demo", version="1.0.0")
    controller._install_item = item
    controller._result = Path("demo")
    controller._failure = None
    controller._canceled = False
    controller._cancel_event = Event()
    controller._cancel_event.set()
    controller._selected = Mock()
    controller._open = Mock()
    controller._thread_finished()
    assert controller._installed[("demo", "1.0.0")] == Path("demo")
    controller._selected.assert_called_once_with(item)
    controller._open.assert_not_called()
