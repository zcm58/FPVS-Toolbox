"""Private process-owned EEG memory maps shared by loader and worker cleanup."""

from __future__ import annotations

import atexit
from collections.abc import Iterator
from contextlib import contextmanager
import errno
import logging
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import threading

_directories: dict[tuple[int, Path], tuple[Path, tuple[int, int]]] = {}
_guard = threading.Lock()
_log = logging.getLogger(__name__)


def _directory_info(path: Path) -> os.stat_result | None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if (not stat.S_ISDIR(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400
            or (os.name == "posix" and (info.st_uid != os.getuid() or info.st_mode & 0o022))):
        raise OSError(errno.EINVAL, "Refusing a linked or unsafe memory-map directory", str(path))
    return info


def memmap_root() -> Path:
    """Validate the container without creating it or following a linked child."""
    root = Path(tempfile.gettempdir()).resolve() / "fpvs_memmap"
    _directory_info(root)
    return root


def memmap_process_id(name: str) -> int | None:
    match = re.fullmatch(r"pid_(\d+)(?:-[a-z0-9_]{8})?", name)
    return int(match[1]) if match is not None else None


def _cleanup_private_directory(path: Path, identity: tuple[int, int]) -> None:
    try:
        _directory_info(path.parent)
        current = _directory_info(path)
        if current is not None and (current.st_dev, current.st_ino) == identity:
            shutil.rmtree(path)
    except OSError:
        _log.debug("memory_map_directory_retained path=%s", path, exc_info=True)


def process_memmap_directory() -> Path:
    """Allocate an exclusive private directory, never reuse a guessed PID path."""
    root = memmap_root()
    pid = os.getpid()
    with _guard:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        _directory_info(root)
        previous = _directories.get((pid, root))
        if previous is not None:
            path, identity = previous
            info = _directory_info(path)
            if info is not None:
                if (info.st_dev, info.st_ino) != identity:
                    raise OSError(errno.EINVAL, "Memory-map directory changed during processing", str(path))
                return path
        path = Path(tempfile.mkdtemp(prefix=f"pid_{pid}-", dir=root))
        info = _directory_info(path)
        if info is None:
            raise OSError(errno.ENOENT, "Memory-map directory disappeared during allocation", str(path))
        identity = (info.st_dev, info.st_ino)
        _directories[(pid, root)] = (path, identity)
        atexit.register(_cleanup_private_directory, path, identity)
        return path


@contextmanager
def recording_memmap_path() -> Iterator[Path]:
    """Give one recording an unused preload destination and remove it on exit."""
    parent = process_memmap_directory()
    parent_info = _directory_info(parent)
    if parent_info is None:
        raise OSError(errno.ENOENT, "Memory-map directory disappeared", str(parent))
    directory = Path(tempfile.mkdtemp(prefix="review-", dir=parent))
    info = _directory_info(directory)
    if info is None:
        raise OSError(errno.ENOENT, "Recording memory-map directory disappeared", str(directory))
    path = directory / "raw.dat"
    try:
        yield path
    finally:
        try:
            _directory_info(parent.parent)
            current_parent = _directory_info(parent)
            current = _directory_info(directory)
            if (current_parent is not None and current is not None
                    and (current_parent.st_dev, current_parent.st_ino) == (parent_info.st_dev, parent_info.st_ino)
                    and (current.st_dev, current.st_ino) == (info.st_dev, info.st_ino)):
                path.unlink(missing_ok=True)
                directory.rmdir()
        except OSError:
            _log.warning("recording_preparation_memmap_cleanup_failed path=%s", path, exc_info=True)
