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

from Tools.Stats.Legacy.noise_utils import compute_noise_stats_for_bin

__all__ = ["compute_full_snr_df", "compute_full_snr"]


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
    num_bins = amplitudes.shape[0]
    snr = np.zeros(num_bins)
    for idx in range(num_bins):
        noise_mean, _ = compute_noise_stats_for_bin(
            amplitudes, idx, window_size=window_size, min_bins=4
        )
        signal = amplitudes[idx]
        snr[idx] = signal / noise_mean if noise_mean > 1e-12 else 0.0
    return snr


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
    window_size: int = 10,
    exclude_radius: int = 1,
) -> np.ndarray:
    """Return full-spectrum SNR values as a (n_channels, n_bins) array."""

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
