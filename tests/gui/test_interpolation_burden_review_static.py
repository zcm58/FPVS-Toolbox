from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Callable
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
DIALOG_PATH = (
    REPO_ROOT
    / "src"
    / "Main_App"
    / "gui"
    / "interpolation_burden_review_dialog.py"
)
WORKFLOW_PATH = REPO_ROOT / "src" / "Main_App" / "gui" / "processing_workflows.py"


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    return next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    )


def _method(tree: ast.Module, class_name: str, name: str) -> ast.FunctionDef:
    class_node = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    return next(
        node
        for node in class_node.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    )


def _call_lines(node: ast.AST, function_name: str) -> list[int]:
    return [
        call.lineno
        for call in ast.walk(node)
        if isinstance(call, ast.Call)
        and (
            isinstance(call.func, ast.Name)
            and call.func.id == function_name
            or isinstance(call.func, ast.Attribute)
            and call.func.attr == function_name
        )
    ]


def test_dialog_requires_explicit_decision_and_labels_reason_optional() -> None:
    tree = _tree(DIALOG_PATH)
    build_ui = _method(tree, "InterpolationBurdenReviewDialog", "_build_ui")
    validate = _method(
        tree,
        "InterpolationBurdenReviewDialog",
        "_validate_and_accept",
    )
    source = ast.unparse(build_ui)
    validate_source = ast.unparse(validate)

    assert "Choose Retain or Exclude" in source
    assert source.count("decision.addItem") == 3
    assert "decision.setCurrentIndex(0)" in source
    assert "reason.setPlaceholderText('Optional reason')" in source
    assert source.index("INTERPOLATION_BURDEN_SCOPE_RECORDING") < source.index(
        "INTERPOLATION_BURDEN_SCOPE_PARTICIPANT"
    )
    assert "self.cancel_button.clicked.connect(self.reject)" in source
    assert validate_source.index("self.choices()") < validate_source.index(
        "self.accept()"
    )


def test_workflow_review_gate_runs_after_report_and_before_post_processing() -> None:
    tree = _tree(WORKFLOW_PATH)
    finished = _function(tree, "on_processing_finished")

    report_line = min(_call_lines(finished, "export_processing_qc_summary"))
    review_line = min(
        _call_lines(finished, "_review_interpolation_burden_before_post_processing")
    )
    post_processing_line = min(
        _call_lines(finished, "_start_post_processing_pipeline_after_processing")
    )

    assert report_line < review_line < post_processing_line


def test_retain_all_changes_every_decision_without_submitting_or_editing_context() -> None:
    tree = _tree(DIALOG_PATH)
    build_ui = ast.unparse(_method(tree, "InterpolationBurdenReviewDialog", "_build_ui"))
    assert "self.retain_all_button.clicked.connect(self._retain_all)" in build_ui
    assert "interpolation_burden_review_retain_all" in build_ui
    method = _method(tree, "InterpolationBurdenReviewDialog", "_retain_all")
    namespace = {"INTERPOLATION_BURDEN_DECISION_RETAIN": "retain"}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(DIALOG_PATH), "exec"), namespace)
    controls = {str(row): Mock() for row in range(60)}
    for row, control in enumerate(controls.values()):
        # Find by item data, independently of the combo's item ordering.
        control.findData.return_value = row + 1
    reasons = {"first": "Review evidence"}
    scopes = {"first": "participant"}
    host = SimpleNamespace(
        _decision_controls=controls,
        _reason_controls=reasons,
        _scope_controls=scopes,
        error_banner=Mock(),
        _update_attention=Mock(),
        accept=Mock(),
        choices=Mock(),
    )
    namespace["_retain_all"](host)
    for row, control in enumerate(controls.values()):
        control.findData.assert_called_once_with("retain")
        control.setCurrentIndex.assert_called_once_with(row + 1)
    assert host._reason_controls == reasons
    assert host._scope_controls == scopes
    host.error_banner.hide.assert_called_once_with()
    host._update_attention.assert_called_once_with()
    host.accept.assert_not_called()
    host.choices.assert_not_called()


def test_workflow_cancel_and_invalid_evidence_return_a_blocking_result() -> None:
    tree = _tree(WORKFLOW_PATH)
    review_gate = _function(
        tree,
        "_review_interpolation_burden_before_post_processing",
    )
    source = ast.unparse(review_gate)

    assert "collect_interpolation_burden_review(project)" in source
    assert "dialog.exec() != QDialog.DialogCode.Accepted" in source
    assert "apply_interpolation_burden_review" in source
    assert "Downstream post-processing was skipped" in source
    assert any(
        isinstance(node, ast.Return)
        and isinstance(node.value, ast.Constant)
        and node.value.value is False
        for node in ast.walk(review_gate)
    )


@pytest.mark.parametrize("review_completed", [False, True])
def test_resume_checks_enabled_burden_review_before_launching_outputs(review_completed):
    resume = _function(_tree(WORKFLOW_PATH), "resume_post_processing")
    events = []
    namespace = {
        "Any": Any, "Callable": Callable,
        "_review_interpolation_burden_before_post_processing": lambda _host: events.append("review") or review_completed,
        "_set_resume_post_processing_pending": Mock(),
        "_start_post_processing_pipeline_after_processing": Mock(return_value=True),
        "logger": Mock(),
    }
    exec(compile(ast.Module(body=[resume], type_ignores=[]), str(WORKFLOW_PATH), "exec"), namespace)
    callback = Mock()
    host = SimpleNamespace(
        currentProject=object(),
        _set_controls_enabled=Mock(side_effect=lambda _value: events.append("controls")),
    )
    namespace[resume.name](host, on_finished=callback)
    if review_completed:
        assert events == ["review", "controls"]
        namespace["_start_post_processing_pipeline_after_processing"].assert_called_once()
        callback.assert_not_called()
    else:
        assert events == ["review"]
        namespace["_start_post_processing_pipeline_after_processing"].assert_not_called()
        namespace["_set_resume_post_processing_pending"].assert_called_once_with(host, True)
        assert "review was not completed" in host._post_processing_failure_reason
        callback.assert_called_once_with()
