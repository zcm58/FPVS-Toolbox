"""Orthographic views of head-frame EEG sensor values on Toolbox's generic head.

Sibson natural-neighbor interpolation uses azimuthal-equidistant cap coordinates inside
the convex hull of the finite electrodes. The head supplies the drawing surface
and anatomical landmarks. Its shape is shared across subjects and conditions.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
from mne.io.constants import FIFF
from scipy.sparse import csr_matrix
from scipy.spatial import ConvexHull, QhullError, cKDTree

from Tools.Publication_Maps.natural_neighbor import natural_neighbor_weights
from Tools.Publication_Maps.scalp_io import InsufficientSensorCoverageError


# Situated 40.15 mm above the ear/nasion plane in head coordinates. This is
# the centre of the original 95 mm BioSemi display sphere (25° inferior ring).
_TEMPLATE_ORIGIN = np.array([0.0, 0.0, 0.095 * np.sin(np.deg2rad(25.0))])
_PAINT_BLOCK_SIZE = 32_768


@dataclass(frozen=True)
class _ScalpGeometry:
    vertices: np.ndarray
    faces: np.ndarray
    origin: np.ndarray
    neck_plane: np.ndarray


@dataclass(frozen=True)
class _SensorProjection:
    cap_coordinates: np.ndarray
    locations: np.ndarray


@dataclass(frozen=True)
class ScalpSurfaceScene:
    """Head-frame mesh in metres and a sensor-space field for an interactive viewer.

    The neutral head uses all faces. Use scalp_faces for the unlit, transparent
    texture overlay. Texture row zero corresponds to the lowest V coordinate;
    flip it vertically for a top-row-first image reader such as PyVista Texture.
    """

    vertices: np.ndarray
    faces: np.ndarray
    scalp_faces: np.ndarray
    origin: np.ndarray
    texture_coordinates: np.ndarray
    texture_rgba: np.ndarray
    sensor_locations: np.ndarray


@dataclass(frozen=True)
class _HeadImage:
    skin: np.ndarray
    pixel_indices: np.ndarray
    cap_coordinates: np.ndarray
    extent: tuple[float, float, float, float]


def _cap_coordinates(vectors: np.ndarray) -> np.ndarray:
    """Project a direction to the plane by its angular distance from the crown."""
    xy = vectors[:, :2]
    radius = np.linalg.norm(xy, axis=1)
    polar_angle = np.arctan2(radius, vectors[:, 2])
    coordinates = xy * np.divide(polar_angle, radius, out=np.zeros_like(radius), where=radius > 0)[:, None]
    coordinates[(radius == 0) & (vectors[:, 2] < 0), 0] = np.pi
    return coordinates


@lru_cache(maxsize=1)
def _ray_triangles():
    geometry = _geometry()
    points = geometry.vertices - geometry.origin
    unit = points / np.linalg.norm(points, axis=1, keepdims=True)
    corners = unit[geometry.faces]
    centers = corners.sum(axis=1)
    centers /= np.linalg.norm(centers, axis=1, keepdims=True)
    # The smallest cosine bounds a spherical cap containing the whole
    # triangle. For caps wider than a hemisphere, always test the triangle.
    cosines = np.einsum("fvc,fc->fv", corners, centers).min(axis=1)
    cosines[cosines < 0] = -1
    a, b, c = points[geometry.faces].transpose(1, 0, 2)
    edge1, edge2 = b - a, c - a
    offset = -a
    cross = np.cross(offset, edge1)
    numerator = np.einsum("ij,ij->i", edge2, cross)
    return centers, cosines, edge1, edge2, offset, cross, numerator


def _radial_sensor_locations(directions: np.ndarray, names: tuple[str, ...]) -> np.ndarray:
    """Place each electrode on the outermost skin along its measured direction."""
    centers, cosines, edge1, edge2, offset, cross, numerator = _ray_triangles()
    geometry = _geometry()
    # A flat cap closes the anatomical mesh for lighting; it cannot represent
    # an electrode site. Exclude it even if a ray intersects multiple surfaces.
    plane = geometry.neck_plane
    origin_height = geometry.origin @ plane[:3] + plane[3]
    positions = []
    outside = []
    for name, direction in zip(names, directions, strict=True):
        possible = np.flatnonzero(centers @ direction >= cosines - 1e-12)
        perpendicular = np.cross(direction, edge2[possible])
        det = np.einsum("ij,ij->i", edge1[possible], perpendicular)
        reciprocal = np.divide(1, det, where=np.abs(det) > 1e-15, out=np.zeros_like(det))
        u = np.einsum("ij,ij->i", offset[possible], perpendicular) * reciprocal
        v = (cross[possible] @ direction) * reciprocal
        distance = numerator[possible] * reciprocal
        hits = (u >= -1e-10) & (v >= -1e-10) & (u + v <= 1 + 1e-10) & (distance > 0)
        skin_hits = hits & (origin_height + distance * (direction @ plane[:3]) > 1e-7)
        if skin_hits.any():
            positions.append(direction * distance[skin_hits].max())
        else:
            outside.append(name)
    if outside:
        raise ValueError(f"Electrodes outside the 3D head template: {', '.join(outside)}. Use the 2D top view.")
    return geometry.origin + np.asarray(positions)


@lru_cache(maxsize=1)
def _geometry() -> _ScalpGeometry:
    try:
        with np.load(Path(__file__).with_name("data") / "neutral_head.npz", allow_pickle=False) as mesh:
            vertices = mesh["vertices"].astype(np.float64)
            faces = mesh["faces"].astype(np.int32)
            neck_plane = mesh["neck_plane"]
    except (OSError, ValueError, KeyError) as exc:
        raise ValueError("The 3D scalp template is missing or unreadable. Repair the Toolbox installation.") from exc
    return _ScalpGeometry(vertices, faces, _TEMPLATE_ORIGIN, neck_plane)


@lru_cache(maxsize=16)
def _montage_origin(digitization: bytes) -> np.ndarray:
    """Fit the complete montage, falling back to the template for sparse or one-sided coverage."""
    points = np.frombuffer(digitization, dtype=np.float64).reshape(-1, 3)
    if len(points) < 9 or (points[:, :2].min(axis=0) >= 0).any() or (points[:, :2].max(axis=0) <= 0).any():
        return _TEMPLATE_ORIGIN
    mean = points.mean(axis=0)
    centered = points - mean
    offset, _, _, singular_values = np.linalg.lstsq(2 * centered, (centered * centered).sum(axis=1), rcond=None)
    origin = mean + offset
    # Nearly planar points and very eccentric fitted spheres are unstable:
    # the fiducial frame still gives a defined, montage-independent reference.
    radius = np.median(np.linalg.norm(points - origin, axis=1))
    if singular_values[-1] < 0.05 * singular_values[0] or np.linalg.norm(origin - _TEMPLATE_ORIGIN) > 0.5 * radius:
        return _TEMPLATE_ORIGIN
    return origin


def _sensor_projection(info) -> _SensorProjection:
    if any(ch["coord_frame"] != FIFF.FIFFV_COORD_HEAD for ch in info["chs"]):
        raise ValueError("3D scalp maps require electrode coordinates in the head frame.")
    selected = np.asarray([ch["loc"][:3] for ch in info["chs"]], dtype=np.float64)
    # MNE pick_info retains the original full EEG digitization in Info.dig.
    # Changes in the selected metric or its finite sensors cannot move the cap.
    full = np.asarray([d["r"] for d in info.get("dig") or () if d["kind"] == FIFF.FIFFV_POINT_EEG
                       and d["coord_frame"] == FIFF.FIFFV_COORD_HEAD and np.isfinite(d["r"]).all()], dtype=np.float64)
    if not np.isfinite(selected).all():
        raise ValueError("3D scalp maps require finite electrode coordinates.")
    return _project_sensors(selected.tobytes(), full.tobytes(), tuple(info.ch_names))


@lru_cache(maxsize=32)
def _project_sensors(selected: bytes, full: bytes, names: tuple[str, ...]) -> _SensorProjection:
    directions = np.frombuffer(selected, dtype=np.float64).reshape(-1, 3) - _montage_origin(full)
    radii = np.linalg.norm(directions, axis=1, keepdims=True)
    at_centre = np.flatnonzero(radii < 1e-9)
    if len(at_centre):
        raise ValueError(f"Electrodes at the head centre have no scalp direction: {', '.join(names[i] for i in at_centre)}.")
    directions /= radii
    beneath = np.flatnonzero((directions[:, 2] < 0) & (np.linalg.norm(directions[:, :2], axis=1) < 1e-9))
    if len(beneath):
        raise ValueError(f"Electrodes directly beneath the 3D head have no cap angle: {', '.join(names[i] for i in beneath)}. "
                         "Use the 2D top view.")
    cap = _cap_coordinates(directions)
    if len(np.unique(cap.round(9), axis=0)) != len(cap):
        raise ValueError("Electrodes with overlapping scalp directions cannot be mapped independently.")
    return _SensorProjection(cap, _radial_sensor_locations(directions, names))


def _camera(view: str) -> np.ndarray:
    if view not in ("front", "back"):
        raise ValueError(f"Unknown 3D scalp view: {view!r}.")
    sign = 1 if view == "front" else -1
    # In head coordinates +X is the participant's right and +Y is anterior.
    angle = np.deg2rad(34 if view == "front" else 27)
    return np.array([[-sign, 0, 0], [0, -sign * np.sin(angle), np.cos(angle)],
                     [0, sign * np.cos(angle), np.sin(angle)]])


def _rasterize_skin(screen, faces, heights, brightness, width, height):
    """Rasterize triangle scanlines with smooth shading and nearest-surface depth."""
    corners = screen[faces]
    # Intersect horizontal pixel rows with the long edge and one short edge.
    order = np.argsort(corners[:, :, 1], axis=1)
    bottom, middle, top = np.take_along_axis(corners, order[:, :, None], axis=1).transpose(1, 0, 2)
    first = np.maximum(0, np.ceil(bottom[:, 1]).astype(int))
    last = np.minimum(height - 1, np.floor(top[:, 1]).astype(int))
    row_counts = np.maximum(0, last - first + 1)
    tri = np.repeat(np.arange(len(faces)), row_counts)
    y = np.arange(len(tri)) + np.repeat(first - np.cumsum(row_counts) + row_counts, row_counts)

    def edge_slope(start, end):
        dx, dy = (end - start).T
        return np.divide(dx, dy, out=np.zeros_like(dx), where=dy != 0)

    lower = y < middle[tri, 1]
    x_long = bottom[tri, 0] + (y - bottom[tri, 1]) * edge_slope(bottom, top)[tri]
    x_short = np.where(
        lower, bottom[tri, 0] + (y - bottom[tri, 1]) * edge_slope(bottom, middle)[tri],
        middle[tri, 0] + (y - middle[tri, 1]) * edge_slope(middle, top)[tri],
    )
    first_x = np.maximum(0, np.ceil(np.minimum(x_long, x_short) - 1e-9).astype(int))
    last_x = np.minimum(width - 1, np.floor(np.maximum(x_long, x_short) + 1e-9).astype(int))
    lengths = np.maximum(0, last_x - first_x + 1)
    cumulative = np.r_[0, np.cumsum(lengths)]
    # Each projected triangle defines an affine plane for depth and shade.
    a, b, c = corners.transpose(1, 0, 2)
    ab, ac = b - a, c - a
    det = ab[:, 0] * ac[:, 1] - ab[:, 1] * ac[:, 0]

    def scanline_values(values):
        va, vb, vc = values[faces].T
        dx = ((vb - va) * ac[:, 1] - (vc - va) * ab[:, 1]) / det
        dy = ((vc - va) * ab[:, 0] - (vb - va) * ac[:, 0]) / det
        value = va[tri] + dx[tri] * (first_x - a[tri, 0]) + dy[tri] * (y - a[tri, 1])
        return value, dx[tri]

    z0, dz = scanline_values(heights)
    g0, dg = scanline_values(brightness)
    depths = np.full(width * height, -np.inf)
    gray = np.zeros(width * height, np.uint8)
    # Bound temporary arrays independently of the publication figure dimensions.
    row = 0
    while row < len(y):
        end = min(len(y), np.searchsorted(cumulative, cumulative[row] + 160_000))
        lines = np.repeat(np.arange(row, end), lengths[row:end])
        dx = np.arange(cumulative[row], cumulative[end]) - cumulative[lines]
        pixel = (y[lines] * width + first_x[lines]) + dx
        depth = z0[lines] + dz[lines] * dx
        np.maximum.at(depths, pixel, depth)
        front = depth == depths[pixel]
        visible = lines[front]
        gray[pixel[front]] = g0[visible] + dg[visible] * dx[front]
        row = end
    return depths.reshape(height, width), gray.reshape(height, width)


@lru_cache(maxsize=2)
def _render_head(view: str, width: int) -> _HeadImage:
    """Rasterize static anatomy with a depth buffer shared by all data panels."""
    geometry = _geometry()
    basis = _camera(view)
    camera_vertices = np.einsum("ij,kj->ik", geometry.vertices, basis)
    # Frame both complete template views at the same physical scale.
    left, right, bottom, top = -0.091, 0.091, -0.126, 0.142
    pixel = (right - left) / width
    height = int(np.ceil((top - bottom) / pixel))
    extent = (left, right, bottom, bottom + height * pixel)
    triangles = camera_vertices[geometry.faces]
    face_normals = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
    normals = np.zeros_like(camera_vertices)
    for column in geometry.faces.T:
        np.add.at(normals, column, face_normals)
    normals /= np.maximum(np.linalg.norm(normals, axis=1), 1e-15)[:, None]
    light = np.array([-0.48, 0.55, 0.68])
    brightness = 145 + 91 * np.maximum(0, np.einsum("ij,j->i", normals, light))
    screen = (camera_vertices[:, :2] - [left, bottom]) / pixel - 0.5
    front_faces = geometry.faces[face_normals[:, 2] > 0]
    depth, gray = _rasterize_skin(screen, front_faces, camera_vertices[:, 2], brightness, width, height)
    inside_head = np.isfinite(depth)
    pixels = np.flatnonzero(inside_head).astype(np.int32)
    surface_coordinates = np.empty((len(pixels), 2), dtype=np.float32)
    skin_surface = np.empty(len(pixels), dtype=bool)
    # A large print tile contains millions of points. Project small blocks to
    # keep the camera-to-head transform and cap coordinates in cache.
    for start in range(0, len(pixels), 65_536):
        block = pixels[start:start + 65_536]
        y, x = np.divmod(block, width)
        camera_points = np.column_stack((left + (x + 0.5) * pixel, bottom + (y + 0.5) * pixel, depth.ravel()[block]))
        # Keep the three-component transforms local to each camera worker.
        world = np.einsum("ij,jk->ik", camera_points, basis)
        surface_coordinates[start:start + len(block)] = _cap_coordinates(world - geometry.origin)
        neck_height = np.einsum("ij,j->i", world, geometry.neck_plane[:3]) + geometry.neck_plane[3]
        skin_surface[start:start + len(block)] = neck_height > 1e-7
    skin = np.stack((gray, gray, gray, inside_head.astype(np.uint8) * 255), axis=-1)
    if not skin_surface.all():
        pixels = pixels[skin_surface]
        surface_coordinates = surface_coordinates[skin_surface]
    return _HeadImage(skin, pixels, surface_coordinates, extent)


@lru_cache(maxsize=32)
def _camera_sensors(view: str, location_bytes: bytes) -> tuple[np.ndarray, np.ndarray]:
    """Check visibility at each sensor's exact location, independent of print resolution."""
    geometry = _geometry()
    camera = _camera(view).T
    sensors = np.frombuffer(location_bytes, np.float64).reshape(-1, 3) @ camera
    triangles = (geometry.vertices @ camera)[geometry.faces]
    a, b, c = triangles.transpose(1, 0, 2)
    ab, ac = b - a, c - a
    determinant = ab[:, 0] * ac[:, 1] - ab[:, 1] * ac[:, 0]
    # For each front-facing triangle, only test electrodes in its horizontal
    # span. A dense cap still needs a small number of point/triangle tests.
    ordered = np.argsort(sensors[:, 0])
    xs = sensors[ordered, 0]
    left = np.searchsorted(xs, np.minimum(np.minimum(a[:, 0], b[:, 0]), c[:, 0]) - 1e-12)
    right = np.searchsorted(xs, np.maximum(np.maximum(a[:, 0], b[:, 0]), c[:, 0]) + 1e-12)
    counts = np.where(determinant > 0, right - left, 0)
    faces = np.repeat(np.arange(len(triangles)), counts)
    offsets = np.cumsum(counts) - counts
    candidates = ordered[left[faces] + np.arange(len(faces)) - offsets[faces]]
    dx, dy = (sensors[candidates, :2] - a[faces, :2]).T
    u = (dx * ac[faces, 1] - dy * ac[faces, 0]) / determinant[faces]
    v = (dy * ab[faces, 0] - dx * ab[faces, 1]) / determinant[faces]
    depth = a[faces, 2] + u * ab[faces, 2] + v * ac[faces, 2]
    hidden = (u >= -1e-10) & (v >= -1e-10) & (u + v <= 1 + 1e-10) & (depth > sensors[candidates, 2] + 1e-8)
    visible = np.ones(len(sensors), dtype=bool)
    visible[candidates[hidden]] = False
    return sensors[:, :2], visible


