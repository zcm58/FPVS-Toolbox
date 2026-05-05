import numpy as np
from scipy import stats

from Tools.Stats.analysis import posthoc_tests as posthoc_module


def _sign(val: float) -> int:
    if val == 0 or np.isnan(val):
        return 0
    return 1 if val > 0 else -1


def test_paired_dz_sign_matches_mean_and_t():
    a = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    b = np.array([1.5, 1.8, 2.1, 3.2, 3.9])
    diff = a - b

    dz, _, _ = posthoc_module._paired_effect_size_and_ci(diff)
    t_stat, _ = stats.ttest_rel(a, b)

    mean_sign = _sign(float(diff.mean()))
    dz_sign = _sign(float(dz))
    t_sign = _sign(float(t_stat))

    assert mean_sign == dz_sign == t_sign
