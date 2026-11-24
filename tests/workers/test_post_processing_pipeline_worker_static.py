from __future__ import annotations

import ast
from contextlib import ExitStack
from dataclasses import dataclass
import json
import logging
from pathlib import Path
import sys
from types import MethodType, SimpleNamespace
from unittest.mock import Mock

import pytest


WORKER_PATH = (
    Path(__file__).resolve().parents[2] / "src" / "Main_App" / "workers" / "post_processing_pipeline_worker.py"
)


def _worker_tree() -> ast.Module:
    return ast.parse(WORKER_PATH.read_text(encoding="utf-8"))


def _class_method(tree: ast.Module, method_name: str) -> ast.FunctionDef:
    worker_class = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "PostProcessingPipelineWorker"
    )
    return next(node for node in worker_class.body if isinstance(node, ast.FunctionDef) and node.name == method_name)


def test_stats_ready_export_precedes_full_audit() -> None:
    tree = _worker_tree()
    run_method = _class_method(tree, "run")
    try_node = next(node for node in run_method.body if isinstance(node, ast.Try))

    def statement_call_index(method_name: str) -> int:
        return next(
            node.lineno
            for node in ast.walk(try_node)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == method_name
        )

    stats_index = statement_call_index("_run_stats_ready_export")
    audit_index = statement_call_index("_run_analysis_ready_export")
    assert stats_index < audit_index


def test_participant_keyed_workbook_has_a_canonical_repeated_session_gate() -> None:
    tree = _worker_tree()
    gate_method = _class_method(tree, "_is_repeated_session_project")
    stats_method = _class_method(tree, "_run_stats_ready_export")

    gate_source = ast.unparse(gate_method)
    stats_source = ast.unparse(stats_method)
    assert "from Main_App.projects import project_recording_context" in gate_source
    assert "project_recording_context(self._project).is_repeated_session" in gate_source
    assert "if self._is_repeated_session_project()" in stats_source
    assert "_REPEATED_SESSION_STATS_READY_SKIP_MESSAGE" in stats_source


def test_post_processing_run_bounds_xlsx_cache_with_exit_stack() -> None:
    tree = _worker_tree()
    run_method = _class_method(tree, "run")
    stack_assignment = next(
        statement
        for statement in run_method.body
        if isinstance(statement, ast.Assign)
        and isinstance(statement.value, ast.Call)
        and isinstance(statement.value.func, ast.Name)
        and statement.value.func.id == "ExitStack"
    )
    assert any(
        isinstance(target, ast.Name) and target.id == "cache_stack"
        for target in stack_assignment.targets
    )

    try_node = next(node for node in run_method.body if isinstance(node, ast.Try))
    cache_import = next(
        statement
        for statement in try_node.body
        if isinstance(statement, ast.ImportFrom)
        and statement.module == "Main_App.io"
    )
    assert [alias.name for alias in cache_import.names] == ["xlsx_read_cache_scope"]

    enter_statement = next(
        statement
        for statement in try_node.body
        if isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Call)
        and isinstance(statement.value.func, ast.Attribute)
        and statement.value.func.attr == "enter_context"
    )
    enter_call = enter_statement.value
    assert isinstance(enter_call.func.value, ast.Name)
    assert enter_call.func.value.id == "cache_stack"
    assert len(enter_call.args) == 1
    scope_call = enter_call.args[0]
    assert isinstance(scope_call, ast.Call)
    assert isinstance(scope_call.func, ast.Name)
    assert scope_call.func.id == "xlsx_read_cache_scope"
    enter_index = try_node.body.index(enter_statement)
    qc_index = next(
        index
        for index, statement in enumerate(try_node.body)
        if isinstance(statement, ast.Assign)
        and isinstance(statement.value, ast.Call)
        and isinstance(statement.value.func, ast.Attribute)
        and statement.value.func.attr == "_run_frequency_domain_qc_review"
    )
    assert enter_index < qc_index
    assert any(isinstance(node, ast.Return) for node in ast.walk(try_node))
    assert try_node.handlers
    assert any(
        _is_named_method_call(statement, "cache_stack", "close")
        for statement in try_node.finalbody
    )


