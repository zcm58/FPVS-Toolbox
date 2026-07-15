"""Lightweight raw-spectrum QC used by preprocessing preflight review."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Callable, Iterator, Mapping, Sequence

import numpy as np

from Main_App.processing.fft_multinotch import (
    FFT_MULTINOTCH_HALF_WIDTH_HZ,
    SkippedNotchCenter,
    resolve_effective_centers,
)
from Main_App.processing.raw_channel_qc import SCALP_CHANNELS
from Tools.Stats.analysis.noise_utils import compute_noise_stats_for_bin


CONDITION_SPECTRAL_QC_METHOD_VERSION = "condition_onbin_spectral_qc_v2"
CONDITION_SPECTRAL_QC_NOISE_WINDOW_BINS = 12
CONDITION_SPECTRAL_QC_NOISE_CANDIDATE_BINS = 22
CONDITION_SPECTRAL_QC_NOISE_RETAINED_BINS = 20
CONDITION_SPECTRAL_QC_FFT_BATCH_TARGET_BYTES = 64 * 1024 * 1024
CONDITION_SPECTRAL_QC_MAX_CHANNELS_PER_FFT_BATCH = 8


class ConditionSpectralQCCancelled(RuntimeError):
    """Raised when condition spectral QC is cancelled between FFT batches."""


@dataclass(frozen=True)
class RawSpectralQCThresholds:
    """Conservative thresholds for pre-processing spectral artifact review."""

    min_frequency_hz: float = 0.5
    max_frequency_hz: float = 30.0
    max_duration_s: float = 90.0
    min_peak_amplitude_uv: float = 250.0
    min_local_ratio: float = 25.0
    min_robust_z: float = 12.0
    widespread_channel_fraction: float = 0.75
    widespread_min_channels: int = 48
    harmonic_tolerance_hz: float = 0.08
    local_noise_bins: int = 8


@dataclass(frozen=True)
class RawSpectralQCResult:
    """Participant-level summary of conservative raw-spectrum artifact flags."""

    evaluated: bool
    widespread: bool
    message: str
    n_channels: int
    flagged_channels: tuple[str, ...]
    peak_frequency_hz: float | None
    max_amplitude_uv: float
    max_local_ratio: float
    thresholds: Mapping[str, float | int]

    def to_payload(self) -> dict[str, object]:
        return {
            "evaluated": self.evaluated,
            "widespread": self.widespread,
            "message": self.message,
            "n_channels": self.n_channels,
            "flagged_channels": list(self.flagged_channels),
            "peak_frequency_hz": self.peak_frequency_hz,
            "max_amplitude_uv": self.max_amplitude_uv,
            "max_local_ratio": self.max_local_ratio,
            "thresholds": dict(self.thresholds),
        }


def _threshold_payload(
    thresholds: RawSpectralQCThresholds,
) -> dict[str, float | int]:
    return {
        "min_frequency_hz": thresholds.min_frequency_hz,
        "max_frequency_hz": thresholds.max_frequency_hz,
        "max_duration_s": thresholds.max_duration_s,
        "min_peak_amplitude_uv": thresholds.min_peak_amplitude_uv,
        "min_local_ratio": thresholds.min_local_ratio,
        "min_robust_z": thresholds.min_robust_z,
        "widespread_channel_fraction": thresholds.widespread_channel_fraction,
        "widespread_min_channels": thresholds.widespread_min_channels,
        "harmonic_tolerance_hz": thresholds.harmonic_tolerance_hz,
        "local_noise_bins": thresholds.local_noise_bins,
    }


def _empty_result(
    *,
    message: str,
    thresholds: RawSpectralQCThresholds,
    n_channels: int = 0,
) -> RawSpectralQCResult:
    return RawSpectralQCResult(
        evaluated=False,
        widespread=False,
        message=message,
        n_channels=n_channels,
        flagged_channels=(),
        peak_frequency_hz=None,
        max_amplitude_uv=0.0,
        max_local_ratio=0.0,
        thresholds=_threshold_payload(thresholds),
    )


def _is_expected_harmonic(
    frequency: float,
    *,
    base_freq: float,
    oddball_freq: float,
    tolerance_hz: float,
) -> bool:
    for fundamental in (base_freq, oddball_freq):
        if not math.isfinite(fundamental) or fundamental <= 0:
            continue
        harmonic = round(frequency / fundamental)
        if harmonic <= 0:
            continue
        if abs(frequency - harmonic * fundamental) <= tolerance_hz:
            return True
    return False


def _scalp_picks(raw: Any, *, stim_channel: str, ref_channels: Sequence[str]) -> list[int]:
    ref_lookup = {str(channel) for channel in ref_channels if channel}
    picks: list[int] = []
    for index, channel in enumerate(getattr(raw, "ch_names", [])):
        name = str(channel)
        if name == stim_channel or name in ref_lookup:
            continue
        if name in SCALP_CHANNELS:
            picks.append(index)
    return picks


def _safe_get_data(raw: Any, picks: Sequence[int], stop: int) -> np.ndarray:
    try:
        return raw.get_data(picks=picks, start=0, stop=stop, verbose=False)
    except TypeError:
        return raw.get_data(picks=picks, start=0, stop=stop)


def _local_baseline(amplitudes: np.ndarray, index: int, radius: int) -> float:
    left = max(0, index - radius)
    right = min(amplitudes.shape[0], index + radius + 1)
    local = amplitudes[left:right]
    if local.size <= 3:
        return 0.0
    center = index - left
    mask = np.ones(local.shape[0], dtype=bool)
    for offset in (-1, 0, 1):
        pos = center + offset
        if 0 <= pos < mask.shape[0]:
            mask[pos] = False
    reference = local[mask]
    finite = reference[np.isfinite(reference) & (reference > 0.0)]
    if finite.size == 0:
        return 0.0
    return float(np.median(finite))


def _robust_z(values: np.ndarray, index: int) -> float:
    finite = values[np.isfinite(values)]
    if finite.size < 8:
        return 0.0
    median = float(np.median(finite))
    mad = float(np.median(np.abs(finite - median)))
    scale = 1.4826 * mad
    if scale <= 0.0 or not math.isfinite(scale):
        return 0.0
    return float((values[index] - median) / scale)


def _float_setting(settings: Mapping[str, Any], key: str, default: float) -> float:
    try:
        value = float(settings.get(key, default))
    except (TypeError, ValueError):
        return float(default)
    return value if math.isfinite(value) else float(default)


def evaluate_raw_spectral_qc(
    raw: Any,
    settings: Mapping[str, Any],
    *,
    filename: str,
    thresholds: RawSpectralQCThresholds | None = None,
) -> RawSpectralQCResult:
    """Flag only very strong, widespread off-harmonic raw spectral peaks."""

    thresholds = thresholds or RawSpectralQCThresholds()
    stim_channel = str(settings.get("stim_channel") or "")
    ref_channels = (
        str(settings.get("ref_channel1") or settings.get("ref_ch1") or ""),
        str(settings.get("ref_channel2") or settings.get("ref_ch2") or ""),
    )
    picks = _scalp_picks(raw, stim_channel=stim_channel, ref_channels=ref_channels)
    n_channels = len(picks)
    if n_channels == 0:
        return _empty_result(
            message=f"Raw spectral QC skipped for {filename}: no scalp EEG channels found.",
            thresholds=thresholds,
        )

    sfreq = float(getattr(raw, "info", {}).get("sfreq", 0.0))
    n_times = int(getattr(raw, "n_times", 0))
    if sfreq <= 0.0 or n_times <= 8:
        return _empty_result(
            message=f"Raw spectral QC skipped for {filename}: not enough samples.",
            thresholds=thresholds,
            n_channels=n_channels,
        )

    stop = min(n_times, max(8, int(round(thresholds.max_duration_s * sfreq))))
    data = _safe_get_data(raw, picks, stop)
    if data.size == 0 or data.shape[1] <= 8:
        return _empty_result(
            message=f"Raw spectral QC skipped for {filename}: no readable EEG samples.",
            thresholds=thresholds,
            n_channels=n_channels,
        )

    data = np.asarray(data, dtype=float)
    data = data - np.nanmedian(data, axis=1, keepdims=True)
    window = np.hanning(data.shape[1])
    if not np.any(window):
        return _empty_result(
            message=f"Raw spectral QC skipped for {filename}: invalid spectral window.",
            thresholds=thresholds,
            n_channels=n_channels,
        )
    amplitudes_uv = (
        np.abs(np.fft.rfft(data * window, axis=1)) * 2.0 / max(1, data.shape[1])
    ) * 1e6
    freqs = np.fft.rfftfreq(data.shape[1], d=1.0 / sfreq)
    base_freq = _float_setting(settings, "base_freq", 6.0)
    analysis = settings.get("analysis")
    oddball_default = 1.2
    if isinstance(analysis, Mapping):
        oddball_default = _float_setting(analysis, "oddball_freq", oddball_default)
    oddball_freq = _float_setting(settings, "oddball_freq", oddball_default)
    freq_mask = (
        (freqs >= thresholds.min_frequency_hz)
        & (freqs <= thresholds.max_frequency_hz)
    )
    usable_indices = [
        int(index)
        for index in np.flatnonzero(freq_mask)
        if not _is_expected_harmonic(
            float(freqs[index]),
            base_freq=base_freq,
            oddball_freq=oddball_freq,
            tolerance_hz=thresholds.harmonic_tolerance_hz,
        )
    ]
    if not usable_indices:
        return _empty_result(
            message=f"Raw spectral QC skipped for {filename}: no off-harmonic bins available.",
            thresholds=thresholds,
            n_channels=n_channels,
        )

    channel_names = [str(raw.ch_names[index]) for index in picks]
    candidates: list[tuple[str, int, float, float, float]] = []
    usable = np.asarray(usable_indices, dtype=int)
    for row_index, channel in enumerate(channel_names):
        row = amplitudes_uv[row_index]
        usable_values = row[usable]
        if not np.any(np.isfinite(usable_values)):
            continue
        local_best: tuple[int, float, float, float] | None = None
        for freq_index in usable_indices:
            amplitude = float(row[freq_index])
            if not math.isfinite(amplitude) or amplitude < thresholds.min_peak_amplitude_uv:
                continue
            baseline = _local_baseline(
                row,
                freq_index,
                thresholds.local_noise_bins,
            )
            if baseline <= 0.0:
                continue
            ratio = amplitude / baseline
            z_score = _robust_z(usable_values, int(np.where(usable == freq_index)[0][0]))
            if ratio < thresholds.min_local_ratio or z_score < thresholds.min_robust_z:
                continue
            if local_best is None or amplitude > local_best[1]:
                local_best = (freq_index, amplitude, ratio, z_score)
        if local_best is not None:
            freq_index, amplitude, ratio, z_score = local_best
            candidates.append((channel, freq_index, amplitude, ratio, z_score))

    if not candidates:
        return RawSpectralQCResult(
            evaluated=True,
            widespread=False,
            message=f"Raw spectral QC passed for {filename}: no strong widespread off-harmonic peaks were found.",
            n_channels=n_channels,
            flagged_channels=(),
            peak_frequency_hz=None,
            max_amplitude_uv=0.0,
            max_local_ratio=0.0,
            thresholds=_threshold_payload(thresholds),
        )

    by_index: dict[int, list[tuple[str, float, float, float]]] = {}
    for channel, freq_index, amplitude, ratio, z_score in candidates:
        by_index.setdefault(freq_index, []).append((channel, amplitude, ratio, z_score))
    min_widespread = max(
        int(thresholds.widespread_min_channels),
        int(math.ceil(n_channels * thresholds.widespread_channel_fraction)),
    )
    best_index, best_rows = max(
        by_index.items(),
        key=lambda item: (len(item[1]), max(row[1] for row in item[1])),
    )
    flagged_channels = tuple(sorted(row[0] for row in best_rows))
    max_amplitude = max(float(row[1]) for row in best_rows)
    max_ratio = max(float(row[2]) for row in best_rows)
    peak_hz = float(freqs[best_index])
    widespread = len(best_rows) >= min_widespread
    if widespread:
        message = (
            f"{filename} has a widespread raw spectral artifact: "
            f"{len(best_rows)}/{n_channels} scalp channels have a strong "
            f"off-harmonic peak near {peak_hz:.2f} Hz."
        )
    else:
        message = (
            f"Raw spectral QC flagged {len(best_rows)}/{n_channels} channel(s) "
            f"near {peak_hz:.2f} Hz for review."
        )
    return RawSpectralQCResult(
        evaluated=True,
        widespread=widespread,
        message=message,
        n_channels=n_channels,
        flagged_channels=flagged_channels,
        peak_frequency_hz=peak_hz,
        max_amplitude_uv=max_amplitude,
        max_local_ratio=max_ratio,
        thresholds=_threshold_payload(thresholds),
    )


@dataclass(frozen=True)
class ConditionSpectralQCThresholds:
    """Review thresholds for one exact, on-bin condition spectrum.

    The neighboring-bin definition is deliberately not configurable here.  It
    is part of :data:`CONDITION_SPECTRAL_QC_METHOD_VERSION`: +/-12 bins,
    excluding the target and its immediately adjacent bins, followed by one
    global minimum and one global maximum removal (22 candidates, 20 retained).
    """

    min_frequency_hz: float = 0.5
    min_peak_amplitude_uv: float = 250.0
    min_local_ratio: float = 25.0
    min_noise_z: float = 12.0
    widespread_channel_fraction: float = 0.75
    widespread_min_channels: int = 48
    harmonic_tolerance_hz: float = 0.08


@dataclass(frozen=True)
class ConditionSpectralPeak:
    """One grouped spectral observation in an on-bin condition spectrum."""

    fft_bin: int
    frequency_hz: float
    channels: tuple[str, ...]
    max_amplitude_uv: float
    max_local_ratio: float
    max_noise_z: float
    widespread: bool
    base_harmonic: int | None
    oddball_harmonic: int | None
    matched_notch_centers_hz: tuple[float, ...]

    def to_payload(self) -> dict[str, object]:
        return {
            "fft_bin": self.fft_bin,
            "frequency_hz": self.frequency_hz,
            "channels": list(self.channels),
            "max_amplitude_uv": self.max_amplitude_uv,
            "max_local_ratio": self.max_local_ratio,
            "max_noise_z": self.max_noise_z,
            "widespread": self.widespread,
            "base_harmonic": self.base_harmonic,
            "oddball_harmonic": self.oddball_harmonic,
            "matched_notch_centers_hz": list(self.matched_notch_centers_hz),
        }


@dataclass(frozen=True)
class ConditionSpectralQCResult:
    """Versioned, review-only QC result for one condition occurrence."""

    method_version: str
    evaluated: bool
    review_only: bool
    message: str
    n_channels: int
    n_samples: int
    sfreq: float
    fft_bin_spacing_hz: float
    requested_upper_frequency_hz: float
    evaluated_upper_frequency_hz: float | None
    amplitude_upper_frequency_hz: float | None
    requested_notch_centers_hz: tuple[float, ...]
    effective_notch_centers_hz: tuple[float, ...]
    skipped_notch_centers: tuple[SkippedNotchCenter, ...]
    expected_harmonic_peaks: tuple[ConditionSpectralPeak, ...]
    notch_handled_peaks: tuple[ConditionSpectralPeak, ...]
    collision_peaks: tuple[ConditionSpectralPeak, ...]
    unexpected_off_harmonic_flags: tuple[ConditionSpectralPeak, ...]
    thresholds: Mapping[str, float | int]

    @property
    def has_review_flags(self) -> bool:
        """Return whether an unexpected off-harmonic peak needs review."""

        return bool(self.unexpected_off_harmonic_flags)

    def to_payload(self) -> dict[str, object]:
        """Return a JSON-compatible result without any exclusion decision."""

        return {
            "method_version": self.method_version,
            "evaluated": self.evaluated,
            "review_only": self.review_only,
            "message": self.message,
            "n_channels": self.n_channels,
            "n_samples": self.n_samples,
            "sfreq": self.sfreq,
            "fft_bin_spacing_hz": self.fft_bin_spacing_hz,
            "requested_upper_frequency_hz": self.requested_upper_frequency_hz,
            "evaluated_upper_frequency_hz": self.evaluated_upper_frequency_hz,
            "amplitude_upper_frequency_hz": self.amplitude_upper_frequency_hz,
            "requested_notch_centers_hz": list(self.requested_notch_centers_hz),
            "effective_notch_centers_hz": list(self.effective_notch_centers_hz),
            "skipped_notch_centers": [
                {"center_hz": item.center_hz, "reason": item.reason}
                for item in self.skipped_notch_centers
            ],
            "expected_harmonic_peaks": [
                item.to_payload() for item in self.expected_harmonic_peaks
            ],
            "notch_handled_peaks": [
                item.to_payload() for item in self.notch_handled_peaks
            ],
            "collision_peaks": [item.to_payload() for item in self.collision_peaks],
            "unexpected_off_harmonic_flags": [
                item.to_payload() for item in self.unexpected_off_harmonic_flags
            ],
            "has_review_flags": self.has_review_flags,
            "thresholds": dict(self.thresholds),
        }


def _condition_threshold_payload(
    thresholds: ConditionSpectralQCThresholds,
) -> dict[str, float | int]:
    return {
        "min_frequency_hz": thresholds.min_frequency_hz,
        "min_peak_amplitude_uv": thresholds.min_peak_amplitude_uv,
        "min_local_ratio": thresholds.min_local_ratio,
        "min_noise_z": thresholds.min_noise_z,
        "widespread_channel_fraction": thresholds.widespread_channel_fraction,
        "widespread_min_channels": thresholds.widespread_min_channels,
        "harmonic_tolerance_hz": thresholds.harmonic_tolerance_hz,
        "noise_window_bins": CONDITION_SPECTRAL_QC_NOISE_WINDOW_BINS,
        "noise_candidate_bins": CONDITION_SPECTRAL_QC_NOISE_CANDIDATE_BINS,
        "noise_retained_bins": CONDITION_SPECTRAL_QC_NOISE_RETAINED_BINS,
        "notch_half_width_hz": FFT_MULTINOTCH_HALF_WIDTH_HZ,
    }


def _bool_setting(settings: Mapping[str, Any], key: str, default: bool) -> bool:
    value = settings.get(key, default)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return bool(value)


def _optional_float_setting(settings: Mapping[str, Any], key: str) -> float | None:
    value = settings.get(key)
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be finite when supplied.") from exc
    if not math.isfinite(number):
        raise ValueError(f"{key} must be finite when supplied.")
    return number


def _harmonic_number(
    frequency: float,
    *,
    fundamental: float,
    tolerance_hz: float,
) -> int | None:
    if not math.isfinite(fundamental) or fundamental <= 0.0:
        return None
    harmonic = int(round(frequency / fundamental))
    if harmonic <= 0:
        return None
    if abs(frequency - harmonic * fundamental) > tolerance_hz:
        return None
    return harmonic


def _condition_empty_result(
    *,
    message: str,
    n_channels: int,
    n_samples: int,
    sfreq: float,
    requested_upper_frequency_hz: float,
    fft_bin_spacing_hz: float,
    requested_notch_centers_hz: tuple[float, ...],
    effective_notch_centers_hz: tuple[float, ...],
    skipped_notch_centers: tuple[SkippedNotchCenter, ...],
    thresholds: ConditionSpectralQCThresholds,
) -> ConditionSpectralQCResult:
    return ConditionSpectralQCResult(
        method_version=CONDITION_SPECTRAL_QC_METHOD_VERSION,
        evaluated=False,
        review_only=True,
        message=message,
        n_channels=n_channels,
        n_samples=n_samples,
        sfreq=sfreq,
        fft_bin_spacing_hz=fft_bin_spacing_hz,
        requested_upper_frequency_hz=requested_upper_frequency_hz,
        evaluated_upper_frequency_hz=None,
        amplitude_upper_frequency_hz=None,
        requested_notch_centers_hz=requested_notch_centers_hz,
        effective_notch_centers_hz=effective_notch_centers_hz,
        skipped_notch_centers=skipped_notch_centers,
        expected_harmonic_peaks=(),
        notch_handled_peaks=(),
        collision_peaks=(),
        unexpected_off_harmonic_flags=(),
        thresholds=_condition_threshold_payload(thresholds),
    )


def _configured_notch_centers(
    *,
    settings: Mapping[str, Any],
    sfreq: float,
) -> tuple[
    tuple[float, ...],
    tuple[float, ...],
    tuple[SkippedNotchCenter, ...],
]:
    if not _bool_setting(settings, "line_noise_filter_enabled", True):
        return (), (), ()
    low_pass = _optional_float_setting(settings, "low_pass")
    return resolve_effective_centers(
        fundamental_hz=_float_setting(settings, "line_noise_frequency_hz", 60.0),
        sfreq=sfreq,
        low_pass=low_pass,
        h_trans_bandwidth=0.1,
    )


def _group_condition_peaks(
    candidates: Mapping[int, Sequence[tuple[str, float, float, float]]],
    *,
    frequencies: np.ndarray,
    n_channels: int,
    base_freq: float,
    oddball_freq: float,
    effective_notch_centers_hz: tuple[float, ...],
    thresholds: ConditionSpectralQCThresholds,
) -> tuple[
    tuple[ConditionSpectralPeak, ...],
    tuple[ConditionSpectralPeak, ...],
    tuple[ConditionSpectralPeak, ...],
    tuple[ConditionSpectralPeak, ...],
]:
    expected: list[ConditionSpectralPeak] = []
    notch_handled: list[ConditionSpectralPeak] = []
    collisions: list[ConditionSpectralPeak] = []
    unexpected: list[ConditionSpectralPeak] = []
    min_widespread = max(
        int(thresholds.widespread_min_channels),
        int(math.ceil(n_channels * thresholds.widespread_channel_fraction)),
    )
    for fft_bin in sorted(candidates):
        rows = candidates[fft_bin]
        frequency = float(frequencies[fft_bin])
        base_harmonic = _harmonic_number(
            frequency,
            fundamental=base_freq,
            tolerance_hz=thresholds.harmonic_tolerance_hz,
        )
        oddball_harmonic = _harmonic_number(
            frequency,
            fundamental=oddball_freq,
            tolerance_hz=thresholds.harmonic_tolerance_hz,
        )
        notch_centers = tuple(
            center
            for center in effective_notch_centers_hz
            if abs(frequency - center) < FFT_MULTINOTCH_HALF_WIDTH_HZ
        )
        peak = ConditionSpectralPeak(
            fft_bin=fft_bin,
            frequency_hz=frequency,
            channels=tuple(sorted(row[0] for row in rows)),
            max_amplitude_uv=max(float(row[1]) for row in rows),
            max_local_ratio=max(float(row[2]) for row in rows),
            max_noise_z=max(float(row[3]) for row in rows),
            widespread=len(rows) >= min_widespread,
            base_harmonic=base_harmonic,
            oddball_harmonic=oddball_harmonic,
            matched_notch_centers_hz=notch_centers,
        )
        is_expected = base_harmonic is not None or oddball_harmonic is not None
        if is_expected and notch_centers:
            collisions.append(peak)
        elif is_expected:
            expected.append(peak)
        elif notch_centers:
            notch_handled.append(peak)
        else:
            unexpected.append(peak)
    return tuple(expected), tuple(notch_handled), tuple(collisions), tuple(unexpected)


def _condition_fft_batch_size(
    *,
    n_samples: int,
    n_amplitude_bins: int,
) -> int:
    """Return a deterministic channel batch size under the working-set target."""

    time_domain_bytes = int(n_samples) * np.dtype(np.float64).itemsize
    complex_spectrum_bytes = (
        int(n_samples // 2 + 1) * np.dtype(np.complex128).itemsize
    )
    amplitude_bytes = int(n_amplitude_bins) * np.dtype(np.float64).itemsize
    peak_bytes_per_channel = max(
        2 * time_domain_bytes + complex_spectrum_bytes,
        complex_spectrum_bytes + amplitude_bytes,
    )
    target_limited = max(
        1,
        CONDITION_SPECTRAL_QC_FFT_BATCH_TARGET_BYTES
        // max(1, peak_bytes_per_channel),
    )
    return max(
        1,
        min(
            CONDITION_SPECTRAL_QC_MAX_CHANNELS_PER_FFT_BATCH,
            int(target_limited),
        ),
    )


def _check_condition_spectral_cancelled(
    should_cancel: Callable[[], bool] | None,
) -> None:
    if should_cancel is not None and should_cancel():
        raise ConditionSpectralQCCancelled("Condition spectral QC was cancelled.")


def _iter_condition_spectral_amplitude_batches(
    array: np.ndarray,
    *,
    window: np.ndarray,
    amplitude_last_bin: int,
    should_cancel: Callable[[], bool] | None,
) -> Iterator[tuple[int, np.ndarray]]:
    """Yield bit-equivalent Hann FFT amplitudes while bounding temporary memory."""

    n_channels, n_samples = array.shape
    batch_size = _condition_fft_batch_size(
        n_samples=n_samples,
        n_amplitude_bins=amplitude_last_bin + 1,
    )
    amplitude_scale = 2.0e6 / n_samples
    for batch_start in range(0, n_channels, batch_size):
        _check_condition_spectral_cancelled(should_cancel)
        batch_stop = min(n_channels, batch_start + batch_size)
        centered = (
            array[batch_start:batch_stop]
            - np.median(
                array[batch_start:batch_stop],
                axis=1,
                keepdims=True,
            )
        )
        spectra = np.fft.rfft(centered * window, axis=1)
        amplitudes_uv = (
            np.abs(spectra[:, : amplitude_last_bin + 1]) * amplitude_scale
        )
        del spectra, centered
        _check_condition_spectral_cancelled(should_cancel)
        yield batch_start, amplitudes_uv


def evaluate_condition_spectral_qc_v2(
    data: np.ndarray,
    *,
    sfreq: float,
    settings: Mapping[str, Any],
    effective_upper_frequency_hz: float,
    channel_names: Sequence[str] | None = None,
    condition_label: str = "condition",
    thresholds: ConditionSpectralQCThresholds | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> ConditionSpectralQCResult:
    """Evaluate one exact shared on-bin condition span without changing data.

    ``data`` must be in volts and already contain only the EEG channels and
    samples belonging to the shared condition crop selected by the FPVS crop
    contract.  Channels are transformed in deterministic, memory-bounded
    batches using the same row-wise float64 formula as an all-channel FFT.
    Strong peaks are categorized for review; the result intentionally contains
    no automatic participant- or channel-exclusion decision. ``should_cancel``
    is checked before and after each FFT batch.
    """

    thresholds = thresholds or ConditionSpectralQCThresholds()
    try:
        sample_rate = float(sfreq)
        requested_upper = float(effective_upper_frequency_hz)
    except (TypeError, ValueError) as exc:
        raise ValueError("Sampling rate and effective upper bound must be finite.") from exc
    if not math.isfinite(sample_rate) or sample_rate <= 0.0:
        raise ValueError("Sampling rate must be a positive finite number.")
    if not math.isfinite(requested_upper) or requested_upper <= 0.0:
        raise ValueError("Effective upper frequency must be a positive finite number.")

    array = np.asarray(data, dtype=np.float64)
    if array.ndim != 2:
        raise ValueError("Condition spectral QC data must have shape (channels, samples).")
    n_channels, n_samples = (int(value) for value in array.shape)
    if channel_names is None:
        names = tuple(f"EEG {index + 1}" for index in range(n_channels))
    else:
        names = tuple(str(name) for name in channel_names)
        if len(names) != n_channels:
            raise ValueError("channel_names must match the number of data rows.")
    if not np.isfinite(array).all():
        raise ValueError("Condition spectral QC requires finite float64 EEG samples.")

    requested_notches, effective_notches, skipped_notches = _configured_notch_centers(
        settings=settings,
        sfreq=sample_rate,
    )
    spacing = sample_rate / n_samples if n_samples > 0 else 0.0
    if n_channels == 0 or n_samples <= 2 * CONDITION_SPECTRAL_QC_NOISE_WINDOW_BINS:
        return _condition_empty_result(
            message=f"Condition spectral QC skipped for {condition_label}: not enough EEG samples.",
            n_channels=n_channels,
            n_samples=n_samples,
            sfreq=sample_rate,
            requested_upper_frequency_hz=requested_upper,
            fft_bin_spacing_hz=spacing,
            requested_notch_centers_hz=requested_notches,
            effective_notch_centers_hz=effective_notches,
            skipped_notch_centers=skipped_notches,
            thresholds=thresholds,
        )

    window = np.hanning(n_samples).astype(np.float64, copy=False)
    all_frequencies = np.fft.rfftfreq(n_samples, d=1.0 / sample_rate)

    physical_upper = min(requested_upper, float(all_frequencies[-1]))
    requested_last_bin = int(
        np.searchsorted(all_frequencies, physical_upper, side="right") - 1
    )
    amplitude_last_bin = min(
        int(all_frequencies.size - 1),
        requested_last_bin + CONDITION_SPECTRAL_QC_NOISE_WINDOW_BINS,
    )
    frequencies = all_frequencies[: amplitude_last_bin + 1]
    candidate_indices = np.flatnonzero(
        (frequencies >= thresholds.min_frequency_hz)
        & (frequencies <= physical_upper)
    )
    candidate_indices = candidate_indices[
        (candidate_indices >= CONDITION_SPECTRAL_QC_NOISE_WINDOW_BINS)
        & (
            candidate_indices + CONDITION_SPECTRAL_QC_NOISE_WINDOW_BINS
            <= amplitude_last_bin
        )
    ]
    if candidate_indices.size == 0:
        return _condition_empty_result(
            message=(
                f"Condition spectral QC skipped for {condition_label}: "
                "no bins have a complete +/-12-bin noise neighborhood."
            ),
            n_channels=n_channels,
            n_samples=n_samples,
            sfreq=sample_rate,
            requested_upper_frequency_hz=requested_upper,
            fft_bin_spacing_hz=spacing,
            requested_notch_centers_hz=requested_notches,
            effective_notch_centers_hz=effective_notches,
            skipped_notch_centers=skipped_notches,
            thresholds=thresholds,
        )

    grouped: dict[int, list[tuple[str, float, float, float]]] = {}
    for batch_start, batch_amplitudes_uv in _iter_condition_spectral_amplitude_batches(
        array,
        window=window,
        amplitude_last_bin=amplitude_last_bin,
        should_cancel=should_cancel,
    ):
        for batch_row, row in enumerate(batch_amplitudes_uv):
            channel_name = names[batch_start + batch_row]
            indices = candidate_indices[
                (row[candidate_indices] >= thresholds.min_peak_amplitude_uv)
                & (row[candidate_indices] >= row[candidate_indices - 1])
                & (row[candidate_indices] >= row[candidate_indices + 1])
            ]
            for fft_bin_value in indices:
                fft_bin = int(fft_bin_value)
                noise_mean, noise_std = compute_noise_stats_for_bin(
                    row,
                    fft_bin,
                    window_size=CONDITION_SPECTRAL_QC_NOISE_WINDOW_BINS,
                    min_bins=CONDITION_SPECTRAL_QC_NOISE_CANDIDATE_BINS,
                )
                amplitude = float(row[fft_bin])
                if noise_mean <= 0.0 or not math.isfinite(noise_mean):
                    continue
                ratio = amplitude / noise_mean
                if noise_std > 0.0 and math.isfinite(noise_std):
                    noise_z = (amplitude - noise_mean) / noise_std
                elif amplitude > noise_mean:
                    noise_z = float(np.finfo(np.float64).max)
                else:
                    noise_z = 0.0
                if ratio < thresholds.min_local_ratio or noise_z < thresholds.min_noise_z:
                    continue
                grouped.setdefault(fft_bin, []).append(
                    (channel_name, amplitude, ratio, noise_z)
                )

    expected, notch_handled, collisions, unexpected = _group_condition_peaks(
        grouped,
        frequencies=frequencies,
        n_channels=n_channels,
        base_freq=_float_setting(settings, "base_freq", 6.0),
        oddball_freq=_float_setting(
            settings,
            "oddball_freq",
            _float_setting(
                settings.get("analysis", {})
                if isinstance(settings.get("analysis"), Mapping)
                else {},
                "oddball_freq",
                1.2,
            ),
        ),
        effective_notch_centers_hz=effective_notches,
        thresholds=thresholds,
    )
    evaluated_upper = float(frequencies[int(candidate_indices[-1])])
    amplitude_upper = float(frequencies[-1])
    if unexpected:
        message = (
            f"Condition spectral QC found {len(unexpected)} unexpected off-harmonic "
            f"peak(s) for review in {condition_label}."
        )
    else:
        message = (
            f"Condition spectral QC passed for {condition_label}: no unexpected "
            "off-harmonic peaks require review."
        )
    return ConditionSpectralQCResult(
        method_version=CONDITION_SPECTRAL_QC_METHOD_VERSION,
        evaluated=True,
        review_only=True,
        message=message,
        n_channels=n_channels,
        n_samples=n_samples,
        sfreq=sample_rate,
        fft_bin_spacing_hz=spacing,
        requested_upper_frequency_hz=requested_upper,
        evaluated_upper_frequency_hz=evaluated_upper,
        amplitude_upper_frequency_hz=amplitude_upper,
        requested_notch_centers_hz=requested_notches,
        effective_notch_centers_hz=effective_notches,
        skipped_notch_centers=skipped_notches,
        expected_harmonic_peaks=expected,
        notch_handled_peaks=notch_handled,
        collision_peaks=collisions,
        unexpected_off_harmonic_flags=unexpected,
        thresholds=_condition_threshold_payload(thresholds),
    )


__all__ = [
    "CONDITION_SPECTRAL_QC_FFT_BATCH_TARGET_BYTES",
    "CONDITION_SPECTRAL_QC_MAX_CHANNELS_PER_FFT_BATCH",
    "CONDITION_SPECTRAL_QC_METHOD_VERSION",
    "CONDITION_SPECTRAL_QC_NOISE_CANDIDATE_BINS",
    "CONDITION_SPECTRAL_QC_NOISE_RETAINED_BINS",
    "CONDITION_SPECTRAL_QC_NOISE_WINDOW_BINS",
    "ConditionSpectralPeak",
    "ConditionSpectralQCCancelled",
    "ConditionSpectralQCResult",
    "ConditionSpectralQCThresholds",
    "RawSpectralQCResult",
    "RawSpectralQCThresholds",
    "evaluate_condition_spectral_qc_v2",
    "evaluate_raw_spectral_qc",
]
