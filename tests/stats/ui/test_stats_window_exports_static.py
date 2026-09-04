from __future__ import annotations

import ast
from pathlib import Path


EXPORTS_PATH = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "Tools"
    / "Stats"
    / "ui"
    / "stats_window_exports.py"
)


def test_managed_stats_ready_export_does_not_read_legacy_bca_ceiling() -> None:
    tree = ast.parse(EXPORTS_PATH.read_text(encoding="utf-8"))
    mixin = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "StatsWindowExportsMixin"
    )
    method = next(
        node
        for node in mixin.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "on_export_stats_ready_clicked"
    )
    source = ast.unparse(method)

    assert "bca_upper_limit" not in source
    assert "max_freq=" not in source
    assert "project_root=str(self._project_path)" in source
