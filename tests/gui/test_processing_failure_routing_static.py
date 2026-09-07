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

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_function(relative_path, name, namespace, *, class_name=None, outer_function=None):
    path = REPO_ROOT / relative_path
    tree = ast.parse(path.read_text(encoding="utf-8"))
    owner = tree if class_name is None else next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    if outer_function is not None:
        owner = next(
            node for node in owner.body
            if isinstance(node, ast.FunctionDef) and node.name == outer_function
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


@pytest.mark.parametrize(
    "case, expected_success",
    [
        ("all_worker_errors", False),
        ("ledger_only_failure", False),
        ("partial_success", True),
        ("intentional_exclusions", True),
    ],
)
def test_completion_does_not_report_an_entirely_failed_batch_as_success(
    tmp_path, case, expected_success,
):
    failed = {"file": str(tmp_path / "P01.bdf"), "status": "error", "error": "Load failed"}
    errors = [failed] if case in {"all_worker_errors", "partial_success"} else []
    ledger_failures = [failed] if case == "ledger_only_failure" else []
    results = [{"file": str(tmp_path / "P02.bdf"), "status": "ok"}] if case == "partial_success" else []
    excluded = (
        [{"file": failed["file"], "status": "excluded", "reason": "Manual exclusion"}]
        if case == "intentional_exclusions" else []
    )

    def start_pipeline(host, *, on_finished):
        on_finished()
        return True

    starter = Mock(side_effect=start_pipeline)
    namespace = {
        "Path": Path, "logging": logging, "logger": logging.getLogger(__name__),
        "record_processing_results": Mock(),
        "export_processing_qc_summary": Mock(return_value=tmp_path / "qc.xlsx"),
        "_run_failed_results_from_ledger": lambda *_: ledger_failures,
        "_run_condition_warning_results_from_ledger": lambda *_: [],
        "_format_exclusion_reason": lambda result: result.get("error", result.get("reason", "")),
        "_show_exclusion_summary_popup": Mock(), "_show_condition_warning_popup": Mock(),
        "format_audit_summary": lambda *_: ("Preprocessed", False),
        "_format_timing_summary": lambda *_: None,
        "_review_interpolation_burden_before_post_processing": lambda *_: True,
        "_start_post_processing_pipeline_after_processing": starter,
        "BDF_RECORDING_NOT_STARTED_REASON": "bdf_recording_not_started",
    }
    finished = _load_function(
        "src/Main_App/gui/processing_workflows.py", "on_processing_finished", namespace,
    )
    host = SimpleNamespace(
        settings=SimpleNamespace(debug_enabled=lambda: False), validated_params={},
        log=Mock(), _processing_plan=object(), currentProject=object(),
        _busy_stop=Mock(), _finalize_processing=Mock(),
    )
    finished(host, {"results": results, "errors": errors, "excluded": excluded})

    host._finalize_processing.assert_called_once_with(expected_success, cancelled=False)
    assert starter.call_count == int(case == "partial_success")
    host._busy_stop.assert_called_once()
    namespace["_show_exclusion_summary_popup"].assert_called_once()
    assert host._post_processing_failure_reason == ""


def _post_processing_namespace():
    path = "src/Main_App/gui/processing_workflows.py"
    tree = ast.parse((REPO_ROOT / path).read_text(encoding="utf-8"))
    assignments = [
        node for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id.startswith("_POST_PROCESSING_")
            for target in node.targets
        )
    ]
    namespace = {}
    exec(compile(ast.Module(body=assignments, type_ignores=[]), path, "exec"), namespace)
    _load_function(path, "_post_processing_frequency_domain_outputs_ready", namespace)
    _load_function(path, "_post_processing_failure_reason", namespace)
    return namespace


def test_post_processing_fatal_prerequisite_keeps_exact_reason():
    namespace = _post_processing_namespace()
    reason = "P9 / Neutral Angry: no condition occurrence was planned."
    result = {
        "ok": False,
        "steps": [{"name": "post_processing_pipeline", "ok": False, "message": reason}],
    }

    assert namespace["_post_processing_failure_reason"](result) == reason


def test_post_processing_optional_failure_keeps_core_outputs_usable():
    namespace = _post_processing_namespace()
    result = {
        "ok": False,
        "steps": [
            {"name": name, "ok": True}
            for name in namespace["_POST_PROCESSING_FREQUENCY_DOMAIN_STEP_NAMES"]
        ] + [{"name": "eloreta_volume_source_psd", "ok": False, "message": "Source export failed"}],
    }

    assert namespace["_post_processing_failure_reason"](result) == ""


@pytest.mark.parametrize("reported_summary", [False, True])
def test_post_processing_incomplete_dialog_survives_preprocessing_summary(reported_summary):
    messages = Mock()
    finalize = _load_function(
        "src/Main_App/gui/processing_completion.py", "finalize_processing_host_state",
        {"user_messages": messages, "gc": gc, "datetime": datetime},
    )
    reason = "P9 / Neutral Angry: no condition occurrence was planned."
    host = SimpleNamespace(
        _processing_summary_reported=reported_summary,
        _post_processing_failure_reason=reason,
        log=Mock(), _set_controls_enabled=Mock(), progress_bar=Mock(),
    )
    finalize(host, False)

    messages.show_info.assert_not_called()
    messages.show_error.assert_called_once()
    title, message, parent = messages.show_error.call_args.args
    assert title == "Post-processing Incomplete"
    assert reason in message
    assert "not ready" in message
    assert parent is host
    assert not host.busy


