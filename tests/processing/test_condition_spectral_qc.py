from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from Main_App.processing import raw_spectral_qc
from Main_App.processing.raw_spectral_qc import (
    CONDITION_SPECTRAL_QC_METHOD_VERSION,
    ConditionSpectralQCCancelled,
    ConditionSpectralQCThresholds,
    evaluate_condition_spectral_qc_v2,
)
from Main_App.projects import (
    EXPECTED_CYCLES_SOURCE_MANUAL,
    FrequencyProtocol,
    RawSpectralScreeningSettings,
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
    protocol = FrequencyProtocol.from_recurrence(
        6,
        5,
        expected_analyzed_oddball_cycles=12,
        expected_analyzed_oddball_cycles_source=EXPECTED_CYCLES_SOURCE_MANUAL,
    )
    return {
        "frequency_protocol": protocol,
        "base_freq": 6.0,  # Deliberately redundant legacy values.
        "oddball_freq": 1.2,
        "line_noise_filter_enabled": True,
        "line_noise_frequency_hz": mains_hz,
        "high_pass": 0.1,
        "low_pass": low_pass_hz,
        "raw_spectral_screening": RawSpectralScreeningSettings().to_manifest(),
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


@pytest.mark.parametrize(
    ("score", "noise_mean", "noise_std", "expected_flags"),
    (
        (250.0, 10.0, 20.0, 1),
        (np.nextafter(250.0, 0.0), 1.0, 1.0, 0),
        (250.0, 10.0001, 1.0, 0),
        (250.0, 10.0, 20.0001, 0),
    ),
)
def test_locked_score_ratio_and_standardized_boundaries_are_inclusive(
    monkeypatch: pytest.MonkeyPatch,
    score: float,
    noise_mean: float,
    noise_std: float,
    expected_flags: int,
) -> None:
    target_bin = 400  # 40 Hz for the ten-second, 256-Hz test span.

    def _amplitude_batches(
        _array: np.ndarray,
        *,
        window: np.ndarray,
        amplitude_last_bin: int,
        should_cancel: object,
    ):
        del window, should_cancel
        amplitudes = np.zeros((1, amplitude_last_bin + 1), dtype=np.float64)
        amplitudes[0, target_bin] = score
        yield 0, amplitudes

    monkeypatch.setattr(
        raw_spectral_qc,
        "_iter_condition_spectral_amplitude_batches",
        _amplitude_batches,
    )
    monkeypatch.setattr(
        raw_spectral_qc,
        "compute_noise_stats_for_bin",
        lambda *_args, **_kwargs: (noise_mean, noise_std),
    )

    result = evaluate_condition_spectral_qc_v2(
        np.zeros((1, 2560), dtype=np.float64),
        sfreq=256.0,
        settings=_settings(mains_hz=60, low_pass_hz=50.0),
        effective_upper_frequency_hz=50.0,
        channel_names=("Oz",),
    )

    assert len(result.unexpected_off_harmonic_flags) == expected_flags


@pytest.mark.parametrize(("channel_count", "expected"), ((48, True), (47, False)))
def test_widespread_boundary_requires_75_percent_and_at_least_48_channels(
    channel_count: int,
    expected: bool,
) -> None:
    candidates = {
        400: tuple(
            (f"EEG {index + 1}", 250.0, 25.0, 12.0)
            for index in range(channel_count)
        )
    }
    *_, unexpected = raw_spectral_qc._group_condition_peaks(
        candidates,
        frequencies=np.arange(501, dtype=np.float64) / 10.0,
        n_channels=64,
        canonical_targets_by_bin={},
        effective_notch_centers_hz=(),
        thresholds=ConditionSpectralQCThresholds(),
    )

    assert unexpected[0].widespread is expected


@pytest.mark.parametrize(
    ("notch_center", "expected_notch_matches"),
    ((40.5, 0), (np.nextafter(40.5, 40.0), 1)),
)
def test_notch_association_is_strictly_inside_half_hz_boundary(
    notch_center: float,
    expected_notch_matches: int,
) -> None:
    _expected, notch_handled, _collisions, unexpected = (
        raw_spectral_qc._group_condition_peaks(
            {400: (("Oz", 250.0, 25.0, 12.0),)},
            frequencies=np.arange(501, dtype=np.float64) / 10.0,
            n_channels=64,
            canonical_targets_by_bin={},
            effective_notch_centers_hz=(notch_center,),
            thresholds=ConditionSpectralQCThresholds(),
        )
    )

    assert len(notch_handled) == expected_notch_matches
    assert len(unexpected) == 1 - expected_notch_matches


def test_point_five_hz_screen_boundary_is_inclusive() -> None:
    eligibility = SimpleNamespace(
        targets=(
            SimpleNamespace(
                target_bin_index=49,
                target=SimpleNamespace(
                    frequency_hz=np.nextafter(0.5, 0.0),
                    oddball_harmonic_order=1,
                    presentation_harmonic_order=None,
                ),
            ),
            SimpleNamespace(
                target_bin_index=50,
                target=SimpleNamespace(
                    frequency_hz=0.5,
                    oddball_harmonic_order=1,
                    presentation_harmonic_order=None,
                ),
            ),
        )
    )

    below = raw_spectral_qc._targets_below_screen_boundary(
        eligibility,
        minimum_frequency_hz=0.5,
    )

    assert [row["fft_bin"] for row in below] == [49]


@pytest.mark.parametrize("n_samples", [257, 4096])
@pytest.mark.parametrize("kind", [
    "contiguous", "sliced", "stepped", "reversed", "fortran", "signed_zero",
    "mixed_zero", "constant", "subnormal", "overflow", "nan", "inf", "readonly",
])
def test_batched_amplitudes_are_bit_identical_to_unbatched_formula(
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    n_samples: int,
) -> None:
    rng = np.random.default_rng(641920)
    backing = rng.normal(scale=20e-6, size=(11, n_samples * 2 + 5))
    data = backing[:, 3:n_samples + 3].copy()
    if kind == "sliced":
        data = backing[:, 3:n_samples + 3]
    elif kind == "stepped":
        data = backing[:, 3:n_samples * 2 + 3:2]
    elif kind == "reversed":
        data = data[:, ::-1]
    elif kind == "fortran":
        data = np.asfortranarray(data)
    elif kind == "signed_zero":
        data = rng.choice([0.0, -0.0], size=data.shape)
    elif kind == "mixed_zero":
        data = rng.choice([-1e-5, -0.0, 0.0, 1e-5], size=data.shape)
    elif kind == "constant":
        data[:] = 1e-5
    elif kind == "subnormal":
        data *= 1e-305
    elif kind == "overflow":
        data = rng.choice([-np.finfo(float).max, np.finfo(float).max], size=data.shape)
    elif kind == "nan":
        data[0, 10] = np.nan
    elif kind == "inf":
        data[0, 10] = np.inf
    elif kind == "readonly":
        data.flags.writeable = False
    window = np.hanning(data.shape[1]).astype(np.float64, copy=False)
    amplitude_last_bin = min(900, n_samples // 2)
    with np.errstate(over="ignore", invalid="ignore", under="ignore"):
        expected_complex = np.fft.rfft(
            (data - np.median(data, axis=1, keepdims=True)) * window, axis=1,
        )
        expected = np.abs(expected_complex[:, :amplitude_last_bin + 1]) * (2.0e6 / data.shape[1])
    before = data.tobytes()
    window_before = window.tobytes()
    complex_batches = []
    original_rfft = np.fft.rfft

    def capture_fft(values, **kwargs):
        assert not np.shares_memory(values, data)
        result = original_rfft(values, **kwargs)
        complex_batches.append(result.copy())
        return result

    monkeypatch.setattr(np.fft, "rfft", capture_fft)
    monkeypatch.setattr(
        raw_spectral_qc,
        "CONDITION_SPECTRAL_QC_MAX_CHANNELS_PER_FFT_BATCH",
        3,
    )

    with np.errstate(over="ignore", invalid="ignore", under="ignore"):
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
    assert np.concatenate(complex_batches, axis=0).tobytes() == expected_complex.tobytes()
    assert data.tobytes() == before
    assert window.tobytes() == window_before


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


def test_private_scratch_reuse_preserves_former_spectral_evidence(monkeypatch):
    data = _condition_data(36.0, 40.0, 50.0, n_channels=9)
    before = data.tobytes()
    kwargs = {
        "sfreq": 256.0, "settings": _settings(mains_hz=50, low_pass_hz=100.0),
        "effective_upper_frequency_hz": 100.0, "condition_label": "Control",
    }
    observed = evaluate_condition_spectral_qc_v2(data, **kwargs)

    def former_batches(array, *, window, amplitude_last_bin, should_cancel):
        n_channels, n_samples = array.shape
        size = raw_spectral_qc._condition_fft_batch_size(
            n_samples=n_samples, n_amplitude_bins=amplitude_last_bin + 1,
        )
        scale = 2.0e6 / n_samples
        for start in range(0, n_channels, size):
            centered = array[start:start + size] - np.median(
                array[start:start + size], axis=1, keepdims=True,
            )
            spectra = np.fft.rfft(centered * window, axis=1)
            yield start, np.abs(spectra[:, :amplitude_last_bin + 1]) * scale

    monkeypatch.setattr(raw_spectral_qc, "_iter_condition_spectral_amplitude_batches", former_batches)
    expected = evaluate_condition_spectral_qc_v2(data, **kwargs)
    assert observed.to_payload() == expected.to_payload()
    assert data.tobytes() == before


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


def test_current_screen_rejects_legacy_rate_fallback() -> None:
    settings = _settings(mains_hz=60, low_pass_hz=50.0)
    settings.pop("frequency_protocol")

    with pytest.raises(ValueError, match="canonical project frequency protocol"):
        evaluate_condition_spectral_qc_v2(
            _condition_data(),
            sfreq=256.0,
            settings=settings,
            effective_upper_frequency_hz=50.0,
        )


def test_expected_peak_classification_uses_exact_project_bin_not_point_08_hz() -> None:
    duration_s = 120.0
    protocol = FrequencyProtocol.from_recurrence(
        6,
        5,
        expected_analyzed_oddball_cycles=144,
        expected_analyzed_oddball_cycles_source=EXPECTED_CYCLES_SOURCE_MANUAL,
    )
    settings = _settings(mains_hz=60, low_pass_hz=10.0)
    settings["frequency_protocol"] = protocol

    result = evaluate_condition_spectral_qc_v2(
        _condition_data(1.25, duration_s=duration_s, n_channels=1),
        sfreq=256.0,
        settings=settings,
        effective_upper_frequency_hz=10.0,
        channel_names=("Oz",),
    )

    assert result.expected_harmonic_peaks == ()
    assert len(result.unexpected_off_harmonic_flags) == 1
    assert result.unexpected_off_harmonic_flags[0].frequency_hz == pytest.approx(1.25)
    assert result.thresholds["expected_peak_classification"] == (
        "exact_canonical_fft_bin"
    )
    assert result.thresholds["legacy_harmonic_tolerance_hz"] is None


def test_nondefault_three_hz_every_ten_protocol_and_sub_point_5_target_are_explicit() -> None:
    protocol = FrequencyProtocol.from_recurrence(
        3,
        10,
        expected_analyzed_oddball_cycles=30,
        expected_analyzed_oddball_cycles_source=EXPECTED_CYCLES_SOURCE_MANUAL,
    )
    settings = _settings(mains_hz=60, low_pass_hz=10.0)
    settings["frequency_protocol"] = protocol

    result = evaluate_condition_spectral_qc_v2(
        _condition_data(3.0, duration_s=100.0, n_channels=1),
        sfreq=256.0,
        settings=settings,
        effective_upper_frequency_hz=10.0,
        channel_names=("Oz",),
    )

    assert [peak.frequency_hz for peak in result.expected_harmonic_peaks] == pytest.approx(
        [3.0]
    )
    first_below = result.targets_below_screen_boundary[0]
    assert first_below["frequency_hz"] == pytest.approx(0.3)
    assert first_below["evaluation_status"] == "not_evaluated"
    assert result.has_review_flags is True
    assert result.presentation_rate_hz == pytest.approx(3.0)
    assert result.oddball_rate_hz == pytest.approx(0.3)
    assert result.fixed_noise_neighborhood_half_width_hz == pytest.approx(0.12)
    assert result.fixed_noise_neighborhood_total_span_hz == pytest.approx(0.24)


def test_current_policy_rejects_unversioned_threshold_override() -> None:
    with pytest.raises(ValueError, match="thresholds are locked"):
        evaluate_condition_spectral_qc_v2(
            _condition_data(3.0, n_channels=1),
            sfreq=256.0,
            settings=_settings(mains_hz=60, low_pass_hz=10.0),
            effective_upper_frequency_hz=10.0,
            thresholds=ConditionSpectralQCThresholds(
                min_legacy_hann_spectrum_score=251.0
            ),
        )


def test_disabled_project_setting_is_not_performed_and_runs_no_fft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(mains_hz=60, low_pass_hz=50.0)
    settings["raw_spectral_screening"] = RawSpectralScreeningSettings(
        enabled=False
    ).to_manifest()
    settings.pop("frequency_protocol")
    monkeypatch.setattr(
        raw_spectral_qc.np.fft,
        "rfft",
        lambda *_args, **_kwargs: pytest.fail("disabled screening ran an FFT"),
    )

    result = evaluate_condition_spectral_qc_v2(
        _condition_data(40.0),
        sfreq=256.0,
        settings=settings,
        effective_upper_frequency_hz=50.0,
    )

    assert result.evaluation_status == "not_performed_disabled"
    assert result.evaluated is False
    assert result.has_review_flags is False
    assert result.unexpected_off_harmonic_flags == ()
    assert result.notch_collisions == ()
    assert result.frequency_protocol_fingerprint == ""


def test_notch_collisions_are_visible_without_an_observed_peak() -> None:
    result = evaluate_condition_spectral_qc_v2(
        _condition_data(n_channels=2),
        sfreq=256.0,
        settings=_settings(mains_hz=60, low_pass_hz=100.0),
        effective_upper_frequency_hz=100.0,
        channel_names=("O1", "Oz"),
    )

    direct = next(
        collision
        for collision in result.notch_collisions
        if collision.target_frequency_hz == pytest.approx(60.0)
    )
    assert direct.target_notch_centers_hz == (60.0,)
    assert direct.affected_channels == ("O1", "Oz")
    assert direct.standard_analysis_effect == (
        "target_and_standard_noise_metrics_unavailable"
    )
    assert any(
        not collision.target_notch_centers_hz and collision.noise_bin_collisions
        for collision in result.notch_collisions
    )
    assert result.unexpected_off_harmonic_flags == ()
    assert result.has_review_flags is True
