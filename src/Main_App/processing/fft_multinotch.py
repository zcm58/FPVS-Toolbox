"""Frequency-domain multi-notch filtering for mains line noise.

The helper in this module is intentionally isolated from project settings and
pipeline orchestration.  It applies the versioned FPVS multi-notch definition
to preloaded EEG data and leaves all Raw metadata untouched.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import mne
import numpy as np

FFT_MULTINOTCH_METHOD_VERSION = "fft_hann_multinotch_v1"
FFT_MULTINOTCH_HALF_WIDTH_HZ = 0.5
FFT_MULTINOTCH_COMPONENT_COUNT = 3

_SUPPORTED_FUNDAMENTALS_HZ = (50.0, 60.0)

__all__ = [
    "FFT_MULTINOTCH_COMPONENT_COUNT",
    "FFT_MULTINOTCH_HALF_WIDTH_HZ",
    "FFT_MULTINOTCH_METHOD_VERSION",
    "FFTMultiNotchResult",
    "SkippedNotchCenter",
    "apply_fft_multinotch",
    "build_fft_multinotch_mask",
    "resolve_effective_centers",
]


@dataclass(frozen=True)
class SkippedNotchCenter:
    """A requested notch center that was not applied."""

    center_hz: float
    reason: str


@dataclass(frozen=True)
class FFTMultiNotchResult:
    """Structured record of one multi-notch decision and application."""

    method_version: str
    fundamental_hz: float
    half_width_hz: float
    requested_centers_hz: tuple[float, ...]
    applied_centers_hz: tuple[float, ...]
    skipped_centers: tuple[SkippedNotchCenter, ...]
    filtered_channels: tuple[str, ...]
    segment_count: int

    @property
    def did_filter(self) -> bool:
        """Return whether any EEG samples were transformed."""

        return bool(self.applied_centers_hz and self.filtered_channels and self.segment_count)


def _validated_fundamental(fundamental_hz: float) -> float:
    try:
        fundamental = float(fundamental_hz)
    except (TypeError, ValueError) as exc:
        raise ValueError("Mains frequency must be either 50 or 60 Hz.") from exc
    if not np.isfinite(fundamental) or fundamental not in _SUPPORTED_FUNDAMENTALS_HZ:
        raise ValueError("Mains frequency must be either 50 or 60 Hz.")
    return fundamental


def _validated_positive_float(value: float, *, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive finite number.") from exc
    if not np.isfinite(number) or number <= 0.0:
        raise ValueError(f"{name} must be a positive finite number.")
    return number


def resolve_effective_centers(
    *,
    fundamental_hz: float,
    sfreq: float,
    low_pass: float | None,
    h_trans_bandwidth: float = 0.1,
    half_width_hz: float = FFT_MULTINOTCH_HALF_WIDTH_HZ,
) -> tuple[
    tuple[float, ...],
    tuple[float, ...],
    tuple[SkippedNotchCenter, ...],
]:
    """Resolve requested centers that can still overlap the retained spectrum.

    A center is effective only when its full Hann support is below the raw
    Nyquist frequency and some part of that support reaches the existing FIR
    low-pass transition.  The latter condition avoids a redundant FFT/IFFT
    when the preceding FIR has already removed the requested component.
    """

    fundamental = _validated_fundamental(fundamental_hz)
    sample_rate = _validated_positive_float(sfreq, name="Sampling frequency")
    half_width = _validated_positive_float(half_width_hz, name="Notch half-width")
    transition = _validated_positive_float(
        h_trans_bandwidth,
        name="Low-pass transition bandwidth",
    )
    if low_pass is None:
        upper_passband = None
    else:
        try:
            upper_passband = float(low_pass)
        except (TypeError, ValueError) as exc:
            raise ValueError("Low-pass frequency must be finite and non-negative.") from exc
        if not np.isfinite(upper_passband) or upper_passband < 0.0:
            raise ValueError("Low-pass frequency must be finite and non-negative.")

    requested = tuple(
        fundamental * multiplier
        for multiplier in range(1, FFT_MULTINOTCH_COMPONENT_COUNT + 1)
    )
    effective: list[float] = []
    skipped: list[SkippedNotchCenter] = []
    nyquist = sample_rate / 2.0

    for center in requested:
        if center + half_width >= nyquist:
            skipped.append(
                SkippedNotchCenter(
                    center_hz=center,
                    reason="notch_support_reaches_or_exceeds_nyquist",
                )
            )
            continue
        if (
            upper_passband is not None
            and center - half_width > upper_passband + transition
        ):
            skipped.append(
                SkippedNotchCenter(
                    center_hz=center,
                    reason="above_low_pass_transition",
                )
            )
            continue
        effective.append(center)

    return requested, tuple(effective), tuple(skipped)


def build_fft_multinotch_mask(
    *,
    n_times: int,
    sfreq: float,
    centers_hz: Iterable[float],
    half_width_hz: float = FFT_MULTINOTCH_HALF_WIDTH_HZ,
) -> np.ndarray:
    """Build the real-FFT Hann attenuation mask for the supplied centers."""

    if isinstance(n_times, bool) or not isinstance(n_times, (int, np.integer)):
        raise ValueError("Number of samples must be a positive integer.")
    sample_count = int(n_times)
    if sample_count <= 0:
        raise ValueError("Number of samples must be a positive integer.")
    sample_rate = _validated_positive_float(sfreq, name="Sampling frequency")
    half_width = _validated_positive_float(half_width_hz, name="Notch half-width")

    centers: list[float] = []
    for value in centers_hz:
        try:
            center = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("Notch centers must be positive finite numbers.") from exc
        if not np.isfinite(center) or center <= 0.0:
            raise ValueError("Notch centers must be positive finite numbers.")
        centers.append(center)

    frequencies = np.fft.rfftfreq(sample_count, d=1.0 / sample_rate)
    mask = np.ones(frequencies.shape, dtype=np.float64)
    for center in centers:
        distance = np.abs(frequencies - center)
        inside = distance < half_width
        mask[inside] *= 0.5 * (
            1.0 - np.cos(np.pi * distance[inside] / half_width)
        )
    return mask


def _edge_contiguous_segments(raw: mne.io.BaseRaw) -> tuple[tuple[int, int], ...]:
    """Return the same contiguous spans used by MNE 1.9 for ``edge`` skips."""

    # This is the helper used internally by Raw.filter in the repository's
    # pinned MNE 1.9 runtime.  Keeping the call local contains the private API
    # dependency and preserves the established edge-annotation semantics.
    from mne.annotations import _annotations_starts_stops

    onsets, ends = _annotations_starts_stops(raw, "edge", invert=True)
    return tuple(
        (int(start), int(stop))
        for start, stop in zip(onsets, ends)
        if int(stop) > int(start)
    )


def _result(
    *,
    fundamental_hz: float,
    requested: tuple[float, ...],
    applied: tuple[float, ...],
    skipped: tuple[SkippedNotchCenter, ...],
    filtered_channels: tuple[str, ...] = (),
    segment_count: int = 0,
) -> FFTMultiNotchResult:
    return FFTMultiNotchResult(
        method_version=FFT_MULTINOTCH_METHOD_VERSION,
        fundamental_hz=fundamental_hz,
        half_width_hz=FFT_MULTINOTCH_HALF_WIDTH_HZ,
        requested_centers_hz=requested,
        applied_centers_hz=applied,
        skipped_centers=skipped,
        filtered_channels=filtered_channels,
        segment_count=segment_count,
    )


def apply_fft_multinotch(
    raw: mne.io.BaseRaw,
    *,
    fundamental_hz: float,
    low_pass: float | None,
    stim_channel: str | None,
    h_trans_bandwidth: float = 0.1,
) -> FFTMultiNotchResult:
    """Apply the versioned FFT multi-notch to eligible EEG data in place.

    Bad EEG channels remain eligible so that later interpolation sees the same
    preprocessing as the retained channels.  The configured stimulation
    channel and all non-EEG channel types are never transformed.
    """

    fundamental = _validated_fundamental(fundamental_hz)
    requested, effective, skipped = resolve_effective_centers(
        fundamental_hz=fundamental,
        sfreq=float(raw.info["sfreq"]),
        low_pass=low_pass,
        h_trans_bandwidth=h_trans_bandwidth,
    )

    # This early return is the bit-preserving path when the FIR has already
    # removed every requested component (or the raw Nyquist cannot contain it).
    if not effective:
        return _result(
            fundamental_hz=fundamental,
            requested=requested,
            applied=(),
            skipped=skipped,
        )

    if not raw.preload:
        raise RuntimeError("FFT multi-notch filtering requires preloaded Raw data.")

    eeg_picks = tuple(
        int(pick)
        for pick in mne.pick_types(raw.info, eeg=True, exclude=[])
        if stim_channel is None or raw.ch_names[int(pick)] != stim_channel
    )
    if not eeg_picks:
        no_channels = skipped + tuple(
            SkippedNotchCenter(center_hz=center, reason="no_eligible_eeg_channels")
            for center in effective
        )
        return _result(
            fundamental_hz=fundamental,
            requested=requested,
            applied=(),
            skipped=no_channels,
        )

    # Validate all selected data before changing the first channel, preventing
    # a late nonfinite value from leaving a partially filtered Raw object.
    for pick in eeg_picks:
        if not np.isfinite(raw._data[pick]).all():
            channel = raw.ch_names[pick]
            raise ValueError(
                f"FFT multi-notch cannot filter nonfinite EEG data in channel {channel!r}."
            )

    segments = _edge_contiguous_segments(raw)
    if not segments:
        no_segments = skipped + tuple(
            SkippedNotchCenter(center_hz=center, reason="no_contiguous_data_segments")
            for center in effective
        )
        return _result(
            fundamental_hz=fundamental,
            requested=requested,
            applied=(),
            skipped=no_segments,
        )

    sfreq = float(raw.info["sfreq"])
    masks_by_length: dict[int, np.ndarray] = {}
    for start, stop in segments:
        segment_length = stop - start
        mask = masks_by_length.get(segment_length)
        if mask is None:
            mask = build_fft_multinotch_mask(
                n_times=segment_length,
                sfreq=sfreq,
                centers_hz=effective,
            )
            masks_by_length[segment_length] = mask
        for pick in eeg_picks:
            signal = raw._data[pick, start:stop]
            spectrum = np.fft.rfft(signal)
            signal[:] = np.fft.irfft(spectrum * mask, n=segment_length)

    filtered_channels = tuple(raw.ch_names[pick] for pick in eeg_picks)
    return _result(
        fundamental_hz=fundamental,
        requested=requested,
        applied=effective,
        skipped=skipped,
        filtered_channels=filtered_channels,
        segment_count=len(segments),
    )
