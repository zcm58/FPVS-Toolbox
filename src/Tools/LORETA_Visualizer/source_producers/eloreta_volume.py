"""Beta eLORETA volume source producer.

This module owns calculation-side eLORETA volume source-space z-score maps for
FPVS frequency-domain inputs. It writes prepared JSON payloads for the
visualizer validator/importer. It does not import GUI, renderer, display mesh,
display transforms, or prepared-payload importer code.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from Tools.LORETA_Visualizer.prepared_payload_validator import (
    PREPARED_SOURCE_MANIFEST_FORMAT,
    PREPARED_SOURCE_PAYLOAD_FORMAT,
    validate_prepared_source_manifest_json,
    validate_prepared_source_payload_json,
    validate_prepared_source_payload_mapping,
)
from Tools.LORETA_Visualizer.source_producers.contracts import ProducedPayload, SourceProducerRunResult
from Tools.LORETA_Visualizer.source_producers.l2_mne_cortical import (
    DEFAULT_LAMBDA2,
    HARMONIC_STRATEGY_SUM_SENSOR_TOPOGRAPHIES_THEN_INVERT,
    _array_to_json_rows,
    _array_to_json_values,
    _json_safe_metadata,
    _round_harmonic,
    _slug,
    _validate_harmonics,
    _validate_label,
    _validate_matrix,
    _validate_points,
)
from Tools.LORETA_Visualizer.source_producers.l2_mne_hauk_zscore import (
    CLUSTER_MASK_METHOD_SOURCE_SPACE_SIGN_FLIP_POSITIVE,
    CLUSTER_MASK_STATUS_DISABLED,
    DEFAULT_CLUSTER_ALPHA,
    DEFAULT_CLUSTER_FORMING_P_VALUE,
    DEFAULT_CLUSTER_MASK_ENABLED,
    DEFAULT_CLUSTER_PERMUTATION_COUNT,
    DEFAULT_CLUSTER_PERMUTATION_SEED,
    DEFAULT_CLUSTER_TAIL,
    DEFAULT_HAUK_ZSCORE_EXCLUDED_OFFSETS,
    DEFAULT_HAUK_ZSCORE_MIN_NOISE_BINS,
    DEFAULT_HAUK_ZSCORE_NOISE_WINDOW_BINS,
    DEFAULT_PARTICIPANT_ZSCORE_AGGREGATIONS,
    DEFAULT_PARTICIPANT_ZSCORE_TRIM_FRACTION,
    L2MNEHaukHarmonicBins,
    L2MNEHaukParticipantGroupCondition,
    L2MNEHaukZScoreCondition,
    PARTICIPANT_SOURCE_MAP_SIDECAR_FORMAT,
    PARTICIPANT_ZSCORE_AGGREGATION_MEAN,
    PARTICIPANT_ZSCORE_AGGREGATION_MEDIAN,
    PARTICIPANT_ZSCORE_AGGREGATION_METHOD_IDS,
    PARTICIPANT_ZSCORE_AGGREGATION_TRIMMED_MEAN,
)
from Tools.LORETA_Visualizer.source_producers.source_space_statistics import (
    CLUSTER_TAIL_POSITIVE,
    SourceSpaceClusterPermutationResult,
    compute_source_space_cluster_permutation_mask,
    validate_adjacency,
)

logger = logging.getLogger(__name__)
ProgressCallback = Callable[[str], None]

METHOD_ID_ELORETA_VOLUME_HAUK_ZSCORE_BETA = "eloreta_volume_hauk_zscore_beta"
METHOD_ID_ELORETA_VOLUME_PARTICIPANT_ZSCORE = "eloreta_volume_participant_zscore"
METHOD_ID_ELORETA_VOLUME_PARTICIPANT_ZSCORE_MEAN = "eloreta_volume_participant_zscore_mean"
METHOD_ID_ELORETA_VOLUME_PARTICIPANT_ZSCORE_MEDIAN = "eloreta_volume_participant_zscore_median"
METHOD_ID_ELORETA_VOLUME_PARTICIPANT_ZSCORE_TRIMMED_MEAN = (
    "eloreta_volume_participant_zscore_trimmed_mean"
)
ELORETA_PARTICIPANT_ZSCORE_AGGREGATION_METHOD_IDS = {
    PARTICIPANT_ZSCORE_AGGREGATION_MEAN: METHOD_ID_ELORETA_VOLUME_PARTICIPANT_ZSCORE_MEAN,
    PARTICIPANT_ZSCORE_AGGREGATION_MEDIAN: METHOD_ID_ELORETA_VOLUME_PARTICIPANT_ZSCORE_MEDIAN,
    PARTICIPANT_ZSCORE_AGGREGATION_TRIMMED_MEAN: METHOD_ID_ELORETA_VOLUME_PARTICIPANT_ZSCORE_TRIMMED_MEAN,
}
COORDINATE_SPACE_FSAVERAGE_VOLUME = "fsaverage_volume"
SOURCE_KIND_VOLUME_POINTS = "volume_points"
SOURCE_METHOD_ELORETA_VOLUME = "eloreta_volume"


@dataclass(frozen=True)
class ELORETAVolumeZScoreConfig:
    """Configuration for beta eLORETA volume source-space z-score maps."""

    selected_harmonics_hz: tuple[float, ...]
    method_id: str = METHOD_ID_ELORETA_VOLUME_HAUK_ZSCORE_BETA
    lambda2: float = DEFAULT_LAMBDA2
    harmonic_strategy: str = HARMONIC_STRATEGY_SUM_SENSOR_TOPOGRAPHIES_THEN_INVERT
    apply_average_reference: bool = True
    noise_window_bins: int = DEFAULT_HAUK_ZSCORE_NOISE_WINDOW_BINS
    min_noise_bins: int = DEFAULT_HAUK_ZSCORE_MIN_NOISE_BINS
    excluded_noise_offsets: tuple[int, ...] = DEFAULT_HAUK_ZSCORE_EXCLUDED_OFFSETS
    drop_min_max_noise_per_source: bool = True
    cluster_mask_enabled: bool = DEFAULT_CLUSTER_MASK_ENABLED
    cluster_forming_p_value: float = DEFAULT_CLUSTER_FORMING_P_VALUE
    cluster_alpha: float = DEFAULT_CLUSTER_ALPHA
    cluster_permutation_count: int = DEFAULT_CLUSTER_PERMUTATION_COUNT
    cluster_permutation_seed: int = DEFAULT_CLUSTER_PERMUTATION_SEED
    cluster_tail: str = DEFAULT_CLUSTER_TAIL
    eloreta_method_params: Mapping[str, Any] = field(default_factory=dict)
    montage_name: str = "BioSemi ActiveTwo 64-channel 10-10"
    harmonic_policy_id: str = "stats_group_significant_oddball_harmonics"
    template_subject: str = "fsaverage"
    value_label: str = "source-space z-score"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        selected = _validate_harmonics(self.selected_harmonics_hz)
        lambda2 = float(self.lambda2)
        if not np.isfinite(lambda2) or lambda2 <= 0.0:
            raise ValueError("eLORETA volume lambda2 must be positive and finite.")
        if self.harmonic_strategy != HARMONIC_STRATEGY_SUM_SENSOR_TOPOGRAPHIES_THEN_INVERT:
            raise ValueError("eLORETA volume currently supports summed sensor topographies before inversion only.")
        noise_window_bins = int(self.noise_window_bins)
        min_noise_bins = int(self.min_noise_bins)
        if noise_window_bins < 2:
            raise ValueError("eLORETA z-score noise window must include at least two bins on each side.")
        if min_noise_bins < 2:
            raise ValueError("eLORETA z-score min_noise_bins must be at least 2.")
        excluded = tuple(sorted({int(offset) for offset in self.excluded_noise_offsets}))
        if 0 not in excluded:
            raise ValueError("eLORETA z-score excluded noise offsets must include the target offset 0.")
        cluster_forming_p = _validate_probability(self.cluster_forming_p_value, "cluster_forming_p_value")
        cluster_alpha = _validate_probability(self.cluster_alpha, "cluster_alpha")
        cluster_permutation_count = int(self.cluster_permutation_count)
        if cluster_permutation_count < 1:
            raise ValueError("Cluster permutation count must be at least 1.")
        cluster_tail = str(self.cluster_tail).strip().lower()
        if cluster_tail != CLUSTER_TAIL_POSITIVE:
            raise ValueError("Hauk-style source-space cluster masking uses positive-tail testing only.")
        object.__setattr__(self, "selected_harmonics_hz", selected)
        object.__setattr__(self, "lambda2", lambda2)
        object.__setattr__(self, "noise_window_bins", noise_window_bins)
        object.__setattr__(self, "min_noise_bins", min_noise_bins)
        object.__setattr__(self, "excluded_noise_offsets", excluded)
        object.__setattr__(self, "cluster_mask_enabled", bool(self.cluster_mask_enabled))
        object.__setattr__(self, "cluster_forming_p_value", cluster_forming_p)
        object.__setattr__(self, "cluster_alpha", cluster_alpha)
        object.__setattr__(self, "cluster_permutation_count", cluster_permutation_count)
        object.__setattr__(self, "cluster_permutation_seed", int(self.cluster_permutation_seed))
        object.__setattr__(self, "cluster_tail", cluster_tail)
        object.__setattr__(self, "eloreta_method_params", dict(self.eloreta_method_params))
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True)
class ELORETAVolumeForwardModel:
    """Source-ready volume forward/inverse model for eLORETA."""

    channel_names: tuple[str, ...]
    source_points: np.ndarray
    leadfield: np.ndarray
    source_adjacency: Sequence[set[int]]
    coordinate_space: str = COORDINATE_SPACE_FSAVERAGE_VOLUME
    label: str = "fsaverage volume source space"
    metadata: Mapping[str, Any] = field(default_factory=dict)
    source_estimator: Callable[..., Sequence[float] | np.ndarray] | None = None
    source_indices: Sequence[int] | None = None

    def __post_init__(self) -> None:
        channels = tuple(_validate_label(name, "channel_name") for name in self.channel_names)
        if not channels:
            raise ValueError("eLORETA volume forward model requires at least one channel.")
        if len(set(channels)) != len(channels):
            raise ValueError("eLORETA volume forward model channel names must be unique.")
        points = _validate_points(self.source_points, field_name="source_points")
        leadfield = _validate_matrix(self.leadfield, field_name="leadfield")
        if leadfield.shape[0] != len(channels):
            raise ValueError(
                "eLORETA volume leadfield must have one row per channel "
                f"({len(channels)} expected, got {leadfield.shape[0]})."
            )
        if self.source_estimator is None or not callable(self.source_estimator):
            raise TypeError("eLORETA volume source_estimator must be callable.")
        adjacency = validate_adjacency(self.source_adjacency, source_count=len(points))
        source_indices = _validate_optional_source_indices(self.source_indices, source_count=len(points))
        object.__setattr__(self, "channel_names", channels)
        object.__setattr__(self, "source_points", points)
        object.__setattr__(self, "leadfield", leadfield)
        object.__setattr__(self, "source_adjacency", adjacency)
        object.__setattr__(self, "coordinate_space", _validate_label(self.coordinate_space, "coordinate_space"))
        object.__setattr__(self, "label", _validate_label(self.label, "label"))
        object.__setattr__(self, "metadata", dict(self.metadata))
        object.__setattr__(self, "source_indices", source_indices)


@dataclass(frozen=True)
class ELORETAVolumeZScoreValues:
    """Computed eLORETA volume z-score result and diagnostic arrays."""

    values: np.ndarray
    target_source_values: np.ndarray
    noise_mean_values: np.ndarray
    noise_std_values: np.ndarray
    noise_offsets_used: tuple[int, ...]
    zero_noise_sd_source_count: int


@dataclass(frozen=True)
class ELORETAVolumeParticipantZScoreValues:
    """One participant's computed eLORETA volume z-score map."""

    participant_id: str
    values: np.ndarray
    target_source_values: np.ndarray
    noise_mean_values: np.ndarray
    noise_std_values: np.ndarray
    noise_offsets_used: tuple[int, ...]
    zero_noise_sd_source_count: int


