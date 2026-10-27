"""Harmonic worker terminal outcomes without importing or executing Qt."""

from __future__ import annotations

import ast
import logging
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest


WORKER_PATH = (
    Path(__file__).resolve().parents[2]
    / "src/Main_App/workers/harmonic_selection_worker.py"
)


def _worker_without_qt(monkeypatch, tmp_path):
    tree = ast.parse(WORKER_PATH.read_text(encoding="utf-8"))
    owner = next(node for node in tree.body if isinstance(node, ast.ClassDef))
    run = next(node for node in owner.body if isinstance(node, ast.FunctionDef) and node.name == "run")
    run.decorator_list = []
    report = SimpleNamespace(
        workbook_path=tmp_path / "Harmonic_Selection_Summary.xlsx",
        selection_metadata={"selected_harmonics_hz": [1.2]},
    )
    select = Mock(return_value=report)
    namespace = {"Path": Path, "logger": logging.getLogger(__name__),
                 "run_processing_harmonic_selection_qc": select}
    exec(compile(ast.Module(body=[run], type_ignores=[]), str(WORKER_PATH), "exec"), namespace)
    downstream = ModuleType("Main_App.workers.post_processing_pipeline_worker")
    downstream.POST_PROCESSING_PHASE_COUNT = 5
    downstream.run_postprocessing_from_selection = Mock()
    monkeypatch.setitem(sys.modules, downstream.__name__, downstream)
    worker = SimpleNamespace(
        _project=SimpleNamespace(project_root=tmp_path),
        progress=Mock(), phase_progress=Mock(), finished=Mock(),
    )
    worker.run = namespace["run"].__get__(worker)
    return worker, namespace, select, downstream, report


@pytest.mark.parametrize("error_type", [PermissionError, RuntimeError, ValueError])
def test_project_root_resolution_failure_still_finishes(monkeypatch, tmp_path, error_type):
    worker, namespace, select, downstream, _report = _worker_without_qt(monkeypatch, tmp_path)
    path = Mock()
    path.expanduser.return_value.resolve.side_effect = error_type("Cannot resolve project root")
    namespace["Path"] = Mock(return_value=path)

    worker.run()

    worker.finished.emit.assert_called_once_with({
        "ok": False, "error": "Cannot resolve project root", "messages": [],
    })
    select.assert_not_called()
    downstream.run_postprocessing_from_selection.assert_not_called()


def test_successful_selection_keeps_the_existing_result_payload(monkeypatch, tmp_path):
    worker, _namespace, select, downstream, report = _worker_without_qt(monkeypatch, tmp_path)

    worker.run()

    select.assert_called_once()
    assert select.call_args.args == (worker._project,)
    assert select.call_args.kwargs["force_recalculate"] is True
    worker.finished.emit.assert_called_once_with({
        "ok": True,
        "workbook_path": str(report.workbook_path),
        "selection_metadata": report.selection_metadata,
        "messages": [], "downstream_postprocessing": None, "downstream_rebuilt": False,
    })
    downstream.run_postprocessing_from_selection.assert_not_called()
