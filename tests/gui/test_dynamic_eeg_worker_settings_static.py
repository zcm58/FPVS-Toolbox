"""Exercise current worker-setting resolution without loading Qt."""

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from Main_App.workers.mp_env import compute_dynamic_worker_ceiling


ROOT = Path(__file__).resolve().parents[2]


def _review_resolver():
    path = ROOT / "src/Main_App/gui/preprocessing_qc_workflow.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == "_review_worker_ceiling")
    namespace = {"compute_dynamic_worker_ceiling": lambda requested: compute_dynamic_worker_ceiling(
        requested, cpu_count=24,
    )}
    module = ast.Module(body=[ast.ImportFrom(
        module="__future__", names=[ast.alias(name="annotations")], level=0,
    ), function], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(path), "exec"), namespace)
    return namespace[function.name]


@pytest.mark.parametrize("current,legacy,stale,expected", [
    (12, 2, 4, 12), (2, 12, 16, 2), (0, 12, 4, 12),
    (0, "6", 4, 6), (0, None, 4, 23), (0, "invalid", 4, 23),
    (100, None, 4, 23),
])
def test_review_uses_current_project_ceiling_instead_of_previous_gui_run(current, legacy, stale, expected):
    host = SimpleNamespace(max_workers=stale, currentProject=SimpleNamespace(options={"max_workers": legacy}))
    assert _review_resolver()(host, {"max_parallel_workers_override": current}) == expected


def test_normal_and_startup_gui_use_dynamic_cpu_ceiling_without_ram_tiers():
    for relative in ("main_window.py", "processing_workflows.py"):
        tree = ast.parse((ROOT / "src/Main_App/gui" / relative).read_text(encoding="utf-8"))
        calls = [node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Name)]
        assert "compute_dynamic_worker_ceiling" in calls
        assert "compute_effective_max_workers" not in calls
        assert "get_ram_tier_recommendation" not in calls


def test_preflight_and_preparation_both_resolve_the_current_ceiling():
    path = ROOT / "src/Main_App/gui/preprocessing_qc_workflow.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for name in ("_run_scan_embedded", "_run_kurtosis_review_scan_embedded"):
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)
        calls = [node for node in ast.walk(function) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Name) and node.func.id == "_review_worker_ceiling"]
        assert len(calls) == 1


def test_settings_save_does_not_prompt_for_obsolete_ram_tier_override():
    path = ROOT / "src/Main_App/gui/settings_panel.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    owner = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "SettingsDialog")
    function = next(node for node in owner.body if isinstance(node, ast.FunctionDef)
                    and node.name == "_confirm_parallel_worker_override")
    namespace = {}
    module = ast.Module(body=[ast.ImportFrom(
        module="__future__", names=[ast.alias(name="annotations")], level=0,
    ), function], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(path), "exec"), namespace)
    assert namespace[function.name](object(), {"max_parallel_workers_override": 100}) is True
    literals = [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant)
                and isinstance(node.value, str)]
    assert "Maximum parallel workers (0 = automatic):" in literals
    assert not any("recommended for your RAM tier" in value for value in literals)