@dataclass(frozen=True)
class ELORETAVolumeParticipantZScoreSummary:
    """Group summary over participant-level eLORETA volume maps."""

    aggregation: str
    label_suffix: str
    method_id: str
    values: np.ndarray
    participant_count: int
    trim_fraction: float | None = None


@dataclass(frozen=True)
class ELORETAVolumeParticipantZScoreWriteResult:
    """Participant-first eLORETA output files plus the producer result."""

    producer_result: SourceProducerRunResult
    participant_sidecar_path: Path


def compute_eloreta_volume_zscore_source_values(
    *,
    forward_model: ELORETAVolumeForwardModel,
    condition: L2MNEHaukZScoreCondition,
    config: ELORETAVolumeZScoreConfig,
) -> ELORETAVolumeZScoreValues:
    """Compute Hauk-style eLORETA volume source-space z-scores for one condition."""
    harmonic_bins = _selected_harmonic_bins(condition, config=config, n_channels=len(forward_model.channel_names))
    common_offsets = _common_noise_offsets(harmonic_bins, config=config)
    if len(common_offsets) < config.min_noise_bins:
        raise ValueError(
            f"{condition.label} has {len(common_offsets)} common neighboring-bin offsets; "
            f"{config.min_noise_bins} are required for eLORETA source-space z-scores."
        )

    target_topography = np.zeros(len(forward_model.channel_names), dtype=float)
    for bin_set in harmonic_bins:
        target_topography += _prepare_topography(
            bin_set.target_topography,
            apply_average_reference=config.apply_average_reference,
        )

    noise_topographies: list[np.ndarray] = []
    for offset in common_offsets:
        noise_topography = np.zeros(len(forward_model.channel_names), dtype=float)
        for bin_set in harmonic_bins:
            noise_topography += _prepare_topography(
                bin_set.noise_topographies_by_offset[offset],
                apply_average_reference=config.apply_average_reference,
            )
        noise_topographies.append(noise_topography)
    topographies = np.vstack((target_topography, *noise_topographies))
    source_values = _source_amplitudes_from_topographies(
        forward_model,
        topographies,
        lambda2=config.lambda2,
        method_params=config.eloreta_method_params,
    )
    target_source_values = source_values[0]
    noise_source_values = source_values[1:]
    used_noise = _drop_extreme_noise_rows(noise_source_values) if config.drop_min_max_noise_per_source else noise_source_values
    noise_mean = np.mean(used_noise, axis=0)
    noise_std = np.std(used_noise, axis=0, ddof=0)
    valid = np.isfinite(noise_std) & (noise_std > 1e-12)
    if not np.any(valid):
        raise ValueError(f"{condition.label} has no volume source points with finite neighboring-bin noise SD.")
    z_values = np.zeros_like(target_source_values, dtype=float)
    z_values[valid] = (target_source_values[valid] - noise_mean[valid]) / noise_std[valid]
    if not np.all(np.isfinite(z_values)):
        raise ValueError("eLORETA volume produced non-finite source z-score values.")
    return ELORETAVolumeZScoreValues(
        values=z_values.astype(float),
        target_source_values=target_source_values.astype(float),
        noise_mean_values=noise_mean.astype(float),
        noise_std_values=noise_std.astype(float),
        noise_offsets_used=tuple(common_offsets),
        zero_noise_sd_source_count=int(np.count_nonzero(~valid)),
    )


