"""Shared fsaverage cache path helpers for the LORETA visualizer."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol

FSAVERAGE_SUBJECT = "fsaverage"
FPVS_FSAVERAGE_SUBJECTS_DIR_ENV = "FPVS_FSAVERAGE_SUBJECTS_DIR"
DEFAULT_FSAVERAGE_SUBJECTS_DIR = Path(".fpvs_cache") / "mne" / "MNE-fsaverage-data"


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
    env_subjects_dir = _env_fsaverage_subjects_dir()
    if env_subjects_dir is not None:
        candidates.append(env_subjects_dir)
    candidates.append(default_fsaverage_subjects_dir())
    return _unique_valid_subjects_dirs(candidates)


def preferred_fsaverage_dirs() -> list[Path]:
    """Return explicit-env plus root-local fsaverage dirs used before any global fallback."""
    return [subjects_dir / FSAVERAGE_SUBJECT for subjects_dir in preferred_fsaverage_subjects_dirs()]


def fetch_fsaverage_subjects_dir() -> Path:
    """Return the subjects dir automatic fsaverage fetches should target."""
    return preferred_fsaverage_subjects_dirs()[0]


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
                candidates.append(_subjects_dir_from_config_path(Path(value).expanduser()))

    candidates.append(Path.home() / "mne_data" / "MNE-fsaverage-data")
    return _unique_valid_subjects_dirs(candidates)


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


def _env_fsaverage_subjects_dir() -> Path | None:
    env_subjects_dir = os.environ.get(FPVS_FSAVERAGE_SUBJECTS_DIR_ENV) or os.environ.get("SUBJECTS_DIR")
    if not env_subjects_dir:
        return None
    return _subjects_dir_from_config_path(Path(env_subjects_dir).expanduser())


def _unique_valid_subjects_dirs(candidates: list[Path]) -> list[Path]:
    unique: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = ensure_allowed_fsaverage_subjects_dir(candidate)
        if resolved not in seen:
            unique.append(resolved)
            seen.add(resolved)
    return unique


def _raise_if_forbidden_fsaverage_path(path: Path) -> None:
    resolved = path.expanduser().resolve()
    root = fpvs_toolbox_root()
    forbidden_roots = (
        root / "src",
        root / "docs",
    )
    for forbidden_root in forbidden_roots:
        try:
            resolved.relative_to(forbidden_root.resolve())
        except ValueError:
            continue
        raise ValueError(
            "fsaverage cache data cannot live under src/ or docs/. "
            f"Use the root-local cache at {default_fsaverage_subjects_dir()} or set "
            f"{FPVS_FSAVERAGE_SUBJECTS_DIR_ENV} to another untracked subjects directory."
        )
