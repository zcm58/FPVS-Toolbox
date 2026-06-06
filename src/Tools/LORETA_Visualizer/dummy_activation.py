"""Synthetic activation payloads for visualizing LORETA layer behavior."""

from __future__ import annotations

import numpy as np

from Tools.LORETA_Visualizer.conditions import DemoLoretaCondition, default_condition
from Tools.LORETA_Visualizer.source_payloads import (
    COORDINATE_SPACE_DISPLAY,
    SOURCE_KIND_SURFACE_MESH,
    SOURCE_KIND_SURFACE_POINTS,
    SOURCE_KIND_VOLUME_MESH,
    SourcePayload,
    empty_source_payload,
    make_source_payload,
)

ActivationPayload = SourcePayload


def make_occipital_demo_activation(
    mesh_points: np.ndarray,
    *,
    max_points: int = 900,
) -> ActivationPayload:
    """Return deterministic posterior/occipital demo activation points."""
    return make_demo_condition_activation(mesh_points, condition=default_condition(), max_points=max_points)


def make_demo_condition_activation(
    mesh_points: np.ndarray,
    *,
    mesh_faces: np.ndarray | None = None,
    condition: DemoLoretaCondition,
    max_points: int = 900,
) -> ActivationPayload:
    """Return deterministic condition-specific synthetic activation points.

    The payload is synthetic. It uses the current mesh coordinate space so it
    aligns with fsaverage-derived meshes when available.
    """
    points = np.asarray(mesh_points, dtype=float)
    if points.ndim != 2 or points.shape[1] != 3 or len(points) == 0:
        return empty_source_payload(label=f"Synthetic {condition.activation_region} demo activation")
    if condition.activation_region == "deep_medial_temporal":
        return _make_deep_medial_temporal_activation(points, condition=condition, max_points=max_points)

    return _make_surface_region_activation(points, mesh_faces=mesh_faces, condition=condition, max_points=max_points)


def _make_surface_region_activation(
    points: np.ndarray,
    *,
    mesh_faces: np.ndarray | None,
    condition: DemoLoretaCondition,
    max_points: int,
) -> ActivationPayload:
    """Return deterministic cortical-surface demo activation points."""

    axis = 1
    axis_min = float(np.min(points[:, axis]))
    axis_max = float(np.max(points[:, axis]))
    axis_span = max(axis_max - axis_min, 1e-6)
    region_points = _region_points(points, region=condition.activation_region, axis=axis, axis_span=axis_span)
    if len(region_points) == 0:
        region_points = points

    centers = _condition_centers(region_points, region=condition.activation_region)
    values = np.zeros(len(points), dtype=float)
    sigma = axis_span * 0.18
    for center, weight in centers:
        distances = np.linalg.norm(points - center, axis=1)
        values = np.maximum(values, weight * np.exp(-((distances / sigma) ** 2)))

    values *= _region_weight(points, region=condition.activation_region, axis=axis, axis_span=axis_span)

    active = values > 0.08
    if not np.any(active):
        active = values > np.percentile(values, 90)

    if mesh_faces is not None:
        surface_payload = _surface_mesh_payload(
            points,
            values,
            active,
            mesh_faces=mesh_faces,
            condition=condition,
            max_points=max_points,
        )
        if surface_payload is not None:
            return surface_payload

    active_points = points[active]
    active_values = values[active]

    if len(active_points) > max_points:
        order = np.argsort(active_values)[-max_points:]
        active_points = active_points[order]
        active_values = active_values[order]

    return make_source_payload(
        points=active_points,
        values=active_values,
        label=f"Synthetic {condition.activation_region} demo activation",
        kind=SOURCE_KIND_SURFACE_POINTS,
        coordinate_space=COORDINATE_SPACE_DISPLAY,
        source_model=condition.source_model,
        metadata={
            "condition_id": condition.condition_id,
            "synthetic": True,
        },
        normalize_values=False,
    )


