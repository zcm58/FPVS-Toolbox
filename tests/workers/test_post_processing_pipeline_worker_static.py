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


def test_default_source_modes_are_time_domain_l2_then_eloreta() -> None:
    tree = _worker_tree()
    modes_assignment = next(
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "SOURCE_OUTPUT_MODES" for target in node.targets)
    )

    assert isinstance(modes_assignment.value, ast.Tuple)
    assert [element.value for element in modes_assignment.value.elts if isinstance(element, ast.Constant)] == [
        "l2_mne_source_psd",
        "eloreta_volume_source_psd",
    ]


def test_source_psd_modes_are_the_fourth_and_fifth_phases_with_time_domain_status() -> None:
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
    assert ast.literal_eval(phase_map_assignment.value) == {
        "l2_mne_source_psd": "l2_mne_source_maps",
        "eloreta_volume_source_psd": "eloreta_source_maps",
    }
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
        and statement.module == "Tools.Stats.io.xlsx_selected_reader"
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
    normal_close_index = next(
        index
        for index, statement in enumerate(try_node.body)
        if _is_named_method_call(statement, "cache_stack", "close")
    )
    source_maps_index = next(
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
    assert normal_close_index < source_maps_index
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
    run_method = _class_method(tree, "run")

    qc_source = ast.unparse(qc_method)
    harmonic_source = ast.unparse(harmonic_method)
    stats_source = ast.unparse(stats_method)
    assert (
        "self._dataset_index = load_project_dataset_index(project_root)"
        in qc_source
    )
    assert "dataset_index=self._dataset_index" in qc_source
    assert "dataset_index=self._dataset_index" in harmonic_source
    assert "dataset_index=self._dataset_index" in stats_source

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


def test_source_psd_exporters_are_loaded_through_separate_expected_seams() -> None:
    tree = _worker_tree()
    expected_loaders = {
        "_load_source_psd_export_api": (
            "Tools.LORETA_Visualizer.source_producers.project_l2_mne_hauk_source_psd_export",
            {
                "default_project_l2_mne_hauk_source_psd_output_dir",
                "write_project_l2_mne_hauk_source_psd_payloads",
            },
        ),
        "_load_eloreta_source_psd_export_api": (
            "Tools.LORETA_Visualizer.source_producers.project_eloreta_volume_hauk_source_psd_export",
            {
                "default_project_eloreta_volume_hauk_source_psd_output_dir",
                "write_project_eloreta_volume_hauk_source_psd_payloads",
            },
        ),
    }
    for loader_name, (module_name, imported_names) in expected_loaders.items():
        loader = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == loader_name
        )
        import_node = next(node for node in loader.body if isinstance(node, ast.ImportFrom))
        assert import_node.module == module_name
        assert {alias.name for alias in import_node.names} == imported_names

    source_mode_method = _class_method(tree, "_run_source_map_mode")
    writer_calls = [
        node
        for node in ast.walk(source_mode_method)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "write_payloads"
    ]
    assert len(writer_calls) == 2
    for writer_call in writer_calls:
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
