# noise_utils.py

"""
This file is used to calculate SNR using the +/- 10 bins method used in several publications:

1: Dzhelyova, M., & Rossion, B. (2014a). The effect of parametric stimulus variation on individual face discrimination
   indexed by fast periodic visual stimulation. Journal of Vision, 14(12), 1–18. https://doi.org/10.1167/14.12.22

2: Georges, C., Retter, T. L., & Rossion, B. (2020). Face-selective responses in the human brain: A periodic
   stimulation approach. NeuroImage, 214, 116703. https://doi.org/10.1016/j.neuroimage.2020.116703

3: Liu-Shuang, J., Norcia, A. M., & Rossion, B. (2014). An objective index of individual face discrimination in the
   right occipito-temporal cortex by means of fast periodic oddball stimulation. Neuropsychologia, 52, 57–72.
   https://doi.org/10.1016/j.neuropsychologia.2013.10.022

4: Poncet, F., Rossion, B., & Jacques, C. (2019). Evidence for the existence of a face-selective neural response in
   the human brain with fast periodic visual stimulation. NeuroImage, 189, 150–162.
   https://doi.org/10.1016/j.neuroimage.2019.01.021

"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence, Tuple

import numpy as np

__all__ = [
    "QC14_METRIC_METHOD_VERSION",
    "QC14NoiseMetricResult",
    "compute_qc14_standard_metrics",
    "compute_noise_stats_for_bin",
    "compute_noise_stats_for_bin_channels",
]


_BATCH_SAFE_ABS_MIN = 1e-100
_BATCH_SAFE_ABS_MAX = 1e100
QC14_METRIC_METHOD_VERSION = "qc14_fixed_bin_metrics_v1"
QC14_EFFECTIVELY_ZERO_TOLERANCE = 1e-12
_QC14_OFFSETS = tuple([*range(-10, -1), *range(2, 11)])


@dataclass(frozen=True, slots=True)
class QC14NoiseMetricResult:
    """Per-channel standard metrics with explicit QC-14 availability."""

    method_version: str
    target_bin_index: int
    candidate_bin_indices: tuple[int, ...]
    retained_bin_indices: tuple[int, ...]
    target_amplitude: float | None
    noise_mean: float | None
    noise_population_sd: float | None
    bca: float | None
    snr: float | None
    local_z: float | None
    target_amplitude_status: str
    bca_status: str
    snr_status: str
    local_z_status: str
    reason_codes: tuple[str, ...]

    def to_payload(self) -> dict[str, object]:
        return {
            "method_version": self.method_version,
            "target_bin_index": self.target_bin_index,
            "candidate_bin_indices": list(self.candidate_bin_indices),
            "retained_bin_indices": list(self.retained_bin_indices),
            "target_amplitude": self.target_amplitude,
            "noise_mean": self.noise_mean,
            "noise_population_sd": self.noise_population_sd,
            "bca": self.bca,
            "snr": self.snr,
            "local_z": self.local_z,
            "target_amplitude_status": self.target_amplitude_status,
            "bca_status": self.bca_status,
            "snr_status": self.snr_status,
            "local_z_status": self.local_z_status,
            "reason_codes": list(self.reason_codes),
        }


def compute_qc14_standard_metrics(
    amplitudes: np.ndarray,
    *,
    target_idx: int,
    candidate_bin_indices: Sequence[int],
    static_metrics_available: bool = True,
    static_reason_codes: Sequence[str] = (),
    target_amplitude_status: str = "available",
    zero_tolerance: float = QC14_EFFECTIVELY_ZERO_TOLERANCE,
) -> QC14NoiseMetricResult:
    """Calculate BCA/SNR/local z only from complete valid QC-14 support.

    The candidate list must be the exact symmetric ``-10..-2,+2..+10`` set.
    One finite minimum and one finite maximum are removed, including when tied,
    leaving exactly 16 values in their original frequency order.
    """

    values = np.asarray(amplitudes)
    if values.ndim != 1:
        raise ValueError("QC-14 metrics require one one-dimensional amplitude spectrum.")
    target = int(target_idx)
    candidates = tuple(int(index) for index in candidate_bin_indices)
    expected = tuple(target + offset for offset in _QC14_OFFSETS)
    reasons = list(dict.fromkeys(str(value) for value in static_reason_codes if str(value)))

    target_value: float | None = None
    if 0 <= target < values.size and np.isfinite(values[target]):
        target_value = float(values[target])
    else:
        reasons.append("nonfinite_or_missing_target_bin")
        target_amplitude_status = "unavailable"

    if candidates != expected or any(index < 0 or index >= values.size for index in candidates):
        reasons.append("incomplete_or_asymmetric_noise_support")
        return _unavailable_qc14_result(
            target_idx=target,
            candidates=candidates,
            target_value=target_value,
            target_amplitude_status=target_amplitude_status,
            reasons=reasons,
        )
    if not static_metrics_available:
        return _unavailable_qc14_result(
            target_idx=target,
            candidates=candidates,
            target_value=target_value,
            target_amplitude_status=target_amplitude_status,
            reasons=reasons or ["static_spectral_eligibility_unavailable"],
        )
    if target_value is None:
        return _unavailable_qc14_result(
            target_idx=target,
            candidates=candidates,
            target_value=None,
            target_amplitude_status="unavailable",
            reasons=reasons,
        )

    noise_values = values[np.asarray(candidates, dtype=np.intp)].astype(float)
    if not np.all(np.isfinite(noise_values)):
        reasons.append("nonfinite_noise_support")
        return _unavailable_qc14_result(
            target_idx=target,
            candidates=candidates,
            target_value=target_value,
            target_amplitude_status=target_amplitude_status,
            reasons=reasons,
        )

    # Stable sorting identifies distinct occurrences when the extrema tie.
    sorted_positions = np.argsort(noise_values, kind="stable")
    removed_positions = {int(sorted_positions[0]), int(sorted_positions[-1])}
    retained_positions = tuple(
        position
        for position in range(len(candidates))
        if position not in removed_positions
    )
    retained_indices = tuple(candidates[position] for position in retained_positions)
    retained_values = noise_values[np.asarray(retained_positions, dtype=np.intp)]
    if retained_values.size != 16:
        raise RuntimeError("QC-14 trimming must retain exactly 16 noise bins.")

    noise_mean = float(retained_values.mean())
    noise_sd = float(retained_values.std(ddof=0))
    bca = float(target_value - noise_mean)
    snr: float | None = None
    local_z: float | None = None
    snr_status = "available"
    local_z_status = "available"
    if not np.isfinite(noise_mean):
        reasons.append("nonfinite_noise_mean")
        return _unavailable_qc14_result(
            target_idx=target,
            candidates=candidates,
            target_value=target_value,
            target_amplitude_status=target_amplitude_status,
            reasons=reasons,
            retained_indices=retained_indices,
        )
    if abs(noise_mean) <= float(zero_tolerance):
        reasons.append("effectively_zero_noise_mean")
        snr_status = "unavailable"
    else:
        snr = float(target_value / noise_mean)
    if not np.isfinite(noise_sd):
        reasons.append("nonfinite_noise_population_sd")
        local_z_status = "unavailable"
    elif abs(noise_sd) <= float(zero_tolerance):
        reasons.append("effectively_zero_noise_population_sd")
        local_z_status = "unavailable"
    else:
        local_z = float((target_value - noise_mean) / noise_sd)

    return QC14NoiseMetricResult(
        method_version=QC14_METRIC_METHOD_VERSION,
        target_bin_index=target,
        candidate_bin_indices=candidates,
        retained_bin_indices=retained_indices,
        target_amplitude=target_value,
        noise_mean=noise_mean,
        noise_population_sd=noise_sd,
        bca=bca,
        snr=snr,
        local_z=local_z,
        target_amplitude_status=target_amplitude_status,
        bca_status="available",
        snr_status=snr_status,
        local_z_status=local_z_status,
        reason_codes=tuple(dict.fromkeys(reasons)),
    )


def _unavailable_qc14_result(
    *,
    target_idx: int,
    candidates: tuple[int, ...],
    target_value: float | None,
    target_amplitude_status: str,
    reasons: Sequence[str],
    retained_indices: tuple[int, ...] = (),
) -> QC14NoiseMetricResult:
    return QC14NoiseMetricResult(
        method_version=QC14_METRIC_METHOD_VERSION,
        target_bin_index=target_idx,
        candidate_bin_indices=candidates,
        retained_bin_indices=retained_indices,
        target_amplitude=target_value,
        noise_mean=None,
        noise_population_sd=None,
        bca=None,
        snr=None,
        local_z=None,
        target_amplitude_status=target_amplitude_status,
        bca_status="unavailable",
        snr_status="unavailable",
        local_z_status="unavailable",
        reason_codes=tuple(dict.fromkeys(reasons)),
    )


def compute_noise_stats_for_bin(
    amplitudes: np.ndarray,
    target_idx: int,
    window_size: int = 10,
    min_bins: int = 4,
) -> Tuple[float, float]:
    """
    Compute noise mean and std around a target FFT bin using neighboring bins.

    Logic:
    - Take a ±window_size-bin window around target_idx.
    - Exclude the target bin and its immediate neighbors (target_idx-1, target_idx+1).
    - If there are fewer than `min_bins` candidate bins -> return (0.0, 0.0).
    - From the remaining bins, remove one max and one min value (two most extreme).
    - Return (mean, std) of the remaining noise amplitudes.

    Parameters
    ----------
    amplitudes
        1-D array of FFT amplitudes for a single channel.
    target_idx
        Index of the FFT bin corresponding to the frequency of interest.
    window_size
        Number of bins on each side of target_idx to consider (±window_size).
    min_bins
        Minimum number of candidate noise bins (before extreme-value removal)
        required to compute noise statistics.

    Returns
    -------
    (noise_mean, noise_std)
        Mean and standard deviation of the noise amplitudes. (0.0, 0.0) if
        there are too few bins.
    """
    num_bins = amplitudes.shape[0]
    low = max(0, target_idx - window_size)
    high = min(num_bins - 1, target_idx + window_size)

    # Exclude target and its immediate neighbors
    exclude = {target_idx - 1, target_idx, target_idx + 1}
    indices = [
        i
        for i in range(low, high + 1)
        if 0 <= i < num_bins and i not in exclude
    ]

    if len(indices) < min_bins:
        return 0.0, 0.0

    noise_vals = amplitudes[indices].astype(float)

    # Remove one max and one min (two most extreme values) if possible
    if noise_vals.size > 2:
        max_idx = int(noise_vals.argmax())
        min_idx = int(noise_vals.argmin())
        mask = np.ones(noise_vals.shape[0], dtype=bool)
        mask[max_idx] = False
        mask[min_idx] = False
        noise_vals = noise_vals[mask]

    if noise_vals.size == 0:
        return 0.0, 0.0

    noise_mean = float(noise_vals.mean())
    noise_std = float(noise_vals.std(ddof=0))
    return noise_mean, noise_std


def compute_noise_stats_for_bin_channels(
    amplitudes: np.ndarray,
    target_idx: int,
    window_size: int = 10,
    min_bins: int = 4,
) -> tuple[np.ndarray, np.ndarray]:
    """Compute one target-bin noise estimate for every channel, byte-exact.

    Normal post-processing FFT amplitudes are native float64, finite,
    C-contiguous, and comfortably within ordinary EEG magnitude ranges.  That
    case can reduce the same retained values along adjacent rows in one NumPy
    call.  Inputs with zeros, non-finite/extreme values, tied extrema, another
    dtype, or another layout retain the scalar helper above so its values and
    warning behavior remain unchanged.
    """

    amplitude_matrix = np.asarray(amplitudes)
    if amplitude_matrix.ndim != 2:
        raise ValueError(
            "Channel noise statistics require a 2-D channels x FFT-bins array."
        )

    num_channels, num_bins = amplitude_matrix.shape
    low = max(0, target_idx - window_size)
    high = min(num_bins - 1, target_idx + window_size)
    exclude = {target_idx - 1, target_idx, target_idx + 1}
    indices = [
        index
        for index in range(low, high + 1)
        if 0 <= index < num_bins and index not in exclude
    ]

    if len(indices) < min_bins:
        return np.zeros(num_channels, dtype=float), np.zeros(
            num_channels,
            dtype=float,
        )

    if (
        amplitude_matrix.dtype == np.dtype(np.float64)
        and amplitude_matrix.flags.c_contiguous
    ):
        noise_values = np.ascontiguousarray(amplitude_matrix[:, indices])
        absolute_values = np.abs(noise_values)
        if (
            noise_values.shape[1] > 2
            and np.all(np.isfinite(absolute_values))
            and np.all(absolute_values >= _BATCH_SAFE_ABS_MIN)
            and np.all(absolute_values <= _BATCH_SAFE_ABS_MAX)
        ):
            max_indices = noise_values.argmax(axis=1)
            min_indices = noise_values.argmin(axis=1)
            if np.all(max_indices != min_indices):
                keep = np.ones(noise_values.shape, dtype=bool)
                channel_indices = np.arange(num_channels)
                keep[channel_indices, max_indices] = False
                keep[channel_indices, min_indices] = False
                retained = np.ascontiguousarray(
                    noise_values[keep].reshape(num_channels, -1)
                )
                return retained.mean(axis=1), retained.std(axis=1, ddof=0)

    noise_means = np.empty(num_channels, dtype=float)
    noise_stds = np.empty(num_channels, dtype=float)
    for channel_index in range(num_channels):
        noise_means[channel_index], noise_stds[channel_index] = (
            compute_noise_stats_for_bin(
                amplitude_matrix[channel_index],
                target_idx,
                window_size=window_size,
                min_bins=min_bins,
            )
        )
    return noise_means, noise_stds
