"""Raw EEG channel-health QC for preprocessing interpolation and exclusions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np

RAW_CHANNEL_QC_EXCLUSION_REASON = "raw_channel_qc_failure"

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
    low_std_uv: float = 20.0
    low_p2p_99_uv: float = 80.0
    low_std_relative_ratio: float = 0.25
    low_p2p_99_relative_ratio: float = 0.25
    relative_low_std_uv_ceiling: float = 60.0
    relative_low_p2p_99_uv_ceiling: float = 240.0
    high_std_relative_ratio: float = 7.5
    high_p2p_99_relative_ratio: float = 10.0
    high_std_uv_floor: float = 2_000.0
    high_p2p_99_uv_floor: float = 10_000.0
    auto_detect_removed_electrodes: bool = True
    min_bad_cluster_warning_size: int = 4
    min_bad_cluster_size: int = 6
    neighbor_distance_factor: float = 1.75
    spatial_qc_enabled: bool = True
    spatial_neighbor_count: int = 6
    spatial_min_neighbors: int = 3
    spatial_neighbor_distance_factor: float = 2.60
    spatial_predictability_max_bad_corr: float = 0.12
    spatial_predictability_relative_ratio: float = 0.55
    spatial_predictability_mad_z: float = 3.5
    sample_windows: int = 6
    sample_window_s: float = 10.0
    edge_padding_s: float = 10.0


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
    low_variance_channels: tuple[str, ...]
    high_amplitude_channels: tuple[str, ...]
    spatial_outlier_channels: tuple[str, ...]
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
            "low_variance_channels": list(self.low_variance_channels),
            "high_amplitude_channels": list(self.high_amplitude_channels),
            "spatial_outlier_channels": list(self.spatial_outlier_channels),
            "largest_bad_cluster_size": self.largest_bad_cluster_size,
            "largest_bad_cluster_channels": list(self.largest_bad_cluster_channels),
            "triggered_rules": list(self.triggered_rules),
            "warning_rules": list(self.warning_rules),
            "thresholds": dict(self.thresholds),
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
    return RawChannelQCConfig(
        max_bad_channels=max(0, max_bad),
        auto_detect_removed_electrodes=auto_detect,
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


def _scaled_mad(values: Sequence[float]) -> float:
    finite = np.asarray(
        [float(value) for value in values if np.isfinite(value)],
        dtype=float,
    )
    if finite.size == 0:
        return 0.0
    median = float(np.median(finite))
    mad = float(np.median(np.abs(finite - median)))
    return float(1.4826 * mad)


def _is_low_variance_removed_channel(
    *,
    std_uv: float,
    p2p_99_uv: float,
    median_std_uv: float,
    median_p2p_99_uv: float,
    config: RawChannelQCConfig,
) -> bool:
    absolute_low = std_uv < config.low_std_uv and p2p_99_uv < config.low_p2p_99_uv
    relative_low = (
        median_std_uv > config.low_std_uv
        and median_p2p_99_uv > config.low_p2p_99_uv
        and std_uv < median_std_uv * config.low_std_relative_ratio
        and p2p_99_uv < median_p2p_99_uv * config.low_p2p_99_relative_ratio
        and std_uv < config.relative_low_std_uv_ceiling
        and p2p_99_uv < config.relative_low_p2p_99_uv_ceiling
    )
    return bool(absolute_low or relative_low)


def _is_high_amplitude_removed_channel(
    *,
    std_uv: float,
    p2p_99_uv: float,
    median_std_uv: float,
    median_p2p_99_uv: float,
    config: RawChannelQCConfig,
) -> bool:
    return bool(
        median_std_uv > 0.0
        and median_p2p_99_uv > 0.0
        and std_uv >= config.high_std_uv_floor
        and p2p_99_uv >= config.high_p2p_99_uv_floor
        and std_uv >= median_std_uv * config.high_std_relative_ratio
        and p2p_99_uv >= median_p2p_99_uv * config.high_p2p_99_relative_ratio
    )


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
    excluded = {str(channel) for channel in excluded_channels}
    reference_scores = [
        float(score)
        for channel, score in scores.items()
        if channel not in excluded and np.isfinite(score)
    ]
    if len(reference_scores) < config.min_channels_for_hard_qc:
        return ()

    median_score = float(np.median(reference_scores))
    mad_score = _scaled_mad(reference_scores)
    robust_threshold = median_score - config.spatial_predictability_mad_z * mad_score
    relative_threshold = median_score * config.spatial_predictability_relative_ratio
    threshold = min(
        config.spatial_predictability_max_bad_corr,
        relative_threshold,
        robust_threshold,
    )
    if not np.isfinite(threshold) or threshold <= 0.0:
        return ()

    return tuple(
        channel
        for channel, score in scores.items()
        if channel not in excluded and np.isfinite(score) and float(score) < threshold
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
        low_variance_channels=(),
        high_amplitude_channels=(),
        spatial_outlier_channels=(),
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
        "low_std_uv": config.low_std_uv,
        "low_p2p_99_uv": config.low_p2p_99_uv,
        "low_std_relative_ratio": config.low_std_relative_ratio,
        "low_p2p_99_relative_ratio": config.low_p2p_99_relative_ratio,
        "relative_low_std_uv_ceiling": config.relative_low_std_uv_ceiling,
        "relative_low_p2p_99_uv_ceiling": config.relative_low_p2p_99_uv_ceiling,
        "high_std_relative_ratio": config.high_std_relative_ratio,
        "high_p2p_99_relative_ratio": config.high_p2p_99_relative_ratio,
        "high_std_uv_floor": config.high_std_uv_floor,
        "high_p2p_99_uv_floor": config.high_p2p_99_uv_floor,
        "auto_detect_removed_electrodes": config.auto_detect_removed_electrodes,
        "min_bad_cluster_warning_size": config.min_bad_cluster_warning_size,
        "min_bad_cluster_size": config.min_bad_cluster_size,
        "spatial_qc_enabled": config.spatial_qc_enabled,
        "spatial_neighbor_count": config.spatial_neighbor_count,
        "spatial_min_neighbors": config.spatial_min_neighbors,
        "spatial_neighbor_distance_factor": config.spatial_neighbor_distance_factor,
        "spatial_predictability_max_bad_corr": config.spatial_predictability_max_bad_corr,
        "spatial_predictability_relative_ratio": config.spatial_predictability_relative_ratio,
        "spatial_predictability_mad_z": config.spatial_predictability_mad_z,
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
            low_variance_channels=tuple(str(raw.ch_names[index]) for index in picks),
            high_amplitude_channels=(),
            spatial_outlier_channels=(),
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

    channel_stats: list[tuple[str, str, float, float]] = []
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

        values = data[row_index]
        std_uv = float(np.nanstd(values) * 1e6)
        p2p_99_uv = float(
            (np.nanpercentile(values, 99.5) - np.nanpercentile(values, 0.5)) * 1e6
        )
        channel_stats.append((channel, group, std_uv, p2p_99_uv))

    median_std_uv = _robust_median([row[2] for row in channel_stats])
    median_p2p_99_uv = _robust_median([row[3] for row in channel_stats])

    low_variance_channels: list[str] = []
    for channel, _group, std_uv, p2p_99_uv in channel_stats:
        is_bad = _is_low_variance_removed_channel(
            std_uv=std_uv,
            p2p_99_uv=p2p_99_uv,
            median_std_uv=median_std_uv,
            median_p2p_99_uv=median_p2p_99_uv,
            config=config,
        )
        if not is_bad:
            continue

        low_variance_channels.append(channel)

    high_amplitude_channels: list[str] = []
    if config.auto_detect_removed_electrodes:
        low_lookup = set(low_variance_channels)
        for channel, _group, std_uv, p2p_99_uv in channel_stats:
            if channel in low_lookup:
                continue
            is_bad = _is_high_amplitude_removed_channel(
                std_uv=std_uv,
                p2p_99_uv=p2p_99_uv,
                median_std_uv=median_std_uv,
                median_p2p_99_uv=median_p2p_99_uv,
                config=config,
            )
            if is_bad:
                high_amplitude_channels.append(channel)

    spatial_outlier_channels: list[str] = []
    if config.auto_detect_removed_electrodes and config.spatial_qc_enabled:
        channel_names = [row[0] for row in channel_stats]
        donor_exclusions = [
            *_raw_bads(raw),
            *low_variance_channels,
            *high_amplitude_channels,
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
            [*low_variance_channels, *high_amplitude_channels, *spatial_outlier_channels]
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
    channels_to_interpolate = (
        tuple(low_variance_channels) if config.auto_detect_removed_electrodes else ()
    )

    cluster_candidates = set(_raw_bads(raw))
    if config.auto_detect_removed_electrodes:
        cluster_candidates.update(candidate_channels)
    clusters = _bad_channel_clusters(raw, sorted(cluster_candidates), config=config)
    largest_cluster = clusters[0] if clusters else ()

    triggered: list[str] = []
    if n_bad > config.max_bad_channels:
        triggered.append("bad_channel_count")
    if bad_fraction > config.max_bad_fraction:
        triggered.append("bad_channel_fraction")
    if left_total >= config.min_hemisphere_channels and left_fraction >= config.max_hemisphere_bad_fraction:
        triggered.append("left_hemisphere_failure")
    if right_total >= config.min_hemisphere_channels and right_fraction >= config.max_hemisphere_bad_fraction:
        triggered.append("right_hemisphere_failure")
    if (
        config.auto_detect_removed_electrodes
        and len(largest_cluster) >= config.min_bad_cluster_size
    ):
        triggered.append("bad_channel_cluster")
    warning_rules: list[str] = []
    if (
        config.auto_detect_removed_electrodes
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
    if excluded:
        message = (
            f"{filename} excluded by raw channel-health QC: {n_bad}/{n_channels} scalp EEG "
            "channels were low-amplitude, extreme high-amplitude, or spatially "
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
            message += f" Warning rule(s): {', '.join(warning_rules)}."
    else:
        message = (
            f"Raw channel QC passed for {filename}: {n_bad}/{n_channels} scalp EEG channels "
            "were low-amplitude, extreme high-amplitude, or spatially inconsistent."
        )
        if warning_rules:
            message += f"{cluster_text} Warning rule(s): {', '.join(warning_rules)}."

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
        low_variance_channels=tuple(low_variance_channels),
        high_amplitude_channels=tuple(high_amplitude_channels),
        spatial_outlier_channels=tuple(spatial_outlier_channels),
        largest_bad_cluster_size=len(largest_cluster),
        largest_bad_cluster_channels=tuple(largest_cluster),
        triggered_rules=tuple(triggered),
        warning_rules=tuple(warning_rules),
        thresholds=thresholds,
    )


__all__ = [
    "RAW_CHANNEL_QC_EXCLUSION_REASON",
    "RawChannelQCConfig",
    "RawChannelQCResult",
    "evaluate_raw_channel_qc",
]
