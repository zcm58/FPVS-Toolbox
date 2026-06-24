from __future__ import annotations

import numpy as np
import pytest

from Tools.LORETA_Visualizer.source_payloads import (
    SOURCE_KIND_VOLUME_MESH,
    make_source_payload,
    source_payload_to_display,
)
from Tools.LORETA_Visualizer.synthetic_brain import make_synthetic_brain_mesh
from Tools.LORETA_Visualizer.transforms import (
    COORDINATE_SPACE_DISPLAY,
    COORDINATE_SPACE_FSAVERAGE,
    COORDINATE_SPACE_FSAVERAGE_VOLUME,
    MeshDisplayTransform,
)


def test_mesh_display_transform_round_trips_native_points() -> None:
    native_points = np.asarray(
        [
            [10.0, 0.0, 0.0],
            [12.0, 0.0, 0.0],
            [10.0, 4.0, 0.0],
            [10.0, 0.0, 8.0],
        ],
        dtype=float,
    )
    transform = MeshDisplayTransform.from_native_points(
        native_points,
        native_coordinate_space=COORDINATE_SPACE_FSAVERAGE,
    )

    display_points = transform.to_display_points(native_points)
    round_trip = transform.from_display_points(display_points)

    assert np.allclose(np.mean(display_points, axis=0), np.zeros(3))
    assert np.max(np.linalg.norm(display_points, axis=1)) == pytest.approx(1.0)
    assert np.allclose(round_trip, native_points)


def test_mesh_display_transform_accepts_already_display_points() -> None:
    mesh = make_synthetic_brain_mesh()
    display_points = mesh.display_transform.to_display_points(
        mesh.points,
        coordinate_space=COORDINATE_SPACE_DISPLAY,
    )

    assert np.allclose(display_points, mesh.points)


def test_mesh_display_transform_rejects_unmatched_coordinate_space() -> None:
    transform = MeshDisplayTransform.from_native_points(
        np.asarray([[0.0, 0.0, 0.0], [2.0, 0.0, 0.0]], dtype=float),
        native_coordinate_space=COORDINATE_SPACE_FSAVERAGE,
    )

    with pytest.raises(ValueError, match="Cannot transform"):
        transform.to_display_points(
            np.asarray([[0.0, 0.0, 0.0]], dtype=float),
            coordinate_space="subject_mri",
        )


def test_fsaverage_surface_transform_accepts_fsaverage_volume_points() -> None:
    surface_points = np.asarray(
        [
            [-60.0, -80.0, -35.0],
            [-55.0, 45.0, 55.0],
            [58.0, -78.0, -32.0],
            [56.0, 48.0, 52.0],
        ],
        dtype=float,
    )
    volume_points = np.asarray(
        [
            [-20.0, -62.0, 8.0],
            [0.0, -70.0, 12.0],
            [22.0, -61.0, 7.0],
        ],
        dtype=float,
    )
    transform = MeshDisplayTransform.from_native_points(
        surface_points,
        native_coordinate_space=COORDINATE_SPACE_FSAVERAGE,
    )

    display_points = transform.to_display_points(
        volume_points,
        coordinate_space=COORDINATE_SPACE_FSAVERAGE_VOLUME,
    )

    assert np.allclose(display_points, (volume_points - transform.center) / transform.radius)


def test_source_payload_to_display_preserves_values_and_faces() -> None:
    native_points = np.asarray(
        [
            [10.0, 0.0, 0.0],
            [12.0, 0.0, 0.0],
            [10.0, 4.0, 0.0],
            [10.0, 0.0, 8.0],
        ],
        dtype=float,
    )
    transform = MeshDisplayTransform.from_native_points(
        native_points,
        native_coordinate_space=COORDINATE_SPACE_FSAVERAGE,
    )
    faces = np.asarray([3, 0, 1, 2], dtype=np.int64)
    values = np.asarray([0.1, 0.2, 0.8, 1.0], dtype=float)
    native_payload = make_source_payload(
        points=native_points,
        values=values,
        label="native demo",
        kind=SOURCE_KIND_VOLUME_MESH,
        coordinate_space=COORDINATE_SPACE_FSAVERAGE,
        source_model="volume_grid",
        faces=faces,
        normalize_values=False,
    )

    display_payload = source_payload_to_display(native_payload, transform)

    assert display_payload.coordinate_space == COORDINATE_SPACE_DISPLAY
    assert np.allclose(display_payload.points, transform.to_display_points(native_points))
    assert np.allclose(display_payload.values, values)
    assert np.array_equal(display_payload.faces, faces)


def test_fsaverage_like_native_payload_maps_into_display_mesh_space() -> None:
    native_mesh_points = np.asarray(
        [
            [-60.0, -80.0, -35.0],
            [-55.0, 45.0, 55.0],
            [-10.0, -15.0, 75.0],
            [10.0, -20.0, -45.0],
            [58.0, -78.0, -32.0],
            [56.0, 48.0, 52.0],
        ],
        dtype=float,
    )
    transform = MeshDisplayTransform.from_native_points(
        native_mesh_points,
        native_coordinate_space=COORDINATE_SPACE_FSAVERAGE,
    )
    native_source_points = np.asarray(
        [
            [-20.0, -62.0, 8.0],
            [0.0, -70.0, 12.0],
            [22.0, -61.0, 7.0],
        ],
        dtype=float,
    )
    values = np.asarray([0.25, 0.75, 1.0], dtype=float)
    native_payload = make_source_payload(
        points=native_source_points,
        values=values,
        label="fsaverage native source payload",
        kind=SOURCE_KIND_VOLUME_MESH,
        coordinate_space=COORDINATE_SPACE_FSAVERAGE_VOLUME,
        source_model="volume_grid",
        faces=np.asarray([3, 0, 1, 2], dtype=np.int64),
        metadata={"source_space": "fsaverage_like_mm"},
        normalize_values=False,
    )

    display_payload = source_payload_to_display(native_payload, transform)
    expected_display_points = transform.to_display_points(
        native_source_points,
        coordinate_space=COORDINATE_SPACE_FSAVERAGE_VOLUME,
    )
    display_mesh_points = transform.to_display_points(native_mesh_points)

    assert display_payload.coordinate_space == COORDINATE_SPACE_DISPLAY
    assert np.allclose(display_payload.points, expected_display_points)
    assert np.allclose(transform.from_display_points(display_payload.points), native_source_points)
    assert np.max(np.abs(display_payload.points)) <= np.max(np.abs(display_mesh_points)) + 1e-9
    assert np.allclose(display_payload.values, values)
    assert display_payload.metadata == {"source_space": "fsaverage_like_mm"}
