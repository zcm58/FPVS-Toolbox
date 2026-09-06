"""Inspect and clear saved disposable caches without deleting scientific outputs.

The GUI must keep processing, tool calculations, and updater work idle throughout
inspection, confirmation, and removal. This service never runs recursive deletion.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass
import errno
import hashlib
import json
import logging
from pathlib import Path
import stat
import sys
import threading

from Main_App.processing import toolbox_cache_paths as paths

logger = logging.getLogger(__name__)
_CLEAR_LOCK = threading.Lock()


class ToolboxCacheError(ValueError):
    """The requested cache boundary cannot be verified safely."""


class ToolboxCacheChangedError(ToolboxCacheError):
    """The confirmed inventory changed and needs a fresh inspection."""


@dataclass(frozen=True)
class CacheFile:
    path: Path
    size_bytes: int
    signature: tuple[int, ...]


@dataclass(frozen=True)
class CacheTarget:
    label: str
    path: Path
    location: paths.CacheLocation
    files: tuple[CacheFile, ...]

    @property
    def file_count(self) -> int:
        return len(self.files)

    @property
    def total_bytes(self) -> int:
        return sum(file.size_bytes for file in self.files)


@dataclass(frozen=True)
class _ManifestState:
    path: Path
    signature: tuple[int, ...]
    sha256: str
    cache_entries: int


@dataclass(frozen=True)
class ToolboxCacheInventory:
    active_project_root: Path | None
    projects_root: Path | None
    project_roots: tuple[Path, ...]
    targets: tuple[CacheTarget, ...]
    manifests: tuple[_ManifestState, ...]
    warnings: tuple[str, ...] = ()

    @property
    def file_count(self) -> int:
        return sum(target.file_count for target in self.targets)

    @property
    def total_bytes(self) -> int:
        return sum(target.total_bytes for target in self.targets)

    @property
    def manifest_cache_entries(self) -> int:
        return sum(item.cache_entries for item in self.manifests)


@dataclass(frozen=True)
class ToolboxCacheClearResult:
    removed_files: int = 0
    removed_bytes: int = 0
    errors: tuple[str, ...] = ()
    cancelled: bool = False
    cleared_project_roots: tuple[Path, ...] = ()
    memory_cache_names: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


def _signature(path: Path) -> tuple[int, ...]:
    value = path.lstat()
    if not stat.S_ISREG(value.st_mode) or value.st_nlink != 1:
        raise ToolboxCacheError(f"Not an exclusively owned regular file: {path}")
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def _root(path: Path) -> Path:
    root = paths.checked_path(Path(path))
    if root == Path(root.anchor) or not root.is_dir():
        raise ToolboxCacheError(f"Not a usable project/cache root: {path}")
    return root


def _manifest(root: Path) -> tuple[dict, _ManifestState]:
    path = paths.checked_path(root / "project.json", root)
    before = _signature(path)
    content = path.read_bytes()
    data = json.loads(content)
    if not isinstance(data, dict) or not data:
        raise ToolboxCacheError(f"Not an FPVS project manifest: {path}")
    if _signature(path) != before:
        raise ToolboxCacheChangedError(f"Project changed during inspection: {root}")
    node = data
    for name in ("tools", "stats", "group_significant_harmonics_cache", "entries"):
        node = node.get(name, {}) if isinstance(node, dict) else {}
    return data, _ManifestState(path, before, hashlib.sha256(content).hexdigest(), len(node) if isinstance(node, dict) else 0)


def _inspect_location(location: paths.CacheLocation, check_cancel) -> tuple[CacheTarget | None, bool]:
    paths.checked_path(location.path, location.boundary)
    if not location.path.exists():
        return None, False
    if not location.path.is_dir():
        raise ToolboxCacheError(f"Cache directory is not a directory: {location.path}")
    files, pending, skipped = [], [location.path], False
    while pending:
        check_cancel()
        directory = pending.pop()
        paths.checked_path(directory, location.boundary)
        for child in sorted(directory.iterdir()):
            check_cancel()
            paths.checked_path(child, location.boundary)
            if child.is_dir():
                pending.append(child)
            elif paths.owned_cache_file(location, child):
                signature = _signature(child)
                files.append(CacheFile(child, signature[2], signature))
            elif not child.name.endswith(".lock"):
                skipped = True
    target = CacheTarget(location.label, location.path, location, tuple(sorted(files, key=lambda item: str(item.path))))
    return target if files else None, skipped


def inspect_toolbox_caches(*, active_project_root: Path | None = None,
                           projects_root: Path | None = None,
                           should_cancel: Callable[[], bool] | None = None) -> ToolboxCacheInventory:
    """Inventory only active/configured projects and canonical app cache roots."""
    try:
        def check_cancel():
            if should_cancel and should_cancel():
                raise ToolboxCacheError("Cache inspection cancelled.")

        check_cancel()
        warnings = []
        active = _root(active_project_root) if active_project_root is not None else None
        configured = _root(projects_root) if projects_root is not None else None
        roots = {active} if active is not None else set()
        if configured is not None:
            for child in sorted(configured.iterdir()):
                check_cancel()
                # Validate a link before probing its destination's manifest.
                try:
                    paths.checked_path(child, configured)
                except ValueError as exc:
                    warnings.append(str(exc))
                    continue
                if child.is_dir() and (child / "project.json").exists():
                    roots.add(child)
        targets, manifests, valid_roots = [], [], []
        locations = list(paths.app_cache_locations())
        for root in sorted(roots):
            check_cancel()
            try:
                data, state = _manifest(root)
            except (OSError, ValueError) as exc:
                if root == active:
                    raise
                warnings.append(f"Project was skipped: {root}: {exc}")
                continue
            manifests.append(state)
            valid_roots.append(root)
            locations.extend(paths.project_cache_locations(root, data, check_cancel))
        seen = set()
        for location in locations:
            check_cancel()
            if location.path in seen:
                continue
            seen.add(location.path)
            try:
                target, skipped = _inspect_location(location, check_cancel)
            except (OSError, ValueError) as exc:
                check_cancel()
                warnings.append(f"Cache location was kept: {location.path}: {exc}")
                continue
            if target is not None:
                targets.append(target)
            if skipped:
                warnings.append(f"Unrecognized or active files will be kept in {location.path}.")
        return ToolboxCacheInventory(active, configured, tuple(valid_roots), tuple(targets), tuple(manifests), tuple(warnings))
    except (OSError, ValueError) as exc:
        if isinstance(exc, ToolboxCacheError):
            raise
        raise ToolboxCacheError(str(exc)) from exc


def _namespace_for(target: CacheTarget, file: CacheFile) -> Path | None:
    if target.location.kind != "preflight":
        return None
    parent = file.path.parent
    return parent.parent if parent.name == ".slots" else parent


def _publication_lock(namespace: Path | None):
    if namespace is None:
        return nullcontext(True)
    from Main_App.processing.preflight_qc_pruning import namespace_cache_publication_lock
    return namespace_cache_publication_lock(namespace)


def _remove_empty_cache_dirs(target: CacheTarget, removed: list[Path]) -> None:
    directories = set()
    for path in removed:
        current = path.parent
        while current.is_relative_to(target.path):
            directories.add(current)
            if current == target.path:
                break
            current = current.parent
    for directory in sorted(directories, key=lambda item: len(item.parts), reverse=True):
        paths.checked_path(directory, target.location.boundary)
        try:
            directory.rmdir()
        except OSError as exc:
            if exc.errno not in (errno.ENOENT, errno.ENOTEMPTY, errno.EEXIST):
                logger.debug("cache_empty_directory_kept path=%s error=%s", directory, exc)


def _clear_saved_harmonics(state: _ManifestState) -> None:
    paths.checked_path(state.path, state.path.parent)
    data, current = _manifest(state.path.parent)
    if current != state:
        raise ToolboxCacheChangedError(f"Project changed before cache clearing: {state.path}")
    temporary = paths.checked_path(state.path.with_name("project.json.tmp"), state.path.parent)
    if temporary.exists():
        raise ToolboxCacheError(f"A project save is already pending: {state.path}")
    # The existing public helper normalizes nonfinite values across its JSON
    # payload. Preserve such a manifest byte-for-byte instead of changing any
    # unrelated scientific metadata as a side effect of cache clearing.
    json.dumps(data, allow_nan=False)
    from Tools.Stats.data.group_harmonic_cache import clear_cached_group_harmonic_selections
    clear_cached_group_harmonic_selections(state.path.parent)
    _data, after = _manifest(state.path.parent)
    if after.cache_entries:
        raise ToolboxCacheError(f"Saved harmonic cache was not cleared: {state.path}")


def clear_toolbox_caches(inventory: ToolboxCacheInventory, *,
                         should_cancel: Callable[[], bool] | None = None) -> ToolboxCacheClearResult:
    """Clear an unchanged confirmed inventory, reporting partial failures exactly."""
    if not isinstance(inventory, ToolboxCacheInventory):
        raise ToolboxCacheError("A current toolbox cache inventory is required.")
    def cancelled():
        return bool(should_cancel and should_cancel())
    if cancelled():
        return ToolboxCacheClearResult(cancelled=True)
    with _CLEAR_LOCK:
        current = inspect_toolbox_caches(active_project_root=inventory.active_project_root,
                                         projects_root=inventory.projects_root, should_cancel=should_cancel)
        if current != inventory:
            raise ToolboxCacheChangedError("Saved caches changed. Inspect them again before clearing.")
        removed_count, removed_bytes = 0, 0
        errors, cleared_projects, memory_names = [], [], []
        for target in inventory.targets:
            grouped = defaultdict(list)
            for file in target.files:
                grouped[_namespace_for(target, file)].append(file)
            removed = []
            for namespace, files in grouped.items():
                if cancelled():
                    break
                with _publication_lock(namespace) as acquired:
                    if not acquired:
                        errors.append(f"Cache is busy and was kept: {namespace}")
                        continue
                    for file in files:
                        if cancelled():
                            break
                        try:
                            paths.checked_path(file.path, target.location.boundary)
                            if not paths.owned_cache_file(target.location, file.path) or _signature(file.path) != file.signature:
                                raise ToolboxCacheChangedError("Cache file changed after inspection")
                            file.path.unlink()
                            removed_count += 1
                            removed_bytes += file.size_bytes
                            removed.append(file.path)
                        except (OSError, ValueError) as exc:
                            errors.append(f"{file.path}: {exc}")
                            logger.warning("toolbox_cache_file_kept path=%s error=%s", file.path, exc)
            try:
                _remove_empty_cache_dirs(target, removed)
            except (OSError, ValueError) as exc:
                errors.append(f"Empty cache directories were kept: {target.path}: {exc}")
            if cancelled():
                break
        if not cancelled():
            for state in inventory.manifests:
                if cancelled():
                    break
                if not state.cache_entries:
                    continue
                try:
                    _clear_saved_harmonics(state)
                    cleared_projects.append(state.path.parent)
                except (OSError, ValueError) as exc:
                    errors.append(f"{state.path}: {exc}")
            module = sys.modules.get("Tools.Stats.analysis.dv_policy_group_significant")
            if module is not None:
                module.clear_group_significant_selection_cache()
                memory_names.append("Stats harmonic selections")
        return ToolboxCacheClearResult(removed_count, removed_bytes, tuple(errors), cancelled(),
                                       tuple(cleared_projects), tuple(memory_names), inventory.warnings)
