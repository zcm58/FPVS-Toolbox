# full_snr.py
# -*- coding: utf-8 -*-
"""Utility for computing full-spectrum SNR values.

This module mirrors the FFT and SNR logic from :mod:`Main_App.post_process`
but exposes a helper that computes the Signal-to-Noise Ratio for **all** FFT
bins using a sliding-window estimate of the noise floor.

The resulting values can be saved to Excel alongside other metrics.
"""

from __future__ import annotations

from typing import Sequence

import numpy as np
import pandas as pd

__all__ = [
    "compute_full_snr_df",
    "compute_full_snr",
    "compute_full_snr_from_amplitudes",
    "compute_full_snr_prefix_from_amplitudes",
]


def _fft_amplitudes(data_uv: np.ndarray) -> np.ndarray:
    num_times = data_uv.shape[1]
    num_bins = num_times // 2 + 1
    fft_spectrum = np.fft.fft(data_uv, axis=1)
    return np.abs(fft_spectrum[:, :num_bins]) / num_times * 2


def _compute_snr_matrix_for_amplitudes(
    amplitudes: np.ndarray,
    window_size: int = 10,
) -> np.ndarray:
    """Return full-spectrum SNR using the shared +/-bin noise rule."""
    amplitudes = np.asarray(amplitudes, dtype=float)
    num_channels, num_bins = amplitudes.shape
    noise_sum = np.zeros((num_channels, num_bins), dtype=amplitudes.dtype)
    noise_min = np.full((num_channels, num_bins), np.inf, dtype=amplitudes.dtype)
    noise_max = np.full((num_channels, num_bins), -np.inf, dtype=amplitudes.dtype)
    counts = np.zeros(num_bins, dtype=np.intp)

    for offset in range(-window_size, window_size + 1):
        if -1 <= offset <= 1:
            continue
        if offset < 0:
            if num_bins + offset <= 0:
                continue
            source = amplitudes[:, : num_bins + offset]
            dest = slice(-offset, num_bins)
        else:
            if num_bins - offset <= 0:
                continue
            source = amplitudes[:, offset:]
            dest = slice(0, num_bins - offset)

        if source.shape[1] == 0:
            continue

        noise_sum[:, dest] += source
        min_slice = noise_min[:, dest]
        max_slice = noise_max[:, dest]
        np.minimum(min_slice, source, out=min_slice)
        np.maximum(max_slice, source, out=max_slice)
        counts[dest] += 1

    # Convert the sum to the trimmed mean without changing the arithmetic
    # order. Bins with too few neighbors are excluded from the final ratio.
    enough_bins = counts >= 4
    np.subtract(noise_sum, noise_min, out=noise_sum, where=enough_bins)
    np.subtract(noise_sum, noise_max, out=noise_sum, where=enough_bins)
    np.divide(noise_sum, counts - 2, out=noise_sum, where=enough_bins)

    return np.divide(
        amplitudes,
        noise_sum,
        out=np.zeros_like(amplitudes),
        where=enough_bins & (noise_sum > 1e-12),
    )


def compute_full_snr_df(
    data_uv: np.ndarray,
    sfreq: float,
    electrode_names: Sequence[str],
    window_size: int = 10,
    exclude_radius: int = 1,
) -> pd.DataFrame:
    """Compute the SNR for every FFT bin for each channel.

    Parameters
    ----------
    data_uv
        Array of averaged EEG data in microvolts with shape (n_channels, n_timepoints).
    sfreq
        Sampling rate of the data in Hz.
    electrode_names
        Channel names corresponding to ``data_uv`` order.
    window_size
        Half of the sliding window (in bins) used to estimate the noise floor
        (±window_size).
    exclude_radius
        Deprecated. Immediate neighbors are always excluded by the shared noise
        helper; this argument is kept only for API compatibility.

    Returns
    -------
    pandas.DataFrame
        DataFrame indexed by ``electrode_names`` with columns named
        ``"{freq:.1f}_Hz"``.
    """
    num_times = data_uv.shape[1]
    num_bins = num_times // 2 + 1
    freqs = np.linspace(0, sfreq / 2.0, num=num_bins, endpoint=True)

    _ = exclude_radius
    amplitudes = _fft_amplitudes(data_uv)
    snr_matrix = compute_full_snr_from_amplitudes(
        amplitudes,
        window_size=window_size,
    )

    col_names = [f"{f:.1f}_Hz" for f in freqs]
    df = pd.DataFrame(snr_matrix, index=list(electrode_names), columns=col_names)
    df.insert(0, "Electrode", df.index)
    return df


def compute_full_snr(
    data_uv: np.ndarray,
    sfreq: float,
    window_size: int = 10,
    exclude_radius: int = 1,
) -> np.ndarray:
    """Return full-spectrum SNR values as a (n_channels, n_bins) array."""

    _ = sfreq, exclude_radius
    amplitudes = _fft_amplitudes(data_uv)
    return compute_full_snr_from_amplitudes(
        amplitudes,
        window_size=window_size,
    )


def compute_full_snr_from_amplitudes(
    amplitudes: np.ndarray,
    window_size: int = 10,
) -> np.ndarray:
    """Return full-spectrum SNR from precomputed FFT amplitudes."""

    return _compute_snr_matrix_for_amplitudes(
        amplitudes,
        window_size=window_size,
    )


def compute_full_snr_prefix_from_amplitudes(
    amplitudes: np.ndarray,
    *,
    output_bin_count: int,
    window_size: int = 10,
) -> np.ndarray:
    """Return an exact leading FullSNR prefix without processing the tail.

    Every retained output bin still receives the same right-hand neighboring
    amplitudes as a full-spectrum calculation.  Only bins beyond the requested
    prefix plus the unchanged noise window are omitted.
    """

    amplitude_matrix = np.asarray(amplitudes)
    if amplitude_matrix.ndim != 2:
        raise ValueError(
            "FullSNR prefix calculation requires a 2-D channels x FFT-bins array."
        )
    total_bin_count = amplitude_matrix.shape[1]
    retained_bin_count = max(
        0,
        min(int(output_bin_count), total_bin_count),
    )
    calculation_bin_count = min(
        total_bin_count,
        retained_bin_count + max(0, int(window_size)),
    )
    calculated = _compute_snr_matrix_for_amplitudes(
        amplitude_matrix[:, :calculation_bin_count],
        window_size=window_size,
    )
    return calculated[:, :retained_bin_count]
