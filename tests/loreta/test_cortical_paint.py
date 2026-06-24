from __future__ import annotations

import numpy as np

from Tools.LORETA_Visualizer.cortical_paint import (
    payload_cluster_mask,
    payload_cluster_mask_is_empty,
    payload_cluster_mask_is_underpowered,
    payload_cluster_mask_minimum_p,
    payload_has_cluster_mask,
    project_cortical_surface_payload,
    source_payload_uses_zscores,
    uses_cortical_surface_paint,
)
from Tools.LORETA_Visualizer.source_payloads import SOURCE_KIND_SURFACE_MESH, SOURCE_KIND_VOLUME_MESH, make_source_payload


def test_cortical_paint_projects_source_values_to_dense_display_mesh() -> None:
    payload = make_source_payload(
        points=np.asarray([[0.0, 0.0, 0.0], [2.0, 0.0, 0.0]], dtype=float),
        values=np.asarray([-2.0, 4.0], dtype=float),
        label="surface z",
        kind=SOURCE_KIND_SURFACE_MESH,
        source_model="l2_mne_cortical_surface_hauk_zscore_beta",
        value_label="source-space z-score",
        faces=np.asarray([[0, 1, 1]], dtype=np.int64),
        metadata={"source_value_unit": "z-score"},
        normalize_values=False,
    )
    original_values = payload.values.copy()
    display_points = np.asarray(
        [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 0.0, 0.0]],
        dtype=float,
    )

    projection = project_cortical_surface_payload(display_points, payload, neighbors=2)

    assert uses_cortical_surface_paint(payload) is True
    assert source_payload_uses_zscores(payload) is True
    assert projection.source_value_min == -2.0
    assert projection.source_value_max == 4.0
    assert np.isnan(projection.values[0])
    assert projection.values[1:].tolist() == [2.0, 4.0]
    assert np.array_equal(payload.values, original_values)


def test_cortical_paint_threshold_masks_subthreshold_zscores() -> None:
    payload = make_source_payload(
        points=np.asarray([[0.0, 0.0, 0.0], [2.0, 0.0, 0.0]], dtype=float),
        values=np.asarray([1.2, 2.0], dtype=float),
        label="surface z",
        kind=SOURCE_KIND_SURFACE_MESH,
        source_model="l2_mne_cortical_surface_hauk_zscore_beta",
        value_label="source-space z-score",
        faces=np.asarray([[0, 1, 1]], dtype=np.int64),
        metadata={"source_value_unit": "z-score"},
        normalize_values=False,
    )

    projection = project_cortical_surface_payload(payload.points, payload, neighbors=1, z_threshold=1.64)

    assert np.isnan(projection.values[0])
    assert projection.values[1] == 2.0


def test_cortical_paint_cluster_mask_overrides_display_threshold() -> None:
    payload = make_source_payload(
        points=np.asarray([[0.0, 0.0, 0.0], [2.0, 0.0, 0.0]], dtype=float),
        values=np.asarray([0.8, 4.0], dtype=float),
        label="cluster masked surface z",
        kind=SOURCE_KIND_SURFACE_MESH,
        source_model="l2_mne_fsaverage_participant_zscore_mean",
        value_label="source-space z-score",
        faces=np.asarray([[0, 1, 1]], dtype=np.int64),
        metadata={
            "source_value_unit": "z-score",
            "cluster_mask": "source_space_cluster_permutation",
            "cluster_mask_vertex_indices": [0],
        },
        normalize_values=False,
    )

    projection = project_cortical_surface_payload(payload.points, payload, neighbors=1, z_threshold=1.64)

    assert payload_has_cluster_mask(payload) is True
    assert payload_cluster_mask(payload).tolist() == [True, False]
    assert projection.values[0] == 0.8
    assert np.isnan(projection.values[1])


def test_cortical_paint_can_disable_cluster_mask_for_exploratory_display() -> None:
    payload = make_source_payload(
        points=np.asarray([[0.0, 0.0, 0.0], [2.0, 0.0, 0.0]], dtype=float),
        values=np.asarray([0.8, 4.0], dtype=float),
        label="cluster masked surface z",
        kind=SOURCE_KIND_SURFACE_MESH,
        source_model="l2_mne_fsaverage_participant_zscore_mean",
        value_label="source-space z-score",
        faces=np.asarray([[0, 1, 1]], dtype=np.int64),
        metadata={
            "source_value_unit": "z-score",
            "cluster_mask": "source_space_cluster_permutation",
            "cluster_mask_vertex_indices": [0],
        },
        normalize_values=False,
    )

    projection = project_cortical_surface_payload(
        payload.points,
        payload,
        neighbors=1,
        z_threshold=1.64,
        use_cluster_mask=False,
    )

    assert payload_has_cluster_mask(payload) is True
    assert np.isnan(projection.values[0])
    assert projection.values[1] == 4.0


