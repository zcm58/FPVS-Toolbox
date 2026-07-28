"""Raw EEG channel-health QC for preprocessing interpolation and exclusions."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable, Iterable
from typing import Any, Mapping, Sequence

import numpy as np

from Main_App.processing.removed_electrode_detection import (
    DEFAULT_REMOVED_ELECTRODE_DETECTION_CALIBRATION,
    REMOVED_ELECTRODE_DETECTION_MODE_AUTO,
    REMOVED_ELECTRODE_DETECTION_MODE_MANUAL,
    is_high_amplitude_removed_channel,
    is_low_variance_removed_channel,
    normalize_removed_electrode_detection_mode,
    parse_electrode_list,
    removed_electrode_threshold_payload,
    spatial_predictability_outliers,
)

RAW_CHANNEL_QC_EXCLUSION_REASON = "raw_channel_qc_failure"
_CALIBRATION = DEFAULT_REMOVED_ELECTRODE_DETECTION_CALIBRATION

LEFT_HEMISPHERE_CHANNELS: frozenset[str] = frozenset(
    {
        "Fp1",
        "AF7",
        "AF3",
        "F1",
        "F3",
        "F5",
        "F7",
        "FT7",
        "FC5",
        "FC3",
        "FC1",
        "C1",
        "C3",
        "C5",
        "T7",
        "TP7",
        "CP5",
        "CP3",
        "CP1",
        "P1",
        "P3",
        "P5",
        "P7",
        "P9",
        "PO7",
        "PO3",
        "O1",
    }
)
RIGHT_HEMISPHERE_CHANNELS: frozenset[str] = frozenset(
    {
        "Fp2",
        "AF8",
        "AF4",
        "F2",
        "F4",
        "F6",
        "F8",
        "FT8",
        "FC6",
        "FC4",
        "FC2",
        "C2",
        "C4",
        "C6",
        "T8",
        "TP8",
        "CP6",
        "CP4",
        "CP2",
        "P2",
        "P4",
        "P6",
        "P8",
        "P10",
        "PO8",
        "PO4",
        "O2",
    }
)
MIDLINE_CHANNELS: frozenset[str] = frozenset(
    {"Fpz", "AFz", "Fz", "FCz", "Cz", "CPz", "Pz", "POz", "Oz", "Iz"}
)
SCALP_CHANNELS: frozenset[str] = LEFT_HEMISPHERE_CHANNELS | RIGHT_HEMISPHERE_CHANNELS | MIDLINE_CHANNELS


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

    def to_payload(self) -> dict[str, object]:
        return {
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
        }


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
    finite_float64 = (
        metric_values.dtype == np.dtype(np.float64)
        and metric_values.size > 0
        and bool(np.isfinite(metric_values).all())
    )
    if finite_float64:
        percentiles = np.percentile(
            metric_values,
            [0.05, 0.5, 99.5, 99.95],
        )
        std_uv = float(np.std(metric_values) * 1e6)
        full_p2p_uv = float(
            (np.max(metric_values) - np.min(metric_values)) * 1e6
        )
    elif metric_values.dtype == np.dtype(np.float64):
        percentiles = np.nanpercentile(
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


CONDITION_RAW_CHANNEL_QC_METHOD_VERSION = "condition_blocks_v4"


class ConditionRawChannelQCCancelled(RuntimeError):
    """Raised when condition-aware raw-channel QC is cancelled between blocks."""


@dataclass(frozen=True)
class ConditionRawChannelQCBlock:
    """One consecutive block from a single relevant condition occurrence.

    ``data`` contains every source channel listed in ``channel_names`` passed to
    :func:`evaluate_condition_raw_channel_qc_v2`. The evaluator selects scalp EEG
    channels itself. A non-final block must span exactly ten seconds (or the
    explicitly configured block duration); the final block may be shorter.
    """

    condition_id: str
    occurrence: int
    start_sample: int
    stop_sample: int
    data: np.ndarray
    is_final: bool


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

    @property
    def n_samples(self) -> int:
        return self.stop_sample - self.start_sample

    def to_payload(self) -> dict[str, object]:
        return {
            "condition_id": self.condition_id,
            "occurrence": self.occurrence,
            "block_index": self.block_index,
            "start_sample": self.start_sample,
            "stop_sample": self.stop_sample,
            "n_samples": self.n_samples,
            **self.metrics.to_payload(),
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
        return _ordered_channel_union(
            self.channel_names,
            self.manual_removed_channels,
            self.low_variance_channels,
            self.high_amplitude_channels,
            self.rare_burst_channels,
        )

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
        return ()

    @property
    def triggered_rules(self) -> tuple[str, ...]:
        return ()

    @property
    def warning_rules(self) -> tuple[str, ...]:
        return self.review_rules

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
                f"{self.n_conditions} condition occurrence(s), {self.n_blocks} block(s), and "
                f"{self.n_bad_channels}/{self.n_channels} channel(s) were persistently "
                "flagged across all occurrences; transient findings are reported separately. "
                "All v2 findings are review-only and do not automatically exclude or interpolate channels."
            )
        return (
            f"Condition-aware raw channel QC passed for {self.filename}: "
            f"{self.n_conditions} condition occurrence(s) and {self.n_blocks} block(s) examined. "
            "V2 findings are review-only."
        )

    def to_payload(self) -> dict[str, object]:
        left = sum(channel in LEFT_HEMISPHERE_CHANNELS for channel in self.bad_channels)
        right = sum(channel in RIGHT_HEMISPHERE_CHANNELS for channel in self.bad_channels)
        midline = sum(channel in MIDLINE_CHANNELS for channel in self.bad_channels)
        return {
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
            "transient_low_variance_channels": list(self.transient_low_variance_channels),
            "transient_high_amplitude_channels": list(self.transient_high_amplitude_channels),
            "transient_rare_burst_channels": list(self.transient_rare_burst_channels),
            "spatial_outlier_channels": [],
            "spatial_qc_evaluated": False,
            "raw_baseline_median_std_uv": self.raw_baseline_median_std_uv,
            "raw_baseline_median_p2p_99_uv": self.raw_baseline_median_p2p_99_uv,
            "raw_baseline_aggregation": "maximum_across_condition_occurrences",
            "raw_baseline_warning": self.raw_baseline_warning,
            "raw_baseline_excluded": False,
            "raw_baseline_failure_review": self.raw_baseline_failure_review,
            "largest_bad_cluster_size": 0,
            "largest_bad_cluster_channels": [],
            "bad_cluster_qc_evaluated": False,
            "triggered_rules": [],
            "warning_rules": list(self.warning_rules),
            "review_rules": list(self.review_rules),
            "thresholds": dict(self.thresholds),
            "conditions": [item.to_payload() for item in self.conditions],
            "transient_extrema": [item.to_payload() for item in self.transient_extrema],
        }


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
        if mode == REMOVED_ELECTRODE_DETECTION_MODE_MANUAL
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


def _channel_positions(raw: Any, channels: Sequence[str]) -> dict[str, np.ndarray]:
    positions: dict[str, np.ndarray] = {}
    try:
        montage = raw.get_montage()
        montage_positions = montage.get_positions().get("ch_pos", {}) if montage else {}
    except (AttributeError, TypeError, ValueError):
        montage_positions = {}

    for index, channel in enumerate(getattr(raw, "ch_names", [])):
        name = str(channel)
        if name not in channels:
            continue
        coord = montage_positions.get(name)
        if coord is None:
            try:
                coord = raw.info["chs"][index]["loc"][:3]
            except (AttributeError, KeyError, IndexError, TypeError):
                coord = None
        if coord is None:
            continue
        arr = np.asarray(coord, dtype=float)
        if arr.shape != (3,) or not np.all(np.isfinite(arr)) or np.allclose(arr, 0.0):
            continue
        positions[name] = arr
    return positions


def _bad_channel_clusters(
    raw: Any,
    bad_channels: Sequence[str],
    *,
    config: RawChannelQCConfig,
) -> list[tuple[str, ...]]:
    unique_bads = sorted({str(channel) for channel in bad_channels if str(channel) in SCALP_CHANNELS})
    if not unique_bads:
        return []

    all_scalp = [str(channel) for channel in getattr(raw, "ch_names", []) if str(channel) in SCALP_CHANNELS]
    positions = _channel_positions(raw, all_scalp)
    if len(positions) < 2:
        return [(channel,) for channel in unique_bads]

    pos_names = sorted(positions)
    coords = np.vstack([positions[name] for name in pos_names])
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
    positions = _channel_positions(raw, channels)
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
    neighbor_map = _spatial_neighbor_map(raw, channels, config=config)
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


def _empty_result(
    *,
    message: str,
    thresholds: Mapping[str, float | int | bool],
    n_channels: int = 0,
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
    )


def evaluate_raw_channel_qc(
    raw: Any,
    settings: Mapping[str, Any],
    *,
    filename: str,
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
        "auto_detect_removed_electrodes": config.auto_detect_removed_electrodes,
        **removed_electrode_threshold_payload(config),
    }
    if n_channels == 0:
        return _empty_result(
            message=f"Raw channel QC skipped for {filename}: no scalp EEG channels found.",
            thresholds=thresholds,
        )
    if n_channels < config.min_channels_for_hard_qc:
        return _empty_result(
            message=(
                f"Raw channel QC skipped for {filename}: only {n_channels} scalp EEG channels "
                f"were found; hard QC requires at least {config.min_channels_for_hard_qc}."
            ),
            thresholds=thresholds,
            n_channels=n_channels,
        )

    sfreq = float(raw.info.get("sfreq", 0.0))
    spans = _sample_spans(int(getattr(raw, "n_times", 0)), sfreq, config)
    if not spans:
        return RawChannelQCResult(
            excluded=True,
            reason=RAW_CHANNEL_QC_EXCLUSION_REASON,
            message=f"{filename} excluded by raw channel-health QC: no EEG samples were available.",
            n_channels=n_channels,
            n_bad_channels=n_channels,
            bad_fraction=1.0,
            left_bad=0,
            left_total=0,
            right_bad=0,
            right_total=0,
            midline_bad=0,
            midline_total=0,
            bad_channels=tuple(str(raw.ch_names[index]) for index in picks),
            channels_to_interpolate=(),
            manual_removed_channels=(),
            low_variance_channels=tuple(str(raw.ch_names[index]) for index in picks),
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

    candidate_channels = list(
        dict.fromkeys(
            [
                *manual_removed_channels,
                *low_variance_channels,
                *high_amplitude_channels,
                *rare_burst_channels,
                *spatial_outlier_channels,
            ]
        )
    )
    left_bad = right_bad = midline_bad = 0
    for channel in candidate_channels:
        group = _channel_group(channel)
        if group == "left":
            left_bad += 1
        elif group == "right":
            right_bad += 1
        elif group == "midline":
            midline_bad += 1

    n_bad = len(candidate_channels)
    bad_fraction = n_bad / n_channels if n_channels else 0.0
    left_fraction = left_bad / left_total if left_total else 0.0
    right_fraction = right_bad / right_total if right_total else 0.0
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

    cluster_candidates = set(_raw_bads(raw))
    cluster_rules_enabled = (
        config.auto_detect_removed_electrodes
        or config.removed_electrode_detection_mode == REMOVED_ELECTRODE_DETECTION_MODE_MANUAL
    )
    if cluster_rules_enabled:
        cluster_candidates.update(candidate_channels)
    clusters = _bad_channel_clusters(raw, sorted(cluster_candidates), config=config)
    largest_cluster = clusters[0] if clusters else ()

    triggered: list[str] = []
    if n_bad > config.max_bad_channels:
        triggered.append("bad_channel_count")
    if bad_fraction > config.max_bad_fraction:
        triggered.append("bad_channel_fraction")
    if raw_baseline_excluded:
        triggered.append("raw_amplitude_baseline_failure")
    if left_total >= config.min_hemisphere_channels and left_fraction >= config.max_hemisphere_bad_fraction:
        triggered.append("left_hemisphere_failure")
    if right_total >= config.min_hemisphere_channels and right_fraction >= config.max_hemisphere_bad_fraction:
        triggered.append("right_hemisphere_failure")
    if (
        cluster_rules_enabled
        and len(largest_cluster) >= config.min_bad_cluster_size
    ):
        triggered.append("bad_channel_cluster")
    warning_rules: list[str] = []
    if raw_baseline_warning and not raw_baseline_excluded:
        warning_rules.append("raw_amplitude_baseline_warning")
    if (
        cluster_rules_enabled
        and len(largest_cluster) >= config.min_bad_cluster_warning_size
        and len(largest_cluster) < config.min_bad_cluster_size
    ):
        warning_rules.append("possible_bad_channel_cluster")

    excluded = bool(triggered)
    reason = RAW_CHANNEL_QC_EXCLUSION_REASON if excluded else None
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
            f"{filename} excluded by raw channel-health QC: participant-level raw "
            "amplitude baseline was excessively noisy."
            f"{baseline_text} {n_bad}/{n_channels} scalp EEG channels were "
            "low-amplitude, extreme high-amplitude, rare-burst, or spatially "
            f"inconsistent; left={left_bad}/{left_total}, "
            f"right={right_bad}/{right_total}, midline={midline_bad}/{midline_total}."
            f"{cluster_text} Triggered rule(s): {', '.join(triggered)}."
        )
    elif excluded:
        message = (
            f"{filename} excluded by raw channel-health QC: {n_bad}/{n_channels} scalp EEG "
            "channels were low-amplitude, extreme high-amplitude, rare-burst, or spatially "
            f"inconsistent; left={left_bad}/{left_total}, "
            f"right={right_bad}/{right_total}, midline={midline_bad}/{midline_total}."
            f"{cluster_text} Triggered rule(s): {', '.join(triggered)}."
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
        excluded=excluded,
        reason=reason,
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
        raw_baseline_excluded=raw_baseline_excluded,
        largest_bad_cluster_size=len(largest_cluster),
        largest_bad_cluster_channels=tuple(largest_cluster),
        triggered_rules=tuple(triggered),
        warning_rules=tuple(warning_rules),
        thresholds=thresholds,
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
        "auto_detect_removed_electrodes": config.auto_detect_removed_electrodes,
        "review_only": True,
        **removed_electrode_threshold_payload(config),
    }


def _v2_channel_metrics(channel: str, values: np.ndarray) -> RawChannelMetricSet:
    """Apply the v1 float64 formulas with one vectorized percentile call."""

    values64 = np.asarray(values, dtype=np.float64)
    std_uv, p2p_99_uv, p2p_999_uv, full_p2p_uv = _channel_metric_values(
        values64
    )
    return RawChannelMetricSet(
        channel=channel,
        std_uv=std_uv,
        p2p_99_uv=p2p_99_uv,
        p2p_999_uv=p2p_999_uv,
        full_p2p_uv=full_p2p_uv,
    )


def _v2_metric_rows(
    data: np.ndarray,
    channel_names: Sequence[str],
) -> tuple[RawChannelMetricSet, ...]:
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


def _review_rules(
    conditions: Sequence[RawChannelConditionAggregate],
) -> tuple[str, ...]:
    rules: list[str] = []
    persistent_checks = (
        ("low_variance_channels", "condition_persistent_low_variance_review"),
        ("high_amplitude_channels", "condition_persistent_high_amplitude_review"),
        ("rare_burst_channels", "condition_persistent_rare_burst_review"),
    )
    transient_checks = (
        ("transient_high_amplitude_channels", "condition_transient_high_amplitude_review"),
        ("transient_rare_burst_channels", "condition_transient_rare_burst_review"),
    )
    for field, rule in persistent_checks:
        if conditions and set.intersection(
            *(set(getattr(condition, field)) for condition in conditions)
        ):
            rules.append(rule)
    for field, rule in transient_checks:
        if any(getattr(condition, field) for condition in conditions):
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
    return ConditionRawChannelQCResult(
        filename=filename,
        channel_names=channel_names,
        conditions=ordered_conditions,
        transient_extrema=_transient_extrema(block_rows, channel_names),
        manual_removed_channels=manual_removed_channels,
        thresholds=dict(thresholds),
        review_rules=_review_rules(ordered_conditions),
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
    expected_shape = (chunks[0].shape[0], sum(chunk.shape[1] for chunk in chunks))
    if root.shape != expected_shape:
        return None
    return np.asarray(root, dtype=np.float64)


def evaluate_condition_raw_channel_qc_v2(
    blocks: Iterable[ConditionRawChannelQCBlock],
    channel_names: Sequence[str],
    settings: Mapping[str, Any],
    *,
    filename: str,
    sfreq: float,
    block_duration_s: float = 10.0,
    should_cancel: Callable[[], bool] | None = None,
) -> ConditionRawChannelQCResult:
    """Evaluate every supplied condition sample without retaining a full recording.

    Blocks for an occurrence must be consecutive and end with ``is_final=True``.
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
    current_block_rows: list[RawChannelBlockMetrics] = []
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
            if aggregate_data is None:
                aggregate_data = np.concatenate(current_chunks, axis=1)
        aggregate_rows = _v2_metric_rows(aggregate_data, scalp_names)
        aggregate_classification = _classify_v2_metrics(aggregate_rows, config)
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
        seen_occurrences.add(current_key)
        current_key = None
        current_chunks.clear()
        current_block_rows.clear()
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
        if block.is_final:
            if n_samples > full_block_samples:
                raise ValueError("a final condition block cannot exceed the configured block size")
        elif n_samples != full_block_samples:
            raise ValueError("each non-final condition block must equal the configured block size")

        if current_key is None:
            current_key = key
            current_start = start_sample
            current_stop = start_sample
        if start_sample != current_stop:
            raise ValueError(
                f"condition occurrence {key!r} has a gap or overlap before sample {start_sample}"
            )

        if picks == tuple(range(len(source_channel_names))):
            selected = data
        else:
            selected = data[np.asarray(picks, dtype=int)]
        block_index = len(current_chunks)
        block_metric_rows = _v2_metric_rows(selected, scalp_names)
        classification = _classify_v2_metrics(block_metric_rows, config)
        # A relative low-variance classification is calibrated for persistent
        # multi-window data, not a single 10-second block. Preserve each
        # channel's quietest-block metrics below, but do not turn an isolated
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
            )
            for row in block_metric_rows
        )
        current_chunks.append(selected)
        current_stop = stop_sample

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

    return _condition_result(
        filename=str(filename or first.filename),
        channel_names=channel_names,
        conditions=combined_conditions,
        block_rows=block_rows,
        manual_removed_channels=manual_removed,
        thresholds=thresholds,
    )


__all__ = [
    "CONDITION_RAW_CHANNEL_QC_METHOD_VERSION",
    "RAW_CHANNEL_QC_EXCLUSION_REASON",
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
