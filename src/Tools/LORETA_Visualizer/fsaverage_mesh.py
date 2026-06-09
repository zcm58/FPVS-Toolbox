"""fsaverage mesh loading for the LORETA visualizer.

The fsaverage template is fetched or located through MNE in the FPVS Toolbox
root-local cache by default. Do not bundle fsaverage data into active source,
docs, quarantine paths, or package data.
"""

from __future__ import annotations

import logging
import ssl
from dataclasses import dataclass
from pathlib import Path
from urllib.error import URLError

import numpy as np

from Tools.LORETA_Visualizer.fsaverage_cache import (
    candidate_fsaverage_dirs,
    ensure_allowed_fsaverage_dir,
    fetch_fsaverage_subjects_dir,
    preferred_fsaverage_dirs,
)
from Tools.LORETA_Visualizer.synthetic_brain import BrainHemisphereMesh, BrainMesh
from Tools.LORETA_Visualizer.transforms import COORDINATE_SPACE_FSAVERAGE, MeshDisplayTransform

logger = logging.getLogger(__name__)

DEFAULT_SURFACE = "pial"
DEFAULT_PUBLICATION_SPLIT_SURFACE = "inflated"
DEFAULT_MAX_TRIANGLES = 120000
SURFACE_CHOICES = ("pial", "inflated", "white")


class FsaverageMeshError(RuntimeError):
    """Raised when an fsaverage surface cannot be loaded safely."""


@dataclass(frozen=True)
class FsaverageMeshResult:
    """Loaded fsaverage mesh plus status details for the UI."""

    mesh: BrainMesh
    fsaverage_dir: Path
    surface: str
    triangle_count: int
    source_label: str
    split_surface: str = DEFAULT_SURFACE
    split_shading_source: str | None = None


def load_fsaverage_brain_mesh(
    *,
    surface: str = DEFAULT_SURFACE,
    max_triangles: int = DEFAULT_MAX_TRIANGLES,
    allow_fetch: bool = True,
) -> FsaverageMeshResult:
    """Load a combined left/right fsaverage cortical surface mesh."""
    surface = _validate_surface(surface)
    fsaverage_dir = _resolve_fsaverage_dir(allow_fetch=allow_fetch)
    surf_dir = fsaverage_dir / "surf"
    left_path = surf_dir / f"lh.{surface}"
    right_path = surf_dir / f"rh.{surface}"
    missing = [str(path) for path in (left_path, right_path) if not path.is_file()]
    if missing:
        raise FsaverageMeshError(f"fsaverage surface files are missing: {', '.join(missing)}")

    try:
        import mne

        left_vertices, left_faces, right_vertices, right_faces = _read_surface_pair(mne, surf_dir, surface)
    except (OSError, RuntimeError, ValueError, ImportError, ModuleNotFoundError) as exc:
        raise FsaverageMeshError(f"Unable to read fsaverage {surface} surface: {exc}") from exc

    native_points, faces = _combine_hemispheres(left_vertices, left_faces, right_vertices, right_faces)
    display_transform = _display_transform(native_points)
    points = display_transform.to_display_points(native_points)
    left_shade_values, right_shade_values, split_shading_source = _read_publication_shading(
        surf_dir,
        left_vertex_count=len(left_vertices),
        right_vertex_count=len(right_vertices),
    )
    split_surface = surface
    split_left_vertices = left_vertices
    split_right_vertices = right_vertices
    if surface != DEFAULT_PUBLICATION_SPLIT_SURFACE:
        try:
            split_left_vertices, split_right_vertices, split_surface = _read_publication_split_surface(
                mne,
                surf_dir,
                left_reference_vertices=left_vertices,
                left_reference_faces=left_faces,
                right_reference_vertices=right_vertices,
                right_reference_faces=right_faces,
            )
        except FsaverageMeshError as exc:
            logger.warning("fsaverage_publication_split_surface_unavailable", extra={"error": str(exc)})

    left_hemisphere = _make_split_hemisphere(
        display_transform=display_transform,
        display_vertices=split_left_vertices,
        projection_vertices=left_vertices,
        faces=left_faces,
        shade_values=left_shade_values,
        shade_source=split_shading_source,
        surface=split_surface,
    )
    right_hemisphere = _make_split_hemisphere(
        display_transform=display_transform,
        display_vertices=split_right_vertices,
        projection_vertices=right_vertices,
        faces=right_faces,
        shade_values=right_shade_values,
        shade_source=split_shading_source,
        surface=split_surface,
    )
    mesh = _decimate_surface(
        points,
        faces,
        max_triangles=max_triangles,
        display_transform=display_transform,
        left_hemisphere=left_hemisphere,
        right_hemisphere=right_hemisphere,
    )
    return FsaverageMeshResult(
        mesh=mesh,
        fsaverage_dir=fsaverage_dir,
        surface=surface,
        triangle_count=len(mesh.faces) // 4,
        source_label=f"fsaverage {surface}",
        split_surface=split_surface,
        split_shading_source=split_shading_source,
    )


