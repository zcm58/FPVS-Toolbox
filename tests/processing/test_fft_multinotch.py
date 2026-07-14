from __future__ import annotations

import mne
import numpy as np
import pytest

from Main_App.processing import fft_multinotch
from Main_App.processing.fft_multinotch import (
    FFT_MULTINOTCH_COMPONENT_COUNT,
    FFT_MULTINOTCH_HALF_WIDTH_HZ,
    FFT_MULTINOTCH_METHOD_VERSION,
    apply_fft_multinotch,
    build_fft_multinotch_mask,
    resolve_effective_centers,
)


def _frequency_index(*, n_times: int, sfreq: float, frequency_hz: float) -> int:
    frequencies = np.fft.rfftfreq(n_times, d=1.0 / sfreq)
    return int(np.argmin(np.abs(frequencies - frequency_hz)))


def _raw(
    data: np.ndarray,
    *,
    sfreq: float,
    ch_names: list[str] | None = None,
    ch_types: list[str] | None = None,
) -> mne.io.RawArray:
    if ch_names is None:
        ch_names = [f"E{index + 1}" for index in range(data.shape[0])]
    if ch_types is None:
        ch_types = ["eeg"] * data.shape[0]
    info = mne.create_info(ch_names, sfreq=sfreq, ch_types=ch_types)
    return mne.io.RawArray(data, info, verbose=False)


def test_versioned_constants_define_fundamental_plus_two_harmonics() -> None:
    assert FFT_MULTINOTCH_METHOD_VERSION == "fft_hann_multinotch_v1"
    assert FFT_MULTINOTCH_HALF_WIDTH_HZ == 0.5
    assert FFT_MULTINOTCH_COMPONENT_COUNT == 3

    requested_50, effective_50, _ = resolve_effective_centers(
        fundamental_hz=50,
        sfreq=512,
        low_pass=None,
    )
    requested_60, effective_60, _ = resolve_effective_centers(
        fundamental_hz=60,
        sfreq=512,
        low_pass=None,
    )

    assert requested_50 == effective_50 == (50.0, 100.0, 150.0)
    assert requested_60 == effective_60 == (60.0, 120.0, 180.0)


def test_hann_mask_has_expected_gain_at_center_quarter_and_half_hz() -> None:
    sfreq = 256.0
    n_times = 1024  # 0.25-Hz FFT bins
    mask = build_fft_multinotch_mask(
        n_times=n_times,
        sfreq=sfreq,
        centers_hz=(50.0,),
    )

    assert mask[_frequency_index(n_times=n_times, sfreq=sfreq, frequency_hz=50.0)] == pytest.approx(0.0)
    assert mask[_frequency_index(n_times=n_times, sfreq=sfreq, frequency_hz=49.75)] == pytest.approx(0.5)
    assert mask[_frequency_index(n_times=n_times, sfreq=sfreq, frequency_hz=50.25)] == pytest.approx(0.5)
    assert mask[_frequency_index(n_times=n_times, sfreq=sfreq, frequency_hz=49.5)] == pytest.approx(1.0)
    assert mask[_frequency_index(n_times=n_times, sfreq=sfreq, frequency_hz=50.5)] == pytest.approx(1.0)


@pytest.mark.parametrize(
    ("fundamental_hz", "low_pass", "expected"),
    [
        (50.0, 50.0, (50.0,)),
        (50.0, 100.0, (50.0, 100.0)),
        (60.0, 50.0, ()),
        (60.0, 100.0, (60.0,)),
        (60.0, None, (60.0, 120.0, 180.0)),
    ],
)
def test_low_pass_prunes_already_removed_centers(
    fundamental_hz: float,
    low_pass: float | None,
    expected: tuple[float, ...],
) -> None:
    _, effective, skipped = resolve_effective_centers(
        fundamental_hz=fundamental_hz,
        sfreq=512.0,
        low_pass=low_pass,
    )

    assert effective == expected
    assert all(item.reason == "above_low_pass_transition" for item in skipped)


def test_center_whose_support_reaches_nyquist_is_skipped() -> None:
    requested, effective, skipped = resolve_effective_centers(
        fundamental_hz=50,
        sfreq=301.0,
        low_pass=None,
    )

    assert requested == (50.0, 100.0, 150.0)
    assert effective == (50.0, 100.0)
    assert skipped == (
        fft_multinotch.SkippedNotchCenter(
            center_hz=150.0,
            reason="notch_support_reaches_or_exceeds_nyquist",
        ),
    )


def test_no_effective_centers_returns_before_fft_and_preserves_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rng = np.random.default_rng(20260714)
    raw = _raw(rng.standard_normal((2, 513)), sfreq=512.0)
    before = raw._data.tobytes()

    def _unexpected_fft(*args: object, **kwargs: object) -> None:
        raise AssertionError("FFT must not run when the FIR already removed all centers")

    monkeypatch.setattr(fft_multinotch.np.fft, "rfft", _unexpected_fft)

    result = apply_fft_multinotch(
        raw,
        fundamental_hz=60,
        low_pass=50.0,
        stim_channel="Status",
    )

    assert result.did_filter is False
    assert result.applied_centers_hz == ()
    assert raw._data.tobytes() == before