def test_post_processing_run_reuses_and_releases_one_dataset_index() -> None:
    tree = _worker_tree()
    qc_method = _class_method(tree, "_run_frequency_domain_qc_review")
    harmonic_method = _class_method(tree, "_run_harmonic_selection")
    stats_method = _class_method(tree, "_run_stats_ready_export")
    audit_method = _class_method(tree, "_run_analysis_ready_export")
    run_method = _class_method(tree, "run")

    qc_source = ast.unparse(qc_method)
    harmonic_source = ast.unparse(harmonic_method)
    stats_source = ast.unparse(stats_method)
    audit_source = ast.unparse(audit_method)
    assert (
        "self._dataset_index = load_project_dataset_index(project_root)"
        in qc_source
    )
    assert "dataset_index=self._dataset_index" in qc_source
    assert "dataset_index=self._dataset_index" in harmonic_source
    assert "dataset_index=self._dataset_index" in stats_source
    assert "dataset_index=self._dataset_index" in audit_source
    assert "selection_metadata=self._harmonic_selection_metadata" in audit_source
    assert "provisional_cache=self._provisional_cache" in qc_source

    try_node = next(node for node in run_method.body if isinstance(node, ast.Try))
    assert any(
        isinstance(statement, ast.Assign)
        and any(
            isinstance(target, ast.Attribute)
            and isinstance(target.value, ast.Name)
            and target.value.id == "self"
            and target.attr == "_dataset_index"
            for target in statement.targets
        )
        and isinstance(statement.value, ast.Constant)
        and statement.value.value is None
        for statement in try_node.finalbody
    )


def test_frequency_review_requires_current_recording_condition_outcomes() -> None:
    tree = _worker_tree()
    qc_method = _class_method(tree, "_run_frequency_domain_qc_review")
    qc_source = ast.unparse(qc_method)

    assert "load_ledger(project_root)" in qc_source
    assert "load_recording_condition_outcomes" in qc_source
    assert "require_pre_review_readiness(outcome_ledger)" in qc_source
    assert qc_source.index("require_pre_review_readiness(outcome_ledger)") < qc_source.index(
        "self._dataset_index = load_project_dataset_index(project_root)"
    )


def test_geometry_mismatch_stops_before_coverage_or_frequency_review(tmp_path, monkeypatch):
    from contextlib import nullcontext
    from Main_App import projects
    from Main_App.processing import (
        frequency_domain_qc, full_fft_provenance, processing_ledger,
        recording_condition_outcomes, roi_coverage,
    )

    method = _class_method(_worker_tree(), "_run_frequency_domain_qc_review")
    method.decorator_list = []
    module = ast.Module(body=[method], type_ignores=[])
    namespace = {"Path": Path}
    exec(compile(ast.fix_missing_locations(module), str(WORKER_PATH), "exec"), namespace)
    dataset_index = object()
    outcomes = object()
    monkeypatch.setattr(projects, "load_project_dataset_index", Mock(return_value=dataset_index))
    monkeypatch.setattr(processing_ledger, "load_ledger", Mock(return_value={}))
    monkeypatch.setattr(recording_condition_outcomes, "load_recording_condition_outcomes", Mock(return_value=outcomes))
    monkeypatch.setattr(recording_condition_outcomes, "require_pre_review_readiness", Mock())
    geometry = Mock(side_effect=ValueError("Processed geometry mismatch"))
    monkeypatch.setattr(full_fft_provenance, "require_current_project_pre_review_geometry", geometry)
    coverage = Mock()
    review = Mock()
    monkeypatch.setattr(roi_coverage, "build_pre_review_roi_coverage", coverage)
    monkeypatch.setattr(frequency_domain_qc, "run_frequency_domain_qc_review", review)
    worker = SimpleNamespace(
        _project=SimpleNamespace(project_root=tmp_path),
        _emit_progress=Mock(),
        _frequency_qc_stage=lambda *_: nullcontext(),
    )

    with pytest.raises(ValueError, match="Processed geometry mismatch"):
        namespace[method.name](worker)

    geometry.assert_called_once_with(tmp_path.resolve(), dataset_index=dataset_index)
    coverage.assert_not_called()
    review.assert_not_called()


