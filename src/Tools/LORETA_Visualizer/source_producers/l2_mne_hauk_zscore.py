"""Hauk-style source-space z-score L2-MNE producer.

This module owns Phase 6D calculation-side source-space z-scored L2-MNE maps
for FPVS frequency-domain inputs. It does not import GUI, renderer, display
transforms, fsaverage display mesh loading, or prepared-payload importer code.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

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
    SOURCE_KIND_SURFACE_MESH,
    L2MNECorticalForwardModel,
    _array_to_json_rows,
    _array_to_json_values,
    _json_safe_metadata,
    _minimum_norm_inverse_matrix,
    _referenced_leadfield,
    _round_harmonic,
    _slug,
    _validate_harmonics,
    _validate_label,
)
from Tools.LORETA_Visualizer.source_producers.source_lateralization import (
    DEFAULT_SOURCE_LATERALIZATION_CSV_NAME,
    DEFAULT_SOURCE_LATERALIZATION_JSON_NAME,
    build_source_lateralization_rows,
    write_source_lateralization_summary_files,
)

logger = logging.getLogger(__name__)
ProgressCallback = Callable[[str], None]

METHOD_ID_L2_MNE_CORTICAL_SURFACE_HAUK_ZSCORE_BETA = "l2_mne_cortical_surface_hauk_zscore_beta"
METHOD_ID_L2_MNE_FSAVERAGE_PARTICIPANT_ZSCORE = "l2_mne_fsaverage_participant_zscore"
METHOD_ID_L2_MNE_FSAVERAGE_PARTICIPANT_ZSCORE_MEAN = "l2_mne_fsaverage_participant_zscore_mean"
METHOD_ID_L2_MNE_FSAVERAGE_PARTICIPANT_ZSCORE_MEDIAN = "l2_mne_fsaverage_participant_zscore_median"
METHOD_ID_L2_MNE_FSAVERAGE_PARTICIPANT_ZSCORE_TRIMMED_MEAN = (
    "l2_mne_fsaverage_participant_zscore_trimmed_mean"
)
PARTICIPANT_ZSCORE_AGGREGATION_MEAN = "mean"
PARTICIPANT_ZSCORE_AGGREGATION_MEDIAN = "median"
PARTICIPANT_ZSCORE_AGGREGATION_TRIMMED_MEAN = "trimmed_mean"
PARTICIPANT_ZSCORE_AGGREGATION_METHOD_IDS = {
    PARTICIPANT_ZSCORE_AGGREGATION_MEAN: METHOD_ID_L2_MNE_FSAVERAGE_PARTICIPANT_ZSCORE_MEAN,
    PARTICIPANT_ZSCORE_AGGREGATION_MEDIAN: METHOD_ID_L2_MNE_FSAVERAGE_PARTICIPANT_ZSCORE_MEDIAN,
    PARTICIPANT_ZSCORE_AGGREGATION_TRIMMED_MEAN: METHOD_ID_L2_MNE_FSAVERAGE_PARTICIPANT_ZSCORE_TRIMMED_MEAN,
}
DEFAULT_PARTICIPANT_ZSCORE_AGGREGATIONS = (
    PARTICIPANT_ZSCORE_AGGREGATION_MEAN,
    PARTICIPANT_ZSCORE_AGGREGATION_MEDIAN,
    PARTICIPANT_ZSCORE_AGGREGATION_TRIMMED_MEAN,
)
DEFAULT_PARTICIPANT_ZSCORE_TRIM_FRACTION = 0.2
PARTICIPANT_SOURCE_MAP_SIDECAR_FORMAT = "fpvs_loreta_participant_source_maps_v1"
DEFAULT_HAUK_ZSCORE_NOISE_WINDOW_BINS = 10
DEFAULT_HAUK_ZSCORE_MIN_NOISE_BINS = 4
DEFAULT_HAUK_ZSCORE_EXCLUDED_OFFSETS = (-1, 0, 1)
DEFAULT_CLUSTER_MASK_ENABLED = True
DEFAULT_CLUSTER_FORMING_P_VALUE = 0.05
DEFAULT_CLUSTER_ALPHA = 0.05
DEFAULT_CLUSTER_PERMUTATION_COUNT = 2048
DEFAULT_CLUSTER_PERMUTATION_SEED = 20260609
CLUSTER_MASK_METHOD_SOURCE_SPACE_SIGN_FLIP = "one_sample_sign_flip_max_cluster_mass"
CLUSTER_MASK_STATUS_COMPUTED = "computed"
CLUSTER_MASK_STATUS_NO_CANDIDATES = "no_candidate_clusters"
CLUSTER_MASK_STATUS_DISABLED = "disabled"
CLUSTER_TAIL_POSITIVE = "positive"


@dataclass(frozen=True)
class L2MNEHaukZScoreConfig:
    """Configuration for Hauk-style source-space z-scored L2-MNE maps."""

    selected_harmonics_hz: tuple[float, ...]
    method_id: str = METHOD_ID_L2_MNE_CORTICAL_SURFACE_HAUK_ZSCORE_BETA
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
    cluster_tail: str = CLUSTER_TAIL_POSITIVE
    montage_name: str = "BioSemi ActiveTwo 64-channel 10-10"
    harmonic_policy_id: str = "stats_group_significant_oddball_harmonics"
    template_subject: str = "fsaverage"
    value_label: str = "source-space z-score"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        selected = _validate_harmonics(self.selected_harmonics_hz)
        lambda2 = float(self.lambda2)
        if not np.isfinite(lambda2) or lambda2 <= 0.0:
            raise ValueError("Hauk z-score L2-MNE lambda2 must be positive and finite.")
        if self.harmonic_strategy != HARMONIC_STRATEGY_SUM_SENSOR_TOPOGRAPHIES_THEN_INVERT:
            raise ValueError(
                "Hauk z-score L2-MNE currently supports summed sensor topographies "
                "before inversion only."
            )
        noise_window_bins = int(self.noise_window_bins)
        min_noise_bins = int(self.min_noise_bins)
        if noise_window_bins < 2:
            raise ValueError("Hauk z-score noise window must include at least two bins on each side.")
        if min_noise_bins < 2:
            raise ValueError("Hauk z-score min_noise_bins must be at least 2.")
        excluded = tuple(sorted({int(offset) for offset in self.excluded_noise_offsets}))
        if 0 not in excluded:
            raise ValueError("Hauk z-score excluded noise offsets must include the target offset 0.")
        cluster_forming_p = _validate_probability(self.cluster_forming_p_value, "cluster_forming_p_value")
        cluster_alpha = _validate_probability(self.cluster_alpha, "cluster_alpha")
        cluster_permutation_count = int(self.cluster_permutation_count)
        if cluster_permutation_count < 1:
            raise ValueError("Cluster permutation count must be at least 1.")
        cluster_tail = str(self.cluster_tail).strip().lower()
        if cluster_tail != CLUSTER_TAIL_POSITIVE:
            raise ValueError("Only positive one-sided source-space cluster masks are currently supported.")
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
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True)
class L2MNEHaukHarmonicBins:
    """One selected harmonic with target and neighboring-bin topographies."""

    harmonic_hz: float
    target_topography: Sequence[float]
    target_frequency_hz: float
    target_bin_index: int
    target_column: str
    noise_topographies_by_offset: Mapping[int, Sequence[float]]
    noise_frequencies_hz_by_offset: Mapping[int, float] = field(default_factory=dict)
    noise_bin_indices_by_offset: Mapping[int, int] = field(default_factory=dict)
    noise_columns_by_offset: Mapping[int, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        harmonic = _round_harmonic(float(self.harmonic_hz))
        target = _validate_topography(self.target_topography, label=f"{harmonic:g} Hz target")
        noise_topographies: dict[int, np.ndarray] = {}
        for raw_offset, values in self.noise_topographies_by_offset.items():
            offset = int(raw_offset)
            if offset == 0:
                raise ValueError("Hauk z-score noise bins cannot use target offset 0.")
            vector = _validate_topography(values, label=f"{harmonic:g} Hz noise offset {offset}")
            if len(vector) != len(target):
                raise ValueError(
                    f"Hauk z-score noise offset {offset} for {harmonic:g} Hz has "
                    f"{len(vector)} channels; {len(target)} expected."
                )
            noise_topographies[offset] = vector
        if not noise_topographies:
            raise ValueError(f"Hauk z-score harmonic {harmonic:g} Hz requires neighboring-bin topographies.")
        noise_offsets = set(noise_topographies)
        frequencies = _numeric_mapping_for_offsets(
            self.noise_frequencies_hz_by_offset,
            offsets=noise_offsets,
            label="noise frequency",
        )
        bin_indices = _integer_mapping_for_offsets(
            self.noise_bin_indices_by_offset,
            offsets=noise_offsets,
            label="noise bin index",
        )
        columns = {
            int(offset): str(value)
            for offset, value in self.noise_columns_by_offset.items()
            if int(offset) in noise_offsets
        }
        object.__setattr__(self, "harmonic_hz", harmonic)
        object.__setattr__(self, "target_topography", target)
        object.__setattr__(self, "target_frequency_hz", float(self.target_frequency_hz))
        object.__setattr__(self, "target_bin_index", int(self.target_bin_index))
        object.__setattr__(self, "target_column", _validate_label(self.target_column, "target_column"))
        object.__setattr__(self, "noise_topographies_by_offset", dict(sorted(noise_topographies.items())))
        object.__setattr__(self, "noise_frequencies_hz_by_offset", frequencies)
        object.__setattr__(self, "noise_bin_indices_by_offset", bin_indices)
        object.__setattr__(self, "noise_columns_by_offset", dict(sorted(columns.items())))


@dataclass(frozen=True)
class L2MNEHaukZScoreCondition:
    """FPVS condition with source-ready target and noise-bin topographies."""

    condition_id: str
    label: str
    harmonic_bins: Mapping[float, L2MNEHaukHarmonicBins]
    sensor_value_unit: str = "raw FFT amplitude uV"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        condition_id = _slug(_validate_label(self.condition_id, "condition_id"))
        label = _validate_label(self.label, "label")
        lookup: dict[float, L2MNEHaukHarmonicBins] = {}
        for harmonic, bin_set in self.harmonic_bins.items():
            key = _round_harmonic(float(harmonic))
            if key in lookup:
                raise ValueError(f"Duplicate Hauk z-score harmonic bin set for {key:g} Hz.")
            if not isinstance(bin_set, L2MNEHaukHarmonicBins):
                raise TypeError("Hauk z-score harmonic_bins values must be L2MNEHaukHarmonicBins.")
            if bin_set.harmonic_hz != key:
                raise ValueError("Hauk z-score harmonic_bins key must match the bin-set harmonic.")
            lookup[key] = bin_set
        if not lookup:
            raise ValueError("Hauk z-score condition requires at least one harmonic bin set.")
        object.__setattr__(self, "condition_id", condition_id)
        object.__setattr__(self, "label", label)
        object.__setattr__(self, "harmonic_bins", dict(sorted(lookup.items())))
        object.__setattr__(self, "sensor_value_unit", _validate_label(self.sensor_value_unit, "sensor_value_unit"))
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True)
class L2MNEHaukZScoreValues:
    """Computed source-space z-score result and diagnostic arrays."""

    values: np.ndarray
    target_source_values: np.ndarray
    noise_mean_values: np.ndarray
    noise_std_values: np.ndarray
    noise_offsets_used: tuple[int, ...]
    zero_noise_sd_source_count: int


@dataclass(frozen=True)
class L2MNEHaukParticipantSourceInput:
    """One participant's source-ready target/noise-bin topographies."""

    participant_id: str
    condition: L2MNEHaukZScoreCondition

    def __post_init__(self) -> None:
        participant_id = _validate_label(self.participant_id, "participant_id")
        if not isinstance(self.condition, L2MNEHaukZScoreCondition):
            raise TypeError("Participant source input condition must be L2MNEHaukZScoreCondition.")
        object.__setattr__(self, "participant_id", participant_id)


