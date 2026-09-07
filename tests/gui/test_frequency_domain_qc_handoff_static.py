"""Exercise handoff control flow without importing or running Qt."""

from __future__ import annotations

import ast
import logging
from pathlib import Path
from types import ModuleType, SimpleNamespace
import sys
from unittest.mock import Mock

import pytest


ROOT = Path(__file__).resolve().parents[2]
HANDOFF = ROOT / "src/Main_App/gui/frequency_domain_qc_handoff.py"


def _function(name, namespace, owner=None, path=HANDOFF):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    body = tree.body if owner is None else next(
        node.body for node in tree.body if isinstance(node, ast.ClassDef) and node.name == owner
    )
    node = next(node for node in body if isinstance(node, ast.FunctionDef) and node.name == name)
    node.decorator_list = []
    future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
    module = ast.fix_missing_locations(ast.Module(body=[future, node], type_ignores=[]))
    exec(compile(module, str(path), "exec"), namespace)
    return namespace[name]


@pytest.mark.parametrize("result", [
    {"success": True, "tools": {"frequency_domain_qc": {"review_complete": True}}},
    {"success": False, "error": "Disk full", "stale_error": "Status save failed"},
    None,
])
@pytest.mark.parametrize("resume_started", [False, True])
def test_completion_resumes_only_after_successful_receipt_and_refreshes_only_tools(monkeypatch, result, resume_started):
    module = ModuleType("Main_App.gui.processing_workflows")
    module._set_resume_post_processing_pending = Mock()
    module._start_post_processing_pipeline_after_processing = Mock(return_value=resume_started)
    monkeypatch.setitem(sys.modules, module.__name__, module)
    thread = object()
    host = SimpleNamespace(_frequency_domain_qc_save_thread=thread, log=Mock())
    manifest = {"tools": {"previous": True}, "unsaved_name": "Keep this edit"}
    owner = SimpleNamespace(
        host=host, project=SimpleNamespace(manifest=manifest), save_thread=thread,
        on_finished=Mock(), result=result, deleteLater=Mock(),
        provisional_cache=Mock(),
        button_state=(Mock(), True, "Stop Processing", "Original tooltip"),
    )
    messages = SimpleNamespace(critical=Mock())
    complete = _function("complete", {"logging": logging, "QMessageBox": messages}, "_DecisionSaveBridge")
    complete(owner)
    assert host._frequency_domain_qc_save_thread is None
    assert host._frequency_domain_qc_save_worker is None
    assert host._frequency_domain_qc_save_bridge is None
    owner.deleteLater.assert_called_once()
    button = owner.button_state[0]
    button.setText.assert_called_once_with("Stop Processing")
    button.setToolTip.assert_called_once_with("Original tooltip")
    button.setEnabled.assert_called_once_with(True)
    assert manifest["unsaved_name"] == "Keep this edit"
    if result and result["success"]:
        assert manifest["tools"] == result["tools"]
        module._start_post_processing_pipeline_after_processing.assert_called_once_with(
            host, on_finished=owner.on_finished, completed_phase_floor=1,
            provisional_cache=owner.provisional_cache,
        )
        if resume_started:
            owner.provisional_cache.clear.assert_not_called()
            owner.on_finished.assert_not_called()
        else:
            owner.provisional_cache.clear.assert_called_once()
            owner.on_finished.assert_called_once()
        messages.critical.assert_not_called()
    else:
        module._start_post_processing_pipeline_after_processing.assert_not_called()
        owner.on_finished.assert_called_once()
        module._set_resume_post_processing_pending.assert_called_once_with(host, True)
        assert manifest["tools"] == {"previous": True}
        assert host._post_processing_failure_reason
        messages.critical.assert_called_once()
        owner.provisional_cache.clear.assert_called_once()
        if result:
            assert result["error"] in host._post_processing_failure_reason
            assert result["stale_error"] in host._post_processing_failure_reason


