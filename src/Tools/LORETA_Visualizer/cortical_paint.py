"""Display-only cortical surface paint projection helpers."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from Tools.LORETA_Visualizer.source_payloads import SOURCE_KIND_SURFACE_MESH, SourcePayload

DEFAULT_CORTICAL_PAINT_NEIGHBORS = 4
DEFAULT_CORTICAL_PAINT_POWER = 2.0
DEFAULT_CORTICAL_PAINT_Z_THRESHOLD = 1.64


@dataclass(frozen=True)
class CorticalPaintProjection:
    """Scalar values projected onto the high-resolution display cortex."""

    values: np.ndarray
    source_value_min: float
    source_value_max: float


def source_payload_uses_zscores(payload: SourcePayload) -> bool:
    """Return whether a payload's scalar values should be read as z-scores."""
    source_unit = str(payload.metadata.get("source_value_unit", "")).strip().lower()
    if source_unit in {"z-score", "z score", "zscore"}:
        return True
    label = payload.value_label.strip().lower()
    model = payload.source_model.strip().lower()
    return "z-score" in label or "zscore" in model


def uses_cortical_surface_paint(payload: SourcePayload) -> bool:
    """Return whether a payload should render as opaque cortical paint."""
    if payload.kind != SOURCE_KIND_SURFACE_MESH or payload.faces is None:
        return False
    model_text = " ".join(
        (
            payload.source_model,
            str(payload.metadata.get("producer_method", "")),
            str(payload.metadata.get("base_producer_method", "")),
            str(payload.metadata.get("source_model", "")),
            str(payload.metadata.get("source_space", "")),
        )
    ).lower()
    return "l2_mne" in model_text


def project_cortical_surface_payload(
    display_points: np.ndarray,
    payload: SourcePayload,
    *,
    neighbors: int = DEFAULT_CORTICAL_PAINT_NEIGHBORS,
    power: float = DEFAULT_CORTICAL_PAINT_POWER,
    z_threshold: float = DEFAULT_CORTICAL_PAINT_Z_THRESHOLD,
) -> CorticalPaintProjection:
    """Project an L2-MNE cortical source mesh onto the display brain mesh.

    This is visualization interpolation only. It does not change the prepared
    payload or imply additional source-estimation precision.
    """
    if not uses_cortical_surface_paint(payload):
        raise ValueError("Cortical paint projection requires an L2-MNE cortical surface mesh payload.")

    target_points = np.asarray(display_points, dtype=float)
    source_points = np.asarray(payload.points, dtype=float)
    source_values = np.asarray(payload.values, dtype=float).reshape(-1)
    _validate_projection_inputs(target_points, source_points, source_values)

    original_min = float(np.min(source_values))
    original_max = float(np.max(source_values))
    projection_values = source_values.copy()
    is_zscore_payload = source_payload_uses_zscores(payload)
    if is_zscore_payload:
        threshold = _valid_z_threshold(z_threshold)
        projection_values = np.where(projection_values >= threshold, projection_values, 0.0)

    interpolated = _inverse_distance_values(
        target_points,
        source_points,
        projection_values,
        neighbors=neighbors,
        power=power,
    )
    if is_zscore_payload:
        interpolated = np.where(interpolated >= threshold, interpolated, np.nan)
    return CorticalPaintProjection(
        values=np.asarray(interpolated, dtype=float),
        source_value_min=original_min,
        source_value_max=original_max,
    )


def _valid_z_threshold(z_threshold: float) -> float:
    threshold = float(z_threshold)
    if not np.isfinite(threshold) or threshold < 0.0:
        return DEFAULT_CORTICAL_PAINT_Z_THRESHOLD
    return threshold


def _validate_projection_inputs(
    target_points: np.ndarray,
    source_points: np.ndarray,
    source_values: np.ndarray,
) -> None:
    if target_points.ndim != 2 or target_points.shape[1] != 3 or len(target_points) == 0:
        raise ValueError("Cortical paint target points must be a non-empty N x 3 array.")
    if source_points.ndim != 2 or source_points.shape[1] != 3 or len(source_points) == 0:
        raise ValueError("Cortical paint source points must be a non-empty N x 3 array.")
    if len(source_points) != len(source_values):
        raise ValueError("Cortical paint source values must align one-to-one with source points.")
    if not np.all(np.isfinite(target_points)):
        raise ValueError("Cortical paint target points must be finite.")
    if not np.all(np.isfinite(source_points)) or not np.all(np.isfinite(source_values)):
        raise ValueError("Cortical paint source points and values must be finite.")


def _inverse_distance_values(
    target_points: np.ndarray,
    source_points: np.ndarray,
    source_values: np.ndarray,
    *,
    neighbors: int,
    power: float,
) -> np.ndarray:
    from scipy.spatial import cKDTree

    k = max(1, min(int(neighbors), len(source_points)))
    numeric_power = max(float(power), 0.1)
    tree = cKDTree(source_points)
    distances, indices = tree.query(target_points, k=k)

    if k == 1:
        return source_values[np.asarray(indices, dtype=np.int64)]

    distances = np.asarray(distances, dtype=float)
    indices = np.asarray(indices, dtype=np.int64)
    exact = distances <= 1e-12
    has_exact = np.any(exact, axis=1)
    output = np.empty(len(target_points), dtype=float)

    if np.any(has_exact):
        exact_rows = np.flatnonzero(has_exact)
        first_exact_columns = np.argmax(exact[has_exact], axis=1)
        output[exact_rows] = source_values[indices[exact_rows, first_exact_columns]]

    weighted_rows = ~has_exact
    if np.any(weighted_rows):
        weighted_distances = distances[weighted_rows]
        weighted_indices = indices[weighted_rows]
        weights = 1.0 / np.power(weighted_distances, numeric_power)
        neighbor_values = source_values[weighted_indices]
        finite_values = np.isfinite(neighbor_values)
        finite_weights = np.where(finite_values, weights, 0.0)
        weight_sums = np.sum(finite_weights, axis=1)
        weighted_values = np.where(finite_values, neighbor_values, 0.0)
        row_values = np.full(len(weight_sums), np.nan, dtype=float)
        valid_rows = weight_sums > 0.0
        row_values[valid_rows] = (
            np.sum(finite_weights[valid_rows] * weighted_values[valid_rows], axis=1)
            / weight_sums[valid_rows]
        )
        output[weighted_rows] = row_values
    return output