def test_full_fft_provenance_uses_only_ready_project_protocol_rates() -> None:
    tree = _worker_tree()
    method = _class_method(tree, "_run_full_fft_provenance")
    source = ast.unparse(method)

    assert "normalize_frequency_protocol" in source
    assert "protocol.presentation_rate_hz" in source
    assert "protocol.oddball_rate_hz" in source
    assert "frequency_protocol_fingerprint=protocol.fingerprint" in source
    assert "SettingsManager" not in source
    assert "DEFAULT_ODDBALL_FREQ" not in source


def _is_named_method_call(
    statement: ast.stmt,
    object_name: str,
    method_name: str,
) -> bool:
    return (
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Call)
        and isinstance(statement.value.func, ast.Attribute)
        and statement.value.func.attr == method_name
        and isinstance(statement.value.func.value, ast.Name)
        and statement.value.func.value.id == object_name
    )


def _pipeline_without_qt(tmp_path, *, failed_step="", review_error="", repeated_session=False):
    """Run the production orchestration with exporter/signal doubles and no Qt."""

    from Main_App.processing.pipeline_plan import PipelineCancelled

    tree = _worker_tree()
    methods = (
        "run", "_record_failed_frequency_outputs", "_emit_phase_progress",
        "_is_repeated_session_project", "_run_from_accepted_selection",
    )
    extracted = [_class_method(tree, name) for name in methods]
    for method in extracted:
        method.decorator_list = []
    definitions = [
        node for node in tree.body
        if isinstance(node, ast.Assign)
        or (isinstance(node, ast.ClassDef) and node.name == "PostProcessingStepResult")
        or (isinstance(node, ast.FunctionDef) and node.name == "_required_output_failure_reason")
    ]
    module = ast.Module(
        body=[
            ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
            *definitions,
            *extracted,
        ],
        type_ignores=[],
    )
    namespace = {
        "__name__": __name__, "Path": Path, "ExitStack": ExitStack,
        "dataclass": dataclass, "logging": logging,
        "PipelineCancelled": PipelineCancelled, "report_failure": Mock(),
    }
    exec(compile(ast.fix_missing_locations(module), str(WORKER_PATH), "exec"), namespace)
    step_result = namespace["PostProcessingStepResult"]
    (tmp_path / "project.json").write_text(
        json.dumps({"tools": {"processing": {"full_fft_provenance": {"status": "current"}}}}),
        encoding="utf-8",
    )

    def result(name):
        return step_result(name, name != failed_step, f"{name} failed" if name == failed_step else "OK")

    def review():
        if review_error:
            raise ValueError(review_error)
        return {"review_required": False}

    sessions = {
        "visit_1": {"label": "Visit 1", "visit_index": 1},
        "visit_2": {"label": "Visit 2", "visit_index": 2},
    } if repeated_session else {}
    worker = SimpleNamespace(
        _project=SimpleNamespace(project_root=tmp_path, sessions=sessions),
        _resume_from_selection=False,
        _requires_recording_aware_export=False,
        _harmonic_selection_metadata={"selection_fingerprint": "accepted"},
        _selection_fingerprint=None,
        _selection_changed=True,
        _emit_progress=Mock(),
        _capture_previous_selection_fingerprint=Mock(),
        _run_frequency_domain_qc_review=review,
        _sync_frequency_domain_qc_automatic_state=Mock(),
        _finalize_frequency_qc_release=Mock(),
        _run_full_fft_provenance=lambda *_: result("full_fft_provenance"),
        _run_harmonic_selection=lambda: result("harmonic_selection"),
        _run_stats_ready_export=lambda *_: result("stats_ready_summed_bca"),
        _run_analysis_ready_export=lambda *_: result("analysis_ready_full_audit"),
        _activate_artifact_freshness=Mock(),
        _record_artifact_freshness=lambda step: step,
        _artifact_targets={},
        _artifact_archives={},
        _project_manifest_exists=lambda root: (root / "project.json").is_file(),
        phase_progress=Mock(),
        progress=Mock(),
        finished=Mock(),
    )
    for name in methods:
        setattr(worker, name, MethodType(namespace[name], worker))

    return worker