def _surface_mesh_payload(
    points: np.ndarray,
    values: np.ndarray,
    active: np.ndarray,
    *,
    mesh_faces: np.ndarray,
    condition: DemoLoretaCondition,
    max_points: int,
) -> ActivationPayload | None:
    triangles = _triangles_from_vtk_faces(mesh_faces)
    if triangles is None or len(triangles) == 0:
        return None

    active_vertices = np.asarray(active, dtype=bool)
    if int(np.count_nonzero(active_vertices)) > max_points:
        cutoff_index = max(len(values) - max_points, 0)
        cutoff = float(np.partition(values, cutoff_index)[cutoff_index])
        active_vertices = values >= cutoff

    active_faces = np.all(active_vertices[triangles], axis=1)
    if not np.any(active_faces):
        active_faces = np.any(active_vertices[triangles], axis=1)
    selected_triangles = triangles[active_faces]
    if len(selected_triangles) == 0:
        return None

    used_vertices = np.unique(selected_triangles.reshape(-1))
    remap = np.full(len(points), -1, dtype=np.int64)
    remap[used_vertices] = np.arange(len(used_vertices), dtype=np.int64)
    remapped_triangles = remap[selected_triangles]
    return make_source_payload(
        points=points[used_vertices],
        values=values[used_vertices],
        label=f"Synthetic {condition.activation_region} demo activation",
        kind=SOURCE_KIND_SURFACE_MESH,
        coordinate_space=COORDINATE_SPACE_DISPLAY,
        source_model=condition.source_model,
        faces=_faces_to_vtk(remapped_triangles),
        metadata={
            "condition_id": condition.condition_id,
            "synthetic": True,
            "surface_patch": True,
        },
        normalize_values=False,
    )


def _make_deep_medial_temporal_activation(
    points: np.ndarray,
    *,
    condition: DemoLoretaCondition,
    max_points: int,
) -> ActivationPayload:
    """Return deterministic internal volume-source demo mesh blobs."""
    bounds_min = np.min(points, axis=0)
    bounds_max = np.max(points, axis=0)
    span = np.maximum(bounds_max - bounds_min, 1e-6)
    center = (bounds_min + bounds_max) / 2.0
    centers = (
        (np.asarray((center[0] - span[0] * 0.15, center[1] - span[1] * 0.06, center[2] - span[2] * 0.10)), 1.00),
        (np.asarray((center[0] + span[0] * 0.15, center[1] - span[1] * 0.06, center[2] - span[2] * 0.10)), 0.94),
    )
    radii = np.asarray((span[0] * 0.055, span[1] * 0.090, span[2] * 0.060), dtype=float)
    mesh_points: list[np.ndarray] = []
    mesh_values: list[float] = []
    mesh_faces: list[np.ndarray] = []
    for blob_center, weight in centers:
        blob_points, blob_values, blob_faces = _ellipsoid_blob_mesh(blob_center, radii, weight=weight)
        offset = len(mesh_points)
        mesh_points.extend(blob_points)
        mesh_values.extend(blob_values)
        mesh_faces.append(blob_faces + offset)

    active_points = np.asarray(mesh_points, dtype=float)
    active_values = np.asarray(mesh_values, dtype=float)
    active_faces = np.vstack(mesh_faces) if mesh_faces else np.empty((0, 3), dtype=np.int64)

    return make_source_payload(
        points=active_points,
        values=active_values,
        label="Synthetic deep medial temporal demo activation",
        kind=SOURCE_KIND_VOLUME_MESH,
        coordinate_space=COORDINATE_SPACE_DISPLAY,
        source_model=condition.source_model,
        faces=_faces_to_vtk(active_faces),
        metadata={
            "condition_id": condition.condition_id,
            "synthetic": True,
            "visual_goal": "deep_source_rendering",
        },
        normalize_values=False,
    )