@dataclass(frozen=True)
class L2MNEHaukParticipantGroupCondition:
    """One condition containing participant-level source-ready inputs."""

    condition_id: str
    label: str
    participants: Sequence[L2MNEHaukParticipantSourceInput]
    sensor_value_unit: str = "raw FFT amplitude uV"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        condition_id = _slug(_validate_label(self.condition_id, "condition_id"))
        label = _validate_label(self.label, "label")
        participant_list = tuple(self.participants)
        if not participant_list:
            raise ValueError("Participant-first Hauk z-score condition requires at least one participant.")
        ids = [participant.participant_id for participant in participant_list]
        if len(set(ids)) != len(ids):
            raise ValueError(f"Duplicate participant source inputs for {label}.")
        for participant in participant_list:
            if not isinstance(participant, L2MNEHaukParticipantSourceInput):
                raise TypeError("participants must contain L2MNEHaukParticipantSourceInput values.")
            if participant.condition.condition_id != condition_id:
                raise ValueError("Participant source input condition_id must match the group condition_id.")
        object.__setattr__(self, "condition_id", condition_id)
        object.__setattr__(self, "label", label)
        object.__setattr__(self, "participants", participant_list)
        object.__setattr__(self, "sensor_value_unit", _validate_label(self.sensor_value_unit, "sensor_value_unit"))
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True)
class L2MNEHaukParticipantZScoreValues:
    """One participant's computed source-space z-score map."""

    participant_id: str
    values: np.ndarray
    target_source_values: np.ndarray
    noise_mean_values: np.ndarray
    noise_std_values: np.ndarray
    noise_offsets_used: tuple[int, ...]
    zero_noise_sd_source_count: int


@dataclass(frozen=True)
class L2MNEHaukParticipantZScoreSummary:
    """Group summary over participant-level source z-score maps."""

    aggregation: str
    label_suffix: str
    method_id: str
    values: np.ndarray
    participant_count: int
    trim_fraction: float | None = None


@dataclass(frozen=True)
class L2MNEHaukSourceCluster:
    """One source-space cluster from the participant-level permutation test."""

    cluster_id: int
    vertex_indices: tuple[int, ...]
    cluster_mass: float
    p_value: float
    significant: bool


