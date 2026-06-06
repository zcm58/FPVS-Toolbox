from __future__ import annotations

import numpy as np

from Tools.LORETA_Visualizer.conditions import condition_by_id
from Tools.LORETA_Visualizer.dummy_activation import make_demo_condition_activation
from Tools.LORETA_Visualizer.scalar_fields import LORETA_SCALAR_COLORS, resolve_scalar_limits
from Tools.LORETA_Visualizer.source_payloads import SOURCE_KIND_VOLUME_MESH, make_source_payload
from Tools.LORETA_Visualizer.synthetic_brain import make_synthetic_brain_mesh
from Tools.LORETA_Visualizer.transforms import (
    COORDINATE_SPACE_DISPLAY,
    COORDINATE_SPACE_FSAVERAGE,
    MeshDisplayTransform,
)


def test_demo_conditions_place_volume_activation_in_distinct_regions() -> None:
    mesh = make_synthetic_brain_mesh()
    occipital = make_demo_condition_activation(mesh.points, mesh_faces=mesh.faces, condition=condition_by_id("occipital"))
    frontal = make_demo_condition_activation(mesh.points, mesh_faces=mesh.faces, condition=condition_by_id("frontal"))

    assert len(occipital.points) > 0
    assert len(frontal.points) > 0
    assert occipital.kind == SOURCE_KIND_VOLUME_MESH
    assert frontal.kind == SOURCE_KIND_VOLUME_MESH
    assert occipital.source_model == "volume_grid"
    assert frontal.source_model == "volume_grid"
    assert occipital.faces is not None
    assert frontal.faces is not None
    assert len(occipital.faces) > 0
    assert len(frontal.faces) > 0
    assert float(np.min(occipital.values)) > 0.0
    assert float(np.max(occipital.values)) <= 1.0
    assert float(np.mean(occipital.points[:, 1])) < 0.0
    assert float(np.mean(frontal.points[:, 1])) > 0.0
    assert float(np.mean(frontal.points[:, 1])) > float(np.mean(occipital.points[:, 1]))


def test_deep_demo_condition_uses_internal_volume_mesh() -> None:
    mesh = make_synthetic_brain_mesh()
    deep = make_demo_condition_activation(mesh.points, condition=condition_by_id("deep_medial_temporal"))

    shell_radius = np.linalg.norm(mesh.points, axis=1)
    deep_radius = np.linalg.norm(deep.points, axis=1)

    assert deep.kind == SOURCE_KIND_VOLUME_MESH
    assert deep.source_model == "volume_grid"
    assert len(deep.points) > 0
    assert deep.faces is not None
    assert len(deep.faces) > 0
    assert float(np.min(deep.values)) < 0.25
    assert float(np.max(deep.values)) > 0.9
    assert float(np.mean(deep_radius)) < float(np.percentile(shell_radius, 50))


def test_source_payload_normalizes_and_filters_values() -> None:
    payload = make_source_payload(
        points=np.asarray(
            [
                [0.0, 0.0, 0.0],
                [1.0, 0.0, 0.0],
                [float("nan"), 0.0, 0.0],
            ]
        ),
        values=np.asarray([2.0, 4.0, 9.0]),
        label="demo",
        source_model="volume_grid",
    )

    assert payload.points.shape == (2, 3)
    assert payload.values.tolist() == [0.0, 1.0]


def test_scalar_gradient_limits_follow_scalp_map_style_bounds() -> None:
    assert LORETA_SCALAR_COLORS[-1] == "#b2182b"
    assert resolve_scalar_limits(np.asarray([0.2, 0.8]), auto_scale=True) == (0.0, 0.8)
    assert resolve_scalar_limits(np.asarray([-0.4, 0.8]), auto_scale=True) == (-0.4, 0.8)
    assert resolve_scalar_limits(np.asarray([0.2]), auto_scale=False, manual_min=1.0, manual_max=1.0) == (1.0, 2.0)


