"""Raw EEG channel-health QC for preprocessing interpolation and exclusions."""

from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Callable, Iterable
from typing import Any, Mapping, Sequence

import numpy as np

from Main_App.io.eeg_geometry import (
    BIOSEMI64_CHANNELS,
    BIOSEMI64_CHANNEL_SET,
    BioSemi64GeometryError,
    canonical_biosemi64_head_coordinates,
    validate_raw_biosemi64_geometry,
)
from Main_App.processing.analysis_spans import merge_relative_spans
from Main_App.processing.removed_electrode_detection import (
    DEFAULT_REMOVED_ELECTRODE_DETECTION_CALIBRATION,
    REMOVED_ELECTRODE_DETECTION_MODE_AUTO,
    REMOVED_ELECTRODE_DETECTION_MODE_MANUAL,
    is_high_amplitude_removed_channel,
    is_low_variance_removed_channel,
    manual_removed_electrodes_are_enabled,
    normalize_removed_electrode_detection_mode,
    parse_electrode_list,
    removed_electrode_threshold_payload,
    spatial_predictability_outliers,
)

RAW_CHANNEL_QC_EXCLUSION_REASON = "raw_channel_qc_failure"
RAW_CHANNEL_QC_METHOD_VERSION = "analyzed_interval_review_flags_v4"
BIOSEMI_SHARED_NOISE_HELP_URL = "https://www.biosemi.com/faq/cms%26drl.htm"
SEVERE_RAW_AMPLITUDE_HELP_TEXT = (
    "Large raw signals detected. Referencing may reduce shared electrical noise. "
    "Review before excluding this recording."
)
_CALIBRATION = DEFAULT_REMOVED_ELECTRODE_DETECTION_CALIBRATION

SCALP_CHANNEL_ORDER: tuple[str, ...] = BIOSEMI64_CHANNELS
SCALP_CHANNELS: frozenset[str] = BIOSEMI64_CHANNEL_SET
MIDLINE_CHANNELS: frozenset[str] = frozenset(
    channel for channel in SCALP_CHANNEL_ORDER if channel.endswith("z")
)
LEFT_HEMISPHERE_CHANNELS: frozenset[str] = frozenset(
    channel
    for channel in SCALP_CHANNEL_ORDER
    if channel not in MIDLINE_CHANNELS and int(channel[-1]) % 2 == 1
)
RIGHT_HEMISPHERE_CHANNELS: frozenset[str] = frozenset(
    channel
    for channel in SCALP_CHANNEL_ORDER
    if channel not in MIDLINE_CHANNELS and int(channel[-1]) % 2 == 0
)

if (
    LEFT_HEMISPHERE_CHANNELS
    | RIGHT_HEMISPHERE_CHANNELS
    | MIDLINE_CHANNELS
) != SCALP_CHANNELS:
    raise RuntimeError("BioSemi64 hemisphere groups do not partition the scalp set.")


@dataclass(frozen=True)
class RawChannelQCConfig:
    max_bad_channels: int = 20
    max_bad_fraction: float = 0.50
    max_hemisphere_bad_fraction: float = 0.50
    min_channels_for_hard_qc: int = 16
    min_hemisphere_channels: int = 8
    low_std_uv: float = _CALIBRATION.low_std_uv
    low_p2p_99_uv: float = _CALIBRATION.low_p2p_99_uv
    low_std_relative_ratio: float = _CALIBRATION.low_std_relative_ratio
    low_p2p_99_relative_ratio: float = _CALIBRATION.low_p2p_99_relative_ratio
    relative_low_std_uv_ceiling: float = _CALIBRATION.relative_low_std_uv_ceiling
    relative_low_p2p_99_uv_ceiling: float = (
        _CALIBRATION.relative_low_p2p_99_uv_ceiling
    )
    high_std_relative_ratio: float = _CALIBRATION.high_std_relative_ratio
    high_p2p_99_relative_ratio: float = _CALIBRATION.high_p2p_99_relative_ratio
    high_std_uv_floor: float = _CALIBRATION.high_std_uv_floor
    high_p2p_99_uv_floor: float = _CALIBRATION.high_p2p_99_uv_floor
    baseline_warning_median_std_uv: float = _CALIBRATION.baseline_warning_median_std_uv
    baseline_warning_median_p2p_99_uv: float = (
        _CALIBRATION.baseline_warning_median_p2p_99_uv
    )
    baseline_exclusion_median_std_uv: float = (
        _CALIBRATION.baseline_exclusion_median_std_uv
    )
    baseline_exclusion_median_p2p_99_uv: float = (
        _CALIBRATION.baseline_exclusion_median_p2p_99_uv
    )
    rare_burst_std_uv_floor: float = _CALIBRATION.rare_burst_std_uv_floor
    rare_burst_p2p_99_uv_ceiling: float = (
        _CALIBRATION.rare_burst_p2p_99_uv_ceiling
    )
    rare_burst_p2p_999_uv_floor: float = (
        _CALIBRATION.rare_burst_p2p_999_uv_floor
    )
    rare_burst_full_to_p2p_99_ratio: float = (
        _CALIBRATION.rare_burst_full_to_p2p_99_ratio
    )
    rare_burst_rank_limit: int = _CALIBRATION.rare_burst_rank_limit
    auto_detect_removed_electrodes: bool = True
    min_bad_cluster_warning_size: int = _CALIBRATION.min_bad_cluster_warning_size
    min_bad_cluster_size: int = _CALIBRATION.min_bad_cluster_size
    neighbor_distance_factor: float = _CALIBRATION.neighbor_distance_factor
    spatial_qc_enabled: bool = _CALIBRATION.spatial_qc_enabled
    spatial_neighbor_count: int = _CALIBRATION.spatial_neighbor_count
    spatial_min_neighbors: int = _CALIBRATION.spatial_min_neighbors
    spatial_neighbor_distance_factor: float = _CALIBRATION.spatial_neighbor_distance_factor
    spatial_predictability_max_bad_corr: float = (
        _CALIBRATION.spatial_predictability_max_bad_corr
    )
    spatial_predictability_relative_ratio: float = (
        _CALIBRATION.spatial_predictability_relative_ratio
    )
    spatial_predictability_mad_z: float = _CALIBRATION.spatial_predictability_mad_z
    sample_windows: int = _CALIBRATION.sample_windows
    sample_window_s: float = _CALIBRATION.sample_window_s
    edge_padding_s: float = _CALIBRATION.edge_padding_s
    removed_electrode_detection_mode: str = REMOVED_ELECTRODE_DETECTION_MODE_AUTO
    manual_removed_electrodes: tuple[str, ...] = ()


@dataclass(frozen=True)
class RawChannelQCResult:
    excluded: bool
    reason: str | None
    message: str
    n_channels: int
    n_bad_channels: int
    bad_fraction: float
    left_bad: int
    left_total: int
    right_bad: int
    right_total: int
    midline_bad: int
    midline_total: int
    bad_channels: tuple[str, ...]
    channels_to_interpolate: tuple[str, ...]
    manual_removed_channels: tuple[str, ...]
    low_variance_channels: tuple[str, ...]
    high_amplitude_channels: tuple[str, ...]
    rare_burst_channels: tuple[str, ...]
    spatial_outlier_channels: tuple[str, ...]
    raw_baseline_median_std_uv: float
    raw_baseline_median_p2p_99_uv: float
    raw_baseline_warning: bool
    raw_baseline_excluded: bool
    largest_bad_cluster_size: int
    largest_bad_cluster_channels: tuple[str, ...]
    triggered_rules: tuple[str, ...]
    warning_rules: tuple[str, ...]
    thresholds: Mapping[str, float | int | bool]
    scoring_scope: str = "legacy_sampled_windows"
    scoring_spans: tuple[tuple[int, int], ...] = ()
    scoring_sample_count: int = 0
    review_rules: tuple[str, ...] = ()
    candidate_sources: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    burden_findings: tuple[Mapping[str, object], ...] = ()
    review_only: bool = True
    raw_baseline_severe_review: bool = False

    def to_payload(self) -> dict[str, object]:
        payload = {
            "method_version": RAW_CHANNEL_QC_METHOD_VERSION,
            "n_channels": self.n_channels,
            "n_bad_channels": self.n_bad_channels,
            "bad_fraction": self.bad_fraction,
            "left_bad": self.left_bad,
            "left_total": self.left_total,
            "right_bad": self.right_bad,
            "right_total": self.right_total,
            "midline_bad": self.midline_bad,
            "midline_total": self.midline_total,
            "bad_channels": list(self.bad_channels),
            "channels_to_interpolate": list(self.channels_to_interpolate),
            "manual_removed_channels": list(self.manual_removed_channels),
            "low_variance_channels": list(self.low_variance_channels),
            "high_amplitude_channels": list(self.high_amplitude_channels),
            "rare_burst_channels": list(self.rare_burst_channels),
            "spatial_outlier_channels": list(self.spatial_outlier_channels),
            "raw_baseline_median_std_uv": self.raw_baseline_median_std_uv,
            "raw_baseline_median_p2p_99_uv": self.raw_baseline_median_p2p_99_uv,
            "raw_baseline_warning": self.raw_baseline_warning,
            "raw_baseline_excluded": self.raw_baseline_excluded,
            "largest_bad_cluster_size": self.largest_bad_cluster_size,
            "largest_bad_cluster_channels": list(self.largest_bad_cluster_channels),
            "triggered_rules": list(self.triggered_rules),
            "warning_rules": list(self.warning_rules),
            "thresholds": dict(self.thresholds),
            "scoring_scope": self.scoring_scope,
            "scoring_spans": [list(span) for span in self.scoring_spans],
            "scoring_sample_count": self.scoring_sample_count,
            "review_only": self.review_only,
            "review_rules": list(self.review_rules),
            "candidate_sources": {
                str(channel): list(sources)
                for channel, sources in self.candidate_sources.items()
            },
            "candidate_burden_findings": [
                dict(finding) for finding in self.burden_findings
            ],
            "raw_baseline_severe_review": self.raw_baseline_severe_review,
        }
        payload["raw_amplitude_review_findings"] = (
            [
                {
                    "scope": "recording_analyzed_interval_union",
                    "severity": (
                        "severe_review"
                        if self.raw_baseline_severe_review
                        else "warning_review"
                    ),
                    "median_std_uv": self.raw_baseline_median_std_uv,
                    "median_p2p_99_uv": self.raw_baseline_median_p2p_99_uv,
                    "scoring_spans": [list(span) for span in self.scoring_spans],
                    "scoring_sample_count": self.scoring_sample_count,
                    "authority": "review_only",
                    "help_text": SEVERE_RAW_AMPLITUDE_HELP_TEXT,
                    "help_url": BIOSEMI_SHARED_NOISE_HELP_URL,
                }
            ]
            if self.raw_baseline_warning
            else []
        )
        return payload


@dataclass(frozen=True)
class _ChannelStats:
    channel: str
    group: str
    std_uv: float
    p2p_99_uv: float
    p2p_999_uv: float
    full_p2p_uv: float


def _channel_metric_values(
    values: np.ndarray,
) -> tuple[float, float, float, float]:
    """Return the v1 metrics while sharing percentile work."""

    metric_values = np.asarray(values)
    is_float64 = metric_values.dtype == np.dtype(np.float64)
    # Multi-quantile percentile calls can preserve a different zero sign than
    # separate scalar calls. Keep the established scalar formulas whenever a
    # signed-zero-sensitive value is present.
    vector_candidate = (
        is_float64
        and metric_values.size > 0
        and not bool(np.equal(metric_values, 0.0).any())
    )
    finite_float64 = vector_candidate and bool(
        np.isfinite(metric_values).all()
    )
    safe_vector_float64 = False
    if finite_float64:
        max_abs = float(np.max(np.abs(metric_values)))
        safe_limit = float(
            np.sqrt(
                np.finfo(np.float64).max
                / max(metric_values.size * 8, 1)
            )
        )
        safe_vector_float64 = max_abs <= safe_limit
    if safe_vector_float64:
        percentiles = np.percentile(
            metric_values,
            [0.05, 0.5, 99.5, 99.95],
        )
        std_uv = float(np.nanstd(metric_values) * 1e6)
        full_p2p_uv = float(
            (np.nanmax(metric_values) - np.nanmin(metric_values)) * 1e6
        )
    else:
        std_uv = float(np.nanstd(metric_values) * 1e6)
        p2p_99_uv = float(
            (
                np.nanpercentile(metric_values, 99.5)
                - np.nanpercentile(metric_values, 0.5)
            )
            * 1e6
        )
        p2p_999_uv = float(
            (
                np.nanpercentile(metric_values, 99.95)
                - np.nanpercentile(metric_values, 0.05)
            )
            * 1e6
        )
        full_p2p_uv = float(
            (np.nanmax(metric_values) - np.nanmin(metric_values)) * 1e6
        )
        return std_uv, p2p_99_uv, p2p_999_uv, full_p2p_uv
    p2p_99_uv = float((percentiles[2] - percentiles[1]) * 1e6)
    p2p_999_uv = float((percentiles[3] - percentiles[0]) * 1e6)
    return std_uv, p2p_99_uv, p2p_999_uv, full_p2p_uv


