"""Coordinate transform contracts for LORETA visualizer payloads."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

COORDINATE_SPACE_DISPLAY = "normalized_display"
COORDINATE_SPACE_FSAVERAGE = "fsaverage_surface"
COORDINATE_SPACE_FSAVERAGE_VOLUME = "fsaverage_volume"
COORDINATE_SPACE_UNKNOWN = "unknown"

_FSAVERAGE_COMPATIBLE_COORDINATE_SPACES = frozenset(
    {
        COORDINATE_SPACE_FSAVERAGE,
        COORDINATE_SPACE_FSAVERAGE_VOLUME,
    }
)


@dataclass(frozen=True)
class MeshDisplayTransform:
    """Map native anatomical/source coordinates into renderer display space."""

    center: np.ndarray
    radius: float
    native_coordinate_space: str = COORDINATE_SPACE_UNKNOWN
    display_coordinate_space: str = COORDINATE_SPACE_DISPLAY

    @classmethod
    def identity(cls) -> MeshDisplayTransform:
        """Return an identity display transform."""
        return cls(
            center=np.zeros(3, dtype=float),
            radius=1.0,
            native_coordinate_space=COORDINATE_SPACE_DISPLAY,
        )

    @classmethod
    def from_native_points(
        cls,
        points: np.ndarray,
        *,
        native_coordinate_space: str = COORDINATE_SPACE_UNKNOWN,
    ) -> MeshDisplayTransform:
        """Build the same center/radius normalization used for display meshes."""
        payload_points = _validate_points(points)
        center = np.mean(payload_points, axis=0)
        radius = float(np.max(np.linalg.norm(payload_points - center, axis=1)))
        if radius <= 0.0:
            raise ValueError("Display transform cannot be built from a zero-radius point cloud.")
        return cls(
            center=center.astype(float),
            radius=radius,
            native_coordinate_space=str(native_coordinate_space),
        )

    def to_display_points(
        self,
        points: np.ndarray,
        *,
        coordinate_space: str | None = None,
    ) -> np.ndarray:
        """Transform points from native/display coordinates into display coordinates."""
        payload_points = _validate_points(points)
        source_space = self.native_coordinate_space if coordinate_space is None else str(coordinate_space)
        if source_space == self.display_coordinate_space:
            return payload_points.astype(float)
        if not _coordinate_spaces_are_transform_compatible(
            source_space,
            self.native_coordinate_space,
        ):
            raise ValueError(
                f"Cannot transform {source_space!r} points with a {self.native_coordinate_space!r} display transform."
            )
        return ((payload_points - self.center) / self.radius).astype(float)

    def from_display_points(self, points: np.ndarray) -> np.ndarray:
        """Transform display coordinates back into this transform's native space."""
        payload_points = _validate_points(points)
        return (payload_points * self.radius + self.center).astype(float)


def _validate_points(points: np.ndarray) -> np.ndarray:
    payload_points = np.asarray(points, dtype=float)
    if payload_points.ndim != 2 or payload_points.shape[1] != 3:
        raise ValueError("Coordinate transforms require an N x 3 point array.")
    if len(payload_points) == 0:
        raise ValueError("Coordinate transforms require at least one point.")
    if not np.all(np.isfinite(payload_points)):
        raise ValueError("Coordinate transforms require finite points.")
    return payload_points


def _coordinate_spaces_are_transform_compatible(source_space: str, native_space: str) -> bool:
    if source_space == native_space:
        return True
    return {source_space, native_space}.issubset(_FSAVERAGE_COMPATIBLE_COORDINATE_SPACES)
