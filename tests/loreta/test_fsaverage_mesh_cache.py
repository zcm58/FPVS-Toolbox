from __future__ import annotations

import io
import zipfile
from pathlib import Path

import numpy as np
import pytest

from Tools.LORETA_Visualizer import fsaverage_mesh
from Tools.LORETA_Visualizer import fsaverage_cache
from Tools.LORETA_Visualizer.fsaverage_cache import (
    FSAVERAGE_DOWNLOAD_CACHE_DIR,
    _FsaverageArchiveSpec,
    fetch_fsaverage_into_subjects_dir,
)
from Tools.LORETA_Visualizer.fsaverage_mesh import FsaverageMeshError, FsaverageMeshResult
from Tools.LORETA_Visualizer.synthetic_brain import BrainHemisphereMesh, BrainMesh
from Tools.LORETA_Visualizer.transforms import COORDINATE_SPACE_FSAVERAGE, MeshDisplayTransform


def test_mesh_loader_rejects_partial_cache_when_fetch_disabled(monkeypatch, tmp_path: Path) -> None:
    fsaverage_dir = tmp_path / "repo-cache" / "mne" / "MNE-fsaverage-data" / "fsaverage"
    fsaverage_dir.mkdir(parents=True)
    monkeypatch.setattr(fsaverage_mesh, "candidate_fsaverage_dirs", lambda: [fsaverage_dir])

    with pytest.raises(FsaverageMeshError, match="fsaverage is not available and fetching is disabled"):
        fsaverage_mesh._resolve_fsaverage_dir(allow_fetch=False)


def test_mesh_loader_fetches_through_repo_local_wrapper(monkeypatch, tmp_path: Path) -> None:
    target_subjects_dir = tmp_path / "repo-cache" / "mne" / "MNE-fsaverage-data"
    partial_fsaverage_dir = target_subjects_dir / "fsaverage"
    partial_fsaverage_dir.mkdir(parents=True)
    calls: list[Path] = []

    def fake_fetch_fsaverage(subjects_dir: Path) -> Path:
        calls.append(subjects_dir)
        return subjects_dir / "fsaverage"

    monkeypatch.setattr(fsaverage_mesh, "preferred_fsaverage_dirs", lambda: [partial_fsaverage_dir])
    monkeypatch.setattr(fsaverage_mesh, "fetch_fsaverage_subjects_dir", lambda: target_subjects_dir)
    monkeypatch.setattr(fsaverage_mesh, "fetch_fsaverage_into_subjects_dir", fake_fetch_fsaverage)

    assert fsaverage_mesh._resolve_fsaverage_dir(allow_fetch=True) == partial_fsaverage_dir
    assert calls == [target_subjects_dir]


def test_fetch_fsaverage_downloads_archives_inside_subjects_dir(monkeypatch, tmp_path: Path) -> None:
    subjects_dir = tmp_path / "repo-cache" / "mne" / "MNE-fsaverage-data"
    manifest_root = tmp_path / "manifests"
    manifest_root.mkdir()
    (manifest_root / "root.txt").write_text("fsaverage/surf/lh.pial\nfsaverage/surf/rh.pial\n", encoding="utf-8")
    (manifest_root / "bem.txt").write_text("bem/fsaverage-trans.fif\n", encoding="utf-8")

    archives = {
        "root-url": _zip_bytes(
            {
                "fsaverage/surf/lh.pial": b"left pial",
                "fsaverage/surf/rh.pial": b"right pial",
            }
        ),
        "bem-url": _zip_bytes({"bem/fsaverage-trans.fif": b"transform"}),
    }
    download_targets: list[Path] = []
    monkeypatch.setattr(fsaverage_cache, "_mne_fsaverage_manifest_root", lambda: manifest_root)
    monkeypatch.setattr(
        fsaverage_cache,
        "_FSAVERAGE_ARCHIVES",
        (
            _FsaverageArchiveSpec(
                manifest_name="root.txt",
                destination_relative=Path("."),
                archive_name="root.zip",
                url="root-url",
                md5="unused",
            ),
            _FsaverageArchiveSpec(
                manifest_name="bem.txt",
                destination_relative=Path("fsaverage"),
                archive_name="bem.zip",
                url="bem-url",
                md5="unused",
            ),
        ),
    )

    def fake_download(url: str, target_path: Path, *, expected_md5: str) -> None:
        del expected_md5
        download_targets.append(target_path)
        assert target_path.is_relative_to(subjects_dir / FSAVERAGE_DOWNLOAD_CACHE_DIR)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(archives[url])

    monkeypatch.setattr(fsaverage_cache, "_download_url_to_file", fake_download)

    assert fetch_fsaverage_into_subjects_dir(subjects_dir) == subjects_dir / "fsaverage"
    assert (subjects_dir / "fsaverage" / "surf" / "lh.pial").read_bytes() == b"left pial"
    assert (subjects_dir / "fsaverage" / "surf" / "rh.pial").read_bytes() == b"right pial"
    assert (subjects_dir / "fsaverage" / "bem" / "fsaverage-trans.fif").read_bytes() == b"transform"
    assert {path.name for path in download_targets} == {"root.zip.part", "bem.zip.part"}


