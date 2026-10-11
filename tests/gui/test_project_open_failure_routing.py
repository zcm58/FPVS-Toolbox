"""A rejected project open must not reset the active project's GUI state."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.mark.parametrize("opened", [False, True])
def test_project_ready_notification_requires_successful_open(opened):
    source = Path(__file__).resolve().parents[2] / "src/Main_App/gui/project_workflows.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    method = next(node for node in tree.body if getattr(node, "name", "") == "open_project_path")
    previous_project = object()
    next_project = object() if opened else None
    host = SimpleNamespace(currentProject=previous_project)
    namespace = {
        "Any": object,
        "confirm_project_draft_exit": Mock(return_value=True),
        "_open_project_path": Mock(return_value=next_project),
        "notify_project_ready": Mock(),
    }
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), "exec"), namespace)

    namespace["open_project_path"](host, "synthetic-project")

    namespace["_open_project_path"].assert_called_once_with(host, "synthetic-project")
    if opened:
        namespace["notify_project_ready"].assert_called_once_with(host)
    else:
        namespace["notify_project_ready"].assert_not_called()
        assert host.currentProject is previous_project
