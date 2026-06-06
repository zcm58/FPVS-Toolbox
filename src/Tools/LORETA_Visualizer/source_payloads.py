"""Renderer-facing source payload contracts for the LORETA visualizer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from Tools.LORETA_Visualizer.transforms import COORDINATE_SPACE_DISPLAY, MeshDisplayTransform

SOURCE_KIND_SURFACE_POINTS = "surface_points"
SOURCE_KIND_SURFACE_MESH = "surface_mesh"
SOURCE_KIND_VOLUME_POINTS = "volume_points"
SOURCE_KIND_VOLUME_MESH = "volume_mesh"
SOURCE_KIND_ROI_MESH = "roi_mesh"


@dataclass(frozen=True)
class SourcePayload:
    """Prepared source values in renderer coordinates.

    This is intentionally a rendering contract, not a LORETA calculation model.
    Future computation paths should prepare coordinates and scalar values before
    creating this payload.
    """

    points: np.ndarray
    values: np.ndarray
    label: str
    kind: str = SOURCE_KIND_SURFACE_POINTS
    coordinate_space: str = COORDINATE_SPACE_DISPLAY
    source_model: str = "cortical_surface"
    value_label: str = "activation"
    faces: np.ndarray | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def make_source_payload(
    *,
    points: np.ndarray,
    values: np.ndarray,
    label: str,
    kind: str = SOURCE_KIND_SURFACE_POINTS,
    coordinate_space: str = COORDINATE_SPACE_DISPLAY,
    source_model: str = "cortical_surface",
    value_label: str = "activation",
    faces: np.ndarray | None = None,
    metadata: dict[str, Any] | None = None,
    normalize_values: bool = True,
) -> SourcePayload:
    """Validate and normalize a renderer-facing source payload."""
    payload_points = np.asarray(points, dtype=float)
    payload_values = np.asarray(values, dtype=float).reshape(-1)
    if payload_points.ndim != 2 or payload_points.shape[1] != 3:
        raise ValueError("Source payload points must be an N x 3 array.")
    if len(payload_points) != len(payload_values):
        raise ValueError("Source payload values must have one value per point.")

    finite = np.isfinite(payload_values) & np.all(np.isfinite(payload_points), axis=1)
    if faces is not None and not np.all(finite):
        raise ValueError("Source mesh payloads must not contain non-finite points or values.")
    payload_points = payload_points[finite]
    payload_values = payload_values[finite]
    if normalize_values:
        payload_values = _normalize_values(payload_values)

    payload_faces = None if faces is None else np.asarray(faces, dtype=np.int64)
    return SourcePayload(
        points=payload_points.astype(float),
        values=payload_values.astype(float),
        label=str(label),
        kind=str(kind),
        coordinate_space=str(coordinate_space),
        source_model=str(source_model),
        value_label=str(value_label),
        faces=payload_faces,
        metadata=dict(metadata or {}),
    )


def empty_source_payload(label: str) -> SourcePayload:
    """Return an empty, valid source payload."""
    return SourcePayload(
        points=np.empty((0, 3), dtype=float),
        values=np.empty((0,), dtype=float),
        label=label,
    )


def source_payload_to_display(
    payload: SourcePayload,
    display_transform: MeshDisplayTransform,
) -> SourcePayload:
    """Return a payload whose coordinates are in renderer display space."""
    if payload.coordinate_space == display_transform.display_coordinate_space:
        return payload
    display_points = display_transform.to_display_points(
        payload.points,
        coordinate_space=payload.coordinate_space,
    )
    return make_source_payload(
        points=display_points,
        values=payload.values,
        label=payload.label,
        kind=payload.kind,
        coordinate_space=display_transform.display_coordinate_space,
        source_model=payload.source_model,
        value_label=payload.value_label,
        faces=payload.faces,
        metadata=payload.metadata,
        normalize_values=False,
    )


def _normalize_values(values: np.ndarray) -> np.ndarray:
    if len(values) == 0:
        return values.astype(float)
    min_value = float(np.min(values))
    max_value = float(np.max(values))
    if max_value <= min_value:
        fill = 1.0 if max_value > 0.0 else 0.0
        return np.full(len(values), fill, dtype=float)
    return (values - min_value) / (max_value - min_value)
