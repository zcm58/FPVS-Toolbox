"""Prepared source-map fixture for validating real-data adapter behavior.

This module intentionally simulates already-computed source-localization output.
It does not calculate inverse solutions or source estimates.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from Tools.LORETA_Visualizer.source_payloads import (
    COORDINATE_SPACE_DISPLAY,
    SOURCE_KIND_VOLUME_MESH,
    SourcePayload,
    make_source_payload,
    source_payload_to_display,
)
from Tools.LORETA_Visualizer.transforms import MeshDisplayTransform


@dataclass(frozen=True)
class PreparedSourceFixture:
    """Already-prepared fixture data shaped like a future source-map handoff."""

    points: np.ndarray
    values: np.ndarray
    faces: np.ndarray
    coordinate_space: str
    source_model: str
    label: str
    metadata: dict[str, object]


def make_prepared_source_fixture_payload(
    mesh_points: np.ndarray,
    *,
    condition_id: str,
    label: str,
    source_model: str,
    display_transform: MeshDisplayTransform | None,
) -> SourcePayload:
    """Return a display-space payload adapted from prepared fixture data."""
    display_points = _validate_mesh_points(mesh_points)
    fixture = _make_prepared_fixture(
        display_points,
        condition_id=condition_id,
        label=label,
        source_model=source_model,
        display_transform=display_transform,
    )
    native_payload = make_source_payload(
        points=fixture.points,
        values=fixture.values,
        label=fixture.label,
        kind=SOURCE_KIND_VOLUME_MESH,
        coordinate_space=fixture.coordinate_space,
        source_model=fixture.source_model,
        value_label="prepared activation",
        faces=fixture.faces,
        metadata=fixture.metadata,
        normalize_values=False,
    )
    if display_transform is None:
        return native_payload
    return source_payload_to_display(native_payload, display_transform)


def _make_prepared_fixture(
    display_mesh_points: np.ndarray,
    *,
    condition_id: str,
    label: str,
    source_model: str,
    display_transform: MeshDisplayTransform | None,
) -> PreparedSourceFixture:
    display_points, values, faces = _make_display_source_field(display_mesh_points)
    coordinate_space = COORDINATE_SPACE_DISPLAY
    fixture_points = display_points
    metadata: dict[str, object] = {
        "condition_id": condition_id,
        "synthetic": True,
        "fixture_kind": "prepared_source_map",
        "visual_goal": "real_data_adapter_shape",
        "source_file_format": "in_memory_fixture",
        "source_space": COORDINATE_SPACE_DISPLAY,
        "source_lobes": 4,
    }
    if display_transform is not None and display_transform.native_coordinate_space != display_transform.display_coordinate_space:
        fixture_points = display_transform.from_display_points(display_points)
        coordinate_space = display_transform.native_coordinate_space
        metadata.update(
            {
                "source_space": display_transform.native_coordinate_space,
                "adapted_through": "source_payload_to_display",
                "display_coordinate_space": display_transform.display_coordinate_space,
            }
        )
    return PreparedSourceFixture(
        points=fixture_points,
        values=values,
        faces=faces,
        coordinate_space=coordinate_space,
        source_model=source_model,
        label=label,
        metadata=metadata,
    )


def _make_display_source_field(display_mesh_points: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    bounds_min = np.min(display_mesh_points, axis=0)
    bounds_max = np.max(display_mesh_points, axis=0)
    span = np.maximum(bounds_max - bounds_min, 1e-6)
    center = (bounds_min + bounds_max) / 2.0
    lobe_specs = (
        (
            np.asarray((center[0] + span[0] * 0.18, bounds_min[1] + span[1] * 0.20, center[2] + span[2] * 0.02)),
            np.asarray((span[0] * 0.105, span[1] * 0.110, span[2] * 0.085)),
            1.00,
            0.4,
        ),
        (
            np.asarray((center[0] - span[0] * 0.16, bounds_min[1] + span[1] * 0.24, center[2] - span[2] * 0.02)),
            np.asarray((span[0] * 0.092, span[1] * 0.095, span[2] * 0.078)),
            0.82,
            1.6,
        ),
        (
            np.asarray((center[0] + span[0] * 0.03, center[1] - span[1] * 0.08, center[2] - span[2] * 0.12)),
            np.asarray((span[0] * 0.070, span[1] * 0.085, span[2] * 0.065)),
            0.54,
            2.4,
        ),
        (
            np.asarray((center[0] - span[0] * 0.09, bounds_max[1] - span[1] * 0.24, center[2] + span[2] * 0.08)),
            np.asarray((span[0] * 0.055, span[1] * 0.060, span[2] * 0.052)),
            0.36,
            3.1,
        ),
    )

    all_points: list[np.ndarray] = []
    all_values: list[float] = []
    all_faces: list[np.ndarray] = []
    for lobe_center, radii, weight, phase in lobe_specs:
        lobe_points, lobe_values, lobe_faces = _ellipsoid_lobe_mesh(
            lobe_center,
            radii,
            weight=weight,
            phase=phase,
        )
        offset = len(all_points)
        all_points.extend(lobe_points)
        all_values.extend(lobe_values)
        all_faces.append(lobe_faces + offset)

    points = np.asarray(all_points, dtype=float)
    values = np.asarray(all_values, dtype=float)
    faces = np.vstack(all_faces) if all_faces else np.empty((0, 3), dtype=np.int64)
    return points, values, _faces_to_vtk(faces)


def _ellipsoid_lobe_mesh(
    center: np.ndarray,
    radii: np.ndarray,
    *,
    weight: float,
    phase: float,
    lat_steps: int = 16,
    lon_steps: int = 32,
) -> tuple[list[np.ndarray], list[float], np.ndarray]:
    points: list[np.ndarray] = []
    values: list[float] = []
    theta_values = np.linspace(0.0, np.pi, lat_steps + 1)
    phi_values = np.linspace(0.0, 2.0 * np.pi, lon_steps, endpoint=False)
    for theta in theta_values:
        sin_theta = np.sin(theta)
        cos_theta = np.cos(theta)
        for phi in phi_values:
            ripple = 1.0 + 0.05 * np.sin(3.0 * phi + phase) * sin_theta
            offset = np.asarray(
                (
                    sin_theta * np.cos(phi),
                    cos_theta,
                    sin_theta * np.sin(phi),
                ),
                dtype=float,
            )
            point = center + offset * radii * ripple
            angular_hotspot = 0.5 + 0.5 * np.cos(phi - phase)
            vertical_taper = 0.35 + 0.65 * sin_theta
            scalar = weight * (0.14 + 0.86 * angular_hotspot * vertical_taper)
            points.append(point)
            values.append(float(np.clip(scalar, 0.0, 1.0)))

    faces: list[tuple[int, int, int]] = []
    for row in range(lat_steps):
        row_start = row * lon_steps
        next_row_start = (row + 1) * lon_steps
        for col in range(lon_steps):
            next_col = (col + 1) % lon_steps
            a = row_start + col
            b = row_start + next_col
            c = next_row_start + col
            d = next_row_start + next_col
            faces.append((a, c, b))
            faces.append((b, c, d))
    return points, values, np.asarray(faces, dtype=np.int64)


def _faces_to_vtk(faces: np.ndarray) -> np.ndarray:
    counts = np.full((len(faces), 1), 3, dtype=np.int64)
    return np.hstack((counts, faces.astype(np.int64))).reshape(-1)


def _validate_mesh_points(mesh_points: np.ndarray) -> np.ndarray:
    points = np.asarray(mesh_points, dtype=float)
    if points.ndim != 2 or points.shape[1] != 3 or len(points) == 0:
        raise ValueError("Prepared source fixture requires a non-empty N x 3 mesh point array.")
    if not np.all(np.isfinite(points)):
        raise ValueError("Prepared source fixture requires finite mesh points.")
    return points
