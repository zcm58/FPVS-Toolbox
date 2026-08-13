from __future__ import annotations

import numpy as np
import pytest

from Tools.Free_Harmonic_Clustering.analysis import (
    BIOSEMI64_ADJACENCY_FINGERPRINT,
    BIOSEMI64_CHANNELS,
    AnalysisCancelled,
    DegenerateVarianceWarning,
    NEGATIVE_TAIL,
    POSITIVE_TAIL,
    biosemi64_adjacency_manifest,
    biosemi64_edge_export,
    biosemi64_spatial_adjacency,
    cartesian_free_harmonic_adjacency,
    cartesian_free_harmonic_edges,
    cluster_forming_t_threshold,
    cluster_monte_carlo_p_value,
    independent_cluster_effect_size,
    independent_permutation_t_maps,
    independent_t_map,
    paired_cluster_effect_size,
    paired_permutation_t_maps,
    paired_t_map,
    public_result_from_core,
    run_cluster_permutation,
    run_cluster_permutation_core,
    signed_cluster_components,
    signed_null_extrema,
)
from Tools.Free_Harmonic_Clustering.models import (
    AnalysisDesign,
    ClusterPermutationResult,
    FreeHarmonicMethodSpec,
)


def _chain_adjacency(sensor_count: int) -> np.ndarray:
    adjacency = np.zeros((sensor_count, sensor_count), dtype=bool)
    for sensor in range(sensor_count - 1):
        adjacency[sensor, sensor + 1] = True
        adjacency[sensor + 1, sensor] = True
    return adjacency


