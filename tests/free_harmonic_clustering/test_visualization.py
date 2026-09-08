from __future__ import annotations

from dataclasses import FrozenInstanceError, fields, replace
from pathlib import Path

import numpy as np
import pytest

from Tools.Free_Harmonic_Clustering.models import AnalysisDesign
from Tools.Free_Harmonic_Clustering.visualization import (
    ClusterMapData,
    build_cluster_map_data,
    build_repeated_cluster_map_data,
)

from tests.free_harmonic_clustering.test_exports import _prepared_and_result
from tests.free_harmonic_clustering.test_repeated_session_batch_inference import _batch_fixture


def test_map_background_uses_analyzed_mean_difference_and_retains_no_participants(tmp_path: Path) -> None:
    prepared, result = _prepared_and_result(tmp_path)
    data = build_cluster_map_data(prepared, result)

    expected = prepared.values_a.mean(axis=0) - prepared.values_b.mean(axis=0)
    np.testing.assert_array_equal(data.mean_difference, expected)
    assert not np.allclose(data.mean_difference, result.observed_t)
    assert not np.allclose(data.mean_difference, prepared.snr_a.mean(axis=0) - prepared.snr_b.mean(axis=0))
    assert data.arm_a_label == prepared.arm_a_label
    assert data.arm_b_label == prepared.arm_b_label
    assert data.harmonic_orders == (1, 2)
    assert data.harmonics_hz == (1.2, 2.4)
    assert data.clusters == (result.clusters[0],)
    np.testing.assert_array_equal(data.cluster_labels, [[1, 0], [0, 0]])
    assert data.color_limit == np.max(np.abs(expected))
    assert not np.shares_memory(data.mean_difference, prepared.values_a)
    assert not np.shares_memory(data.cluster_labels, result.cluster_labels)
    assert all(
        not isinstance(value := getattr(data, field.name), np.ndarray) or value.ndim == 2
        for field in fields(data)
    )
    with pytest.raises(ValueError, match="read-only"):
        data.mean_difference[0, 0] = 99
    with pytest.raises(ValueError, match="read-only"):
        data.cluster_labels[0, 0] = 99
    with pytest.raises(FrozenInstanceError):
        data.arm_a_label = "Changed"


def test_membership_keeps_electrode_harmonic_pairs_and_signed_original_ids(tmp_path: Path) -> None:
    prepared, result = _prepared_and_result(tmp_path)
    positive = replace(
        result.clusters[0],
        cluster_id=4,
        node_indices=(0, 3),
        sensor_indices=(0, 1),
        harmonic_indices=(0, 1),
    )
    negative = replace(result.clusters[1], cluster_id=-3, significant=True)
    means = np.array([[0.1, -0.2], [0.0, 0.05]])
    prepared = replace(prepared, values_a=prepared.values_b + means)
    result = replace(
        result,
        clusters=(positive, negative),
        observed_t=np.array([[2.0, -3.0], [0.0, 2.5]]),
        cluster_labels=np.array([[4, -3], [0, 4]]),
    )
    data = build_cluster_map_data(prepared, result)

    np.testing.assert_array_equal(data.cluster_labels[:, 0], [4, 0])
    np.testing.assert_array_equal(data.cluster_labels[:, 1], [-3, 4])
    assert {cluster.cluster_id for cluster in data.clusters} == {4, -3}
    assert data.color_limit == pytest.approx(0.2)


@pytest.mark.parametrize("malformation", ["extra_label", "wrong_pair", "wrong_t_sign"])
def test_map_rejects_inconsistent_source_membership_or_direction(tmp_path: Path, malformation: str) -> None:
    prepared, result = _prepared_and_result(tmp_path)
    if malformation == "extra_label":
        result = replace(result, cluster_labels=np.array([[1, -1], [1, 0]]))
    elif malformation == "wrong_pair":
        first = replace(result.clusters[0], sensor_indices=(1,))
        result = replace(result, clusters=(first, result.clusters[1]))
    elif malformation == "wrong_t_sign":
        result = replace(result, observed_t=-result.observed_t)
    with pytest.raises(ValueError):
        build_cluster_map_data(prepared, result)


