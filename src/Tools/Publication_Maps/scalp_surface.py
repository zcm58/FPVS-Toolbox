"""Orthographic views of BioSemi64 sensor values on MNE's packaged template head.

Data are linearly interpolated in azimuthal-equidistant cap coordinates, inside
the convex hull of the finite electrodes. The head supplies the drawing surface
and anatomical landmarks. Its shape is shared across subjects and conditions.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import mne
import numpy as np
from scipy.interpolate import LinearNDInterpolator
from scipy.spatial import QhullError

from Tools.Publication_Maps.scalp_io import InsufficientSensorCoverageError, biosemi64_info


@dataclass(frozen=True)
class _ScalpGeometry:
    vertices: np.ndarray
    faces: np.ndarray
    origin: np.ndarray
    cap_coordinates: np.ndarray
    sensor_locations: np.ndarray


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
    sensor_xy: np.ndarray
    visible: np.ndarray
    extent: tuple[float, float, float, float]


def _cap_coordinates(vectors: np.ndarray) -> np.ndarray:
    """Project a direction to the plane by its angular distance from the crown."""
    xy = vectors[:, :2]
    radius = np.linalg.norm(xy, axis=1)
    polar_angle = np.arctan2(radius, vectors[:, 2])
    coordinates = xy * np.divide(polar_angle, radius, out=np.zeros_like(radius), where=radius > 0)[:, None]
    coordinates[(radius == 0) & (vectors[:, 2] < 0), 0] = np.pi
    return coordinates


def _radial_sensor_locations(
    vertices: np.ndarray, faces: np.ndarray, origin: np.ndarray, directions: np.ndarray,
) -> np.ndarray:
    """Intersect each cap direction with the first outward crossing of the head."""
    a, b, c = vertices[faces].transpose(1, 0, 2)
    edge1, edge2 = b - a, c - a
    offset = origin - a
    cross = np.cross(offset, edge1)
    numerator = np.einsum("ij,ij->i", edge2, cross)
    positions = []
    for direction in directions:
        perpendicular = np.cross(direction, edge2)
        det = np.einsum("ij,ij->i", edge1, perpendicular)
        reciprocal = np.divide(1, det, where=np.abs(det) > 1e-15, out=np.zeros_like(det))
        u = np.einsum("ij,ij->i", offset, perpendicular) * reciprocal
        v = (cross @ direction) * reciprocal
        distance = numerator * reciprocal
        hits = (u >= -1e-10) & (v >= -1e-10) & (u + v <= 1 + 1e-10) & (distance > 0)
        if not hits.any():
            raise ValueError("A BioSemi64 electrode could not be placed on the template scalp.")
        positions.append(origin + direction * distance[hits].min())
    return np.asarray(positions)


@lru_cache(maxsize=1)
def _geometry() -> _ScalpGeometry:
    template = Path(mne.__file__).parent / "data" / "fsaverage"
    try:
        surface, = mne.read_bem_surfaces(template / "fsaverage-head.fif", verbose=False)
        transform = mne.read_trans(template / "fsaverage-trans.fif", verbose=False)
    except OSError as exc:
        raise ValueError("The MNE template scalp for 3D maps is missing or unreadable. Repair the Toolbox installation.") from exc
    if surface["coord_frame"] != transform["to"]:
        raise ValueError("The template scalp and head transform have incompatible coordinates.")
    vertices = mne.transforms.apply_trans(mne.transforms.invert_transform(transform), surface["rr"])
    faces = surface["tris"]
    montage = np.asarray([ch["loc"][:3] for ch in biosemi64_info()["chs"]])
    # BioSemi's standard montage is spherical. Fit its centre once to all
    # 64 channels so missing data can never move the projection.
    origin = np.linalg.lstsq(
        np.column_stack((2 * montage, np.ones(len(montage)))),
        np.sum(montage**2, axis=1), rcond=None,
    )[0][:3]
    directions = montage - origin
    directions /= np.linalg.norm(directions, axis=1)[:, None]
    return _ScalpGeometry(
        vertices, faces, origin, _cap_coordinates(directions),
        _radial_sensor_locations(vertices, faces, origin, directions),
    )


def _camera(view: str) -> np.ndarray:
    if view not in ("front", "back"):
        raise ValueError(f"Unknown 3D scalp view: {view!r}.")
    sign = 1 if view == "front" else -1
    # In head coordinates +X is the participant's right and +Y is anterior.
    angle = np.deg2rad(28)
    return np.array([[-sign, 0, 0], [0, -sign * np.sin(angle), np.cos(angle)],
                     [0, sign * np.cos(angle), np.sin(angle)]])


@lru_cache(maxsize=2)
def _render_head(view: str, width: int) -> _HeadImage:
    """Rasterize static anatomy with a depth buffer shared by all data panels."""
    geometry = _geometry()
    basis = _camera(view)
    camera_vertices = geometry.vertices @ basis.T
    # Frame both complete template views at the same physical scale.
    left, right, bottom, top = -0.090, 0.090, -0.141, 0.146
    pixel = (right - left) / width
    height = int(np.ceil((top - bottom) / pixel))
    extent = (left, right, bottom, bottom + height * pixel)
    depth = np.full((height, width), -np.inf)
    gray = np.zeros((height, width), dtype=np.uint8)
    triangles = camera_vertices[geometry.faces]
    face_normals = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
    normals = np.zeros_like(camera_vertices)
    for column in geometry.faces.T:
        np.add.at(normals, column, face_normals)
    normals /= np.maximum(np.linalg.norm(normals, axis=1), 1e-15)[:, None]
    light = np.array([-0.42, 0.53, 0.74])
    brightness = 157 + 79 * np.maximum(0, normals @ light)
    # Triangle-local barycentric interpolation avoids a graphics backend and
    # resolves projecting ears, nose and hidden scalp in image depth order.
    screen = (camera_vertices[:, :2] - [left, bottom]) / pixel - 0.5
    for face in geometry.faces[face_normals[:, 2] > 0]:
        a, b, c = screen[face]
        corners = screen[face]
        x0, y0 = np.maximum(np.ceil(corners.min(axis=0)).astype(int), 0)
        x1, y1 = np.minimum(np.floor(corners.max(axis=0)).astype(int) + 1, [width, height])
        if x1 <= x0 or y1 <= y0:
            continue
        y, x = np.ogrid[y0:y1, x0:x1]
        ab, ac = b - a, c - a
        det = ab[0] * ac[1] - ab[1] * ac[0]
        u = ((x - a[0]) * ac[1] - (y - a[1]) * ac[0]) / det
        v = (ab[0] * (y - a[1]) - ab[1] * (x - a[0])) / det
        z_a, z_b, z_c = camera_vertices[face, 2]
        z = z_a + u * (z_b - z_a) + v * (z_c - z_a)
        local_depth = depth[y0:y1, x0:x1]
        mask = (u >= -1e-10) & (v >= -1e-10) & (u + v <= 1 + 1e-10) & (z > local_depth)
        local_depth[mask] = z[mask]
        g_a, g_b, g_c = brightness[face]
        gray[y0:y1, x0:x1][mask] = (g_a + u[mask] * (g_b - g_a) + v[mask] * (g_c - g_a))
    y, x = np.nonzero(np.isfinite(depth))
    world = np.column_stack((left + (x + 0.5) * pixel, bottom + (y + 0.5) * pixel, depth[y, x])) @ basis
    surface_coordinates = _cap_coordinates(world - geometry.origin)
    skin = np.empty((height, width, 4), dtype=np.uint8)
    skin[:, :, :3] = gray[:, :, None]
    skin[:, :, 3] = np.where(np.isfinite(depth), 255, 0)
    sensors = geometry.sensor_locations @ basis.T
    ix = np.clip(((sensors[:, 0] - left) / pixel).astype(int), 0, width - 1)
    iy = np.clip(((sensors[:, 1] - bottom) / pixel).astype(int), 0, height - 1)
    # Only the front surface can show a dot. One pixel of tolerance handles
    # the difference between an exact projected location and a pixel centre.
    depth_at_sensor = depth[iy, ix]
    visible = np.isfinite(depth_at_sensor) & (sensors[:, 2] + 2 * pixel >= depth_at_sensor)
    return _HeadImage(skin, (y * width + x).astype(np.int32), surface_coordinates.astype(np.float32),
                      sensors[:, :2], visible, extent)


def _interpolate(coordinates: np.ndarray, values: np.ndarray, points: np.ndarray) -> np.ndarray:
    try:
        return LinearNDInterpolator(coordinates, values)(points)
    except QhullError as exc:
        raise InsufficientSensorCoverageError(finite_sensor_count=len(values), reason="degenerate cap coverage") from exc


def _sensor_indices(info) -> np.ndarray:
    names = biosemi64_info().ch_names
    return np.asarray([names.index(name) for name in info.ch_names], dtype=int)


@lru_cache(maxsize=1)
def _head_atlas() -> tuple[np.ndarray, np.ndarray]:
    geometry = _geometry()
    cap = _cap_coordinates(geometry.vertices - geometry.origin)
    vertex_angle = np.linalg.norm(cap, axis=1)
    lowest_sensor_angle = np.linalg.norm(geometry.cap_coordinates, axis=1).max()
    # The cone below the lowest BioSemi parallel is convex. A face wholly
    # inside it cannot carry sensor data. Omitting those faces also prevents
    # UV interpolation across the south-pole singularity from painting the chin.
    scalp_faces = geometry.faces[np.any(vertex_angle[geometry.faces] <= lowest_sensor_angle, axis=1)]
    return (cap / (2 * np.pi) + 0.5).astype(np.float32), scalp_faces


def build_scalp_surface_scene(data, info, *, cmap, norm) -> ScalpSurfaceScene:
    """Prepare a GUI-free scene using the exporter's finite values, hull and color mapping."""
    geometry = _geometry()
    indices = _sensor_indices(info)
    uv, scalp_faces = _head_atlas()
    size = 1024
    axis = (np.arange(size) + 0.5) * (2 * np.pi / size) - np.pi
    # Bound sampling to the finite electrodes' rectangle. The interpolator
    # returns NaN for points within this rectangle but outside their convex hull.
    coordinates = geometry.cap_coordinates[indices]
    x0, y0 = np.searchsorted(axis, coordinates.min(axis=0))
    x1, y1 = np.searchsorted(axis, coordinates.max(axis=0), side="right")
    x, y = np.meshgrid(axis[x0:x1], axis[y0:y1])
    values = _interpolate(coordinates, data, np.stack((x, y), axis=-1))
    rgba = np.zeros((size, size, 4), dtype=np.uint8)
    supported = np.isfinite(values)
    rgba[y0:y1, x0:x1][supported] = cmap(norm(values[supported]), bytes=True)
    return ScalpSurfaceScene(geometry.vertices, geometry.faces, scalp_faces, geometry.origin, uv, rgba,
                             geometry.sensor_locations[indices])


def draw_scalp_surface(ax, data, info, *, view, cmap, norm) -> None:
    """Draw one labelled-by-caller view from already aligned finite montage values."""
    indices = _sensor_indices(info)
    # Round upwards so similarly sized panels can reuse the geometry. A 3D
    # tile at standard double-column placement is at most half a panel wide.
    width = int(np.clip(np.ceil(ax.get_window_extent().width / 128), 1, 16)) * 128
    head = _render_head(view, width)
    values = _interpolate(_geometry().cap_coordinates[indices], data, head.cap_coordinates)
    supported = np.isfinite(values)
    rgba = head.skin.copy()
    rgba.reshape(-1, 4)[head.pixel_indices[supported]] = cmap(norm(values[supported]), bytes=True)
    ax.imshow(rgba, origin="lower", extent=head.extent, interpolation="none", aspect="equal")
    xy = head.sensor_xy[indices][head.visible[indices]]
    ax.scatter(xy[:, 0], xy[:, 1], s=2.5, c="#252525", edgecolors="white", linewidths=0.22, clip_on=True)
    ax.set_axis_off()