def _sampling_weights(coordinates, points):
    try:
        return natural_neighbor_weights(coordinates, points)
    except QhullError as exc:
        raise InsufficientSensorCoverageError(finite_sensor_count=len(coordinates), reason="degenerate cap coverage") from exc


def _cap_light(x, y):
    angle = np.hypot(x, y)
    return np.clip(0.94 * np.cos(angle) - 0.34 * x * np.sinc(angle / np.pi), 0, 1)


def _scalp_pigment(cmap, norm, values, lighting):
    """Shade palette hues by a soft crown light fixed in head coordinates."""
    rgba = cmap(norm(values), bytes=True)
    rgb = rgba[:, :3]
    peak = np.maximum(np.maximum(rgb[:, 0], rgb[:, 1]), rgb[:, 2])
    chroma = peak - np.minimum(np.minimum(rgb[:, 0], rgb[:, 1]), rgb[:, 2])
    saturation = chroma / np.maximum(peak, 1)
    # Achromatic colors retain their exact luminance, including white below
    # a Z threshold. Covered pixels are opaque, avoiding depth-sorting seams.
    material = 1 - 0.22 * (1 - lighting) * saturation
    for channel in rgb.T:
        channel[:] = np.rint(channel * material)
    return rgba


@lru_cache(maxsize=16)
def _head_atlas(lowest_sensor_angle: float) -> tuple[np.ndarray, np.ndarray]:
    geometry = _geometry()
    cap = _cap_coordinates(geometry.vertices - geometry.origin)
    vertex_angle = np.linalg.norm(cap, axis=1)
    # Keep the artificial neck closure neutral, including when a dense cap
    # extends to the jaw. Its triangles can cross the projection's south pole.
    skin_vertex = geometry.vertices @ geometry.neck_plane[:3] + geometry.neck_plane[3] > 1e-7
    scalp_faces = geometry.faces[np.any(vertex_angle[geometry.faces] <= lowest_sensor_angle, axis=1)
                                & skin_vertex[geometry.faces].any(axis=1)]
    # An especially inferior custom montage can reach the patch directly
    # under the chin, where the polar atlas has no unique longitude. A face
    # spanning over half the texture would sample the opposite side of the
    # scalp; keep these singular triangles neutral in the rotating view.
    inferior = np.all(vertex_angle[scalp_faces] > np.pi / 2, axis=1)
    corners = cap[scalp_faces[inferior]]
    spans_pole = np.any(np.sum((corners - np.roll(corners, 1, axis=1)) ** 2, axis=2) > np.pi ** 2, axis=1)
    inferior[inferior] = spans_pole
    scalp_faces = scalp_faces[~inferior]
    return (cap / (2 * np.pi) + 0.5).astype(np.float32), scalp_faces


