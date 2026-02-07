from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


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


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TOOLS = SRC / "Tools"
STATS = TOOLS / "Stats"
PYSIDE6 = STATS / "PySide6"
LEGACY = STATS / "Legacy"

_ensure_package("Tools", TOOLS)
_ensure_package("Tools.Stats", STATS)
_ensure_package("Tools.Stats.PySide6", PYSIDE6)
_ensure_package("Tools.Stats.Legacy", LEGACY)

dv_policies = _load_module(
    "Tools.Stats.PySide6.dv_policies", PYSIDE6 / "dv_policies.py"
)
group_harmonics = _load_module(
    "Tools.Stats.PySide6.group_harmonics", PYSIDE6 / "group_harmonics.py"
)


def test_group_harmonics_exports_compute_union_harmonics_by_roi() -> None:
    assert hasattr(group_harmonics, "compute_union_harmonics_by_roi")


def test_dv_policies_exports_group_mean_z_policy_name() -> None:
    assert hasattr(dv_policies, "GROUP_MEAN_Z_POLICY_NAME")
    assert isinstance(dv_policies.GROUP_MEAN_Z_POLICY_NAME, str)
    assert dv_policies.GROUP_MEAN_Z_POLICY_NAME
