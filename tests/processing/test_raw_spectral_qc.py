from __future__ import annotations

import mne
import numpy as np

from Main_App.processing.raw_spectral_qc import evaluate_raw_spectral_qc


def _raw_with_sine(
    *,
    frequency_hz: float,
    amplitude_uv: float,
    affected_channels: int,
) -> mne.io.RawArray:
    montage = mne.channels.make_standard_montage("biosemi64")
    names = list(montage.ch_names)
    sfreq = 256.0
    n_times = int(sfreq * 80)
    t = np.arange(n_times) / sfreq
    rng = np.random.default_rng(2026)
    data = rng.normal(scale=10e-6, size=(len(names), n_times))
    sine = np.sin(2 * np.pi * frequency_hz * t) * amplitude_uv * 1e-6
    for index in range(min(affected_channels, len(names))):
        data[index] += sine
    raw = mne.io.RawArray(
        data,
        mne.create_info(names, sfreq=sfreq, ch_types=["eeg"] * len(names)),
        verbose=False,
    )
    raw.set_montage(montage)
    return raw


def test_raw_spectral_qc_flags_widespread_off_harmonic_peak() -> None:
    result = evaluate_raw_spectral_qc(
        _raw_with_sine(frequency_hz=16.0, amplitude_uv=3000.0, affected_channels=64),
        {"stim_channel": "Status", "base_freq": 6.0, "oddball_freq": 1.2},
        filename="P12.bdf",
    )

    assert result.evaluated is True
    assert result.widespread is True
    assert len(result.flagged_channels) >= 48
    assert result.peak_frequency_hz is not None
    assert abs(result.peak_frequency_hz - 16.0) < 0.05


def test_raw_spectral_qc_does_not_flag_typical_alpha_like_peak() -> None:
    result = evaluate_raw_spectral_qc(
        _raw_with_sine(frequency_hz=10.0, amplitude_uv=35.0, affected_channels=64),
        {"stim_channel": "Status", "base_freq": 6.0, "oddball_freq": 1.2},
        filename="P01.bdf",
    )

    assert result.evaluated is True
    assert result.widespread is False
    assert result.flagged_channels == ()
