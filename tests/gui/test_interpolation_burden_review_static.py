from __future__ import annotations

import ast
from pathlib import Path


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


def test_dialog_starts_with_no_decision_and_requires_reason_before_accept() -> None:
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
    assert "reason.setPlaceholderText('Required review reason')" in source
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
