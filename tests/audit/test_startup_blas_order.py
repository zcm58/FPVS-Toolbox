"""Check normal startup ordering without executing Qt or diagnostic dispatch."""

import ast

from tests import repo_root


def test_normal_startup_limits_blas_before_application_imports() -> None:
    source = (repo_root() / "src" / "main.py").read_text(encoding="utf-8")
    statements = ast.parse(source).body
    limit_calls = [
        statement
        for statement in statements
        if isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Call)
        and isinstance(statement.value.func, ast.Name)
        and statement.value.func.id == "set_blas_threads_single_process"
    ]
    assert len(limit_calls) == 1

    # Frozen diagnostic dispatch intentionally exits before normal startup.
    # Its guarded import is not part of the module-level GUI startup path.
    application_imports = [
        statement
        for statement in statements
        if isinstance(statement, ast.ImportFrom)
        and (statement.module or "").split(".")[0] in {"Main_App", "PySide6"}
        and statement.module != "Main_App.workers.mp_env"
    ]
    assert application_imports
    assert all(limit_calls[0].lineno < statement.lineno for statement in application_imports)
