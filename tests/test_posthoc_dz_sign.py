import importlib.util
from pathlib import Path

import numpy as np
from scipy import stats


def _load_posthoc_module():
    module_path = Path(__file__).resolve().parents[1] / "src" / "Tools" / "Stats" / "Legacy" / "posthoc_tests.py"
    spec = importlib.util.spec_from_file_location("posthoc_tests", module_path)
    if spec is None or spec.loader is None:
        raise ImportError("Failed to load posthoc_tests module for sign check.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sign(val: float) -> int:
    if val == 0 or np.isnan(val):
        return 0
    return 1 if val > 0 else -1


def test_paired_dz_sign_matches_mean_and_t():
    posthoc_module = _load_posthoc_module()
    a = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    b = np.array([1.5, 1.8, 2.1, 3.2, 3.9])
    diff = a - b

    dz, _, _ = posthoc_module._paired_effect_size_and_ci(diff)
    t_stat, _ = stats.ttest_rel(a, b)

    mean_sign = _sign(float(diff.mean()))
    dz_sign = _sign(float(dz))
    t_sign = _sign(float(t_stat))

    assert mean_sign == dz_sign == t_sign
