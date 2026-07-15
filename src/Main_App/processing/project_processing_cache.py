"""Project-scoped helpers for an FPVS-managed cold processing run.

Only disposable state that can change whether raw files are rescanned or
preprocessed is managed here.  Canonical project configuration, raw inputs,
generated outputs, run history, and user-reviewed QC settings are outside this
module's deletion boundary.
"""

from __future__ import annotations

import shutil
import threading
from dataclasses import dataclass
from pathlib import Path

from Main_App.processing.preflight_qc_cache import preflight_qc_cache_directory
from Main_App.processing.processing_ledger import ledger_path

PREPROCESSED_CACHE_RELATIVE_DIRECTORY = Path(".fpvs_cache") / "preprocessed"
_CACHE_RESET_LOCK = threading.Lock()


@dataclass(frozen=True)
class ProjectProcessingCacheUsage:
    """Size and exact target set found during inspection or removal."""

    file_count: int = 0
    total_bytes: int = 0
    targets: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.targets


def preprocessed_cache_directory(project_root: Path) -> Path:
    """Return the preprocessed-Raw cache beneath an explicit project root."""

    root = Path(project_root)
    if not root.is_absolute():
        raise ValueError("project_root must be an explicit absolute path")
    return root / PREPROCESSED_CACHE_RELATIVE_DIRECTORY


def _is_redirected_directory(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(callable(is_junction) and is_junction())


def _path_present(path: Path) -> bool:
    """Return true for normal entries and dangling symbolic links."""

    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True


def _validated_cache_targets(project_root: Path) -> tuple[tuple[str, Path], ...]:
    root = Path(project_root)
    if not root.is_absolute():
        raise ValueError("project_root must be an explicit absolute path")

    resolved_root = root.resolve(strict=False)
    ledger = ledger_path(root)
    targets = (
        ("preprocessed Raw cache", preprocessed_cache_directory(root)),
        ("preflight QC cache", preflight_qc_cache_directory(root)),
        ("processing ledger temporary file", ledger.with_suffix(".json.tmp")),
        ("processing ledger", ledger),
    )
    for _label, target in targets:
        resolved_target = target.resolve(strict=False)
        if resolved_target == resolved_root or not resolved_target.is_relative_to(
            resolved_root
        ):
            raise ValueError(
                f"Refusing cache target outside the project root: {target}"
            )
    return targets


def _path_usage(path: Path) -> tuple[int, int]:
    if not _path_present(path):
        return 0, 0
    if _is_redirected_directory(path):
        return 1, int(path.lstat().st_size)
    if not path.is_dir():
        return 1, int(path.stat().st_size)

    file_count = 0
    total_bytes = 0
    pending = [path]
    while pending:
        directory = pending.pop()
        for child in directory.iterdir():
            if _is_redirected_directory(child):
                file_count += 1
                total_bytes += int(child.lstat().st_size)
            elif child.is_dir():
                pending.append(child)
            else:
                file_count += 1
                total_bytes += int(child.stat().st_size)
    return file_count, total_bytes


def _inspect_project_processing_cache_unlocked(
    project_root: Path,
) -> ProjectProcessingCacheUsage:
    file_count = 0
    total_bytes = 0
    present_targets: list[str] = []
    for label, target in _validated_cache_targets(project_root):
        if not _path_present(target):
            continue
        target_files, target_bytes = _path_usage(target)
        file_count += target_files
        total_bytes += target_bytes
        present_targets.append(label)
    return ProjectProcessingCacheUsage(
        file_count=file_count,
        total_bytes=total_bytes,
        targets=tuple(present_targets),
    )


def inspect_project_processing_cache(
    project_root: Path,
) -> ProjectProcessingCacheUsage:
    """Inspect cold-run cache state without creating or changing project files."""

    with _CACHE_RESET_LOCK:
        return _inspect_project_processing_cache_unlocked(project_root)


def clear_project_processing_cache(
    project_root: Path,
) -> ProjectProcessingCacheUsage:
    """Remove only cache state required for an FPVS-managed cold next run.

    The preprocessed and preflight caches are removed before the incremental
    ledger.  If either directory cannot be cleared, the ledger remains in place
    and the caller receives the filesystem error instead of a misleading
    partially cold planning state.
    """

    with _CACHE_RESET_LOCK:
        usage = _inspect_project_processing_cache_unlocked(project_root)
        for _label, target in _validated_cache_targets(project_root):
            if not _path_present(target):
                continue
            if _is_redirected_directory(target):
                raise OSError(f"Refusing to clear redirected cache target: {target}")
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
        return usage


__all__ = [
    "PREPROCESSED_CACHE_RELATIVE_DIRECTORY",
    "ProjectProcessingCacheUsage",
    "clear_project_processing_cache",
    "inspect_project_processing_cache",
    "preprocessed_cache_directory",
]