def test_no_significant_clusters_keeps_descriptive_domain_and_shared_scale(tmp_path: Path) -> None:
    prepared, result = _prepared_and_result(tmp_path)
    result = replace(result, clusters=tuple(replace(cluster, significant=False) for cluster in result.clusters))
    data = build_cluster_map_data(prepared, result)
    assert data.clusters == ()
    assert not np.any(data.cluster_labels)
    assert data.mean_difference.shape == (2, 2)
    assert data.color_limit == pytest.approx(np.max(np.abs(data.mean_difference)))
    zero = replace(data, mean_difference=np.zeros_like(data.mean_difference))
    assert zero.color_limit == 1.0


def test_snapshot_preserves_nonconsecutive_harmonic_orders_without_refilling() -> None:
    data = ClusterMapData(
        sensor_names=("Fp1", "Fp2"),
        harmonic_orders=(1, 4, 6),
        harmonics_hz=(1.2, 4.8, 7.2),
        mean_difference=np.zeros((2, 3)),
        cluster_labels=np.zeros((2, 3), dtype=int),
        clusters=(),
        arm_a_label="Group A",
        arm_b_label="Group B",
    )
    assert data.harmonic_orders == (1, 4, 6)
    assert data.harmonics_hz == (1.2, 4.8, 7.2)


def test_repeated_maps_preserve_composite_tensor_semantics_and_run_holm(tmp_path: Path) -> None:
    _prepared, result = _batch_fixture(tmp_path)
    for outcome in result.outcomes:
        data = build_repeated_cluster_map_data(outcome)
        run = outcome.prepared_run
        np.testing.assert_allclose(
            data.mean_difference,
            run.prepared.values_a.mean(axis=0) - run.prepared.values_b.mean(axis=0),
        )
        assert run.condition in data.run_label
        assert run.family_label in data.run_label
        assert "within-run, sign-specific" in data.multiplicity_note
        assert "Holm values apply to the run, not individual clusters" in data.multiplicity_note
        assert f"Holm within family p = {outcome.holm_within_family_p_value:.4g}" in data.multiplicity_note
        if outcome.family_id == "group_session_change":
            assert data.value_label == "Mean normalized SNR change difference"
        elif outcome.family_id == "session_averaged_groups":
            assert data.value_label == "Mean session-averaged normalized SNR difference"
        else:
            assert data.value_label == "Mean normalized SNR session difference"


def test_group_change_background_is_not_renormalized(tmp_path: Path) -> None:
    _prepared, result = _batch_fixture(tmp_path)
    outcome = result.outcomes[-1]
    # A group-by-session change may contain negative components and need not
    # have unit length. Its descriptive map must preserve both facts.
    values_a = np.array([[[0.02, -0.1], [-0.2, 0.1]], [[0.04, -0.2], [-0.1, 0.0]]])
    values_b = np.array([[[0.01, -0.05], [-0.1, 0.0]], [[0.01, -0.1], [-0.05, -0.1]]])
    contrast = replace(outcome.prepared_run.prepared, values_a=values_a, values_b=values_b)
    outcome = replace(outcome, prepared_run=replace(outcome.prepared_run, prepared=contrast))
    data = build_repeated_cluster_map_data(outcome)
    np.testing.assert_array_equal(data.mean_difference, values_a.mean(axis=0) - values_b.mean(axis=0))


def test_paired_difference_averages_original_pair_differences_before_cancellation(tmp_path: Path) -> None:
    prepared, result = _prepared_and_result(tmp_path)
    values_b = np.full((2, 2, 2), 0.5)
    values_a = values_b.copy()
    values_a[0, 0, 0] = np.nextafter(0.5, 1.0)
    prepared = replace(
        prepared,
        request=replace(
            prepared.request,
            design=AnalysisDesign.PAIRED_CONDITIONS,
            condition_b="Neutral Happy",
            group_ids=(),
        ),
        participant_ids_b=prepared.participant_ids_a,
        values_a=values_a,
        values_b=values_b,
    )
    result = replace(result, design=AnalysisDesign.PAIRED_CONDITIONS)
    data = build_cluster_map_data(prepared, result)
    assert (values_a.mean(axis=0) - values_b.mean(axis=0))[0, 0] == 0
    assert data.mean_difference[0, 0] > 0
    assert np.isfinite(data.color_limit)
