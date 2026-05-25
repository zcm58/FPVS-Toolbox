from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

from tests import repo_root


def _ensure_package(name: str, path: Path) -> None:
    if name in sys.modules:
        return
    module = types.ModuleType(name)
    module.__path__ = [str(path)]
    sys.modules[name] = module


def _load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module spec for {module_name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


ROOT = repo_root()
SRC = ROOT / "src"
TOOLS = SRC / "Tools"
STATS = TOOLS / "Stats"
_ensure_package("Tools", TOOLS)
_ensure_package("Tools.Stats", STATS)
_ensure_package("Tools.Stats.analysis", STATS / "analysis")

dv_policies = _load_module(
    "Tools.Stats.analysis.dv_policies", STATS / "analysis" / "dv_policies.py"
)
fixed_predefined = _load_module(
    "Tools.Stats.analysis.dv_policy_fixed_predefined",
    STATS / "analysis" / "dv_policy_fixed_predefined.py",
)


def test_fixed_predefined_policy_exports_selection_builder() -> None:
    assert hasattr(fixed_predefined, "build_fixed_harmonic_selection")


def test_dv_policies_exports_fixed_predefined_policy_name() -> None:
    assert hasattr(dv_policies, "FIXED_PREDEFINED_POLICY_NAME")
    assert isinstance(dv_policies.FIXED_PREDEFINED_POLICY_NAME, str)
    assert dv_policies.FIXED_PREDEFINED_POLICY_NAME
