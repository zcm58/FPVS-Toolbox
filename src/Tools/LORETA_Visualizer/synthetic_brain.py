"""Synthetic geometry for validating the LORETA visualizer rendering path."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from Tools.LORETA_Visualizer.transforms import MeshDisplayTransform


@dataclass(frozen=True)
class BrainMesh:
    """Triangle mesh payload consumed by the rendering adapter."""

    points: np.ndarray
    faces: np.ndarray
    display_transform: MeshDisplayTransform = field(default_factory=MeshDisplayTransform.identity)


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

    return BrainMesh(
        points=np.asarray(points, dtype=float),
        faces=np.asarray(faces, dtype=np.int64),
    )