@pytest.mark.parametrize("selection_resume", [False, True])
def test_workbook_release_does_not_import_source_map_producers(tmp_path, monkeypatch, selection_resume):
    worker = _pipeline_without_qt(tmp_path)
    worker._resume_from_selection = selection_resume
    monkeypatch.setitem(sys.modules, "Tools.LORETA_Visualizer.source_producers", None)

    worker.run()

    result = worker.finished.emit.call_args.args[0]
    assert result["ok"] is True
    assert [step["name"] for step in result["steps"]][-2:] == [
        "stats_ready_summed_bca", "analysis_ready_full_audit",
    ]
    assert worker.phase_progress.emit.call_args.args[:3] == ("post_processing_complete", 3, 3)


def test_prerequisite_failure_persists_reason_and_never_reports_completion(tmp_path):
    reason = "P9 / Neutral Angry has no retained data. Resolve the missing condition before post-processing."
    worker = _pipeline_without_qt(tmp_path, review_error=reason)

    worker.run()

    payload = worker.finished.emit.call_args.args[0]
    phases = [call.args for call in worker.phase_progress.emit.call_args_list]
    assert payload["ok"] is False
    assert payload["failure_reason"] == reason
    assert [(phase, completed) for phase, completed, _, _ in phases] == [
        ("frequency_domain_qc", 0), ("post_processing_failed", 0),
    ]
    manifest = json.loads((tmp_path / "project.json").read_text(encoding="utf-8"))
    state = manifest["tools"]["frequency_domain_qc"]
    assert state["downstream_outputs_stale"] is True
    assert reason in state["stale_reason"]


@pytest.mark.parametrize("outcome", ["complete", "review_pause", "review_error"])
def test_validation_scope_closes_when_post_processing_releases_workbooks_or_pauses(tmp_path, outcome):
    from Main_App.processing.post_processing_context import (
        CACHE_MISS, cached_validation, remember_validation, validation_scope_active,
    )

    worker = _pipeline_without_qt(tmp_path)
    stages = []

    def review():
        assert validation_scope_active()
        remember_validation("test", "review", {"current": True}, files=())
        stages.append("review")
        if outcome == "review_error":
            raise ValueError("Review failed")
        return {"review_required": outcome == "review_pause"}

    original_export = worker._run_stats_ready_export

    def export(*args):
        assert cached_validation("test", "review") == {"current": True}
        stages.append("export")
        return original_export(*args)

    worker._run_frequency_domain_qc_review = review
    worker._run_stats_ready_export = export
    worker.run()

    assert stages == (["review", "export"] if outcome == "complete" else ["review"])
    assert not validation_scope_active()
    assert cached_validation("test", "review") is CACHE_MISS


@pytest.mark.parametrize("failed_step", ["full_fft_provenance", "harmonic_selection", "stats_ready_summed_bca"])
def test_required_output_failure_preserves_progress_and_upstream_independence(tmp_path, failed_step):
    worker = _pipeline_without_qt(tmp_path, failed_step=failed_step)

    worker.run()

    payload = worker.finished.emit.call_args.args[0]
    phases = [call.args for call in worker.phase_progress.emit.call_args_list]
    assert payload["ok"] is False
    assert payload["failure_reason"] == f"{failed_step} failed"
    assert phases[-1][0] == "post_processing_failed"
    assert all(phase != "post_processing_complete" and completed < total for phase, completed, total, _ in phases)
    manifest = json.loads((tmp_path / "project.json").read_text(encoding="utf-8"))
    state = manifest["tools"].get("frequency_domain_qc", {})
    assert bool(state.get("downstream_outputs_stale")) is (failed_step == "full_fft_provenance")
    assert manifest["tools"]["processing"]["full_fft_provenance"]["status"] == "current"