@dataclass(frozen=True)
class _ScalpField:
    low: np.ndarray
    high: np.ndarray
    step: np.ndarray
    width: int
    weights: csr_matrix
    smooth_cells: np.ndarray
    possible_cells: np.ndarray


@lru_cache(maxsize=4)
def _scalp_field(coordinate_bytes: bytes) -> _ScalpField:
    """Sample a common Sibson field at a resolution set by the electrode spacing."""
    xy = np.frombuffer(coordinate_bytes, np.float64).reshape(-1, 2)
    distances = cKDTree(xy).query(xy, k=2)[0][:, 1]
    spacing = np.median(distances) / 16
    low, high = xy.min(axis=0), xy.max(axis=0)
    nx, ny = np.clip(np.ceil((high - low) / spacing), 2, 256).astype(int)
    x = np.linspace(low[0], high[0], nx + 1)
    y = np.linspace(low[1], high[1], ny + 1)
    step = (high - low) / [nx, ny]
    knots = np.stack(np.meshgrid(x, y), axis=-1).reshape(-1, 2)

    # Entirely interior cells can interpolate our exact scalar samples. Near
    # oblique hull edges the Sibson weights can change on a much finer scale
    # than the electrode spacing. Evaluate those display pixels directly.
    centre_x, centre_y = np.meshgrid(x[:-1] + step[0] / 2, y[:-1] + step[1] / 2)
    smooth = np.ones((ny, nx), dtype=bool)
    possible = smooth.copy()
    try:
        equations = ConvexHull(xy).equations
    except QhullError as exc:
        raise InsufficientSensorCoverageError(finite_sensor_count=len(xy), reason="degenerate cap coverage") from exc
    for a, b, offset in equations:
        centre = a * centre_x + b * centre_y + offset
        radius = (abs(a) * step[0] + abs(b) * step[1]) / 2
        smooth &= centre < -radius - 2 * max(step)
        possible &= centre <= radius + 1e-12
    # An electrode can land anywhere within a texel. Direct evaluation keeps
    # measured site values exact, whatever the density or asymmetry of the cap.
    col, row = np.minimum(((xy - low) / step).astype(int), [nx - 1, ny - 1]).T
    smooth[row, col] = False
    # A very steep transition can also occur inside an irregular or dense
    # cap. Check each remaining cell against genuine Sibson weights at its
    # centre. Half the L1 difference is the worst scalar error there for
    # *any* input with a unit data range.
    row, col = np.nonzero(smooth)
    centres = np.column_stack((centre_x[row, col], centre_y[row, col]))
    sampled = _sampling_weights(xy, np.vstack((knots, centres)))
    weights = sampled[:len(knots)]
    corners = row * (nx + 1) + col
    mean = (weights[corners] + weights[corners + 1]
            + weights[corners + nx + 1] + weights[corners + nx + 2]) * 0.25
    error = np.asarray(abs(sampled[len(knots):] - mean).sum(axis=1)).ravel() * 0.5
    refine = error > 0.005
    smooth[row[refine], col[refine]] = False
    return _ScalpField(low, high, step, nx + 1, weights, smooth, possible)