@pytest.mark.parametrize("cancelled", [False, True])
def test_processing_completion_propagates_post_processing_failure(tmp_path, cancelled):
    reason = "P9 / Neutral Angry: no condition occurrence was planned."

    def start_pipeline(host, *, on_finished):
        host._post_processing_failure_reason = reason
        on_finished()
        return True

    namespace = {
        "Path": Path, "logging": logging, "logger": logging.getLogger(__name__),
        "format_audit_summary": lambda *_: ("Preprocessed", False),
        "_format_timing_summary": lambda *_: None,
        "_show_exclusion_summary_popup": Mock(), "_show_condition_warning_popup": Mock(),
        "_review_interpolation_burden_before_post_processing": lambda *_: True,
        "_start_post_processing_pipeline_after_processing": start_pipeline,
    }
    finished = _load_function(
        "src/Main_App/gui/processing_workflows.py", "on_processing_finished", namespace,
    )
    host = SimpleNamespace(
        settings=SimpleNamespace(debug_enabled=lambda: False), validated_params={},
        log=Mock(), _busy_stop=Mock(), _finalize_processing=Mock(),
    )
    result = {"file": str(tmp_path / "p9.bdf"), "status": "ok"}
    finished(host, {"results": [result], "cancelled": cancelled})

    host._finalize_processing.assert_called_once_with(False, cancelled=cancelled)
    assert host._post_processing_failure_reason == ("" if cancelled else reason)


def test_ledger_save_failure_does_not_claim_processing_success(tmp_path):
    namespace = {
        "Path": Path, "logging": logging, "logger": logging.getLogger(__name__),
        "format_audit_summary": lambda *_: ("Preprocessed", False),
        "_format_timing_summary": lambda *_: None,
        "_show_exclusion_summary_popup": Mock(), "_show_condition_warning_popup": Mock(),
        "record_processing_results": Mock(side_effect=OSError("Project folder is read-only")),
        "_start_post_processing_pipeline_after_processing": Mock(),
    }
    finished = _load_function(
        "src/Main_App/gui/processing_workflows.py", "on_processing_finished", namespace,
    )
    host = SimpleNamespace(
        settings=SimpleNamespace(debug_enabled=lambda: False), validated_params={},
        log=Mock(), _busy_stop=Mock(), _finalize_processing=Mock(),
        _processing_plan=object(), currentProject=object(),
    )
    finished(host, {"results": [{"file": str(tmp_path / "p9.bdf"), "status": "ok"}]})

    host._finalize_processing.assert_called_once_with(False, cancelled=False)
    namespace["_start_post_processing_pipeline_after_processing"].assert_not_called()
    assert "Project folder is read-only" in host._post_processing_failure_reason


def test_successful_rebuild_skip_is_not_a_post_processing_failure():
    reason = _post_processing_namespace()["_post_processing_failure_reason"]
    assert reason({"ok": True, "rebuild_skipped": True, "steps": []}) == ""


def test_paused_frequency_qc_requires_review_without_claiming_success():
    reason = _post_processing_namespace()["_post_processing_failure_reason"]
    assert "QC review must be completed" in reason({
        "ok": False, "requires_frequency_domain_qc_review": True, "steps": [],
    })


def test_worker_finished_delivers_explicit_failure_to_completion_callback():
    reason = "P9 / Neutral Angry: no condition occurrence was planned."
    host = SimpleNamespace(log=Mock())
    finalized_reasons = []
    namespace = _post_processing_namespace()
    namespace.update({
        "host": host, "project": object(), "logging": logging,
        "_post_processing_source_map_outcome": lambda _: (False, False),
        "on_finished": lambda: finalized_reasons.append(host._post_processing_failure_reason),
        "QTimer": SimpleNamespace(singleShot=lambda _delay, callback: callback()),
    })
    handler = _load_function(
        "src/Main_App/gui/processing_workflows.py", "_handle_finished", namespace,
        outer_function="_start_post_processing_pipeline_after_processing",
    )
    handler({
        "ok": False, "failure_reason": reason,
        "steps": [{"name": "post_processing_pipeline", "ok": False, "message": reason}],
    })

    assert finalized_reasons == [reason]
    assert host._post_processing_pipeline_thread is None
    assert any("not ready" in call.args[0] for call in host.log.call_args_list)


def test_failed_post_processing_phase_does_not_say_complete():
    namespace = _post_processing_namespace()
    display = _load_function(
        "src/Main_App/gui/processing_workflows.py", "_post_processing_phase_display_state",
        namespace,
    )
    title, message, phase = display("post_processing_failed", "P9 needs a condition decision.")

    assert title == "Post-processing Incomplete"
    assert message == "P9 needs a condition decision."
    assert phase == 5


def test_canceled_processing_does_not_show_post_processing_error_dialog():
    messages = Mock()
    finalize = _load_function(
        "src/Main_App/gui/processing_completion.py", "finalize_processing_host_state",
        {"user_messages": messages, "gc": gc, "datetime": datetime},
    )
    finalize(SimpleNamespace(
        _suppress_completion_dialogs=True, _post_processing_failure_reason="Previous failure",
        log=Mock(),
    ), False)

    assert not messages.mock_calls