def test_biosemi64_adjacency_has_fixed_auditable_identity() -> None:
    adjacency = biosemi64_spatial_adjacency()
    edges = biosemi64_edge_export()
    manifest = biosemi64_adjacency_manifest()

    assert adjacency.shape == (64, 64)
    assert adjacency.dtype == np.bool_
    assert np.array_equal(adjacency, adjacency.T)
    assert not np.any(np.diag(adjacency))
    assert int(np.count_nonzero(adjacency) // 2) == 197
    assert len(edges) == 197
    assert len(set(edges)) == len(edges)
    assert BIOSEMI64_ADJACENCY_FINGERPRINT == (
        "9aa6734d6ed392c20b02f9e3e5ed56c224aaf0c6cacc95eb351b7923b1629fd6"
    )
    assert manifest["fingerprint_sha256"] == BIOSEMI64_ADJACENCY_FINGERPRINT
    assert manifest["edge_count"] == 197
    assert manifest["base_edge_count"] == 169
    assert manifest["added_edge_count"] == 28
    assert manifest["edges"] == [list(edge) for edge in edges]
    assert {tuple(edge) for edge in manifest["added_edges"]} == {
        ("Fp1", "F1"),
        ("AF3", "F5"),
        ("F3", "FC5"),
        ("F5", "FT7"),
        ("FC5", "T7"),
        ("FC3", "C5"),
        ("FC1", "C3"),
        ("C3", "CP1"),
        ("C5", "CP3"),
        ("T7", "CP5"),
        ("TP7", "P5"),
        ("CP5", "P3"),
        ("P1", "O1"),
        ("P5", "PO3"),
        ("Fp2", "F2"),
        ("AF4", "F6"),
        ("F4", "FC6"),
        ("F6", "FT8"),
        ("FC6", "T8"),
        ("FC4", "C6"),
        ("FC2", "C4"),
        ("C4", "CP2"),
        ("C6", "CP4"),
        ("T8", "CP6"),
        ("TP8", "P6"),
        ("CP6", "P4"),
        ("P2", "O2"),
        ("P6", "PO4"),
    }

    # A breadth-first check guards accidental graph fragmentation.
    seen = {0}
    frontier = [0]
    while frontier:
        sensor = frontier.pop()
        for neighbor in np.flatnonzero(adjacency[sensor]):
            neighbor_index = int(neighbor)
            if neighbor_index not in seen:
                seen.add(neighbor_index)
                frontier.append(neighbor_index)
    assert len(seen) == 64


def test_biosemi64_adjacency_reorders_by_name_but_rejects_channel_drift() -> None:
    reordered_names = tuple(reversed(BIOSEMI64_CHANNELS))
    reordered = biosemi64_spatial_adjacency(reordered_names)
    canonical = biosemi64_spatial_adjacency()
    reverse_indices = np.arange(63, -1, -1)

    assert np.array_equal(reordered, canonical[np.ix_(reverse_indices, reverse_indices)])
    with pytest.raises(ValueError, match="exactly 64"):
        biosemi64_spatial_adjacency(BIOSEMI64_CHANNELS[:-1])
    with pytest.raises(ValueError, match="channel mismatch"):
        biosemi64_spatial_adjacency((*BIOSEMI64_CHANNELS[:-1], "BAD"))


def test_cartesian_graph_is_sensor_major_and_has_no_diagonal_edges() -> None:
    spatial = _chain_adjacency(3)
    combined = cartesian_free_harmonic_adjacency(spatial, harmonic_count=3)
    edges = cartesian_free_harmonic_edges(spatial, harmonic_count=3)

    assert combined.shape == (9, 9)
    assert np.array_equal(combined, combined.T)
    assert not np.any(np.diag(combined))
    assert int(np.count_nonzero(combined) // 2) == 15  # 3*C(3,2) + 2*3
    assert set(edges) == set(zip(*np.where(np.triu(combined, k=1))))

    # Same sensor: every distinct harmonic is adjacent.
    assert combined[0 * 3 + 0, 0 * 3 + 2]
    # Spatial neighbours: only equal harmonic indices are directly adjacent.
    assert combined[0 * 3 + 1, 1 * 3 + 1]
    assert not combined[0 * 3 + 1, 1 * 3 + 2]
    # Non-neighbour sensors have no direct edge.
    assert not combined[0 * 3 + 0, 2 * 3 + 0]


@pytest.mark.parametrize(
    ("degrees_of_freedom", "expected"),
    ((18, 2.878440472713585), (29, 2.7563859036703344)),
)
def test_cluster_forming_threshold_is_two_tailed_point_zero_one(
    degrees_of_freedom: int,
    expected: float,
) -> None:
    assert cluster_forming_t_threshold(degrees_of_freedom) == pytest.approx(expected, rel=1e-14)


def test_paired_t_and_cluster_average_dz_match_golden_values() -> None:
    condition_a = np.asarray([1.0, 2.0, 3.0, 4.0]).reshape(4, 1, 1)
    condition_b = np.zeros_like(condition_a)

    t_map, degrees_of_freedom = paired_t_map(condition_a, condition_b)
    effect = paired_cluster_effect_size(condition_a, condition_b, (0,))

    assert degrees_of_freedom == 3
    assert t_map[0, 0] == pytest.approx(3.872983346207417)
    assert effect == pytest.approx(1.9364916731037085)


def test_paired_permutation_t_maps_match_vectorized_golden_matrix() -> None:
    differences = np.asarray([[1.0, 2.0], [2.0, 0.0], [3.0, -2.0]]).reshape(3, 1, 2)
    signs = np.asarray(
        [[1, 1, 1], [1, -1, 1], [-1, -1, -1], [1, 1, -1]],
        dtype=np.int8,
    )
    expected = np.asarray(
        [
            [3.4641016151377544, 0.0],
            [0.4588314677411235, 0.0],
            [-3.4641016151377544, 0.0],
            [0.0, 2.0],
        ]
    )

    actual = paired_permutation_t_maps(differences, signs)

    assert actual.shape == (4, 1, 2)
    assert actual[:, 0, :] == pytest.approx(expected)


def test_zero_variance_t_conventions_are_explicit() -> None:
    identical_nonzero = np.ones((3, 1, 2), dtype=float)
    zeros = np.zeros_like(identical_nonzero)

    with pytest.warns(DegenerateVarianceWarning):
        t_map, _ = paired_t_map(identical_nonzero, zeros)

    assert np.isposinf(t_map[0, 0])
    assert np.isposinf(t_map[0, 1])
    zero_t, _ = paired_t_map(zeros, zeros)
    assert np.array_equal(zero_t, np.zeros((1, 2)))


def test_independent_pooled_t_and_cluster_average_d_match_golden_values() -> None:
    group_a = np.asarray([1.0, 2.0, 3.0]).reshape(3, 1, 1)
    group_b = np.asarray([4.0, 6.0]).reshape(2, 1, 1)

    t_map, degrees_of_freedom = independent_t_map(group_a, group_b)
    effect = independent_cluster_effect_size(group_a, group_b, (0,))

    assert degrees_of_freedom == 3
    assert t_map[0, 0] == pytest.approx(-2.8460498941515415)
    assert effect == pytest.approx(-2.598076211353316)


def test_independent_permutation_t_maps_equal_direct_pooled_t_maps() -> None:
    pooled = np.asarray([1.0, 2.0, 3.0, 4.0, 6.0]).reshape(5, 1, 1)
    masks = np.asarray(
        [
            [1, 1, 1, 0, 0],
            [1, 0, 0, 1, 1],
            [0, 1, 1, 0, 1],
        ],
        dtype=bool,
    )

    batch = independent_permutation_t_maps(pooled, masks)

    for row_index, mask in enumerate(masks):
        direct, _ = independent_t_map(pooled[mask], pooled[~mask])
        assert batch[row_index] == pytest.approx(direct)


def test_components_include_compound_path_and_isolated_singleton() -> None:
    spatial = np.zeros((4, 4), dtype=bool)
    spatial[0, 1] = spatial[1, 0] = True
    spatial[1, 2] = spatial[2, 1] = True
    t_map = np.zeros((4, 4), dtype=float)
    t_map[0, 0] = 3.0
    t_map[1, 0] = 4.0
    t_map[1, 2] = 5.0
    t_map[2, 2] = 6.0
    t_map[3, 1] = 7.0
    t_map[0, 3] = -4.0
    t_map[1, 3] = -5.0

    clusters = signed_cluster_components(t_map, spatial_adjacency=spatial, threshold=3.0)

    assert [(cluster.tail, cluster.node_indices, cluster.mass) for cluster in clusters] == [
        (POSITIVE_TAIL, (0, 4, 6, 10), 18.0),
        (POSITIVE_TAIL, (13,), 7.0),
        (NEGATIVE_TAIL, (3, 7), -9.0),
    ]
    assert clusters[0].sensor_harmonic_indices == ((0, 0), (1, 0), (1, 2), (2, 2))


def test_diagonal_sensor_plus_harmonic_nodes_do_not_connect() -> None:
    spatial = np.asarray([[False, True], [True, False]])
    t_map = np.asarray([[3.0, 0.0], [0.0, 4.0]])

    clusters = signed_cluster_components(t_map, spatial_adjacency=spatial, threshold=3.0)

    assert [cluster.node_indices for cluster in clusters] == [(3,), (0,)]


def test_opposite_signs_never_share_a_cluster_and_threshold_is_inclusive() -> None:
    spatial = np.asarray([[False, True], [True, False]])
    t_map = np.asarray([[3.0], [-3.0]])

    clusters = signed_cluster_components(t_map, spatial_adjacency=spatial, threshold=3.0)

    assert [(cluster.tail, cluster.node_indices) for cluster in clusters] == [
        (POSITIVE_TAIL, (0,)),
        (NEGATIVE_TAIL, (1,)),
    ]


def test_signed_null_extrema_use_zero_when_a_tail_has_no_cluster() -> None:
    maps = np.asarray(
        [
            [[4.0, 3.0], [0.0, 0.0]],
            [[-5.0, 0.0], [-4.0, 0.0]],
            [[0.0, 0.0], [0.0, 0.0]],
        ]
    )
    positive, negative = signed_null_extrema(
        maps,
        spatial_adjacency=_chain_adjacency(2),
        threshold=3.0,
    )

    assert positive.tolist() == [7.0, 0.0, 0.0]
    assert negative.tolist() == [0.0, -9.0, 0.0]


@pytest.mark.parametrize(
    ("tail", "observed", "null"),
    (
        (POSITIVE_TAIL, 7.0, np.asarray([0.0, 3.0, 7.0, 8.0])),
        (NEGATIVE_TAIL, -5.0, np.asarray([0.0, -4.0, -5.0, -6.0])),
    ),
)
def test_cluster_p_value_uses_strict_comparison_plus_one_and_exposes_ties(
    tail: str,
    observed: float,
    null: np.ndarray,
) -> None:
    result = cluster_monte_carlo_p_value(tail=tail, observed_mass=observed, null_extrema=null)

    assert result.p_value == pytest.approx(0.4)
    assert result.conservative_p_value == pytest.approx(0.6)
    assert result.tie_count == 1
    assert result.adjusted_two_sided_p_value == pytest.approx(0.8)
    assert not result.significant
    assert result.confidence_interval_straddles_alpha


def test_final_cluster_alpha_is_point_zero_two_five_not_point_zero_five() -> None:
    # 2 strict exceedances among 99 assignments => (1 + 2) / 100 = .03.
    null = np.concatenate((np.asarray([11.0, 12.0]), np.zeros(97)))
    result = cluster_monte_carlo_p_value(
        tail=POSITIVE_TAIL,
        observed_mass=10.0,
        null_extrema=null,
    )

    assert result.p_value == pytest.approx(0.03)
    assert not result.significant


def test_missing_values_are_rejected_instead_of_pairwise_dropped() -> None:
    first = np.ones((3, 1, 1), dtype=float)
    second = np.zeros_like(first)
    first[1, 0, 0] = np.nan

    with pytest.raises(ValueError, match="complete maps"):
        paired_t_map(first, second)


def test_paired_monte_carlo_is_seeded_and_batch_size_invariant() -> None:
    condition_a = np.asarray(
        [
            [[1.0, 0.2], [0.4, -0.2]],
            [[1.4, 0.1], [0.2, -0.4]],
            [[0.8, 0.5], [0.1, -0.1]],
            [[1.2, 0.3], [0.3, -0.5]],
            [[1.6, 0.4], [0.5, -0.3]],
            [[0.9, 0.0], [0.0, -0.6]],
        ]
    )
    condition_b = np.zeros_like(condition_a)
    adjacency = _chain_adjacency(2)

    one_at_a_time = run_cluster_permutation_core(
        condition_a,
        condition_b,
        design="paired_conditions",
        spatial_adjacency=adjacency,
        permutation_count=64,
        seed=17,
        batch_size=1,
    )
    uneven_batches = run_cluster_permutation_core(
        condition_a,
        condition_b,
        design="paired_conditions",
        spatial_adjacency=adjacency,
        permutation_count=64,
        seed=17,
        batch_size=19,
    )

    assert uneven_batches.observed_t == pytest.approx(one_at_a_time.observed_t)
    assert np.array_equal(uneven_batches.null_positive_maxima, one_at_a_time.null_positive_maxima)
    assert np.array_equal(uneven_batches.null_negative_minima, one_at_a_time.null_negative_minima)
    assert uneven_batches.clusters == one_at_a_time.clusters
    assert uneven_batches.rng_algorithm == "PCG64"
    assert uneven_batches.permutation_assignment_hash == one_at_a_time.permutation_assignment_hash
    assert len(uneven_batches.permutation_assignment_hash) == 64


def test_independent_monte_carlo_preserves_group_sizes_and_batch_sequence() -> None:
    group_a = np.asarray(
        [
            [[1.0, 0.2]],
            [[1.3, -0.1]],
            [[0.8, 0.4]],
        ]
    )
    group_b = np.asarray(
        [
            [[-0.4, 0.1]],
            [[-0.8, -0.3]],
            [[-0.5, 0.0]],
            [[-0.2, -0.2]],
        ]
    )
    adjacency = np.zeros((1, 1), dtype=bool)

    first = run_cluster_permutation_core(
        group_a,
        group_b,
        design="independent_groups",
        spatial_adjacency=adjacency,
        permutation_count=37,
        seed=9,
        batch_size=4,
    )
    second = run_cluster_permutation_core(
        group_a,
        group_b,
        design="independent_groups",
        spatial_adjacency=adjacency,
        permutation_count=37,
        seed=9,
        batch_size=23,
    )

    assert np.array_equal(first.null_positive_maxima, second.null_positive_maxima)
    assert np.array_equal(first.null_negative_minima, second.null_negative_minima)
    assert first.clusters == second.clusters


def test_condition_swap_flips_paired_t_map() -> None:
    first = np.asarray([1.0, 2.0, 4.0, 8.0]).reshape(4, 1, 1)
    second = np.asarray([0.0, 1.0, 1.0, 2.0]).reshape(4, 1, 1)

    forward, _ = paired_t_map(first, second)
    reverse, _ = paired_t_map(second, first)

    assert reverse == pytest.approx(-forward)


def test_complete_harmonic_graph_makes_cluster_membership_reorder_invariant() -> None:
    adjacency = _chain_adjacency(2)
    original = np.asarray([[3.0, 0.0, 4.0], [5.0, 0.0, 6.0]])
    order = np.asarray([2, 0, 1])
    reordered = original[:, order]

    original_clusters = signed_cluster_components(original, spatial_adjacency=adjacency, threshold=3.0)
    reordered_clusters = signed_cluster_components(reordered, spatial_adjacency=adjacency, threshold=3.0)

    assert [cluster.mass for cluster in reordered_clusters] == pytest.approx(
        [cluster.mass for cluster in original_clusters]
    )
    assert [len(cluster.node_indices) for cluster in reordered_clusters] == [
        len(cluster.node_indices) for cluster in original_clusters
    ]


def test_cancellation_is_checked_at_batch_boundaries_without_partial_result() -> None:
    first = np.arange(1.0, 7.0).reshape(6, 1, 1)
    second = np.zeros_like(first)
    calls = 0

    def cancel_check() -> bool:
        nonlocal calls
        calls += 1
        return calls >= 2

    with pytest.raises(AnalysisCancelled):
        run_cluster_permutation_core(
            first,
            second,
            design="paired_conditions",
            spatial_adjacency=np.zeros((1, 1), dtype=bool),
            permutation_count=20,
            seed=1,
            batch_size=5,
            cancel_check=cancel_check,
        )


def test_core_adapter_builds_signed_labels_and_public_cluster_records() -> None:
    condition_a = np.asarray(
        [
            [[1.0, -1.1], [0.2, -0.4]],
            [[1.3, -1.4], [0.4, -0.7]],
            [[0.8, -0.9], [0.1, -0.3]],
            [[1.5, -1.6], [0.5, -0.8]],
            [[1.1, -1.2], [0.3, -0.5]],
            [[0.9, -1.0], [0.0, -0.2]],
        ]
    )
    core = run_cluster_permutation_core(
        condition_a,
        np.zeros_like(condition_a),
        design=AnalysisDesign.PAIRED_CONDITIONS,
        spatial_adjacency=_chain_adjacency(2),
        permutation_count=32,
        seed=4,
        batch_size=7,
    )

    result = public_result_from_core(
        core,
        sensor_adjacency_version="synthetic-chain-v1",
        sensor_adjacency_fingerprint="synthetic-fingerprint",
        sensor_adjacency_edges=(("A", "B"),),
    )

    assert isinstance(result, ClusterPermutationResult)
    assert result.design is AnalysisDesign.PAIRED_CONDITIONS
    assert not result.observed_t.flags.writeable
    assert not result.cluster_labels.flags.writeable
    assert {int(value) for value in np.unique(result.cluster_labels)} <= {
        0,
        *(record.cluster_id for record in result.clusters),
    }
    for record in result.clusters:
        assert (record.cluster_id > 0) == (record.sign == POSITIVE_TAIL)
        assert len(record.node_indices) == len(record.sensor_indices) == len(record.harmonic_indices)
        for node, sensor, harmonic in zip(
            record.node_indices,
            record.sensor_indices,
            record.harmonic_indices,
            strict=True,
        ):
            assert node == sensor * condition_a.shape[2] + harmonic


def test_public_adapter_preserves_signed_infinite_mass_and_undefined_effect() -> None:
    arm_a = np.tile(np.asarray([[[1.0], [-1.0]]]), (3, 1, 1))
    arm_b = np.zeros_like(arm_a)

    with pytest.warns(DegenerateVarianceWarning):
        core = run_cluster_permutation_core(
            arm_a,
            arm_b,
            design=AnalysisDesign.PAIRED_CONDITIONS,
            spatial_adjacency=_chain_adjacency(2),
            permutation_count=8,
            seed=2,
            batch_size=3,
        )
    result = public_result_from_core(
        core,
        sensor_adjacency_version="synthetic-chain-v1",
        sensor_adjacency_fingerprint="synthetic-fingerprint",
        sensor_adjacency_edges=(("A", "B"),),
    )

    assert [record.mass for record in result.clusters] == [np.inf, -np.inf]
    assert all(record.effect_size is None and record.effect_size_kind is None for record in result.clusters)
    assert any("infinite values" in warning for warning in result.warnings)


def test_public_array_runner_records_fixed_biosemi_provenance() -> None:
    participant_scales = np.asarray([0.75, 0.9, 1.0, 1.1, 1.25, 1.4])
    sensor_profile = np.linspace(-1.0, 1.0, 64)
    arm_a = participant_scales[:, None, None] * sensor_profile[None, :, None]
    arm_b = np.zeros_like(arm_a)
    method = FreeHarmonicMethodSpec(n_permutations=12, seed=23)

    result = run_cluster_permutation(
        arm_a,
        arm_b,
        design=AnalysisDesign.PAIRED_CONDITIONS,
        method=method,
        batch_size=5,
    )

    assert result.observed_t.shape == (64, 1)
    assert result.permutations_evaluated == 12
    assert result.sensor_adjacency_fingerprint == BIOSEMI64_ADJACENCY_FINGERPRINT
    assert result.sensor_adjacency_edges == biosemi64_edge_export()
    assert result.rng_algorithm == "PCG64"
    assert result.seed == 23
    assert any("not been numerically author-validated" in warning for warning in result.warnings)


@pytest.mark.parametrize(
    ("design", "data_seed", "shape_a", "shape_b"),
    (
        ("paired_conditions", 98231, (10, 2, 3), (10, 2, 3)),
        ("independent_groups", 98232, (9, 2, 3), (12, 2, 3)),
    ),
)
def test_fixed_domain_gaussian_null_has_reasonable_global_rejection_rate(
    design: str,
    data_seed: int,
    shape_a: tuple[int, int, int],
    shape_b: tuple[int, int, int],
) -> None:
    """Catch gross FWER regressions without mixing in adaptive selection."""

    rng = np.random.default_rng(data_seed)
    adjacency = _chain_adjacency(2)
    rejections = 0
    replicate_count = 200
    for replicate in range(replicate_count):
        arm_a = rng.normal(size=shape_a)
        arm_b = rng.normal(size=shape_b)
        result = run_cluster_permutation_core(
            arm_a,
            arm_b,
            design=design,
            spatial_adjacency=adjacency,
            permutation_count=199,
            seed=3000 + replicate,
            batch_size=43,
        )
        rejections += any(
            cluster.inference.significant for cluster in result.clusters
        )

    # The deterministic fixtures yield 8/200 for each design. The wider bound
    # reflects finite Monte Carlo and simulation uncertainty while still
    # detecting a clear loss of global null control.
    assert rejections <= 20