@dataclass(frozen=True)
class _DisplaySamples:
    pixels: np.ndarray
    cells: np.ndarray
    frac_x: np.ndarray
    frac_y: np.ndarray
    boundary: csr_matrix
    lighting: np.ndarray


def _display_samples(coordinate_bytes, points, pixels):
    """Locate supported pixels and retain exact weights in the flagged cells."""
    sites = np.frombuffer(coordinate_bytes, np.float64).reshape(-1, 2)
    field = _scalp_field(coordinate_bytes)
    x, y = points.T
    # Float64 is required here even for float32 fixed-view coordinates: tiny
    # coordinate errors can put a query on the wrong side of a hull pixel.
    ix = (x - field.low[0]) / field.step[0]
    iy = (y - field.low[1]) / field.step[1]
    px = np.clip(ix.astype(np.int32), 0, field.smooth_cells.shape[1] - 1)
    py = np.clip(iy.astype(np.int32), 0, field.smooth_cells.shape[0] - 1)
    bbox = ((x >= field.low[0]) & (x <= field.high[0]) & (y >= field.low[1]) & (y <= field.high[1]))
    inside = bbox & field.smooth_cells[py, px]
    smooth = np.flatnonzero(inside)
    edges = np.flatnonzero(bbox & ~inside & field.possible_cells[py, px])
    boundary = _sampling_weights(sites, points[edges])
    active = np.flatnonzero(np.diff(boundary.indptr))
    indices = np.r_[smooth, edges[active]]
    px, py = px[smooth], py[smooth]
    frac_x, frac_y = ix[smooth] - px, iy[smooth] - py
    cells = (py * field.width + px).astype(np.int32)
    return _DisplaySamples(pixels[indices], cells, frac_x, frac_y, boundary[active], _cap_light(x[indices], y[indices]))


