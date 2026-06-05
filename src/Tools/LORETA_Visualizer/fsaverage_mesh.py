"""fsaverage mesh loading for the LORETA visualizer.

The fsaverage template is fetched or located through MNE outside the repository.
Do not bundle fsaverage data into active source or quarantine paths.
"""

from __future__ import annotations

import logging
import os
import ssl
from dataclasses import dataclass
from pathlib import Path
from urllib.error import URLError

import numpy as np

from Tools.LORETA_Visualizer.synthetic_brain import BrainMesh

logger = logging.getLogger(__name__)

DEFAULT_SURFACE = "pial"
DEFAULT_MAX_TRIANGLES = 70000
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

        left_vertices, left_faces = mne.read_surface(left_path, verbose=False)
        right_vertices, right_faces = mne.read_surface(right_path, verbose=False)
    except (OSError, RuntimeError, ValueError, ImportError, ModuleNotFoundError) as exc:
        raise FsaverageMeshError(f"Unable to read fsaverage {surface} surface: {exc}") from exc

    points, faces = _combine_hemispheres(left_vertices, left_faces, right_vertices, right_faces)
    points, faces = _downsample_faces(points, faces, max_triangles=max_triangles)
    points = _normalize_points(points)
    mesh = BrainMesh(points=points, faces=_faces_to_vtk(faces))
    return FsaverageMeshResult(
        mesh=mesh,
        fsaverage_dir=fsaverage_dir,
        surface=surface,
        triangle_count=len(faces),
        source_label=f"fsaverage {surface}",
    )


def _validate_surface(surface: str) -> str:
    cleaned = str(surface).strip().lower()
    if cleaned not in SURFACE_CHOICES:
        raise FsaverageMeshError(f"Unsupported fsaverage surface: {surface!r}")
    return cleaned


def _resolve_fsaverage_dir(*, allow_fetch: bool) -> Path:
    for candidate in _candidate_fsaverage_dirs():
        if candidate.is_dir():
            return _ensure_outside_repo(candidate)

    if not allow_fetch:
        raise FsaverageMeshError("fsaverage is not available and fetching is disabled.")

    try:
        from mne.datasets import fetch_fsaverage

        fs_dir = Path(fetch_fsaverage(subjects_dir=None, verbose=False))
    except (OSError, RuntimeError, ValueError, ImportError, ModuleNotFoundError, URLError, ssl.SSLError, TimeoutError) as exc:
        raise FsaverageMeshError(f"Unable to fetch fsaverage through MNE: {exc}") from exc
    return _ensure_outside_repo(fs_dir)


def _candidate_fsaverage_dirs() -> list[Path]:
    candidates: list[Path] = []
    env_subjects_dir = os.environ.get("FPVS_FSAVERAGE_SUBJECTS_DIR") or os.environ.get("SUBJECTS_DIR")
    if env_subjects_dir:
        candidate = Path(env_subjects_dir).expanduser()
        candidates.append(candidate if candidate.name == "fsaverage" else candidate / "fsaverage")

    try:
        import mne

        for key in ("MNE_DATASETS_FSAVERAGE_PATH", "MNE_DATA"):
            value = mne.get_config(key)
            if not value:
                continue
            base = Path(value).expanduser()
            candidates.append(base if base.name == "fsaverage" else base / "fsaverage")
    except (ImportError, ModuleNotFoundError, RuntimeError, ValueError):
        logger.debug("fsaverage_mne_config_lookup_failed", exc_info=True)

    candidates.append(Path.home() / "mne_data" / "MNE-fsaverage-data" / "fsaverage")
    return candidates


def _ensure_outside_repo(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    try:
        repo_root = Path.cwd().resolve()
        resolved.relative_to(repo_root)
    except ValueError:
        return resolved
    raise FsaverageMeshError(
        "fsaverage resolved inside this repository; choose an external MNE/user cache location."
    )


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


def _downsample_faces(
    points: np.ndarray,
    faces: np.ndarray,
    *,
    max_triangles: int,
) -> tuple[np.ndarray, np.ndarray]:
    if max_triangles <= 0 or len(faces) <= max_triangles:
        return points, faces
    step = int(np.ceil(len(faces) / max_triangles))
    sampled = faces[::step]
    used_indices = np.unique(sampled.reshape(-1))
    remap = np.full(len(points), -1, dtype=np.int64)
    remap[used_indices] = np.arange(len(used_indices), dtype=np.int64)
    compact_points = points[used_indices]
    compact_faces = remap[sampled]
    logger.debug(
        "fsaverage_mesh_downsampled",
        extra={"original_triangles": len(faces), "triangles": len(compact_faces), "step": step},
    )
    return compact_points, compact_faces


def _normalize_points(points: np.ndarray) -> np.ndarray:
    centered = np.asarray(points, dtype=float) - np.mean(points, axis=0)
    radius = float(np.max(np.linalg.norm(centered, axis=1)))
    if radius <= 0.0:
        raise FsaverageMeshError("fsaverage mesh has invalid zero radius.")
    return centered / radius


def _faces_to_vtk(faces: np.ndarray) -> np.ndarray:
    counts = np.full((len(faces), 1), 3, dtype=np.int64)
    return np.hstack((counts, faces.astype(np.int64))).reshape(-1)