CONDITION_RAW_CHANNEL_QC_METHOD_VERSION = (
    "condition_windows_v6_five_second_half_overlap_biosemi64"
)


class ConditionRawChannelQCCancelled(RuntimeError):
    """Raised when condition-aware raw-channel QC is cancelled between blocks."""


@dataclass(frozen=True)
class ConditionRawChannelQCBlock:
    """One consecutive block from a single relevant condition occurrence.

    ``data`` contains every source channel listed in ``channel_names`` passed to
    :func:`evaluate_condition_raw_channel_qc_v2`. The evaluator selects scalp EEG
    channels itself. Windows may overlap. ``window_kind`` distinguishes regular
    windows, the optional full-length window aligned to the occurrence end, and
    a single short occurrence. ``is_final`` marks the last diagnostic window,
    not a disjoint data chunk.
    """

    condition_id: str
    occurrence: int
    start_sample: int
    stop_sample: int
    data: np.ndarray
    is_final: bool
    window_kind: str = "regular"


@dataclass(frozen=True)
class RawChannelMetricSet:
    """Float64 time-domain metrics for one channel over one exact sample span."""

    channel: str
    std_uv: float
    p2p_99_uv: float
    p2p_999_uv: float
    full_p2p_uv: float

    def to_payload(self) -> dict[str, object]:
        return {
            "channel": self.channel,
            "std_uv": self.std_uv,
            "p2p_99_uv": self.p2p_99_uv,
            "p2p_999_uv": self.p2p_999_uv,
            "full_p2p_uv": self.full_p2p_uv,
        }


@dataclass(frozen=True)
class RawChannelBlockMetrics:
    """Metrics and source-sample provenance for one channel in one QC block."""

    condition_id: str
    occurrence: int
    block_index: int
    start_sample: int
    stop_sample: int
    metrics: RawChannelMetricSet
    sampling_rate_hz: float = 1.0
    window_kind: str = "regular"
    review_categories: tuple[str, ...] = ()

    @property
    def n_samples(self) -> int:
        return self.stop_sample - self.start_sample

    @property
    def duration_s(self) -> float:
        return self.n_samples / self.sampling_rate_hz

    def to_payload(self) -> dict[str, object]:
        return {
            "condition_id": self.condition_id,
            "occurrence": self.occurrence,
            "block_index": self.block_index,
            "start_sample": self.start_sample,
            "stop_sample": self.stop_sample,
            "n_samples": self.n_samples,
            "duration_s": self.duration_s,
            "window_kind": self.window_kind,
            "review_categories": list(self.review_categories),
            **self.metrics.to_payload(),
        }


@dataclass(frozen=True)
class RawAmplitudeWindowMetrics:
    """Cap-wide amplitude evidence from one bounded diagnostic window."""

    condition_id: str
    occurrence: int
    start_sample: int
    stop_sample: int
    sampling_rate_hz: float
    window_kind: str
    median_std_uv: float
    median_p2p_99_uv: float
    severe_review: bool

    @property
    def n_samples(self) -> int:
        return self.stop_sample - self.start_sample

    def to_payload(self) -> dict[str, object]:
        return {
            "condition_label": self.condition_id,
            "occurrence": self.occurrence,
            "occurrence_display": self.occurrence + 1,
            "start_sample": self.start_sample,
            "stop_sample": self.stop_sample,
            "sample_count": self.n_samples,
            "duration_s": self.n_samples / self.sampling_rate_hz,
            "window_kind": self.window_kind,
            "median_std_uv": self.median_std_uv,
            "median_p2p_99_uv": self.median_p2p_99_uv,
            "severity": (
                "severe_review" if self.severe_review else "warning_review"
            ),
        }


@dataclass(frozen=True)
class RawChannelTransientExtrema:
    """Quietest and highest-amplitude blocks retained for review provenance."""

    channel: str
    lowest_variance_block: RawChannelBlockMetrics
    highest_amplitude_block: RawChannelBlockMetrics

    def to_payload(self) -> dict[str, object]:
        return {
            "channel": self.channel,
            "lowest_variance_block": self.lowest_variance_block.to_payload(),
            "highest_amplitude_block": self.highest_amplitude_block.to_payload(),
        }


@dataclass(frozen=True)
class RawChannelConditionAggregate:
    """Persistent aggregate plus transient review findings for one occurrence."""

    condition_id: str
    occurrence: int
    start_sample: int
    stop_sample: int
    n_blocks: int
    channel_metrics: tuple[RawChannelMetricSet, ...]
    low_variance_channels: tuple[str, ...]
    high_amplitude_channels: tuple[str, ...]
    rare_burst_channels: tuple[str, ...]
    spatial_outlier_channels: tuple[str, ...]
    transient_low_variance_channels: tuple[str, ...]
    transient_high_amplitude_channels: tuple[str, ...]
    transient_rare_burst_channels: tuple[str, ...]
    raw_baseline_median_std_uv: float
    raw_baseline_median_p2p_99_uv: float
    raw_baseline_warning: bool
    raw_baseline_failure_review: bool

    @property
    def n_samples(self) -> int:
        return self.stop_sample - self.start_sample

    def to_payload(self) -> dict[str, object]:
        return {
            "condition_id": self.condition_id,
            "occurrence": self.occurrence,
            "start_sample": self.start_sample,
            "stop_sample": self.stop_sample,
            "n_samples": self.n_samples,
            "n_blocks": self.n_blocks,
            "channel_metrics": [item.to_payload() for item in self.channel_metrics],
            "low_variance_channels": list(self.low_variance_channels),
            "high_amplitude_channels": list(self.high_amplitude_channels),
            "rare_burst_channels": list(self.rare_burst_channels),
            "spatial_outlier_channels": list(self.spatial_outlier_channels),
            "transient_low_variance_channels": list(self.transient_low_variance_channels),
            "transient_high_amplitude_channels": list(self.transient_high_amplitude_channels),
            "transient_rare_burst_channels": list(self.transient_rare_burst_channels),
            "raw_baseline_median_std_uv": self.raw_baseline_median_std_uv,
            "raw_baseline_median_p2p_99_uv": self.raw_baseline_median_p2p_99_uv,
            "raw_baseline_warning": self.raw_baseline_warning,
            "raw_baseline_failure_review": self.raw_baseline_failure_review,
        }


@dataclass(frozen=True)
class ConditionRawChannelQCResult:
    """Condition-only raw-channel QC findings that never hard-exclude data."""

    filename: str
    channel_names: tuple[str, ...]
    conditions: tuple[RawChannelConditionAggregate, ...]
    transient_extrema: tuple[RawChannelTransientExtrema, ...]
    manual_removed_channels: tuple[str, ...]
    thresholds: Mapping[str, float | int | bool]
    review_rules: tuple[str, ...]
    candidate_sources: Mapping[str, tuple[str, ...]]
    burden_findings: tuple[Mapping[str, object], ...]
    largest_bad_cluster_channels: tuple[str, ...]
    occurrence_review_findings: tuple[Mapping[str, object], ...]
    transient_review_findings: tuple[Mapping[str, object], ...]
    transient_amplitude_review_findings: tuple[Mapping[str, object], ...]
    transient_windowing: Mapping[str, object]
    method_version: str = CONDITION_RAW_CHANNEL_QC_METHOD_VERSION
    review_only: bool = True
    excluded: bool = False
    reason: str | None = None

    @property
    def n_channels(self) -> int:
        return len(self.channel_names)

    @property
    def n_conditions(self) -> int:
        return len(self.conditions)

    @property
    def n_blocks(self) -> int:
        return sum(item.n_blocks for item in self.conditions)

    @property
    def n_samples(self) -> int:
        return sum(item.n_samples for item in self.conditions)

    def _condition_union(self, field: str) -> tuple[str, ...]:
        selected: set[str] = set()
        for condition in self.conditions:
            selected.update(getattr(condition, field))
        return tuple(channel for channel in self.channel_names if channel in selected)

    def _condition_intersection(self, field: str) -> tuple[str, ...]:
        if not self.conditions:
            return ()
        selected = set(getattr(self.conditions[0], field))
        for condition in self.conditions[1:]:
            selected.intersection_update(getattr(condition, field))
        return tuple(channel for channel in self.channel_names if channel in selected)

    @property
    def persistent_low_variance_channels(self) -> tuple[str, ...]:
        return self._condition_intersection("low_variance_channels")

    @property
    def persistent_high_amplitude_channels(self) -> tuple[str, ...]:
        return self._condition_intersection("high_amplitude_channels")

    @property
    def persistent_rare_burst_channels(self) -> tuple[str, ...]:
        return self._condition_intersection("rare_burst_channels")

    @property
    def persistent_spatial_outlier_channels(self) -> tuple[str, ...]:
        return self._condition_intersection("spatial_outlier_channels")

    @property
    def transient_low_variance_channels(self) -> tuple[str, ...]:
        return self._condition_union("transient_low_variance_channels")

    @property
    def transient_high_amplitude_channels(self) -> tuple[str, ...]:
        return self._condition_union("transient_high_amplitude_channels")

    @property
    def transient_rare_burst_channels(self) -> tuple[str, ...]:
        return self._condition_union("transient_rare_burst_channels")

    @property
    def low_variance_channels(self) -> tuple[str, ...]:
        return self.persistent_low_variance_channels

    @property
    def high_amplitude_channels(self) -> tuple[str, ...]:
        return self.persistent_high_amplitude_channels

    @property
    def rare_burst_channels(self) -> tuple[str, ...]:
        return self.persistent_rare_burst_channels

    @property
    def bad_channels(self) -> tuple[str, ...]:
        return tuple(self.candidate_sources)

    @property
    def channels_to_interpolate(self) -> tuple[str, ...]:
        # Persistent full-condition findings feed the existing user-review gate.
        # Transient block findings are never interpolation candidates.
        return _ordered_channel_union(
            self.channel_names,
            self.manual_removed_channels,
            self.persistent_low_variance_channels,
        )

    @property
    def spatial_outlier_channels(self) -> tuple[str, ...]:
        return self.persistent_spatial_outlier_channels

    @property
    def triggered_rules(self) -> tuple[str, ...]:
        return ()

    @property
    def warning_rules(self) -> tuple[str, ...]:
        return self.review_rules

    @property
    def largest_bad_cluster_size(self) -> int:
        return len(self.largest_bad_cluster_channels)

    @property
    def raw_baseline_warning(self) -> bool:
        return any(item.raw_baseline_warning for item in self.conditions)

    @property
    def raw_baseline_failure_review(self) -> bool:
        return any(item.raw_baseline_failure_review for item in self.conditions)

    @property
    def raw_baseline_excluded(self) -> bool:
        return False

    @property
    def raw_baseline_median_std_uv(self) -> float:
        return max(
            (item.raw_baseline_median_std_uv for item in self.conditions),
            default=0.0,
        )

    @property
    def raw_baseline_median_p2p_99_uv(self) -> float:
        return max(
            (item.raw_baseline_median_p2p_99_uv for item in self.conditions),
            default=0.0,
        )

    @property
    def n_bad_channels(self) -> int:
        return len(self.bad_channels)

    @property
    def bad_fraction(self) -> float:
        return self.n_bad_channels / self.n_channels if self.n_channels else 0.0

    @property
    def message(self) -> str:
        if not self.conditions:
            return f"Condition-aware raw channel QC skipped for {self.filename}: no condition samples were supplied."
        if self.bad_channels or self.raw_baseline_warning or self.review_rules:
            return (
                f"Condition-aware raw channel QC completed for {self.filename}: "
                f"{self.n_conditions} condition occurrence(s), {self.n_blocks} "
                "diagnostic window(s), and "
                f"{self.n_bad_channels}/{self.n_channels} channel(s) were persistently "
                "flagged across all occurrences; transient findings are reported separately. "
                "Signal-review findings do not automatically exclude recordings or select "
                "channels for interpolation."
            )
        return (
            f"Condition-aware raw channel QC passed for {self.filename}: "
            f"{self.n_conditions} condition occurrence(s) and {self.n_blocks} "
            "diagnostic window(s) examined."
        )

    def to_payload(self) -> dict[str, object]:
        left = sum(channel in LEFT_HEMISPHERE_CHANNELS for channel in self.bad_channels)
        right = sum(channel in RIGHT_HEMISPHERE_CHANNELS for channel in self.bad_channels)
        midline = sum(channel in MIDLINE_CHANNELS for channel in self.bad_channels)
        payload = {
            "method_version": self.method_version,
            "review_only": self.review_only,
            "excluded": self.excluded,
            "reason": self.reason,
            "message": self.message,
            "n_channels": self.n_channels,
            "n_conditions": self.n_conditions,
            "n_blocks": self.n_blocks,
            "n_samples": self.n_samples,
            "n_bad_channels": self.n_bad_channels,
            "bad_fraction": self.bad_fraction,
            "left_bad": left,
            "left_total": sum(channel in LEFT_HEMISPHERE_CHANNELS for channel in self.channel_names),
            "right_bad": right,
            "right_total": sum(channel in RIGHT_HEMISPHERE_CHANNELS for channel in self.channel_names),
            "midline_bad": midline,
            "midline_total": sum(channel in MIDLINE_CHANNELS for channel in self.channel_names),
            "bad_channels": list(self.bad_channels),
            "channels_to_interpolate": list(self.channels_to_interpolate),
            "manual_removed_channels": list(self.manual_removed_channels),
            "low_variance_channels": list(self.low_variance_channels),
            # Compatibility review-table fields contain persistent findings only.
            # Transient block findings remain separately reported below and must
            # not be prefilled as physically removed/interpolation candidates.
            "high_amplitude_channels": list(self.persistent_high_amplitude_channels),
            "rare_burst_channels": list(self.persistent_rare_burst_channels),
            "persistent_low_variance_channels": list(self.persistent_low_variance_channels),
            "persistent_high_amplitude_channels": list(self.persistent_high_amplitude_channels),
            "persistent_rare_burst_channels": list(self.persistent_rare_burst_channels),
            "persistent_spatial_outlier_channels": list(
                self.persistent_spatial_outlier_channels
            ),
            "transient_low_variance_channels": list(self.transient_low_variance_channels),
            "transient_high_amplitude_channels": list(self.transient_high_amplitude_channels),
            "transient_rare_burst_channels": list(self.transient_rare_burst_channels),
            "spatial_outlier_channels": list(self.spatial_outlier_channels),
            "spatial_qc_evaluated": bool(
                self.thresholds.get("spatial_predictability_experimental")
            ),
            "raw_baseline_median_std_uv": self.raw_baseline_median_std_uv,
            "raw_baseline_median_p2p_99_uv": self.raw_baseline_median_p2p_99_uv,
            "raw_baseline_aggregation": "maximum_across_condition_occurrences",
            "raw_baseline_warning": self.raw_baseline_warning,
            "raw_baseline_excluded": False,
            "raw_baseline_failure_review": self.raw_baseline_failure_review,
            "largest_bad_cluster_size": self.largest_bad_cluster_size,
            "largest_bad_cluster_channels": list(
                self.largest_bad_cluster_channels
            ),
            "bad_cluster_qc_evaluated": bool(
                self.thresholds.get("bad_channel_cluster_experimental")
            ),
            "triggered_rules": [],
            "warning_rules": list(self.warning_rules),
            "review_rules": list(self.review_rules),
            "candidate_sources": {
                channel: list(sources)
                for channel, sources in self.candidate_sources.items()
            },
            "candidate_burden_findings": [
                dict(finding) for finding in self.burden_findings
            ],
            "occurrence_review_findings": [
                dict(finding) for finding in self.occurrence_review_findings
            ],
            "transient_review_findings": [
                dict(finding) for finding in self.transient_review_findings
            ],
            "transient_windowing": dict(self.transient_windowing),
            "thresholds": dict(self.thresholds),
            "conditions": [item.to_payload() for item in self.conditions],
            "transient_extrema": [item.to_payload() for item in self.transient_extrema],
        }
        payload["raw_amplitude_review_findings"] = [
            {
                "scope": "condition_occurrence",
                "condition_label": condition.condition_id,
                "occurrence": condition.occurrence,
                "occurrence_display": condition.occurrence + 1,
                "start_sample": condition.start_sample,
                "stop_sample": condition.stop_sample,
                "sample_count": condition.n_samples,
                "median_std_uv": condition.raw_baseline_median_std_uv,
                "median_p2p_99_uv": condition.raw_baseline_median_p2p_99_uv,
                "severity": (
                    "severe_review"
                    if condition.raw_baseline_failure_review
                    else "warning_review"
                ),
                "authority": "review_only",
                "help_text": SEVERE_RAW_AMPLITUDE_HELP_TEXT,
                "help_url": BIOSEMI_SHARED_NOISE_HELP_URL,
            }
            for condition in self.conditions
            if condition.raw_baseline_warning
        ] + [dict(finding) for finding in self.transient_amplitude_review_findings]
        return payload


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _coerce_bool(value: Any, default: bool) -> bool:
    if value in (None, ""):
        return bool(default)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
        if not lowered:
            return bool(default)
    return bool(default)


