from __future__ import annotations

import ast
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
import json
import logging
from pathlib import Path
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


def test_stats_audit_and_source_steps_keep_their_pipeline_order() -> None:
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
    source_index = statement_call_index("_run_source_maps")

    assert stats_index < audit_index < source_index


def test_participant_keyed_loreta_steps_have_a_canonical_repeated_session_gate() -> None:
    tree = _worker_tree()
    gate_method = _class_method(tree, "_is_repeated_session_project")
    stats_method = _class_method(tree, "_run_stats_ready_export")
    source_method = _class_method(tree, "_run_source_maps")

    gate_source = ast.unparse(gate_method)
    stats_source = ast.unparse(stats_method)
    source_source = ast.unparse(source_method)
    assert "from Main_App.projects import project_recording_context" in gate_source
    assert "project_recording_context(self._project).is_repeated_session" in gate_source
    assert "if self._is_repeated_session_project()" in stats_source
    assert "if self._is_repeated_session_project()" in source_source
    assert "_REPEATED_SESSION_STATS_READY_SKIP_MESSAGE" in stats_source
    assert "_REPEATED_SESSION_SOURCE_SKIP_MESSAGE" in source_source


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
    normal_close_index = min(
        statement.lineno
        for statement in ast.walk(try_node)
        if _is_named_method_call(statement, "cache_stack", "close")
    )
    source_maps_index = next(
        statement.lineno
        for statement in ast.walk(try_node)
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


def _pipeline_without_qt(tmp_path, *, failed_step="", review_error="", repeated_session=False):
    """Run the production orchestration with exporter/signal doubles and no Qt."""

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

    def source_maps(_root):
        worker._emit_phase_progress("l2_mne_source_maps", 4, "Source maps")
        worker._emit_phase_progress("eloreta_source_maps", 5, "Source maps")
        return [result("l2_mne_source_psd"), result("eloreta_volume_source_psd")]

    worker._run_source_maps = source_maps
    return worker


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
def test_validation_scope_ends_before_sources_and_on_every_review_exit(tmp_path, outcome):
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
    original_sources = worker._run_source_maps

    def export(*args):
        assert cached_validation("test", "review") == {"current": True}
        stages.append("export")
        return original_export(*args)

    def sources(*args):
        assert not validation_scope_active()
        assert cached_validation("test", "review") is CACHE_MISS
        stages.append("sources")
        return original_sources(*args)

    worker._run_frequency_domain_qc_review = review
    worker._run_stats_ready_export = export
    worker._run_source_maps = sources
    worker.run()

    assert stages == (["review", "export", "sources"] if outcome == "complete" else ["review"])
    assert not validation_scope_active()
    assert cached_validation("test", "review") is CACHE_MISS


@pytest.mark.parametrize("fail_second_mode", [False, True])
def test_source_modes_share_one_compatibility_scope_and_release_it(tmp_path, monkeypatch, fail_second_mode):
    from Tools.LORETA_Visualizer.source_producers import source_psd_cache

    worker = _pipeline_without_qt(tmp_path)
    namespace = worker.run.__func__.__globals__
    method = _class_method(_worker_tree(), "_run_source_maps")
    module = ast.Module(body=[method], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(WORKER_PATH), "exec"), namespace)
    worker._is_repeated_session_project = lambda: False
    worker._pipeline_steps = []
    worker._emit_progress = Mock()
    state = {"entries": 0, "active": False}
    modes = []

    @contextmanager
    def scope():
        state.update(entries=state["entries"] + 1, active=True)
        try:
            yield
        finally:
            state["active"] = False

    def export(_root, mode):
        assert state["active"]
        modes.append(mode)
        if fail_second_mode and len(modes) == 2:
            raise ValueError("Second source export failed")
        return mode

    monkeypatch.setattr(source_psd_cache, "source_psd_cache_scope", scope)
    worker._run_source_map_mode = export
    run_sources = MethodType(namespace["_run_source_maps"], worker)
    if fail_second_mode:
        with pytest.raises(ValueError, match="Second source export failed"):
            run_sources(tmp_path)
    else:
        assert run_sources(tmp_path) == ["l2_mne_source_psd", "eloreta_volume_source_psd"]
    assert modes == ["l2_mne_source_psd", "eloreta_volume_source_psd"]
    assert state == {"entries": 1, "active": False}


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
        "_run_analysis_ready_export", "_run_source_maps",
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
    worker._run_source_maps.assert_not_called()
    worker._activate_artifact_freshness.assert_not_called()
    assert worker._dataset_index is None
    assert worker._harmonic_selection_metadata is None


@pytest.mark.parametrize("failed_step", ["stats_ready_summed_bca", "analysis_ready_full_audit"])
def test_failed_sibling_export_still_runs_source_maps(tmp_path, failed_step):
    worker = _pipeline_without_qt(tmp_path, failed_step=failed_step)
    worker._run_source_maps = Mock(wraps=worker._run_source_maps)

    worker.run()

    worker._run_source_maps.assert_called_once_with(tmp_path.resolve())
    worker.finished.emit.assert_called_once()
    payload = worker.finished.emit.call_args.args[0]
    assert payload["ok"] is False
    assert {step["name"] for step in payload["steps"] if step["ok"]}.issuperset(
        {"full_fft_provenance", "harmonic_selection", "l2_mne_source_psd", "eloreta_volume_source_psd"}
    )


@pytest.mark.parametrize("failed_step", ["analysis_ready_full_audit", "l2_mne_source_psd", "eloreta_volume_source_psd"])
def test_optional_export_failure_leaves_frequency_outputs_current(tmp_path, failed_step):
    worker = _pipeline_without_qt(tmp_path, failed_step=failed_step)

    worker.run()

    payload = worker.finished.emit.call_args.args[0]
    phase, completed, total, _message = worker.phase_progress.emit.call_args.args
    assert payload["ok"] is False
    assert payload["failure_reason"] == ""
    assert (phase, completed, total) == ("post_processing_complete", 5, 5)
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
        assert (phase, completed, total) == ("post_processing_complete", 5, 5)
        assert "optional" in message
    if selection_resume:
        worker._run_frequency_domain_qc_review.assert_not_called()
        worker._run_harmonic_selection.assert_not_called()
    # An export failure cannot invalidate already accepted upstream evidence.
    assert (tmp_path / "project.json").read_bytes() == before
    assert worker._dataset_index is None
    assert worker._harmonic_selection_metadata is None


def test_exception_after_core_outputs_does_not_report_a_required_output_failure(tmp_path):
    worker = _pipeline_without_qt(tmp_path)
    worker._run_source_maps = Mock(side_effect=RuntimeError("Optional source export failed"))

    worker.run()

    payload = worker.finished.emit.call_args.args[0]
    phase, completed, total, _message = worker.phase_progress.emit.call_args.args
    assert payload["ok"] is False
    assert payload["failure_reason"] == ""
    assert payload["steps"][-1]["message"] == "Optional source export failed"
    assert (phase, completed, total) == ("post_processing_complete", 5, 5)
