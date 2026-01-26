"""Debug helper for paired Cohen's dz sign consistency."""
from __future__ import annotations

from typing import Iterable

import numpy as np
from scipy import stats


def report_paired_signs(a: Iterable[float], b: Iterable[float]) -> None:
    """Print mean/SD of paired diffs, dz, and paired t-stat for arrays A and B."""
    a_arr = np.asarray(a, dtype=float)
    b_arr = np.asarray(b, dtype=float)
    if a_arr.shape != b_arr.shape:
        raise ValueError("A and B must have the same shape for paired comparisons.")
    diff = a_arr - b_arr
    mean_diff = float(np.mean(diff))
    sd_diff = float(np.std(diff, ddof=1))
    dz = mean_diff / sd_diff if sd_diff != 0 else np.nan
    t_stat, p_val = stats.ttest_rel(a_arr, b_arr)

    print("Paired sign check")
    print(f"mean(A-B) = {mean_diff:.6f}")
    print(f"sd(A-B, ddof=1) = {sd_diff:.6f}")
    print(f"dz = {dz:.6f}")
    print(f"t = {t_stat:.6f} (p = {p_val:.6f})")


if __name__ == "__main__":
    sample_a = [1.1, 1.4, 1.6, 1.9, 2.0]
    sample_b = [1.4, 1.3, 1.2, 1.8, 1.7]
    report_paired_signs(sample_a, sample_b)
