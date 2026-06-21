"""Source-space group statistics for prepared source producers.

This module owns method-neutral source-space statistics. It does not estimate
sources, read projects, render payloads, or import GUI/display helpers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np

CLUSTER_TAIL_POSITIVE = "positive"
CLUSTER_TAIL_NEGATIVE = "negative"
CLUSTER_TAIL_TWO_SIDED = "two-sided"
CLUSTER_MASK_STATUS_COMPUTED = "computed"
CLUSTER_MASK_STATUS_NO_CANDIDATES = "no_candidate_clusters"


@dataclass(frozen=True)
class SourceSpaceCluster:
    """One source-space cluster from a permutation test."""

    cluster_id: int
    tail: str
    source_indices: tuple[int, ...]
    cluster_mass: float
    p_value: float
    significant: bool


@dataclass(frozen=True)
class SourceSpaceClusterPermutationResult:
    """Source-space cluster mask computed from participant maps."""

    status: str
    mask: np.ndarray
    t_values: np.ndarray
    cluster_forming_threshold: float
    cluster_forming_p_value: float
    cluster_alpha: float
    permutation_count: int
    permutation_seed: int
    tail: str
    clusters: tuple[SourceSpaceCluster, ...]

    @property
    def significant_clusters(self) -> tuple[SourceSpaceCluster, ...]:
        """Return only clusters that survive cluster-level correction."""
        return tuple(cluster for cluster in self.clusters if cluster.significant)


def participant_zscore_matrix(participant_values: Sequence[Any]) -> np.ndarray:
    """Return a participants x source-locations matrix from value-bearing rows."""
    rows = tuple(participant_values)
    if len(rows) < 2:
        raise ValueError("Source-space cluster permutation requires at least two participant maps.")
    matrix = np.vstack([np.asarray(row.values, dtype=float).reshape(1, -1) for row in rows])
    if matrix.ndim != 2 or matrix.shape[1] == 0:
        raise ValueError("Participant source z-score matrix must be participants x source_points.")
    if not np.all(np.isfinite(matrix)):
        raise ValueError("Participant source z-score matrix contains non-finite values.")
    return matrix.astype(float)


def compute_source_space_cluster_permutation_mask(
    participant_values: Sequence[Any],
    *,
    adjacency: Sequence[set[int]],
    cluster_forming_p_value: float,
    cluster_alpha: float,
    permutation_count: int,
    permutation_seed: int,
    tail: str = CLUSTER_TAIL_POSITIVE,
) -> SourceSpaceClusterPermutationResult:
    """Compute a source-space sign-flip max-cluster-mass mask."""
    matrix = participant_zscore_matrix(participant_values)
    source_count = matrix.shape[1]
    normalized_adjacency = validate_adjacency(adjacency, source_count=source_count)
    observed_t = one_sample_t_values(matrix)
    threshold = cluster_forming_t_threshold(
        participant_count=matrix.shape[0],
        p_value=cluster_forming_p_value,
        tail=tail,
    )
    cluster_tail = validate_cluster_tail(tail)
    observed_clusters = signed_cluster_components(
        observed_t,
        threshold=threshold,
        adjacency=normalized_adjacency,
        tail=cluster_tail,
    )
    empty_mask = np.zeros(source_count, dtype=bool)
    if not observed_clusters:
        return SourceSpaceClusterPermutationResult(
            status=CLUSTER_MASK_STATUS_NO_CANDIDATES,
            mask=empty_mask,
            t_values=observed_t,
            cluster_forming_threshold=threshold,
            cluster_forming_p_value=float(cluster_forming_p_value),
            cluster_alpha=float(cluster_alpha),
            permutation_count=0,
            permutation_seed=int(permutation_seed),
            tail=cluster_tail,
            clusters=(),
        )

    null_max_masses = permutation_max_cluster_masses(
        matrix,
        adjacency=normalized_adjacency,
        threshold=threshold,
        tail=cluster_tail,
        permutation_count=int(permutation_count),
        seed=int(permutation_seed),
    )
    clusters: list[SourceSpaceCluster] = []
    mask = empty_mask.copy()
    denominator = float(len(null_max_masses) + 1)
    for cluster_index, (candidate_tail, source_indices) in enumerate(observed_clusters, start=1):
        cluster_mass = cluster_mass_value(observed_t, source_indices, tail=candidate_tail)
        p_value = float((1 + np.count_nonzero(null_max_masses >= cluster_mass - 1e-12)) / denominator)
        significant = p_value <= float(cluster_alpha)
        if significant:
            mask[np.asarray(source_indices, dtype=np.int64)] = True
        clusters.append(
            SourceSpaceCluster(
                cluster_id=cluster_index,
                tail=candidate_tail,
                source_indices=tuple(int(index) for index in source_indices),
                cluster_mass=cluster_mass,
                p_value=p_value,
                significant=significant,
            )
        )

    return SourceSpaceClusterPermutationResult(
        status=CLUSTER_MASK_STATUS_COMPUTED,
        mask=mask,
        t_values=observed_t,
        cluster_forming_threshold=threshold,
        cluster_forming_p_value=float(cluster_forming_p_value),
        cluster_alpha=float(cluster_alpha),
        permutation_count=int(len(null_max_masses)),
        permutation_seed=int(permutation_seed),
        tail=cluster_tail,
        clusters=tuple(clusters),
    )


def adjacency_from_triangular_faces(faces: np.ndarray, *, source_count: int) -> tuple[set[int], ...]:
    """Build source adjacency from triangle faces."""
    adjacency = [set() for _ in range(int(source_count))]
    for triangle in triangle_faces_from_any_faces(faces):
        if not np.all((triangle >= 0) & (triangle < source_count)):
            raise ValueError("Cluster-mask source faces must refer to existing source points.")
        a, b, c = (int(index) for index in triangle)
        adjacency[a].update((b, c))
        adjacency[b].update((a, c))
        adjacency[c].update((a, b))
    return tuple(adjacency)


def adjacency_from_sparse_matrix(matrix: Any, *, source_count: int | None = None) -> tuple[set[int], ...]:
    """Convert an MNE/scipy sparse source adjacency matrix to adjacency sets."""
    try:
        sparse_matrix = matrix.tocsr()
        row_count, column_count = sparse_matrix.shape
        expected = row_count if source_count is None else int(source_count)
        if row_count != column_count or row_count != expected:
            raise ValueError("Sparse source adjacency must be square and match the source count.")
        adjacency = []
        for row_index in range(row_count):
            start = sparse_matrix.indptr[row_index]
            stop = sparse_matrix.indptr[row_index + 1]
            neighbors = {
                int(index)
                for index in sparse_matrix.indices[start:stop]
                if int(index) != row_index
            }
            adjacency.append(neighbors)
        return tuple(adjacency)
    except AttributeError:
        array = np.asarray(matrix)
        if array.ndim != 2 or array.shape[0] != array.shape[1]:
            raise ValueError("Dense source adjacency must be a square matrix.")
        expected = array.shape[0] if source_count is None else int(source_count)
        if array.shape[0] != expected:
            raise ValueError("Dense source adjacency must match the source count.")
        return tuple(
            {
                int(column_index)
                for column_index, connected in enumerate(row)
                if column_index != row_index and bool(connected)
            }
            for row_index, row in enumerate(array)
        )


def validate_adjacency(adjacency: Sequence[set[int]], *, source_count: int) -> tuple[set[int], ...]:
    """Validate and normalize adjacency sets."""
    rows = tuple(set(int(index) for index in row) for row in adjacency)
    if len(rows) != int(source_count):
        raise ValueError("Source adjacency must contain one row per source point.")
    for row_index, neighbors in enumerate(rows):
        if row_index in neighbors:
            neighbors.remove(row_index)
        if any(index < 0 or index >= int(source_count) for index in neighbors):
            raise ValueError("Source adjacency contains an out-of-range neighbor index.")
    return rows


def one_sample_t_values(matrix: np.ndarray) -> np.ndarray:
    """Return one-sample t values against zero for each source location."""
    values = np.asarray(matrix, dtype=float)
    participant_count = values.shape[0]
    means = np.mean(values, axis=0)
    sd = np.std(values, axis=0, ddof=1)
    t_values = np.zeros(values.shape[1], dtype=float)
    valid = np.isfinite(sd) & (sd > 1e-12)
    t_values[valid] = means[valid] / (sd[valid] / np.sqrt(float(participant_count)))
    return np.where(np.isfinite(t_values), t_values, 0.0)


def cluster_forming_t_threshold(*, participant_count: int, p_value: float, tail: str) -> float:
    """Return the t threshold for cluster candidate formation."""
    if participant_count < 2:
        raise ValueError("Cluster-forming threshold requires at least two participants.")
    cluster_tail = validate_cluster_tail(tail)
    tail_probability = float(p_value) / 2.0 if cluster_tail == CLUSTER_TAIL_TWO_SIDED else float(p_value)
    try:
        from scipy import stats

        threshold = float(stats.t.ppf(1.0 - tail_probability, df=participant_count - 1))
    except (ImportError, AttributeError, TypeError, ValueError) as exc:
        raise RuntimeError("SciPy is required for source-space cluster-forming thresholds.") from exc
    if not np.isfinite(threshold):
        raise ValueError("Cluster-forming threshold was not finite.")
    return threshold


def permutation_max_cluster_masses(
    matrix: np.ndarray,
    *,
    adjacency: Sequence[set[int]],
    threshold: float,
    tail: str,
    permutation_count: int,
    seed: int,
) -> np.ndarray:
    """Return null max-cluster masses from sign-flipped participant maps."""
    values = np.asarray(matrix, dtype=float)
    masses: list[float] = []
    for signs in sign_flip_vectors(values.shape[0], permutation_count=permutation_count, seed=seed):
        signed = values * signs[:, np.newaxis]
        t_values = one_sample_t_values(signed)
        clusters = signed_cluster_components(t_values, threshold=threshold, adjacency=adjacency, tail=tail)
        if clusters:
            masses.append(
                max(
                    cluster_mass_value(t_values, cluster_sources, tail=cluster_tail)
                    for cluster_tail, cluster_sources in clusters
                )
            )
        else:
            masses.append(0.0)
    return np.asarray(masses, dtype=float)


def sign_flip_vectors(
    participant_count: int,
    *,
    permutation_count: int,
    seed: int,
) -> Sequence[np.ndarray]:
    """Return exact or sampled sign-flip vectors."""
    exact_count = 2**participant_count
    if participant_count <= 12 and exact_count <= int(permutation_count):
        return tuple(exact_sign_vector(index, participant_count) for index in range(exact_count))
    rng = np.random.default_rng(int(seed))
    draws = rng.choice(np.asarray([-1.0, 1.0], dtype=float), size=(int(permutation_count), participant_count))
    return tuple(np.asarray(row, dtype=float) for row in draws)


def exact_sign_vector(index: int, participant_count: int) -> np.ndarray:
    """Return one exact sign-flip vector by bit index."""
    signs = np.empty(participant_count, dtype=float)
    for participant_index in range(participant_count):
        signs[participant_index] = 1.0 if (index >> participant_index) & 1 else -1.0
    return signs


def triangle_faces_from_any_faces(faces: np.ndarray) -> np.ndarray:
    """Normalize triangle faces from row or VTK-style face arrays."""
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


def cluster_components(
    candidate_mask: np.ndarray,
    adjacency: Sequence[set[int]],
) -> tuple[tuple[int, ...], ...]:
    """Return connected components among candidate source locations."""
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


def signed_cluster_components(
    t_values: np.ndarray,
    *,
    threshold: float,
    adjacency: Sequence[set[int]],
    tail: str,
) -> tuple[tuple[str, tuple[int, ...]], ...]:
    """Return positive/negative source clusters based on the requested tail."""
    cluster_tail = validate_cluster_tail(tail)
    values = np.asarray(t_values, dtype=float).reshape(-1)
    if cluster_tail == CLUSTER_TAIL_POSITIVE:
        return tuple((CLUSTER_TAIL_POSITIVE, cluster) for cluster in cluster_components(values >= threshold, adjacency))
    positive_clusters = tuple(
        (CLUSTER_TAIL_POSITIVE, cluster) for cluster in cluster_components(values >= threshold, adjacency)
    )
    negative_clusters = tuple(
        (CLUSTER_TAIL_NEGATIVE, cluster) for cluster in cluster_components(values <= -float(threshold), adjacency)
    )
    return (*positive_clusters, *negative_clusters)


def cluster_mass_value(t_values: np.ndarray, source_indices: Sequence[int], *, tail: str) -> float:
    """Return cluster mass for source indices."""
    values = np.asarray(t_values, dtype=float)[np.asarray(source_indices, dtype=np.int64)]
    cluster_tail = validate_cluster_tail(tail)
    if cluster_tail == CLUSTER_TAIL_NEGATIVE:
        return float(np.sum(-values))
    return float(np.sum(values))


def validate_cluster_tail(tail: str) -> str:
    """Validate a cluster tail identifier."""
    cluster_tail = str(tail).strip().lower()
    if cluster_tail not in {CLUSTER_TAIL_POSITIVE, CLUSTER_TAIL_TWO_SIDED, CLUSTER_TAIL_NEGATIVE}:
        raise ValueError("Cluster tail must be 'two-sided', 'positive', or 'negative'.")
    return cluster_tail
