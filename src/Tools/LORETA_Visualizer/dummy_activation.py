"""Synthetic activation payloads for visualizing LORETA layer behavior."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class ActivationPayload:
    """Prepared activation points and scalar values in renderer coordinates."""

    points: np.ndarray
    values: np.ndarray
    label: str


def make_occipital_demo_activation(
    mesh_points: np.ndarray,
    *,
    max_points: int = 900,
) -> ActivationPayload:
    """Return deterministic posterior/occipital demo activation points.

    The payload is synthetic. It uses the posterior side of the current mesh
    coordinate space so it aligns with fsaverage-derived meshes when available.
    """
    points = np.asarray(mesh_points, dtype=float)
    if points.ndim != 2 or points.shape[1] != 3 or len(points) == 0:
        return ActivationPayload(
            points=np.empty((0, 3), dtype=float),
            values=np.empty((0,), dtype=float),
            label="Synthetic occipital demo activation",
        )

    posterior_axis = 1
    posterior_min = float(np.min(points[:, posterior_axis]))
    posterior_max = float(np.max(points[:, posterior_axis]))
    posterior_span = max(posterior_max - posterior_min, 1e-6)
    posterior_cutoff = posterior_min + posterior_span * 0.34
    posterior_points = points[points[:, posterior_axis] <= posterior_cutoff]
    if len(posterior_points) == 0:
        posterior_points = points

    centers = _occipital_centers(posterior_points)
    values = np.zeros(len(points), dtype=float)
    sigma = posterior_span * 0.18
    for center, weight in centers:
        distances = np.linalg.norm(points - center, axis=1)
        values = np.maximum(values, weight * np.exp(-((distances / sigma) ** 2)))

    posterior_weight = np.clip((posterior_cutoff - points[:, posterior_axis]) / (posterior_span * 0.22), 0.0, 1.0)
    values *= posterior_weight

    active = values > 0.08
    if not np.any(active):
        active = values > np.percentile(values, 90)
    active_points = points[active]
    active_values = values[active]

    if len(active_points) > max_points:
        order = np.argsort(active_values)[-max_points:]
        active_points = active_points[order]
        active_values = active_values[order]

    max_value = float(np.max(active_values)) if len(active_values) else 0.0
    if max_value > 0.0:
        active_values = active_values / max_value

    return ActivationPayload(
        points=active_points.astype(float),
        values=active_values.astype(float),
        label="Synthetic occipital demo activation",
    )


def _occipital_centers(points: np.ndarray) -> tuple[tuple[np.ndarray, float], ...]:
    left = _nearest_point(points, target_x=-0.32)
    right = _nearest_point(points, target_x=0.32)
    mid = _nearest_point(points, target_x=0.0)
    return (
        (left, 1.00),
        (right, 0.92),
        (mid, 0.68),
    )


def _nearest_point(points: np.ndarray, *, target_x: float) -> np.ndarray:
    y = points[:, 1]
    z = points[:, 2]
    target_y = float(np.min(y) + (np.max(y) - np.min(y)) * 0.18)
    target_z = float(np.median(z))
    target = np.asarray((target_x, target_y, target_z), dtype=float)
    distances = np.linalg.norm(points - target, axis=1)
    return points[int(np.argmin(distances))]
