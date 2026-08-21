from __future__ import annotations

import ast
from pathlib import Path


WORKER_PATH = (
    Path(__file__).resolve().parents[2] / "src/Tools/Ratio_Calculator/worker.py"
)


def test_worker_emits_terminal_signal_from_finally() -> None:
    tree = ast.parse(WORKER_PATH.read_text(encoding="utf-8"))
    worker_class = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "RatioCalculatorWorker"
    )
    declared_signals = {
        target.id
        for statement in worker_class.body
        if isinstance(statement, ast.Assign)
        and isinstance(statement.value, ast.Call)
        and isinstance(statement.value.func, ast.Name)
        and statement.value.func.id == "Signal"
        for target in statement.targets
        if isinstance(target, ast.Name)
    }
    assert "terminal" in declared_signals

    run_method = next(
        node
        for node in worker_class.body
        if isinstance(node, ast.FunctionDef) and node.name == "run"
    )
    run_try = next(node for node in run_method.body if isinstance(node, ast.Try))
    assert any(
        isinstance(node, ast.Call) and ast.unparse(node) == "self.terminal.emit()"
        for statement in run_try.finalbody
        for node in ast.walk(statement)
    )
