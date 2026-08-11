"""Clean-room free-harmonic cluster permutation inference.

This module is deliberately independent of project I/O, spectral preparation,
exports, and Qt.  Public numerical tensors use participant x sensor x harmonic
order.  A flattened node index is therefore ``sensor * harmonic_count +
harmonic``.

The fixed BioSemi64 edge table was derived independently from the standard MNE
1.9.0 ``biosemi64`` montage with its EEG Delaunay-neighbour routine.  The table
is embedded so scientific results do not change when MNE changes.  Its named
edges and SHA-256 fingerprint are public audit data, not an unpublished author
layout.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from time import perf_counter
from typing import Callable, Literal, Sequence
import warnings

import numpy as np

from .models import (
    AnalysisDesign,
    ClusterPermutationResult,
    ClusterRecord,
    FreeHarmonicCancelledError,
    FreeHarmonicMethodSpec,
    PreparedContrast,
)

POSITIVE_TAIL = "positive"
NEGATIVE_TAIL = "negative"
ClusterTail = Literal["positive", "negative"]

PAIRED_DESIGN = "paired_conditions"
INDEPENDENT_DESIGN = "independent_groups"

DEFAULT_CLUSTER_ENTRY_ALPHA = 0.01
DEFAULT_CLUSTER_ALPHA_PER_TAIL = 0.025
DEFAULT_PERMUTATION_COUNT = 10_000
DEFAULT_BATCH_SIZE = 256

BIOSEMI64_ADJACENCY_VERSION = "biosemi64-mne-delaunay-v1"
BIOSEMI64_CHANNELS: tuple[str, ...] = (
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
    "Iz",
    "Oz",
    "POz",
    "Pz",
    "CPz",
    "Fpz",
    "Fp2",
    "AF8",
    "AF4",
    "AFz",
    "Fz",
    "F2",
    "F4",
    "F6",
    "F8",
    "FT8",
    "FC6",
    "FC4",
    "FC2",
    "FCz",
    "Cz",
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
)

# Undirected edges in canonical-channel index order.  Keeping this literal is
# intentional: adjacency must not silently drift with a dependency upgrade.
_BIOSEMI64_EDGE_INDICES: tuple[tuple[int, int], ...] = (
    (0, 1),
    (0, 2),
    (0, 32),
    (0, 36),
    (1, 2),
    (1, 4),
    (1, 5),
    (1, 6),
    (2, 3),
    (2, 4),
    (2, 36),
    (3, 4),
    (3, 10),
    (3, 36),
    (3, 37),
    (3, 46),
    (4, 5),
    (4, 9),
    (4, 10),
    (5, 6),
    (5, 8),
    (5, 9),
    (6, 7),
    (6, 8),
    (7, 8),
    (7, 13),
    (7, 14),
    (8, 9),
    (8, 12),
    (8, 13),
    (9, 10),
    (9, 11),
    (9, 12),
    (10, 11),
    (10, 46),
    (10, 47),
    (11, 12),
    (11, 17),
    (11, 18),
    (11, 47),
    (12, 13),
    (12, 16),
    (12, 17),
    (13, 14),
    (13, 15),
    (13, 16),
    (14, 15),
    (15, 16),
    (15, 22),
    (15, 23),
    (16, 17),
    (16, 21),
    (16, 22),
    (17, 18),
    (17, 20),
    (17, 21),
    (18, 19),
    (18, 20),
    (18, 31),
    (18, 47),
    (19, 20),
    (19, 25),
    (19, 29),
    (19, 30),
    (19, 31),
    (20, 21),
    (20, 24),
    (20, 25),
    (21, 22),
    (21, 24),
    (22, 23),
    (22, 24),
    (23, 24),
    (24, 25),
    (24, 26),
    (25, 26),
    (25, 29),
    (26, 27),
    (26, 28),
    (26, 29),
    (27, 28),
    (27, 63),
    (28, 29),
    (28, 63),
    (29, 30),
    (29, 56),
    (29, 62),
    (29, 63),
    (30, 31),
    (30, 56),
    (31, 47),
    (31, 55),
    (31, 56),
    (32, 33),
    (32, 36),
    (33, 34),
    (33, 35),
    (33, 36),
    (34, 35),
    (34, 39),
    (34, 40),
    (34, 41),
    (35, 36),
    (35, 38),
    (35, 39),
    (36, 37),
    (36, 38),
    (37, 38),
    (37, 46),
    (38, 39),
    (38, 45),
    (38, 46),
    (39, 40),
    (39, 44),
    (39, 45),
    (40, 41),
    (40, 43),
    (40, 44),
    (41, 42),
    (41, 43),
    (42, 43),
    (42, 50),
    (42, 51),
    (43, 44),
    (43, 49),
    (43, 50),
    (44, 45),
    (44, 48),
    (44, 49),
    (45, 46),
    (45, 47),
    (45, 48),
    (46, 47),
    (47, 48),
    (47, 55),
    (48, 49),
    (48, 54),
    (48, 55),
    (49, 50),
    (49, 53),
    (49, 54),
    (50, 51),
    (50, 52),
    (50, 53),
    (51, 52),
    (52, 53),
    (52, 59),
    (52, 60),
    (53, 54),
    (53, 58),
    (53, 59),
    (54, 55),
    (54, 57),
    (54, 58),
    (55, 56),
    (55, 57),
    (56, 57),
    (56, 62),
    (57, 58),
    (57, 61),
    (57, 62),
    (58, 59),
    (58, 61),
    (59, 60),
    (59, 61),
    (60, 61),
    (61, 62),
    (61, 63),
    (62, 63),
)


def _named_biosemi64_edges() -> tuple[tuple[str, str], ...]:
    return tuple((BIOSEMI64_CHANNELS[left], BIOSEMI64_CHANNELS[right]) for left, right in _BIOSEMI64_EDGE_INDICES)


BIOSEMI64_EDGES: tuple[tuple[str, str], ...] = _named_biosemi64_edges()


def _biosemi64_fingerprint() -> str:
    payload = BIOSEMI64_ADJACENCY_VERSION + "\n"
    payload += "".join(f"{left}--{right}\n" for left, right in BIOSEMI64_EDGES)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


BIOSEMI64_ADJACENCY_FINGERPRINT = "1f9c97bd057ea22d5bfdf9c36426e016eb27d94b8ced5959d241cc07fde613fa"
if _biosemi64_fingerprint() != BIOSEMI64_ADJACENCY_FINGERPRINT:  # pragma: no cover - import-time integrity guard
    raise RuntimeError("The embedded BioSemi64 adjacency no longer matches its scientific fingerprint.")


class DegenerateVarianceWarning(RuntimeWarning):
    """A statistic had a non-zero numerator and exactly zero variance."""


class AnalysisCancelled(RuntimeError):
    """The caller cancelled inference at a permutation-batch boundary."""


@dataclass(frozen=True)
class SignedClusterComponent:
    """One sign-homogeneous connected component in sensor-major node order."""

    tail: ClusterTail
    node_indices: tuple[int, ...]
    sensor_harmonic_indices: tuple[tuple[int, int], ...]
    mass: float


@dataclass(frozen=True)
class ClusterPValue:
    """Strict Monte Carlo inference and tie/uncertainty audit fields."""

    p_value: float
    conservative_p_value: float
    tie_count: int
    adjusted_two_sided_p_value: float
    significant: bool
    confidence_interval: tuple[float, float]
    confidence_interval_straddles_alpha: bool


@dataclass(frozen=True)
class EvaluatedCluster:
    """An observed component with cluster-level inference and effect size."""

    component: SignedClusterComponent
    inference: ClusterPValue
    effect_size: float
    effect_size_kind: str


@dataclass(frozen=True)
class CoreClusterPermutationResult:
    """GUI- and project-neutral output of the numerical permutation engine."""

    design: str
    observed_t: np.ndarray
    degrees_of_freedom: int
    cluster_forming_threshold: float
    cluster_entry_alpha: float
    cluster_alpha_per_tail: float
    permutation_count: int
    seed: int
    clusters: tuple[EvaluatedCluster, ...]
    null_positive_maxima: np.ndarray
    null_negative_minima: np.ndarray
    rng_algorithm: str
    permutation_assignment_hash: str
    warnings: tuple[str, ...]
    timing_seconds: tuple[tuple[str, float], ...]

    @property
    def significant_clusters(self) -> tuple[EvaluatedCluster, ...]:
        """Return clusters meeting the predeclared per-direction alpha."""
        return tuple(cluster for cluster in self.clusters if cluster.inference.significant)


def biosemi64_edge_export() -> tuple[tuple[str, str], ...]:
    """Return the canonical, named, sorted BioSemi64 undirected edge table."""
    return BIOSEMI64_EDGES


def biosemi64_adjacency_manifest() -> dict[str, object]:
    """Return JSON-ready provenance for the fixed spatial neighbourhood."""
    return {
        "version": BIOSEMI64_ADJACENCY_VERSION,
        "fingerprint_sha256": BIOSEMI64_ADJACENCY_FINGERPRINT,
        "derivation": "MNE 1.9.0 standard biosemi64 montage, EEG Delaunay triangulation",
        "channels": list(BIOSEMI64_CHANNELS),
        "edges": [list(edge) for edge in BIOSEMI64_EDGES],
    }


def biosemi64_spatial_adjacency(channel_names: Sequence[str] = BIOSEMI64_CHANNELS) -> np.ndarray:
    """Return fixed BioSemi64 adjacency in the requested strict channel order.

    ``channel_names`` may reorder the complete montage, but may not omit,
    duplicate, or add labels.  This lets input preparation preserve a declared
    sensor order without changing the named graph or its fingerprint.
    """
    requested = tuple(str(name) for name in channel_names)
    if len(requested) != len(BIOSEMI64_CHANNELS):
        raise ValueError("BioSemi64 adjacency requires exactly 64 channel labels.")
    if len(set(requested)) != len(requested):
        raise ValueError("BioSemi64 channel labels must be unique.")
    expected = set(BIOSEMI64_CHANNELS)
    actual = set(requested)
    if actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        raise ValueError(f"BioSemi64 channel mismatch; missing={missing}, unexpected={unexpected}.")

    requested_index = {name: index for index, name in enumerate(requested)}
    adjacency = np.zeros((len(requested), len(requested)), dtype=bool)
    for left_name, right_name in BIOSEMI64_EDGES:
        left = requested_index[left_name]
        right = requested_index[right_name]
        adjacency[left, right] = True
        adjacency[right, left] = True
    return adjacency


def validate_spatial_adjacency(adjacency: np.ndarray, *, sensor_count: int | None = None) -> np.ndarray:
    """Validate a finite, symmetric, loop-free spatial adjacency matrix."""
    try:
        values = adjacency.toarray()  # type: ignore[union-attr]
    except AttributeError:
        values = np.asarray(adjacency)
    if values.ndim != 2 or values.shape[0] != values.shape[1]:
        raise ValueError("Spatial adjacency must be a square matrix.")
    if sensor_count is not None and values.shape[0] != int(sensor_count):
        raise ValueError("Spatial adjacency size does not match the tensor sensor dimension.")
    if not np.all(np.isfinite(values)):
        raise ValueError("Spatial adjacency contains non-finite values.")
    normalized = values.astype(bool, copy=True)
    if np.any(np.diag(normalized)):
        raise ValueError("Spatial adjacency must not contain self-edges.")
    if not np.array_equal(normalized, normalized.T):
        raise ValueError("Spatial adjacency must be symmetric.")
    return normalized


def spatial_edges_from_adjacency(adjacency: np.ndarray) -> tuple[tuple[int, int], ...]:
    """Return deterministic undirected index pairs from spatial adjacency."""
    normalized = validate_spatial_adjacency(adjacency)
    return tuple(
        (left, right)
        for left in range(normalized.shape[0])
        for right in range(left + 1, normalized.shape[1])
        if normalized[left, right]
    )


def cartesian_free_harmonic_adjacency(spatial_adjacency: np.ndarray, harmonic_count: int) -> np.ndarray:
    """Return the Cartesian spatial x complete-harmonic graph.

    Node order is sensor-major.  Spatial edges connect the same harmonic only;
    every pair of different harmonics connects within a sensor.  There are no
    direct diagonal sensor-plus-harmonic edges.
    """
    spatial = validate_spatial_adjacency(spatial_adjacency)
    harmonics = int(harmonic_count)
    if harmonics < 1:
        raise ValueError("Free-harmonic adjacency requires at least one harmonic.")
    harmonic_complete = np.ones((harmonics, harmonics), dtype=bool)
    np.fill_diagonal(harmonic_complete, False)
    spatial_part = np.kron(spatial, np.eye(harmonics, dtype=bool))
    harmonic_part = np.kron(np.eye(spatial.shape[0], dtype=bool), harmonic_complete)
    return np.logical_or(spatial_part, harmonic_part)


def cartesian_free_harmonic_edges(
    spatial_adjacency: np.ndarray,
    harmonic_count: int,
) -> tuple[tuple[int, int], ...]:
    """Return Cartesian graph edges without materializing its dense matrix."""
    spatial = validate_spatial_adjacency(spatial_adjacency)
    harmonics = int(harmonic_count)
    if harmonics < 1:
        raise ValueError("Free-harmonic adjacency requires at least one harmonic.")
    edges: list[tuple[int, int]] = []
    for sensor in range(spatial.shape[0]):
        offset = sensor * harmonics
        edges.extend(
            (offset + first, offset + second)
            for first in range(harmonics)
            for second in range(first + 1, harmonics)
        )
    for left_sensor, right_sensor in spatial_edges_from_adjacency(spatial):
        edges.extend(
            (left_sensor * harmonics + harmonic, right_sensor * harmonics + harmonic)
            for harmonic in range(harmonics)
        )
    return tuple(sorted(edges))


def _finite_tensor(values: np.ndarray, *, label: str, minimum_participants: int = 2) -> np.ndarray:
    tensor = np.asarray(values, dtype=np.float64)
    if tensor.ndim != 3:
        raise ValueError(f"{label} must have participant x sensor x harmonic dimensions.")
    if tensor.shape[0] < minimum_participants:
        raise ValueError(f"{label} requires at least {minimum_participants} participants.")
    if tensor.shape[1] < 1 or tensor.shape[2] < 1:
        raise ValueError(f"{label} must contain at least one sensor and one harmonic.")
    if not np.all(np.isfinite(tensor)):
        raise ValueError(f"{label} contains missing or non-finite values; complete maps are required.")
    return np.ascontiguousarray(tensor)


def _clip_roundoff_negative(values: np.ndarray, *, scale: np.ndarray, label: str) -> np.ndarray:
    tolerance = 256.0 * np.finfo(np.float64).eps * np.maximum(1.0, np.asarray(scale, dtype=np.float64))
    if np.any(values < -tolerance):
        minimum = float(np.min(values))
        raise FloatingPointError(f"{label} was materially negative ({minimum:g}).")
    return np.maximum(values, 0.0)


def _safe_t_ratio(numerator: np.ndarray, denominator: np.ndarray, *, warn_degenerate: bool) -> np.ndarray:
    numerator_values, denominator_values = np.broadcast_arrays(
        np.asarray(numerator, dtype=np.float64),
        np.asarray(denominator, dtype=np.float64),
    )
    if np.any(denominator_values < 0.0) or not np.all(np.isfinite(denominator_values)):
        raise FloatingPointError("A t-statistic denominator was negative or non-finite.")
    result = np.zeros(numerator_values.shape, dtype=np.float64)
    regular = denominator_values > 0.0
    np.divide(numerator_values, denominator_values, out=result, where=regular)
    degenerate = ~regular & (numerator_values != 0.0)
    result[degenerate] = np.copysign(np.inf, numerator_values[degenerate])
    if warn_degenerate and np.any(degenerate):
        warnings.warn(
            "At least one node had a non-zero mean difference and zero variance; its t statistic is infinite.",
            DegenerateVarianceWarning,
            stacklevel=3,
        )
    return result


def paired_t_map(condition_a: np.ndarray, condition_b: np.ndarray) -> tuple[np.ndarray, int]:
    """Return the paired Student t map and ``n - 1`` degrees of freedom."""
    first = _finite_tensor(condition_a, label="Paired condition A")
    second = _finite_tensor(condition_b, label="Paired condition B")
    if first.shape != second.shape:
        raise ValueError("Paired conditions must have identical participant, sensor, and harmonic dimensions.")
    differences = first - second
    participant_count = differences.shape[0]
    flat = differences.reshape(participant_count, -1)
    t_flat = _paired_permutation_t_maps_flat(
        flat,
        np.ones((1, participant_count), dtype=np.float64),
    )[0]
    t_map = t_flat.reshape(differences.shape[1:])
    if np.any(np.isinf(t_map)):
        warnings.warn(
            "At least one node had a non-zero mean difference and zero variance; its t statistic is infinite.",
            DegenerateVarianceWarning,
            stacklevel=2,
        )
    return t_map, participant_count - 1


def independent_t_map(group_a: np.ndarray, group_b: np.ndarray) -> tuple[np.ndarray, int]:
    """Return the pooled-variance independent Student t map and ``N - 2`` df."""
    first = _finite_tensor(group_a, label="Independent group A")
    second = _finite_tensor(group_b, label="Independent group B")
    if first.shape[1:] != second.shape[1:]:
        raise ValueError("Independent groups must have identical sensor and harmonic dimensions.")
    count_a = first.shape[0]
    count_b = second.shape[0]
    degrees_of_freedom = count_a + count_b - 2
    pooled = np.concatenate((first, second), axis=0)
    observed_mask = np.zeros((1, pooled.shape[0]), dtype=bool)
    observed_mask[0, :count_a] = True
    t_flat = _independent_permutation_t_maps_flat(
        pooled.reshape(pooled.shape[0], -1),
        observed_mask,
    )[0]
    t_map = t_flat.reshape(first.shape[1:])
    if np.any(np.isinf(t_map)):
        warnings.warn(
            "At least one node had a non-zero mean difference and zero variance; its t statistic is infinite.",
            DegenerateVarianceWarning,
            stacklevel=2,
        )
    return t_map, degrees_of_freedom


def _paired_permutation_t_maps_flat(differences_flat: np.ndarray, signs: np.ndarray) -> np.ndarray:
    participant_count = differences_flat.shape[0]
    means = np.einsum("bn,np->bp", signs, differences_flat, optimize=False) / float(participant_count)
    sum_squares = np.sum(np.square(differences_flat), axis=0, dtype=np.float64)
    variance_numerators = sum_squares[None, :] - participant_count * np.square(means)
    scale = np.maximum(sum_squares[None, :], participant_count * np.square(means))
    variance_numerators = _clip_roundoff_negative(
        variance_numerators,
        scale=scale,
        label="Paired permutation variance numerator",
    )
    variances = variance_numerators / float(participant_count - 1)
    return _safe_t_ratio(means, np.sqrt(variances / float(participant_count)), warn_degenerate=False)


def paired_permutation_t_maps(differences: np.ndarray, signs: np.ndarray) -> np.ndarray:
    """Vectorize whole-participant sign-flip t maps over one permutation batch."""
    values = _finite_tensor(differences, label="Paired differences")
    sign_matrix = np.asarray(signs)
    if sign_matrix.ndim != 2 or sign_matrix.shape[1] != values.shape[0] or sign_matrix.shape[0] < 1:
        raise ValueError("Signs must be a non-empty permutation x participant matrix.")
    if not np.all(np.logical_or(sign_matrix == -1, sign_matrix == 1)):
        raise ValueError("Every paired permutation sign must be exactly -1 or +1.")
    flat = values.reshape(values.shape[0], -1)
    t_flat = _paired_permutation_t_maps_flat(flat, sign_matrix.astype(np.float64, copy=False))
    return t_flat.reshape(sign_matrix.shape[0], values.shape[1], values.shape[2])


def _independent_permutation_t_maps_flat(
    pooled_flat: np.ndarray,
    group_a_masks: np.ndarray,
) -> np.ndarray:
    masks = group_a_masks.astype(np.float64, copy=False)
    participant_count = pooled_flat.shape[0]
    count_a = int(np.sum(group_a_masks[0]))
    count_b = participant_count - count_a
    degrees_of_freedom = participant_count - 2

    total_sums = np.sum(pooled_flat, axis=0, dtype=np.float64)
    total_squares = np.sum(np.square(pooled_flat), axis=0, dtype=np.float64)
    sums_a = np.einsum("bn,np->bp", masks, pooled_flat, optimize=False)
    squares_a = np.einsum("bn,np->bp", masks, np.square(pooled_flat), optimize=False)
    sums_b = total_sums[None, :] - sums_a
    squares_b = total_squares[None, :] - squares_a
    means_a = sums_a / float(count_a)
    means_b = sums_b / float(count_b)
    within_ss = (squares_a - count_a * np.square(means_a)) + (
        squares_b - count_b * np.square(means_b)
    )
    scale = np.maximum(
        squares_a + squares_b,
        count_a * np.square(means_a) + count_b * np.square(means_b),
    )
    within_ss = _clip_roundoff_negative(within_ss, scale=scale, label="Independent permutation within-group SS")
    pooled_variance = within_ss / float(degrees_of_freedom)
    denominator = np.sqrt(pooled_variance * (1.0 / count_a + 1.0 / count_b))
    return _safe_t_ratio(means_a - means_b, denominator, warn_degenerate=False)


def independent_permutation_t_maps(pooled: np.ndarray, group_a_masks: np.ndarray) -> np.ndarray:
    """Vectorize pooled independent t maps for fixed-size whole-subject labels."""
    values = _finite_tensor(pooled, label="Pooled independent participants", minimum_participants=4)
    masks = np.asarray(group_a_masks)
    if masks.ndim != 2 or masks.shape[1] != values.shape[0] or masks.shape[0] < 1:
        raise ValueError("Group masks must be a non-empty permutation x participant matrix.")
    if not np.all(np.logical_or(masks == 0, masks == 1)):
        raise ValueError("Every group mask value must be Boolean or exactly 0/1.")
    boolean_masks = masks.astype(bool, copy=False)
    row_counts = np.sum(boolean_masks, axis=1)
    if not np.all(row_counts == row_counts[0]):
        raise ValueError("Every independent permutation must preserve the same group sizes.")
    count_a = int(row_counts[0])
    count_b = values.shape[0] - count_a
    if count_a < 2 or count_b < 2:
        raise ValueError("Independent pooled t statistics require at least two participants per group.")
    flat = values.reshape(values.shape[0], -1)
    t_flat = _independent_permutation_t_maps_flat(flat, boolean_masks)
    return t_flat.reshape(boolean_masks.shape[0], values.shape[1], values.shape[2])


def cluster_forming_t_threshold(degrees_of_freedom: int, *, entry_alpha: float = DEFAULT_CLUSTER_ENTRY_ALPHA) -> float:
    """Return the two-sided Student threshold at ``1 - entry_alpha / 2``."""
    df = int(degrees_of_freedom)
    alpha = float(entry_alpha)
    if df < 1:
        raise ValueError("Cluster-forming threshold requires positive degrees of freedom.")
    if not 0.0 < alpha < 1.0:
        raise ValueError("Cluster-entry alpha must be strictly between zero and one.")
    try:
        from scipy.stats import t as student_t
    except ImportError as exc:  # pragma: no cover - SciPy is a declared runtime dependency
        raise RuntimeError("SciPy is required to compute the cluster-forming t threshold.") from exc
    threshold = float(student_t.ppf(1.0 - alpha / 2.0, df=df))
    if not math.isfinite(threshold) or threshold <= 0.0:
        raise ValueError("Cluster-forming t threshold was not finite and positive.")
    return threshold


def _union_find_components(
    active: np.ndarray,
    *,
    spatial_edges: Sequence[tuple[int, int]],
) -> tuple[tuple[int, ...], ...]:
    sensor_count, harmonic_count = active.shape
    node_count = sensor_count * harmonic_count
    parent = np.full(node_count, -1, dtype=np.int64)
    rank = np.zeros(node_count, dtype=np.uint8)
    active_nodes = np.flatnonzero(active.reshape(-1))
    parent[active_nodes] = active_nodes

    def find(node: int) -> int:
        root = node
        while parent[root] != root:
            root = int(parent[root])
        while parent[node] != node:
            next_node = int(parent[node])
            parent[node] = root
            node = next_node
        return root

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root == right_root:
            return
        if rank[left_root] < rank[right_root]:
            left_root, right_root = right_root, left_root
        parent[right_root] = left_root
        if rank[left_root] == rank[right_root]:
            rank[left_root] += 1

    # Complete free-harmonic connectivity within each sensor.
    for sensor in range(sensor_count):
        harmonics = np.flatnonzero(active[sensor])
        if harmonics.size > 1:
            first = sensor * harmonic_count + int(harmonics[0])
            for harmonic in harmonics[1:]:
                union(first, sensor * harmonic_count + int(harmonic))

    # Spatial connectivity is restricted to equal harmonic indices.
    for left_sensor, right_sensor in spatial_edges:
        shared_harmonics = np.flatnonzero(np.logical_and(active[left_sensor], active[right_sensor]))
        for harmonic in shared_harmonics:
            harmonic_index = int(harmonic)
            union(
                left_sensor * harmonic_count + harmonic_index,
                right_sensor * harmonic_count + harmonic_index,
            )

    grouped: dict[int, list[int]] = {}
    for node in active_nodes:
        node_index = int(node)
        grouped.setdefault(find(node_index), []).append(node_index)
    return tuple(tuple(nodes) for nodes in sorted(grouped.values(), key=lambda item: tuple(item)))


def _signed_cluster_components_from_edges(
    t_values: np.ndarray,
    *,
    spatial_edges: Sequence[tuple[int, int]],
    threshold: float,
) -> tuple[SignedClusterComponent, ...]:
    sensor_count, harmonic_count = t_values.shape
    flat_t = t_values.reshape(-1)

    def components_for_tail(tail: ClusterTail, active: np.ndarray) -> list[SignedClusterComponent]:
        components: list[SignedClusterComponent] = []
        for nodes in _union_find_components(active, spatial_edges=spatial_edges):
            mass = float(np.sum(flat_t[np.asarray(nodes, dtype=np.int64)], dtype=np.float64))
            coordinates = tuple(divmod(node, harmonic_count) for node in nodes)
            components.append(
                SignedClusterComponent(
                    tail=tail,
                    node_indices=nodes,
                    sensor_harmonic_indices=coordinates,
                    mass=mass,
                )
            )
        return components

    positive = components_for_tail(POSITIVE_TAIL, t_values >= threshold)
    negative = components_for_tail(NEGATIVE_TAIL, t_values <= -threshold)
    positive.sort(key=lambda component: (-component.mass, component.node_indices))
    negative.sort(key=lambda component: (component.mass, component.node_indices))
    return tuple(positive + negative)


def signed_cluster_components(
    t_map: np.ndarray,
    *,
    spatial_adjacency: np.ndarray,
    threshold: float,
) -> tuple[SignedClusterComponent, ...]:
    """Form deterministic positive and negative free-harmonic components."""
    t_values = np.asarray(t_map, dtype=np.float64)
    if t_values.ndim != 2 or t_values.shape[0] < 1 or t_values.shape[1] < 1:
        raise ValueError("A t map must have sensor x harmonic dimensions.")
    if np.any(np.isnan(t_values)):
        raise ValueError("A t map must not contain NaN values.")
    spatial = validate_spatial_adjacency(spatial_adjacency, sensor_count=t_values.shape[0])
    cutoff = float(threshold)
    if not math.isfinite(cutoff) or cutoff <= 0.0:
        raise ValueError("Cluster-forming threshold must be finite and positive.")
    return _signed_cluster_components_from_edges(
        t_values,
        spatial_edges=spatial_edges_from_adjacency(spatial),
        threshold=cutoff,
    )


def signed_null_extrema(
    permutation_t_maps: np.ndarray,
    *,
    spatial_adjacency: np.ndarray,
    threshold: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Return separate max-positive and min-negative cluster-mass nulls."""
    maps = np.asarray(permutation_t_maps, dtype=np.float64)
    if maps.ndim != 3 or maps.shape[0] < 1 or maps.shape[1] < 1 or maps.shape[2] < 1:
        raise ValueError("Permutation t maps must have permutation x sensor x harmonic dimensions.")
    if np.any(np.isnan(maps)):
        raise ValueError("Permutation t maps must not contain NaN values.")
    spatial = validate_spatial_adjacency(spatial_adjacency, sensor_count=maps.shape[1])
    cutoff = float(threshold)
    if not math.isfinite(cutoff) or cutoff <= 0.0:
        raise ValueError("Cluster-forming threshold must be finite and positive.")
    edges = spatial_edges_from_adjacency(spatial)
    positive_maxima = np.zeros(maps.shape[0], dtype=np.float64)
    negative_minima = np.zeros(maps.shape[0], dtype=np.float64)
    for permutation_index, t_values in enumerate(maps):
        components = _signed_cluster_components_from_edges(t_values, spatial_edges=edges, threshold=cutoff)
        positive_masses = [component.mass for component in components if component.tail == POSITIVE_TAIL]
        negative_masses = [component.mass for component in components if component.tail == NEGATIVE_TAIL]
        if positive_masses:
            positive_maxima[permutation_index] = max(positive_masses)
        if negative_masses:
            negative_minima[permutation_index] = min(negative_masses)
    return positive_maxima, negative_minima


