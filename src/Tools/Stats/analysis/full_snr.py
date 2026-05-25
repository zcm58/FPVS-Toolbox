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
        noise_min[:, dest] = np.minimum(noise_min[:, dest], source)
        noise_max[:, dest] = np.maximum(noise_max[:, dest], source)
        counts[dest] += 1

    means = np.zeros((num_channels, num_bins), dtype=amplitudes.dtype)
    enough_bins = counts >= 4
    means[:, enough_bins] = (
        noise_sum[:, enough_bins]
        - noise_min[:, enough_bins]
        - noise_max[:, enough_bins]
    ) / (counts[enough_bins] - 2)

    return np.divide(
        amplitudes,
        means,
        out=np.zeros_like(amplitudes),
        where=means > 1e-12,
    )


def _compute_snr_for_amplitudes(
    amplitudes: np.ndarray,
    window_size: int = 10,
    exclude_radius: int = 1,
) -> np.ndarray:
    """Return full-spectrum SNR for a single channel.

    Parameters
    ----------
    amplitudes
        1-D numpy array of FFT amplitudes for one channel.
    window_size
        Half window size on each side used when estimating the noise floor
        (±window_size bins).
    exclude_radius
        Kept for backward compatibility; the actual exclusion of immediate
        neighbors is handled inside ``compute_noise_stats_for_bin`` and is
        fixed at ±1 bin around the target.
    """
    _ = exclude_radius
    return _compute_snr_matrix_for_amplitudes(
        amplitudes[np.newaxis, :],
        window_size=window_size,
    )[0]


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