def _config_from_settings(settings: Mapping[str, Any]) -> RawChannelQCConfig:
    max_bad = _coerce_int(
        settings.get(
            "max_bad_chans",
            settings.get("max_bad_channels", settings.get("max_bad_channels_alert_thresh")),
        ),
        RawChannelQCConfig.max_bad_channels,
    )
    auto_detect = _coerce_bool(
        settings.get(
            "auto_detect_removed_electrodes",
            settings.get(
                "detect_removed_electrodes",
                settings.get("auto_mark_removed_electrodes"),
            ),
        ),
        RawChannelQCConfig.auto_detect_removed_electrodes,
    )
    mode = normalize_removed_electrode_detection_mode(
        settings.get("removed_electrode_detection_mode"),
        auto_detect_removed_electrodes=auto_detect,
    )
    manual_removed = (
        tuple(parse_electrode_list(settings.get("_fpvs_manual_removed_electrodes")))
        if manual_removed_electrodes_are_enabled(settings)
        else ()
    )
    return RawChannelQCConfig(
        max_bad_channels=max(0, max_bad),
        auto_detect_removed_electrodes=(
            mode == REMOVED_ELECTRODE_DETECTION_MODE_AUTO
        ),
        removed_electrode_detection_mode=mode,
        manual_removed_electrodes=manual_removed,
    )


