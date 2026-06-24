"""Shared fsaverage cache path helpers for the LORETA visualizer."""

from __future__ import annotations

import os
import logging
import hashlib
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.request import urlopen

FSAVERAGE_SUBJECT = "fsaverage"
FPVS_FSAVERAGE_SUBJECTS_DIR_ENV = "FPVS_FSAVERAGE_SUBJECTS_DIR"
DEFAULT_FSAVERAGE_SUBJECTS_DIR = Path(".fpvs_cache") / "mne" / "MNE-fsaverage-data"
FSAVERAGE_DOWNLOAD_CACHE_DIR = ".downloads"
FSAVERAGE_ROOT_ARCHIVE_URL = "https://osf.io/3bxqt/download?version=2"
FSAVERAGE_ROOT_ARCHIVE_MD5 = "5133fe92b7b8f03ae19219d5f46e4177"
FSAVERAGE_BEM_ARCHIVE_URL = "https://osf.io/7ve8g/download?version=4"
FSAVERAGE_BEM_ARCHIVE_MD5 = "b31509cdcf7908af6a83dc5ee8f49fb1"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _FsaverageArchiveSpec:
    manifest_name: str
    destination_relative: Path
    archive_name: str
    url: str
    md5: str


_FSAVERAGE_ARCHIVES = (
    _FsaverageArchiveSpec(
        manifest_name="root.txt",
        destination_relative=Path("."),
        archive_name="fsaverage-root.zip",
        url=FSAVERAGE_ROOT_ARCHIVE_URL,
        md5=FSAVERAGE_ROOT_ARCHIVE_MD5,
    ),
    _FsaverageArchiveSpec(
        manifest_name="bem.txt",
        destination_relative=Path(FSAVERAGE_SUBJECT),
        archive_name="fsaverage-bem.zip",
        url=FSAVERAGE_BEM_ARCHIVE_URL,
        md5=FSAVERAGE_BEM_ARCHIVE_MD5,
    ),
)


class _MneConfigProvider(Protocol):
    def get_config(self, key: str) -> str | None:
        ...


