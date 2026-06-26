from __future__ import annotations

import mne
import numpy as np

from Main_App.processing.raw_channel_qc import (
    LEFT_HEMISPHERE_CHANNELS,
    RIGHT_HEMISPHERE_CHANNELS,
    evaluate_raw_channel_qc,
)


def _raw_with_left_failure() -> mne.io.RawArray:
    left = list(LEFT_HEMISPHERE_CHANNELS)
    right = list(RIGHT_HEMISPHERE_CHANNELS)
    midline = ["Iz", "Oz", "POz", "Pz", "CPz", "AFz", "Fz", "FCz", "Cz", "Fpz"]
    names = [*left, *midline, *right]
    rng = np.random.default_rng(42)
    data = rng.normal(scale=500e-6, size=(len(names), 2048))

    left_lookup = set(left)
    for index, name in enumerate(names):
        if name in left_lookup:
            data[index] = rng.normal(scale=2e-6, size=data.shape[1])
    return mne.io.RawArray(
        data,
        mne.create_info(names, sfreq=256.0, ch_types=["eeg"] * len(names)),
        verbose=False,
    )


def _raw_with_clustered_removed_channels(removed: list[str]) -> mne.io.RawArray:
    names = list(mne.channels.make_standard_montage("biosemi64").ch_names)
    rng = np.random.default_rng(64)
    data = rng.normal(scale=500e-6, size=(len(names), 4096))
    for channel in removed:
        data[names.index(channel)] = rng.normal(scale=2e-6, size=data.shape[1])
    raw = mne.io.RawArray(
        data,
        mne.create_info(names, sfreq=256.0, ch_types=["eeg"] * len(names)),
        verbose=False,
    )
    raw.set_montage(mne.channels.make_standard_montage("biosemi64"))
    return raw


def _raw_with_spatial_outlier_channel(channel: str) -> mne.io.RawArray:
    montage = mne.channels.make_standard_montage("biosemi64")
    names = list(montage.ch_names)
    positions = montage.get_positions()["ch_pos"]
    rng = np.random.default_rng(144)
    n_times = 8192
    t = np.arange(n_times) / 256.0
    common = np.sin(2 * np.pi * 8.0 * t)
    anterior_posterior = np.sin(2 * np.pi * 11.0 * t + 0.4)
    left_right = np.sin(2 * np.pi * 5.0 * t + 0.9)
    data = np.zeros((len(names), n_times), dtype=float)
    for index, name in enumerate(names):
        x, y, _z = positions[name]
        signal = (
            0.8 * common
            + 0.4 * float(x) * left_right
            + 0.4 * float(y) * anterior_posterior
            + rng.normal(scale=0.03, size=n_times)
        )
        data[index] = signal * 300e-6

    data[names.index(channel)] = rng.normal(scale=320e-6, size=n_times)
    raw = mne.io.RawArray(
        data,
        mne.create_info(names, sfreq=256.0, ch_types=["eeg"] * len(names)),
        verbose=False,
    )
    raw.set_montage(montage)
    return raw


def _raw_with_high_amplitude_channel(channel: str) -> mne.io.RawArray:
    raw = _raw_with_spatial_outlier_channel(channel)
    rng = np.random.default_rng(512)
    raw._data[raw.ch_names.index(channel)] = rng.normal(
        scale=20_000e-6,
        size=raw.n_times,
    )
    return raw


def test_raw_channel_qc_excludes_hemisphere_failure_at_exact_half_channels() -> None:
    result = evaluate_raw_channel_qc(
        _raw_with_left_failure(),
        {"stim_channel": "Status", "max_bad_chans": 20},
        filename="p21.bdf",
    )

    assert result.excluded is True
    assert result.n_channels == 64
    assert result.n_bad_channels == 27
    assert result.bad_fraction < 0.50
    assert result.left_bad == result.left_total
    assert "left_hemisphere_failure" in result.triggered_rules


def test_raw_channel_qc_excludes_when_bad_fraction_exceeds_half() -> None:
    raw = _raw_with_left_failure()
    rng = np.random.default_rng(24)
    extra_midline = ["Iz", "Oz", "POz", "Pz", "CPz", "AFz"]
    for channel in extra_midline:
        raw._data[raw.ch_names.index(channel)] = rng.normal(scale=2e-6, size=raw.n_times)

    result = evaluate_raw_channel_qc(
        raw,
        {"stim_channel": "Status", "max_bad_chans": 64},
        filename="p21.bdf",
    )

    assert result.excluded is True
    assert result.n_bad_channels == 33
    assert result.bad_fraction > 0.50
    assert "bad_channel_fraction" in result.triggered_rules