def cluster_monte_carlo_p_value(
    *,
    tail: ClusterTail,
    observed_mass: float,
    null_extrema: np.ndarray,
    alpha_per_tail: float = DEFAULT_CLUSTER_ALPHA_PER_TAIL,
) -> ClusterPValue:
    """Evaluate strict FieldTrip-style ``+1`` cluster Monte Carlo inference.

    Strict comparison is intentional: positive null mass must be greater than
    the observed positive mass; negative null mass must be less than the
    observed negative mass.  Equal values are separately exposed as ties.
    """
    if tail not in (POSITIVE_TAIL, NEGATIVE_TAIL):
        raise ValueError("Cluster tail must be 'positive' or 'negative'.")
    mass = float(observed_mass)
    if math.isnan(mass):
        raise ValueError("Observed cluster mass must not be NaN.")
    null = np.asarray(null_extrema, dtype=np.float64).reshape(-1)
    if null.size < 1 or np.any(np.isnan(null)):
        raise ValueError("A non-empty finite-or-infinite null-extrema vector is required.")
    alpha = float(alpha_per_tail)
    if not 0.0 < alpha < 1.0:
        raise ValueError("Cluster alpha per tail must be strictly between zero and one.")

    if tail == POSITIVE_TAIL:
        strict_exceedances = int(np.count_nonzero(null > mass))
        conservative_exceedances = int(np.count_nonzero(null >= mass))
    else:
        strict_exceedances = int(np.count_nonzero(null < mass))
        conservative_exceedances = int(np.count_nonzero(null <= mass))
    ties = int(np.count_nonzero(null == mass))
    denominator = float(null.size + 1)
    p_value = float((1 + strict_exceedances) / denominator)
    conservative_p_value = float((1 + conservative_exceedances) / denominator)
    adjusted = float(min(1.0, 2.0 * p_value))
    monte_carlo_delta = 1.96 * math.sqrt(p_value * (1.0 - p_value) / float(null.size))
    lower = float(max(0.0, p_value - monte_carlo_delta))
    upper = float(min(1.0, p_value + monte_carlo_delta))
    return ClusterPValue(
        p_value=p_value,
        conservative_p_value=conservative_p_value,
        tie_count=ties,
        adjusted_two_sided_p_value=adjusted,
        significant=p_value <= alpha,
        confidence_interval=(lower, upper),
        confidence_interval_straddles_alpha=lower <= alpha <= upper,
    )