@dataclass(frozen=True)
class L2MNEHaukClusterPermutationResult:
    """Source-space cluster mask computed from participant z-score maps."""

    status: str
    mask: np.ndarray
    t_values: np.ndarray
    cluster_forming_threshold: float
    cluster_forming_p_value: float
    cluster_alpha: float
    permutation_count: int
    permutation_seed: int
    tail: str
    clusters: tuple[L2MNEHaukSourceCluster, ...]

    @property
    def significant_clusters(self) -> tuple[L2MNEHaukSourceCluster, ...]:
        """Return only clusters that survive cluster-level correction."""
        return tuple(cluster for cluster in self.clusters if cluster.significant)


@dataclass(frozen=True)
class L2MNEHaukParticipantZScoreWriteResult:
    """Participant-first output files plus the renderer-ready producer result."""

    producer_result: SourceProducerRunResult
    participant_sidecar_path: Path
    lateralization_summary_path: Path | None = None
    lateralization_summary_csv_path: Path | None = None


def compute_l2_mne_hauk_zscore_source_values(
    *,
    forward_model: L2MNECorticalForwardModel,
    condition: L2MNEHaukZScoreCondition,
    config: L2MNEHaukZScoreConfig,
) -> L2MNEHaukZScoreValues:
    """Compute Hauk-style source-space z-scores for one condition."""
    inverse = None
    if forward_model.source_estimator is None:
        leadfield = _referenced_leadfield(
            forward_model.leadfield,
            apply_average_reference=config.apply_average_reference,
        )
        inverse = _minimum_norm_inverse_matrix(leadfield, lambda2=config.lambda2)
    harmonic_bins = _selected_harmonic_bins(condition, config=config, n_channels=len(forward_model.channel_names))
    common_offsets = _common_noise_offsets(harmonic_bins, config=config)
    if len(common_offsets) < config.min_noise_bins:
        raise ValueError(
            f"{condition.label} has {len(common_offsets)} common neighboring-bin offsets; "
            f"{config.min_noise_bins} are required for source-space z-scores."
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
    source_values = (
        _source_amplitudes_from_topographies(
            forward_model,
            topographies,
            lambda2=config.lambda2,
        )
        if inverse is None
        else np.abs(topographies @ inverse.T)
    )
    target_source_values = source_values[0]
    noise_source_values = source_values[1:]
    used_noise = _drop_extreme_noise_rows(noise_source_values) if config.drop_min_max_noise_per_source else noise_source_values
    noise_mean = np.mean(used_noise, axis=0)
    noise_std = np.std(used_noise, axis=0, ddof=0)
    valid = np.isfinite(noise_std) & (noise_std > 1e-12)
    if not np.any(valid):
        raise ValueError(f"{condition.label} has no source points with finite neighboring-bin noise SD.")
    z_values = np.zeros_like(target_source_values, dtype=float)
    z_values[valid] = (target_source_values[valid] - noise_mean[valid]) / noise_std[valid]
    if not np.all(np.isfinite(z_values)):
        raise ValueError("Hauk z-score L2-MNE produced non-finite source values.")
    return L2MNEHaukZScoreValues(
        values=z_values.astype(float),
        target_source_values=target_source_values.astype(float),
        noise_mean_values=noise_mean.astype(float),
        noise_std_values=noise_std.astype(float),
        noise_offsets_used=tuple(common_offsets),
        zero_noise_sd_source_count=int(np.count_nonzero(~valid)),
    )


def compute_l2_mne_hauk_participant_zscore_source_values(
    *,
    forward_model: L2MNECorticalForwardModel,
    condition: L2MNEHaukParticipantGroupCondition,
    config: L2MNEHaukZScoreConfig,
) -> tuple[L2MNEHaukParticipantZScoreValues, ...]:
    """Compute source-space z-score maps independently for each participant."""
    rows: list[L2MNEHaukParticipantZScoreValues] = []
    for participant in condition.participants:
        result = compute_l2_mne_hauk_zscore_source_values(
            forward_model=forward_model,
            condition=participant.condition,
            config=config,
        )
        rows.append(
            L2MNEHaukParticipantZScoreValues(
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


def summarize_l2_mne_hauk_participant_zscores(
    participant_values: Sequence[L2MNEHaukParticipantZScoreValues],
    *,
    aggregation: str,
    trim_fraction: float = DEFAULT_PARTICIPANT_ZSCORE_TRIM_FRACTION,
) -> L2MNEHaukParticipantZScoreSummary:
    """Summarize participant-level z-score maps with a deterministic aggregator."""
    aggregation_id = _validate_participant_zscore_aggregation(aggregation)
    rows = tuple(participant_values)
    if not rows:
        raise ValueError("Participant z-score aggregation requires at least one participant map.")
    matrix = np.vstack([np.asarray(row.values, dtype=float).reshape(1, -1) for row in rows])
    if not np.all(np.isfinite(matrix)):
        raise ValueError("Participant source z-score maps contain non-finite values.")
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
    return L2MNEHaukParticipantZScoreSummary(
        aggregation=aggregation_id,
        label_suffix=label_suffix,
        method_id=PARTICIPANT_ZSCORE_AGGREGATION_METHOD_IDS[aggregation_id],
        values=np.asarray(values, dtype=float),
        participant_count=len(rows),
        trim_fraction=summary_trim_fraction,
    )


def compute_l2_mne_hauk_source_cluster_mask(
    participant_values: Sequence[L2MNEHaukParticipantZScoreValues],
    *,
    faces: np.ndarray,
    config: L2MNEHaukZScoreConfig,
) -> L2MNEHaukClusterPermutationResult:
    """Compute a Hauk-style source-space cluster mask across participants.

    This is a one-sample, positive-tail sign-flip permutation test against zero
    over participant source-space z-score maps. It produces an inferential mask
    for display payloads; it does not alter source values or run the inverse
    solution.
    """
    matrix = _participant_zscore_matrix(participant_values)
    source_count = matrix.shape[1]
    adjacency = _mesh_adjacency(faces, source_count=source_count)
    observed_t = _one_sample_t_values(matrix)
    threshold = _cluster_forming_t_threshold(
        participant_count=matrix.shape[0],
        p_value=config.cluster_forming_p_value,
    )
    observed_clusters = _cluster_components(observed_t >= threshold, adjacency)
    empty_mask = np.zeros(source_count, dtype=bool)
    if not observed_clusters:
        return L2MNEHaukClusterPermutationResult(
            status=CLUSTER_MASK_STATUS_NO_CANDIDATES,
            mask=empty_mask,
            t_values=observed_t,
            cluster_forming_threshold=threshold,
            cluster_forming_p_value=config.cluster_forming_p_value,
            cluster_alpha=config.cluster_alpha,
            permutation_count=0,
            permutation_seed=int(config.cluster_permutation_seed),
            tail=config.cluster_tail,
            clusters=(),
        )

    null_max_masses = _permutation_max_cluster_masses(
        matrix,
        adjacency=adjacency,
        threshold=threshold,
        permutation_count=config.cluster_permutation_count,
        seed=config.cluster_permutation_seed,
    )
    clusters: list[L2MNEHaukSourceCluster] = []
    mask = empty_mask.copy()
    denominator = float(len(null_max_masses) + 1)
    for cluster_index, cluster_vertices in enumerate(observed_clusters, start=1):
        cluster_mass = float(np.sum(observed_t[np.asarray(cluster_vertices, dtype=np.int64)]))
        p_value = float((1 + np.count_nonzero(null_max_masses >= cluster_mass - 1e-12)) / denominator)
        significant = p_value <= config.cluster_alpha
        if significant:
            mask[np.asarray(cluster_vertices, dtype=np.int64)] = True
        clusters.append(
            L2MNEHaukSourceCluster(
                cluster_id=cluster_index,
                vertex_indices=tuple(int(index) for index in cluster_vertices),
                cluster_mass=cluster_mass,
                p_value=p_value,
                significant=significant,
            )
        )

    return L2MNEHaukClusterPermutationResult(
        status=CLUSTER_MASK_STATUS_COMPUTED,
        mask=mask,
        t_values=observed_t,
        cluster_forming_threshold=threshold,
        cluster_forming_p_value=config.cluster_forming_p_value,
        cluster_alpha=config.cluster_alpha,
        permutation_count=int(len(null_max_masses)),
        permutation_seed=int(config.cluster_permutation_seed),
        tail=config.cluster_tail,
        clusters=tuple(clusters),
    )


def build_l2_mne_hauk_zscore_surface_payload(
    *,
    forward_model: L2MNECorticalForwardModel,
    condition: L2MNEHaukZScoreCondition,
    config: L2MNEHaukZScoreConfig,
) -> dict[str, Any]:
    """Build one validator-ready source-space z-score payload."""
    result = compute_l2_mne_hauk_zscore_source_values(
        forward_model=forward_model,
        condition=condition,
        config=config,
    )
    payload = {
        "format": PREPARED_SOURCE_PAYLOAD_FORMAT,
        "label": f"{condition.label} L2-MNE source-space z-score map",
        "kind": SOURCE_KIND_SURFACE_MESH,
        "coordinate_space": forward_model.coordinate_space,
        "source_model": config.method_id,
        "value_label": config.value_label,
        "points": _array_to_json_rows(forward_model.source_points),
        "values": _array_to_json_values(result.values),
        "faces": _array_to_json_rows(forward_model.faces),
        "metadata": _payload_metadata(
            forward_model=forward_model,
            condition=condition,
            config=config,
            result=result,
        ),
    }
    validate_prepared_source_payload_mapping(payload)
    return payload


def build_l2_mne_hauk_participant_zscore_summary_payload(
    *,
    forward_model: L2MNECorticalForwardModel,
    condition: L2MNEHaukParticipantGroupCondition,
    config: L2MNEHaukZScoreConfig,
    participant_values: Sequence[L2MNEHaukParticipantZScoreValues],
    summary: L2MNEHaukParticipantZScoreSummary,
    cluster_result: L2MNEHaukClusterPermutationResult | None = None,
) -> dict[str, Any]:
    """Build one renderer-ready group summary from participant source maps."""
    values = np.asarray(summary.values, dtype=float).reshape(-1)
    if len(values) != len(forward_model.source_points):
        raise ValueError(
            f"Participant source summary has {len(values)} source values; "
            f"{len(forward_model.source_points)} expected."
        )
    payload = {
        "format": PREPARED_SOURCE_PAYLOAD_FORMAT,
        "label": f"{condition.label} {summary.label_suffix}",
        "kind": SOURCE_KIND_SURFACE_MESH,
        "coordinate_space": forward_model.coordinate_space,
        "source_model": summary.method_id,
        "value_label": config.value_label,
        "points": _array_to_json_rows(forward_model.source_points),
        "values": _array_to_json_values(values),
        "faces": _array_to_json_rows(forward_model.faces),
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


def write_l2_mne_hauk_zscore_surface_payloads(
    *,
    forward_model: L2MNECorticalForwardModel,
    conditions: Sequence[L2MNEHaukZScoreCondition],
    config: L2MNEHaukZScoreConfig,
    output_dir: str | Path,
    manifest_name: str = "l2_mne_hauk_zscore_beta_manifest.json",
    progress_callback: ProgressCallback | None = None,
) -> SourceProducerRunResult:
    """Write validated Hauk-style source-space z-score payloads and manifest."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    condition_list = tuple(conditions)
    if not condition_list:
        raise ValueError("Hauk z-score L2-MNE producer requires at least one condition.")

    emitted: list[ProducedPayload] = []
    manifest_conditions: list[dict[str, Any]] = []
    used_file_names: set[str] = set()
    for index, condition in enumerate(condition_list, start=1):
        _emit_progress(
            progress_callback,
            f"Computing source-space z-score map {index}/{len(condition_list)}: {condition.label}...",
        )
        payload = build_l2_mne_hauk_zscore_surface_payload(
            forward_model=forward_model,
            condition=condition,
            config=config,
        )
        file_name = _unique_payload_file_name(condition.condition_id, used_file_names)
        payload_path = output_path / file_name
        _emit_progress(
            progress_callback,
            f"Writing and validating source JSON {index}/{len(condition_list)}: {condition.label}...",
        )
        _write_json(payload_path, payload)
        validation = validate_prepared_source_payload_json(payload_path)
        emitted.append(
            ProducedPayload(
                condition_id=condition.condition_id,
                label=condition.label,
                payload_path=payload_path,
                validation=validation,
            )
        )
        manifest_conditions.append(
            {
                "id": condition.condition_id,
                "label": condition.label,
                "file": file_name,
                "metadata": {
                    "producer_method": config.method_id,
                    "selected_harmonics_hz": list(config.selected_harmonics_hz),
                    "value_label": config.value_label,
                    "source_value_unit": "z-score",
                },
            }
        )

    manifest = {
        "format": PREPARED_SOURCE_MANIFEST_FORMAT,
        "label": "L2-MNE Hauk-style source-space z-score beta maps",
        "conditions": manifest_conditions,
    }
    manifest_path = output_path / manifest_name
    _emit_progress(progress_callback, "Writing source-map manifest...")
    _write_json(manifest_path, manifest)
    _emit_progress(progress_callback, "Validating source-map manifest...")
    manifest_validation = validate_prepared_source_manifest_json(manifest_path, require_payload_files=True)
    logger.info(
        "l2_mne_hauk_zscore_payloads_written",
        extra={"output_dir": str(output_path), "condition_count": len(emitted)},
    )
    return SourceProducerRunResult(
        method_id=config.method_id,
        output_dir=output_path,
        manifest_path=manifest_path,
        payloads=tuple(emitted),
        manifest_validation=manifest_validation,
    )


def write_l2_mne_hauk_participant_zscore_surface_payloads(
    *,
    forward_model: L2MNECorticalForwardModel,
    conditions: Sequence[L2MNEHaukParticipantGroupCondition],
    config: L2MNEHaukZScoreConfig,
    output_dir: str | Path,
    manifest_name: str = "l2_mne_participant_zscore_manifest.json",
    aggregations: Sequence[str] = DEFAULT_PARTICIPANT_ZSCORE_AGGREGATIONS,
    trim_fraction: float = DEFAULT_PARTICIPANT_ZSCORE_TRIM_FRACTION,
    participant_sidecar_name: str = "participant_l2_mne_hauk_zscore_maps.json",
    progress_callback: ProgressCallback | None = None,
) -> L2MNEHaukParticipantZScoreWriteResult:
    """Write participant-first z-score summaries and participant sidecar JSON."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    condition_list = tuple(conditions)
    if not condition_list:
        raise ValueError("Participant-first Hauk z-score producer requires at least one condition.")
    aggregation_list = tuple(_validate_participant_zscore_aggregation(value) for value in aggregations)
    if not aggregation_list:
        raise ValueError("Participant-first Hauk z-score producer requires at least one aggregation.")
    trim_fraction = _validate_trim_fraction(trim_fraction)

    emitted: list[ProducedPayload] = []
    manifest_conditions: list[dict[str, Any]] = []
    used_file_names: set[str] = set()
    participant_rows_by_condition: dict[str, tuple[L2MNEHaukParticipantZScoreValues, ...]] = {}
    cluster_results_by_condition: dict[str, L2MNEHaukClusterPermutationResult | None] = {}
    lateralization_rows: list[dict[str, Any]] = []
    for condition_index, condition in enumerate(condition_list, start=1):
        _emit_progress(
            progress_callback,
            (
                f"Computing participant source z-scores for condition "
                f"{condition_index}/{len(condition_list)}: {condition.label}..."
            ),
        )
        participant_rows = compute_l2_mne_hauk_participant_zscore_source_values(
            forward_model=forward_model,
            condition=condition,
            config=config,
        )
        participant_rows_by_condition[condition.condition_id] = participant_rows
        cluster_result = None
        if config.cluster_mask_enabled:
            _emit_progress(
                progress_callback,
                f"Computing source-space cluster mask for {condition.label}...",
            )
            cluster_result = compute_l2_mne_hauk_source_cluster_mask(
                participant_rows,
                faces=forward_model.faces,
                config=config,
            )
            _emit_progress(
                progress_callback,
                (
                    f"Cluster mask for {condition.label}: "
                    f"{int(np.count_nonzero(cluster_result.mask))} source point(s) retained."
                ),
            )
        cluster_results_by_condition[condition.condition_id] = cluster_result
        condition_summaries: list[L2MNEHaukParticipantZScoreSummary] = []
        for aggregation in aggregation_list:
            summary = summarize_l2_mne_hauk_participant_zscores(
                participant_rows,
                aggregation=aggregation,
                trim_fraction=trim_fraction,
            )
            condition_summaries.append(summary)
            _emit_progress(
                progress_callback,
                f"Writing {condition.label} {summary.label_suffix} source JSON...",
            )
            payload = build_l2_mne_hauk_participant_zscore_summary_payload(
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
                        "producer_method": summary.method_id,
                        "base_producer_method": METHOD_ID_L2_MNE_FSAVERAGE_PARTICIPANT_ZSCORE,
                        "participant_zscore_aggregation": summary.aggregation,
                        "selected_harmonics_hz": list(config.selected_harmonics_hz),
                        "value_label": config.value_label,
                        "source_value_unit": "z-score",
                        **_cluster_manifest_entry_metadata(cluster_result),
                    },
                }
            )
        lateralization_rows.extend(
            build_source_lateralization_rows(
                source_points=forward_model.source_points,
                condition_id=condition.condition_id,
                condition_label=condition.label,
                participant_values=participant_rows,
                group_summaries=condition_summaries,
                cluster_mask=None if cluster_result is None else cluster_result.mask,
            )
        )

    sidecar_path = output_path / participant_sidecar_name
    _emit_progress(progress_callback, "Writing participant source-map sidecar...")
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

    lateralization_json_path = output_path / DEFAULT_SOURCE_LATERALIZATION_JSON_NAME
    lateralization_csv_path = output_path / DEFAULT_SOURCE_LATERALIZATION_CSV_NAME
    _emit_progress(progress_callback, "Writing source lateralization summary...")
    write_source_lateralization_summary_files(
        json_path=lateralization_json_path,
        csv_path=lateralization_csv_path,
        rows=lateralization_rows,
        metadata={
            "source_map_model": "participant_first",
            "source_value_unit": "z-score",
            "participant_sidecar_file": sidecar_path.name,
            "selected_harmonics_hz": list(config.selected_harmonics_hz),
            "cluster_mask": (
                "source_space_cluster_permutation" if config.cluster_mask_enabled else CLUSTER_MASK_STATUS_DISABLED
            ),
            "cluster_mask_method": (
                CLUSTER_MASK_METHOD_SOURCE_SPACE_SIGN_FLIP if config.cluster_mask_enabled else "none"
            ),
            "summary_note": (
                "Descriptive source-space lateralization companion metric. It does not replace "
                "sensor-space BCA lateralization statistics."
            ),
        },
    )

    manifest = {
        "format": PREPARED_SOURCE_MANIFEST_FORMAT,
        "label": "L2-MNE participant-first source-space z-score maps",
        "conditions": manifest_conditions,
        "metadata": {
            "producer_method": METHOD_ID_L2_MNE_FSAVERAGE_PARTICIPANT_ZSCORE,
            "aggregation_methods": list(aggregation_list),
            "participant_sidecar_file": sidecar_path.name,
            "cluster_mask": (
                "source_space_cluster_permutation" if config.cluster_mask_enabled else CLUSTER_MASK_STATUS_DISABLED
            ),
            "cluster_mask_method": (
                CLUSTER_MASK_METHOD_SOURCE_SPACE_SIGN_FLIP if config.cluster_mask_enabled else "none"
            ),
        },
    }
    manifest_path = output_path / manifest_name
    _emit_progress(progress_callback, "Writing source-map manifest...")
    _write_json(manifest_path, manifest)
    _emit_progress(progress_callback, "Validating source-map manifest...")
    manifest_validation = validate_prepared_source_manifest_json(manifest_path, require_payload_files=True)
    logger.info(
        "l2_mne_participant_zscore_payloads_written",
        extra={
            "output_dir": str(output_path),
            "condition_count": len(condition_list),
            "payload_count": len(emitted),
            "participant_sidecar_path": str(sidecar_path),
            "lateralization_summary_path": str(lateralization_json_path),
        },
    )
    return L2MNEHaukParticipantZScoreWriteResult(
        producer_result=SourceProducerRunResult(
            method_id=METHOD_ID_L2_MNE_FSAVERAGE_PARTICIPANT_ZSCORE,
            output_dir=output_path,
            manifest_path=manifest_path,
            payloads=tuple(emitted),
            manifest_validation=manifest_validation,
        ),
        participant_sidecar_path=sidecar_path,
        lateralization_summary_path=lateralization_json_path,
        lateralization_summary_csv_path=lateralization_csv_path,
    )


def _source_amplitudes_from_topographies(
    forward_model: L2MNECorticalForwardModel,
    topographies: np.ndarray,
    *,
    lambda2: float,
) -> np.ndarray:
    source_estimator = forward_model.source_estimator
    if source_estimator is None:
        raise ValueError("Batch source topography estimation requires an estimator-backed forward model.")
    topography_matrix = np.asarray(topographies, dtype=float)
    if topography_matrix.ndim != 2 or topography_matrix.shape[1] != len(forward_model.channel_names):
        raise ValueError(
            "Batch source topography estimation expected shape "
            f"n_topographies x {len(forward_model.channel_names)} channels."
        )
    values = np.asarray(source_estimator(topography_matrix, lambda2=float(lambda2)), dtype=float)
    if values.ndim == 1 and topography_matrix.shape[0] == 1:
        values = values.reshape(1, -1)
    if values.ndim != 2:
        raise ValueError("Estimator-backed batch source estimation returned an unexpected shape.")
    expected_shape = (topography_matrix.shape[0], len(forward_model.source_points))
    if values.shape != expected_shape:
        raise ValueError(
            "Estimator-backed batch source estimation returned shape "
            f"{values.shape}; expected {expected_shape}."
        )
    return values.astype(float)


def _emit_progress(progress_callback: ProgressCallback | None, message: str) -> None:
    if progress_callback is not None:
        progress_callback(message)


def _selected_harmonic_bins(
    condition: L2MNEHaukZScoreCondition,
    *,
    config: L2MNEHaukZScoreConfig,
    n_channels: int,
) -> tuple[L2MNEHaukHarmonicBins, ...]:
    rows: list[L2MNEHaukHarmonicBins] = []
    for harmonic in config.selected_harmonics_hz:
        key = _round_harmonic(harmonic)
        if key not in condition.harmonic_bins:
            raise ValueError(f"{condition.label} is missing selected harmonic {key:g} Hz.")
        bin_set = condition.harmonic_bins[key]
        if len(bin_set.target_topography) != n_channels:
            raise ValueError(
                f"{condition.label} harmonic {key:g} Hz has {len(bin_set.target_topography)} channels; "
                f"{n_channels} expected."
            )
        rows.append(bin_set)
    return tuple(rows)


def _common_noise_offsets(
    harmonic_bins: Sequence[L2MNEHaukHarmonicBins],
    *,
    config: L2MNEHaukZScoreConfig,
) -> list[int]:
    excluded = set(config.excluded_noise_offsets)
    common: set[int] | None = None
    for bin_set in harmonic_bins:
        offsets = {int(offset) for offset in bin_set.noise_topographies_by_offset if int(offset) not in excluded}
        common = offsets if common is None else common & offsets
    return sorted(common or set())


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


def _participant_zscore_matrix(
    participant_values: Sequence[L2MNEHaukParticipantZScoreValues],
) -> np.ndarray:
    rows = tuple(participant_values)
    if len(rows) < 2:
        raise ValueError("Source-space cluster permutation requires at least two participant maps.")
    matrix = np.vstack([np.asarray(row.values, dtype=float).reshape(1, -1) for row in rows])
    if matrix.ndim != 2 or matrix.shape[1] == 0:
        raise ValueError("Participant source z-score matrix must be participants x source_points.")
    if not np.all(np.isfinite(matrix)):
        raise ValueError("Participant source z-score matrix contains non-finite values.")
    return matrix.astype(float)


def _one_sample_t_values(matrix: np.ndarray) -> np.ndarray:
    values = np.asarray(matrix, dtype=float)
    participant_count = values.shape[0]
    means = np.mean(values, axis=0)
    sd = np.std(values, axis=0, ddof=1)
    t_values = np.zeros(values.shape[1], dtype=float)
    valid = np.isfinite(sd) & (sd > 1e-12)
    t_values[valid] = means[valid] / (sd[valid] / np.sqrt(float(participant_count)))
    return np.where(np.isfinite(t_values), t_values, 0.0)


def _cluster_forming_t_threshold(*, participant_count: int, p_value: float) -> float:
    if participant_count < 2:
        raise ValueError("Cluster-forming threshold requires at least two participants.")
    try:
        from scipy import stats

        threshold = float(stats.t.ppf(1.0 - float(p_value), df=participant_count - 1))
    except (ImportError, AttributeError, TypeError, ValueError):
        threshold = 1.6448536269514722
    if not np.isfinite(threshold):
        raise ValueError("Cluster-forming threshold was not finite.")
    return threshold


def _permutation_max_cluster_masses(
    matrix: np.ndarray,
    *,
    adjacency: Sequence[set[int]],
    threshold: float,
    permutation_count: int,
    seed: int,
) -> np.ndarray:
    values = np.asarray(matrix, dtype=float)
    masses: list[float] = []
    for signs in _sign_flip_vectors(values.shape[0], permutation_count=permutation_count, seed=seed):
        signed = values * signs[:, np.newaxis]
        t_values = _one_sample_t_values(signed)
        clusters = _cluster_components(t_values >= threshold, adjacency)
        if clusters:
            masses.append(max(float(np.sum(t_values[np.asarray(cluster, dtype=np.int64)])) for cluster in clusters))
        else:
            masses.append(0.0)
    return np.asarray(masses, dtype=float)


def _sign_flip_vectors(
    participant_count: int,
    *,
    permutation_count: int,
    seed: int,
) -> Sequence[np.ndarray]:
    exact_count = 2**participant_count
    if participant_count <= 12 and exact_count <= int(permutation_count):
        return tuple(_exact_sign_vector(index, participant_count) for index in range(exact_count))
    rng = np.random.default_rng(int(seed))
    draws = rng.choice(np.asarray([-1.0, 1.0], dtype=float), size=(int(permutation_count), participant_count))
    return tuple(np.asarray(row, dtype=float) for row in draws)


def _exact_sign_vector(index: int, participant_count: int) -> np.ndarray:
    signs = np.empty(participant_count, dtype=float)
    for participant_index in range(participant_count):
        signs[participant_index] = 1.0 if (index >> participant_index) & 1 else -1.0
    return signs


def _mesh_adjacency(faces: np.ndarray, *, source_count: int) -> tuple[set[int], ...]:
    adjacency = [set() for _ in range(int(source_count))]
    for triangle in _triangle_faces_from_any_faces(faces):
        if not np.all((triangle >= 0) & (triangle < source_count)):
            raise ValueError("Cluster-mask source faces must refer to existing source points.")
        a, b, c = (int(index) for index in triangle)
        adjacency[a].update((b, c))
        adjacency[b].update((a, c))
        adjacency[c].update((a, b))
    return tuple(adjacency)


def _triangle_faces_from_any_faces(faces: np.ndarray) -> np.ndarray:
    face_array = np.asarray(faces, dtype=np.int64)
    if face_array.ndim == 1:
        if len(face_array) % 4 != 0:
            raise ValueError("Flat source faces must use VTK-style triangular records.")
        vtk_faces = face_array.reshape(-1, 4)
        if not np.all(vtk_faces[:, 0] == 3):
            raise ValueError("Flat source faces must use VTK-style triangular records.")
        return vtk_faces[:, 1:4].astype(np.int64)
    if face_array.ndim == 2 and face_array.shape[1] == 4:
        if not np.all(face_array[:, 0] == 3):
            raise ValueError("Source face rows must use VTK-style triangular records.")
        return face_array[:, 1:4].astype(np.int64)
    if face_array.ndim == 2 and face_array.shape[1] == 3:
        return face_array.astype(np.int64)
    raise ValueError("Source faces must be triangle rows or VTK-style triangular records.")


def _cluster_components(
    candidate_mask: np.ndarray,
    adjacency: Sequence[set[int]],
) -> tuple[tuple[int, ...], ...]:
    candidate = np.asarray(candidate_mask, dtype=bool).reshape(-1)
    if len(candidate) != len(adjacency):
        raise ValueError("Cluster candidate mask must align with source adjacency.")
    unvisited = set(int(index) for index in np.flatnonzero(candidate))
    clusters: list[tuple[int, ...]] = []
    while unvisited:
        seed = unvisited.pop()
        stack = [seed]
        cluster = [seed]
        while stack:
            current = stack.pop()
            for neighbor in adjacency[current]:
                if neighbor in unvisited:
                    unvisited.remove(neighbor)
                    stack.append(neighbor)
                    cluster.append(neighbor)
        clusters.append(tuple(sorted(cluster)))
    return tuple(clusters)


def _validate_probability(value: float, label: str) -> float:
    probability = float(value)
    if not np.isfinite(probability) or probability <= 0.0 or probability >= 1.0:
        raise ValueError(f"{label} must be > 0 and < 1.")
    return probability


def _validate_topography(values: Sequence[float], *, label: str) -> np.ndarray:
    vector = np.asarray(values, dtype=float).reshape(-1)
    if len(vector) == 0 or not np.all(np.isfinite(vector)):
        raise ValueError(f"Hauk z-score {label} topography must contain finite values.")
    return vector.astype(float)


def _numeric_mapping_for_offsets(
    mapping: Mapping[int, float],
    *,
    offsets: set[int],
    label: str,
) -> dict[int, float]:
    out: dict[int, float] = {}
    for offset in offsets:
        if offset not in mapping:
            continue
        value = float(mapping[offset])
        if not np.isfinite(value):
            raise ValueError(f"Hauk z-score {label} for offset {offset} must be finite.")
        out[int(offset)] = value
    return dict(sorted(out.items()))


def _integer_mapping_for_offsets(
    mapping: Mapping[int, int],
    *,
    offsets: set[int],
    label: str,
) -> dict[int, int]:
    out: dict[int, int] = {}
    for offset in offsets:
        if offset not in mapping:
            continue
        out[int(offset)] = int(mapping[offset])
    return dict(sorted(out.items()))


def _payload_metadata(
    *,
    forward_model: L2MNECorticalForwardModel,
    condition: L2MNEHaukZScoreCondition,
    config: L2MNEHaukZScoreConfig,
    result: L2MNEHaukZScoreValues,
) -> dict[str, Any]:
    metadata = {
        "beta": True,
        "producer_method": config.method_id,
        "inverse_method": "L2 minimum-norm estimate",
        "source_space": "cortical_surface",
        "template_subject": config.template_subject,
        "montage_name": config.montage_name,
        "coordinate_space": forward_model.coordinate_space,
        "forward_model_label": forward_model.label,
        "harmonic_policy_id": config.harmonic_policy_id,
        "selected_harmonics_hz": list(config.selected_harmonics_hz),
        "harmonic_strategy": config.harmonic_strategy,
        "lambda2": float(config.lambda2),
        "inverse_backend": str(forward_model.metadata.get("inverse_backend", "manual_ridge")),
        "orientation_constraint": str(forward_model.metadata.get("orientation_constraint", "fixed")),
        "loose_orientation": forward_model.metadata.get("loose_orientation"),
        "fixed_orientation": forward_model.metadata.get("fixed_orientation", True),
        "depth_weighting": str(forward_model.metadata.get("depth_weighting", "not_applicable")),
        "noise_normalization": str(forward_model.metadata.get("noise_normalization", "none")),
        "regularization": str(
            forward_model.metadata.get("regularization", "lambda2 scaled by leadfield sensor-space trace")
        ),
        "average_reference_applied": bool(config.apply_average_reference),
        "sensor_value_unit": condition.sensor_value_unit,
        "source_value_unit": "z-score",
        "source_value_unit_note": (
            "Source-space z-score computed from target-bin L2-MNE source amplitude "
            "relative to neighboring-bin source-space noise."
        ),
        "value_label": config.value_label,
        "neighboring_bin_policy": {
            "noise_window_bins_each_side": int(config.noise_window_bins),
            "excluded_offsets": list(config.excluded_noise_offsets),
            "common_offsets_used": list(result.noise_offsets_used),
            "drop_min_max_noise_per_source": bool(config.drop_min_max_noise_per_source),
            "min_noise_bins": int(config.min_noise_bins),
        },
        "baseline_correction_rule": "target source amplitude minus neighboring-bin source-space mean",
        "z_score_denominator_rule": "population SD of neighboring-bin source-space amplitudes after optional min/max removal",
        "zero_noise_sd_source_count": int(result.zero_noise_sd_source_count),
        "channel_count": len(forward_model.channel_names),
        "source_count": int(len(forward_model.source_points)),
        "channel_names": list(forward_model.channel_names),
        "hauk_2021_frequency_domain_zscore_aligned": True,
        "hauk_alignment_target": "frequency-domain L2-MNE source-space baseline correction and z-scoring",
        "hauk_alignment_limitations": [
            "EEG only; Hauk 2021 used combined EEG and MEG.",
            "Template fsaverage head/source model; Hauk 2021 and 2025 used individual MRIs.",
            "Deprecated group-first mode source-estimates group-level topographies once; Phase 6H-A(2) participant-first maps are the preferred path.",
            "Ad hoc diagonal EEG covariance is used for whitening in this EEG-only template path.",
        ],
        "source_map_model": "deprecated_group_first",
        "deprecated_model": True,
        "deprecation_note": (
            "Retained as an advanced fallback while participant-first source maps are validated; "
            "planned for removal."
        ),
        "cluster_mask": "none",
        "sensor_modalities": ["EEG"],
        "head_model": "fsaverage template",
        "subject_mri": "none",
        "deep_source_claim": "none; Hauk-style beta L2-MNE payload is cortical surface only",
        "project_integration": "none",
        "renderer_dependency": "none",
    }
    metadata.update(_json_safe_metadata(forward_model.metadata, prefix="forward_model"))
    metadata.update(_json_safe_metadata(config.metadata, prefix="config"))
    metadata.update(_json_safe_metadata(condition.metadata, prefix="condition"))
    return metadata


def _cluster_payload_metadata(
    cluster_result: L2MNEHaukClusterPermutationResult | None,
    *,
    config: L2MNEHaukZScoreConfig,
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
        "cluster_mask_method": CLUSTER_MASK_METHOD_SOURCE_SPACE_SIGN_FLIP,
        "cluster_mask_note": (
            "Renderer uses this producer-computed source-space mask as the primary "
            "publication-style L2-MNE display mask; source values remain unchanged."
        ),
        "cluster_mask_vertex_indices": [int(index) for index in retained],
        "cluster_mask_vertex_count": int(len(retained)),
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
                "vertex_count": int(len(cluster.vertex_indices)),
                "cluster_mass": float(cluster.cluster_mass),
                "p_value": float(cluster.p_value),
            }
            for cluster in significant_clusters
        ],
    }


