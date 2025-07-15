"""Helper utilities for SNR calculations used by the plot generator."""

from __future__ import annotations

from typing import Sequence, List

__all__ = ["calc_snr_matlab"]


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def calc_snr_matlab(amplitudes: Sequence[float]) -> List[float]:
    """Return MATLAB-style SNR values for each amplitude bin.

    Parameters
    ----------
    amplitudes:
        Sequence of FFT amplitude values ordered by increasing frequency.

    This mirrors the method used in some MATLAB FPVS scripts where a
    +/-12-bin window is taken around the target bin, the immediate
    neighbours (target\ ``\pm``\ 1) are removed, the maximum and minimum
    remaining values are dropped and the mean of the rest is used as the
    noise estimate.
    """

    amps = [float(a) for a in amplitudes]
    n_bins = len(amps)
    snr: List[float] = [0.0] * n_bins

    for idx in range(n_bins):
        low = max(0, idx - 12)
        high = min(n_bins - 1, idx + 12)
        neighbours = [amps[i] for i in range(low, high + 1)]

        for remove in sorted({idx - 1, idx, idx + 1}, reverse=True):
            if low <= remove <= high:
                neighbours.pop(remove - low)

        if not neighbours:
            snr[idx] = 0.0
            continue

        if len(neighbours) > 2:
            neighbours.remove(max(neighbours))
            neighbours.remove(min(neighbours))

        if neighbours:
            mean_noise = _mean(neighbours)
            snr[idx] = amps[idx] / mean_noise if mean_noise > 1e-12 else 0.0
        else:
            snr[idx] = 0.0

    return snr