def _validated_cluster_nodes(
    node_indices: Sequence[int],
    *,
    sensor_count: int,
    harmonic_count: int,
) -> np.ndarray:
    nodes = np.asarray(tuple(int(node) for node in node_indices), dtype=np.int64)
    if nodes.ndim != 1 or nodes.size < 1:
        raise ValueError("A cluster must contain at least one node.")
    if np.unique(nodes).size != nodes.size:
        raise ValueError("Cluster node indices must be unique.")
    if np.any(nodes < 0) or np.any(nodes >= sensor_count * harmonic_count):
        raise ValueError("Cluster node index is outside the tensor domain.")
    return nodes


def cluster_participant_averages(values: np.ndarray, node_indices: Sequence[int]) -> np.ndarray:
    """Average a declared cluster's nodes separately for every participant."""
    tensor = _finite_tensor(values, label="Cluster-effect tensor")
    nodes = _validated_cluster_nodes(
        node_indices,
        sensor_count=tensor.shape[1],
        harmonic_count=tensor.shape[2],
    )
    return np.mean(tensor.reshape(tensor.shape[0], -1)[:, nodes], axis=1)


def paired_cluster_effect_size(
    condition_a: np.ndarray,
    condition_b: np.ndarray,
    node_indices: Sequence[int],
) -> float:
    """Return cluster-average paired Cohen ``d_z`` (A minus B)."""
    first = _finite_tensor(condition_a, label="Paired effect condition A")
    second = _finite_tensor(condition_b, label="Paired effect condition B")
    if first.shape != second.shape:
        raise ValueError("Paired effect tensors must have identical dimensions.")
    first_average = cluster_participant_averages(first, node_indices)
    second_average = cluster_participant_averages(second, node_indices)
    differences = first_average - second_average
    standard_deviation = float(np.std(differences, ddof=1))
    if standard_deviation == 0.0:
        return float("nan")
    return float(np.mean(differences) / standard_deviation)


