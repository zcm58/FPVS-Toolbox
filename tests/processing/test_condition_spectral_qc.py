from __future__ import annotations

import numpy as np
import pytest

from Main_App.processing import raw_spectral_qc
from Main_App.processing.raw_spectral_qc import (
    CONDITION_SPECTRAL_QC_METHOD_VERSION,
    ConditionSpectralQCCancelled,
    evaluate_condition_spectral_qc_v2,
)
from Tools.Stats.analysis.noise_utils import compute_noise_stats_for_bin


def _condition_data(
    *frequencies_hz: float,
    sfreq: float = 256.0,
    duration_s: float = 10.0,
    n_channels: int = 4,
    amplitude_uv: float = 3000.0,
) -> np.ndarray:
    n_samples = int(round(sfreq * duration_s))
    time = np.arange(n_samples, dtype=np.float64) / sfreq
    rng = np.random.default_rng(20260715)
    data = rng.normal(scale=10e-6, size=(n_channels, n_samples))
    for frequency_hz in frequencies_hz:
        data += (
            np.sin(2.0 * np.pi * frequency_hz * time)
            * amplitude_uv
            * 1e-6
        )
    return data


def _settings(*, mains_hz: int, low_pass_hz: float) -> dict[str, object]:
    return {
        "base_freq": 6.0,
        "oddball_freq": 1.2,
        "line_noise_filter_enabled": True,
        "line_noise_frequency_hz": mains_hz,
        "low_pass": low_pass_hz,
    }


def test_v2_scans_above_30_hz_through_caller_upper_bound() -> None:
    data = _condition_data(40.0)

    below_peak = evaluate_condition_spectral_qc_v2(
        data,
        sfreq=256.0,
        settings=_settings(mains_hz=60, low_pass_hz=50.0),
        effective_upper_frequency_hz=30.0,
        condition_label="Control",
    )
    through_peak = evaluate_condition_spectral_qc_v2(
        data,
        sfreq=256.0,
        settings=_settings(mains_hz=60, low_pass_hz=50.0),
        effective_upper_frequency_hz=50.0,
        condition_label="Control",
    )

    assert below_peak.unexpected_off_harmonic_flags == ()
    assert len(through_peak.unexpected_off_harmonic_flags) == 1
    assert through_peak.unexpected_off_harmonic_flags[0].frequency_hz == pytest.approx(40.0)
    assert through_peak.evaluated_upper_frequency_hz == pytest.approx(50.0)
    assert through_peak.amplitude_upper_frequency_hz == pytest.approx(51.2)


def test_v2_uses_one_fft_and_exact_22_candidate_20_retained_noise_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = _condition_data(40.0, n_channels=1)
    original_rfft = np.fft.rfft
    fft_calls = 0
    observed_neighborhoods: list[tuple[int, int, int, int]] = []

    def _counted_rfft(*args: object, **kwargs: object) -> np.ndarray:
        nonlocal fft_calls
        fft_calls += 1
        return original_rfft(*args, **kwargs)

    def _recorded_noise(
        amplitudes: np.ndarray,
        target_idx: int,
        window_size: int = 10,
        min_bins: int = 4,
    ) -> tuple[float, float]:
        candidates = [
            index
            for index in range(target_idx - window_size, target_idx + window_size + 1)
            if index not in {target_idx - 1, target_idx, target_idx + 1}
        ]
        observed_neighborhoods.append(
            (window_size, min_bins, len(candidates), len(candidates) - 2)
        )
        return compute_noise_stats_for_bin(
            amplitudes,
            target_idx,
            window_size=window_size,
            min_bins=min_bins,
        )

    monkeypatch.setattr(raw_spectral_qc.np.fft, "rfft", _counted_rfft)
    monkeypatch.setattr(raw_spectral_qc, "compute_noise_stats_for_bin", _recorded_noise)

    result = evaluate_condition_spectral_qc_v2(
        data,
        sfreq=256.0,
        settings=_settings(mains_hz=60, low_pass_hz=50.0),
        effective_upper_frequency_hz=50.0,
    )

    assert fft_calls == 1
    assert observed_neighborhoods == [(12, 22, 22, 20)]
    assert result.thresholds["noise_window_bins"] == 12
    assert result.thresholds["noise_candidate_bins"] == 22
    assert result.thresholds["noise_retained_bins"] == 20