def test_display_mesh_cache_round_trip_preserves_split_mesh(monkeypatch, tmp_path: Path) -> None:
    cache_dir = tmp_path / "display-mesh-cache"
    monkeypatch.setattr(fsaverage_mesh, "default_loreta_display_mesh_cache_dir", lambda: cache_dir)
    with fsaverage_mesh._DISPLAY_MESH_MEMORY_CACHE_LOCK:
        fsaverage_mesh._DISPLAY_MESH_MEMORY_CACHE.clear()

    display_transform = MeshDisplayTransform(
        center=np.asarray([1.0, 2.0, 3.0], dtype=float),
        radius=4.0,
        native_coordinate_space=COORDINATE_SPACE_FSAVERAGE,
    )
    left_hemisphere = BrainHemisphereMesh(
        points=np.asarray([[0.0, 0.0, 0.0], [0.2, 0.0, 0.0], [0.0, 0.2, 0.0]], dtype=float),
        faces=np.asarray([3, 0, 1, 2], dtype=np.int64),
        projection_points=np.asarray([[10.0, 0.0, 0.0], [12.0, 0.0, 0.0], [10.0, 2.0, 0.0]], dtype=float),
        shade_values=np.asarray([0.1, 0.5, 0.9], dtype=float),
        shade_source="curv",
        surface="inflated",
    )
    mesh = BrainMesh(
        points=np.asarray([[0.0, 0.0, 0.0], [0.5, 0.0, 0.0], [0.0, 0.5, 0.0]], dtype=float),
        faces=np.asarray([3, 0, 1, 2], dtype=np.int64),
        display_transform=display_transform,
        left_hemisphere=left_hemisphere,
    )
    result = FsaverageMeshResult(
        mesh=mesh,
        fsaverage_dir=tmp_path / "fsaverage",
        surface="pial",
        triangle_count=1,
        source_label="fsaverage pial",
        split_surface="inflated",
        split_shading_source="curv",
    )

    fsaverage_mesh._write_cached_mesh_result("demo-cache-key", result)
    loaded = fsaverage_mesh._load_cached_mesh_result("demo-cache-key")

    assert loaded is not None
    assert loaded.surface == "pial"
    assert loaded.split_surface == "inflated"
    assert loaded.split_shading_source == "curv"
    assert np.allclose(loaded.mesh.points, mesh.points)
    assert np.array_equal(loaded.mesh.faces, mesh.faces)
    assert np.allclose(loaded.mesh.display_transform.center, display_transform.center)
    assert loaded.mesh.display_transform.radius == display_transform.radius
    assert loaded.mesh.left_hemisphere is not None
    assert loaded.mesh.left_hemisphere.shade_source == "curv"
    assert loaded.mesh.left_hemisphere.surface == "inflated"
    assert np.allclose(loaded.mesh.left_hemisphere.shade_values, left_hemisphere.shade_values)
    assert loaded.mesh.right_hemisphere is None


def _zip_bytes(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, payload in files.items():
            archive.writestr(name, payload)
    return buffer.getvalue()