def _cluster_manifest_entry_metadata(
    cluster_result: L2MNEHaukClusterPermutationResult | None,
) -> dict[str, Any]:
    if cluster_result is None:
        return {
            "cluster_mask": "none",
            "cluster_mask_vertex_count": 0,
            "cluster_significant_cluster_count": 0,
        }
    return {
        "cluster_mask": "source_space_cluster_permutation",
        "cluster_mask_status": cluster_result.status,
        "cluster_mask_vertex_count": int(np.count_nonzero(cluster_result.mask)),
        "cluster_mask_source_count": int(len(cluster_result.mask)),
        "cluster_significant_cluster_count": int(len(cluster_result.significant_clusters)),
        "cluster_forming_p_value": float(cluster_result.cluster_forming_p_value),
        "cluster_alpha": float(cluster_result.cluster_alpha),
        "cluster_permutation_count": int(cluster_result.permutation_count),
    }


def _participant_summary_payload_metadata(
    *,
    forward_model: L2MNECorticalForwardModel,
    condition: L2MNEHaukParticipantGroupCondition,
    config: L2MNEHaukZScoreConfig,
    participant_values: Sequence[L2MNEHaukParticipantZScoreValues],
    summary: L2MNEHaukParticipantZScoreSummary,
    cluster_result: L2MNEHaukClusterPermutationResult | None = None,
) -> dict[str, Any]:
    rows = tuple(participant_values)
    participant_ids = [row.participant_id for row in rows]
    common_offsets = sorted({offset for row in rows for offset in row.noise_offsets_used})
    metadata = {
        "beta": True,
        "producer_method": summary.method_id,
        "base_producer_method": METHOD_ID_L2_MNE_FSAVERAGE_PARTICIPANT_ZSCORE,
        "inverse_method": "L2 minimum-norm estimate",
        "source_space": "cortical_surface",
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
            "estimate source values for each participant target and noise topography",
            "sum source estimates across selected significant harmonics",
            "compute participant source-space z-score maps",
            "aggregate participant z-score maps for group display",
        ],
        "participant_zscore_aggregation": summary.aggregation,
        "participant_zscore_aggregation_label": summary.label_suffix,
        "participant_zscore_trim_fraction": summary.trim_fraction,
        "participant_count": summary.participant_count,
        "participant_ids": participant_ids,
        "lambda2": float(config.lambda2),
        "inverse_backend": str(forward_model.metadata.get("inverse_backend", "manual_ridge")),
        "orientation_constraint": str(forward_model.metadata.get("orientation_constraint", "fixed")),
        "loose_orientation": forward_model.metadata.get("loose_orientation"),
        "fixed_orientation": forward_model.metadata.get("fixed_orientation", True),
        "depth_weighting": str(forward_model.metadata.get("depth_weighting", "not_applicable")),
        "noise_normalization": str(forward_model.metadata.get("noise_normalization", "none")),
        "regularization": str(
            forward_model.metadata.get("regularization", "lambda2 scaled by leadfield sensor-space trace")
        ),
        "average_reference_applied": bool(config.apply_average_reference),
        "sensor_value_unit": condition.sensor_value_unit,
        "source_value_unit": "z-score",
        "source_value_unit_note": (
            "Group summary of participant-level source-space z-score maps. Each participant map is "
            "computed from target-bin L2-MNE source amplitude relative to neighboring-bin source-space noise."
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
        "hauk_alignment_target": "participant-first frequency-domain L2-MNE source-space baseline correction and z-scoring",
        "hauk_alignment_limitations": [
            "EEG only; Hauk 2021 used combined EEG and MEG.",
            "Template fsaverage head/source model; Hauk 2021 and 2025 used individual MRIs.",
            "Ad hoc diagonal EEG covariance is used for whitening in this EEG-only template path.",
        ],
        "sensor_modalities": ["EEG"],
        "head_model": "fsaverage template",
        "subject_mri": "none",
        "deep_source_claim": "none; Hauk-style beta L2-MNE payload is cortical surface only",
        "project_integration": "none",
        "renderer_dependency": "none",
    }
    metadata.update(_cluster_payload_metadata(cluster_result, config=config))
    metadata.update(_json_safe_metadata(forward_model.metadata, prefix="forward_model"))
    metadata.update(_json_safe_metadata(config.metadata, prefix="config"))
    metadata.update(_json_safe_metadata(condition.metadata, prefix="condition"))
    return metadata