def test_raw_channel_qc_skips_hard_rules_for_tiny_montage() -> None:
    names = ["Cz", "Pz", "Oz", "Status"]
    data = np.zeros((len(names), 128))
    raw = mne.io.RawArray(
        data,
        mne.create_info(names, sfreq=128.0, ch_types=["eeg", "eeg", "eeg", "stim"]),
        verbose=False,
    )

    result = evaluate_raw_channel_qc(
        raw,
        {"stim_channel": "Status", "max_bad_chans": 0},
        filename="synthetic.bdf",
    )

    assert result.excluded is False
    assert result.n_channels == 3
    assert result.triggered_rules == ()


def test_raw_channel_qc_marks_isolated_low_variance_channels_for_interpolation() -> None:
    raw = _raw_with_clustered_removed_channels(["P9"])

    result = evaluate_raw_channel_qc(
        raw,
        {"stim_channel": "Status", "max_bad_chans": 20},
        filename="p03.bdf",
    )

    assert result.excluded is False
    assert result.bad_channels == ("P9",)
    assert result.channels_to_interpolate == ("P9",)
    assert result.triggered_rules == ()


def test_raw_channel_qc_flags_spatial_outlier_without_interpolation() -> None:
    raw = _raw_with_spatial_outlier_channel("FT7")

    result = evaluate_raw_channel_qc(
        raw,
        {"stim_channel": "Status", "max_bad_chans": 20},
        filename="p09.bdf",
    )

    assert result.excluded is False
    assert result.low_variance_channels == ()
    assert result.spatial_outlier_channels == ("FT7",)
    assert result.bad_channels == ("FT7",)
    assert result.channels_to_interpolate == ()
    assert result.triggered_rules == ()


def test_raw_channel_qc_flags_high_amplitude_outlier_without_interpolation() -> None:
    raw = _raw_with_high_amplitude_channel("FT8")

    result = evaluate_raw_channel_qc(
        raw,
        {"stim_channel": "Status", "max_bad_chans": 20},
        filename="p01.bdf",
    )

    assert result.excluded is False
    assert result.low_variance_channels == ()
    assert result.high_amplitude_channels == ("FT8",)
    assert result.spatial_outlier_channels == ()
    assert result.bad_channels == ("FT8",)
    assert result.channels_to_interpolate == ()
    assert result.triggered_rules == ()


def test_raw_channel_qc_toggle_disables_auto_interpolation_candidates() -> None:
    raw = _raw_with_clustered_removed_channels(["P9"])

    result = evaluate_raw_channel_qc(
        raw,
        {
            "stim_channel": "Status",
            "max_bad_chans": 20,
            "auto_detect_removed_electrodes": False,
        },
        filename="p03.bdf",
    )

    assert result.excluded is False
    assert result.bad_channels == ("P9",)
    assert result.channels_to_interpolate == ()
    assert result.triggered_rules == ()


def test_raw_channel_qc_toggle_disables_spatial_outlier_detection() -> None:
    raw = _raw_with_spatial_outlier_channel("FT7")

    result = evaluate_raw_channel_qc(
        raw,
        {
            "stim_channel": "Status",
            "max_bad_chans": 20,
            "auto_detect_removed_electrodes": False,
        },
        filename="p09.bdf",
    )

    assert result.excluded is False
    assert result.spatial_outlier_channels == ()
    assert result.bad_channels == ()
    assert result.channels_to_interpolate == ()


def test_raw_channel_qc_warns_for_four_channel_bad_cluster() -> None:
    raw = _raw_with_clustered_removed_channels(["F7", "FT7", "FC5", "T7"])

    result = evaluate_raw_channel_qc(
        raw,
        {"stim_channel": "Status", "max_bad_chans": 20},
        filename="p15.bdf",
    )

    assert result.excluded is False
    assert result.n_bad_channels == 4
    assert result.triggered_rules == ()
    assert result.warning_rules == ("possible_bad_channel_cluster",)
    assert result.largest_bad_cluster_size == 4
    assert set(result.largest_bad_cluster_channels) == {"F7", "FT7", "FC5", "T7"}


def test_raw_channel_qc_excludes_six_channel_bad_cluster() -> None:
    raw = _raw_with_clustered_removed_channels(["F7", "FT7", "FC5", "T7", "C5", "CP5"])

    result = evaluate_raw_channel_qc(
        raw,
        {"stim_channel": "Status", "max_bad_chans": 20},
        filename="p15.bdf",
    )

    assert result.excluded is True
    assert result.n_bad_channels == 6
    assert "bad_channel_cluster" in result.triggered_rules
    assert result.warning_rules == ()
    assert result.largest_bad_cluster_size == 6