def test_underpowered_empty_cluster_mask_falls_back_to_threshold_display() -> None:
    payload = make_source_payload(
        points=np.asarray([[0.0, 0.0, 0.0], [2.0, 0.0, 0.0]], dtype=float),
        values=np.asarray([0.8, 4.0], dtype=float),
        label="small sample surface z",
        kind=SOURCE_KIND_SURFACE_MESH,
        source_model="l2_mne_fsaverage_participant_zscore_mean",
        value_label="source-space z-score",
        faces=np.asarray([[0, 1, 1]], dtype=np.int64),
        metadata={
            "source_value_unit": "z-score",
            "cluster_mask": "source_space_cluster_permutation",
            "cluster_mask_vertex_indices": [],
            "cluster_mask_vertex_count": 0,
            "participant_count": 4,
            "cluster_permutation_count": 16,
            "cluster_alpha": 0.05,
        },
        normalize_values=False,
    )

    projection = project_cortical_surface_payload(payload.points, payload, neighbors=1, z_threshold=1.64)

    assert payload_cluster_mask_is_underpowered(payload) is True
    assert payload_cluster_mask_minimum_p(payload) == 1.0 / 17.0
    assert payload_has_cluster_mask(payload) is False
    assert payload_cluster_mask(payload) is None
    assert np.isnan(projection.values[0])
    assert projection.values[1] == 4.0


def test_empty_cluster_mask_falls_back_to_threshold_display() -> None:
    payload = make_source_payload(
        points=np.asarray([[0.0, 0.0, 0.0], [2.0, 0.0, 0.0]], dtype=float),
        values=np.asarray([2.4, 4.0], dtype=float),
        label="large sample empty mask surface z",
        kind=SOURCE_KIND_SURFACE_MESH,
        source_model="l2_mne_fsaverage_participant_zscore_mean",
        value_label="source-space z-score",
        faces=np.asarray([[0, 1, 1]], dtype=np.int64),
        metadata={
            "source_value_unit": "z-score",
            "cluster_mask": "source_space_cluster_permutation",
            "cluster_mask_vertex_indices": [],
            "cluster_mask_vertex_count": 0,
            "participant_count": 24,
            "cluster_permutation_count": 10000,
            "cluster_alpha": 0.05,
        },
        normalize_values=False,
    )

    projection = project_cortical_surface_payload(payload.points, payload, neighbors=1, z_threshold=1.64)

    assert payload_cluster_mask_is_empty(payload) is True
    assert payload_cluster_mask_is_underpowered(payload) is False
    assert payload_has_cluster_mask(payload) is True
    assert payload_cluster_mask(payload).tolist() == [False, False]
    assert projection.values.tolist() == [2.4, 4.0]


def test_cortical_paint_cluster_mask_keeps_negative_two_tailed_values() -> None:
    payload = make_source_payload(
        points=np.asarray([[0.0, 0.0, 0.0], [2.0, 0.0, 0.0]], dtype=float),
        values=np.asarray([-2.4, 3.1], dtype=float),
        label="two-tailed cluster masked surface z",
        kind=SOURCE_KIND_SURFACE_MESH,
        source_model="l2_mne_fsaverage_participant_zscore_mean",
        value_label="source-space z-score",
        faces=np.asarray([[0, 1, 1]], dtype=np.int64),
        metadata={
            "source_value_unit": "z-score",
            "cluster_mask": "source_space_cluster_permutation",
            "cluster_forming_tail": "two-sided",
            "cluster_mask_vertex_indices": [0, 1],
        },
        normalize_values=False,
    )

    projection = project_cortical_surface_payload(payload.points, payload, neighbors=1, z_threshold=1.64)

    assert projection.values.tolist() == [-2.4, 3.1]


def test_cortical_paint_detects_participant_first_surface_metadata() -> None:
    payload = make_source_payload(
        points=np.asarray([[0.0, 0.0, 0.0], [2.0, 0.0, 0.0]], dtype=float),
        values=np.asarray([1.2, 2.0], dtype=float),
        label="participant mean z",
        kind=SOURCE_KIND_SURFACE_MESH,
        source_model="l2_mne_fsaverage_participant_zscore_mean",
        value_label="source-space z-score",
        faces=np.asarray([[0, 1, 1]], dtype=np.int64),
        metadata={
            "source_value_unit": "z-score",
            "source_space": "fsaverage_surface",
            "base_producer_method": "l2_mne_fsaverage_participant_zscore",
        },
        normalize_values=False,
    )

    assert uses_cortical_surface_paint(payload) is True


def test_cortical_paint_rejects_non_l2_mne_volume_payloads() -> None:
    payload = make_source_payload(
        points=np.asarray([[0.0, 0.0, 0.0]], dtype=float),
        values=np.asarray([1.0], dtype=float),
        label="volume",
        kind=SOURCE_KIND_VOLUME_MESH,
        source_model="volume_grid",
        faces=np.asarray([[0, 0, 0]], dtype=np.int64),
        normalize_values=False,
    )

    assert uses_cortical_surface_paint(payload) is False
