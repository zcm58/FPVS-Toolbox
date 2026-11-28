"""Sibson natural-neighbor interpolation on the plane of a projected EEG cap.

Each weight is the fraction of an inserted query's Voronoi cell taken from
one original electrode's cell. Store those weights once for reuse by any
metric on the same finite electrode layout.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np
from scipy.sparse import coo_matrix, csr_matrix
from scipy.spatial import Delaunay, Voronoi


# Coordinates are normalized isotropically into a unit bounding box.
_TOLERANCE = 64 * np.finfo(float).eps


def _cross(a, b):
    return a[..., 0] * b[..., 1] - a[..., 1] * b[..., 0]


def _voronoi_cells(sites):
    """Return oriented finite edges and boundary rays for each original site."""
    vor = Voronoi(sites)
    cells = [[] for _ in sites]
    centre = sites.mean(axis=0)
    for (i, j), vertices in zip(vor.ridge_points, vor.ridge_vertices, strict=True):
        finite = -1 not in vertices
        if finite:
            a, b = vor.vertices[vertices]
            edge = b - a
        else:
            a = vor.vertices[max(vertices)]
            delta = sites[j] - sites[i]
            edge = np.array([-delta[1], delta[0]])
            edge *= np.sign(edge @ ((sites[i] + sites[j]) * 0.5 - centre)) / np.linalg.norm(edge)
        for site in (i, j):
            start = a - sites[site]
            orientation = np.sign(_cross(edge, -start))
            cells[site].append((start, edge, orientation, finite))
    return cells


def _stolen_area(offsets, edges):
    """Twice the area taken from one Voronoi cell by the inserted queries.

    Within the old cell its site is already closest. Only one bisector is
    needed to clip the cell. Integrate each retained oriented edge about a
    point on that bisector, where the closing segment has zero signed area.
    """
    dx, dy = offsets.T
    half_squared = (dx * dx + dy * dy) * 0.5
    area = np.zeros(len(offsets))
    for start, edge, orientation, finite in edges:
        h = start[0] * dx + start[1] * dy - half_squared
        step = edge[0] * dx + edge[1] * dy
        if finite:
            end = h + step
            # Segment fraction on the query's side of the bisector.
            length = np.clip(np.divide(np.maximum(h, end), np.abs(step),
                                       out=(h >= 0).astype(float), where=step != 0), 0, 1)
        else:
            # An interior query's side always ends before infinity.
            length = np.divide(np.maximum(h, 0), -step, out=np.zeros_like(h), where=step < 0)
        moment = (start[0] - dx * .5) * edge[1] - (start[1] - dy * .5) * edge[0]
        area += orientation * moment * length
    return np.maximum(area, 0)


def _boundary_weights(sites, tri, simplices, rows, xy):
    # The limiting value on the hull is linear along its edge. Exact electrode
    # locations interpolate to themselves (also on a cocircular montage).
    weights = []
    matched = np.zeros(len(xy), dtype=bool)
    vertices = tri.simplices[simplices]
    for j in range(3):
        offset = xy - sites[vertices[:, j]]
        exact = (np.abs(offset[:, 0]) <= _TOLERANCE) & (np.abs(offset[:, 1]) <= _TOLERANCE) & ~matched
        matched |= exact
        weights.append((rows[exact], vertices[exact, j], np.ones(np.count_nonzero(exact))))
    for j in range(3):
        idx = np.flatnonzero((tri.neighbors[simplices, j] < 0) & ~matched)
        a, b = vertices[idx, (j + 1) % 3], vertices[idx, (j + 2) % 3]
        ab = sites[b] - sites[a]
        delta = xy[idx] - sites[a]
        squared = np.einsum("ij,ij->i", ab, ab)
        tol = _TOLERANCE * np.sqrt(squared)
        projection = np.einsum("ij,ij->i", delta, ab)
        on_edge = (np.abs(_cross(delta, ab)) <= tol) & (projection >= -tol) & (projection <= squared + tol)
        t = np.clip(projection[on_edge] / squared[on_edge], 0, 1)
        edge_rows = rows[idx[on_edge]]
        weights.append((edge_rows, a[on_edge], 1 - t))
        weights.append((edge_rows, b[on_edge], t))
        matched[idx[on_edge]] = True

    return weights, matched


@lru_cache(maxsize=4)
def _bounded_voronoi_cells(site_bytes):
    """Reuse Voronoi edges and their search bounds across atlas and camera queries."""
    sites = np.frombuffer(site_bytes, np.float64).reshape(-1, 2)
    cells = []
    for i, edges in enumerate(_voronoi_cells(sites)):
        # Changes to an old cell can only occur inside a circumcircle of
        # one of its vertices. Restrict clipping to that bounding box.
        starts = [edge[0] for edge in edges]
        ends = [a + delta for a, delta, _, finite in edges if finite]
        corners = np.array(starts + ends)
        radii = np.linalg.norm(corners, axis=1)[:, None]
        low = sites[i] + (corners - radii).min(axis=0) - _TOLERANCE
        high = sites[i] + (corners + radii).max(axis=0) + _TOLERANCE
        cells.append((edges, low, high))
    return cells


def _interior_areas(sites, rows, xy):
    order = np.argsort(xy[:, 0], kind="stable")
    rows, xy = rows[order], xy[order]
    xs, ys = xy.T
    for i, (edges, low, high) in enumerate(_bounded_voronoi_cells(sites.tobytes())):
        left, right = np.searchsorted(xs, [low[0], high[0]])
        idx = left + np.flatnonzero((ys[left:right] >= low[1]) & (ys[left:right] <= high[1]))
        if not len(idx):
            continue
        area = _stolen_area(xy[idx] - sites[i], edges)
        positive = area > 0
        yield rows[idx[positive]], np.full(np.count_nonzero(positive), i), area[positive]


def natural_neighbor_weights(coordinates: np.ndarray, queries: np.ndarray) -> csr_matrix:
    """Compute reusable, normalized Sibson weights; exterior rows have no entries."""
    coordinates = np.asarray(coordinates, dtype=float)
    queries = np.asarray(queries, dtype=float)
    if coordinates.ndim != 2 or coordinates.shape[1] != 2 or queries.ndim != 2 or queries.shape[1] != 2:
        raise ValueError("Scalp interpolation needs two-dimensional coordinates.")
    if (len(coordinates) < 3 or not np.all(np.isfinite(coordinates))
            or len(np.unique(coordinates, axis=0)) != len(coordinates)):
        raise ValueError("Scalp interpolation needs distinct, finite electrode locations.")
    origin = coordinates.min(axis=0)
    scale = np.ptp(coordinates, axis=0).max()
    sites = (coordinates - origin) / scale
    query = (queries - origin) / scale
    tri = Delaunay(sites)
    finite_rows = np.flatnonzero(np.isfinite(query).all(axis=1))
    simplex = tri.find_simplex(query[finite_rows])
    inside = simplex >= 0
    rows = finite_rows[inside]
    shape = (len(query), len(sites))
    xy = query[rows]
    parts, boundary = _boundary_weights(sites, tri, simplex[inside], rows, xy)
    # For a slender hull triangle Qhull's barycentric tolerance may miss a
    # point constructed exactly on an edge. Use a relaxed search to identify
    # candidates, then accept only the geometric site/segment test above.
    rejected = finite_rows[~inside]
    if len(rejected):
        retry = tri.find_simplex(query[rejected], tol=1e-10)
        near = rejected[retry >= 0]
        if len(near):
            extra, _ = _boundary_weights(sites, tri, retry[retry >= 0], near, query[near])
            parts.extend(extra)
    if not boundary.all():
        parts.extend(_interior_areas(sites, rows[~boundary], xy[~boundary]))
    row_ids, column_ids, areas = (np.concatenate(field) for field in zip(*parts, strict=True))
    weights = coo_matrix((areas, (row_ids, column_ids)), shape=shape).tocsr()
    totals = np.asarray(weights.sum(axis=1)).ravel()
    if np.any(totals[finite_rows[inside]] <= 0) or not np.isfinite(weights.data).all():
        raise ValueError("Unable to interpolate the measured scalp area for this montage.")
    weights.data /= np.repeat(totals, np.diff(weights.indptr))
    return weights