def compute_eloreta_volume_participant_zscore_source_values(
    *,
    forward_model: ELORETAVolumeForwardModel,
    condition: L2MNEHaukParticipantGroupCondition,
    config: ELORETAVolumeZScoreConfig,
) -> tuple[ELORETAVolumeParticipantZScoreValues, ...]:
    """Compute eLORETA volume z-score maps independently for each participant."""
    rows: list[ELORETAVolumeParticipantZScoreValues] = []
    for participant in condition.participants:
        result = compute_eloreta_volume_zscore_source_values(
            forward_model=forward_model,
            condition=participant.condition,
            config=config,
        )
        rows.append(
            ELORETAVolumeParticipantZScoreValues(
                participant_id=participant.participant_id,
                values=result.values,
                target_source_values=result.target_source_values,
                noise_mean_values=result.noise_mean_values,
                noise_std_values=result.noise_std_values,
                noise_offsets_used=result.noise_offsets_used,
                zero_noise_sd_source_count=result.zero_noise_sd_source_count,
            )
        )
    return tuple(rows)


def summarize_eloreta_volume_participant_zscores(
    participant_values: Sequence[ELORETAVolumeParticipantZScoreValues],
    *,
    aggregation: str,
    trim_fraction: float = DEFAULT_PARTICIPANT_ZSCORE_TRIM_FRACTION,
) -> ELORETAVolumeParticipantZScoreSummary:
    """Summarize participant eLORETA z-score maps with a deterministic aggregator."""
    aggregation_id = _validate_participant_zscore_aggregation(aggregation)
    rows = tuple(participant_values)
    if not rows:
        raise ValueError("Participant z-score aggregation requires at least one participant map.")
    matrix = np.vstack([np.asarray(row.values, dtype=float).reshape(1, -1) for row in rows])
    if not np.all(np.isfinite(matrix)):
        raise ValueError("Participant eLORETA source z-score maps contain non-finite values.")
    if aggregation_id == PARTICIPANT_ZSCORE_AGGREGATION_MEAN:
        values = np.mean(matrix, axis=0)
        label_suffix = "Raw mean z-score"
        summary_trim_fraction: float | None = None
    elif aggregation_id == PARTICIPANT_ZSCORE_AGGREGATION_MEDIAN:
        values = np.median(matrix, axis=0)
        label_suffix = "Median z-score"
        summary_trim_fraction = None
    else:
        trim_fraction = _validate_trim_fraction(trim_fraction)
        values = _trimmed_mean(matrix, trim_fraction=trim_fraction)
        label_suffix = f"{trim_fraction:.0%} trimmed mean z-score"
        summary_trim_fraction = trim_fraction
    return ELORETAVolumeParticipantZScoreSummary(
        aggregation=aggregation_id,
        label_suffix=label_suffix,
        method_id=ELORETA_PARTICIPANT_ZSCORE_AGGREGATION_METHOD_IDS[aggregation_id],
        values=np.asarray(values, dtype=float),
        participant_count=len(rows),
        trim_fraction=summary_trim_fraction,
    )