def independent_cluster_effect_size(
    group_a: np.ndarray,
    group_b: np.ndarray,
    node_indices: Sequence[int],
) -> float:
    """Return cluster-average pooled Cohen ``d`` (group A minus group B)."""
    first = _finite_tensor(group_a, label="Independent effect group A")
    second = _finite_tensor(group_b, label="Independent effect group B")
    if first.shape[1:] != second.shape[1:]:
        raise ValueError("Independent effect tensors must share sensor and harmonic dimensions.")
    first_average = cluster_participant_averages(first, node_indices)
    second_average = cluster_participant_averages(second, node_indices)
    count_a = first_average.size
    count_b = second_average.size
    pooled_variance = (
        (count_a - 1) * np.var(first_average, ddof=1) + (count_b - 1) * np.var(second_average, ddof=1)
    ) / float(count_a + count_b - 2)
    pooled_standard_deviation = float(np.sqrt(pooled_variance))
    if pooled_standard_deviation == 0.0:
        return float("nan")
    return float((np.mean(first_average) - np.mean(second_average)) / pooled_standard_deviation)


def _normalized_design(design: object) -> str:
    value = getattr(design, "value", design)
    normalized = str(value).strip().lower()
    aliases = {
        PAIRED_DESIGN: PAIRED_DESIGN,
        "paired": PAIRED_DESIGN,
        "paired-condition": PAIRED_DESIGN,
        "paired_conditions": PAIRED_DESIGN,
        INDEPENDENT_DESIGN: INDEPENDENT_DESIGN,
        "independent": INDEPENDENT_DESIGN,
        "independent-groups": INDEPENDENT_DESIGN,
        "independent_groups": INDEPENDENT_DESIGN,
    }
    try:
        return aliases[normalized]
    except KeyError as exc:
        raise ValueError("Design must be paired_conditions or independent_groups.") from exc


