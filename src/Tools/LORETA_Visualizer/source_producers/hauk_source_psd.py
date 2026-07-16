"""Hauk-informed time-domain source-PSD calculations for FPVS data.

This module owns numerical source-PSD preparation only.  It accepts an already
averaged, source-ready MNE Raw object plus an inverse operator, delegates the
PSD calculation to MNE (or an injected compatible callable), and then performs
the FPVS harmonic alignment and source-space z-scoring steps.  It does not
discover project files, construct anatomical models, render, or write outputs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

import numpy as np

HAUK_SOURCE_PSD_METHOD_ID = "l2_mne_hauk_source_psd_v1"
HAUK_SOURCE_PSD_METHOD_VERSION = "hauk_source_psd_v1"
HAUK_2021_REFERENCE_DOI = "10.1016/j.neuroimage.2021.118460"
HAUK_REFERENCE_CODE_URL = "https://github.com/olafhauk/FPVS_sweep"
DEFAULT_HAUK_SOURCE_PSD_LAMBDA2 = 1.0 / 9.0
DEFAULT_HAUK_SOURCE_PSD_NOISE_OFFSETS = tuple(range(-10, -1)) + tuple(range(2, 11))
DEFAULT_HAUK_SOURCE_PSD_ALIGNED_OFFSETS = (0, *DEFAULT_HAUK_SOURCE_PSD_NOISE_OFFSETS)
DEFAULT_BIN_POSITION_TOLERANCE = 1e-7
DEFAULT_NEGATIVE_POWER_RELATIVE_TOLERANCE = 1e-12
DEFAULT_ZERO_NOISE_SD_RELATIVE_TOLERANCE = 1e-12
SUPPORTED_MNE_INVERSE_METHODS = ("MNE", "dSPM", "sLORETA", "eLORETA")

ComputeSourcePsdCallable = Callable[..., Any]


@dataclass(frozen=True)
class HaukSourcePsdConfig:
    """Versioned numerical settings for the Hauk-informed source-PSD path."""

    selected_harmonics_hz: tuple[float, ...]
    lambda2: float = DEFAULT_HAUK_SOURCE_PSD_LAMBDA2
    bin_position_tolerance: float = DEFAULT_BIN_POSITION_TOLERANCE
    negative_power_relative_tolerance: float = DEFAULT_NEGATIVE_POWER_RELATIVE_TOLERANCE
    zero_noise_sd_relative_tolerance: float = DEFAULT_ZERO_NOISE_SD_RELATIVE_TOLERANCE
    inverse_method: str = "MNE"
    method_params: Mapping[str, Any] = field(default_factory=dict)
    prepared: bool = False
    method_id: str = HAUK_SOURCE_PSD_METHOD_ID
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        harmonics = _validated_harmonics(self.selected_harmonics_hz)
        lambda2 = float(self.lambda2)
        if not np.isfinite(lambda2) or lambda2 <= 0.0:
            raise ValueError("Hauk source-PSD lambda2 must be positive and finite.")
        bin_tolerance = _positive_finite(
            self.bin_position_tolerance,
            label="bin_position_tolerance",
        )
        negative_tolerance = _nonnegative_finite(
            self.negative_power_relative_tolerance,
            label="negative_power_relative_tolerance",
        )
        zero_sd_tolerance = _nonnegative_finite(
            self.zero_noise_sd_relative_tolerance,
            label="zero_noise_sd_relative_tolerance",
        )
        inverse_method = _validated_inverse_method(self.inverse_method)
        if not isinstance(self.method_params, Mapping):
            raise TypeError("Hauk source-PSD method_params must be a mapping.")
        method_id = str(self.method_id).strip()
        if not method_id:
            raise ValueError("Hauk source-PSD method_id cannot be empty.")
        object.__setattr__(self, "selected_harmonics_hz", harmonics)
        object.__setattr__(self, "lambda2", lambda2)
        object.__setattr__(self, "bin_position_tolerance", bin_tolerance)
        object.__setattr__(self, "negative_power_relative_tolerance", negative_tolerance)
        object.__setattr__(self, "zero_noise_sd_relative_tolerance", zero_sd_tolerance)
        object.__setattr__(self, "inverse_method", inverse_method)
        object.__setattr__(self, "method_params", dict(self.method_params))
        object.__setattr__(self, "prepared", bool(self.prepared))
        object.__setattr__(self, "method_id", method_id)
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_metadata(self) -> dict[str, Any]:
        """Return deterministic, JSON-safe method metadata for provenance/cache keys."""
        return {
            "method_id": self.method_id,
            "method_version": HAUK_SOURCE_PSD_METHOD_VERSION,
            "reference_publication_doi": HAUK_2021_REFERENCE_DOI,
            "reference_code_repository": HAUK_REFERENCE_CODE_URL,
            "reference_method_relation": (
                "Hauk-informed EEG/fsaverage FPVS Toolbox adaptation; not an exact "
                "combined EEG/MEG or individual-MRI reproduction"
            ),
            "selected_harmonics_hz": [float(value) for value in self.selected_harmonics_hz],
            "inverse_method": self.inverse_method,
            "method_params": dict(self.method_params),
            "prepared": bool(self.prepared),
            "lambda2": float(self.lambda2),
            "source_psd_n_fft": "averaged_raw_n_times",
            "source_psd_overlap": 0.0,
            "source_psd_bandwidth": "hann",
            "source_psd_low_bias": True,
            "source_psd_nave": 1,
            "source_psd_pca": True,
            "source_psd_pick_ori": None,
            "source_psd_decibels": False,
            "power_to_amplitude": "sqrt_after_nonnegative_validation",
            "harmonic_aggregation": "sum_corresponding_source_amplitude_offsets_before_zscore",
            "aligned_offsets": [int(value) for value in DEFAULT_HAUK_SOURCE_PSD_ALIGNED_OFFSETS],
            "noise_offsets": [int(value) for value in DEFAULT_HAUK_SOURCE_PSD_NOISE_OFFSETS],
            "noise_bin_count": len(DEFAULT_HAUK_SOURCE_PSD_NOISE_OFFSETS),
            "excluded_target_adjacent_offsets": [-1, 0, 1],
            "noise_extreme_rule": "drop_one_global_min_and_one_global_max_per_source",
            "noise_standard_deviation_ddof": 0,
            "nearest_fft_bin_substitution": "forbidden",
            "bin_position_tolerance": float(self.bin_position_tolerance),
            "negative_power_relative_tolerance": float(self.negative_power_relative_tolerance),
            "zero_noise_sd_relative_tolerance": float(self.zero_noise_sd_relative_tolerance),
            "custom_metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class HaukSourcePsdFrequencyPlan:
    """Exact FFT-bin plan shared by the MNE call and harmonic aggregation."""

    sfreq: float
    n_times: int
    frequency_resolution_hz: float
    selected_harmonics_hz: tuple[float, ...]
    harmonic_bin_indices: tuple[int, ...]
    required_bin_indices: tuple[int, ...]
    fmin_hz: float
    fmax_hz: float
    aligned_offsets: tuple[int, ...] = DEFAULT_HAUK_SOURCE_PSD_ALIGNED_OFFSETS

    def to_metadata(self) -> dict[str, Any]:
        """Return deterministic, JSON-safe frequency metadata for provenance/cache keys."""
        return {
            "sfreq": float(self.sfreq),
            "n_times": int(self.n_times),
            "frequency_resolution_hz": float(self.frequency_resolution_hz),
            "selected_harmonics_hz": [float(value) for value in self.selected_harmonics_hz],
            "harmonic_bin_indices": [int(value) for value in self.harmonic_bin_indices],
            "required_bin_indices": [int(value) for value in self.required_bin_indices],
            "fmin_hz": float(self.fmin_hz),
            "fmax_hz": float(self.fmax_hz),
            "aligned_offsets": [int(value) for value in self.aligned_offsets],
        }


@dataclass(frozen=True)
class HaukSourcePsdZScoreResult:
    """Per-source z-scores and their summed-spectrum diagnostics."""

    values: np.ndarray
    target_source_amplitudes: np.ndarray
    noise_mean_values: np.ndarray
    noise_std_values: np.ndarray
    noise_values_after_extreme_drop: np.ndarray
    zero_noise_sd_source_count: int


@dataclass(frozen=True)
class HaukSourcePsdResult:
    """Complete compact result for one averaged participant/condition Raw."""

    config: HaukSourcePsdConfig
    frequency_plan: HaukSourcePsdFrequencyPlan
    summed_source_amplitudes: np.ndarray
    zscore: HaukSourcePsdZScoreResult
    source_count: int
    source_psd_frequency_count: int

    @property
    def values(self) -> np.ndarray:
        """Return the participant source-space z-score vector."""
        return self.zscore.values

    def cache_fingerprint_payload(self) -> dict[str, Any]:
        """Return numerical inputs that project orchestration can hash for caching."""
        return {
            "method": self.config.to_metadata(),
            "frequency_plan": self.frequency_plan.to_metadata(),
        }


def build_hauk_source_psd_frequency_plan(
    *,
    sfreq: float,
    n_times: int,
    selected_harmonics_hz: Sequence[float],
    bin_position_tolerance: float = DEFAULT_BIN_POSITION_TOLERANCE,
) -> HaukSourcePsdFrequencyPlan:
    """Build an exact-bin plan; nominal harmonics are never moved to nearby bins."""
    sample_rate = _positive_finite(sfreq, label="sfreq")
    sample_count = int(n_times)
    if sample_count != n_times or sample_count < 2:
        raise ValueError("Hauk source-PSD n_times must be an integer of at least 2.")
    tolerance = _positive_finite(bin_position_tolerance, label="bin_position_tolerance")
    harmonics = _validated_harmonics(selected_harmonics_hz)
    resolution = sample_rate / float(sample_count)
    max_fft_bin = sample_count // 2

    harmonic_bins: list[int] = []
    for harmonic in harmonics:
        position = harmonic * float(sample_count) / sample_rate
        bin_index = int(np.rint(position))
        if abs(position - bin_index) > tolerance:
            raise ValueError(
                f"Selected harmonic {harmonic:g} Hz is not on an exact FFT bin "
                f"(position={position:.12g}, df={resolution:.12g} Hz); nearest-bin substitution is forbidden."
            )
        if bin_index < 0 or bin_index > max_fft_bin:
            raise ValueError(f"Selected harmonic {harmonic:g} Hz is outside the real FFT frequency range.")
        harmonic_bins.append(bin_index)
    if len(set(harmonic_bins)) != len(harmonic_bins):
        raise ValueError("Selected harmonics must resolve to distinct exact FFT bins.")

    required_bins = sorted(
        {
            harmonic_bin + offset
            for harmonic_bin in harmonic_bins
            for offset in DEFAULT_HAUK_SOURCE_PSD_ALIGNED_OFFSETS
        }
    )
    if required_bins[0] < 0 or required_bins[-1] > max_fft_bin:
        raise ValueError(
            "Selected harmonics do not have the complete required source-PSD noise window "
            f"within 0..{max_fft_bin} FFT bins."
        )
    return HaukSourcePsdFrequencyPlan(
        sfreq=sample_rate,
        n_times=sample_count,
        frequency_resolution_hz=resolution,
        selected_harmonics_hz=harmonics,
        harmonic_bin_indices=tuple(harmonic_bins),
        required_bin_indices=tuple(required_bins),
        fmin_hz=float(required_bins[0] * resolution),
        fmax_hz=float(required_bins[-1] * resolution),
    )


def source_amplitudes_from_psd_power(
    source_psd_power: Sequence[Sequence[float]] | np.ndarray,
    *,
    negative_relative_tolerance: float = DEFAULT_NEGATIVE_POWER_RELATIVE_TOLERANCE,
) -> np.ndarray:
    """Convert source PSD power to amplitude while rejecting substantive negatives."""
    power = np.asarray(source_psd_power, dtype=float)
    if power.ndim != 2 or power.shape[0] == 0 or power.shape[1] == 0:
        raise ValueError("Source PSD power must have shape n_sources x n_frequencies.")
    if not np.all(np.isfinite(power)):
        raise ValueError("Source PSD power contains non-finite values.")
    relative_tolerance = _nonnegative_finite(
        negative_relative_tolerance,
        label="negative_relative_tolerance",
    )
    scale = max(float(np.max(np.abs(power))), float(np.finfo(float).tiny))
    negative_tolerance = scale * relative_tolerance
    if np.any(power < -negative_tolerance):
        minimum = float(np.min(power))
        raise ValueError(
            "Source PSD power contains negative values larger than numerical tolerance "
            f"(minimum={minimum:.12g}, tolerance={negative_tolerance:.12g})."
        )
    nonnegative_power = np.maximum(power, 0.0)
    amplitudes = np.sqrt(nonnegative_power)
    if not np.all(np.isfinite(amplitudes)):
        raise ValueError("Source PSD power-to-amplitude conversion produced non-finite values.")
    return amplitudes.astype(float)


def sum_harmonic_source_amplitudes(
    *,
    source_amplitudes: Sequence[Sequence[float]] | np.ndarray,
    source_psd_frequencies_hz: Sequence[float] | np.ndarray,
    frequency_plan: HaukSourcePsdFrequencyPlan,
    bin_position_tolerance: float = DEFAULT_BIN_POSITION_TOLERANCE,
) -> np.ndarray:
    """Sum matching target/noise offsets across harmonics in source space."""
    amplitudes = np.asarray(source_amplitudes, dtype=float)
    if amplitudes.ndim != 2 or amplitudes.shape[0] == 0 or amplitudes.shape[1] == 0:
        raise ValueError("Source amplitudes must have shape n_sources x n_frequencies.")
    if not np.all(np.isfinite(amplitudes)) or np.any(amplitudes < 0.0):
        raise ValueError("Source amplitudes must be finite and nonnegative.")
    frequencies = np.asarray(source_psd_frequencies_hz, dtype=float).reshape(-1)
    if len(frequencies) != amplitudes.shape[1]:
        raise ValueError("Source PSD frequency count does not match the source-amplitude columns.")
    columns_by_bin = _frequency_columns_by_exact_fft_bin(
        frequencies,
        frequency_plan=frequency_plan,
        bin_position_tolerance=bin_position_tolerance,
    )

    summed = np.zeros((amplitudes.shape[0], len(frequency_plan.aligned_offsets)), dtype=float)
    for offset_index, offset in enumerate(frequency_plan.aligned_offsets):
        for harmonic_bin in frequency_plan.harmonic_bin_indices:
            summed[:, offset_index] += amplitudes[:, columns_by_bin[harmonic_bin + offset]]
    if not np.all(np.isfinite(summed)):
        raise ValueError("Summed harmonic source amplitudes contain non-finite values.")
    return summed


def compute_hauk_source_zscores(
    summed_source_amplitudes: Sequence[Sequence[float]] | np.ndarray,
    *,
    aligned_offsets: Sequence[int] = DEFAULT_HAUK_SOURCE_PSD_ALIGNED_OFFSETS,
    zero_sd_relative_tolerance: float = DEFAULT_ZERO_NOISE_SD_RELATIVE_TOLERANCE,
) -> HaukSourcePsdZScoreResult:
    """Z-score summed target amplitudes using the intentional Toolbox noise rule."""
    offsets = tuple(int(value) for value in aligned_offsets)
    if offsets != DEFAULT_HAUK_SOURCE_PSD_ALIGNED_OFFSETS:
        raise ValueError(
            "Hauk source-PSD z-scores require offsets exactly 0, -10..-2, and +2..+10."
        )
    summed = np.asarray(summed_source_amplitudes, dtype=float)
    if summed.ndim != 2 or summed.shape[0] == 0 or summed.shape[1] != len(offsets):
        raise ValueError(
            "Summed source amplitudes must have shape n_sources x 19 "
            "for target plus eighteen intentional Toolbox noise offsets."
        )
    if not np.all(np.isfinite(summed)):
        raise ValueError("Summed source amplitudes contain non-finite values.")

    target = summed[:, 0].astype(float)
    noise = summed[:, 1:]
    # Sorting across all eighteen finite noise values drops exactly one global
    # minimum and one global maximum per source, including in the presence of ties.
    retained_noise = np.sort(noise, axis=1, kind="stable")[:, 1:-1]
    noise_mean = np.mean(retained_noise, axis=1)
    noise_std = np.std(retained_noise, axis=1, ddof=0)
    relative_tolerance = _nonnegative_finite(
        zero_sd_relative_tolerance,
        label="zero_sd_relative_tolerance",
    )
    scale = np.maximum(np.max(np.abs(retained_noise), axis=1), np.finfo(float).tiny)
    valid = np.isfinite(noise_std) & (noise_std > scale * relative_tolerance)
    if not np.any(valid):
        raise ValueError("No source points have a finite, non-zero neighboring-bin noise SD.")
    z_values = np.zeros_like(target, dtype=float)
    z_values[valid] = (target[valid] - noise_mean[valid]) / noise_std[valid]
    if not np.all(np.isfinite(z_values)):
        raise ValueError("Hauk source-PSD z-scoring produced non-finite values.")
    return HaukSourcePsdZScoreResult(
        values=z_values,
        target_source_amplitudes=target,
        noise_mean_values=noise_mean.astype(float),
        noise_std_values=noise_std.astype(float),
        noise_values_after_extreme_drop=retained_noise.astype(float),
        zero_noise_sd_source_count=int(np.count_nonzero(~valid)),
    )


def compute_hauk_source_psd(
    *,
    averaged_raw: Any,
    inverse_operator: Any,
    config: HaukSourcePsdConfig,
    compute_source_psd_func: ComputeSourcePsdCallable | None = None,
) -> HaukSourcePsdResult:
    """Compute one participant/condition Hauk-informed source-space z-score map."""
    sfreq = _raw_sfreq(averaged_raw)
    n_times = _raw_n_times(averaged_raw)
    plan = build_hauk_source_psd_frequency_plan(
        sfreq=sfreq,
        n_times=n_times,
        selected_harmonics_hz=config.selected_harmonics_hz,
        bin_position_tolerance=config.bin_position_tolerance,
    )
    source_psd_callable = compute_source_psd_func or _default_compute_source_psd()
    source_psd = source_psd_callable(
        raw=averaged_raw,
        inverse_operator=inverse_operator,
        lambda2=float(config.lambda2),
        method=config.inverse_method,
        tmin=0.0,
        tmax=None,
        fmin=float(plan.fmin_hz),
        fmax=float(plan.fmax_hz),
        n_fft=int(plan.n_times),
        overlap=0.0,
        pick_ori=None,
        nave=1,
        pca=True,
        prepared=bool(config.prepared),
        method_params=dict(config.method_params) or None,
        bandwidth="hann",
        adaptive=False,
        low_bias=True,
        n_jobs=None,
        return_sensor=False,
        dB=False,
    )
    if isinstance(source_psd, tuple):
        if not source_psd:
            raise ValueError("Source PSD callable returned an empty tuple.")
        source_psd = source_psd[0]
    try:
        source_power = np.asarray(source_psd.data, dtype=float)
        source_frequencies = np.asarray(source_psd.times, dtype=float)
    except AttributeError as exc:
        raise TypeError("Source PSD callable must return an object with data and times arrays.") from exc
    source_amplitudes = source_amplitudes_from_psd_power(
        source_power,
        negative_relative_tolerance=config.negative_power_relative_tolerance,
    )
    summed = sum_harmonic_source_amplitudes(
        source_amplitudes=source_amplitudes,
        source_psd_frequencies_hz=source_frequencies,
        frequency_plan=plan,
        bin_position_tolerance=config.bin_position_tolerance,
    )
    zscore = compute_hauk_source_zscores(
        summed,
        aligned_offsets=plan.aligned_offsets,
        zero_sd_relative_tolerance=config.zero_noise_sd_relative_tolerance,
    )
    return HaukSourcePsdResult(
        config=config,
        frequency_plan=plan,
        summed_source_amplitudes=summed,
        zscore=zscore,
        source_count=int(source_power.shape[0]),
        source_psd_frequency_count=int(source_power.shape[1]),
    )


def _frequency_columns_by_exact_fft_bin(
    frequencies_hz: np.ndarray,
    *,
    frequency_plan: HaukSourcePsdFrequencyPlan,
    bin_position_tolerance: float,
) -> dict[int, int]:
    if frequencies_hz.ndim != 1 or len(frequencies_hz) == 0 or not np.all(np.isfinite(frequencies_hz)):
        raise ValueError("Source PSD frequencies must be a finite, non-empty 1D array.")
    if len(frequencies_hz) > 1 and np.any(np.diff(frequencies_hz) <= 0.0):
        raise ValueError("Source PSD frequencies must be strictly increasing.")
    tolerance = _positive_finite(bin_position_tolerance, label="bin_position_tolerance")
    columns_by_bin: dict[int, int] = {}
    for column, frequency in enumerate(frequencies_hz):
        position = float(frequency) * float(frequency_plan.n_times) / float(frequency_plan.sfreq)
        bin_index = int(np.rint(position))
        if abs(position - bin_index) > tolerance:
            raise ValueError(
                f"Source PSD returned off-grid frequency {frequency:g} Hz "
                f"(FFT position={position:.12g}); nearest-bin substitution is forbidden."
            )
        if bin_index in columns_by_bin:
            raise ValueError(f"Source PSD returned duplicate frequency columns for FFT bin {bin_index}.")
        columns_by_bin[bin_index] = column
    missing = [value for value in frequency_plan.required_bin_indices if value not in columns_by_bin]
    if missing:
        missing_hz = [float(value * frequency_plan.frequency_resolution_hz) for value in missing]
        raise ValueError(
            "Source PSD output is missing required exact FFT bins "
            f"{missing} ({missing_hz} Hz); nearest-bin substitution is forbidden."
        )
    return columns_by_bin


def _default_compute_source_psd() -> ComputeSourcePsdCallable:
    try:
        from mne.minimum_norm import compute_source_psd
    except (ImportError, ModuleNotFoundError) as exc:  # pragma: no cover - dependency contract
        raise ImportError("MNE is required for Hauk source-PSD estimation.") from exc
    return compute_source_psd


def _raw_sfreq(raw: Any) -> float:
    try:
        value = raw.info["sfreq"]
    except (AttributeError, KeyError, TypeError) as exc:
        raise TypeError("averaged_raw must expose info['sfreq'].") from exc
    return _positive_finite(value, label="averaged_raw.info['sfreq']")


def _raw_n_times(raw: Any) -> int:
    try:
        value = raw.n_times
    except AttributeError as exc:
        raise TypeError("averaged_raw must expose n_times.") from exc
    count = int(value)
    if count != value or count < 2:
        raise ValueError("averaged_raw.n_times must be an integer of at least 2.")
    return count


def _validated_harmonics(values: Sequence[float]) -> tuple[float, ...]:
    harmonics = tuple(sorted(float(value) for value in values))
    if not harmonics:
        raise ValueError("Hauk source-PSD estimation requires at least one selected harmonic.")
    if any(not np.isfinite(value) or value <= 0.0 for value in harmonics):
        raise ValueError("Selected Hauk source-PSD harmonics must be positive and finite.")
    if len(set(harmonics)) != len(harmonics):
        raise ValueError("Selected Hauk source-PSD harmonics must be unique.")
    return harmonics


def _validated_inverse_method(value: Any) -> str:
    method = str(value).strip()
    canonical_by_casefold = {
        candidate.casefold(): candidate for candidate in SUPPORTED_MNE_INVERSE_METHODS
    }
    try:
        return canonical_by_casefold[method.casefold()]
    except KeyError as exc:
        supported = ", ".join(SUPPORTED_MNE_INVERSE_METHODS)
        raise ValueError(
            f"Unsupported Hauk source-PSD inverse_method {value!r}; expected one of: {supported}."
        ) from exc


def _positive_finite(value: Any, *, label: str) -> float:
    number = float(value)
    if not np.isfinite(number) or number <= 0.0:
        raise ValueError(f"{label} must be positive and finite.")
    return number


def _nonnegative_finite(value: Any, *, label: str) -> float:
    number = float(value)
    if not np.isfinite(number) or number < 0.0:
        raise ValueError(f"{label} must be nonnegative and finite.")
    return number


__all__ = [
    "DEFAULT_BIN_POSITION_TOLERANCE",
    "DEFAULT_HAUK_SOURCE_PSD_ALIGNED_OFFSETS",
    "DEFAULT_HAUK_SOURCE_PSD_LAMBDA2",
    "DEFAULT_HAUK_SOURCE_PSD_NOISE_OFFSETS",
    "DEFAULT_NEGATIVE_POWER_RELATIVE_TOLERANCE",
    "DEFAULT_ZERO_NOISE_SD_RELATIVE_TOLERANCE",
    "HAUK_SOURCE_PSD_METHOD_ID",
    "HAUK_SOURCE_PSD_METHOD_VERSION",
    "HAUK_2021_REFERENCE_DOI",
    "HAUK_REFERENCE_CODE_URL",
    "SUPPORTED_MNE_INVERSE_METHODS",
    "HaukSourcePsdConfig",
    "HaukSourcePsdFrequencyPlan",
    "HaukSourcePsdResult",
    "HaukSourcePsdZScoreResult",
    "build_hauk_source_psd_frequency_plan",
    "compute_hauk_source_psd",
    "compute_hauk_source_zscores",
    "source_amplitudes_from_psd_power",
    "sum_harmonic_source_amplitudes",
]