@lru_cache(maxsize=2)
def _texture_samples(coordinate_bytes: bytes, size: int):
    coordinates = np.frombuffer(coordinate_bytes, np.float64).reshape(-1, 2)
    axis = (np.arange(size) + 0.5) * (2 * np.pi / size) - np.pi
    x0, y0 = np.searchsorted(axis, coordinates.min(axis=0))
    x1, y1 = np.searchsorted(axis, coordinates.max(axis=0), side="right")
    xy = np.stack(np.meshgrid(axis[x0:x1], axis[y0:y1]), axis=-1).reshape(-1, 2)
    pixels = np.arange(x0, x1, dtype=np.int32) + size * np.arange(y0, y1, dtype=np.int32)[:, None]
    return _display_samples(coordinate_bytes, xy, pixels.ravel())


@lru_cache(maxsize=2)
def _fixed_samples(coordinate_bytes: bytes, view: str, width: int):
    head = _render_head(view, width)
    return _display_samples(coordinate_bytes, head.cap_coordinates, head.pixel_indices)


def _display_values(field, samples, data):
    grid = field.weights @ data
    step = field.width
    values = np.empty(len(samples.pixels))
    cells = samples.cells
    for start in range(0, len(cells), _PAINT_BLOCK_SIZE):
        block = slice(start, min(start + _PAINT_BLOCK_SIZE, len(cells)))
        i = cells[block]
        fx, fy = samples.frac_x[block], samples.frac_y[block]
        lower = grid[i] + (grid[i + 1] - grid[i]) * fx
        upper = grid[i + step] + (grid[i + step + 1] - grid[i + step]) * fx
        values[block] = lower + (upper - lower) * fy
    values[len(cells):] = samples.boundary @ data
    return values


