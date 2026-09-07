"""Exercise preflight reuse decisions without importing or executing Qt."""

from __future__ import annotations

import ast
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from Main_App.projects.preprocessing_settings import (
    normalize_manual_excluded_participant_conditions,
    normalize_manual_excluded_recording_conditions,
)

WORKFLOW = Path(__file__).resolve().parents[2] / "src/Main_App/gui/preprocessing_qc_workflow.py"


def _reuse_namespace():
    tree = ast.parse(WORKFLOW.read_text(encoding="utf-8"))
    helper = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_condition_review_scan_identity")
    workflow = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "run_preprocessing_qc_workflow")
    reuse_branch = next(
        node for node in ast.walk(workflow) if isinstance(node, ast.If)
        and any(isinstance(child, ast.Name) and child.id == "condition_review_identity" for child in ast.walk(node.test))
    )
    wrapper = ast.parse("def review_scan():\n    pass\n").body[0]
    wrapper.body = [deepcopy(reuse_branch), ast.Return(ast.Name("scan", ast.Load()))]
    # The branch assigns scan locally. Start with the completed initial scan.
    wrapper.body.insert(0, ast.Assign([ast.Name("scan", ast.Store())], ast.Name("initial_scan", ast.Load())))
    module = ast.Module(
        body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), helper, wrapper],
        type_ignores=[],
    )
    namespace = {
        "Path": Path,
        "deepcopy": deepcopy,
        "normalize_manual_excluded_participant_conditions": normalize_manual_excluded_participant_conditions,
        "normalize_manual_excluded_recording_conditions": normalize_manual_excluded_recording_conditions,
    }
    exec(compile(ast.fix_missing_locations(module), str(WORKFLOW), "exec"), namespace)
    return namespace


@pytest.mark.parametrize("change", ["none", "participant", "recording", "markers", "source", "missing"])
def test_only_changed_condition_selection_or_source_repeats_scan(tmp_path, change):
    source = tmp_path / "P1.bdf"
    source.write_bytes(b"source")
    infos = [SimpleNamespace(path=source)]
    params = {"manual_excluded_participant_conditions": {"P1": ["Neutral"]}}
    params["_fpvs_marker_review_decisions_by_file"] = {str(source): {"occurrence-1": {"decision": "retain"}}}
    namespace = _reuse_namespace()
    identity = namespace["_condition_review_scan_identity"](infos, params)
    if change == "participant":
        params["manual_excluded_participant_conditions"]["P1"].append("Oddball")
    elif change == "recording":
        params["manual_excluded_recording_conditions"] = {"P1-session2": ["Neutral"]}
    elif change == "markers":
        params["_fpvs_marker_review_decisions_by_file"][str(source)]["occurrence-1"]["decision"] = "exclude"
    elif change == "source":
        source.write_bytes(b"different source")
    elif change == "missing":
        source.unlink()
    calls = []
    initial = SimpleNamespace(cancelled=False)
    rescanned = SimpleNamespace(cancelled=False)

    def scan(*args, **kwargs):
        calls.append((args, kwargs))
        return rescanned

    namespace.update(
        active_infos=infos, params=params, condition_review_identity=identity,
        host=object(), group_labels={}, initial_scan=initial,
        _run_scan_embedded=scan,
    )
    actual = namespace["review_scan"]()
    assert actual is (initial if change == "none" else rescanned)
    assert len(calls) == (0 if change == "none" else 1)


@pytest.mark.parametrize("result", [None, SimpleNamespace(cancelled=True)])
def test_required_rescan_failure_blocks_continuation(result):
    namespace = _reuse_namespace()
    namespace.update(
        active_infos=[], params={}, condition_review_identity=None,
        host=object(), group_labels={}, initial_scan=SimpleNamespace(cancelled=False),
        _run_scan_embedded=lambda *_args, **_kwargs: result,
    )
    assert namespace["review_scan"]() is False


def test_unreadable_identity_never_allows_reuse(tmp_path):
    namespace = _reuse_namespace()
    assert namespace["_condition_review_scan_identity"]([SimpleNamespace(path=tmp_path / "missing.bdf")], {}) is None