def test_demo_condition_can_exercise_native_to_display_bridge() -> None:
    native_mesh_points = np.asarray(
        [
            [-35.0, -70.0, -20.0],
            [-35.0, 40.0, 40.0],
            [35.0, -70.0, -18.0],
            [35.0, 42.0, 38.0],
            [0.0, -20.0, 72.0],
            [0.0, -15.0, -45.0],
        ],
        dtype=float,
    )
    transform = MeshDisplayTransform.from_native_points(
        native_mesh_points,
        native_coordinate_space=COORDINATE_SPACE_FSAVERAGE,
    )
    display_mesh_points = transform.to_display_points(native_mesh_points)

    direct_payload = make_demo_condition_activation(
        display_mesh_points,
        condition=condition_by_id("occipital"),
    )
    bridged_payload = make_demo_condition_activation(
        display_mesh_points,
        condition=condition_by_id("occipital"),
        display_transform=transform,
    )

    assert bridged_payload.coordinate_space == COORDINATE_SPACE_DISPLAY
    assert bridged_payload.metadata["transform_simulation"] is True
    assert bridged_payload.metadata["native_coordinate_space"] == COORDINATE_SPACE_FSAVERAGE
    assert np.allclose(bridged_payload.points, direct_payload.points)
    assert np.allclose(bridged_payload.values, direct_payload.values)
    assert np.array_equal(bridged_payload.faces, direct_payload.faces)


def test_prepared_source_fixture_condition_has_real_data_handoff_shape() -> None:
    mesh = make_synthetic_brain_mesh()
    payload = make_demo_condition_activation(
        mesh.points,
        condition=condition_by_id("prepared_source_fixture"),
        display_transform=mesh.display_transform,
    )

    assert payload.kind == SOURCE_KIND_VOLUME_MESH
    assert payload.source_model == "prepared_fsaverage_volume_fixture"
    assert payload.coordinate_space == COORDINATE_SPACE_DISPLAY
    assert payload.faces is not None
    assert len(payload.faces) > 0
    assert len(payload.points) == len(payload.values)
    assert payload.metadata["fixture_kind"] == "prepared_source_map"
    assert payload.metadata["source_file_format"] == "in_memory_fixture"
    assert payload.metadata["source_lobes"] == 4
    assert float(np.min(payload.values)) < 0.1
    assert float(np.max(payload.values)) > 0.9
    assert len(np.unique(np.round(payload.values, decimals=3))) > 30


def test_prepared_source_fixture_uses_fsaverage_like_transform_bridge() -> None:
    native_mesh_points = np.asarray(
        [
            [-65.0, -85.0, -40.0],
            [-62.0, 48.0, 52.0],
            [62.0, -82.0, -38.0],
            [65.0, 50.0, 50.0],
            [0.0, -18.0, 76.0],
            [0.0, -22.0, -52.0],
        ],
        dtype=float,
    )
    transform = MeshDisplayTransform.from_native_points(
        native_mesh_points,
        native_coordinate_space=COORDINATE_SPACE_FSAVERAGE,
    )
    display_mesh_points = transform.to_display_points(native_mesh_points)

    direct_payload = make_demo_condition_activation(
        display_mesh_points,
        condition=condition_by_id("prepared_source_fixture"),
    )
    bridged_payload = make_demo_condition_activation(
        display_mesh_points,
        condition=condition_by_id("prepared_source_fixture"),
        display_transform=transform,
    )

    assert bridged_payload.coordinate_space == COORDINATE_SPACE_DISPLAY
    assert bridged_payload.metadata["source_space"] == COORDINATE_SPACE_FSAVERAGE
    assert bridged_payload.metadata["adapted_through"] == "source_payload_to_display"
    assert np.allclose(bridged_payload.points, direct_payload.points)
    assert np.allclose(bridged_payload.values, direct_payload.values)
    assert np.array_equal(bridged_payload.faces, direct_payload.faces)