def _sample_spans(n_times: int, sfreq: float, config: RawChannelQCConfig) -> list[tuple[int, int]]:
    if n_times <= 0:
        return []
    window = max(1, int(round(config.sample_window_s * sfreq)))
    if n_times <= window:
        return [(0, n_times)]

    edge = int(round(config.edge_padding_s * sfreq))
    edge = min(edge, max(0, (n_times - window) // 4))
    first = edge
    last = max(first, n_times - window - edge)
    starts = np.linspace(first, last, max(1, int(config.sample_windows))).astype(int)
    return [(int(start), int(start + window)) for start in starts]


def _channel_group(channel: str) -> str:
    if channel in LEFT_HEMISPHERE_CHANNELS:
        return "left"
    if channel in RIGHT_HEMISPHERE_CHANNELS:
        return "right"
    if channel in MIDLINE_CHANNELS:
        return "midline"
    return "other"


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


def _raw_bads(raw: Any) -> list[str]:
    bads = getattr(getattr(raw, "info", {}), "get", lambda *_args: [])("bads", [])
    if not isinstance(bads, Sequence) or isinstance(bads, str):
        return []
    return [str(channel) for channel in bads if str(channel) in SCALP_CHANNELS]


def _safe_get_data(raw: Any, picks: Sequence[int], start: int, stop: int) -> np.ndarray:
    try:
        return raw.get_data(picks=picks, start=start, stop=stop, verbose=False)
    except TypeError:
        return raw.get_data(picks=picks, start=start, stop=stop)


def _robust_median(values: Sequence[float]) -> float:
    finite = [float(value) for value in values if np.isfinite(value) and value > 0.0]
    if not finite:
        return 0.0
    return float(np.median(finite))


def _configured_geometry_roles(
    raw: Any,
    settings: Mapping[str, Any],
) -> tuple[tuple[str, ...], str | None]:
    """Return only configured reference/stim roles that remain in ``raw``."""

    raw_name_lookup = {
        str(channel).casefold(): str(channel)
        for channel in getattr(raw, "ch_names", ())
    }
    references = (
        str(
            settings.get("ref_channel1")
            or settings.get("ref_chan1")
            or settings.get("ref_ch1")
            or "EXG1"
        ),
        str(
            settings.get("ref_channel2")
            or settings.get("ref_chan2")
            or settings.get("ref_ch2")
            or "EXG2"
        ),
    )
    retained_references = tuple(
        raw_name_lookup[channel.casefold()]
        for channel in references
        if channel.casefold() in raw_name_lookup
    )
    stim = str(settings.get("stim_channel") or settings.get("stim") or "Status")
    return retained_references, raw_name_lookup.get(stim.casefold())


def _validate_spatial_geometry(
    raw: Any,
    channels: Sequence[str],
    settings: Mapping[str, Any],
) -> None:
    """Require the loader-attached BioSemi64 identity for spatial QC."""

    references, stim = _configured_geometry_roles(raw, settings)
    validate_raw_biosemi64_geometry(
        raw,
        expected_retained_channels=channels,
        reference_channels=references,
        stim_channel=stim,
        require_runtime_identity=True,
    )


def _channel_positions(raw: Any, channels: Sequence[str]) -> dict[str, np.ndarray]:
    """Read validated head coordinates without a missing-position fallback."""

    raw_names = tuple(str(channel) for channel in getattr(raw, "ch_names", ()))
    index_by_name = {channel: index for index, channel in enumerate(raw_names)}
    positions: dict[str, np.ndarray] = {}
    for channel in channels:
        index = index_by_name.get(str(channel))
        if index is None:
            raise BioSemi64GeometryError(
                f"Spatial raw-channel QC cannot locate retained channel {channel!r}."
            )
        try:
            coordinate = np.asarray(raw.info["chs"][index]["loc"][:3], dtype=float)
        except (AttributeError, KeyError, IndexError, TypeError, ValueError) as error:
            raise BioSemi64GeometryError(
                f"Spatial raw-channel QC cannot read the coordinate for {channel!r}."
            ) from error
        if (
            coordinate.shape != (3,)
            or not np.isfinite(coordinate).all()
            or np.allclose(coordinate, 0.0)
        ):
            raise BioSemi64GeometryError(
                f"Spatial raw-channel QC requires a finite BioSemi64 coordinate for {channel!r}."
            )
        positions[str(channel)] = coordinate
    return positions


def _bad_channel_clusters(
    raw: Any,
    bad_channels: Sequence[str],
    *,
    config: RawChannelQCConfig,
) -> list[tuple[str, ...]]:
    all_scalp = [
        str(channel)
        for channel in getattr(raw, "ch_names", [])
        if str(channel) in SCALP_CHANNELS
    ]
    return _bad_channel_clusters_from_positions(
        _channel_positions(raw, all_scalp),
        bad_channels,
        config=config,
    )


def _bad_channel_clusters_from_positions(
    positions: Mapping[str, Sequence[float]],
    bad_channels: Sequence[str],
    *,
    config: RawChannelQCConfig,
) -> list[tuple[str, ...]]:
    """Return connected candidate components for one explicit sensor geometry."""

    unique_bads = sorted(
        {
            str(channel)
            for channel in bad_channels
            if str(channel) in SCALP_CHANNELS and str(channel) in positions
        }
    )
    if not unique_bads:
        return []

    if len(positions) < 2:
        return [(channel,) for channel in unique_bads]

    pos_names = sorted(positions)
    coords = np.vstack(
        [np.asarray(positions[name], dtype=float) for name in pos_names]
    )
    distances = np.linalg.norm(coords[:, None, :] - coords[None, :, :], axis=2)
    np.fill_diagonal(distances, np.inf)
    nearest = np.min(distances, axis=1)
    finite_nearest = nearest[np.isfinite(nearest) & (nearest > 0.0)]
    if finite_nearest.size == 0:
        return [(channel,) for channel in unique_bads]
    threshold = float(np.median(finite_nearest) * config.neighbor_distance_factor)

    index_by_name = {name: idx for idx, name in enumerate(pos_names)}
    bad_lookup = set(unique_bads)
    adjacency: dict[str, set[str]] = {channel: set() for channel in unique_bads}
    for left_pos, left_name in enumerate(pos_names):
        if left_name not in bad_lookup:
            continue
        for right_name in unique_bads:
            right_pos = index_by_name.get(right_name)
            if right_pos is None or right_name == left_name:
                continue
            if float(distances[left_pos, right_pos]) <= threshold:
                adjacency[left_name].add(right_name)
                adjacency[right_name].add(left_name)

    seen: set[str] = set()
    clusters: list[tuple[str, ...]] = []
    for channel in unique_bads:
        if channel in seen:
            continue
        stack = [channel]
        component: list[str] = []
        seen.add(channel)
        while stack:
            current = stack.pop()
            component.append(current)
            for neighbor in adjacency.get(current, set()):
                if neighbor not in seen:
                    seen.add(neighbor)
                    stack.append(neighbor)
        clusters.append(tuple(sorted(component)))
    clusters.sort(key=lambda item: (-len(item), item))
    return clusters


def _spatial_neighbor_map(
    raw: Any,
    channels: Sequence[str],
    *,
    config: RawChannelQCConfig,
) -> dict[str, tuple[str, ...]]:
    return _spatial_neighbor_map_from_positions(
        _channel_positions(raw, channels),
        channels,
        config=config,
    )


def _spatial_neighbor_map_from_positions(
    positions: Mapping[str, Sequence[float]],
    channels: Sequence[str],
    *,
    config: RawChannelQCConfig,
) -> dict[str, tuple[str, ...]]:
    positions = {
        str(channel): np.asarray(positions[str(channel)], dtype=float)
        for channel in channels
        if str(channel) in positions
    }
    if len(positions) < config.spatial_min_neighbors + 1:
        return {}

    pos_names = sorted(positions)
    coords = np.vstack([positions[name] for name in pos_names])
    distances = np.linalg.norm(coords[:, None, :] - coords[None, :, :], axis=2)
    np.fill_diagonal(distances, np.inf)
    nearest = np.min(distances, axis=1)
    finite_nearest = nearest[np.isfinite(nearest) & (nearest > 0.0)]
    if finite_nearest.size == 0:
        return {}
    radius = float(np.median(finite_nearest) * config.spatial_neighbor_distance_factor)

    neighbors: dict[str, tuple[str, ...]] = {}
    max_neighbors = max(config.spatial_min_neighbors, config.spatial_neighbor_count)
    for row_index, channel in enumerate(pos_names):
        ordered_indices = [
            int(index)
            for index in np.argsort(distances[row_index])
            if np.isfinite(distances[row_index, index])
        ]
        local = [
            pos_names[index]
            for index in ordered_indices
            if float(distances[row_index, index]) <= radius
        ][:max_neighbors]
        if len(local) < config.spatial_min_neighbors:
            local = [pos_names[index] for index in ordered_indices[: config.spatial_min_neighbors]]
        neighbors[channel] = tuple(local[:max_neighbors])
    return neighbors


def _zscore_rows(data: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    centered = data - np.nanmedian(data, axis=1, keepdims=True)
    scale = np.nanstd(centered, axis=1)
    safe_scale = np.where(scale > 0.0, scale, np.nan)
    return centered / safe_scale[:, None], scale


def _spatial_predictability_scores(
    raw: Any,
    data: np.ndarray,
    channels: Sequence[str],
    *,
    donor_exclusions: Sequence[str],
    config: RawChannelQCConfig,
) -> dict[str, float]:
    return _spatial_predictability_scores_with_neighbors(
        data,
        channels,
        neighbor_map=_spatial_neighbor_map(raw, channels, config=config),
        donor_exclusions=donor_exclusions,
        config=config,
    )


def _spatial_predictability_scores_with_neighbors(
    data: np.ndarray,
    channels: Sequence[str],
    *,
    neighbor_map: Mapping[str, Sequence[str]],
    donor_exclusions: Sequence[str],
    config: RawChannelQCConfig,
) -> dict[str, float]:
    if not neighbor_map:
        return {}

    channel_lookup = {channel: index for index, channel in enumerate(channels)}
    excluded = {str(channel) for channel in donor_exclusions}
    z_data, row_scale = _zscore_rows(data)
    scores: dict[str, float] = {}
    for channel in channels:
        row_index = channel_lookup[channel]
        if not np.isfinite(row_scale[row_index]) or row_scale[row_index] <= 0.0:
            continue

        neighbor_indices = [
            channel_lookup[neighbor]
            for neighbor in neighbor_map.get(channel, ())
            if neighbor not in excluded
            and neighbor in channel_lookup
            and np.isfinite(row_scale[channel_lookup[neighbor]])
            and row_scale[channel_lookup[neighbor]] > 0.0
        ]
        if len(neighbor_indices) < config.spatial_min_neighbors:
            continue

        prediction = np.nanmean(z_data[neighbor_indices], axis=0)
        observed = z_data[row_index]
        finite = np.isfinite(observed) & np.isfinite(prediction)
        if int(np.sum(finite)) < config.spatial_min_neighbors:
            continue
        obs = observed[finite]
        pred = prediction[finite]
        denom = float(np.linalg.norm(obs) * np.linalg.norm(pred))
        if denom <= 0.0 or not np.isfinite(denom):
            continue
        scores[channel] = float(abs(np.dot(obs, pred) / denom))
    return scores


def _spatial_outlier_channels(
    scores: Mapping[str, float],
    *,
    excluded_channels: Sequence[str],
    config: RawChannelQCConfig,
) -> tuple[str, ...]:
    return spatial_predictability_outliers(
        dict(scores),
        excluded_channels=tuple(excluded_channels),
        calibration=config,
        min_reference_count=config.min_channels_for_hard_qc,
    )


def _candidate_source_map(
    channel_names: Sequence[str],
    **sources: Sequence[str],
) -> dict[str, tuple[str, ...]]:
    """Keep each candidate channel's evidence sources separate and ordered."""

    source_sets = {
        str(source): {str(channel) for channel in channels}
        for source, channels in sources.items()
    }
    return {
        str(channel): tuple(
            source
            for source, channels in source_sets.items()
            if str(channel) in channels
        )
        for channel in channel_names
        if any(str(channel) in channels for channels in source_sets.values())
    }


def _candidate_burden(
    channel_names: Sequence[str],
    candidate_sources: Mapping[str, Sequence[str]],
    *,
    positions: Mapping[str, Sequence[float]],
    config: RawChannelQCConfig,
    cluster_rules_enabled: bool,
) -> dict[str, object]:
    """Describe provisional candidate burden without making an exclusion decision."""

    candidates = tuple(
        str(channel)
        for channel in channel_names
        if str(channel) in candidate_sources
    )
    left_channels = tuple(
        channel for channel in candidates if channel in LEFT_HEMISPHERE_CHANNELS
    )
    right_channels = tuple(
        channel for channel in candidates if channel in RIGHT_HEMISPHERE_CHANNELS
    )
    midline_channels = tuple(
        channel for channel in candidates if channel in MIDLINE_CHANNELS
    )
    left_total = sum(channel in LEFT_HEMISPHERE_CHANNELS for channel in channel_names)
    right_total = sum(channel in RIGHT_HEMISPHERE_CHANNELS for channel in channel_names)
    midline_total = sum(channel in MIDLINE_CHANNELS for channel in channel_names)
    n_channels = len(channel_names)
    n_candidates = len(candidates)
    bad_fraction = n_candidates / n_channels if n_channels else 0.0
    left_fraction = len(left_channels) / left_total if left_total else 0.0
    right_fraction = len(right_channels) / right_total if right_total else 0.0
    clusters = (
        _bad_channel_clusters_from_positions(
            positions,
            candidates,
            config=config,
        )
        if cluster_rules_enabled
        else []
    )
    largest_cluster = clusters[0] if clusters else ()

    findings: list[dict[str, object]] = []

    def add_finding(
        rule: str,
        *,
        observed: float | int,
        threshold: float | int,
        comparator: str,
        channels: Sequence[str],
        denominator: int | None = None,
        severity: str = "review",
    ) -> None:
        findings.append(
            {
                "rule": rule,
                "authority": "review_only",
                "severity": severity,
                "observed": observed,
                "threshold": threshold,
                "comparator": comparator,
                "denominator": denominator,
                "channels": list(channels),
                "candidate_sources": {
                    channel: list(candidate_sources[channel])
                    for channel in channels
                    if channel in candidate_sources
                },
                "rule_version": RAW_CHANNEL_QC_METHOD_VERSION,
            }
        )

    if n_candidates > config.max_bad_channels:
        add_finding(
            "candidate_count_review",
            observed=n_candidates,
            threshold=config.max_bad_channels,
            comparator=">",
            channels=candidates,
            denominator=n_channels,
        )
    if bad_fraction > config.max_bad_fraction:
        add_finding(
            "candidate_fraction_review",
            observed=bad_fraction,
            threshold=config.max_bad_fraction,
            comparator=">",
            channels=candidates,
            denominator=n_channels,
        )
    if (
        left_total >= config.min_hemisphere_channels
        and left_fraction >= config.max_hemisphere_bad_fraction
    ):
        add_finding(
            "left_hemisphere_candidate_burden_review",
            observed=left_fraction,
            threshold=config.max_hemisphere_bad_fraction,
            comparator=">=",
            channels=left_channels,
            denominator=left_total,
        )
    if (
        right_total >= config.min_hemisphere_channels
        and right_fraction >= config.max_hemisphere_bad_fraction
    ):
        add_finding(
            "right_hemisphere_candidate_burden_review",
            observed=right_fraction,
            threshold=config.max_hemisphere_bad_fraction,
            comparator=">=",
            channels=right_channels,
            denominator=right_total,
        )
    if cluster_rules_enabled and len(largest_cluster) >= config.min_bad_cluster_size:
        add_finding(
            "candidate_cluster_review",
            observed=len(largest_cluster),
            threshold=config.min_bad_cluster_size,
            comparator=">=",
            channels=largest_cluster,
            severity="severe_review",
        )
    elif (
        cluster_rules_enabled
        and len(largest_cluster) >= config.min_bad_cluster_warning_size
    ):
        add_finding(
            "possible_candidate_cluster_review",
            observed=len(largest_cluster),
            threshold=config.min_bad_cluster_warning_size,
            comparator=">=",
            channels=largest_cluster,
            severity="warning_review",
        )

    return {
        "candidate_channels": candidates,
        "n_candidates": n_candidates,
        "n_channels": n_channels,
        "candidate_fraction": bad_fraction,
        "left_channels": left_channels,
        "left_total": left_total,
        "left_fraction": left_fraction,
        "right_channels": right_channels,
        "right_total": right_total,
        "right_fraction": right_fraction,
        "midline_channels": midline_channels,
        "midline_total": midline_total,
        "largest_cluster": tuple(largest_cluster),
        "clusters": tuple(tuple(cluster) for cluster in clusters),
        "findings": tuple(findings),
    }


def _empty_result(
    *,
    message: str,
    thresholds: Mapping[str, float | int | bool],
    n_channels: int = 0,
    scoring_scope: str = "legacy_sampled_windows",
    scoring_spans: tuple[tuple[int, int], ...] = (),
) -> RawChannelQCResult:
    return RawChannelQCResult(
        excluded=False,
        reason=None,
        message=message,
        n_channels=n_channels,
        n_bad_channels=0,
        bad_fraction=0.0,
        left_bad=0,
        left_total=0,
        right_bad=0,
        right_total=0,
        midline_bad=0,
        midline_total=0,
        bad_channels=(),
        channels_to_interpolate=(),
        manual_removed_channels=(),
        low_variance_channels=(),
        high_amplitude_channels=(),
        rare_burst_channels=(),
        spatial_outlier_channels=(),
        raw_baseline_median_std_uv=0.0,
        raw_baseline_median_p2p_99_uv=0.0,
        raw_baseline_warning=False,
        raw_baseline_excluded=False,
        largest_bad_cluster_size=0,
        largest_bad_cluster_channels=(),
        triggered_rules=(),
        warning_rules=(),
        thresholds=thresholds,
        scoring_scope=scoring_scope,
        scoring_spans=scoring_spans,
        scoring_sample_count=sum(stop - start for start, stop in scoring_spans),
    )


def evaluate_raw_channel_qc(
    raw: Any,
    settings: Mapping[str, Any],
    *,
    filename: str,
    analysis_spans: Sequence[Sequence[int]] | None = None,
) -> RawChannelQCResult:
    """Detect flat/dead electrode channels before interpolation can hide them."""

    config = _config_from_settings(settings)
    stim_channel = str(settings.get("stim_channel") or "")
    ref_channels = (
        str(settings.get("ref_channel1") or settings.get("ref_ch1") or ""),
        str(settings.get("ref_channel2") or settings.get("ref_ch2") or ""),
    )
    picks = _scalp_picks(raw, stim_channel=stim_channel, ref_channels=ref_channels)
    n_channels = len(picks)
    thresholds = {
        "max_bad_channels": config.max_bad_channels,
        "max_bad_fraction": config.max_bad_fraction,
        "max_hemisphere_bad_fraction": config.max_hemisphere_bad_fraction,
        "min_channels_for_hard_qc": config.min_channels_for_hard_qc,
        "min_hemisphere_channels": config.min_hemisphere_channels,
        "min_bad_cluster_warning_size": config.min_bad_cluster_warning_size,
        "min_bad_cluster_size": config.min_bad_cluster_size,
        "neighbor_distance_factor": config.neighbor_distance_factor,
        "auto_detect_removed_electrodes": config.auto_detect_removed_electrodes,
        "spatial_predictability_experimental": bool(
            config.auto_detect_removed_electrodes and config.spatial_qc_enabled
        ),
        "bad_channel_cluster_experimental": bool(
            config.auto_detect_removed_electrodes
            or config.manual_removed_electrodes
        ),
        **removed_electrode_threshold_payload(config),
        "baseline_severe_review_median_std_uv": (
            config.baseline_exclusion_median_std_uv
        ),
        "baseline_severe_review_median_p2p_99_uv": (
            config.baseline_exclusion_median_p2p_99_uv
        ),
    }
    n_times = int(getattr(raw, "n_times", 0))
    if analysis_spans is None:
        scoring_scope = "legacy_sampled_windows"
        spans = tuple(_sample_spans(n_times, float(raw.info.get("sfreq", 0.0)), config))
    else:
        scoring_scope = "approved_analyzed_interval_union"
        spans = merge_relative_spans(analysis_spans, n_times=n_times)

    if n_channels == 0:
        return _empty_result(
            message=f"Raw channel QC skipped for {filename}: no scalp EEG channels found.",
            thresholds=thresholds,
            scoring_scope=scoring_scope,
            scoring_spans=spans,
        )
    if n_channels < config.min_channels_for_hard_qc:
        return _empty_result(
            message=(
                f"Raw channel QC skipped for {filename}: only {n_channels} scalp EEG channels "
                f"were found; hard QC requires at least {config.min_channels_for_hard_qc}."
            ),
            thresholds=thresholds,
            n_channels=n_channels,
            scoring_scope=scoring_scope,
            scoring_spans=spans,
        )

    if not spans:
        return RawChannelQCResult(
            excluded=True,
            reason=RAW_CHANNEL_QC_EXCLUSION_REASON,
            message=(
                f"{filename} could not be evaluated by raw channel-health QC: "
                "no analyzed EEG samples were available."
            ),
            n_channels=n_channels,
            n_bad_channels=0,
            bad_fraction=0.0,
            left_bad=0,
            left_total=0,
            right_bad=0,
            right_total=0,
            midline_bad=0,
            midline_total=0,
            bad_channels=(),
            channels_to_interpolate=(),
            manual_removed_channels=(),
            low_variance_channels=(),
            high_amplitude_channels=(),
            rare_burst_channels=(),
            spatial_outlier_channels=(),
            raw_baseline_median_std_uv=0.0,
            raw_baseline_median_p2p_99_uv=0.0,
            raw_baseline_warning=False,
            raw_baseline_excluded=False,
            largest_bad_cluster_size=0,
            largest_bad_cluster_channels=(),
            triggered_rules=("no_samples",),
            warning_rules=(),
            thresholds=thresholds,
            scoring_scope=scoring_scope,
            scoring_spans=spans,
            scoring_sample_count=0,
            review_only=False,
        )

    cluster_rules_enabled = (
        config.auto_detect_removed_electrodes
        or bool(config.manual_removed_electrodes)
    )
    spatial_predictability_enabled = (
        config.auto_detect_removed_electrodes and config.spatial_qc_enabled
    )
    if cluster_rules_enabled or spatial_predictability_enabled:
        # These geometry-dependent rules remain experimental pending
        # revalidation on external BioSemi64 datasets. A canonical geometry
        # gate prevents legacy or missing coordinates from changing their
        # neighborhoods silently.
        _validate_spatial_geometry(
            raw,
            [str(raw.ch_names[index]) for index in picks],
            settings,
        )

    chunks = [
        _safe_get_data(raw, picks=picks, start=start, stop=stop)
        for start, stop in spans
    ]
    data = np.concatenate(chunks, axis=1)

    channel_stats: list[_ChannelStats] = []
    left_total = right_total = midline_total = 0
    for row_index, raw_index in enumerate(picks):
        channel = str(raw.ch_names[raw_index])
        group = _channel_group(channel)
        if group == "left":
            left_total += 1
        elif group == "right":
            right_total += 1
        elif group == "midline":
            midline_total += 1

        (
            std_uv,
            p2p_99_uv,
            p2p_999_uv,
            full_p2p_uv,
        ) = _channel_metric_values(
            data[row_index]
        )
        channel_stats.append(
            _ChannelStats(
                channel=channel,
                group=group,
                std_uv=std_uv,
                p2p_99_uv=p2p_99_uv,
                p2p_999_uv=p2p_999_uv,
                full_p2p_uv=full_p2p_uv,
            )
        )

    median_std_uv = _robust_median([row.std_uv for row in channel_stats])
    median_p2p_99_uv = _robust_median([row.p2p_99_uv for row in channel_stats])
    raw_baseline_excluded = (
        median_std_uv >= config.baseline_exclusion_median_std_uv
        and median_p2p_99_uv >= config.baseline_exclusion_median_p2p_99_uv
    )
    raw_baseline_warning = (
        raw_baseline_excluded
        or median_std_uv >= config.baseline_warning_median_std_uv
        or median_p2p_99_uv >= config.baseline_warning_median_p2p_99_uv
    )
    raw_channel_names = {row.channel for row in channel_stats}
    manual_removed_channels = [
        channel
        for channel in config.manual_removed_electrodes
        if channel in raw_channel_names and channel in SCALP_CHANNELS
    ]

    low_variance_channels: list[str] = []
    if config.auto_detect_removed_electrodes:
        for row in channel_stats:
            is_bad = is_low_variance_removed_channel(
                std_uv=row.std_uv,
                p2p_99_uv=row.p2p_99_uv,
                median_std_uv=median_std_uv,
                median_p2p_99_uv=median_p2p_99_uv,
                calibration=config,
            )
            if not is_bad:
                continue

            low_variance_channels.append(row.channel)

    high_amplitude_channels: list[str] = []
    if config.auto_detect_removed_electrodes:
        low_lookup = set(low_variance_channels)
        for row in channel_stats:
            if row.channel in low_lookup:
                continue
            is_bad = is_high_amplitude_removed_channel(
                std_uv=row.std_uv,
                p2p_99_uv=row.p2p_99_uv,
                median_std_uv=median_std_uv,
                median_p2p_99_uv=median_p2p_99_uv,
                calibration=config,
            )
            if is_bad:
                high_amplitude_channels.append(row.channel)

    rare_burst_channels: list[str] = []
    if config.auto_detect_removed_electrodes:
        excluded_lookup = {*low_variance_channels, *high_amplitude_channels}
        std_rank = {
            row.channel: rank
            for rank, row in enumerate(
                sorted(channel_stats, key=lambda item: item.std_uv, reverse=True),
                start=1,
            )
        }
        for row in channel_stats:
            if row.channel in excluded_lookup:
                continue
            if row.std_uv < config.rare_burst_std_uv_floor:
                continue
            if std_rank.get(row.channel, n_channels + 1) > config.rare_burst_rank_limit:
                continue
            full_to_p2p_99 = (
                row.full_p2p_uv / row.p2p_99_uv
                if row.p2p_99_uv > 0.0
                else float("inf")
            )
            if (
                row.p2p_99_uv < config.rare_burst_p2p_99_uv_ceiling
                or full_to_p2p_99 >= config.rare_burst_full_to_p2p_99_ratio
                or (
                    row.p2p_999_uv >= config.rare_burst_p2p_999_uv_floor
                    and row.p2p_99_uv < config.rare_burst_p2p_99_uv_ceiling * 10.0
                )
            ):
                rare_burst_channels.append(row.channel)

    spatial_outlier_channels: list[str] = []
    if config.auto_detect_removed_electrodes and config.spatial_qc_enabled:
        channel_names = [row.channel for row in channel_stats]
        donor_exclusions = [
            *_raw_bads(raw),
            *low_variance_channels,
            *high_amplitude_channels,
            *rare_burst_channels,
        ]
        scores = _spatial_predictability_scores(
            raw,
            data,
            channel_names,
            donor_exclusions=donor_exclusions,
            config=config,
        )
        spatial_outlier_channels = list(
            _spatial_outlier_channels(
                scores,
                excluded_channels=donor_exclusions,
                config=config,
            )
        )

    candidate_sources = _candidate_source_map(
        [row.channel for row in channel_stats],
        manual_removed=manual_removed_channels,
        low_variance=low_variance_channels,
        high_amplitude=high_amplitude_channels,
        rare_burst=rare_burst_channels,
        spatial_predictability=spatial_outlier_channels,
        preexisting_raw_bad=(
            _raw_bads(raw) if cluster_rules_enabled else ()
        ),
    )
    candidate_channels = tuple(candidate_sources)
    channels_to_interpolate = tuple(
        dict.fromkeys(
            [
                *manual_removed_channels,
                *(
                    low_variance_channels
                    if config.auto_detect_removed_electrodes
                    else []
                ),
            ]
        )
    )
    burden = _candidate_burden(
        [row.channel for row in channel_stats],
        candidate_sources,
        positions=(
            _channel_positions(raw, [row.channel for row in channel_stats])
            if cluster_rules_enabled
            else {}
        ),
        config=config,
        cluster_rules_enabled=cluster_rules_enabled,
    )
    n_bad = int(burden["n_candidates"])
    bad_fraction = float(burden["candidate_fraction"])
    left_bad = len(burden["left_channels"])
    right_bad = len(burden["right_channels"])
    midline_bad = len(burden["midline_channels"])
    largest_cluster = tuple(burden["largest_cluster"])
    burden_findings = tuple(burden["findings"])

    review_rules = [str(finding["rule"]) for finding in burden_findings]
    if raw_baseline_excluded:
        review_rules.insert(0, "raw_amplitude_baseline_severe_review")
    elif raw_baseline_warning:
        review_rules.insert(0, "raw_amplitude_baseline_warning")
    warning_rules = list(review_rules)

    cluster_text = ""
    if largest_cluster:
        cluster_text = (
            f" Largest bad-channel cluster={len(largest_cluster)} "
            f"({', '.join(largest_cluster)})."
        )
    baseline_text = (
        f" Raw baseline median std={median_std_uv:.1f} uV, "
        f"median p2p99={median_p2p_99_uv:.1f} uV."
    )
    if raw_baseline_excluded:
        message = (
            f"Raw channel QC flagged {filename} for review: large raw signals "
            "were detected. Referencing may reduce shared electrical noise; "
            "review the evidence before excluding this recording."
            f"{baseline_text} {n_bad}/{n_channels} scalp EEG channels were "
            "low-amplitude, extreme high-amplitude, rare-burst, or spatially "
            f"inconsistent; left={left_bad}/{left_total}, "
            f"right={right_bad}/{right_total}, midline={midline_bad}/{midline_total}."
            f"{cluster_text} Review rule(s): {', '.join(review_rules)}."
        )
    elif burden_findings:
        message = (
            f"Raw channel QC flagged {filename} for review: {n_bad}/{n_channels} scalp EEG "
            "channels were low-amplitude, extreme high-amplitude, rare-burst, or spatially "
            f"inconsistent; left={left_bad}/{left_total}, "
            f"right={right_bad}/{right_total}, midline={midline_bad}/{midline_total}."
            f"{cluster_text} Review rule(s): {', '.join(review_rules)}."
        )
    elif channels_to_interpolate:
        message = (
            f"Raw channel QC passed for {filename}: auto-marking "
            f"{len(channels_to_interpolate)} low-variance raw-QC channel(s) for interpolation "
            f"({', '.join(channels_to_interpolate)}).{cluster_text}"
        )
        if warning_rules:
            message += f"{baseline_text} Warning rule(s): {', '.join(warning_rules)}."
    else:
        message = (
            f"Raw channel QC passed for {filename}: {n_bad}/{n_channels} scalp EEG channels "
            "were low-amplitude, extreme high-amplitude, rare-burst, or spatially inconsistent."
        )
        if warning_rules:
            message += f"{cluster_text}{baseline_text} Warning rule(s): {', '.join(warning_rules)}."

    return RawChannelQCResult(
        excluded=False,
        reason=None,
        message=message,
        n_channels=n_channels,
        n_bad_channels=n_bad,
        bad_fraction=bad_fraction,
        left_bad=left_bad,
        left_total=left_total,
        right_bad=right_bad,
        right_total=right_total,
        midline_bad=midline_bad,
        midline_total=midline_total,
        bad_channels=tuple(candidate_channels),
        channels_to_interpolate=channels_to_interpolate,
        manual_removed_channels=tuple(manual_removed_channels),
        low_variance_channels=tuple(low_variance_channels),
        high_amplitude_channels=tuple(high_amplitude_channels),
        rare_burst_channels=tuple(rare_burst_channels),
        spatial_outlier_channels=tuple(spatial_outlier_channels),
        raw_baseline_median_std_uv=median_std_uv,
        raw_baseline_median_p2p_99_uv=median_p2p_99_uv,
        raw_baseline_warning=raw_baseline_warning,
        raw_baseline_excluded=False,
        largest_bad_cluster_size=len(largest_cluster),
        largest_bad_cluster_channels=tuple(largest_cluster),
        triggered_rules=(),
        warning_rules=tuple(warning_rules),
        thresholds=thresholds,
        scoring_scope=scoring_scope,
        scoring_spans=spans,
        scoring_sample_count=sum(stop - start for start, stop in spans),
        review_rules=tuple(review_rules),
        candidate_sources=candidate_sources,
        burden_findings=burden_findings,
        raw_baseline_severe_review=raw_baseline_excluded,
    )


@dataclass(frozen=True)
class _V2Classification:
    low_variance_channels: tuple[str, ...]
    high_amplitude_channels: tuple[str, ...]
    rare_burst_channels: tuple[str, ...]
    median_std_uv: float
    median_p2p_99_uv: float
    baseline_warning: bool
    baseline_failure_review: bool


def _ordered_channel_union(
    channel_names: Sequence[str],
    *groups: Sequence[str],
) -> tuple[str, ...]:
    selected = {str(channel) for group in groups for channel in group}
    return tuple(str(channel) for channel in channel_names if str(channel) in selected)


def _v2_thresholds(config: RawChannelQCConfig) -> dict[str, float | int | bool]:
    return {
        "max_bad_channels": config.max_bad_channels,
        "max_bad_fraction": config.max_bad_fraction,
        "max_hemisphere_bad_fraction": config.max_hemisphere_bad_fraction,
        "min_channels_for_hard_qc": config.min_channels_for_hard_qc,
        "min_hemisphere_channels": config.min_hemisphere_channels,
        "min_bad_cluster_warning_size": config.min_bad_cluster_warning_size,
        "min_bad_cluster_size": config.min_bad_cluster_size,
        "neighbor_distance_factor": config.neighbor_distance_factor,
        "auto_detect_removed_electrodes": config.auto_detect_removed_electrodes,
        "spatial_predictability_experimental": bool(
            config.auto_detect_removed_electrodes and config.spatial_qc_enabled
        ),
        "bad_channel_cluster_experimental": bool(
            config.auto_detect_removed_electrodes
            or config.manual_removed_electrodes
        ),
        "review_only": True,
        **removed_electrode_threshold_payload(config),
    }


def _v2_channel_metrics(channel: str, values: np.ndarray) -> RawChannelMetricSet:
    """Apply the v1 float64 formulas with one vectorized percentile call."""

    values64 = np.asarray(values, dtype=np.float64)
    percentiles = np.nanpercentile(values64, [0.05, 0.5, 99.5, 99.95])
    return RawChannelMetricSet(
        channel=channel,
        std_uv=float(np.nanstd(values64) * 1e6),
        p2p_99_uv=float((percentiles[2] - percentiles[1]) * 1e6),
        p2p_999_uv=float((percentiles[3] - percentiles[0]) * 1e6),
        full_p2p_uv=float(
            (np.nanmax(values64) - np.nanmin(values64)) * 1e6
        ),
    )


def _v2_metric_rows(
    data: np.ndarray,
    channel_names: Sequence[str],
) -> tuple[RawChannelMetricSet, ...]:
    # Batch ordinary diagnostic windows, but keep full-occurrence scratch
    # bounded. Contiguous samples within each row preserve NumPy's existing
    # reduction order; column-major/other layouts retain the row formulas.
    if (
        data.ndim == 2
        and data.dtype == np.dtype(np.float64)
        and data.shape[0] == len(channel_names)
        and data.shape[0] > 1
        and data.shape[1] > 0
        and data.nbytes <= 8 * 1024 * 1024
        and data.strides[1] == data.itemsize
        and data.strides[0] >= data.shape[1] * data.itemsize
        and bool(np.isfinite(data).all())
    ):
        percentiles = np.percentile(data, [0.05, 0.5, 99.5, 99.95], axis=1)
        std_uv = np.nanstd(data, axis=1) * 1e6
        p2p_99_uv = (percentiles[2] - percentiles[1]) * 1e6
        p2p_999_uv = (percentiles[3] - percentiles[0]) * 1e6
        full_p2p_uv = (np.nanmax(data, axis=1) - np.nanmin(data, axis=1)) * 1e6
        return tuple(
            RawChannelMetricSet(
                channel=str(channel),
                std_uv=float(std_uv[row_index]),
                p2p_99_uv=float(p2p_99_uv[row_index]),
                p2p_999_uv=float(p2p_999_uv[row_index]),
                full_p2p_uv=float(full_p2p_uv[row_index]),
            )
            for row_index, channel in enumerate(channel_names)
        )
    return tuple(
        _v2_channel_metrics(str(channel), data[row_index])
        for row_index, channel in enumerate(channel_names)
    )


def _classify_v2_metrics(
    rows: Sequence[RawChannelMetricSet],
    config: RawChannelQCConfig,
) -> _V2Classification:
    median_std_uv = _robust_median([row.std_uv for row in rows])
    median_p2p_99_uv = _robust_median([row.p2p_99_uv for row in rows])
    baseline_failure_review = (
        median_std_uv >= config.baseline_exclusion_median_std_uv
        and median_p2p_99_uv >= config.baseline_exclusion_median_p2p_99_uv
    )
    baseline_warning = (
        baseline_failure_review
        or median_std_uv >= config.baseline_warning_median_std_uv
        or median_p2p_99_uv >= config.baseline_warning_median_p2p_99_uv
    )

    low_variance: list[str] = []
    if config.auto_detect_removed_electrodes:
        for row in rows:
            if is_low_variance_removed_channel(
                std_uv=row.std_uv,
                p2p_99_uv=row.p2p_99_uv,
                median_std_uv=median_std_uv,
                median_p2p_99_uv=median_p2p_99_uv,
                calibration=config,
            ):
                low_variance.append(row.channel)

    high_amplitude: list[str] = []
    if config.auto_detect_removed_electrodes:
        low_lookup = set(low_variance)
        for row in rows:
            if row.channel in low_lookup:
                continue
            if is_high_amplitude_removed_channel(
                std_uv=row.std_uv,
                p2p_99_uv=row.p2p_99_uv,
                median_std_uv=median_std_uv,
                median_p2p_99_uv=median_p2p_99_uv,
                calibration=config,
            ):
                high_amplitude.append(row.channel)

    rare_burst: list[str] = []
    if config.auto_detect_removed_electrodes:
        excluded_lookup = {*low_variance, *high_amplitude}
        std_rank = {
            row.channel: rank
            for rank, row in enumerate(
                sorted(rows, key=lambda item: item.std_uv, reverse=True),
                start=1,
            )
        }
        for row in rows:
            if row.channel in excluded_lookup:
                continue
            if row.std_uv < config.rare_burst_std_uv_floor:
                continue
            if std_rank.get(row.channel, len(rows) + 1) > config.rare_burst_rank_limit:
                continue
            full_to_p2p_99 = (
                row.full_p2p_uv / row.p2p_99_uv
                if row.p2p_99_uv > 0.0
                else float("inf")
            )
            if (
                row.p2p_99_uv < config.rare_burst_p2p_99_uv_ceiling
                or full_to_p2p_99 >= config.rare_burst_full_to_p2p_99_ratio
                or (
                    row.p2p_999_uv >= config.rare_burst_p2p_999_uv_floor
                    and row.p2p_99_uv < config.rare_burst_p2p_99_uv_ceiling * 10.0
                )
            ):
                rare_burst.append(row.channel)

    return _V2Classification(
        low_variance_channels=tuple(low_variance),
        high_amplitude_channels=tuple(high_amplitude),
        rare_burst_channels=tuple(rare_burst),
        median_std_uv=median_std_uv,
        median_p2p_99_uv=median_p2p_99_uv,
        baseline_warning=baseline_warning,
        baseline_failure_review=baseline_failure_review,
    )


def _finite_for_min(value: float) -> float:
    return float(value) if np.isfinite(value) else float("inf")


def _finite_for_descending(value: float) -> float:
    return -float(value) if np.isfinite(value) else float("inf")


def _block_tie_key(item: RawChannelBlockMetrics) -> tuple[int, str, int, int]:
    return (
        item.start_sample,
        item.condition_id.casefold(),
        item.occurrence,
        item.block_index,
    )


def _lowest_variance_key(item: RawChannelBlockMetrics) -> tuple[object, ...]:
    return (
        _finite_for_min(item.metrics.std_uv),
        _finite_for_min(item.metrics.p2p_99_uv),
        *_block_tie_key(item),
    )


def _highest_amplitude_key(item: RawChannelBlockMetrics) -> tuple[object, ...]:
    return (
        _finite_for_descending(item.metrics.full_p2p_uv),
        _finite_for_descending(item.metrics.p2p_999_uv),
        _finite_for_descending(item.metrics.p2p_99_uv),
        _finite_for_descending(item.metrics.std_uv),
        *_block_tie_key(item),
    )


def _transient_extrema(
    block_rows: Sequence[RawChannelBlockMetrics],
    channel_names: Sequence[str],
) -> tuple[RawChannelTransientExtrema, ...]:
    by_channel: dict[str, list[RawChannelBlockMetrics]] = {
        str(channel): [] for channel in channel_names
    }
    for row in block_rows:
        by_channel.setdefault(row.metrics.channel, []).append(row)

    extrema: list[RawChannelTransientExtrema] = []
    for channel in channel_names:
        candidates = by_channel.get(str(channel), [])
        if not candidates:
            continue
        extrema.append(
            RawChannelTransientExtrema(
                channel=str(channel),
                lowest_variance_block=min(candidates, key=_lowest_variance_key),
                highest_amplitude_block=min(candidates, key=_highest_amplitude_key),
            )
        )
    return tuple(extrema)


_OCCURRENCE_CATEGORY_FIELDS = (
    ("low_variance_channels", "low_variance"),
    ("high_amplitude_channels", "high_amplitude"),
    ("rare_burst_channels", "rare_burst"),
    ("spatial_outlier_channels", "spatial_predictability"),
)


def _occurrence_review_findings(
    conditions: Sequence[RawChannelConditionAggregate],
    channel_names: Sequence[str],
) -> tuple[Mapping[str, object], ...]:
    """Explain exactly where full-occurrence channel flags did and did not recur."""

    evaluated_count = len(conditions)
    by_channel: dict[
        str, list[tuple[RawChannelConditionAggregate, tuple[str, ...]]]
    ] = {str(channel): [] for channel in channel_names}
    for condition in conditions:
        for channel in channel_names:
            categories = tuple(
                category
                for field_name, category in _OCCURRENCE_CATEGORY_FIELDS
                if channel in getattr(condition, field_name)
            )
            if categories:
                by_channel[str(channel)].append((condition, categories))

    findings: list[Mapping[str, object]] = []
    for channel in channel_names:
        flagged = by_channel.get(str(channel), [])
        flagged_count = len(flagged)
        if not flagged_count:
            continue
        all_flagged = flagged_count == evaluated_count
        common_categories = set(flagged[0][1])
        for _condition, categories in flagged[1:]:
            common_categories.intersection_update(categories)
        persistent_categories = (
            tuple(sorted(common_categories)) if all_flagged else ()
        )
        same_category_persistent = all_flagged and bool(persistent_categories)
        reason_varied = all_flagged and not same_category_persistent
        for condition, categories in flagged:
            location = (
                f"{condition.condition_id}, occurrence {condition.occurrence + 1}"
            )
            if evaluated_count == 1:
                statement = (
                    f"{channel} was flagged as potentially bad in {location} "
                    "(the only evaluated occurrence)."
                )
            elif flagged_count == 1:
                others = evaluated_count - 1
                statement = (
                    f"{channel} was flagged as potentially bad in {location} only. "
                    f"It was not flagged in the other {others} evaluated "
                    f"occurrence{'s' if others != 1 else ''}."
                )
            elif same_category_persistent:
                statement = (
                    f"{channel} was flagged as potentially bad in {location} and "
                    f"in all {evaluated_count} evaluated occurrences for at least "
                    f"one same reason ({', '.join(persistent_categories)})."
                )
            elif reason_varied:
                statement = (
                    f"{channel} was flagged as potentially bad in {location}. Every "
                    "evaluated occurrence was flagged, but the reason varied."
                )
            else:
                statement = (
                    f"{channel} was flagged as potentially bad in {location}. It was "
                    f"flagged in {flagged_count} of {evaluated_count} evaluated occurrences."
                )
            findings.append(
                {
                    "channel": str(channel),
                    "condition_label": condition.condition_id,
                    "occurrence": condition.occurrence,
                    "occurrence_display": condition.occurrence + 1,
                    "categories": list(categories),
                    "start_sample": condition.start_sample,
                    "stop_sample": condition.stop_sample,
                    "sample_count": condition.n_samples,
                    "evaluated_occurrence_count": evaluated_count,
                    "flagged_occurrence_count": flagged_count,
                    "same_category_persistent": same_category_persistent,
                    "persistent_categories": list(persistent_categories),
                    "all_evaluated_occurrences_flagged": all_flagged,
                    "reason_varied": reason_varied,
                    "statement": statement,
                    "authority": "review_only",
                }
            )
    return tuple(findings)


def _merged_window_spans(
    windows: Sequence[RawChannelBlockMetrics | RawAmplitudeWindowMetrics],
) -> tuple[tuple[int, int], ...]:
    spans = sorted((window.start_sample, window.stop_sample) for window in windows)
    merged: list[list[int]] = []
    for start, stop in spans:
        if not merged or start > merged[-1][1]:
            merged.append([start, stop])
        else:
            merged[-1][1] = max(merged[-1][1], stop)
    return tuple((start, stop) for start, stop in merged)


def _transient_review_findings(
    block_rows: Sequence[RawChannelBlockMetrics],
) -> tuple[Mapping[str, object], ...]:
    grouped: dict[tuple[str, str, int, str], list[RawChannelBlockMetrics]] = {}
    for row in block_rows:
        for category in row.review_categories:
            grouped.setdefault(
                (row.metrics.channel, row.condition_id, row.occurrence, category),
                [],
            ).append(row)

    findings: list[Mapping[str, object]] = []
    for (channel, condition, occurrence, category), windows in sorted(
        grouped.items(),
        key=lambda item: (
            min(window.start_sample for window in item[1]),
            item[0],
        ),
    ):
        ordered_windows = sorted(windows, key=_block_tie_key)
        union_spans = _merged_window_spans(ordered_windows)
        union_samples = sum(stop - start for start, stop in union_spans)
        findings.append(
            {
                "channel": channel,
                "condition_label": condition,
                "occurrence": occurrence,
                "occurrence_display": occurrence + 1,
                "category": category,
                "diagnostic_window_count": len(ordered_windows),
                "windows": [window.to_payload() for window in ordered_windows],
                "flagged_window_union_spans": [list(span) for span in union_spans],
                "flagged_window_coverage_samples": union_samples,
                "coverage_meaning": "flagged_window_coverage_not_artifact_duration",
                "authority": "review_only",
            }
        )
    return tuple(findings)


def _transient_amplitude_review_findings(
    rows: Sequence[RawAmplitudeWindowMetrics],
) -> tuple[Mapping[str, object], ...]:
    """Group overlapping cap-wide amplitude windows as review provenance."""

    grouped: dict[tuple[str, int], list[RawAmplitudeWindowMetrics]] = {}
    for row in rows:
        grouped.setdefault((row.condition_id, row.occurrence), []).append(row)

    findings: list[Mapping[str, object]] = []
    for (condition, occurrence), windows in sorted(
        grouped.items(),
        key=lambda item: (
            min(window.start_sample for window in item[1]),
            item[0],
        ),
    ):
        ordered = sorted(windows, key=lambda item: (item.start_sample, item.stop_sample))
        union_spans = _merged_window_spans(ordered)
        peak = max(
            ordered,
            key=lambda item: (
                item.severe_review,
                item.median_std_uv,
                item.median_p2p_99_uv,
                -item.start_sample,
            ),
        )
        findings.append(
            {
                "scope": "overlapping_diagnostic_window_union",
                "condition_label": condition,
                "occurrence": occurrence,
                "occurrence_display": occurrence + 1,
                "severity": (
                    "severe_review"
                    if any(window.severe_review for window in ordered)
                    else "warning_review"
                ),
                "median_std_uv": peak.median_std_uv,
                "median_p2p_99_uv": peak.median_p2p_99_uv,
                "diagnostic_window_count": len(ordered),
                "windows": [window.to_payload() for window in ordered],
                "flagged_window_union_spans": [list(span) for span in union_spans],
                "flagged_window_coverage_samples": sum(
                    stop - start for start, stop in union_spans
                ),
                "coverage_meaning": "flagged_window_coverage_not_artifact_duration",
                "authority": "review_only",
                "help_text": SEVERE_RAW_AMPLITUDE_HELP_TEXT,
                "help_url": BIOSEMI_SHARED_NOISE_HELP_URL,
            }
        )
    return tuple(findings)


def _review_rules(
    conditions: Sequence[RawChannelConditionAggregate],
) -> tuple[str, ...]:
    rules: list[str] = []
    persistent_checks = (
        ("low_variance_channels", "condition_persistent_low_variance_review"),
        ("high_amplitude_channels", "condition_persistent_high_amplitude_review"),
        ("rare_burst_channels", "condition_persistent_rare_burst_review"),
        ("spatial_outlier_channels", "condition_persistent_spatial_review"),
    )
    transient_checks = (
        ("transient_high_amplitude_channels", "condition_transient_high_amplitude_review"),
        ("transient_rare_burst_channels", "condition_transient_rare_burst_review"),
    )
    for field_name, rule in persistent_checks:
        if conditions and set.intersection(
            *(set(getattr(condition, field_name)) for condition in conditions)
        ):
            rules.append(rule)
    if any(
        getattr(condition, field_name)
        for condition in conditions
        for field_name, _category in _OCCURRENCE_CATEGORY_FIELDS
    ):
        rules.append("condition_occurrence_channel_review")
    for field_name, rule in transient_checks:
        if any(getattr(condition, field_name) for condition in conditions):
            rules.append(rule)
    if any(condition.raw_baseline_failure_review for condition in conditions):
        rules.append("condition_amplitude_baseline_failure_review")
    elif any(condition.raw_baseline_warning for condition in conditions):
        rules.append("condition_amplitude_baseline_warning")
    return tuple(rules)


def _condition_result(
    *,
    filename: str,
    channel_names: tuple[str, ...],
    conditions: Sequence[RawChannelConditionAggregate],
    block_rows: Sequence[RawChannelBlockMetrics],
    manual_removed_channels: tuple[str, ...],
    thresholds: Mapping[str, float | int | bool],
    config: RawChannelQCConfig,
    inherited_transient_findings: Sequence[Mapping[str, object]] | None = None,
    transient_amplitude_findings: Sequence[Mapping[str, object]] = (),
    transient_windowing: Mapping[str, object] | None = None,
) -> ConditionRawChannelQCResult:
    ordered_conditions = tuple(
        sorted(
            conditions,
            key=lambda item: (
                item.start_sample,
                item.condition_id.casefold(),
                item.occurrence,
            ),
        )
    )
    def persistent(field_name: str) -> tuple[str, ...]:
        if not ordered_conditions:
            return ()
        selected = set(getattr(ordered_conditions[0], field_name))
        for condition in ordered_conditions[1:]:
            selected.intersection_update(getattr(condition, field_name))
        return tuple(channel for channel in channel_names if channel in selected)

    candidate_sources = _candidate_source_map(
        channel_names,
        manual_removed=manual_removed_channels,
        persistent_low_variance=persistent("low_variance_channels"),
        persistent_high_amplitude=persistent("high_amplitude_channels"),
        persistent_rare_burst=persistent("rare_burst_channels"),
        persistent_spatial_predictability=persistent("spatial_outlier_channels"),
    )
    cluster_rules_enabled = (
        config.auto_detect_removed_electrodes
        or bool(config.manual_removed_electrodes)
    )
    burden = _candidate_burden(
        channel_names,
        candidate_sources,
        positions=canonical_biosemi64_head_coordinates(),
        config=config,
        cluster_rules_enabled=cluster_rules_enabled,
    )
    burden_findings = tuple(burden["findings"])
    review_rules = list(_review_rules(ordered_conditions))
    review_rules.extend(str(finding["rule"]) for finding in burden_findings)
    if any(
        str(finding.get("severity") or "") == "severe_review"
        for finding in transient_amplitude_findings
    ):
        review_rules.append("condition_transient_amplitude_baseline_severe_review")
    elif transient_amplitude_findings:
        review_rules.append("condition_transient_amplitude_baseline_warning")
    transient_findings = (
        tuple(inherited_transient_findings)
        if inherited_transient_findings is not None
        else _transient_review_findings(block_rows)
    )
    return ConditionRawChannelQCResult(
        filename=filename,
        channel_names=channel_names,
        conditions=ordered_conditions,
        transient_extrema=_transient_extrema(block_rows, channel_names),
        manual_removed_channels=manual_removed_channels,
        thresholds=dict(thresholds),
        review_rules=tuple(dict.fromkeys(review_rules)),
        candidate_sources=candidate_sources,
        burden_findings=burden_findings,
        largest_bad_cluster_channels=tuple(burden["largest_cluster"]),
        occurrence_review_findings=_occurrence_review_findings(
            ordered_conditions,
            channel_names,
        ),
        transient_review_findings=transient_findings,
        transient_amplitude_review_findings=tuple(transient_amplitude_findings),
        transient_windowing=dict(transient_windowing or {}),
    )


def _root_array(value: np.ndarray) -> np.ndarray:
    root = value
    seen: set[int] = set()
    while isinstance(getattr(root, "base", None), np.ndarray):
        if id(root) in seen:
            break
        seen.add(id(root))
        root = root.base
    return root


def _shared_full_condition_view(
    chunks: Sequence[np.ndarray],
) -> np.ndarray | None:
    """Recover a shared full-condition backing array without concatenating."""

    if not chunks:
        return None
    root = _root_array(chunks[0])
    if root.ndim != 2 or any(_root_array(chunk) is not root for chunk in chunks[1:]):
        return None
    if root.shape[0] != chunks[0].shape[0]:
        return None
    return np.asarray(root, dtype=np.float64)


def _assemble_unique_condition_data(
    chunks: Sequence[np.ndarray],
    starts: Sequence[int],
    *,
    occurrence_start: int,
    occurrence_stop: int,
) -> np.ndarray:
    """Rebuild unique occurrence samples without counting overlap twice."""

    if not chunks or len(chunks) != len(starts):
        raise ValueError("condition windows and sample starts must be non-empty and aligned")
    n_samples = int(occurrence_stop) - int(occurrence_start)
    assembled = np.empty((chunks[0].shape[0], n_samples), dtype=np.float64)
    covered = np.zeros(n_samples, dtype=bool)
    for chunk, start in zip(chunks, starts, strict=True):
        local_start = int(start) - int(occurrence_start)
        local_stop = local_start + int(chunk.shape[1])
        if local_start < 0 or local_stop > n_samples:
            raise ValueError("condition window lies outside its occurrence bounds")
        existing = covered[local_start:local_stop]
        if existing.any() and not np.array_equal(
            assembled[:, local_start:local_stop][:, existing],
            chunk[:, existing],
            equal_nan=True,
        ):
            raise ValueError("overlapping condition windows contain different samples")
        assembled[:, local_start:local_stop] = chunk
        covered[local_start:local_stop] = True
    if not bool(covered.all()):
        raise ValueError("condition windows do not cover every occurrence sample")
    return assembled


def evaluate_condition_raw_channel_qc_v2(
    blocks: Iterable[ConditionRawChannelQCBlock],
    channel_names: Sequence[str],
    settings: Mapping[str, Any],
    *,
    filename: str,
    sfreq: float,
    block_duration_s: float = 10.0,
    window_hop_s: float | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> ConditionRawChannelQCResult:
    """Evaluate every supplied condition sample without retaining a full recording.

    Windows for an occurrence must cover it without gaps and end with
    ``is_final=True``. Overlap contributes only to transient diagnostics; exact
    full-occurrence metrics count every analyzed sample once.
    Exact aggregate percentiles require retaining only the current occurrence's
    blocks; they are discarded as soon as that occurrence is finalized. Review
    thresholds intentionally never set ``excluded`` or interpolation candidates.
    """

    sfreq_value = float(sfreq)
    duration_value = float(block_duration_s)
    if not np.isfinite(sfreq_value) or sfreq_value <= 0.0:
        raise ValueError("sfreq must be a positive finite value")
    if not np.isfinite(duration_value) or duration_value <= 0.0:
        raise ValueError("block_duration_s must be a positive finite value")
    full_block_samples = max(1, int(round(sfreq_value * duration_value)))
    hop_value = duration_value if window_hop_s is None else float(window_hop_s)
    if not np.isfinite(hop_value) or hop_value <= 0.0:
        raise ValueError("window_hop_s must be a positive finite value")
    hop_samples = max(1, int(round(sfreq_value * hop_value)))
    if hop_samples > full_block_samples:
        raise ValueError("window_hop_s cannot leave gaps between diagnostic windows")

    source_channel_names = tuple(str(channel) for channel in channel_names)
    if len(set(source_channel_names)) != len(source_channel_names):
        raise ValueError("channel_names must be unique")
    stim_channel = str(settings.get("stim_channel") or "")
    ref_channels = {
        str(settings.get("ref_channel1") or settings.get("ref_ch1") or ""),
        str(settings.get("ref_channel2") or settings.get("ref_ch2") or ""),
    }
    picks = tuple(
        index
        for index, channel in enumerate(source_channel_names)
        if channel in SCALP_CHANNELS and channel != stim_channel and channel not in ref_channels
    )
    scalp_names = tuple(source_channel_names[index] for index in picks)
    if not scalp_names:
        raise ValueError("condition-aware raw channel QC requires at least one scalp EEG channel")

    config = _config_from_settings(settings)
    manual_removed = tuple(
        channel
        for channel in config.manual_removed_electrodes
        if channel in scalp_names
    )
    conditions: list[RawChannelConditionAggregate] = []
    all_block_rows: list[RawChannelBlockMetrics] = []
    seen_occurrences: set[tuple[str, int]] = set()
    current_key: tuple[str, int] | None = None
    current_start = 0
    current_stop = 0
    current_chunks: list[np.ndarray] = []
    current_window_starts: list[int] = []
    current_block_rows: list[RawChannelBlockMetrics] = []
    current_amplitude_window_rows: list[RawAmplitudeWindowMetrics] = []
    all_amplitude_window_rows: list[RawAmplitudeWindowMetrics] = []
    transient_low: set[str] = set()
    transient_high: set[str] = set()
    transient_rare: set[str] = set()

    def finalize_current() -> None:
        nonlocal current_key
        if current_key is None:
            return
        aggregate_data = current_chunks[0]
        if len(current_chunks) > 1:
            aggregate_data = _shared_full_condition_view(current_chunks)
            if (
                aggregate_data is None
                or aggregate_data.shape[1] != current_stop - current_start
            ):
                aggregate_data = _assemble_unique_condition_data(
                    current_chunks,
                    current_window_starts,
                    occurrence_start=current_start,
                    occurrence_stop=current_stop,
                )
        aggregate_rows = _v2_metric_rows(aggregate_data, scalp_names)
        aggregate_classification = _classify_v2_metrics(aggregate_rows, config)
        spatial_outliers: tuple[str, ...] = ()
        if config.auto_detect_removed_electrodes and config.spatial_qc_enabled:
            donor_exclusions = _ordered_channel_union(
                scalp_names,
                manual_removed,
                aggregate_classification.low_variance_channels,
                aggregate_classification.high_amplitude_channels,
                aggregate_classification.rare_burst_channels,
            )
            canonical_positions = canonical_biosemi64_head_coordinates()
            neighbor_map = _spatial_neighbor_map_from_positions(
                canonical_positions,
                scalp_names,
                config=config,
            )
            scores = _spatial_predictability_scores_with_neighbors(
                aggregate_data,
                scalp_names,
                neighbor_map=neighbor_map,
                donor_exclusions=donor_exclusions,
                config=config,
            )
            spatial_outliers = _spatial_outlier_channels(
                scores,
                excluded_channels=donor_exclusions,
                config=config,
            )
        conditions.append(
            RawChannelConditionAggregate(
                condition_id=current_key[0],
                occurrence=current_key[1],
                start_sample=current_start,
                stop_sample=current_stop,
                n_blocks=len(current_chunks),
                channel_metrics=aggregate_rows,
                low_variance_channels=aggregate_classification.low_variance_channels,
                high_amplitude_channels=aggregate_classification.high_amplitude_channels,
                rare_burst_channels=aggregate_classification.rare_burst_channels,
                spatial_outlier_channels=spatial_outliers,
                transient_low_variance_channels=_ordered_channel_union(
                    scalp_names, tuple(transient_low)
                ),
                transient_high_amplitude_channels=_ordered_channel_union(
                    scalp_names, tuple(transient_high)
                ),
                transient_rare_burst_channels=_ordered_channel_union(
                    scalp_names, tuple(transient_rare)
                ),
                raw_baseline_median_std_uv=aggregate_classification.median_std_uv,
                raw_baseline_median_p2p_99_uv=aggregate_classification.median_p2p_99_uv,
                raw_baseline_warning=aggregate_classification.baseline_warning,
                raw_baseline_failure_review=aggregate_classification.baseline_failure_review,
            )
        )
        all_block_rows.extend(current_block_rows)
        # A lone short/exact window is identical to the full-occurrence
        # aggregate already reported above. Multi-window occurrences retain
        # bounded amplitude evidence so a brief cap-wide burst is not diluted
        # out of the occurrence aggregate.
        if len(current_chunks) > 1:
            all_amplitude_window_rows.extend(current_amplitude_window_rows)
        seen_occurrences.add(current_key)
        current_key = None
        current_chunks.clear()
        current_window_starts.clear()
        current_block_rows.clear()
        current_amplitude_window_rows.clear()
        transient_low.clear()
        transient_high.clear()
        transient_rare.clear()

    iterator = iter(blocks)
    while True:
        if should_cancel is not None and should_cancel():
            raise ConditionRawChannelQCCancelled(
                "Condition-aware raw channel QC was cancelled between blocks."
            )
        try:
            block = next(iterator)
        except StopIteration:
            break
        if not isinstance(block, ConditionRawChannelQCBlock):
            raise TypeError("blocks must contain ConditionRawChannelQCBlock instances")

        condition_id = str(block.condition_id).strip()
        occurrence = int(block.occurrence)
        key = (condition_id, occurrence)
        if not condition_id:
            raise ValueError("condition_id must not be empty")
        if occurrence < 0:
            raise ValueError("occurrence must be zero or greater")
        if key in seen_occurrences:
            raise ValueError(f"condition occurrence {key!r} was supplied more than once")
        if current_key is not None and key != current_key:
            raise ValueError(f"condition occurrence {current_key!r} ended without a final block")

        data = np.asarray(block.data, dtype=np.float64)
        if data.ndim != 2:
            raise ValueError("each condition block must be a two-dimensional channel-by-sample array")
        if data.shape[0] != len(source_channel_names):
            raise ValueError(
                "condition block channel count does not match channel_names "
                f"({data.shape[0]} != {len(source_channel_names)})"
            )
        start_sample = int(block.start_sample)
        stop_sample = int(block.stop_sample)
        n_samples = stop_sample - start_sample
        if start_sample < 0 or n_samples <= 0 or data.shape[1] != n_samples:
            raise ValueError("condition block provenance must exactly match its positive sample count")
        window_kind = str(block.window_kind or "regular")
        if window_kind not in {"regular", "tail_aligned", "short"}:
            raise ValueError(f"unsupported condition-window kind {window_kind!r}")
        if n_samples > full_block_samples:
            raise ValueError("a condition window cannot exceed the configured window size")
        if not block.is_final and n_samples != full_block_samples:
            raise ValueError("each non-final condition window must equal the configured window size")
        if window_kind in {"tail_aligned", "short"} and not block.is_final:
            raise ValueError(f"a {window_kind} condition window must be final")
        if window_kind == "tail_aligned" and n_samples != full_block_samples:
            raise ValueError("a tail-aligned condition window must be full length")
        if window_kind == "short" and n_samples >= full_block_samples:
            raise ValueError("a short condition window must be shorter than the nominal window")

        if current_key is None:
            current_key = key
            current_start = start_sample
            current_stop = stop_sample
        else:
            previous_start = current_window_starts[-1]
            expected_start = previous_start + hop_samples
            if start_sample <= previous_start or start_sample > current_stop:
                raise ValueError(
                    f"condition occurrence {key!r} has invalid window coverage before sample {start_sample}"
                )
            if window_kind == "tail_aligned":
                if start_sample > expected_start:
                    raise ValueError("tail-aligned condition window leaves a gap")
            elif start_sample != expected_start:
                raise ValueError(
                    f"condition occurrence {key!r} has an unexpected window hop before sample {start_sample}"
                )

        if picks == tuple(range(len(source_channel_names))):
            selected = data
        else:
            selected = data[np.asarray(picks, dtype=int)]
        block_index = len(current_chunks)
        block_metric_rows = _v2_metric_rows(selected, scalp_names)
        classification = _classify_v2_metrics(block_metric_rows, config)
        if classification.baseline_warning:
            current_amplitude_window_rows.append(
                RawAmplitudeWindowMetrics(
                    condition_id=condition_id,
                    occurrence=occurrence,
                    start_sample=start_sample,
                    stop_sample=stop_sample,
                    sampling_rate_hz=sfreq_value,
                    window_kind=window_kind,
                    median_std_uv=classification.median_std_uv,
                    median_p2p_99_uv=classification.median_p2p_99_uv,
                    severe_review=classification.baseline_failure_review,
                )
            )
        # A relative low-variance classification is calibrated for persistent
        # multi-window data, not a single 5-second diagnostic window. Preserve
        # each channel's quietest-block metrics below, but do not turn an isolated
        # quiet block into a removed-electrode review flag.
        transient_high.update(classification.high_amplitude_channels)
        transient_rare.update(classification.rare_burst_channels)
        current_block_rows.extend(
            RawChannelBlockMetrics(
                condition_id=condition_id,
                occurrence=occurrence,
                block_index=block_index,
                start_sample=start_sample,
                stop_sample=stop_sample,
                metrics=row,
                sampling_rate_hz=sfreq_value,
                window_kind=window_kind,
                review_categories=tuple(
                    category
                    for category, channels in (
                        ("high_amplitude", classification.high_amplitude_channels),
                        ("rare_burst", classification.rare_burst_channels),
                    )
                    if row.channel in channels
                ),
            )
            for row in block_metric_rows
        )
        current_chunks.append(selected)
        current_window_starts.append(start_sample)
        current_stop = max(current_stop, stop_sample)

        if block.is_final:
            finalize_current()

    if current_key is not None:
        raise ValueError(f"condition occurrence {current_key!r} ended without a final block")

    return _condition_result(
        filename=filename,
        channel_names=scalp_names,
        conditions=conditions,
        block_rows=all_block_rows,
        manual_removed_channels=manual_removed,
        thresholds=_v2_thresholds(config),
        config=config,
        transient_amplitude_findings=_transient_amplitude_review_findings(
            all_amplitude_window_rows
        ),
        transient_windowing={
            "requested_window_duration_s": duration_value,
            "requested_hop_duration_s": hop_value,
            "actual_window_samples": full_block_samples,
            "actual_hop_samples": hop_samples,
            "actual_window_duration_s": full_block_samples / sfreq_value,
            "actual_hop_duration_s": hop_samples / sfreq_value,
            "nominal_overlap_samples": max(0, full_block_samples - hop_samples),
            "nominal_overlap_fraction": max(
                0.0,
                (full_block_samples - hop_samples) / full_block_samples,
            ),
            "tail_policy": "full_window_ending_at_occurrence_stop",
            "short_occurrence_policy": "one_unpadded_window",
            "full_occurrence_sample_counting": "unique_samples_once",
        },
    )


def combine_condition_raw_channel_qc_v2(
    results: Sequence[ConditionRawChannelQCResult],
    *,
    filename: str | None = None,
) -> ConditionRawChannelQCResult:
    """Deterministically combine independently cached condition-occurrence results."""

    if not results:
        raise ValueError("at least one condition-aware raw channel QC result is required")
    first = results[0]
    channel_names = first.channel_names
    thresholds = dict(first.thresholds)
    transient_windowing = dict(first.transient_windowing)
    manual_removed = first.manual_removed_channels
    combined_conditions: list[RawChannelConditionAggregate] = []
    block_rows: list[RawChannelBlockMetrics] = []
    seen: set[tuple[str, int]] = set()
    for result in results:
        if result.method_version != CONDITION_RAW_CHANNEL_QC_METHOD_VERSION:
            raise ValueError("cannot combine a different raw-channel QC method version")
        if result.channel_names != channel_names:
            raise ValueError("cannot combine raw-channel QC results with different channel layouts")
        if dict(result.thresholds) != thresholds:
            raise ValueError("cannot combine raw-channel QC results with different thresholds")
        if dict(result.transient_windowing) != transient_windowing:
            raise ValueError(
                "cannot combine raw-channel QC results with different transient windows"
            )
        if result.manual_removed_channels != manual_removed:
            raise ValueError("cannot combine raw-channel QC results with different manual channel settings")
        for condition in result.conditions:
            key = (condition.condition_id, condition.occurrence)
            if key in seen:
                raise ValueError(f"duplicate condition occurrence {key!r} in combined QC results")
            seen.add(key)
            combined_conditions.append(condition)
        for extrema in result.transient_extrema:
            block_rows.extend(
                (extrema.lowest_variance_block, extrema.highest_amplitude_block)
            )

    config = RawChannelQCConfig(
        max_bad_channels=_coerce_int(
            thresholds.get("max_bad_channels"),
            RawChannelQCConfig.max_bad_channels,
        ),
        max_bad_fraction=float(
            thresholds.get("max_bad_fraction", RawChannelQCConfig.max_bad_fraction)
        ),
        max_hemisphere_bad_fraction=float(
            thresholds.get(
                "max_hemisphere_bad_fraction",
                RawChannelQCConfig.max_hemisphere_bad_fraction,
            )
        ),
        min_channels_for_hard_qc=_coerce_int(
            thresholds.get("min_channels_for_hard_qc"),
            RawChannelQCConfig.min_channels_for_hard_qc,
        ),
        min_hemisphere_channels=_coerce_int(
            thresholds.get("min_hemisphere_channels"),
            RawChannelQCConfig.min_hemisphere_channels,
        ),
        min_bad_cluster_warning_size=_coerce_int(
            thresholds.get("min_bad_cluster_warning_size"),
            RawChannelQCConfig.min_bad_cluster_warning_size,
        ),
        min_bad_cluster_size=_coerce_int(
            thresholds.get("min_bad_cluster_size"),
            RawChannelQCConfig.min_bad_cluster_size,
        ),
        neighbor_distance_factor=float(
            thresholds.get(
                "neighbor_distance_factor",
                RawChannelQCConfig.neighbor_distance_factor,
            )
        ),
        auto_detect_removed_electrodes=bool(
            thresholds.get("auto_detect_removed_electrodes")
        ),
        removed_electrode_detection_mode=(
            REMOVED_ELECTRODE_DETECTION_MODE_MANUAL
            if manual_removed
            else REMOVED_ELECTRODE_DETECTION_MODE_AUTO
        ),
    )
    inherited_transient_findings = tuple(
        finding
        for result in results
        for finding in result.transient_review_findings
    )
    inherited_amplitude_findings = tuple(
        finding
        for result in results
        for finding in result.transient_amplitude_review_findings
    )

    return _condition_result(
        filename=str(filename or first.filename),
        channel_names=channel_names,
        conditions=combined_conditions,
        block_rows=block_rows,
        manual_removed_channels=manual_removed,
        thresholds=thresholds,
        config=config,
        inherited_transient_findings=inherited_transient_findings,
        transient_amplitude_findings=inherited_amplitude_findings,
        transient_windowing=transient_windowing,
    )


__all__ = [
    "CONDITION_RAW_CHANNEL_QC_METHOD_VERSION",
    "RAW_CHANNEL_QC_EXCLUSION_REASON",
    "RAW_CHANNEL_QC_METHOD_VERSION",
    "SCALP_CHANNEL_ORDER",
    "SCALP_CHANNELS",
    "ConditionRawChannelQCBlock",
    "ConditionRawChannelQCCancelled",
    "ConditionRawChannelQCResult",
    "RawChannelQCConfig",
    "RawChannelBlockMetrics",
    "RawChannelConditionAggregate",
    "RawChannelMetricSet",
    "RawChannelQCResult",
    "RawChannelTransientExtrema",
    "combine_condition_raw_channel_qc_v2",
    "evaluate_condition_raw_channel_qc_v2",
    "evaluate_raw_channel_qc",
]