def compute_eloreta_volume_source_cluster_mask(
    participant_values: Sequence[ELORETAVolumeParticipantZScoreValues],
    *,
    source_adjacency: Sequence[set[int]],
    config: ELORETAVolumeZScoreConfig,
) -> SourceSpaceClusterPermutationResult:
    """Compute a Hauk-style cluster mask across eLORETA volume participant maps."""
    return compute_source_space_cluster_permutation_mask(
        participant_values,
        adjacency=source_adjacency,
        cluster_forming_p_value=config.cluster_forming_p_value,
        cluster_alpha=config.cluster_alpha,
        permutation_count=config.cluster_permutation_count,
        permutation_seed=config.cluster_permutation_seed,
        tail=config.cluster_tail,
    )


def build_eloreta_volume_participant_zscore_summary_payload(
    *,
    forward_model: ELORETAVolumeForwardModel,
    condition: L2MNEHaukParticipantGroupCondition,
    config: ELORETAVolumeZScoreConfig,
    participant_values: Sequence[ELORETAVolumeParticipantZScoreValues],
    summary: ELORETAVolumeParticipantZScoreSummary,
    cluster_result: SourceSpaceClusterPermutationResult | None = None,
) -> dict[str, Any]:
    """Build one renderer-ready eLORETA group summary payload."""
    values = np.asarray(summary.values, dtype=float).reshape(-1)
    if len(values) != len(forward_model.source_points):
        raise ValueError(
            f"Participant eLORETA summary has {len(values)} source values; "
            f"{len(forward_model.source_points)} expected."
        )
    payload = {
        "format": PREPARED_SOURCE_PAYLOAD_FORMAT,
        "label": f"{condition.label} eLORETA volume {summary.label_suffix}",
        "kind": SOURCE_KIND_VOLUME_POINTS,
        "coordinate_space": forward_model.coordinate_space,
        "source_model": summary.method_id,
        "value_label": config.value_label,
        "points": _array_to_json_rows(forward_model.source_points),
        "values": _array_to_json_values(values),
        "metadata": _participant_summary_payload_metadata(
            forward_model=forward_model,
            condition=condition,
            config=config,
            participant_values=participant_values,
            summary=summary,
            cluster_result=cluster_result,
        ),
    }
    validate_prepared_source_payload_mapping(payload)
    return payload


