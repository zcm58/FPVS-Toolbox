from __future__ import annotations

import ast
from pathlib import Path


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


def test_default_source_mode_is_time_domain_source_psd_only() -> None:
    tree = _worker_tree()
    modes_assignment = next(
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "SOURCE_OUTPUT_MODES" for target in node.targets)
    )

    assert isinstance(modes_assignment.value, ast.Tuple)
    assert [element.value for element in modes_assignment.value.elts if isinstance(element, ast.Constant)] == [
        "l2_mne_source_psd"
    ]


def test_source_psd_is_the_single_fourth_phase_with_time_domain_status() -> None:
    tree = _worker_tree()
    phase_count_assignment = next(
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "POST_PROCESSING_PHASE_COUNT" for target in node.targets)
    )
    phase_map_assignment = next(
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "_SOURCE_PHASE_BY_MODE" for target in node.targets)
    )
    source_maps_method = _class_method(tree, "_run_source_maps")
    status_text = {
        node.value
        for node in ast.walk(source_maps_method)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }

    assert ast.unparse(phase_count_assignment.value) == "3 + len(SOURCE_OUTPUT_MODES)"
    assert ast.literal_eval(phase_map_assignment.value) == {"l2_mne_source_psd": "l2_mne_source_maps"}
    assert any("Hauk-informed time-domain source-space maps" in message for message in status_text)


def test_stats_and_source_exports_are_unconditional_sibling_steps() -> None:
    tree = _worker_tree()
    run_method = _class_method(tree, "run")
    try_node = next(node for node in run_method.body if isinstance(node, ast.Try))

    stats_index = next(
        index
        for index, statement in enumerate(try_node.body)
        if isinstance(statement, ast.Assign)
        and isinstance(statement.value, ast.Call)
        and isinstance(statement.value.func, ast.Attribute)
        and statement.value.func.attr == "_run_stats_ready_export"
    )
    source_index = next(
        index
        for index, statement in enumerate(try_node.body)
        if isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Call)
        and isinstance(statement.value.func, ast.Attribute)
        and statement.value.func.attr == "extend"
        and statement.value.args
        and isinstance(statement.value.args[0], ast.Call)
        and isinstance(statement.value.args[0].func, ast.Attribute)
        and statement.value.args[0].func.attr == "_run_source_maps"
    )

    assert source_index > stats_index


def test_source_psd_exporter_is_loaded_through_the_expected_seam() -> None:
    tree = _worker_tree()
    loader = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_load_source_psd_export_api"
    )
    import_node = next(node for node in loader.body if isinstance(node, ast.ImportFrom))

    assert import_node.module == "Tools.LORETA_Visualizer.source_producers.project_l2_mne_hauk_source_psd_export"
    assert {alias.name for alias in import_node.names} == {
        "default_project_l2_mne_hauk_source_psd_output_dir",
        "write_project_l2_mne_hauk_source_psd_payloads",
    }

    source_mode_method = _class_method(tree, "_run_source_map_mode")
    writer_call = next(
        node
        for node in ast.walk(source_mode_method)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "write_payloads"
    )
    assert {keyword.arg for keyword in writer_call.keywords} == {
        "project",
        "project_root",
        "include_flagged_subjects",
        "allow_fetch_fsaverage",
        "progress_callback",
    }

    source_text = WORKER_PATH.read_text(encoding="utf-8")
    assert "project_l2_mne_hauk_zscore_export" not in source_text
    assert "project_eloreta_volume_export" not in source_text
