"""Exclusive, project-local staging for text and binary publications."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
import os
from pathlib import Path
import tempfile
from typing import IO, Any


@contextmanager
def atomic_write(
    target: str | Path,
    *,
    binary: bool = False,
    replace: Callable[[Path, Path], None] | None = None,
) -> Iterator[IO[Any]]:
    """Write through a newly created descriptor and preserve the target on failure."""
    path = Path(target)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        try:
            stream = os.fdopen(descriptor, "wb" if binary else "w", **({} if binary else {"encoding": "utf-8"}))
        except BaseException:
            os.close(descriptor)
            raise
        with stream:
            yield stream
            stream.flush()
            os.fsync(stream.fileno())
        (replace or os.replace)(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
