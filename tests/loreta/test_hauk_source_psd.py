from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from Tools.LORETA_Visualizer.source_producers.hauk_source_psd import (
    DEFAULT_HAUK_SOURCE_PSD_ALIGNED_OFFSETS,
    DEFAULT_HAUK_SOURCE_PSD_LAMBDA2,
    DEFAULT_HAUK_SOURCE_PSD_NOISE_OFFSETS,
    HAUK_SOURCE_PSD_METHOD_VERSION,
    HaukSourcePsdConfig,
    build_hauk_source_psd_frequency_plan,
    compute_hauk_source_psd,
    compute_hauk_source_zscores,
    source_amplitudes_from_psd_power,
    sum_harmonic_source_amplitudes,
)


class _AveragedRaw:
    def __init__(self, *, sfreq: float, n_times: int) -> None:
        self.info = {"sfreq": sfreq}
        self.n_times = n_times


def test_frequency_plan_requires_exact_bins_and_complete_intentional_noise_windows() -> None:
    plan = build_hauk_source_psd_frequency_plan(
        sfreq=100.0,
        n_times=100,
        selected_harmonics_hz=(30.0, 20.0),
    )

    assert plan.frequency_resolution_hz == pytest.approx(1.0)
    assert plan.selected_harmonics_hz == (20.0, 30.0)
    assert plan.harmonic_bin_indices == (20, 30)
    assert plan.aligned_offsets == (0, *range(-10, -1), *range(2, 11))
    assert plan.fmin_hz == pytest.approx(10.0)
    assert plan.fmax_hz == pytest.approx(40.0)

    with pytest.raises(ValueError, match="not on an exact FFT bin"):
        build_hauk_source_psd_frequency_plan(
            sfreq=100.0,
            n_times=100,
            selected_harmonics_hz=(20.1,),
        )

    with pytest.raises(ValueError, match="complete required source-PSD noise window"):
        build_hauk_source_psd_frequency_plan(
            sfreq=100.0,
            n_times=100,
            selected_harmonics_hz=(5.0,),
        )


def test_power_to_amplitude_clips_only_relative_roundoff_negatives() -> None:
    power = np.asarray([[4.0, -1e-14], [9.0, 16.0]], dtype=float)

    amplitudes = source_amplitudes_from_psd_power(power)

    assert np.array_equal(amplitudes, np.asarray([[2.0, 0.0], [3.0, 4.0]]))
    with pytest.raises(ValueError, match="negative values larger than numerical tolerance"):
        source_amplitudes_from_psd_power(np.asarray([[4.0, -1e-3]], dtype=float))


def test_source_zscore_uses_global_extremes_and_population_sd() -> None:
    source_zero_noise = np.arange(1.0, 19.0)
    source_one_noise = source_zero_noise * 2.0
    summed = np.vstack(
        (
            np.concatenate(([20.0], source_zero_noise)),
            np.concatenate(([10.0], source_one_noise)),
        )
    )

    result = compute_hauk_source_zscores(summed)

    expected_zero_retained = np.arange(2.0, 18.0)
    expected_one_retained = expected_zero_retained * 2.0
    assert np.array_equal(result.noise_values_after_extreme_drop[0], expected_zero_retained)
    assert np.array_equal(result.noise_values_after_extreme_drop[1], expected_one_retained)
    assert result.noise_mean_values == pytest.approx([9.5, 19.0])
    assert result.noise_std_values == pytest.approx(
        [
            np.std(expected_zero_retained, ddof=0),
            np.std(expected_one_retained, ddof=0),
        ]
    )
    assert result.values == pytest.approx(
        [
            (20.0 - 9.5) / np.std(expected_zero_retained, ddof=0),
            (10.0 - 19.0) / np.std(expected_one_retained, ddof=0),
        ]
    )
    assert result.zero_noise_sd_source_count == 0


def test_source_zscore_drops_two_tied_extremes_and_reports_zero_sd_sources() -> None:
    valid_noise = np.asarray([1.0] * 4 + [2.0] * 10 + [3.0] * 4)
    flat_noise = np.ones(18, dtype=float)
    summed = np.vstack(
        (
            np.concatenate(([4.0], valid_noise)),
            np.concatenate(([2.0], flat_noise)),
        )
    )

    result = compute_hauk_source_zscores(summed)

    assert result.noise_values_after_extreme_drop.shape == (2, 16)
    assert np.count_nonzero(result.noise_values_after_extreme_drop[0] == 1.0) == 3
    assert np.count_nonzero(result.noise_values_after_extreme_drop[0] == 3.0) == 3
    assert result.values[1] == 0.0
    assert result.zero_noise_sd_source_count == 1


