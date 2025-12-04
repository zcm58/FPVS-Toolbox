# noise_utils.py

"""
This file is used to calculate SNR using the +/- 10 bins method used in several publications:

1: Dzhelyova, M., & Rossion, B. (2014a). The effect of parametric stimulus variation on individual face discrimination
   indexed by fast periodic visual stimulation. Journal of Vision, 14(12), 1–18. https://doi.org/10.1167/14.12.22

2: Georges, C., Retter, T. L., & Rossion, B. (2020). Face-selective responses in the human brain: A periodic
   stimulation approach. NeuroImage, 214, 116703. https://doi.org/10.1016/j.neuroimage.2020.116703

3: Liu-Shuang, J., Norcia, A. M., & Rossion, B. (2014). An objective index of individual face discrimination in the
   right occipito-temporal cortex by means of fast periodic oddball stimulation. Neuropsychologia, 52, 57–72.
   https://doi.org/10.1016/j.neuropsychologia.2013.10.022

4: Poncet, F., Rossion, B., & Jacques, C. (2019). Evidence for the existence of a face-selective neural response in
   the human brain with fast periodic visual stimulation. NeuroImage, 189, 150–162.
   https://doi.org/10.1016/j.neuroimage.2019.01.021

"""
from __future__ import annotations

from typing import Tuple

import numpy as np

__all__ = ["compute_noise_stats_for_bin"]


def compute_noise_stats_for_bin(
    amplitudes: np.ndarray,
    target_idx: int,
    window_size: int = 10,
    min_bins: int = 4,
) -> Tuple[float, float]:
    """
    Compute noise mean and std around a target FFT bin using neighboring bins.

    Logic:
    - Take a ±window_size-bin window around target_idx.
    - Exclude the target bin and its immediate neighbors (target_idx-1, target_idx+1).
    - If there are fewer than `min_bins` candidate bins -> return (0.0, 0.0).
    - From the remaining bins, remove one max and one min value (two most extreme).
    - Return (mean, std) of the remaining noise amplitudes.

    Parameters
    ----------
    amplitudes
        1-D array of FFT amplitudes for a single channel.
    target_idx
        Index of the FFT bin corresponding to the frequency of interest.
    window_size
        Number of bins on each side of target_idx to consider (±window_size).
    min_bins
        Minimum number of candidate noise bins (before extreme-value removal)
        required to compute noise statistics.

    Returns
    -------
    (noise_mean, noise_std)
        Mean and standard deviation of the noise amplitudes. (0.0, 0.0) if
        there are too few bins.
    """
    num_bins = amplitudes.shape[0]
    low = max(0, target_idx - window_size)
    high = min(num_bins - 1, target_idx + window_size)

    # Exclude target and its immediate neighbors
    exclude = {target_idx - 1, target_idx, target_idx + 1}
    indices = [
        i
        for i in range(low, high + 1)
        if 0 <= i < num_bins and i not in exclude
    ]

    if len(indices) < min_bins:
        return 0.0, 0.0

    noise_vals = amplitudes[indices].astype(float)

    # Remove one max and one min (two most extreme values) if possible
    if noise_vals.size > 2:
        max_idx = int(noise_vals.argmax())
        min_idx = int(noise_vals.argmin())
        mask = np.ones(noise_vals.shape[0], dtype=bool)
        mask[max_idx] = False
        mask[min_idx] = False
        noise_vals = noise_vals[mask]

    if noise_vals.size == 0:
        return 0.0, 0.0

    noise_mean = float(noise_vals.mean())
    noise_std = float(noise_vals.std(ddof=0))
    return noise_mean, noise_std