def _participant_zscore_sidecar_payload(
    *,
    forward_model: L2MNECorticalForwardModel,
    conditions: Sequence[L2MNEHaukParticipantGroupCondition],
    config: L2MNEHaukZScoreConfig,
    participant_rows_by_condition: Mapping[str, Sequence[L2MNEHaukParticipantZScoreValues]],
    cluster_results_by_condition: Mapping[str, L2MNEHaukClusterPermutationResult | None] | None = None,
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
        "source_model": METHOD_ID_L2_MNE_FSAVERAGE_PARTICIPANT_ZSCORE,
        "value_label": config.value_label,
        "source_value_unit": "z-score",
        "coordinate_space": forward_model.coordinate_space,
        "points": _array_to_json_rows(forward_model.source_points),
        "faces": _array_to_json_rows(forward_model.faces),
        "conditions": condition_rows,
        "metadata": {
            "selected_harmonics_hz": list(config.selected_harmonics_hz),
            "participant_level_values": True,
            "cluster_mask": (
                "source_space_cluster_permutation" if config.cluster_mask_enabled else CLUSTER_MASK_STATUS_DISABLED
            ),
            "cluster_mask_method": (
                CLUSTER_MASK_METHOD_SOURCE_SPACE_SIGN_FLIP if config.cluster_mask_enabled else "none"
            ),
            "renderer_dependency": "none",
        },
    }


def _unique_payload_file_name(condition_id: str, used: set[str]) -> str:
    base = _slug(condition_id)
    candidate = f"{base}_l2_mne_hauk_zscore_beta.json"
    suffix = 2
    while candidate in used:
        candidate = f"{base}_{suffix}_l2_mne_hauk_zscore_beta.json"
        suffix += 1
    used.add(candidate)
    return candidate


def _unique_participant_payload_file_name(condition_id: str, aggregation: str, used: set[str]) -> str:
    base = _slug(condition_id)
    suffix_label = _slug(aggregation)
    candidate = f"{base}_l2_mne_participant_zscore_{suffix_label}.json"
    suffix = 2
    while candidate in used:
        candidate = f"{base}_{suffix}_l2_mne_participant_zscore_{suffix_label}.json"
        suffix += 1
    used.add(candidate)
    return candidate


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
    temp_path.replace(path)
