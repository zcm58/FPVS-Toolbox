from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from Tools.LORETA_Visualizer import fsaverage_mesh
from Tools.LORETA_Visualizer import fsaverage_cache
from Tools.LORETA_Visualizer.fsaverage_cache import (
    FSAVERAGE_DOWNLOAD_CACHE_DIR,
    _FsaverageArchiveSpec,
    fetch_fsaverage_into_subjects_dir,
)
from Tools.LORETA_Visualizer.fsaverage_mesh import FsaverageMeshError


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


def _zip_bytes(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, payload in files.items():
            archive.writestr(name, payload)
    return buffer.getvalue()
