"""Guard files that must be opened in place, such as locks and append logs."""

from __future__ import annotations

import errno
import os
from pathlib import Path
import stat
from typing import IO, Any


def regular_file_info(path: Path) -> os.stat_result | None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    _require_regular_file(path, info)
    return info


def _require_regular_file(path: Path, info: os.stat_result) -> None:
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or getattr(info, "st_file_attributes", 0) & 0x400):
        raise OSError(errno.EINVAL, "Refusing a linked or non-regular file", str(path))


def open_regular_file(path: Path, *, append: bool = False) -> IO[Any]:
    """Validate the path and opened inode before allowing any write."""
    expected = regular_file_info(path)
    flags = os.O_RDWR | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    if append:
        flags |= os.O_APPEND
    if expected is None:
        try:
            descriptor = os.open(path, flags | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            # A concurrent writer may have exclusively created this file.
            expected = regular_file_info(path)
            descriptor = os.open(path, flags)
    else:
        descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        _require_regular_file(path, opened)
        current = regular_file_info(path)
        identity = (opened.st_dev, opened.st_ino)
        if (current is None or identity != (current.st_dev, current.st_ino)
                or (expected is not None and identity != (expected.st_dev, expected.st_ino))):
            raise OSError(errno.EINVAL, "File changed while opening", str(path))
        return os.fdopen(descriptor, "a" if append else "r+b", **({"encoding": "utf-8"} if append else {}))
    except BaseException:
        os.close(descriptor)
        raise
