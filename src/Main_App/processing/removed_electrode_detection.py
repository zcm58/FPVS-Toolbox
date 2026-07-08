"""Calibrated helpers for conservative removed-electrode auto-detection.

This module is the adjustment surface for the signal-based detector that looks
for electrodes physically removed before recording. Keep future calibration
constants and explanatory user-facing text here so the method is easy to find.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any

import numpy as np


REMOVED_ELECTRODE_DETECTION_MODE_OFF = "off"
REMOVED_ELECTRODE_DETECTION_MODE_AUTO = "auto"
REMOVED_ELECTRODE_DETECTION_MODE_MANUAL = "manual"
REMOVED_ELECTRODE_DETECTION_MODES = (
    REMOVED_ELECTRODE_DETECTION_MODE_OFF,
    REMOVED_ELECTRODE_DETECTION_MODE_AUTO,
    REMOVED_ELECTRODE_DETECTION_MODE_MANUAL,
)

REMOVED_ELECTRODE_DETECTION_INFO_TEXT = (
    "In the development of FPVS Toolbox, this automatic detection method was "
    "designed to identify electrodes that needed to be physically removed prior "
    "to the start of a recording. In our lab, we were dealing with electrodes "
    "that would sometimes cause a CMS/DRL error, and I calibrated this detection "
    "method using real experimental data. This method was over 99% specific in "
    "removing the correct channels in our training data, but this method is "
    "intentionally very conservative and prioritizes avoiding false positive "
    "electrode removals. As a result, this method only detects around 60% of "
    "electrodes that were actually physically unplugged prior to recording, but "
    "when it does identify an electrode, it is correct 99.7% of the time."
)


@dataclass(frozen=True)
class RemovedElectrodeDetectionCalibration:
    """Threshold profile for raw removed-electrode candidate detection."""

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
    baseline_warning_median_std_uv: float = 2_000.0
    baseline_warning_median_p2p_99_uv: float = 10_000.0
    baseline_exclusion_median_std_uv: float = 10_000.0
    baseline_exclusion_median_p2p_99_uv: float = 100_000.0
    rare_burst_std_uv_floor: float = 8_000.0
    rare_burst_p2p_99_uv_ceiling: float = 100.0
    rare_burst_p2p_999_uv_floor: float = 100_000.0
    rare_burst_full_to_p2p_99_ratio: float = 1_000.0
    rare_burst_rank_limit: int = 2
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


DEFAULT_REMOVED_ELECTRODE_DETECTION_CALIBRATION = RemovedElectrodeDetectionCalibration()


_ELECTRODE_TOKEN_SPLIT_RE = re.compile(r"[,;\n]+")
_ELECTRODE_RE = re.compile(r"^([A-Za-z]+)(\d+|[Zz])?$")
_PREFIX_CASE = {
    "FP": "Fp",
    "AF": "AF",
    "F": "F",
    "FT": "FT",
    "FC": "FC",
    "C": "C",
    "T": "T",
    "TP": "TP",
    "CP": "CP",
    "P": "P",
    "PO": "PO",
    "O": "O",
    "I": "I",
    "EXG": "EXG",
}


def canonicalize_electrode_name(value: Any) -> str:
    """Return a tidy BioSemi-style channel label while preserving unknown labels."""
    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"\s+", "", text)
    upper = text.upper()
    if upper.endswith("Z") and len(upper) > 1:
        prefix = _PREFIX_CASE.get(upper[:-1])
        if prefix:
            return f"{prefix}z"
    match = _ELECTRODE_RE.match(text)
    if not match:
        return text
    prefix_raw, suffix = match.groups()
    prefix = _PREFIX_CASE.get(prefix_raw.upper(), prefix_raw)
    if suffix is None:
        return prefix
    if suffix.casefold() == "z":
        return f"{prefix}z"
    return f"{prefix}{suffix}"


def parse_electrode_list(value: Any) -> list[str]:
    """Parse comma-separated or sequence electrode values into unique labels."""
    if value in (None, ""):
        return []
    if isinstance(value, str):
        parts = _ELECTRODE_TOKEN_SPLIT_RE.split(value)
    elif isinstance(value, (list, tuple, set)):
        parts = [str(item) for item in value]
    else:
        parts = [str(value)]

    seen: set[str] = set()
    electrodes: list[str] = []
    for part in parts:
        label = canonicalize_electrode_name(part)
        if not label:
            continue
        key = label.casefold()
        if key in seen:
            continue
        seen.add(key)
        electrodes.append(label)
    return electrodes


def normalize_manual_removed_electrodes_map(value: Any) -> dict[str, list[str]]:
    """Normalize PID-to-electrodes metadata for manual removed-electrode mode."""
    source = value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return {}
        try:
            source = json.loads(text)
        except json.JSONDecodeError:
            return {}
    if not isinstance(source, dict):
        return {}

    normalized: dict[str, list[str]] = {}
    for raw_pid, raw_electrodes in source.items():
        pid = str(raw_pid or "").strip()
        if not pid:
            continue
        electrodes = parse_electrode_list(raw_electrodes)
        normalized[pid] = electrodes
    return normalized


def manual_removed_electrodes_for_pid(
    manual_map: Any,
    participant_id: Any,
) -> tuple[str, ...]:
    """Return manually removed electrodes for a PID using case-insensitive keys."""
    normalized = normalize_manual_removed_electrodes_map(manual_map)
    pid = str(participant_id or "").strip()
    if not pid:
        return ()
    if pid in normalized:
        return tuple(normalized[pid])
    pid_key = pid.casefold()
    for raw_pid, electrodes in normalized.items():
        if raw_pid.casefold() == pid_key:
            return tuple(electrodes)
    return ()


def _unique_electrodes(values: Any) -> list[str]:
    return parse_electrode_list(values)


def _canonical_lookup(values: list[str]) -> dict[str, str]:
    return {value.casefold(): value for value in values}


def build_removed_electrode_review_record(
    *,
    original_auto_flagged: Any,
    accepted_auto_flagged: Any,
    manual_additions: Any,
) -> dict[str, object]:
    """Build comparison metadata for automatic and manually confirmed removals."""

    original = _unique_electrodes(original_auto_flagged)
    accepted_raw = _unique_electrodes(accepted_auto_flagged)
    manual_raw = _unique_electrodes(manual_additions)
    original_lookup = _canonical_lookup(original)

    accepted: list[str] = []
    seen_accepted: set[str] = set()
    for electrode in accepted_raw:
        original_label = original_lookup.get(electrode.casefold())
        if original_label is None:
            continue
        if original_label.casefold() in seen_accepted:
            continue
        accepted.append(original_label)
        seen_accepted.add(original_label.casefold())

    manual_only: list[str] = []
    seen_manual: set[str] = set()
    for electrode in manual_raw:
        if electrode.casefold() in original_lookup:
            original_label = original_lookup[electrode.casefold()]
            if original_label.casefold() not in seen_accepted:
                accepted.append(original_label)
                seen_accepted.add(original_label.casefold())
            continue
        if electrode.casefold() in seen_manual:
            continue
        manual_only.append(electrode)
        seen_manual.add(electrode.casefold())

    accepted_lookup = {electrode.casefold() for electrode in accepted}
    rejected = [
        electrode for electrode in original if electrode.casefold() not in accepted_lookup
    ]
    final_confirmed = parse_electrode_list([*accepted, *manual_only])
    overlap = list(accepted)
    agreement = removed_electrode_agreement_status(
        original_auto_flagged=original,
        final_confirmed=final_confirmed,
    )
    return {
        "original_auto_flagged": original,
        "accepted_auto_flagged": accepted,
        "rejected_auto_flagged": rejected,
        "manual_additions": manual_only,
        "final_confirmed_removed": final_confirmed,
        "manual_only_missed_by_auto": manual_only,
        "auto_manual_overlap": overlap,
        "agreement_status": agreement,
    }


def removed_electrode_agreement_status(
    *,
    original_auto_flagged: Any,
    final_confirmed: Any,
) -> str:
    """Summarize agreement between preflight auto flags and final confirmations."""

    auto = _unique_electrodes(original_auto_flagged)
    final = _unique_electrodes(final_confirmed)
    auto_keys = {electrode.casefold() for electrode in auto}
    final_keys = {electrode.casefold() for electrode in final}
    if not auto_keys and not final_keys:
        return "none"
    if auto_keys == final_keys:
        return "exact"
    if auto_keys & final_keys:
        return "partial"
    if final_keys:
        return "manual_only"
    return "auto_only"


def normalize_removed_electrode_detection_mode(
    value: Any,
    *,
    auto_detect_removed_electrodes: Any = True,
) -> str:
    """Normalize the removed-electrode QC mode from new or legacy settings."""
    if isinstance(value, bool):
        return (
            REMOVED_ELECTRODE_DETECTION_MODE_AUTO
            if value
            else REMOVED_ELECTRODE_DETECTION_MODE_OFF
        )
    if value not in (None, ""):
        text = str(value).strip().casefold().replace("_", " ").replace("-", " ")
        if text in {"auto", "conservative", "conservative auto", "true", "on"}:
            return REMOVED_ELECTRODE_DETECTION_MODE_AUTO
        if text in {"manual", "manual list", "manual metadata"}:
            return REMOVED_ELECTRODE_DETECTION_MODE_MANUAL
        if text in {"off", "false", "none", "no"}:
            return REMOVED_ELECTRODE_DETECTION_MODE_OFF
    return (
        REMOVED_ELECTRODE_DETECTION_MODE_AUTO
        if bool(auto_detect_removed_electrodes)
        else REMOVED_ELECTRODE_DETECTION_MODE_OFF
    )


def removed_electrode_threshold_payload(calibration: Any) -> dict[str, float | int | bool]:
    """Return calibration values in the stable raw-QC result payload shape."""
    return {
        "low_std_uv": float(calibration.low_std_uv),
        "low_p2p_99_uv": float(calibration.low_p2p_99_uv),
        "low_std_relative_ratio": float(calibration.low_std_relative_ratio),
        "low_p2p_99_relative_ratio": float(calibration.low_p2p_99_relative_ratio),
        "relative_low_std_uv_ceiling": float(calibration.relative_low_std_uv_ceiling),
        "relative_low_p2p_99_uv_ceiling": float(
            calibration.relative_low_p2p_99_uv_ceiling
        ),
        "high_std_relative_ratio": float(calibration.high_std_relative_ratio),
        "high_p2p_99_relative_ratio": float(calibration.high_p2p_99_relative_ratio),
        "high_std_uv_floor": float(calibration.high_std_uv_floor),
        "high_p2p_99_uv_floor": float(calibration.high_p2p_99_uv_floor),
        "baseline_warning_median_std_uv": float(
            calibration.baseline_warning_median_std_uv
        ),
        "baseline_warning_median_p2p_99_uv": float(
            calibration.baseline_warning_median_p2p_99_uv
        ),
        "baseline_exclusion_median_std_uv": float(
            calibration.baseline_exclusion_median_std_uv
        ),
        "baseline_exclusion_median_p2p_99_uv": float(
            calibration.baseline_exclusion_median_p2p_99_uv
        ),
        "rare_burst_std_uv_floor": float(calibration.rare_burst_std_uv_floor),
        "rare_burst_p2p_99_uv_ceiling": float(
            calibration.rare_burst_p2p_99_uv_ceiling
        ),
        "rare_burst_p2p_999_uv_floor": float(
            calibration.rare_burst_p2p_999_uv_floor
        ),
        "rare_burst_full_to_p2p_99_ratio": float(
            calibration.rare_burst_full_to_p2p_99_ratio
        ),
        "rare_burst_rank_limit": int(calibration.rare_burst_rank_limit),
        "min_bad_cluster_warning_size": int(calibration.min_bad_cluster_warning_size),
        "min_bad_cluster_size": int(calibration.min_bad_cluster_size),
        "spatial_qc_enabled": bool(calibration.spatial_qc_enabled),
        "spatial_neighbor_count": int(calibration.spatial_neighbor_count),
        "spatial_min_neighbors": int(calibration.spatial_min_neighbors),
        "spatial_neighbor_distance_factor": float(
            calibration.spatial_neighbor_distance_factor
        ),
        "spatial_predictability_max_bad_corr": float(
            calibration.spatial_predictability_max_bad_corr
        ),
        "spatial_predictability_relative_ratio": float(
            calibration.spatial_predictability_relative_ratio
        ),
        "spatial_predictability_mad_z": float(
            calibration.spatial_predictability_mad_z
        ),
    }


def is_low_variance_removed_channel(
    *,
    std_uv: float,
    p2p_99_uv: float,
    median_std_uv: float,
    median_p2p_99_uv: float,
    calibration: Any,
) -> bool:
    """Return whether a channel matches the flat/low-amplitude removal profile."""
    absolute_low = (
        std_uv < calibration.low_std_uv
        and p2p_99_uv < calibration.low_p2p_99_uv
    )
    relative_low = (
        median_std_uv > calibration.low_std_uv
        and median_p2p_99_uv > calibration.low_p2p_99_uv
        and std_uv < median_std_uv * calibration.low_std_relative_ratio
        and p2p_99_uv < median_p2p_99_uv * calibration.low_p2p_99_relative_ratio
        and std_uv < calibration.relative_low_std_uv_ceiling
        and p2p_99_uv < calibration.relative_low_p2p_99_uv_ceiling
    )
    return bool(absolute_low or relative_low)


def is_high_amplitude_removed_channel(
    *,
    std_uv: float,
    p2p_99_uv: float,
    median_std_uv: float,
    median_p2p_99_uv: float,
    calibration: Any,
) -> bool:
    """Return whether a channel matches the high-amplitude removal profile."""
    return bool(
        median_std_uv > 0.0
        and median_p2p_99_uv > 0.0
        and std_uv >= calibration.high_std_uv_floor
        and p2p_99_uv >= calibration.high_p2p_99_uv_floor
        and std_uv >= median_std_uv * calibration.high_std_relative_ratio
        and p2p_99_uv >= median_p2p_99_uv * calibration.high_p2p_99_relative_ratio
    )


def _scaled_mad(values: list[float]) -> float:
    finite = np.asarray(
        [float(value) for value in values if np.isfinite(value)],
        dtype=float,
    )
    if finite.size == 0:
        return 0.0
    median = float(np.median(finite))
    mad = float(np.median(np.abs(finite - median)))
    return float(1.4826 * mad)


def spatial_predictability_threshold(
    reference_scores: list[float],
    *,
    calibration: Any,
    min_reference_count: int,
) -> float | None:
    """Return the participant-local spatial score cutoff, if enough data exist."""
    finite_scores = [
        float(score)
        for score in reference_scores
        if np.isfinite(score)
    ]
    if len(finite_scores) < min_reference_count:
        return None

    median_score = float(np.median(finite_scores))
    mad_score = _scaled_mad(finite_scores)
    robust_threshold = (
        median_score - calibration.spatial_predictability_mad_z * mad_score
    )
    relative_threshold = median_score * calibration.spatial_predictability_relative_ratio
    threshold = min(
        calibration.spatial_predictability_max_bad_corr,
        relative_threshold,
        robust_threshold,
    )
    if not np.isfinite(threshold) or threshold <= 0.0:
        return None
    return float(threshold)


def spatial_predictability_outliers(
    scores: dict[str, float],
    *,
    excluded_channels: list[str] | tuple[str, ...],
    calibration: Any,
    min_reference_count: int,
) -> tuple[str, ...]:
    """Return channels with poor spatial predictability under the calibration."""
    excluded = {str(channel) for channel in excluded_channels}
    reference_scores = [
        float(score)
        for channel, score in scores.items()
        if channel not in excluded and np.isfinite(score)
    ]
    threshold = spatial_predictability_threshold(
        reference_scores,
        calibration=calibration,
        min_reference_count=min_reference_count,
    )
    if threshold is None:
        return ()

    return tuple(
        channel
        for channel, score in scores.items()
        if channel not in excluded and np.isfinite(score) and float(score) < threshold
    )


__all__ = [
    "DEFAULT_REMOVED_ELECTRODE_DETECTION_CALIBRATION",
    "REMOVED_ELECTRODE_DETECTION_INFO_TEXT",
    "REMOVED_ELECTRODE_DETECTION_MODE_AUTO",
    "REMOVED_ELECTRODE_DETECTION_MODE_MANUAL",
    "REMOVED_ELECTRODE_DETECTION_MODE_OFF",
    "REMOVED_ELECTRODE_DETECTION_MODES",
    "RemovedElectrodeDetectionCalibration",
    "build_removed_electrode_review_record",
    "canonicalize_electrode_name",
    "is_high_amplitude_removed_channel",
    "is_low_variance_removed_channel",
    "manual_removed_electrodes_for_pid",
    "normalize_manual_removed_electrodes_map",
    "normalize_removed_electrode_detection_mode",
    "parse_electrode_list",
    "removed_electrode_agreement_status",
    "removed_electrode_threshold_payload",
    "spatial_predictability_outliers",
    "spatial_predictability_threshold",
]