def test_batched_amplitudes_are_bit_identical_to_unbatched_formula(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rng = np.random.default_rng(641920)
    data = rng.normal(scale=20e-6, size=(11, 4096)).astype(np.float64)
    window = np.hanning(data.shape[1]).astype(np.float64, copy=False)
    amplitude_last_bin = 900
    expected = (
        np.abs(
            np.fft.rfft(
                (data - np.median(data, axis=1, keepdims=True)) * window,
                axis=1,
            )[:, : amplitude_last_bin + 1]
        )
        * (2.0e6 / data.shape[1])
    )
    before = data.tobytes()
    monkeypatch.setattr(
        raw_spectral_qc,
        "CONDITION_SPECTRAL_QC_MAX_CHANNELS_PER_FFT_BATCH",
        3,
    )

    batches = list(
        raw_spectral_qc._iter_condition_spectral_amplitude_batches(
            data,
            window=window,
            amplitude_last_bin=amplitude_last_bin,
            should_cancel=None,
        )
    )
    actual = np.concatenate([batch for _, batch in batches], axis=0)

    assert [start for start, _ in batches] == [0, 3, 6, 9]
    assert actual.tobytes() == expected.tobytes()
    assert data.tobytes() == before


def test_batching_preserves_exact_v2_result_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = _condition_data(36.0, 40.0, 50.0, n_channels=9)
    settings = _settings(mains_hz=50, low_pass_hz=100.0)
    monkeypatch.setattr(
        raw_spectral_qc,
        "CONDITION_SPECTRAL_QC_MAX_CHANNELS_PER_FFT_BATCH",
        1,
    )
    one_at_a_time = evaluate_condition_spectral_qc_v2(
        data,
        sfreq=256.0,
        settings=settings,
        effective_upper_frequency_hz=100.0,
    )
    monkeypatch.setattr(
        raw_spectral_qc,
        "CONDITION_SPECTRAL_QC_MAX_CHANNELS_PER_FFT_BATCH",
        64,
    )
    all_at_once = evaluate_condition_spectral_qc_v2(
        data,
        sfreq=256.0,
        settings=settings,
        effective_upper_frequency_hz=100.0,
    )

    assert one_at_a_time.to_payload() == all_at_once.to_payload()


def test_fft_batch_size_bounds_long_source_rate_working_set() -> None:
    n_samples = 2048 * 125
    n_amplitude_bins = 6264
    batch_size = raw_spectral_qc._condition_fft_batch_size(
        n_samples=n_samples,
        n_amplitude_bins=n_amplitude_bins,
    )
    bytes_per_channel = max(
        2 * n_samples * np.dtype(np.float64).itemsize
        + (n_samples // 2 + 1) * np.dtype(np.complex128).itemsize,
        (n_samples // 2 + 1) * np.dtype(np.complex128).itemsize
        + n_amplitude_bins * np.dtype(np.float64).itemsize,
    )

    assert batch_size <= raw_spectral_qc.CONDITION_SPECTRAL_QC_MAX_CHANNELS_PER_FFT_BATCH
    assert (
        batch_size * bytes_per_channel
        <= raw_spectral_qc.CONDITION_SPECTRAL_QC_FFT_BATCH_TARGET_BYTES
    )


def test_v2_cancels_at_fft_batch_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = _condition_data(40.0, n_channels=9)
    original_rfft = np.fft.rfft
    cancellation_requested = False
    fft_calls = 0

    def _request_cancel_after_fft(*args: object, **kwargs: object) -> np.ndarray:
        nonlocal cancellation_requested, fft_calls
        fft_calls += 1
        result = original_rfft(*args, **kwargs)
        cancellation_requested = True
        return result

    monkeypatch.setattr(
        raw_spectral_qc,
        "CONDITION_SPECTRAL_QC_MAX_CHANNELS_PER_FFT_BATCH",
        2,
    )
    monkeypatch.setattr(raw_spectral_qc.np.fft, "rfft", _request_cancel_after_fft)

    with pytest.raises(ConditionSpectralQCCancelled, match="was cancelled"):
        evaluate_condition_spectral_qc_v2(
            data,
            sfreq=256.0,
            settings=_settings(mains_hz=60, low_pass_hz=50.0),
            effective_upper_frequency_hz=50.0,
            should_cancel=lambda: cancellation_requested,
        )

    assert fft_calls == 1


def test_v2_separates_expected_notch_handled_and_unexpected_peaks() -> None:
    result = evaluate_condition_spectral_qc_v2(
        _condition_data(36.0, 40.0, 50.0),
        sfreq=256.0,
        settings=_settings(mains_hz=50, low_pass_hz=100.0),
        effective_upper_frequency_hz=100.0,
        channel_names=("A", "B", "C", "D"),
    )

    assert [peak.frequency_hz for peak in result.expected_harmonic_peaks] == pytest.approx(
        [36.0]
    )
    assert [peak.frequency_hz for peak in result.notch_handled_peaks] == pytest.approx(
        [50.0]
    )
    assert [
        peak.frequency_hz for peak in result.unexpected_off_harmonic_flags
    ] == pytest.approx([40.0])
    assert result.collision_peaks == ()
    assert result.effective_notch_centers_hz == (50.0, 100.0)
    assert result.review_only is True
    assert "exclude" not in result.to_payload()


def test_v2_reports_60_hz_mains_and_6_hz_harmonic_collision() -> None:
    result = evaluate_condition_spectral_qc_v2(
        _condition_data(60.0),
        sfreq=256.0,
        settings=_settings(mains_hz=60, low_pass_hz=100.0),
        effective_upper_frequency_hz=100.0,
    )

    assert result.expected_harmonic_peaks == ()
    assert result.notch_handled_peaks == ()
    assert result.unexpected_off_harmonic_flags == ()
    assert len(result.collision_peaks) == 1
    collision = result.collision_peaks[0]
    assert collision.frequency_hz == pytest.approx(60.0)
    assert collision.base_harmonic == 10
    assert collision.oddball_harmonic == 50
    assert collision.matched_notch_centers_hz == (60.0,)


def test_v2_clamps_evaluable_bins_below_nyquist_for_full_noise_margin() -> None:
    sfreq = 128.0
    result = evaluate_condition_spectral_qc_v2(
        _condition_data(sfreq=sfreq, duration_s=10.0),
        sfreq=sfreq,
        settings=_settings(mains_hz=60, low_pass_hz=100.0),
        effective_upper_frequency_hz=100.0,
    )

    assert result.evaluated is True
    assert result.requested_upper_frequency_hz == 100.0
    assert result.amplitude_upper_frequency_hz == pytest.approx(64.0)
    assert result.evaluated_upper_frequency_hz == pytest.approx(62.8)
    assert result.evaluated_upper_frequency_hz < sfreq / 2.0
    assert result.effective_notch_centers_hz == (60.0,)


def test_v2_method_and_payload_are_explicitly_review_only() -> None:
    result = evaluate_condition_spectral_qc_v2(
        _condition_data(),
        sfreq=256.0,
        settings=_settings(mains_hz=60, low_pass_hz=50.0),
        effective_upper_frequency_hz=50.0,
    )

    assert result.method_version == CONDITION_SPECTRAL_QC_METHOD_VERSION
    assert result.review_only is True
    assert result.has_review_flags is False
    assert result.to_payload()["review_only"] is True
