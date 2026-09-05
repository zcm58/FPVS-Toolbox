"""Exercise real orchestration functions with lightweight doubles, without Qt."""

from __future__ import annotations

import ast
from datetime import datetime
import gc
import logging
from pathlib import Path
from queue import Empty, Queue
from types import SimpleNamespace
from unittest.mock import Mock


REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_function(relative_path, name, namespace, *, class_name=None):
    path = REPO_ROOT / relative_path
    tree = ast.parse(path.read_text(encoding="utf-8"))
    owner = tree if class_name is None else next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    function = next(
        node for node in owner.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    )
    function.decorator_list = []
    # Postpone production annotations; no PySide6 import or event loop is needed.
    module = ast.Module(
        body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), function],
        type_ignores=[],
    )
    exec(compile(ast.fix_missing_locations(module), str(path), "exec"), namespace)
    return namespace[name]


def test_many_file_errors_keep_batch_running_until_one_finished_payload():
    poll = _load_function(
        "src/Main_App/workers/mp_runner_bridge.py", "_poll",
        {"Empty": Empty, "Path": Path, "logger": logging.getLogger(__name__)},
        class_name="MpRunnerBridge",
    )
    bridge = SimpleNamespace(
        _q=Queue(), _total=12, _running=True, _results=[], _error_results=[],
        _excluded_results=[], _timer=Mock(), _cancel_event=object(),
        _worker_thread=object(), error=Mock(), file_status=Mock(),
        progress=Mock(), finished=Mock(),
    )
    failures = [
        {"file": f"p{index}.bdf", "status": "error", "stage": "preprocess", "error": "Bad receipt"}
        for index in range(12)
    ]
    for index, failure in enumerate(failures, start=1):
        bridge._q.put({"type": "progress", "completed": index, "result": failure})
    poll(bridge)

    assert bridge._running
    bridge.error.emit.assert_not_called()
    bridge.finished.emit.assert_not_called()
    bridge._timer.stop.assert_not_called()
    assert bridge.file_status.emit.call_count == 12

    bridge._q.put({"type": "done"})
    poll(bridge)
    bridge.finished.emit.assert_called_once()
    assert bridge.finished.emit.call_args.args[0]["errors"] == failures
    assert not bridge._running


def test_completion_preserves_failure_details_and_shows_one_summary(tmp_path):
    error = {"file": str(tmp_path / "p1.bdf"), "status": "error", "stage": "preprocess", "error": "Bad receipt"}
    ledger_error = {"file": error["file"], "status": "failed", "reason": "incomplete"}
    summary = Mock()
    record = Mock()
    report = Mock(return_value=tmp_path / "qc.xlsx")
    namespace = {
        "Path": Path, "logging": logging, "logger": logging.getLogger(__name__),
        "record_processing_results": record, "export_processing_qc_summary": report,
        "_run_failed_results_from_ledger": lambda *_: [ledger_error],
        "_run_condition_warning_results_from_ledger": lambda *_: [],
        "_format_exclusion_reason": lambda result: result.get("error", "incomplete"),
        "_show_exclusion_summary_popup": summary,
        "_show_condition_warning_popup": Mock(),
    }
    finished = _load_function(
        "src/Main_App/gui/processing_workflows.py", "on_processing_finished", namespace,
    )
    finalized = []
    host = SimpleNamespace(
        settings=SimpleNamespace(debug_enabled=lambda: False), validated_params={},
        log=Mock(), _processing_plan=object(), currentProject=object(), _busy_stop=Mock(),
    )
    host._finalize_processing = lambda *args, **kwargs: finalized.append(host._processing_summary_reported)
    finished(host, {"results": [], "errors": [error], "cancelled": False})

    assert record.call_args.args[2] == [error]
    assert report.call_args.args[2] == [error]
    summary.assert_called_once_with(host, [error])
    assert finalized == [True]
    assert not host._processing_summary_reported


def test_reported_failures_do_not_open_second_completion_dialog():
    messages = Mock()
    finalize = _load_function(
        "src/Main_App/gui/processing_completion.py", "finalize_processing_host_state",
        {"user_messages": messages, "gc": gc, "datetime": datetime},
    )
    host = SimpleNamespace(
        _processing_summary_reported=True, log=Mock(), _set_controls_enabled=Mock(),
        progress_bar=Mock(),
    )
    finalize(host, True)
    assert not messages.mock_calls
    host._set_controls_enabled.assert_called_once_with(True)
    assert not host.busy