@pytest.mark.parametrize("failed_step", ["full_fft_provenance", "harmonic_selection"])
def test_failed_prerequisite_stops_consumers_and_emits_one_root_failure(tmp_path, failed_step):
    worker = _pipeline_without_qt(tmp_path, failed_step=failed_step)
    for name in (
        "_run_harmonic_selection", "_run_stats_ready_export",
        "_run_analysis_ready_export",
    ):
        setattr(worker, name, Mock(wraps=getattr(worker, name)))

    worker.run()

    worker.finished.emit.assert_called_once()
    payload = worker.finished.emit.call_args.args[0]
    assert payload["failure_reason"] == f"{failed_step} failed"
    assert payload["ok"] is False
    expected_steps = ["frequency_domain_qc", "full_fft_provenance"]
    if failed_step == "harmonic_selection":
        expected_steps.append("harmonic_selection")
        worker._run_harmonic_selection.assert_called_once()
    else:
        worker._run_harmonic_selection.assert_not_called()
    assert [step["name"] for step in payload["steps"]] == expected_steps
    worker._run_stats_ready_export.assert_not_called()
    worker._run_analysis_ready_export.assert_not_called()
    worker._activate_artifact_freshness.assert_not_called()
    assert worker._dataset_index is None
    assert worker._harmonic_selection_metadata is None


@pytest.mark.parametrize("failed_step", ["stats_ready_summed_bca", "analysis_ready_full_audit"])
def test_failed_workbook_export_does_not_suppress_its_sibling(tmp_path, failed_step):
    worker = _pipeline_without_qt(tmp_path, failed_step=failed_step)

    worker.run()

    worker.finished.emit.assert_called_once()
    payload = worker.finished.emit.call_args.args[0]
    assert payload["ok"] is False
    workbook_ids = {"stats_ready_summed_bca", "analysis_ready_full_audit"}
    assert {step["name"] for step in payload["steps"]} == {
        "frequency_domain_qc", "full_fft_provenance", "harmonic_selection", *workbook_ids,
    }
    assert {step["name"] for step in payload["steps"] if not step["ok"]} == {failed_step}


def test_optional_export_failure_leaves_frequency_outputs_current(tmp_path):
    worker = _pipeline_without_qt(tmp_path, failed_step="analysis_ready_full_audit")

    worker.run()

    payload = worker.finished.emit.call_args.args[0]
    phase, completed, total, _message = worker.phase_progress.emit.call_args.args
    assert payload["ok"] is False
    assert payload["failure_reason"] == ""
    assert (phase, completed, total) == ("post_processing_complete", 3, 3)
    manifest = json.loads((tmp_path / "project.json").read_text(encoding="utf-8"))
    assert not manifest["tools"].get("frequency_domain_qc", {}).get("downstream_outputs_stale")


