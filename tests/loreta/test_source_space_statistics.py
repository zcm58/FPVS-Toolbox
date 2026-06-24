from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from Tools.LORETA_Visualizer.source_producers.source_space_statistics import (
    adjacency_from_triangular_faces,
    compute_source_space_cluster_permutation_mask,
)


def test_source_space_cluster_permutation_keeps_connected_positive_cluster() -> None:
    rows = []
    for index, scale in enumerate((0.92, 0.96, 1.0, 1.04, 1.08, 1.12), start=1):
        noise_value = 0.35 if index % 2 else -0.35
        rows.append(
            SimpleNamespace(
                values=np.asarray([4.2 * scale, 4.0 * scale, 3.8 * scale, noise_value, -0.04], dtype=float)
            )
        )
    adjacency = adjacency_from_triangular_faces(
        np.asarray([[0, 1, 2], [2, 3, 4]], dtype=np.int64),
        source_count=5,
    )

    result = compute_source_space_cluster_permutation_mask(
        tuple(rows),
        adjacency=adjacency,
        cluster_forming_p_value=0.00001,
        cluster_alpha=0.05,
        permutation_count=128,
        permutation_seed=13,
    )

    assert result.cluster_forming_p_value == pytest.approx(0.00001)
    assert result.cluster_alpha == pytest.approx(0.05)
    assert result.tail == "positive"
    assert result.permutation_count == 64
    assert result.mask.tolist() == [True, True, True, False, False]
    assert [cluster.source_indices for cluster in result.significant_clusters] == [(0, 1, 2)]


def test_source_space_cluster_permutation_rejects_misaligned_adjacency() -> None:
    rows = (
        SimpleNamespace(values=np.asarray([1.0, 2.0], dtype=float)),
        SimpleNamespace(values=np.asarray([1.2, 2.1], dtype=float)),
    )

    with pytest.raises(ValueError, match="one row per source point"):
        compute_source_space_cluster_permutation_mask(
            rows,
            adjacency=(set(),),
            cluster_forming_p_value=0.05,
            cluster_alpha=0.05,
            permutation_count=16,
            permutation_seed=1,
        )
