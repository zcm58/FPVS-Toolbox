"""Synthetic geometry for validating the LORETA visualizer rendering path."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from Tools.LORETA_Visualizer.transforms import MeshDisplayTransform


@dataclass(frozen=True)
class BrainHemisphereMesh:
    """One hemisphere surface in renderer display coordinates."""

    points: np.ndarray
    faces: np.ndarray
    projection_points: np.ndarray | None = None
    shade_values: np.ndarray | None = None
    shade_source: str | None = None
    surface: str = "pial"


@dataclass(frozen=True)
class BrainMesh:
    """Triangle mesh payload consumed by the rendering adapter."""

    points: np.ndarray
    faces: np.ndarray
    display_transform: MeshDisplayTransform = field(default_factory=MeshDisplayTransform.identity)
    left_hemisphere: BrainHemisphereMesh | None = None
    right_hemisphere: BrainHemisphereMesh | None = None


def make_synthetic_brain_mesh(
    *,
    lat_steps: int = 42,
    lon_steps: int = 84,
) -> BrainMesh:
    """Return a deterministic brain-like ellipsoid mesh for Phase 1 validation."""
    theta_values = np.linspace(0.0, np.pi, lat_steps + 1)
    phi_values = np.linspace(0.0, 2.0 * np.pi, lon_steps, endpoint=False)

    points: list[tuple[float, float, float]] = []
    for theta in theta_values:
        sin_theta = np.sin(theta)
        cos_theta = np.cos(theta)
        for phi in phi_values:
            sin_phi = np.sin(phi)
            cos_phi = np.cos(phi)

            ripple = 1.0 + 0.035 * np.sin(9.0 * phi + 2.5 * theta) * sin_theta
            ripple += 0.020 * np.sin(15.0 * phi - 1.5 * theta) * sin_theta * sin_theta

            x = 0.82 * sin_theta * cos_phi * ripple
            y = 1.05 * cos_theta
            z = 0.62 * sin_theta * sin_phi * ripple

            midline_indent = 0.08 * np.exp(-((x / 0.11) ** 2)) * sin_theta
            z -= np.sign(z) * midline_indent
            points.append((float(x), float(y), float(z)))

    faces: list[int] = []
    for row in range(lat_steps):
        row_start = row * lon_steps
        next_row_start = (row + 1) * lon_steps
        for col in range(lon_steps):
            next_col = (col + 1) % lon_steps
            a = row_start + col
            b = row_start + next_col
            c = next_row_start + col
            d = next_row_start + next_col
            faces.extend((3, a, c, b))
            faces.extend((3, b, c, d))

    mesh_points = np.asarray(points, dtype=float)
    mesh_faces = np.asarray(faces, dtype=np.int64)
    left_hemisphere, right_hemisphere = _split_synthetic_hemispheres(mesh_points, mesh_faces)
    return BrainMesh(
        points=mesh_points,
        faces=mesh_faces,
        left_hemisphere=left_hemisphere,
        right_hemisphere=right_hemisphere,
    )


def _split_synthetic_hemispheres(
    points: np.ndarray,
    vtk_faces: np.ndarray,
) -> tuple[BrainHemisphereMesh | None, BrainHemisphereMesh | None]:
    faces = np.asarray(vtk_faces, dtype=np.int64).reshape(-1, 4)
    if len(points) == 0 or len(faces) == 0 or not np.all(faces[:, 0] == 3):
        return None, None
    triangles = faces[:, 1:4]
    centroids = np.mean(points[triangles], axis=1)
    left = _hemisphere_from_triangles(points, triangles[centroids[:, 0] <= 0.0])
    right = _hemisphere_from_triangles(points, triangles[centroids[:, 0] > 0.0])
    return left, right


def _hemisphere_from_triangles(points: np.ndarray, triangles: np.ndarray) -> BrainHemisphereMesh | None:
    if len(triangles) == 0:
        return None
    used = np.unique(triangles.reshape(-1))
    remap = np.full(len(points), -1, dtype=np.int64)
    remap[used] = np.arange(len(used), dtype=np.int64)
    remapped_triangles = remap[triangles]
    if np.any(remapped_triangles < 0):
        return None
    counts = np.full((len(remapped_triangles), 1), 3, dtype=np.int64)
    faces = np.hstack((counts, remapped_triangles.astype(np.int64))).reshape(-1)
    hemisphere_points = points[used].astype(float)
    return BrainHemisphereMesh(
        points=hemisphere_points,
        faces=faces,
        projection_points=hemisphere_points,
        shade_values=_synthetic_shade_values(hemisphere_points),
        shade_source="synthetic_geometry",
    )


def _synthetic_shade_values(points: np.ndarray) -> np.ndarray:
    centered = np.asarray(points, dtype=float) - np.mean(points, axis=0)
    depth = centered[:, 1] + 0.45 * centered[:, 2]
    minimum = float(np.min(depth))
    maximum = float(np.max(depth))
    if maximum <= minimum:
        return np.full(len(points), 0.55, dtype=float)
    return np.clip((depth - minimum) / (maximum - minimum), 0.0, 1.0)