def _random_fixed_size_group_masks(
    rng: np.random.Generator,
    *,
    permutation_count: int,
    participant_count: int,
    group_a_count: int,
) -> np.ndarray:
    masks = np.zeros((permutation_count, participant_count), dtype=bool)
    for row in range(permutation_count):
        masks[row, rng.permutation(participant_count)[:group_a_count]] = True
    return masks


def _random_sign_matrix(
    rng: np.random.Generator,
    *,
    permutation_count: int,
    participant_count: int,
) -> np.ndarray:
    """Draw signs with a batch-boundary-invariant PCG64 byte sequence."""
    raw = rng.bit_generator.random_raw(permutation_count * participant_count)
    bits = np.bitwise_and(raw, np.uint64(1)).reshape(permutation_count, participant_count)
    return (bits.astype(np.int8) * 2 - 1).astype(np.int8, copy=False)


def run_cluster_permutation_core(
    arm_a: np.ndarray,
    arm_b: np.ndarray,
    *,
    design: object,
    spatial_adjacency: np.ndarray,
    cluster_entry_alpha: float = DEFAULT_CLUSTER_ENTRY_ALPHA,
    cluster_alpha_per_tail: float = DEFAULT_CLUSTER_ALPHA_PER_TAIL,
    permutation_count: int = DEFAULT_PERMUTATION_COUNT,
    seed: int = 0,
    batch_size: int = DEFAULT_BATCH_SIZE,
    progress: Callable[[int, int], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> CoreClusterPermutationResult:
    """Run batched Monte Carlo free-harmonic cluster inference.

    Random assignments are sampled independently with replacement.  Every
    assignment acts on a participant's complete sensor x harmonic tensor.
    Cancellation is observed only at batch boundaries and never returns a
    partial result.
    """
    total_started = perf_counter()
    normalized_design = _normalized_design(design)
    first = _finite_tensor(arm_a, label="Analysis arm A")
    second = _finite_tensor(arm_b, label="Analysis arm B")
    if first.shape[1:] != second.shape[1:]:
        raise ValueError("Analysis arms must share sensor and harmonic dimensions.")
    if normalized_design == PAIRED_DESIGN and first.shape != second.shape:
        raise ValueError("Paired analysis arms must contain the same participants and dimensions.")
    spatial = validate_spatial_adjacency(spatial_adjacency, sensor_count=first.shape[1])
    total_permutations = int(permutation_count)
    permutations_per_batch = int(batch_size)
    if total_permutations < 1:
        raise ValueError("Permutation count must be positive.")
    if permutations_per_batch < 1:
        raise ValueError("Permutation batch size must be positive.")

    observed_started = perf_counter()
    if normalized_design == PAIRED_DESIGN:
        observed_t, degrees_of_freedom = paired_t_map(first, second)
    else:
        observed_t, degrees_of_freedom = independent_t_map(first, second)
    threshold = cluster_forming_t_threshold(degrees_of_freedom, entry_alpha=float(cluster_entry_alpha))
    observed_components = signed_cluster_components(
        observed_t,
        spatial_adjacency=spatial,
        threshold=threshold,
    )
    observed_seconds = perf_counter() - observed_started
    result_warnings: list[str] = []
    if np.any(np.isinf(observed_t)):
        result_warnings.append("Observed t map contains infinite values from non-zero means with zero variance.")

    positive_null = np.zeros(total_permutations, dtype=np.float64)
    negative_null = np.zeros(total_permutations, dtype=np.float64)
    rng = np.random.default_rng(int(seed))
    rng_algorithm = type(rng.bit_generator).__name__
    assignment_digest = hashlib.sha256()
    assignment_digest.update(b"fpvs-free-harmonic-assignments-v1\0")
    assignment_digest.update(normalized_design.encode("ascii"))
    assignment_digest.update(b"\0")
    assignment_digest.update(
        np.asarray(
            [
                total_permutations,
                first.shape[0],
                second.shape[0],
                first.shape[1],
                first.shape[2],
            ],
            dtype="<i8",
        ).tobytes()
    )
    completed = 0
    if progress is not None:
        progress(0, total_permutations)

    if normalized_design == PAIRED_DESIGN:
        differences = first - second
        flat_differences = differences.reshape(differences.shape[0], -1)
    else:
        pooled = np.concatenate((first, second), axis=0)
        flat_pooled = pooled.reshape(pooled.shape[0], -1)

    permutation_started = perf_counter()
    while completed < total_permutations:
        if cancel_check is not None and cancel_check():
            raise AnalysisCancelled("Free-harmonic cluster inference was cancelled.")
        count = min(permutations_per_batch, total_permutations - completed)
        if normalized_design == PAIRED_DESIGN:
            signs = _random_sign_matrix(
                rng,
                permutation_count=count,
                participant_count=first.shape[0],
            )
            assignment_digest.update(np.ascontiguousarray(signs, dtype=np.int8).tobytes())
            flat_t = _paired_permutation_t_maps_flat(flat_differences, signs.astype(np.float64))
            t_batch = flat_t.reshape(count, first.shape[1], first.shape[2])
        else:
            masks = _random_fixed_size_group_masks(
                rng,
                permutation_count=count,
                participant_count=flat_pooled.shape[0],
                group_a_count=first.shape[0],
            )
            assignment_digest.update(np.ascontiguousarray(masks, dtype=np.uint8).tobytes())
            flat_t = _independent_permutation_t_maps_flat(flat_pooled, masks)
            t_batch = flat_t.reshape(count, first.shape[1], first.shape[2])
        batch_positive, batch_negative = signed_null_extrema(
            t_batch,
            spatial_adjacency=spatial,
            threshold=threshold,
        )
        positive_null[completed : completed + count] = batch_positive
        negative_null[completed : completed + count] = batch_negative
        completed += count
        if progress is not None:
            progress(completed, total_permutations)
    permutation_seconds = perf_counter() - permutation_started

    if cancel_check is not None and cancel_check():
        raise AnalysisCancelled("Free-harmonic cluster inference was cancelled.")

    effect_started = perf_counter()
    evaluated_clusters: list[EvaluatedCluster] = []
    for component in observed_components:
        null = positive_null if component.tail == POSITIVE_TAIL else negative_null
        inference = cluster_monte_carlo_p_value(
            tail=component.tail,
            observed_mass=component.mass,
            null_extrema=null,
            alpha_per_tail=float(cluster_alpha_per_tail),
        )
        if normalized_design == PAIRED_DESIGN:
            effect_size = paired_cluster_effect_size(first, second, component.node_indices)
            effect_size_kind = "paired_dz"
        else:
            effect_size = independent_cluster_effect_size(first, second, component.node_indices)
            effect_size_kind = "pooled_cohen_d"
        evaluated_clusters.append(
            EvaluatedCluster(
                component=component,
                inference=inference,
                effect_size=effect_size,
                effect_size_kind=effect_size_kind,
            )
        )
    effect_seconds = perf_counter() - effect_started
    if np.any(np.isinf(positive_null)) or np.any(np.isinf(negative_null)):
        result_warnings.append("Permutation null contains infinite cluster mass from zero-variance assignments.")
    if any(cluster.inference.confidence_interval_straddles_alpha for cluster in evaluated_clusters):
        result_warnings.append(
            "At least one cluster's approximate Monte Carlo p-value confidence interval includes the final alpha."
        )
    result_warnings.extend(
        (
            "Cluster correction controls one sensor-by-harmonic family for this contrast, not separately run contrasts.",
            "The clean-room implementation has not been numerically author-validated against unpublished reference tensors.",
        )
    )
    total_seconds = perf_counter() - total_started

    return CoreClusterPermutationResult(
        design=normalized_design,
        observed_t=observed_t,
        degrees_of_freedom=degrees_of_freedom,
        cluster_forming_threshold=threshold,
        cluster_entry_alpha=float(cluster_entry_alpha),
        cluster_alpha_per_tail=float(cluster_alpha_per_tail),
        permutation_count=total_permutations,
        seed=int(seed),
        clusters=tuple(evaluated_clusters),
        null_positive_maxima=positive_null,
        null_negative_minima=negative_null,
        rng_algorithm=rng_algorithm,
        permutation_assignment_hash=assignment_digest.hexdigest(),
        warnings=tuple(result_warnings),
        timing_seconds=(
            ("observed_statistics_and_clusters", observed_seconds),
            ("permutation_null", permutation_seconds),
            ("cluster_effects", effect_seconds),
            ("total", total_seconds),
        ),
    )


def public_result_from_core(
    core: CoreClusterPermutationResult,
    *,
    sensor_adjacency_version: str,
    sensor_adjacency_fingerprint: str,
    sensor_adjacency_edges: Sequence[tuple[str, str]],
) -> ClusterPermutationResult:
    """Convert numerical core output to immutable public result models."""
    labels = np.zeros(core.observed_t.shape, dtype=np.int64)
    records: list[ClusterRecord] = []
    positive_id = 0
    negative_id = 0
    for evaluated in core.clusters:
        component = evaluated.component
        if component.tail == POSITIVE_TAIL:
            positive_id += 1
            cluster_id = positive_id
        else:
            negative_id += 1
            cluster_id = -negative_id
        flat_labels = labels.reshape(-1)
        flat_labels[np.asarray(component.node_indices, dtype=np.int64)] = cluster_id
        sensor_indices = tuple(sensor for sensor, _harmonic in component.sensor_harmonic_indices)
        harmonic_indices = tuple(harmonic for _sensor, harmonic in component.sensor_harmonic_indices)
        inference = evaluated.inference
        effect_is_finite = math.isfinite(evaluated.effect_size)
        records.append(
            ClusterRecord(
                cluster_id=cluster_id,
                sign=component.tail,
                mass=component.mass,
                p_value=inference.p_value,
                conservative_p_value=inference.conservative_p_value,
                adjusted_two_sided_p_value=inference.adjusted_two_sided_p_value,
                tie_count=inference.tie_count,
                p_ci_low=inference.confidence_interval[0],
                p_ci_high=inference.confidence_interval[1],
                confidence_interval_straddles_alpha=inference.confidence_interval_straddles_alpha,
                significant=inference.significant,
                node_indices=component.node_indices,
                sensor_indices=sensor_indices,
                harmonic_indices=harmonic_indices,
                effect_size=evaluated.effect_size if effect_is_finite else None,
                effect_size_kind=evaluated.effect_size_kind if effect_is_finite else None,
            )
        )

    return ClusterPermutationResult(
        design=AnalysisDesign(core.design),
        observed_t=core.observed_t,
        cluster_labels=labels,
        clusters=tuple(records),
        null_positive_max_mass=core.null_positive_maxima,
        null_negative_min_mass=core.null_negative_minima,
        permutations_evaluated=core.permutation_count,
        degrees_of_freedom=core.degrees_of_freedom,
        cluster_forming_threshold=core.cluster_forming_threshold,
        cluster_entry_alpha=core.cluster_entry_alpha,
        cluster_alpha_per_tail=core.cluster_alpha_per_tail,
        sensor_adjacency_version=str(sensor_adjacency_version),
        sensor_adjacency_fingerprint=str(sensor_adjacency_fingerprint),
        sensor_adjacency_edges=tuple((str(left), str(right)) for left, right in sensor_adjacency_edges),
        rng_algorithm=core.rng_algorithm,
        seed=core.seed,
        permutation_assignment_hash=core.permutation_assignment_hash,
        warnings=core.warnings,
        timing_seconds=core.timing_seconds,
    )


def run_cluster_permutation(
    arm_a: np.ndarray,
    arm_b: np.ndarray,
    *,
    design: AnalysisDesign | str,
    method: FreeHarmonicMethodSpec | None = None,
    sensor_names: Sequence[str] = BIOSEMI64_CHANNELS,
    batch_size: int = DEFAULT_BATCH_SIZE,
    progress: Callable[[int, int], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> ClusterPermutationResult:
    """Run the fixed BioSemi64 method and return shared public result models."""
    specification = method if method is not None else FreeHarmonicMethodSpec()
    if not isinstance(specification, FreeHarmonicMethodSpec):
        raise TypeError("method must be a FreeHarmonicMethodSpec.")
    if specification.sensor_adjacency_version != BIOSEMI64_ADJACENCY_VERSION:
        raise ValueError(
            "Method sensor_adjacency_version does not match the embedded BioSemi64 scientific adjacency."
        )
    sensor_order = tuple(str(name) for name in sensor_names)
    spatial = biosemi64_spatial_adjacency(sensor_order)
    try:
        core = run_cluster_permutation_core(
            arm_a,
            arm_b,
            design=design,
            spatial_adjacency=spatial,
            cluster_entry_alpha=specification.cluster_entry_alpha,
            cluster_alpha_per_tail=specification.cluster_alpha_per_tail,
            permutation_count=specification.n_permutations,
            seed=specification.seed,
            batch_size=batch_size,
            progress=progress,
            cancel_check=cancel_check,
        )
    except AnalysisCancelled as exc:
        raise FreeHarmonicCancelledError(str(exc)) from exc
    return public_result_from_core(
        core,
        sensor_adjacency_version=BIOSEMI64_ADJACENCY_VERSION,
        sensor_adjacency_fingerprint=BIOSEMI64_ADJACENCY_FINGERPRINT,
        sensor_adjacency_edges=BIOSEMI64_EDGES,
    )


def analyze_prepared_contrast(
    prepared: PreparedContrast,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    progress: Callable[[int, int], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> ClusterPermutationResult:
    """Analyze one fully prepared contrast through the public model boundary."""
    if not isinstance(prepared, PreparedContrast):
        raise TypeError("prepared must be a PreparedContrast.")
    return run_cluster_permutation(
        prepared.values_a,
        prepared.values_b,
        design=prepared.request.design,
        method=prepared.method,
        sensor_names=prepared.sensor_names,
        batch_size=batch_size,
        progress=progress,
        cancel_check=cancel_check,
    )
