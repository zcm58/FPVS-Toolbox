"""Synthetic activation payloads for visualizing LORETA layer behavior."""

from __future__ import annotations

import numpy as np

from Tools.LORETA_Visualizer.conditions import DemoLoretaCondition, default_condition
from Tools.LORETA_Visualizer.source_payloads import (
    COORDINATE_SPACE_DISPLAY,
    SOURCE_KIND_VOLUME_MESH,
    SourcePayload,
    empty_source_payload,
    make_source_payload,
    source_payload_to_display,
)
from Tools.LORETA_Visualizer.transforms import MeshDisplayTransform

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
    display_transform: MeshDisplayTransform | None = None,
) -> ActivationPayload:
    """Return deterministic condition-specific synthetic activation points.

    The payload is synthetic. It uses the current mesh coordinate space so it
    aligns with fsaverage-derived meshes when available. When a non-identity
    display transform is available, the synthetic payload is converted into the
    mesh native coordinate space and then back through the same helper path that
    future real source payloads will use.
    """
    points = np.asarray(mesh_points, dtype=float)
    if points.ndim != 2 or points.shape[1] != 3 or len(points) == 0:
        return empty_source_payload(label=f"Synthetic {condition.activation_region} demo activation")
    payload = _make_volume_region_activation(points, condition=condition)
    return _maybe_round_trip_through_native_space(payload, display_transform)


def _maybe_round_trip_through_native_space(
    payload: ActivationPayload,
    display_transform: MeshDisplayTransform | None,
) -> ActivationPayload:
    if display_transform is None:
        return payload
    if display_transform.native_coordinate_space == display_transform.display_coordinate_space:
        return payload

    native_payload = make_source_payload(
        points=display_transform.from_display_points(payload.points),
        values=payload.values,
        label=payload.label,
        kind=payload.kind,
        coordinate_space=display_transform.native_coordinate_space,
        source_model=payload.source_model,
        value_label=payload.value_label,
        faces=payload.faces,
        metadata={
            **payload.metadata,
            "transform_simulation": True,
            "native_coordinate_space": display_transform.native_coordinate_space,
            "display_coordinate_space": display_transform.display_coordinate_space,
        },
        normalize_values=False,
    )
    return source_payload_to_display(native_payload, display_transform)


def _make_volume_region_activation(
    points: np.ndarray,
    *,
    condition: DemoLoretaCondition,
) -> ActivationPayload:
    """Return deterministic internal volume-source demo mesh blobs."""
    bounds_min = np.min(points, axis=0)
    bounds_max = np.max(points, axis=0)
    span = np.maximum(bounds_max - bounds_min, 1e-6)
    centers = _volume_centers(bounds_min, bounds_max, region=condition.activation_region)
    radii = _volume_radii(span, region=condition.activation_region)
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
        label=f"Synthetic {condition.activation_region} demo activation",
        kind=SOURCE_KIND_VOLUME_MESH,
        coordinate_space=COORDINATE_SPACE_DISPLAY,
        source_model=condition.source_model,
        faces=_faces_to_vtk(active_faces),
        metadata={
            "condition_id": condition.condition_id,
            "synthetic": True,
            "visual_goal": "deep_source_rendering",
            "volume_region": condition.activation_region,
        },
        normalize_values=False,
    )


def _volume_centers(
    bounds_min: np.ndarray,
    bounds_max: np.ndarray,
    *,
    region: str,
) -> tuple[tuple[np.ndarray, float], ...]:
    span = np.maximum(bounds_max - bounds_min, 1e-6)
    center = (bounds_min + bounds_max) / 2.0
    if region == "frontal":
        y = bounds_max[1] - span[1] * 0.20
        z = center[2] + span[2] * 0.03
        return (
            (np.asarray((center[0] - span[0] * 0.14, y, z), dtype=float), 1.00),
            (np.asarray((center[0] + span[0] * 0.14, y, z), dtype=float), 0.90),
            (np.asarray((center[0], y - span[1] * 0.06, z + span[2] * 0.05), dtype=float), 0.72),
        )
    if region == "deep_medial_temporal":
        return (
            (
                np.asarray((center[0] - span[0] * 0.15, center[1] - span[1] * 0.06, center[2] - span[2] * 0.10)),
                1.00,
            ),
            (
                np.asarray((center[0] + span[0] * 0.15, center[1] - span[1] * 0.06, center[2] - span[2] * 0.10)),
                0.94,
            ),
        )
    y = bounds_min[1] + span[1] * 0.22
    z = center[2] - span[2] * 0.02
    return (
        (np.asarray((center[0] - span[0] * 0.18, y, z), dtype=float), 1.00),
        (np.asarray((center[0] + span[0] * 0.18, y, z), dtype=float), 0.92),
        (np.asarray((center[0], y + span[1] * 0.05, z - span[2] * 0.04), dtype=float), 0.70),
    )


def _volume_radii(span: np.ndarray, *, region: str) -> np.ndarray:
    if region == "deep_medial_temporal":
        return np.asarray((span[0] * 0.055, span[1] * 0.090, span[2] * 0.060), dtype=float)
    if region == "frontal":
        return np.asarray((span[0] * 0.090, span[1] * 0.080, span[2] * 0.085), dtype=float)
    return np.asarray((span[0] * 0.105, span[1] * 0.085, span[2] * 0.090), dtype=float)


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


def _faces_to_vtk(faces: np.ndarray) -> np.ndarray:
    counts = np.full((len(faces), 1), 3, dtype=np.int64)
    return np.hstack((counts, faces.astype(np.int64))).reshape(-1)