@pytest.mark.parametrize("repeated_session", [False, True])
@pytest.mark.parametrize("selection_resume", [False, True])
def test_full_audit_failure_is_required_only_for_repeated_stats(
    tmp_path, repeated_session, selection_resume,
):
    worker = _pipeline_without_qt(
        tmp_path, failed_step="analysis_ready_full_audit", repeated_session=repeated_session,
    )
    worker._resume_from_selection = selection_resume
    worker._run_frequency_domain_qc_review = Mock(wraps=worker._run_frequency_domain_qc_review)
    worker._run_harmonic_selection = Mock(wraps=worker._run_harmonic_selection)
    before = (tmp_path / "project.json").read_bytes()

    worker.run()

    worker.finished.emit.assert_called_once()
    result = worker.finished.emit.call_args.args[0]
    assert result["ok"] is False
    assert bool(result["failure_reason"]) is repeated_session
    phase, completed, total, message = worker.phase_progress.emit.call_args.args
    if repeated_session:
        assert "Repeated-session Stats requires the full-audit" in result["failure_reason"]
        assert "analysis_ready_full_audit failed" in result["failure_reason"]
        assert phase == "post_processing_failed"
        assert completed < total
        assert "incomplete" in message
        assert "optional" not in message
    else:
        assert (phase, completed, total) == ("post_processing_complete", 3, 3)
        assert "optional" in message
    if selection_resume:
        worker._run_frequency_domain_qc_review.assert_not_called()
        worker._run_harmonic_selection.assert_not_called()
    # An export failure cannot invalidate already accepted upstream evidence.
    assert (tmp_path / "project.json").read_bytes() == before
    assert worker._dataset_index is None
    assert worker._harmonic_selection_metadata is None


@pytest.mark.parametrize("error_type", [MemoryError, AttributeError, IndexError])
@pytest.mark.parametrize("selection_resume", [False, True])
def test_unexpected_stage_error_still_finishes_and_releases_caches(
    tmp_path, error_type, selection_resume,
):
    from Main_App.processing.post_processing_context import validation_scope_active

    worker = _pipeline_without_qt(tmp_path)
    worker._resume_from_selection = selection_resume
    failed_stage = "_run_stats_ready_export" if selection_resume else "_run_frequency_domain_qc_review"
    setattr(worker, failed_stage, Mock(side_effect=error_type("Injected stage failure")))

    worker.run()

    worker.finished.emit.assert_called_once()
    payload = worker.finished.emit.call_args.args[0]
    assert payload["ok"] is False
    assert payload["failure_reason"] == "Injected stage failure"
    assert payload["steps"][-1]["message"] == "Injected stage failure"
    assert not validation_scope_active()
    assert worker._dataset_index is None
    assert worker._harmonic_selection_metadata is None
    assert worker._selection_fingerprint is None
    assert worker._artifact_targets == worker._artifact_archives == {}


def test_failure_status_error_cannot_suppress_worker_completion(tmp_path, monkeypatch):
    from Main_App.processing import frequency_domain_qc

    worker = _pipeline_without_qt(tmp_path, review_error="Original review failure")
    monkeypatch.setattr(
        frequency_domain_qc, "mark_frequency_domain_outputs_stale",
        Mock(side_effect=MemoryError("Failure status allocation failed")),
    )

    worker.run()

    worker.finished.emit.assert_called_once()
    payload = worker.finished.emit.call_args.args[0]
    assert payload["ok"] is False
    assert payload["failure_reason"] == "Original review failure"


def test_setup_import_failure_still_finishes(tmp_path, monkeypatch):
    worker = _pipeline_without_qt(tmp_path)
    worker._run_frequency_domain_qc_review = Mock()
    monkeypatch.setitem(sys.modules, "Main_App.processing.condition_interpolation_executor", None)

    worker.run()

    worker.finished.emit.assert_called_once()
    payload = worker.finished.emit.call_args.args[0]
    assert payload["ok"] is False
    assert "condition_interpolation_executor" in payload["failure_reason"]
    assert payload["requires_processing"] is False
    worker._run_frequency_domain_qc_review.assert_not_called()


def test_processing_required_error_retains_existing_recovery_signal(tmp_path):
    from Main_App.processing.condition_interpolation_executor import ConditionInterpolationProcessingRequired

    worker = _pipeline_without_qt(tmp_path)
    worker._run_frequency_domain_qc_review = Mock(
        side_effect=ConditionInterpolationProcessingRequired("Processing required"),
    )

    worker.run()

    worker.finished.emit.assert_called_once()
    payload = worker.finished.emit.call_args.args[0]
    assert payload["ok"] is False
    assert payload["failure_reason"] == "Processing required"
    assert payload["requires_processing"] is True