def test_source_zscore_rejects_any_other_offset_contract() -> None:
    assert DEFAULT_HAUK_SOURCE_PSD_NOISE_OFFSETS == (*range(-10, -1), *range(2, 11))
    assert DEFAULT_HAUK_SOURCE_PSD_ALIGNED_OFFSETS == (0, *DEFAULT_HAUK_SOURCE_PSD_NOISE_OFFSETS)

    with pytest.raises(ValueError, match="offsets exactly"):
        compute_hauk_source_zscores(
            np.ones((1, 19), dtype=float),
            aligned_offsets=(0, *range(-11, -1), *range(2, 10)),
        )


def test_harmonic_summation_refuses_missing_or_off_grid_source_psd_bins() -> None:
    plan = build_hauk_source_psd_frequency_plan(
        sfreq=200.0,
        n_times=200,
        selected_harmonics_hz=(20.0, 60.0),
    )
    frequencies = np.arange(10.0, 71.0)
    amplitudes = np.ones((2, len(frequencies)), dtype=float)

    missing_frequencies = np.delete(frequencies, 0)
    with pytest.raises(ValueError, match="missing required exact FFT bins"):
        sum_harmonic_source_amplitudes(
            source_amplitudes=amplitudes[:, 1:],
            source_psd_frequencies_hz=missing_frequencies,
            frequency_plan=plan,
        )

    off_grid_frequencies = frequencies.copy()
    off_grid_frequencies[0] = 10.1
    with pytest.raises(ValueError, match="off-grid frequency"):
        sum_harmonic_source_amplitudes(
            source_amplitudes=amplitudes,
            source_psd_frequencies_hz=off_grid_frequencies,
            frequency_plan=plan,
        )


def test_compute_source_psd_calls_mne_contract_then_sums_in_source_space() -> None:
    raw = _AveragedRaw(sfreq=200.0, n_times=200)
    inverse_operator = object()
    config = HaukSourcePsdConfig(
        selected_harmonics_hz=(20.0, 60.0),
        metadata={"input_artifact": "participant_condition_raw_v1"},
    )
    frequencies = np.arange(10.0, 71.0)
    desired_summed = np.vstack(
        (
            np.concatenate(([20.0], np.arange(1.0, 19.0))),
            np.concatenate(([10.0], np.arange(1.0, 19.0) * 2.0)),
        )
    )
    source_amplitudes = np.zeros((2, len(frequencies)), dtype=float)
    for harmonic in (20, 60):
        for offset_index, offset in enumerate(DEFAULT_HAUK_SOURCE_PSD_ALIGNED_OFFSETS):
            source_amplitudes[:, harmonic + offset - 10] = desired_summed[:, offset_index] / 2.0
    source_power = source_amplitudes**2
    calls: list[dict[str, object]] = []

    def fake_compute_source_psd(**kwargs):  # noqa: ANN003, ANN202
        calls.append(kwargs)
        return SimpleNamespace(data=source_power, times=frequencies)

    result = compute_hauk_source_psd(
        averaged_raw=raw,
        inverse_operator=inverse_operator,
        config=config,
        compute_source_psd_func=fake_compute_source_psd,
    )

    assert len(calls) == 1
    call = calls[0]
    assert call["raw"] is raw
    assert call["inverse_operator"] is inverse_operator
    assert call["method"] == "MNE"
    assert call["lambda2"] == pytest.approx(DEFAULT_HAUK_SOURCE_PSD_LAMBDA2)
    assert call["n_fft"] == raw.n_times
    assert call["overlap"] == 0.0
    assert call["bandwidth"] == "hann"
    assert call["low_bias"] is True
    assert call["return_sensor"] is False
    assert call["fmin"] == pytest.approx(10.0)
    assert call["fmax"] == pytest.approx(70.0)
    assert np.array_equal(result.summed_source_amplitudes, desired_summed)
    assert result.values == pytest.approx(
        [
            (20.0 - 9.5) / np.std(np.arange(2.0, 18.0), ddof=0),
            (10.0 - 19.0) / np.std(np.arange(2.0, 18.0) * 2.0, ddof=0),
        ]
    )
    assert result.source_count == 2
    assert result.source_psd_frequency_count == len(frequencies)

    fingerprint = result.cache_fingerprint_payload()
    assert fingerprint["method"]["method_version"] == HAUK_SOURCE_PSD_METHOD_VERSION
    assert fingerprint["method"]["noise_offsets"] == list(DEFAULT_HAUK_SOURCE_PSD_NOISE_OFFSETS)
    assert fingerprint["method"]["noise_standard_deviation_ddof"] == 0
    assert fingerprint["method"]["nearest_fft_bin_substitution"] == "forbidden"
    assert fingerprint["frequency_plan"]["harmonic_bin_indices"] == [20, 60]


def test_compute_source_psd_requires_raw_frequency_metadata() -> None:
    config = HaukSourcePsdConfig(selected_harmonics_hz=(20.0,))

    with pytest.raises(TypeError, match=r"info\['sfreq'\]"):
        compute_hauk_source_psd(
            averaged_raw=SimpleNamespace(n_times=200),
            inverse_operator=object(),
            config=config,
            compute_source_psd_func=lambda **_kwargs: None,
        )
