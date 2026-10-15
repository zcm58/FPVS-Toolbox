from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
from scipy import stats

from Tools.LORETA_Visualizer.source_producers.source_space_statistics import (
    adjacency_from_triangular_faces,
    compute_source_space_cluster_permutation_mask,
    cluster_inference_metadata,
    sign_flip_vectors,
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


@pytest.mark.parametrize(
    ("tail", "alternative", "direction"),
    [("positive", "greater", 1), ("negative", "less", -1), ("two-sided", "two-sided", 1)],
)
def test_exact_single_source_p_value_matches_scipy(tail, alternative, direction) -> None:
    """The observed sign pattern is already included in an exhaustive null."""
    values = direction * np.asarray([9.0, 10.0, 11.0, 10.0, 9.0])
    result = _run(values[:, None], tail=tail)
    reference = stats.permutation_test(
        (values,),
        lambda sample: stats.ttest_1samp(sample, 0.0).statistic,
        permutation_type="samples",
        vectorized=False,
        n_resamples=np.inf,
        alternative=alternative,
    )

    assert result.permutation_count == 32
    assert result.permutation_mode == "exact"
    assert len(result.clusters) == 1
    assert result.clusters[0].tail == ("negative" if direction < 0 else "positive")
    assert result.clusters[0].p_value == pytest.approx(reference.pvalue)
    assert result.mask[0] == (tail != "two-sided")
    assert result.minimum_attainable_p == (2 if tail == "two-sided" else 1) / 32
    assert cluster_inference_metadata(result)["cluster_mask_algorithm_version"] == 2
    assert cluster_inference_metadata(result)["cluster_p_value_estimator"] == "exact_tail_proportion"


def test_negative_tail_excludes_positive_candidates() -> None:
    values = np.asarray([9.0, 10.0, 11.0, 10.0, 9.0])
    result = _run(np.column_stack([values, -values]), tail="negative")

    assert [cluster.source_indices for cluster in result.clusters] == [(1,)]
    assert result.mask.tolist() == [False, False]
    # Either opposite source can contribute the maximum negative mass.
    assert result.clusters[0].p_value == pytest.approx(2 / 32)


def test_sampled_sign_flips_are_deterministic_and_use_plus_one() -> None:
    values = np.asarray([2.4, 1.2, 0.8, 3.6, 2.1, 1.0])
    draw_count, seed = 20, 874
    result = _run(values[:, None], count=draw_count, seed=seed)
    again = _run(values[:, None], count=draw_count, seed=seed)
    # Independent scalar-t reference, using the specified random generator.
    signs = np.random.default_rng(seed).choice([-1.0, 1.0], size=(draw_count, len(values)))
    null_t = stats.ttest_1samp(signs * values, 0.0, axis=1).statistic
    observed_t = stats.ttest_1samp(values, 0.0).statistic
    expected = (np.count_nonzero(null_t >= observed_t - 1e-12) + 1) / (draw_count + 1)

    assert result.permutation_count == draw_count
    assert result.permutation_mode == "sampled"
    assert result.clusters[0].p_value == expected
    assert result.clusters == again.clusters
    assert np.array_equal(result.mask, again.mask)
    assert result.minimum_attainable_p == 1 / 21
    assert cluster_inference_metadata(result)["cluster_p_value_estimator"] == "monte_carlo_plus_one"


@pytest.mark.parametrize("tail", ["positive", "two-sided"])
def test_exact_cluster_family_controls_error_over_complete_sign_orbit(tail) -> None:
    """Finite null calibration for sign-symmetric source maps, not EEG accuracy.

    Every row-sign combination is equiprobable under this conditional null.
    Count any retained cluster across four connected/disconnected locations.
    """
    matrix = np.random.default_rng(481).normal(size=(6, 4))
    matrix[:, 1] += matrix[:, 0] * 0.65
    adjacency = ({1}, {0}, {3}, {2})
    signs = sign_flip_vectors(6, permutation_count=64, seed=0)
    rejections = sum(
        bool(np.any(_run(matrix * flip[:, None], adjacency=adjacency, tail=tail).mask))
        for flip in signs
    )

    assert 0 < rejections / len(signs) <= 0.05


def test_no_candidate_result_retains_planned_resolution() -> None:
    result = _run(np.asarray([-2.0, -1.0, 0.0, 1.0])[:, None])
    assert result.status == "no_candidate_clusters"
    assert result.permutation_count == 0
    assert result.permutation_count_requested == 1024
    assert result.minimum_attainable_p == 1 / 16
    assert result.participant_count == 4


def _run(matrix, *, adjacency=None, tail="positive", count=1024, seed=13):
    return compute_source_space_cluster_permutation_mask(
        tuple(SimpleNamespace(values=row) for row in matrix),
        adjacency=adjacency if adjacency is not None else [set() for _ in range(matrix.shape[1])],
        cluster_forming_p_value=0.05,
        cluster_alpha=0.05,
        permutation_count=count,
        permutation_seed=seed,
        tail=tail,
    )
