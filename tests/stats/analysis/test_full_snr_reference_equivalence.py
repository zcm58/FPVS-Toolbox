from __future__ import annotations

import numpy as np

from Tools.Stats.analysis.full_snr import (
    compute_full_snr,
    compute_full_snr_df,
    compute_full_snr_from_amplitudes,
)
from Tools.Stats.analysis.noise_utils import compute_noise_stats_for_bin


def _legacy_compute_full_snr_reference(
    data_uv: np.ndarray,
    sfreq: float,
    window_size: int = 10,
) -> np.ndarray:
    """Reference copy of the pre-vectorized full-SNR calculation."""
    _ = sfreq
    num_channels, num_times = data_uv.shape
    num_bins = num_times // 2 + 1

    fft_spectrum = np.fft.fft(data_uv, axis=1)
    amplitudes = np.abs(fft_spectrum[:, :num_bins]) / num_times * 2

    snr_matrix = np.zeros((num_channels, num_bins))
    for ch_idx in range(num_channels):
        channel_amplitudes = amplitudes[ch_idx]
        for bin_idx in range(num_bins):
            noise_mean, _ = compute_noise_stats_for_bin(
                channel_amplitudes,
                bin_idx,
                window_size=window_size,
                min_bins=4,
            )
            signal = channel_amplitudes[bin_idx]
            snr_matrix[ch_idx, bin_idx] = (
                signal / noise_mean if noise_mean > 1e-12 else 0.0
            )
    return snr_matrix


def test_compute_full_snr_matches_legacy_reference_for_short_signal() -> None:
    data_uv = np.array(
        [
            [0.0, 1.0, -1.0, 0.5, -0.5, 0.25],
            [1.0, 0.0, 0.5, -0.25, 0.125, -0.0625],
        ],
        dtype=float,
    )

    actual = compute_full_snr(data_uv, sfreq=512.0)
    expected = _legacy_compute_full_snr_reference(data_uv, sfreq=512.0)

    np.testing.assert_allclose(actual, expected, rtol=1e-12, atol=1e-12)
    assert np.count_nonzero(actual) == 0


def test_compute_full_snr_matches_legacy_reference_at_window_edges() -> None:
    sample_idx = np.arange(64, dtype=float)
    data_uv = np.vstack(
        [
            np.sin(2 * np.pi * sample_idx / 16.0),
            np.cos(2 * np.pi * sample_idx / 9.0) + 0.1 * sample_idx,
            np.where(sample_idx % 5 == 0, 2.0, -0.75),
        ]
    )

    actual = compute_full_snr(data_uv, sfreq=512.0)
    expected = _legacy_compute_full_snr_reference(data_uv, sfreq=512.0)

    np.testing.assert_allclose(actual, expected, rtol=1e-12, atol=1e-12)


def test_compute_full_snr_matches_legacy_reference_with_custom_window() -> None:
    rng = np.random.default_rng(90210)
    data_uv = rng.normal(size=(4, 256))

    actual = compute_full_snr(data_uv, sfreq=512.0, window_size=4)
    expected = _legacy_compute_full_snr_reference(
        data_uv,
        sfreq=512.0,
        window_size=4,
    )

    np.testing.assert_allclose(actual, expected, rtol=1e-12, atol=1e-12)


def test_compute_full_snr_matches_legacy_reference_for_realistic_shape() -> None:
    rng = np.random.default_rng(20260521)
    data_uv = rng.normal(loc=0.0, scale=2.5, size=(8, 1024))

    actual = compute_full_snr(data_uv, sfreq=512.0)
    expected = _legacy_compute_full_snr_reference(data_uv, sfreq=512.0)

    np.testing.assert_allclose(actual, expected, rtol=1e-12, atol=1e-12)


def test_compute_full_snr_from_amplitudes_reuses_precomputed_fft_values() -> None:
    rng = np.random.default_rng(20260525)
    data_uv = rng.normal(loc=0.0, scale=2.5, size=(5, 512))
    num_times = data_uv.shape[1]
    num_bins = num_times // 2 + 1
    amplitudes = np.abs(np.fft.fft(data_uv, axis=1)[:, :num_bins]) / num_times * 2

    from_data = compute_full_snr(data_uv, sfreq=512.0)
    from_amplitudes = compute_full_snr_from_amplitudes(amplitudes)

    np.testing.assert_allclose(from_amplitudes, from_data, rtol=1e-12, atol=1e-12)


def test_compute_full_snr_df_matches_legacy_reference_values() -> None:
    rng = np.random.default_rng(12345)
    data_uv = rng.normal(size=(3, 128))
    electrode_names = ["Fp1", "Fz", "Oz"]

    actual = compute_full_snr_df(data_uv, sfreq=512.0, electrode_names=electrode_names)
    expected_values = _legacy_compute_full_snr_reference(data_uv, sfreq=512.0)

    assert actual["Electrode"].tolist() == electrode_names
    np.testing.assert_allclose(
        actual.drop(columns=["Electrode"]).to_numpy(),
        expected_values,
        rtol=1e-12,
        atol=1e-12,
    )