def fpvs_toolbox_root() -> Path:
    """Return the FPVS Toolbox repository root."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "AGENTS.md").is_file() and (parent / "src").is_dir():
            return parent
    raise RuntimeError("Unable to locate the FPVS Toolbox repository root from the LORETA visualizer package.")


def default_fsaverage_subjects_dir() -> Path:
    """Return the root-local MNE subjects directory used for automatic fsaverage installs."""
    return fpvs_toolbox_root() / DEFAULT_FSAVERAGE_SUBJECTS_DIR


def default_fsaverage_dir() -> Path:
    """Return the default root-local fsaverage subject directory."""
    return default_fsaverage_subjects_dir() / FSAVERAGE_SUBJECT


def preferred_fsaverage_subjects_dirs() -> list[Path]:
    """Return explicit-env plus root-local subjects dirs used before any global fallback."""
    candidates: list[Path] = []
    fpvs_env_subjects_dir = _fpvs_env_fsaverage_subjects_dir()
    if fpvs_env_subjects_dir is not None:
        candidates.append(ensure_allowed_fsaverage_subjects_dir(fpvs_env_subjects_dir))
    subjects_dir_env = _subjects_dir_env_subjects_dir()
    if subjects_dir_env is not None:
        candidates.append(subjects_dir_env)
    candidates.append(default_fsaverage_subjects_dir())
    return _unique_subjects_dirs(candidates)


def preferred_fsaverage_dirs() -> list[Path]:
    """Return explicit-env plus root-local fsaverage dirs used before any global fallback."""
    return [subjects_dir / FSAVERAGE_SUBJECT for subjects_dir in preferred_fsaverage_subjects_dirs()]


def fetch_fsaverage_subjects_dir() -> Path:
    """Return the subjects dir automatic fsaverage fetches should target."""
    return default_fsaverage_subjects_dir()


def fetch_fsaverage_into_subjects_dir(subjects_dir: Path) -> Path:
    """Fetch fsaverage using only the configured subjects-dir cache.

    MNE's public ``fetch_fsaverage`` stores final files in ``subjects_dir`` but
    downloads ZIP archives through the process temp directory. This wrapper
    keeps both transient archives and extracted fsaverage data inside the
    allowed FPVS cache tree.
    """
    subjects_path = ensure_allowed_fsaverage_subjects_dir(subjects_dir)
    fsaverage_dir = subjects_path / FSAVERAGE_SUBJECT
    fsaverage_dir.mkdir(parents=True, exist_ok=True)
    manifest_root = _mne_fsaverage_manifest_root()
    download_dir = subjects_path / FSAVERAGE_DOWNLOAD_CACHE_DIR

    for spec in _FSAVERAGE_ARCHIVES:
        manifest_path = manifest_root / spec.manifest_name
        destination = (subjects_path / spec.destination_relative).resolve()
        _manifest_check_download_repo_local(
            manifest_path=manifest_path,
            destination=destination,
            download_dir=download_dir,
            spec=spec,
        )
    return fsaverage_dir


def candidate_fsaverage_subjects_dirs(mne_module: _MneConfigProvider | None = None) -> list[Path]:
    """Return fsaverage subjects-dir candidates in lookup order."""
    candidates: list[Path] = preferred_fsaverage_subjects_dirs()

    if mne_module is None:
        try:
            import mne

            mne_module = mne
        except (ImportError, ModuleNotFoundError, RuntimeError, ValueError):
            mne_module = None

    if mne_module is not None:
        for key in ("SUBJECTS_DIR", "MNE_DATASETS_FSAVERAGE_PATH", "MNE_DATA"):
            value = mne_module.get_config(key)
            if value:
                candidate = _optional_subjects_dir_from_path(
                    Path(value).expanduser(),
                    source=f"MNE config {key}",
                )
                if candidate is not None:
                    candidates.append(candidate)

    candidates.append(Path.home() / "mne_data" / "MNE-fsaverage-data")
    return _unique_subjects_dirs(candidates)


def candidate_fsaverage_dirs(mne_module: _MneConfigProvider | None = None) -> list[Path]:
    """Return fsaverage subject directories in lookup order."""
    return [subjects_dir / FSAVERAGE_SUBJECT for subjects_dir in candidate_fsaverage_subjects_dirs(mne_module)]


def ensure_allowed_fsaverage_subjects_dir(path: Path) -> Path:
    """Resolve a subjects dir and reject tracked source/doc locations."""
    resolved = path.expanduser().resolve()
    _raise_if_forbidden_fsaverage_path(resolved / FSAVERAGE_SUBJECT)
    return resolved


def ensure_allowed_fsaverage_dir(path: Path) -> Path:
    """Resolve an fsaverage dir and reject tracked source/doc locations."""
    resolved = path.expanduser().resolve()
    _raise_if_forbidden_fsaverage_path(resolved)
    return resolved


def _subjects_dir_from_config_path(path: Path) -> Path:
    return path.parent if path.name == FSAVERAGE_SUBJECT else path


def _fpvs_env_fsaverage_subjects_dir() -> Path | None:
    env_subjects_dir = os.environ.get(FPVS_FSAVERAGE_SUBJECTS_DIR_ENV)
    if not env_subjects_dir:
        return None
    return _subjects_dir_from_config_path(Path(env_subjects_dir).expanduser())


def _subjects_dir_env_subjects_dir() -> Path | None:
    env_subjects_dir = os.environ.get("SUBJECTS_DIR")
    if not env_subjects_dir:
        return None
    return _optional_subjects_dir_from_path(Path(env_subjects_dir).expanduser(), source="SUBJECTS_DIR")


def _optional_subjects_dir_from_path(path: Path, *, source: str) -> Path | None:
    subjects_dir = _subjects_dir_from_config_path(path)
    try:
        return ensure_allowed_fsaverage_subjects_dir(subjects_dir)
    except ValueError as exc:
        logger.warning(
            "Ignoring fsaverage subjects-dir candidate from %s because it points into a forbidden path: %s",
            source,
            subjects_dir,
            extra={"source": source, "path": str(subjects_dir), "error": str(exc)},
        )
        return None


def _unique_subjects_dirs(candidates: list[Path]) -> list[Path]:
    unique: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if resolved not in seen:
            unique.append(resolved)
            seen.add(resolved)
    return unique


def _raise_if_forbidden_fsaverage_path(path: Path) -> None:
    resolved = path.expanduser().resolve()
    for forbidden_root in _forbidden_fsaverage_roots():
        try:
            resolved.relative_to(forbidden_root.resolve())
        except ValueError:
            continue
        raise ValueError(
            "fsaverage cache data cannot live under src/, docs/, temp directories, "
            "or admin-protected system folders. "
            f"Use the root-local cache at {default_fsaverage_subjects_dir()} or set "
            f"{FPVS_FSAVERAGE_SUBJECTS_DIR_ENV} to another untracked subjects directory."
        )


def _forbidden_fsaverage_roots() -> tuple[Path, ...]:
    root = fpvs_toolbox_root()
    forbidden_roots = [
        root / "src",
        root / "docs",
    ]
    for env_key in ("TEMP", "TMP", "PROGRAMFILES", "ProgramFiles(x86)", "WINDIR", "SYSTEMROOT"):
        value = os.environ.get(env_key)
        if value:
            forbidden_roots.append(Path(value).expanduser())
    return tuple(forbidden_roots)


def _mne_fsaverage_manifest_root() -> Path:
    from mne.datasets._fsaverage import base as fsaverage_base

    return Path(fsaverage_base.FSAVERAGE_MANIFEST_PATH)


def _manifest_check_download_repo_local(
    *,
    manifest_path: Path,
    destination: Path,
    download_dir: Path,
    spec: _FsaverageArchiveSpec,
) -> None:
    names = _manifest_names(manifest_path)
    missing = [name for name in names if not (destination / name).is_file()]
    logger.info(
        "fsaverage_manifest_missing_files",
        extra={
            "manifest": str(manifest_path),
            "destination": str(destination),
            "missing_count": len(missing),
        },
    )
    if not missing:
        return

    archive_path = _download_archive_to_repo_cache(
        url=spec.url,
        download_dir=download_dir,
        archive_name=spec.archive_name,
        expected_md5=spec.md5,
    )
    _extract_manifest_files(
        archive_path=archive_path,
        destination=destination,
        expected_names=set(names),
        missing_names=missing,
    )


def _manifest_names(manifest_path: Path) -> list[Path]:
    with manifest_path.open(encoding="utf-8") as handle:
        return [Path(line.strip()) for line in handle if line.strip()]


def _download_archive_to_repo_cache(
    *,
    url: str,
    download_dir: Path,
    archive_name: str,
    expected_md5: str,
) -> Path:
    download_dir.mkdir(parents=True, exist_ok=True)
    archive_path = download_dir / archive_name
    if archive_path.is_file() and _file_md5(archive_path) == expected_md5:
        return archive_path

    partial_path = archive_path.with_suffix(archive_path.suffix + ".part")
    if partial_path.exists():
        partial_path.unlink()
    _download_url_to_file(url, partial_path, expected_md5=expected_md5)
    partial_path.replace(archive_path)
    return archive_path


def _download_url_to_file(url: str, target_path: Path, *, expected_md5: str) -> None:
    digest = hashlib.md5(usedforsecurity=False)
    try:
        with urlopen(url, timeout=60) as response, target_path.open("wb") as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                handle.write(chunk)
    except Exception:
        if target_path.exists():
            target_path.unlink()
        raise
    if digest.hexdigest() != expected_md5:
        target_path.unlink(missing_ok=True)
        raise RuntimeError(
            f"Downloaded fsaverage archive hash mismatch for {url}: "
            f"expected {expected_md5}, got {digest.hexdigest()}."
        )


def _file_md5(path: Path) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _extract_manifest_files(
    *,
    archive_path: Path,
    destination: Path,
    expected_names: set[Path],
    missing_names: list[Path],
) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    destination_root = destination.resolve()
    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            members = {Path(name) for name in archive.namelist() if not name.endswith("/")}
            if members != expected_names:
                unexpected = sorted(str(path) for path in members.symmetric_difference(expected_names))
                raise RuntimeError("fsaverage archive contents do not match the MNE manifest:\n" + "\n".join(unexpected))
            for name in missing_names:
                target = (destination / name).resolve()
                try:
                    target.relative_to(destination_root)
                except ValueError as exc:
                    raise RuntimeError(f"Refusing to extract fsaverage file outside cache: {name}") from exc
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(str(name).replace("\\", "/")) as source, target.open("wb") as handle:
                    shutil.copyfileobj(source, handle)
    except zipfile.BadZipFile as exc:
        raise RuntimeError(f"Downloaded fsaverage archive is not a valid ZIP file: {archive_path}") from exc
