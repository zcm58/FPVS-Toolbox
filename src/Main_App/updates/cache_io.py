"""Narrow, no-follow cache I/O and the shared updater/uninstaller OS lock.

Windows directory handles pin the root and every ancestor against rename/deletion.
Read handles deny both writes and deletion through verification and process creation.
Only direct regular-file children are ever changed; this module never removes a folder.
"""

from __future__ import annotations

import errno
import logging
import os
import stat
import sys
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from functools import cache
from pathlib import Path
from threading import Event
from typing import BinaryIO

from Main_App.updates.models import UpdateCacheBusy, UpdateCancelled, UpdateError

LOCK_FILENAME = ".fpvs-update.lock"
_REPARSE_ATTRIBUTE = 0x400
_LOG = logging.getLogger(__name__)


def check_cancel(cancel_event: Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise UpdateCancelled("The update operation was canceled.")


def _is_reparse(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & _REPARSE_ATTRIBUTE)


def _identity(info: os.stat_result) -> tuple[int, int]:
    return info.st_dev, info.st_ino


def _require_regular(path: Path, info: os.stat_result) -> None:
    if _is_reparse(info) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise UpdateError(f"Refusing a linked or non-regular update cache file: {path.name}")


def _reserved_name(name: str) -> bool:
    check = getattr(os.path, "isreserved", None)
    return bool(check(name)) if check is not None else Path(name).is_reserved()


def validate_cache_path(path: Path) -> Path:
    """Require an exact absolute directory, not a relative, device, or drive-root path."""

    path = Path(path)
    if not path.is_absolute() or path == Path(path.anchor) or ".." in path.parts or str(path).startswith("\\\\"):
        raise UpdateError("The update cache must be an exact absolute local directory.")
    for part in path.parts[1:]:
        if (
            any(c in part for c in ':<>"|?*')
            or part.endswith((".", " "))
            or any(ord(c) < 32 for c in part)
            or (os.name == "nt" and _reserved_name(part))
        ):
            raise UpdateError("The update cache path contains an unsafe component.")
    if os.name == "nt" and _reserved_name(str(path)):
        raise UpdateError("The update cache path is a reserved Windows device name.")
    return path


class CacheDirectory:
    """A pinned directory, valid only while its owning guard context is open."""

    def __init__(self, path: Path, directories: list[tuple[Path, os.stat_result]]) -> None:
        self.path = path
        self._directories = directories

    def validate(self) -> None:
        for path, expected in self._directories:
            actual = path.lstat()
            if _is_reparse(actual) or not stat.S_ISDIR(actual.st_mode) or _identity(actual) != _identity(expected):
                raise UpdateError("The update cache path changed or contains a linked directory.")

    def child(self, name: str) -> Path:
        if (
            not name
            or name in {".", ".."}
            or name.endswith((".", " "))
            or any(c in name for c in '/\\:<>"|?*')
            or any(ord(c) < 32 for c in name)
            or (os.name == "nt" and _reserved_name(name))
        ):
            raise UpdateError("An update cache filename escaped its directory.")
        path = self.path / name
        if path.parent != self.path:
            raise UpdateError("An update cache filename escaped its directory.")
        return path

    def names(self) -> list[str]:
        self.validate()
        return sorted(child.name for child in self.path.iterdir())

    def regular_info(self, name: str) -> os.stat_result | None:
        self.validate()
        path = self.child(name)
        try:
            info = path.lstat()
        except FileNotFoundError:
            return None
        _require_regular(path, info)
        return info

    @contextmanager
    def open_file(self, name: str, *, mode: str = "read") -> Iterator[BinaryIO]:
        """Open an existing guarded read, an exclusive new file, or the shared lock."""

        path = self.child(name)
        self.regular_info(name)
        fd = _open_file_descriptor(path, mode)
        stream: BinaryIO | None = None
        try:
            info = os.fstat(fd)
            _require_regular(path, info)
            current = self.regular_info(name)
            if current is None or _identity(current) != _identity(info):
                raise UpdateError("An update cache file changed while it was being opened.")
            stream = os.fdopen(fd, "rb" if mode == "read" else "r+b")
        except BaseException:
            try:
                os.close(fd)
            except OSError:
                _LOG.warning("update_cache_descriptor_close_failed", exc_info=True)
            raise
        try:
            yield stream
        except BaseException:
            try:
                stream.close()
            except OSError:
                _LOG.warning("update_cache_close_failed", extra={"cache_file": name}, exc_info=True)
            raise
        else:
            try:
                stream.close()
            except OSError:
                if mode == "new":
                    raise
                _LOG.warning("update_cache_close_failed", extra={"cache_file": name}, exc_info=True)

    def remove(self, name: str) -> bool:
        if self.regular_info(name) is None:
            return False
        try:
            self.child(name).unlink()
        except FileNotFoundError:
            return False
        return True

    def replace(self, source: str, target: str) -> None:
        if self.regular_info(source) is None:
            raise UpdateError("The staged update file disappeared before finalization.")
        self.regular_info(target)
        self.child(source).replace(self.child(target))
        if self.regular_info(target) is None:
            raise UpdateError("The finalized update file disappeared.")


@contextmanager
def locked_cache(path: Path, *, create: bool = True, cancel_event: Event | None = None) -> Iterator[CacheDirectory]:
    """Take one exclusive, nonblocking byte-range lock for the entire cache lifecycle.

    The lock identity is permanent. Never unlink or truncate it, even after releasing
    it: another app or the Inno uninstaller may already have opened that same file.
    Windows uses byte zero, length one, interoperable with Inno's ``LockFileEx``.
    """

    check_cancel(cancel_event)
    path = validate_cache_path(path)
    try:
        with ExitStack() as stack:
            directories = []
            for directory in (*reversed(path.parents), path):
                check_cancel(cancel_event)
                try:
                    info = directory.lstat()
                except FileNotFoundError:
                    if not create:
                        raise
                    try:
                        directory.mkdir()
                    except FileExistsError:
                        pass
                    info = directory.lstat()
                if _is_reparse(info) or not stat.S_ISDIR(info.st_mode):
                    raise UpdateError("The update cache path contains a linked or invalid directory.")
                stack.enter_context(_pin_directory(directory, info))
                directories.append((directory, info))
            cache = CacheDirectory(path, directories)
            with cache.open_file(LOCK_FILENAME, mode="lock") as lock:
                _acquire_lock(lock)
                try:
                    cache.validate()
                    check_cancel(cancel_event)
                    yield cache
                finally:
                    try:
                        _release_lock(lock)
                    except OSError:
                        _LOG.warning("update_cache_unlock_failed", exc_info=True)
    except UpdateError:
        raise
    except OSError as error:
        raise UpdateError(f"Could not access the update cache: {error}") from error


@contextmanager
def guarded_read_path(path: Path, *, cancel_event: Event | None = None) -> Iterator[BinaryIO]:
    """Read an installed file without following links or creating cache bookkeeping.

    Reuse the updater's directory pins and no-write/delete file guard. This helper
    never writes to the installation and does not acquire or create a cache lock.
    """

    with guarded_read_directory(path.parent, cancel_event=cancel_event) as directory:
        with directory.open_file(path.name) as source:
            yield source


@contextmanager
def guarded_read_directory(path: Path, *, cancel_event: Event | None = None) -> Iterator[CacheDirectory]:
    """Keep one directory's ancestry pinned while reading successive files.

    Each file still validates all pinned directory identities and gets its own
    no-write/delete guard. The pins are released when this context exits.
    """
    parent = validate_cache_path(path)
    with ExitStack() as stack:
        directories = []
        for directory in (*reversed(parent.parents), parent):
            check_cancel(cancel_event)
            info = directory.lstat()
            if _is_reparse(info) or not stat.S_ISDIR(info.st_mode):
                raise UpdateError("The installed application contains a linked directory.")
            stack.enter_context(_pin_directory(directory, info))
            directories.append((directory, info))
        yield CacheDirectory(parent, directories)


def _acquire_lock(stream: BinaryIO) -> None:
    try:
        if sys.platform == "win32":
            import msvcrt

            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as error:
        if error.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
            raise UpdateCacheBusy("Another FPVS Toolbox process is using the update cache.") from error
        raise


def _release_lock(stream: BinaryIO) -> None:
    if sys.platform == "win32":
        import msvcrt

        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _open_file_descriptor(path: Path, mode: str) -> int:
    if mode not in {"read", "new", "lock"}:
        raise ValueError(f"Unsupported cache file mode: {mode}")
    if sys.platform == "win32":
        import msvcrt

        access = 0x80000000 if mode == "read" else 0xC0000000  # GENERIC_READ / READ|WRITE
        share = {"read": 1, "new": 0, "lock": 3}[mode]  # never FILE_SHARE_DELETE
        disposition = {"read": 3, "new": 1, "lock": 4}[mode]
        handle = _windows_open(path, access, share, disposition, 0x00200000)
        try:
            flags = os.O_RDONLY if mode == "read" else os.O_RDWR
            return msvcrt.open_osfhandle(handle, flags | os.O_BINARY)
        except BaseException:
            _windows_close(handle)
            raise
    flags = os.O_RDONLY if mode == "read" else os.O_RDWR
    if mode == "new":
        flags |= os.O_CREAT | os.O_EXCL
    elif mode == "lock":
        flags |= os.O_CREAT
    return os.open(path, flags | os.O_NOFOLLOW, 0o600)


@contextmanager
def _pin_directory(path: Path, expected: os.stat_result) -> Iterator[None]:
    if sys.platform == "win32":
        # BACKUP_SEMANTICS opens directories; OPEN_REPARSE_POINT does not follow links.
        handle = _windows_open(path, 0, 3, 3, 0x02000000 | 0x00200000)
    else:
        handle = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        current = path.lstat()
        if _is_reparse(current) or _identity(current) != _identity(expected):
            raise UpdateError("The update cache directory changed while it was being opened.")
        yield
    finally:
        try:
            if sys.platform == "win32":
                _windows_close(handle)
            else:
                os.close(handle)
        except OSError:
            _LOG.warning("update_cache_directory_close_failed", exc_info=True)


@cache
def _windows_file_api() -> tuple[Callable[..., int], Callable[..., int]]:
    """Bind once; frozen ctypes otherwise probes the filesystem for every handle.

    Only API bindings are retained. File handles, directory identities and file
    contents are still acquired and checked afresh on every guarded read.
    """
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    return create, close


def _windows_open(path: Path, access: int, share: int, disposition: int, flags: int) -> int:
    import ctypes

    create, _close = _windows_file_api()
    handle = create(str(path), access, share, None, disposition, flags, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    return int(handle)


def _windows_close(handle: int) -> None:
    import ctypes

    _create, close = _windows_file_api()
    if not close(handle):
        raise ctypes.WinError(ctypes.get_last_error())