def _paint(rgba, field, samples, data, cmap, norm):
    values = _display_values(field, samples, data)
    # Determine automatic limits from the whole supported field before blocking.
    if not norm.scaled() and len(values):
        norm.autoscale_None(values)
    image = rgba.reshape(-1, 4)
    for start in range(0, len(values), _PAINT_BLOCK_SIZE):
        block = slice(start, start + _PAINT_BLOCK_SIZE)
        image[samples.pixels[block]] = _scalp_pigment(cmap, norm, values[block], samples.lighting[block])


def build_scalp_surface_scene(data, info, *, cmap, norm) -> ScalpSurfaceScene:
    """Prepare a GUI-free scene using the exporter's finite values, hull and color mapping."""
    geometry = _geometry()
    projection = _sensor_projection(info)
    coordinates = projection.cap_coordinates
    uv, scalp_faces = _head_atlas(float(np.linalg.norm(coordinates, axis=1).max()))
    size = 1024
    rgba = np.zeros((size, size, 4), dtype=np.uint8)
    key = coordinates.tobytes()
    _paint(rgba, _scalp_field(key), _texture_samples(key, size), data, cmap, norm)
    return ScalpSurfaceScene(geometry.vertices, geometry.faces, scalp_faces, geometry.origin, uv, rgba,
                             projection.locations)