def test_filter_attenuates_center_and_preserves_outside_frequency() -> None:
    sfreq = 512.0
    n_times = 5120
    times = np.arange(n_times) / sfreq
    data = np.sin(2 * np.pi * 10.0 * times) + np.sin(2 * np.pi * 60.0 * times)
    raw = _raw(data[np.newaxis, :], sfreq=sfreq)

    result = apply_fft_multinotch(
        raw,
        fundamental_hz=60,
        low_pass=100.0,
        stim_channel="Status",
    )

    spectrum = np.abs(np.fft.rfft(raw._data[0]))
    ten_hz = spectrum[_frequency_index(n_times=n_times, sfreq=sfreq, frequency_hz=10.0)]
    sixty_hz = spectrum[_frequency_index(n_times=n_times, sfreq=sfreq, frequency_hz=60.0)]
    assert result.did_filter is True
    assert result.applied_centers_hz == (60.0,)
    assert ten_hz == pytest.approx(n_times / 2.0, rel=1e-12)
    assert sixty_hz < 1e-8


def test_filter_preserves_odd_length_shape_and_dtype() -> None:
    rng = np.random.default_rng(55)
    original = rng.standard_normal((1, 5119)).astype(np.float64)
    raw = _raw(original, sfreq=511.9)
    original_shape = raw._data.shape
    original_dtype = raw._data.dtype

    result = apply_fft_multinotch(
        raw,
        fundamental_hz=60,
        low_pass=100.0,
        stim_channel="Status",
    )

    assert result.did_filter is True
    assert raw._data.shape == original_shape
    assert raw._data.dtype == original_dtype


def test_only_eeg_channels_are_filtered_and_stim_name_is_explicitly_excluded() -> None:
    sfreq = 512.0
    n_times = 5120
    times = np.arange(n_times) / sfreq
    sine = np.sin(2 * np.pi * 60.0 * times)
    status = np.zeros(n_times)
    status[[100, 500, 1000]] = [11.0, 12.0, 13.0]
    auxiliary = sine.copy()
    raw = _raw(
        np.vstack([sine, status, auxiliary]),
        sfreq=sfreq,
        ch_names=["E1", "Status", "AUX"],
        ch_types=["eeg", "eeg", "misc"],
    )
    raw.info["bads"] = ["E1"]
    status_before = raw._data[1].tobytes()
    auxiliary_before = raw._data[2].tobytes()

    result = apply_fft_multinotch(
        raw,
        fundamental_hz=60,
        low_pass=100.0,
        stim_channel="Status",
    )

    assert result.filtered_channels == ("E1",)
    assert np.max(np.abs(raw._data[0])) < 1e-10
    assert raw._data[1].tobytes() == status_before
    assert raw._data[2].tobytes() == auxiliary_before


def test_nonfinite_selected_data_raises_before_any_channel_is_mutated() -> None:
    rng = np.random.default_rng(77)
    data = rng.standard_normal((2, 1024))
    data[1, 700] = np.nan
    raw = _raw(data, sfreq=512.0)
    first_channel_before = raw._data[0].tobytes()

    with pytest.raises(ValueError, match="nonfinite EEG data.*E2"):
        apply_fft_multinotch(
            raw,
            fundamental_hz=60,
            low_pass=100.0,
            stim_channel="Status",
        )

    assert raw._data[0].tobytes() == first_channel_before


def test_edge_annotation_splits_fft_and_prevents_cross_boundary_influence() -> None:
    sfreq = 512.0
    segment_times = np.arange(2560) / sfreq
    first_segment = np.sin(2 * np.pi * 60.0 * segment_times)
    raw = _raw(np.concatenate([first_segment, np.zeros(2560)])[np.newaxis, :], sfreq=sfreq)
    raw.set_annotations(
        mne.Annotations(
            onset=[5.0],
            duration=[0.0],
            description=["EDGE boundary"],
        )
    )

    result = apply_fft_multinotch(
        raw,
        fundamental_hz=60,
        low_pass=100.0,
        stim_channel="Status",
    )

    assert result.segment_count == 2
    assert np.max(np.abs(raw._data[0, :2560])) < 1e-10
    assert np.array_equal(raw._data[0, 2560:], np.zeros(2560))


@pytest.mark.parametrize("fundamental_hz", [0, 49, 55, 61, np.nan])
def test_only_50_or_60_hz_fundamentals_are_accepted(fundamental_hz: float) -> None:
    with pytest.raises(ValueError, match="either 50 or 60 Hz"):
        resolve_effective_centers(
            fundamental_hz=fundamental_hz,
            sfreq=512.0,
            low_pass=100.0,
        )