def write_eloreta_volume_participant_zscore_payloads(
    *,
    forward_model: ELORETAVolumeForwardModel,
    conditions: Sequence[L2MNEHaukParticipantGroupCondition],
    config: ELORETAVolumeZScoreConfig,
    output_dir: str | Path,
    manifest_name: str = "eloreta_volume_participant_zscore_manifest.json",
    aggregations: Sequence[str] = DEFAULT_PARTICIPANT_ZSCORE_AGGREGATIONS,
    trim_fraction: float = DEFAULT_PARTICIPANT_ZSCORE_TRIM_FRACTION,
    participant_sidecar_name: str = "participant_eloreta_volume_hauk_zscore_maps.json",
    progress_callback: ProgressCallback | None = None,
) -> ELORETAVolumeParticipantZScoreWriteResult:
    """Write participant-first eLORETA volume summaries and sidecar JSON."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    condition_list = tuple(conditions)
    if not condition_list:
        raise ValueError("Participant-first eLORETA volume producer requires at least one condition.")
    aggregation_list = tuple(_validate_participant_zscore_aggregation(value) for value in aggregations)
    if not aggregation_list:
        raise ValueError("Participant-first eLORETA volume producer requires at least one aggregation.")
    trim_fraction = _validate_trim_fraction(trim_fraction)

    emitted: list[ProducedPayload] = []
    manifest_conditions: list[dict[str, Any]] = []
    used_file_names: set[str] = set()
    participant_rows_by_condition: dict[str, tuple[ELORETAVolumeParticipantZScoreValues, ...]] = {}
    cluster_results_by_condition: dict[str, SourceSpaceClusterPermutationResult | None] = {}
    for condition_index, condition in enumerate(condition_list, start=1):
        _emit_progress(
            progress_callback,
            (
                f"Computing participant eLORETA volume z-scores for condition "
                f"{condition_index}/{len(condition_list)}: {condition.label}..."
            ),
        )
        participant_rows = compute_eloreta_volume_participant_zscore_source_values(
            forward_model=forward_model,
            condition=condition,
            config=config,
        )
        participant_rows_by_condition[condition.condition_id] = participant_rows
        cluster_result = None
        if config.cluster_mask_enabled:
            _emit_progress(progress_callback, f"Computing eLORETA volume cluster mask for {condition.label}...")
            cluster_result = compute_eloreta_volume_source_cluster_mask(
                participant_rows,
                source_adjacency=forward_model.source_adjacency,
                config=config,
            )
            _emit_progress(
                progress_callback,
                (
                    f"eLORETA volume cluster mask for {condition.label}: "
                    f"{int(np.count_nonzero(cluster_result.mask))} source point(s) retained."
                ),
            )
        cluster_results_by_condition[condition.condition_id] = cluster_result
        for aggregation in aggregation_list:
            summary = summarize_eloreta_volume_participant_zscores(
                participant_rows,
                aggregation=aggregation,
                trim_fraction=trim_fraction,
            )
            _emit_progress(progress_callback, f"Writing {condition.label} eLORETA {summary.label_suffix} JSON...")
            payload = build_eloreta_volume_participant_zscore_summary_payload(
                forward_model=forward_model,
                condition=condition,
                config=config,
                participant_values=participant_rows,
                summary=summary,
                cluster_result=cluster_result,
            )
            condition_payload_id = f"{condition.condition_id}_{summary.aggregation}"
            file_name = _unique_participant_payload_file_name(condition.condition_id, summary.aggregation, used_file_names)
            payload_path = output_path / file_name
            _write_json(payload_path, payload)
            validation = validate_prepared_source_payload_json(payload_path)
            emitted.append(
                ProducedPayload(
                    condition_id=condition_payload_id,
                    label=payload["label"],
                    payload_path=payload_path,
                    validation=validation,
                )
            )
            manifest_conditions.append(
                {
                    "id": condition_payload_id,
                    "label": payload["label"],
                    "file": file_name,
                    "metadata": {
                        "source_method": SOURCE_METHOD_ELORETA_VOLUME,
                        "producer_method": summary.method_id,
                        "base_producer_method": METHOD_ID_ELORETA_VOLUME_PARTICIPANT_ZSCORE,
                        "participant_zscore_aggregation": summary.aggregation,
                        "selected_harmonics_hz": list(config.selected_harmonics_hz),
                        "value_label": config.value_label,
                        "source_value_unit": "z-score",
                        **_cluster_manifest_entry_metadata(cluster_result),
                    },
                }
            )

    sidecar_path = output_path / participant_sidecar_name
    _emit_progress(progress_callback, "Writing eLORETA participant source-map sidecar...")
    _write_json(
        sidecar_path,
        _participant_zscore_sidecar_payload(
            forward_model=forward_model,
            conditions=condition_list,
            config=config,
            participant_rows_by_condition=participant_rows_by_condition,
            cluster_results_by_condition=cluster_results_by_condition,
        ),
    )

    manifest = {
        "format": PREPARED_SOURCE_MANIFEST_FORMAT,
        "label": "eLORETA volume participant-first source-space z-score maps",
        "conditions": manifest_conditions,
        "metadata": {
            "source_method": SOURCE_METHOD_ELORETA_VOLUME,
            "producer_method": METHOD_ID_ELORETA_VOLUME_PARTICIPANT_ZSCORE,
            "aggregation_methods": list(aggregation_list),
            "participant_sidecar_file": sidecar_path.name,
            "cluster_mask": (
                "source_space_cluster_permutation" if config.cluster_mask_enabled else CLUSTER_MASK_STATUS_DISABLED
            ),
            "cluster_mask_method": (
                _cluster_mask_method_label(config.cluster_tail) if config.cluster_mask_enabled else "none"
            ),
        },
    }
    manifest_path = output_path / manifest_name
    _emit_progress(progress_callback, "Writing eLORETA source-map manifest...")
    _write_json(manifest_path, manifest)
    _emit_progress(progress_callback, "Validating eLORETA source-map manifest...")
    manifest_validation = validate_prepared_source_manifest_json(manifest_path, require_payload_files=True)
    logger.info(
        "eloreta_volume_participant_zscore_payloads_written",
        extra={
            "output_dir": str(output_path),
            "condition_count": len(condition_list),
            "payload_count": len(emitted),
            "participant_sidecar_path": str(sidecar_path),
        },
    )
    return ELORETAVolumeParticipantZScoreWriteResult(
        producer_result=SourceProducerRunResult(
            method_id=METHOD_ID_ELORETA_VOLUME_PARTICIPANT_ZSCORE,
            output_dir=output_path,
            manifest_path=manifest_path,
            payloads=tuple(emitted),
            manifest_validation=manifest_validation,
        ),
        participant_sidecar_path=sidecar_path,
    )


def _source_amplitudes_from_topographies(
    forward_model: ELORETAVolumeForwardModel,
    topographies: np.ndarray,
    *,
    lambda2: float,
    method_params: Mapping[str, Any],
) -> np.ndarray:
    topography_matrix = np.asarray(topographies, dtype=float)
    if topography_matrix.ndim == 1:
        topography_matrix = topography_matrix.reshape(1, -1)
    if topography_matrix.ndim != 2 or topography_matrix.shape[1] != len(forward_model.channel_names):
        raise ValueError(
            "eLORETA source estimator expected "
            f"{len(forward_model.channel_names)} channel values; got shape {topography_matrix.shape}."
        )
    values = forward_model.source_estimator(
        topography_matrix,
        lambda2=float(lambda2),
        method_params=dict(method_params),
    )
    source_values = np.asarray(values, dtype=float)
    if source_values.ndim == 1:
        source_values = source_values.reshape(1, -1)
    expected_shape = (topography_matrix.shape[0], len(forward_model.source_points))
    if source_values.shape != expected_shape:
        raise ValueError(
            "eLORETA source estimator returned "
            f"{source_values.shape}; expected {expected_shape}."
        )
    if not np.all(np.isfinite(source_values)):
        raise ValueError("eLORETA source estimator returned non-finite source values.")
    return np.abs(source_values).astype(float)


def _selected_harmonic_bins(
    condition: L2MNEHaukZScoreCondition,
    *,
    config: ELORETAVolumeZScoreConfig,
    n_channels: int,
) -> tuple[L2MNEHaukHarmonicBins, ...]:
    rows: list[L2MNEHaukHarmonicBins] = []
    for harmonic in config.selected_harmonics_hz:
        key = _round_harmonic(harmonic)
        try:
            bin_set = condition.harmonic_bins[key]
        except KeyError as exc:
            raise ValueError(f"Condition {condition.label!r} is missing selected harmonic {key:g} Hz.") from exc
        if len(bin_set.target_topography) != n_channels:
            raise ValueError(
                f"Condition {condition.label!r} harmonic {key:g} Hz has "
                f"{len(bin_set.target_topography)} channels; {n_channels} expected."
            )
        rows.append(bin_set)
    return tuple(rows)


def _common_noise_offsets(
    harmonic_bins: Sequence[L2MNEHaukHarmonicBins],
    *,
    config: ELORETAVolumeZScoreConfig,
) -> tuple[int, ...]:
    if not harmonic_bins:
        return ()
    common = set(next(iter(harmonic_bins)).noise_topographies_by_offset)
    for bin_set in harmonic_bins[1:]:
        common.intersection_update(bin_set.noise_topographies_by_offset)
    excluded = set(config.excluded_noise_offsets)
    return tuple(sorted(offset for offset in common if offset not in excluded))


def _prepare_topography(values: Sequence[float], *, apply_average_reference: bool) -> np.ndarray:
    topography = np.asarray(values, dtype=float).reshape(-1)
    if apply_average_reference:
        topography = topography - float(np.mean(topography))
    return topography.astype(float)


def _drop_extreme_noise_rows(noise_source_values: np.ndarray) -> np.ndarray:
    if noise_source_values.shape[0] <= 2:
        return noise_source_values
    return np.sort(noise_source_values, axis=0)[1:-1, :]


def _validate_participant_zscore_aggregation(value: str) -> str:
    aggregation = str(value).strip().lower()
    if aggregation not in PARTICIPANT_ZSCORE_AGGREGATION_METHOD_IDS:
        valid = ", ".join(PARTICIPANT_ZSCORE_AGGREGATION_METHOD_IDS)
        raise ValueError(f"Unsupported participant z-score aggregation {value!r}; expected one of: {valid}.")
    return aggregation


def _validate_trim_fraction(value: float) -> float:
    fraction = float(value)
    if not np.isfinite(fraction) or fraction < 0.0 or fraction >= 0.5:
        raise ValueError("Participant z-score trim_fraction must be >= 0 and < 0.5.")
    return fraction


def _trimmed_mean(values: np.ndarray, *, trim_fraction: float) -> np.ndarray:
    matrix = np.asarray(values, dtype=float)
    trim_count = int(np.floor(matrix.shape[0] * float(trim_fraction)))
    if trim_count <= 0 or (2 * trim_count) >= matrix.shape[0]:
        return np.mean(matrix, axis=0)
    sorted_values = np.sort(matrix, axis=0)
    return np.mean(sorted_values[trim_count : matrix.shape[0] - trim_count, :], axis=0)


def _validate_probability(value: float, label: str) -> float:
    probability = float(value)
    if not np.isfinite(probability) or probability <= 0.0 or probability >= 1.0:
        raise ValueError(f"{label} must be > 0 and < 1.")
    return probability


def _validate_optional_source_indices(values: Sequence[int] | None, *, source_count: int) -> tuple[int, ...] | None:
    if values is None:
        return None
    indices = tuple(int(value) for value in values)
    if len(indices) != int(source_count):
        raise ValueError(f"eLORETA source indices must contain {source_count} entries; got {len(indices)}.")
    if any(index < 0 for index in indices):
        raise ValueError("eLORETA source indices must be non-negative.")
    return indices


def _cluster_mask_method_label(tail: str) -> str:
    cluster_tail = str(tail).strip().lower()
    if cluster_tail != CLUSTER_TAIL_POSITIVE:
        raise ValueError("Hauk-style source-space cluster masking uses positive-tail testing only.")
    return CLUSTER_MASK_METHOD_SOURCE_SPACE_SIGN_FLIP_POSITIVE


def _source_identity_metadata(forward_model: ELORETAVolumeForwardModel) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    if forward_model.source_indices is not None:
        metadata["source_indices"] = [int(index) for index in forward_model.source_indices]
        metadata["source_index_source"] = "MNE volume source-space vertno values"
    return metadata


def _cluster_payload_metadata(
    cluster_result: SourceSpaceClusterPermutationResult | None,
    *,
    config: ELORETAVolumeZScoreConfig,
) -> dict[str, Any]:
    if not config.cluster_mask_enabled:
        return {
            "cluster_mask": CLUSTER_MASK_STATUS_DISABLED,
            "cluster_mask_primary_display": False,
            "cluster_mask_method": "none",
        }
    if cluster_result is None:
        return {
            "cluster_mask": "none",
            "cluster_mask_primary_display": False,
            "cluster_mask_method": "none",
        }
    retained = np.flatnonzero(cluster_result.mask).astype(int)
    significant_clusters = cluster_result.significant_clusters
    return {
        "cluster_mask": "source_space_cluster_permutation",
        "cluster_mask_status": cluster_result.status,
        "cluster_mask_primary_display": True,
        "cluster_mask_method": _cluster_mask_method_label(cluster_result.tail),
        "cluster_mask_source_space_kind": "volume",
        "cluster_adjacency_source": "mne.spatial_src_adjacency_or_equivalent",
        "cluster_mask_publication_alignment": "Hauk et al. 2025 FPVS_WORDS source-space cluster strategy",
        "cluster_mask_note": (
            "Renderer uses this producer-computed source-space mask as the primary "
            "publication-style eLORETA volume display mask; source values remain unchanged."
        ),
        "cluster_mask_source_indices": [int(index) for index in retained],
        "cluster_mask_source_index_count": int(len(retained)),
        "cluster_mask_source_count": int(len(cluster_result.mask)),
        "cluster_forming_statistic": "one_sample_t_against_zero",
        "cluster_forming_tail": cluster_result.tail,
        "cluster_forming_p_value": float(cluster_result.cluster_forming_p_value),
        "cluster_forming_threshold": float(cluster_result.cluster_forming_threshold),
        "cluster_alpha": float(cluster_result.cluster_alpha),
        "cluster_permutation_count": int(cluster_result.permutation_count),
        "cluster_permutation_seed": int(cluster_result.permutation_seed),
        "cluster_candidate_count": int(len(cluster_result.clusters)),
        "cluster_significant_cluster_count": int(len(significant_clusters)),
        "cluster_significant_clusters": [
            {
                "cluster_id": int(cluster.cluster_id),
                "tail": str(cluster.tail),
                "source_count": int(len(cluster.source_indices)),
                "cluster_mass": float(cluster.cluster_mass),
                "p_value": float(cluster.p_value),
            }
            for cluster in significant_clusters
        ],
    }


def _cluster_manifest_entry_metadata(
    cluster_result: SourceSpaceClusterPermutationResult | None,
) -> dict[str, Any]:
    if cluster_result is None:
        return {
            "cluster_mask": "none",
            "cluster_mask_source_index_count": 0,
            "cluster_significant_cluster_count": 0,
        }
    return {
        "cluster_mask": "source_space_cluster_permutation",
        "cluster_mask_status": cluster_result.status,
        "cluster_mask_source_index_count": int(np.count_nonzero(cluster_result.mask)),
        "cluster_mask_source_count": int(len(cluster_result.mask)),
        "cluster_significant_cluster_count": int(len(cluster_result.significant_clusters)),
        "cluster_forming_p_value": float(cluster_result.cluster_forming_p_value),
        "cluster_forming_tail": cluster_result.tail,
        "cluster_forming_threshold": float(cluster_result.cluster_forming_threshold),
        "cluster_alpha": float(cluster_result.cluster_alpha),
        "cluster_permutation_count": int(cluster_result.permutation_count),
    }


def _participant_summary_payload_metadata(
    *,
    forward_model: ELORETAVolumeForwardModel,
    condition: L2MNEHaukParticipantGroupCondition,
    config: ELORETAVolumeZScoreConfig,
    participant_values: Sequence[ELORETAVolumeParticipantZScoreValues],
    summary: ELORETAVolumeParticipantZScoreSummary,
    cluster_result: SourceSpaceClusterPermutationResult | None = None,
) -> dict[str, Any]:
    rows = tuple(participant_values)
    participant_ids = [row.participant_id for row in rows]
    common_offsets = sorted({offset for row in rows for offset in row.noise_offsets_used})
    metadata = {
        "beta": True,
        "source_method": SOURCE_METHOD_ELORETA_VOLUME,
        "producer_method": summary.method_id,
        "base_producer_method": METHOD_ID_ELORETA_VOLUME_PARTICIPANT_ZSCORE,
        "inverse_method": "eLORETA",
        "source_space": "volume",
        "source_model": "eloreta_volume",
        "source_map_model": "participant_first",
        "template_subject": config.template_subject,
        "montage_name": config.montage_name,
        "coordinate_space": forward_model.coordinate_space,
        "forward_model_label": forward_model.label,
        "harmonic_policy_id": config.harmonic_policy_id,
        "selected_harmonics_hz": list(config.selected_harmonics_hz),
        "harmonic_strategy": config.harmonic_strategy,
        "participant_zscore_order": [
            "read participant sensor FFT amplitude target/noise-bin topographies",
            "sum selected significant harmonics in sensor space",
            "estimate eLORETA volume values for each participant summed target and noise topography",
            "compute participant source-space z-score maps",
            "aggregate participant z-score maps for group display",
        ],
        "participant_zscore_aggregation": summary.aggregation,
        "participant_zscore_aggregation_label": summary.label_suffix,
        "participant_zscore_trim_fraction": summary.trim_fraction,
        "participant_count": summary.participant_count,
        "participant_ids": participant_ids,
        "lambda2": float(config.lambda2),
        "eloreta_method_params": dict(config.eloreta_method_params),
        "inverse_backend": str(forward_model.metadata.get("inverse_backend", "mne_python")),
        "orientation_constraint": str(forward_model.metadata.get("orientation_constraint", "volume_free")),
        "loose_orientation": forward_model.metadata.get("loose_orientation"),
        "fixed_orientation": forward_model.metadata.get("fixed_orientation", False),
        "depth_weighting": str(forward_model.metadata.get("depth_weighting", "none")),
        "noise_normalization": "eLORETA inverse normalization",
        "average_reference_applied": bool(config.apply_average_reference),
        "sensor_value_unit": condition.sensor_value_unit,
        "source_value_unit": "z-score",
        "source_value_unit_note": (
            "Group summary of participant-level eLORETA volume source-space z-score maps. "
            "Each participant map is computed from target-bin source amplitude relative to "
            "neighboring-bin source-space noise."
        ),
        "value_label": config.value_label,
        "neighboring_bin_policy": {
            "noise_window_bins_each_side": int(config.noise_window_bins),
            "excluded_offsets": list(config.excluded_noise_offsets),
            "common_offsets_used": common_offsets,
            "drop_min_max_noise_per_source": bool(config.drop_min_max_noise_per_source),
            "min_noise_bins": int(config.min_noise_bins),
        },
        "baseline_correction_rule": "target source amplitude minus neighboring-bin source-space mean",
        "z_score_denominator_rule": "population SD of neighboring-bin source-space amplitudes after optional min/max removal",
        "zero_noise_sd_source_count_by_participant": {
            row.participant_id: int(row.zero_noise_sd_source_count) for row in rows
        },
        "channel_count": len(forward_model.channel_names),
        "source_count": int(len(forward_model.source_points)),
        "channel_names": list(forward_model.channel_names),
        "hauk_2021_frequency_domain_zscore_aligned": True,
        "hauk_alignment_target": "participant-first frequency-domain eLORETA volume source-space baseline correction and z-scoring",
        "hauk_alignment_limitations": [
            "EEG only; Hauk 2021 used combined EEG and MEG.",
            "Template fsaverage head/source model; Hauk 2021 and 2025 used individual MRIs.",
            "eLORETA volume maps are expected to be smooth and should not be interpreted as precise anatomical localization.",
        ],
        "sensor_modalities": ["EEG"],
        "head_model": "fsaverage template",
        "subject_mri": "none",
        "deep_source_claim": "template beta eLORETA volume visualization only; not precise subject-specific localization",
        "project_integration": "none",
        "renderer_dependency": "none",
    }
    metadata.update(_cluster_payload_metadata(cluster_result, config=config))
    metadata.update(_source_identity_metadata(forward_model))
    metadata.update(_json_safe_metadata(forward_model.metadata, prefix="forward_model"))
    metadata.update(_json_safe_metadata(config.metadata, prefix="config"))
    metadata.update(_json_safe_metadata(condition.metadata, prefix="condition"))
    return metadata


def _participant_zscore_sidecar_payload(
    *,
    forward_model: ELORETAVolumeForwardModel,
    conditions: Sequence[L2MNEHaukParticipantGroupCondition],
    config: ELORETAVolumeZScoreConfig,
    participant_rows_by_condition: Mapping[str, Sequence[ELORETAVolumeParticipantZScoreValues]],
    cluster_results_by_condition: Mapping[str, SourceSpaceClusterPermutationResult | None] | None = None,
) -> dict[str, Any]:
    condition_rows: list[dict[str, Any]] = []
    cluster_lookup = dict(cluster_results_by_condition or {})
    for condition in conditions:
        participant_rows = tuple(participant_rows_by_condition.get(condition.condition_id, ()))
        cluster_result = cluster_lookup.get(condition.condition_id)
        condition_rows.append(
            {
                "condition_id": condition.condition_id,
                "label": condition.label,
                "participant_count": len(participant_rows),
                "participants": [
                    {
                        "participant_id": row.participant_id,
                        "values": _array_to_json_values(row.values),
                        "noise_offsets_used": list(row.noise_offsets_used),
                        "zero_noise_sd_source_count": int(row.zero_noise_sd_source_count),
                    }
                    for row in participant_rows
                ],
                "cluster_mask": _cluster_manifest_entry_metadata(cluster_result),
            }
        )
    return {
        "format": PARTICIPANT_SOURCE_MAP_SIDECAR_FORMAT,
        "source_model": METHOD_ID_ELORETA_VOLUME_PARTICIPANT_ZSCORE,
        "source_method": SOURCE_METHOD_ELORETA_VOLUME,
        "value_label": config.value_label,
        "source_value_unit": "z-score",
        "coordinate_space": forward_model.coordinate_space,
        "points": _array_to_json_rows(forward_model.source_points),
        "conditions": condition_rows,
        "metadata": {
            "selected_harmonics_hz": list(config.selected_harmonics_hz),
            "participant_level_values": True,
            **_source_identity_metadata(forward_model),
            "cluster_mask": (
                "source_space_cluster_permutation" if config.cluster_mask_enabled else CLUSTER_MASK_STATUS_DISABLED
            ),
            "cluster_mask_method": (
                _cluster_mask_method_label(config.cluster_tail) if config.cluster_mask_enabled else "none"
            ),
            "renderer_dependency": "none",
        },
    }


def _unique_participant_payload_file_name(condition_id: str, aggregation: str, used: set[str]) -> str:
    base = _slug(condition_id)
    suffix_label = _slug(aggregation)
    candidate = f"{base}_eloreta_volume_participant_zscore_{suffix_label}.json"
    suffix = 2
    while candidate in used:
        candidate = f"{base}_{suffix}_eloreta_volume_participant_zscore_{suffix_label}.json"
        suffix += 1
    used.add(candidate)
    return candidate


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
    temp_path.replace(path)


def _emit_progress(progress_callback: ProgressCallback | None, message: str) -> None:
    if progress_callback is not None:
        progress_callback(message)
