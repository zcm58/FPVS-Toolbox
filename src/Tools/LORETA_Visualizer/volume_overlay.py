"""Display-only smoothing for sparse volume source payloads."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

DEFAULT_VOLUME_GRID_MAX_DIMENSION = 48
DEFAULT_VOLUME_GRID_MIN_DIMENSION = 12
DEFAULT_VOLUME_GAUSSIAN_NEIGHBORS = 6
DEFAULT_VOLUME_CONTOUR_COUNT: int | None = None
DEFAULT_VOLUME_CONTOUR_TARGET_STEP = 0.7
DEFAULT_VOLUME_CONTOUR_MIN_COUNT = 4
DEFAULT_VOLUME_CONTOUR_MAX_COUNT = 7
DEFAULT_VOLUME_CONTOUR_FRACTION = 0.62
DEFAULT_VOLUME_PADDING = 0.28
DEFAULT_VOLUME_EDGE_ZERO_MARGIN = 2


@dataclass(frozen=True)
class SmoothedVolumeOverlay:
    """Regular display-space grid containing smoothed source values."""

    dimensions: tuple[int, int, int]
    origin: tuple[float, float, float]
    spacing: tuple[float, float, float]
    values: np.ndarray
    contour_values: tuple[float, ...]
    source_point_count: int
    rendered_point_count: int


def build_smoothed_volume_overlay(
    points: np.ndarray,
    values: np.ndarray,
    *,
    display_bounds: tuple[tuple[float, float, float], tuple[float, float, float]] | None = None,
    min_visible_value: float | None = 0.0,
    max_dimension: int = DEFAULT_VOLUME_GRID_MAX_DIMENSION,
    min_dimension: int = DEFAULT_VOLUME_GRID_MIN_DIMENSION,
    gaussian_neighbors: int = DEFAULT_VOLUME_GAUSSIAN_NEIGHBORS,
    contour_count: int | None = DEFAULT_VOLUME_CONTOUR_COUNT,
    contour_target_step: float = DEFAULT_VOLUME_CONTOUR_TARGET_STEP,
    contour_min_count: int = DEFAULT_VOLUME_CONTOUR_MIN_COUNT,
    contour_max_count: int = DEFAULT_VOLUME_CONTOUR_MAX_COUNT,
    contour_fraction: float = DEFAULT_VOLUME_CONTOUR_FRACTION,
    padding: float = DEFAULT_VOLUME_PADDING,
    edge_zero_margin: int = DEFAULT_VOLUME_EDGE_ZERO_MARGIN,
) -> SmoothedVolumeOverlay | None:
    """Interpolate sparse display-space volume points onto a smooth grid.

    This is a renderer-facing display adapter. It never changes saved source
    values, source-space masks, or producer metadata.
    """

    source_points, source_values = _valid_source_arrays(points, values)
    if min_visible_value is not None:
        floor = float(min_visible_value)
        keep = source_values > floor
        source_points = source_points[keep]
        source_values = source_values[keep]
    if len(source_points) < 3:
        return None

    bounds_min, bounds_max = _grid_bounds(source_points, display_bounds=display_bounds, padding=padding)
    inside_bounds = np.all((source_points >= bounds_min) & (source_points <= bounds_max), axis=1)
    source_points = source_points[inside_bounds]
    source_values = source_values[inside_bounds]
    if len(source_points) < 3:
        return None

    dimensions = _grid_dimensions(bounds_min, bounds_max, max_dimension=max_dimension, min_dimension=min_dimension)
    axes = tuple(np.linspace(bounds_min[axis], bounds_max[axis], dimensions[axis]) for axis in range(3))
    spacing = tuple(_axis_spacing(axis_values) for axis_values in axes)
    grid_points = _grid_points(axes)

    sigma = _gaussian_sigma(source_points, spacing=spacing)
    grid_values = _gaussian_interpolated_values(
        grid_points,
        source_points,
        source_values,
        sigma=sigma,
        neighbors=gaussian_neighbors,
    ).reshape(dimensions, order="F")
    grid_values = _zero_grid_edges(grid_values, margin=edge_zero_margin)

    contour_values = _contour_values(
        grid_values,
        min_visible_value=min_visible_value,
        contour_count=contour_count,
        contour_target_step=contour_target_step,
        contour_min_count=contour_min_count,
        contour_max_count=contour_max_count,
        contour_fraction=contour_fraction,
    )
    if not contour_values:
        return None

    return SmoothedVolumeOverlay(
        dimensions=dimensions,
        origin=tuple(float(value) for value in bounds_min),
        spacing=tuple(float(value) for value in spacing),
        values=grid_values.astype(float),
        contour_values=contour_values,
        source_point_count=int(len(points)),
        rendered_point_count=int(len(source_points)),
    )


def _valid_source_arrays(points: np.ndarray, values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    source_points = np.asarray(points, dtype=float)
    source_values = np.asarray(values, dtype=float).reshape(-1)
    if source_points.ndim != 2 or source_points.shape[1] != 3:
        raise ValueError("Volume smoothing points must be an N x 3 array.")
    if len(source_points) != len(source_values):
        raise ValueError("Volume smoothing values must align one-to-one with points.")
    finite = np.isfinite(source_values) & np.all(np.isfinite(source_points), axis=1)
    return source_points[finite], source_values[finite]


def _grid_bounds(
    source_points: np.ndarray,
    *,
    display_bounds: tuple[tuple[float, float, float], tuple[float, float, float]] | None,
    padding: float,
) -> tuple[np.ndarray, np.ndarray]:
    source_min = np.min(source_points, axis=0)
    source_max = np.max(source_points, axis=0)
    source_span = source_max - source_min
    local_span = np.where(source_span <= 1e-9, max(float(np.max(source_span)), 0.1), source_span)
    pad = max(float(padding), 0.0)
    bounds_min = source_min - local_span * pad
    bounds_max = source_max + local_span * pad

    if display_bounds is not None:
        display_min = np.asarray(display_bounds[0], dtype=float)
        display_max = np.asarray(display_bounds[1], dtype=float)
        if display_min.shape != (3,) or display_max.shape != (3,):
            raise ValueError("Volume smoothing display bounds must contain min/max 3D points.")
        if not np.all(np.isfinite(display_min)) or not np.all(np.isfinite(display_max)):
            raise ValueError("Volume smoothing display bounds must be finite.")
        bounds_min = np.maximum(bounds_min, display_min)
        bounds_max = np.minimum(bounds_max, display_max)

    span = bounds_max - bounds_min
    if not np.all(np.isfinite(span)) or np.any(span <= 1e-9):
        raise ValueError("Volume smoothing display bounds are invalid.")
    return bounds_min, bounds_max


def _grid_dimensions(
    bounds_min: np.ndarray,
    bounds_max: np.ndarray,
    *,
    max_dimension: int,
    min_dimension: int,
) -> tuple[int, int, int]:
    max_dim = max(6, int(max_dimension))
    min_dim = max(3, min(int(min_dimension), max_dim))
    span = np.maximum(bounds_max - bounds_min, 1e-9)
    longest = float(np.max(span))
    dims = np.rint((span / longest) * max_dim).astype(int)
    dims = np.clip(dims, min_dim, max_dim)
    return tuple(int(value) for value in dims)


def _axis_spacing(axis_values: np.ndarray) -> float:
    if len(axis_values) < 2:
        return 1.0
    return float(axis_values[1] - axis_values[0])


def _grid_points(axes: Sequence[np.ndarray]) -> np.ndarray:
    x, y, z = np.meshgrid(*axes, indexing="ij")
    return np.column_stack(
        (
            x.ravel(order="F"),
            y.ravel(order="F"),
            z.ravel(order="F"),
        )
    )


def _gaussian_sigma(source_points: np.ndarray, *, spacing: Sequence[float]) -> float:
    grid_spacing = max(float(np.max(np.abs(spacing))), 1e-6)
    if len(source_points) < 2:
        return grid_spacing * 2.0
    from scipy.spatial import cKDTree

    tree = cKDTree(source_points)
    distances, _indices = tree.query(source_points, k=min(2, len(source_points)))
    nearest = np.asarray(distances, dtype=float)
    if nearest.ndim == 2 and nearest.shape[1] > 1:
        nearest = nearest[:, 1]
    finite = nearest[np.isfinite(nearest) & (nearest > 1e-9)]
    source_spacing = float(np.median(finite)) if len(finite) else grid_spacing
    return max(source_spacing * 0.65, grid_spacing * 1.1, 1e-6)


def _gaussian_interpolated_values(
    grid_points: np.ndarray,
    source_points: np.ndarray,
    source_values: np.ndarray,
    *,
    sigma: float,
    neighbors: int,
) -> np.ndarray:
    from scipy.spatial import cKDTree

    neighbor_count = max(1, min(int(neighbors), len(source_points)))
    support_radius = float(sigma) * 1.75
    tree = cKDTree(source_points)
    distances, indices = tree.query(
        grid_points,
        k=neighbor_count,
        distance_upper_bound=support_radius,
    )
    distances = np.asarray(distances, dtype=float)
    indices = np.asarray(indices, dtype=np.int64)
    if neighbor_count == 1:
        distances = distances.reshape(-1, 1)
        indices = indices.reshape(-1, 1)

    valid = np.isfinite(distances) & (indices >= 0) & (indices < len(source_points))
    weights = np.zeros_like(distances, dtype=float)
    weights[valid] = np.exp(-0.5 * np.square(distances[valid] / float(sigma)))
    neighbor_values = np.zeros_like(distances, dtype=float)
    neighbor_values[valid] = source_values[indices[valid]]
    weight_sums = np.sum(weights, axis=1)
    output = np.zeros(len(grid_points), dtype=float)
    nonzero = weight_sums > 0.0
    output[nonzero] = np.sum(weights[nonzero] * neighbor_values[nonzero], axis=1) / weight_sums[nonzero]
    return output


def _contour_values(
    grid_values: np.ndarray,
    *,
    min_visible_value: float | None,
    contour_count: int | None,
    contour_target_step: float,
    contour_min_count: int,
    contour_max_count: int,
    contour_fraction: float,
) -> tuple[float, ...]:
    values = np.asarray(grid_values, dtype=float).reshape(-1)
    finite = values[np.isfinite(values)]
    if min_visible_value is not None:
        floor = float(min_visible_value)
        finite = finite[finite > floor]
    elif len(finite):
        floor = float(np.nanmin(finite))
    else:
        floor = 0.0
    if len(finite) == 0:
        return ()
    vmax = float(np.nanmax(finite))
    if not np.isfinite(vmax) or vmax <= floor:
        return ()
    fraction = min(max(float(contour_fraction), 0.01), 0.95)
    threshold = max(floor + (vmax - floor) * fraction, np.nanpercentile(finite, 72.0))
    if threshold >= vmax:
        threshold = floor + (vmax - floor) * 0.5
    count = _contour_count(
        floor=floor,
        vmax=vmax,
        contour_count=contour_count,
        target_step=contour_target_step,
        min_count=contour_min_count,
        max_count=contour_max_count,
    )
    if count == 1:
        return (float(threshold),)
    return tuple(float(value) for value in np.linspace(threshold, vmax, count))


def _contour_count(
    *,
    floor: float,
    vmax: float,
    contour_count: int | None,
    target_step: float,
    min_count: int,
    max_count: int,
) -> int:
    if contour_count is not None:
        return max(1, int(contour_count))
    lower = max(1, int(min_count))
    upper = max(lower, int(max_count))
    step = max(float(target_step), 1e-6)
    dynamic_range = max(float(vmax) - float(floor), step)
    automatic_count = int(np.ceil(dynamic_range / step))
    return int(np.clip(automatic_count, lower, upper))


def _zero_grid_edges(grid_values: np.ndarray, *, margin: int) -> np.ndarray:
    edge_margin = max(0, int(margin))
    if edge_margin == 0:
        return np.asarray(grid_values, dtype=float)
    values = np.asarray(grid_values, dtype=float).copy()
    for axis, size in enumerate(values.shape):
        width = min(edge_margin, max(size // 2, 1))
        lower = [slice(None)] * values.ndim
        upper = [slice(None)] * values.ndim
        lower[axis] = slice(0, width)
        upper[axis] = slice(size - width, size)
        values[tuple(lower)] = 0.0
        values[tuple(upper)] = 0.0
    return values