@pytest.mark.parametrize("outcome", ["accepted", "cancelled", "dialog_error"])
def test_review_hands_evidence_to_save_only_on_acceptance(monkeypatch, outcome):
    from Main_App.processing import frequency_domain_qc

    dialog_module = ModuleType("Main_App.gui.frequency_domain_qc_dialog")
    save_module = ModuleType("Main_App.gui.frequency_domain_qc_handoff")
    dialog = SimpleNamespace(
        exec=lambda: outcome == "accepted", review_decisions=lambda: [],
        manual_participant_reasons=lambda: {}, manual_recording_reasons=lambda: {},
    )
    dialog_module.FrequencyDomainQcReviewDialog = Mock(
        return_value=dialog,
        side_effect=ValueError("Group mismatch") if outcome == "dialog_error" else None,
    )
    save_module.save_frequency_domain_qc_review = Mock()
    monkeypatch.setitem(sys.modules, dialog_module.__name__, dialog_module)
    monkeypatch.setitem(sys.modules, save_module.__name__, save_module)
    mark_stale = Mock()
    monkeypatch.setattr(frequency_domain_qc, "mark_frequency_domain_outputs_stale", mark_stale)
    callback, cache = Mock(), Mock()
    project, host, report = SimpleNamespace(project_root=Path("project")), SimpleNamespace(log=Mock()), {}
    review = _function("_handle_frequency_domain_qc_review", {
        "_frequency_domain_qc_participant_groups": lambda _project: None,
        "QDialog": SimpleNamespace(DialogCode=SimpleNamespace(Accepted=True)),
        "QMessageBox": SimpleNamespace(critical=Mock()),
        "logger": logging.getLogger(__name__), "logging": logging,
        "_sync_project_tools_metadata_from_disk": Mock(),
        "_set_resume_post_processing_pending": Mock(),
    }, path=ROOT / "src/Main_App/gui/processing_workflows.py")

    review(host, project, report, on_finished=callback, provisional_cache=cache)

    if outcome == "accepted":
        save_module.save_frequency_domain_qc_review.assert_called_once_with(
            host, project, report, review_decisions=[], manual_participant_reasons={},
            manual_recording_reasons={}, on_finished=callback, provisional_cache=cache,
        )
        cache.clear.assert_not_called()
        callback.assert_not_called()
        mark_stale.assert_not_called()
    else:
        save_module.save_frequency_domain_qc_review.assert_not_called()
        cache.clear.assert_called_once()
        callback.assert_called_once()
        mark_stale.assert_called_once()


@pytest.mark.parametrize("start_error", [False, True])
def test_handoff_presents_window_before_start_and_does_not_run_save_synchronously(start_error):
    events = []
    def signal():
        return SimpleNamespace(connect=Mock())
    thread = SimpleNamespace(started=signal(), finished=signal(), quit=Mock(), deleteLater=Mock())
    def start():
        events.append("start")
        if start_error:
            raise RuntimeError("Cannot start thread")
    thread.start = start
    worker = SimpleNamespace(moveToThread=Mock(), run=Mock(), finished=signal(), deleteLater=Mock())
    bridge = SimpleNamespace(receive_result=Mock(), complete=Mock())
    window = SimpleNamespace(
        isMinimized=lambda: False, show=lambda: events.append("show"),
        raise_=lambda: events.append("raise"), activateWindow=lambda: events.append("activate"),
    )
    host = SimpleNamespace(
        _busy_start=Mock(), _set_controls_enabled=Mock(), window=lambda: window,
        processing_title_label=SimpleNamespace(setText=Mock()),
        processing_message_label=SimpleNamespace(setText=Mock()),
    )
    worker_factory = Mock(return_value=worker)
    save = _function("save_frequency_domain_qc_review", {
        "QThread": Mock(return_value=thread), "FrequencyDomainQcDecisionWorker": worker_factory,
        "_DecisionSaveBridge": Mock(return_value=bridge), "logger": logging.getLogger(__name__),
        "shell_status": SimpleNamespace(prepare_post_processing_activity=Mock()),
    })
    project, report, decisions, callback = SimpleNamespace(project_root=Path("project")), {}, ({"decision": "retain"},), Mock()
    kwargs = dict(review_decisions=decisions, manual_participant_reasons={}, manual_recording_reasons={}, on_finished=callback)
    save(host, project, report, **kwargs)
    assert events == ["show", "raise", "activate", "start"]
    worker.run.assert_not_called()
    callback.assert_not_called()
    worker_factory.assert_called_once_with(
        project.project_root, report, review_decisions=decisions,
        manual_participant_reasons={}, manual_recording_reasons={},
    )
    worker.finished.connect.assert_any_call(bridge.receive_result)
    thread.finished.connect.assert_any_call(bridge.complete)
    host._set_controls_enabled.assert_called_once_with(False)
    if start_error:
        bridge.complete.assert_called_once()
        assert "Cannot start thread" in bridge.receive_result.call_args.args[0]["error"]
    else:
        save(host, project, report, **kwargs)
        assert events.count("start") == 1  # Duplicate activation cannot launch another save.
        bridge.complete.assert_not_called()


def test_close_cannot_destroy_an_active_decision_save():
    messages = SimpleNamespace(information=Mock())
    close = _function("closeEvent", {"QMessageBox": messages}, "MainWindow", ROOT / "src/Main_App/gui/main_window.py")
    event = SimpleNamespace(ignore=Mock())
    close(SimpleNamespace(_frequency_domain_qc_save_thread=object()), event)
    event.ignore.assert_called_once()
    messages.information.assert_called_once()


def test_accepted_dialog_callback_hands_off_plain_receipts_without_applying_them():
    path = ROOT / "src/Main_App/gui/processing_workflows.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    handler = next(node for node in tree.body if getattr(node, "name", "") == "_handle_frequency_domain_qc_review")
    accepted = next(node for node in handler.body if isinstance(node, ast.If) and isinstance(node.test, ast.Name) and node.test.id == "accepted")
    names = {node.func.id for node in ast.walk(accepted) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    assert "save_frequency_domain_qc_review" in names
    assert "apply_frequency_domain_qc_decision" not in names
    assert "_sync_project_tools_metadata_from_disk" not in names
    assert "_start_post_processing_pipeline_after_processing" not in names