def _ellipsoid_blob_mesh(
    center: np.ndarray,
    radii: np.ndarray,
    *,
    weight: float,
    lat_steps: int = 14,
    lon_steps: int = 28,
) -> tuple[list[np.ndarray], list[float], np.ndarray]:
    blob_points: list[np.ndarray] = []
    blob_values: list[float] = []
    theta_values = np.linspace(0.0, np.pi, lat_steps + 1)
    phi_values = np.linspace(0.0, 2.0 * np.pi, lon_steps, endpoint=False)
    for theta in theta_values:
        sin_theta = np.sin(theta)
        cos_theta = np.cos(theta)
        for phi in phi_values:
            sin_phi = np.sin(phi)
            cos_phi = np.cos(phi)
            ripple = 1.0 + 0.08 * np.sin(2.0 * phi + theta) * sin_theta
            offset = np.asarray(
                (
                    sin_theta * cos_phi,
                    cos_theta,
                    sin_theta * sin_phi,
                ),
                dtype=float,
            )
            point = center + offset * radii * ripple
            blob_points.append(point)
            angular_hotspot = 0.55 + 0.45 * np.cos(phi - np.pi / 5.0)
            scalar = weight * (0.18 + 0.82 * sin_theta * angular_hotspot)
            blob_values.append(float(np.clip(scalar, 0.0, 1.0)))

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

    return blob_points, blob_values, np.asarray(faces, dtype=np.int64)


def _region_points(points: np.ndarray, *, region: str, axis: int, axis_span: float) -> np.ndarray:
    axis_values = points[:, axis]
    if region == "frontal":
        cutoff = float(np.max(axis_values) - axis_span * 0.34)
        return points[axis_values >= cutoff]
    cutoff = float(np.min(axis_values) + axis_span * 0.34)
    return points[axis_values <= cutoff]


def _region_weight(points: np.ndarray, *, region: str, axis: int, axis_span: float) -> np.ndarray:
    axis_values = points[:, axis]
    if region == "frontal":
        cutoff = float(np.max(axis_values) - axis_span * 0.34)
        return np.clip((axis_values - cutoff) / (axis_span * 0.22), 0.0, 1.0)
    cutoff = float(np.min(axis_values) + axis_span * 0.34)
    return np.clip((cutoff - axis_values) / (axis_span * 0.22), 0.0, 1.0)


def _triangles_from_vtk_faces(mesh_faces: np.ndarray) -> np.ndarray | None:
    faces = np.asarray(mesh_faces, dtype=np.int64)
    if faces.ndim != 1 or len(faces) % 4 != 0:
        return None
    faces = faces.reshape(-1, 4)
    if not np.all(faces[:, 0] == 3):
        return None
    return faces[:, 1:4]


def _faces_to_vtk(faces: np.ndarray) -> np.ndarray:
    counts = np.full((len(faces), 1), 3, dtype=np.int64)
    return np.hstack((counts, faces.astype(np.int64))).reshape(-1)


def _condition_centers(points: np.ndarray, *, region: str) -> tuple[tuple[np.ndarray, float], ...]:
    left = _nearest_point(points, target_x=-0.32, region=region)
    right = _nearest_point(points, target_x=0.32, region=region)
    mid = _nearest_point(points, target_x=0.0, region=region)
    return (
        (left, 1.00),
        (right, 0.92),
        (mid, 0.68),
    )


def _nearest_point(points: np.ndarray, *, target_x: float, region: str) -> np.ndarray:
    y = points[:, 1]
    z = points[:, 2]
    y_span = np.max(y) - np.min(y)
    if region == "frontal":
        target_y = float(np.max(y) - y_span * 0.18)
        target_z = float(np.median(z) + (np.max(z) - np.min(z)) * 0.06)
    else:
        target_y = float(np.min(y) + y_span * 0.18)
        target_z = float(np.median(z))
    target = np.asarray((target_x, target_y, target_z), dtype=float)
    distances = np.linalg.norm(points - target, axis=1)
    return points[int(np.argmin(distances))]
