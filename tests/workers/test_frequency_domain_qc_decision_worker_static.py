from __future__ import annotations

import ast
from copy import deepcopy
import json
from pathlib import Path
import sys
from types import ModuleType
from unittest.mock import Mock

import pytest


WORKER_PATH = (
    Path(__file__).resolve().parents[2]
    / "src" / "Main_App" / "workers" / "frequency_domain_qc_decision_worker.py"
)
BACKEND_MODULE = "Main_App.processing.frequency_domain_qc"


def _worker_without_qt(tmp_path, monkeypatch):
    """Execute the production worker with signal doubles, without importing Qt."""
    tree = ast.parse(WORKER_PATH.read_text(encoding="utf-8"))
    tree.body = [
        node for node in tree.body
        if not (isinstance(node, ast.ImportFrom) and node.module == "PySide6.QtCore")
    ]
    namespace = {
        "__name__": __name__, "QObject": object,
        "Signal": lambda *_args: None,
        "Slot": lambda *_args: lambda method: method,
    }
    exec(compile(tree, str(WORKER_PATH), "exec"), namespace)
    backend = ModuleType(BACKEND_MODULE)
    backend.apply_frequency_domain_qc_decision = Mock()
    backend.mark_frequency_domain_outputs_stale = Mock()
    monkeypatch.setitem(sys.modules, BACKEND_MODULE, backend)
    inputs = {
        "report": {"analysis_fingerprint": "original", "flags": [{"value": -55.25}]},
        "review_decisions": ({"finding_fingerprint": "f1", "decision": "retain"},),
        "manual_participant_reasons": {"P9": "No reason provided"},
        "manual_recording_reasons": {"P9-visit2": "User review"},
    }
    worker = namespace["FrequencyDomainQcDecisionWorker"](tmp_path, **inputs)
    worker.finished = Mock()
    return worker, backend, inputs


def test_save_returns_new_disk_metadata_and_preserves_exact_decision_inputs(tmp_path, monkeypatch):
    worker, backend, inputs = _worker_without_qt(tmp_path, monkeypatch)
    original = deepcopy(inputs)
    tools = {"frequency_domain_qc": {"review_complete": True, "decision_fingerprint": "saved"}}
    manifest = {"tools": tools, "participants": [{"participant_id": "P9"}]}

    def save(*_args, **_kwargs):
        (tmp_path / "project.json").write_text(json.dumps(manifest), encoding="utf-8")

    backend.apply_frequency_domain_qc_decision.side_effect = save
    worker.run()

    backend.apply_frequency_domain_qc_decision.assert_called_once_with(
        tmp_path, inputs["report"],
        review_decisions=inputs["review_decisions"],
        manual_participant_reasons=inputs["manual_participant_reasons"],
        manual_recording_reasons=inputs["manual_recording_reasons"],
    )
    assert inputs == original
    backend.mark_frequency_domain_outputs_stale.assert_not_called()
    worker.finished.emit.assert_called_once_with({
        "success": True, "tools": tools, "error": "", "stale_error": "",
    })


@pytest.mark.parametrize("error", [ValueError("Conflicting decisions"), OSError("Disk full")])
def test_save_failure_emits_failure_and_marks_outputs_stale(tmp_path, monkeypatch, error):
    worker, backend, inputs = _worker_without_qt(tmp_path, monkeypatch)
    original = deepcopy(inputs)
    backend.apply_frequency_domain_qc_decision.side_effect = error
    worker.run()

    backend.mark_frequency_domain_outputs_stale.assert_called_once_with(
        tmp_path, reason="Frequency-domain QC review failed before post-processing resumed.",
    )
    worker.finished.emit.assert_called_once_with({
        "success": False, "tools": None,
        "error": f"Frequency-domain QC decisions could not be saved: {error}",
        "stale_error": "",
    })
    assert inputs == original


def test_stale_status_failure_does_not_mask_save_error_or_prevent_completion(tmp_path, monkeypatch):
    worker, backend, _inputs = _worker_without_qt(tmp_path, monkeypatch)
    backend.apply_frequency_domain_qc_decision.side_effect = ValueError("Original failure")
    backend.mark_frequency_domain_outputs_stale.side_effect = OSError("Permission denied")
    worker.run()

    worker.finished.emit.assert_called_once_with({
        "success": False, "tools": None,
        "error": "Frequency-domain QC decisions could not be saved: Original failure",
        "stale_error": "Downstream stale status could not be saved: Permission denied",
    })


@pytest.mark.parametrize("payload", [None, "{corrupt", "[]", "{}", '{"tools": []}'])
def test_unreadable_or_missing_metadata_never_resumes_with_stale_tools(tmp_path, monkeypatch, payload):
    worker, backend, _inputs = _worker_without_qt(tmp_path, monkeypatch)
    if payload is not None:
        (tmp_path / "project.json").write_text(payload, encoding="utf-8")
    worker.run()

    backend.apply_frequency_domain_qc_decision.assert_called_once()
    backend.mark_frequency_domain_outputs_stale.assert_called_once()
    worker.finished.emit.assert_called_once()
    result = worker.finished.emit.call_args.args[0]
    assert result["success"] is False
    assert result["tools"] is None
    assert result["error"].startswith("Frequency-domain QC decisions could not be saved:")


def test_backend_import_failure_still_emits_a_completion_result(tmp_path, monkeypatch):
    worker, _backend, _inputs = _worker_without_qt(tmp_path, monkeypatch)
    monkeypatch.setitem(sys.modules, BACKEND_MODULE, None)
    worker.run()

    worker.finished.emit.assert_called_once()
    result = worker.finished.emit.call_args.args[0]
    assert result["success"] is False
    assert result["error"]
    assert result["stale_error"]


def test_worker_keeps_gui_and_project_objects_outside_its_dependency_boundary():
    tree = ast.parse(WORKER_PATH.read_text(encoding="utf-8"))
    imports = [node for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not any("gui" in (node.module or "").split(".") for node in imports)
    assert not any(node.module == "PySide6.QtWidgets" for node in imports)
    assert not any(node.module == BACKEND_MODULE for node in tree.body if isinstance(node, ast.ImportFrom))
    worker_class = next(node for node in tree.body if isinstance(node, ast.ClassDef))
    constructor = next(node for node in worker_class.body if isinstance(node, ast.FunctionDef) and node.name == "__init__")
    assert [arg.arg for arg in constructor.args.args] == ["self", "project_root", "report"]
    assert {arg.arg for arg in constructor.args.kwonlyargs} == {
        "review_decisions", "manual_participant_reasons", "manual_recording_reasons",
    }
