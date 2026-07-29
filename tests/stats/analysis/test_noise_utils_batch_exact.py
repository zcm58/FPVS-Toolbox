from __future__ import annotations

import warnings

import numpy as np
import pytest

from Tools.Stats.analysis.noise_utils import (
    compute_noise_stats_for_bin,
    compute_noise_stats_for_bin_channels,
)


def _scalar_channel_stats(
    amplitudes: np.ndarray,
    target_idx: int,
    *,
    window_size: int = 10,
    min_bins: int = 4,
) -> tuple[np.ndarray, np.ndarray]:
    means = np.empty(amplitudes.shape[0], dtype=float)
    stds = np.empty(amplitudes.shape[0], dtype=float)
    for channel_index in range(amplitudes.shape[0]):
        means[channel_index], stds[channel_index] = compute_noise_stats_for_bin(
            amplitudes[channel_index],
            target_idx,
            window_size=window_size,
            min_bins=min_bins,
        )
    return means, stds


def _call_with_warnings(callable_, *args, **kwargs):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = callable_(*args, **kwargs)
    warning_records = [
        (item.category, str(item.message))
        for item in caught
    ]
    return result, warning_records


@pytest.mark.parametrize("target_idx", [0, 1, 4, 10, 100, 1024])
def test_channel_batch_noise_stats_match_scalar_bytes_for_normal_fft_values(
    target_idx: int,
) -> None:
    amplitudes = np.abs(
        np.random.default_rng(20260729).normal(size=(64, 2049))
    )
    assert amplitudes.dtype == np.dtype(np.float64)
    assert amplitudes.flags.c_contiguous
    assert np.all(amplitudes != 0.0)

    expected = _scalar_channel_stats(amplitudes, target_idx)
    actual = compute_noise_stats_for_bin_channels(amplitudes, target_idx)

    for expected_array, actual_array in zip(expected, actual):
        assert actual_array.dtype == expected_array.dtype
        assert actual_array.shape == expected_array.shape
        assert actual_array.tobytes() == expected_array.tobytes()


@pytest.mark.parametrize(
    "array_kind",
    [
        "zeros",
        "signed_zeros",
        "nonfinite",
        "float32",
        "fortran",
        "strided",
        "large",
        "small",
        "tied_extrema",
    ],
)
def test_channel_batch_noise_stats_fallback_matches_values_and_warnings(
    array_kind: str,
) -> None:
    rng = np.random.default_rng(314159)
    amplitudes = np.abs(rng.normal(size=(7, 96)))
    if array_kind == "zeros":
        amplitudes.fill(0.0)
    elif array_kind == "signed_zeros":
        amplitudes[:, 36] = -0.0
        amplitudes[:, 37] = 0.0
    elif array_kind == "nonfinite":
        amplitudes[1, 34] = np.nan
        amplitudes[2, 42] = np.inf
    elif array_kind == "float32":
        amplitudes = amplitudes.astype(np.float32)
    elif array_kind == "fortran":
        amplitudes = np.asfortranarray(amplitudes)
        assert not amplitudes.flags.c_contiguous
    elif array_kind == "strided":
        amplitudes = amplitudes[:, ::2]
        assert not amplitudes.flags.c_contiguous
    elif array_kind == "large":
        amplitudes *= 1e101
    elif array_kind == "small":
        amplitudes *= 1e-101
    elif array_kind == "tied_extrema":
        amplitudes[:, 30:51] = 1.0

    target_idx = min(40, amplitudes.shape[1] - 1)
    expected, expected_warnings = _call_with_warnings(
        _scalar_channel_stats,
        amplitudes,
        target_idx,
    )
    actual, actual_warnings = _call_with_warnings(
        compute_noise_stats_for_bin_channels,
        amplitudes,
        target_idx,
    )

    assert actual_warnings == expected_warnings
    for expected_array, actual_array in zip(expected, actual):
        assert actual_array.dtype == expected_array.dtype
        assert actual_array.shape == expected_array.shape
        assert actual_array.tobytes() == expected_array.tobytes()


def test_channel_batch_noise_stats_matches_short_window_zero_result() -> None:
    amplitudes = np.arange(18, dtype=float).reshape(3, 6)

    expected = _scalar_channel_stats(amplitudes, 0)
    actual = compute_noise_stats_for_bin_channels(amplitudes, 0)

    assert actual[0].tobytes() == expected[0].tobytes()
    assert actual[1].tobytes() == expected[1].tobytes()
