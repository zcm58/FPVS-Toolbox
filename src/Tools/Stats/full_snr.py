# full_snr.py
# -*- coding: utf-8 -*-
"""Utility for computing full-spectrum SNR values.

This module mirrors the FFT and SNR logic from :mod:`Main_App.post_process`
but exposes a helper that computes the Signal-to-Noise Ratio for **all** FFT
bins using a sliding-window estimate of the noise floor.

The resulting values can be saved to Excel alongside other metrics.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Sequence

__all__ = ["compute_full_snr_df", "compute_full_snr"]


def _compute_snr_for_amplitudes(
    amplitudes: np.ndarray,
    window_size: int = 12,
    exclude_radius: int = 2,
) -> np.ndarray:
    """Return full-spectrum SNR for a single channel.

    Parameters
    ----------
    amplitudes:
        1-D numpy array of FFT amplitudes for one channel.
    window_size:
        Half window size on each side used when estimating the noise floor.
    exclude_radius:
        Number of bins around the target bin to exclude from the noise estimate.
    """
    num_bins = amplitudes.shape[0]
    snr = np.zeros(num_bins)
    for idx in range(num_bins):
        low = idx - window_size
        high = idx + window_size
        exclude = set(range(idx - exclude_radius, idx + exclude_radius + 1))
        valid = [
            i
            for i in range(low, high + 1)
            if 0 <= i < num_bins and i not in exclude
        ]
        if len(valid) >= 4:
            noise_mean = np.mean(amplitudes[valid])
        else:
            noise_mean = 0.0
        signal = amplitudes[idx]
        snr[idx] = signal / noise_mean if noise_mean > 1e-12 else 0.0
    return snr


def compute_full_snr_df(
    data_uv: np.ndarray,
    sfreq: float,
    electrode_names: Sequence[str],
    window_size: int = 12,
    exclude_radius: int = 2,
) -> pd.DataFrame:
    """Compute the SNR for every FFT bin for each channel.

    Parameters
    ----------
    data_uv:
        Array of averaged EEG data in microvolts with shape ``(n_channels, n_timepoints)``.
    sfreq:
        Sampling rate of the data in Hz.
    electrode_names:
        Channel names corresponding to ``data_uv`` order.
    window_size:
        Half of the sliding window (in bins) used to estimate the noise floor.
    exclude_radius:
        Number of bins around the target bin excluded from noise estimate.

    Returns
    -------
    pandas.DataFrame
        DataFrame indexed by ``electrode_names`` with columns named ``"{freq:.1f}_Hz"``.
    """
    num_channels, num_times = data_uv.shape
    num_bins = num_times // 2 + 1
    freqs = np.linspace(0, sfreq / 2.0, num=num_bins, endpoint=True)

    fft_spectrum = np.fft.fft(data_uv, axis=1)
    amplitudes = np.abs(fft_spectrum[:, :num_bins]) / num_times * 2

    snr_matrix = np.zeros((num_channels, num_bins))
    for ch_idx in range(num_channels):
        snr_matrix[ch_idx] = _compute_snr_for_amplitudes(
            amplitudes[ch_idx], window_size=window_size, exclude_radius=exclude_radius
        )

    col_names = [f"{f:.1f}_Hz" for f in freqs]
    df = pd.DataFrame(snr_matrix, index=list(electrode_names), columns=col_names)
    df.insert(0, "Electrode", df.index)
    return df


def compute_full_snr(
    data_uv: np.ndarray,
    sfreq: float,
    window_size: int = 12,
    exclude_radius: int = 2,
) -> np.ndarray:
    """Return full-spectrum SNR values as a ``(n_channels, n_bins)`` array."""

    num_channels, num_times = data_uv.shape
    num_bins = num_times // 2 + 1

    fft_spectrum = np.fft.fft(data_uv, axis=1)
    amplitudes = np.abs(fft_spectrum[:, :num_bins]) / num_times * 2

    snr_matrix = np.zeros((num_channels, num_bins))
    for ch_idx in range(num_channels):
        snr_matrix[ch_idx] = _compute_snr_for_amplitudes(
            amplitudes[ch_idx], window_size=window_size, exclude_radius=exclude_radius
        )
    return snr_matrix

