from __future__ import annotations

import subprocess
import sys

from tests import repo_root


ROOT = repo_root()


def _probe_compat_symbol(expression: str) -> None:
    """Probe private Stats compatibility modules without polluting pytest imports."""

    code = f"""
import importlib.util
from pathlib import Path
import sys
import types

root = Path.cwd()
sys.path.insert(0, str(root / 'src'))
stats = root / 'src' / 'Tools' / 'Stats'
for name, path in (
    ('Tools', root / 'src' / 'Tools'),
    ('Tools.Stats', stats),
    ('Tools.Stats.analysis', stats / 'analysis'),
):
    module = types.ModuleType(name)
    module.__path__ = [str(path)]
    sys.modules[name] = module

def load(module_name, path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'Unable to load {{module_name}}')
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module

dv_policies = load(
    'Tools.Stats.analysis.dv_policies',
    stats / 'analysis' / 'dv_policies.py',
)
fixed_predefined = load(
    'Tools.Stats.analysis.dv_policy_fixed_predefined',
    stats / 'analysis' / 'dv_policy_fixed_predefined.py',
)
assert {expression}
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_fixed_predefined_policy_exports_selection_builder() -> None:
    _probe_compat_symbol(
        "hasattr(fixed_predefined, 'build_fixed_harmonic_selection')"
    )


def test_dv_policies_exports_fixed_predefined_policy_name() -> None:
    _probe_compat_symbol(
        "hasattr(dv_policies, 'FIXED_PREDEFINED_POLICY_NAME') "
        "and isinstance(dv_policies.FIXED_PREDEFINED_POLICY_NAME, str) "
        "and bool(dv_policies.FIXED_PREDEFINED_POLICY_NAME)"
    )
