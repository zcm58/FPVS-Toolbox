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
PIPELINE_PATH = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "Tools"
    / "Stats"
    / "ui"
    / "stats_window_pipeline.py"
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


def test_qc17_review_flags_do_not_become_stats_exclusion_reasons() -> None:
    tree = ast.parse(PIPELINE_PATH.read_text(encoding="utf-8"))
    mixin = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "StatsWindowPipelineMixin"
    )
    method = next(
        node
        for node in mixin.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_collect_excluded_reasons"
    )
    source = ast.unparse(method)

    assert "QC exclusion" not in source
    assert "qc_report.participants" not in source
    assert "manual exclusion" in source
    assert "required DV exclusion" in source


def test_individual_stats_exports_format_before_final_disk_write() -> None:
    tree = ast.parse(EXPORTS_PATH.read_text(encoding="utf-8"))
    mixin = next(node for node in tree.body if isinstance(node, ast.ClassDef))
    method = next(
        node for node in mixin.body
        if isinstance(node, ast.FunctionDef) and node.name == "export_results"
    )
    source = ast.unparse(method)
    assert "partial(export_formatted_stats_results, func, kind=kind)" in source
    assert "safe_export_call(" in source
    assert "apply_rm_anova_pvalue_number_formats(path)" not in source
    assert "apply_lmm_number_formats_and_metadata(path" not in source
    assert "apply_baseline_vs_zero_number_formats(path)" not in source