def _raster_width(ax):
    # Bucket similarly sized print panels so the two camera rasters can be
    # reused across conditions and metrics at publication resolution.
    return int(np.clip(np.ceil(ax.get_window_extent().width / 128), 1, 16)) * 128


def prepare_scalp_surface_pair(info, front_ax, back_ax) -> None:
    """Prepare two independent camera rasters; all figure access stays on the caller."""
    key = _sensor_projection(info).cap_coordinates.tobytes()
    front_width, back_width = _raster_width(front_ax), _raster_width(back_ax)
    _scalp_field(key)  # Both cameras reuse this exact finite montage.
    with ThreadPoolExecutor(max_workers=1) as executor:
        back = executor.submit(_fixed_samples, key, "back", back_width)
        _fixed_samples(key, "front", front_width)
        back.result()


def draw_scalp_surface(ax, data, info, *, view, cmap, norm) -> None:
    """Draw one labelled-by-caller view from already aligned finite montage values."""
    projection = _sensor_projection(info)
    width = _raster_width(ax)
    head = _render_head(view, width)
    rgba = head.skin.copy()
    key = projection.cap_coordinates.tobytes()
    _paint(rgba, _scalp_field(key), _fixed_samples(key, view, width), data, cmap, norm)
    ax.imshow(rgba, origin="lower", extent=head.extent, interpolation="none", aspect="equal")
    xy, visible = _camera_sensors(view, projection.locations.tobytes())
    ax.scatter(xy[visible, 0], xy[visible, 1], s=2.5, c="#171717", edgecolors="none", clip_on=True)
    ax.set_axis_off()
