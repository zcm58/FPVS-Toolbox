"""Lightweight raw-spectrum QC used by preprocessing preflight review."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping, Sequence

import numpy as np

from Main_App.processing.raw_channel_qc import SCALP_CHANNELS


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


__all__ = [
    "RawSpectralQCResult",
    "RawSpectralQCThresholds",
    "evaluate_raw_spectral_qc",
]