def _validate_surface(surface: str) -> str:
    cleaned = str(surface).strip().lower()
    if cleaned not in SURFACE_CHOICES:
        raise FsaverageMeshError(f"Unsupported fsaverage surface: {surface!r}")
    return cleaned


def _read_surface_pair(
    mne: object,
    surf_dir: Path,
    surface: str,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    left_vertices, left_faces = mne.read_surface(surf_dir / f"lh.{surface}", verbose=False)
    right_vertices, right_faces = mne.read_surface(surf_dir / f"rh.{surface}", verbose=False)
    return (
        np.asarray(left_vertices, dtype=float),
        np.asarray(left_faces, dtype=np.int64),
        np.asarray(right_vertices, dtype=float),
        np.asarray(right_faces, dtype=np.int64),
    )


def _read_publication_split_surface(
    mne: object,
    surf_dir: Path,
    *,
    left_reference_vertices: np.ndarray,
    left_reference_faces: np.ndarray,
    right_reference_vertices: np.ndarray,
    right_reference_faces: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, str]:
    surface = DEFAULT_PUBLICATION_SPLIT_SURFACE
    left_path = surf_dir / f"lh.{surface}"
    right_path = surf_dir / f"rh.{surface}"
    missing = [str(path) for path in (left_path, right_path) if not path.is_file()]
    if missing:
        raise FsaverageMeshError(f"publication split surface files are missing: {', '.join(missing)}")
    left_vertices, left_faces, right_vertices, right_faces = _read_surface_pair(mne, surf_dir, surface)
    if not _surfaces_share_topology(left_vertices, left_faces, left_reference_vertices, left_reference_faces):
        raise FsaverageMeshError("left inflated split surface does not match pial topology.")
    if not _surfaces_share_topology(right_vertices, right_faces, right_reference_vertices, right_reference_faces):
        raise FsaverageMeshError("right inflated split surface does not match pial topology.")
    return left_vertices, right_vertices, surface


def _read_publication_shading(
    surf_dir: Path,
    *,
    left_vertex_count: int,
    right_vertex_count: int,
) -> tuple[np.ndarray | None, np.ndarray | None, str | None]:
    for morph_name in ("curv", "sulc"):
        left_path = surf_dir / f"lh.{morph_name}"
        right_path = surf_dir / f"rh.{morph_name}"
        if not left_path.is_file() or not right_path.is_file():
            continue
        try:
            from nibabel.freesurfer.io import read_morph_data

            left_values = np.asarray(read_morph_data(str(left_path)), dtype=float)
            right_values = np.asarray(read_morph_data(str(right_path)), dtype=float)
        except (OSError, RuntimeError, ValueError, ImportError, ModuleNotFoundError) as exc:
            logger.warning(
                "fsaverage_publication_shading_read_failed",
                extra={"morph_name": morph_name, "error": str(exc)},
            )
            continue
        if len(left_values) != left_vertex_count or len(right_values) != right_vertex_count:
            logger.warning(
                "fsaverage_publication_shading_size_mismatch",
                extra={
                    "morph_name": morph_name,
                    "left_values": len(left_values),
                    "left_vertices": left_vertex_count,
                    "right_values": len(right_values),
                    "right_vertices": right_vertex_count,
                },
            )
            continue
        return (
            _normalize_shading_values(left_values, morph_name=morph_name),
            _normalize_shading_values(right_values, morph_name=morph_name),
            morph_name,
        )
    return None, None, None


def _normalize_shading_values(values: np.ndarray, *, morph_name: str) -> np.ndarray:
    shade = np.asarray(values, dtype=float).reshape(-1)
    finite = shade[np.isfinite(shade)]
    if len(finite) == 0:
        return np.full(len(shade), 0.55, dtype=float)
    lower, upper = np.percentile(finite, [2.0, 98.0])
    if upper <= lower:
        normalized = np.full(len(shade), 0.55, dtype=float)
    else:
        normalized = np.clip((shade - float(lower)) / (float(upper) - float(lower)), 0.0, 1.0)
        normalized = np.where(np.isfinite(normalized), normalized, 0.55)
    if morph_name == "sulc":
        normalized = 1.0 - normalized
    return normalized.astype(float)


def _surfaces_share_topology(
    vertices: np.ndarray,
    faces: np.ndarray,
    reference_vertices: np.ndarray,
    reference_faces: np.ndarray,
) -> bool:
    return (
        len(vertices) == len(reference_vertices)
        and np.asarray(faces, dtype=np.int64).shape == np.asarray(reference_faces, dtype=np.int64).shape
        and np.array_equal(np.asarray(faces, dtype=np.int64), np.asarray(reference_faces, dtype=np.int64))
    )


def _resolve_fsaverage_dir(*, allow_fetch: bool) -> Path:
    try:
        candidates = preferred_fsaverage_dirs() if allow_fetch else candidate_fsaverage_dirs()
    except ValueError as exc:
        raise FsaverageMeshError(str(exc)) from exc
    for candidate in candidates:
        if candidate.is_dir() and (not allow_fetch or _has_default_surface_pair(candidate)):
            try:
                return ensure_allowed_fsaverage_dir(candidate)
            except ValueError as exc:
                raise FsaverageMeshError(str(exc)) from exc

    if not allow_fetch:
        raise FsaverageMeshError("fsaverage is not available and fetching is disabled.")

    try:
        subjects_dir = fetch_fsaverage_subjects_dir()
    except ValueError as exc:
        raise FsaverageMeshError(str(exc)) from exc
    try:
        from mne.datasets import fetch_fsaverage

        fs_dir = Path(fetch_fsaverage(subjects_dir=subjects_dir, verbose=False))
    except (OSError, RuntimeError, ValueError, ImportError, ModuleNotFoundError, URLError, ssl.SSLError, TimeoutError) as exc:
        raise FsaverageMeshError(f"Unable to fetch fsaverage through MNE: {exc}") from exc
    try:
        return ensure_allowed_fsaverage_dir(fs_dir)
    except ValueError as exc:
        raise FsaverageMeshError(str(exc)) from exc


def _has_default_surface_pair(fsaverage_dir: Path) -> bool:
    surf_dir = fsaverage_dir / "surf"
    return (surf_dir / f"lh.{DEFAULT_SURFACE}").is_file() and (surf_dir / f"rh.{DEFAULT_SURFACE}").is_file()


def _combine_hemispheres(
    left_vertices: np.ndarray,
    left_faces: np.ndarray,
    right_vertices: np.ndarray,
    right_faces: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    left_vertices = np.asarray(left_vertices, dtype=float)
    right_vertices = np.asarray(right_vertices, dtype=float)
    left_faces = np.asarray(left_faces, dtype=np.int64)
    right_faces = np.asarray(right_faces, dtype=np.int64)
    points = np.vstack((left_vertices, right_vertices))
    faces = np.vstack((left_faces, right_faces + len(left_vertices)))
    return points, faces


def _decimate_surface(
    points: np.ndarray,
    faces: np.ndarray,
    *,
    max_triangles: int,
    display_transform: MeshDisplayTransform,
    left_hemisphere: BrainHemisphereMesh | None = None,
    right_hemisphere: BrainHemisphereMesh | None = None,
) -> BrainMesh:
    if max_triangles <= 0 or len(faces) <= max_triangles:
        return BrainMesh(
            points=points,
            faces=_faces_to_vtk(faces),
            display_transform=display_transform,
            left_hemisphere=left_hemisphere,
            right_hemisphere=right_hemisphere,
        )
    try:
        import pyvista as pv

        surface = pv.PolyData(points, _faces_to_vtk(faces))
        target_reduction = 1.0 - (max_triangles / max(len(faces), 1))
        decimated = surface.decimate_pro(
            target_reduction,
            preserve_topology=True,
            boundary_vertex_deletion=False,
            splitting=False,
        )
        decimated = decimated.triangulate()
        decimated_faces = _vtk_faces_to_triangles(np.asarray(decimated.faces, dtype=np.int64))
        logger.debug(
            "fsaverage_mesh_decimated",
            extra={"original_triangles": len(faces), "triangles": len(decimated_faces)},
        )
        return BrainMesh(
            points=np.asarray(decimated.points, dtype=float),
            faces=_faces_to_vtk(decimated_faces),
            display_transform=display_transform,
            left_hemisphere=left_hemisphere,
            right_hemisphere=right_hemisphere,
        )
    except (AttributeError, RuntimeError, TypeError, ValueError, ImportError, ModuleNotFoundError) as exc:
        logger.warning(
            "fsaverage_mesh_decimation_failed",
            extra={"error": str(exc), "original_triangles": len(faces)},
        )
        return BrainMesh(
            points=points,
            faces=_faces_to_vtk(faces),
            display_transform=display_transform,
            left_hemisphere=left_hemisphere,
            right_hemisphere=right_hemisphere,
        )


def _make_split_hemisphere(
    *,
    display_transform: MeshDisplayTransform,
    display_vertices: np.ndarray,
    projection_vertices: np.ndarray,
    faces: np.ndarray,
    shade_values: np.ndarray | None,
    shade_source: str | None,
    surface: str,
) -> BrainHemisphereMesh:
    display_points = display_transform.to_display_points(display_vertices)
    projection_points = display_transform.to_display_points(projection_vertices)
    display_shade_values = (
        np.asarray(shade_values, dtype=float)
        if shade_values is not None and len(shade_values) == len(display_points)
        else _geometry_shading_values(display_points)
    )
    return BrainHemisphereMesh(
        points=np.asarray(display_points, dtype=float),
        faces=_faces_to_vtk(faces),
        projection_points=np.asarray(projection_points, dtype=float),
        shade_values=display_shade_values,
        shade_source=shade_source or "geometry",
        surface=surface,
    )


def _geometry_shading_values(points: np.ndarray) -> np.ndarray:
    display_points = np.asarray(points, dtype=float)
    if len(display_points) == 0:
        return np.empty((0,), dtype=float)
    centered = display_points - np.mean(display_points, axis=0)
    depth = centered[:, 1] + 0.35 * centered[:, 2]
    minimum = float(np.min(depth))
    maximum = float(np.max(depth))
    if maximum <= minimum:
        return np.full(len(display_points), 0.55, dtype=float)
    return np.clip((depth - minimum) / (maximum - minimum), 0.0, 1.0)


def _decimate_hemisphere(
    points: np.ndarray,
    faces: np.ndarray,
    *,
    max_triangles: int,
) -> BrainHemisphereMesh:
    if max_triangles <= 0 or len(faces) <= max_triangles:
        return BrainHemisphereMesh(points=np.asarray(points, dtype=float), faces=_faces_to_vtk(faces))
    try:
        import pyvista as pv

        surface = pv.PolyData(points, _faces_to_vtk(faces))
        target_reduction = 1.0 - (max_triangles / max(len(faces), 1))
        decimated = surface.decimate_pro(
            target_reduction,
            preserve_topology=True,
            boundary_vertex_deletion=False,
            splitting=False,
        )
        decimated = decimated.triangulate()
        decimated_faces = _vtk_faces_to_triangles(np.asarray(decimated.faces, dtype=np.int64))
        return BrainHemisphereMesh(
            points=np.asarray(decimated.points, dtype=float),
            faces=_faces_to_vtk(decimated_faces),
        )
    except (AttributeError, RuntimeError, TypeError, ValueError, ImportError, ModuleNotFoundError) as exc:
        logger.warning(
            "fsaverage_hemisphere_decimation_failed",
            extra={"error": str(exc), "original_triangles": len(faces)},
        )
        return BrainHemisphereMesh(points=np.asarray(points, dtype=float), faces=_faces_to_vtk(faces))


def _display_transform(points: np.ndarray) -> MeshDisplayTransform:
    try:
        return MeshDisplayTransform.from_native_points(
            points,
            native_coordinate_space=COORDINATE_SPACE_FSAVERAGE,
        )
    except ValueError as exc:
        raise FsaverageMeshError(f"fsaverage mesh has invalid display transform: {exc}") from exc


def _faces_to_vtk(faces: np.ndarray) -> np.ndarray:
    counts = np.full((len(faces), 1), 3, dtype=np.int64)
    return np.hstack((counts, faces.astype(np.int64))).reshape(-1)


def _vtk_faces_to_triangles(vtk_faces: np.ndarray) -> np.ndarray:
    faces = np.asarray(vtk_faces, dtype=np.int64).reshape(-1, 4)
    if not np.all(faces[:, 0] == 3):
        raise FsaverageMeshError("Expected triangulated fsaverage display mesh.")
    return faces[:, 1:4]
