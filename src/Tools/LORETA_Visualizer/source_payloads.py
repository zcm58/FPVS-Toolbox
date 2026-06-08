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


def filter_source_payload_values_above(
    payload: SourcePayload,
    *,
    threshold: float,
    inclusive: bool = False,
) -> SourcePayload:
    """Return a display payload containing only values above a threshold."""
    numeric_threshold = float(threshold)
    values = np.asarray(payload.values, dtype=float).reshape(-1)
    keep = values >= numeric_threshold if inclusive else values > numeric_threshold
    if len(keep) != len(payload.points):
        raise ValueError("Source payload values must have one value per point.")

    filtered_points = payload.points[keep]
    filtered_values = values[keep]
    filtered_faces = _filter_faces_for_kept_points(payload.faces, keep)
    metadata = dict(payload.metadata)
    metadata.update(
        {
            "display_value_filter": "values_above_threshold",
            "display_value_filter_threshold": numeric_threshold,
            "display_value_filter_inclusive": bool(inclusive),
            "display_value_filter_original_point_count": int(len(payload.points)),
            "display_value_filter_rendered_point_count": int(len(filtered_points)),
        }
    )
    return SourcePayload(
        points=np.asarray(filtered_points, dtype=float),
        values=np.asarray(filtered_values, dtype=float),
        label=payload.label,
        kind=payload.kind,
        coordinate_space=payload.coordinate_space,
        source_model=payload.source_model,
        value_label=payload.value_label,
        faces=filtered_faces,
        metadata=metadata,
    )


def _filter_faces_for_kept_points(faces: np.ndarray | None, keep: np.ndarray) -> np.ndarray | None:
    if faces is None:
        return None
    face_array = np.asarray(faces, dtype=np.int64)
    if face_array.size == 0:
        return _empty_faces_like(face_array)
    triangle_faces, face_format = _triangle_faces_from_payload_faces(face_array)
    if not np.all((triangle_faces >= 0) & (triangle_faces < len(keep))):
        raise ValueError("Source payload faces must refer to existing points.")
    kept_indices = np.flatnonzero(keep)
    remap = np.full(len(keep), -1, dtype=np.int64)
    remap[kept_indices] = np.arange(len(kept_indices), dtype=np.int64)
    retained = np.all(keep[triangle_faces], axis=1)
    remapped = remap[triangle_faces[retained]].astype(np.int64)
    return _payload_faces_from_triangle_faces(remapped, face_format)


def _empty_faces_like(faces: np.ndarray) -> np.ndarray:
    if faces.ndim == 2 and faces.shape[1] == 3:
        return np.empty((0, 3), dtype=np.int64)
    if faces.ndim == 2 and faces.shape[1] == 4:
        return np.empty((0, 4), dtype=np.int64)
    return np.empty((0,), dtype=np.int64)


def _triangle_faces_from_payload_faces(faces: np.ndarray) -> tuple[np.ndarray, str]:
    if faces.ndim == 1:
        if len(faces) % 4 != 0:
            raise ValueError("Flat source payload faces must use VTK-style [3, i, j, k] records.")
        vtk_faces = faces.reshape(-1, 4)
        if not np.all(vtk_faces[:, 0] == 3):
            raise ValueError("Flat source payload faces must use triangular VTK-style records.")
        return vtk_faces[:, 1:4], "vtk_flat"
    if faces.ndim == 2 and faces.shape[1] == 4:
        if not np.all(faces[:, 0] == 3):
            raise ValueError("Source payload VTK face rows must use triangular records.")
        return faces[:, 1:4], "vtk_rows"
    if faces.ndim == 2 and faces.shape[1] == 3:
        return faces, "triangle_rows"
    raise ValueError("Source payload faces must be triangle rows or VTK-style triangular records.")


def _payload_faces_from_triangle_faces(faces: np.ndarray, face_format: str) -> np.ndarray:
    if face_format == "triangle_rows":
        return faces.astype(np.int64)
    counts = np.full((len(faces), 1), 3, dtype=np.int64)
    vtk_faces = np.hstack((counts, faces.astype(np.int64)))
    if face_format == "vtk_rows":
        return vtk_faces
    return vtk_faces.reshape(-1)


def _normalize_values(values: np.ndarray) -> np.ndarray:
    if len(values) == 0:
        return values.astype(float)
    min_value = float(np.min(values))
    max_value = float(np.max(values))
    if max_value <= min_value:
        fill = 1.0 if max_value > 0.0 else 0.0
        return np.full(len(values), fill, dtype=float)
    return (values - min_value) / (max_value - min_value)
