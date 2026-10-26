"""Exclusive, project-local staging for text and binary publications."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
import os
from pathlib import Path
import tempfile
import time
from typing import IO, Any


_PUBLICATION_RETRY_DELAYS = (0.0, 0.01, 0.02, 0.05, 0.1, 0.1)


def replace_with_retry(temporary: Path, target: Path) -> None:
    """Retry brief file-lock permission failures, then propagate the last error.

    Opt-in callers retain their own staging cleanup and synchronization. Six
    attempts wait at most 0.28 seconds in total, matching manifest publication.
    Other I/O failures propagate immediately.
    """
    for attempt, delay in enumerate(_PUBLICATION_RETRY_DELAYS):
        if delay:
            time.sleep(delay)
        try:
            os.replace(temporary, target)
            return
        except PermissionError:
            if attempt == 5:
                raise


def rename_with_retry(temporary: Path, target: Path) -> None:
    """Publish a staged directory despite brief permission locks on its files.

    Preserve ``os.rename`` semantics rather than replacing an existing
    publication. The caller owns unique destination selection and staging
    cleanup. Persistent permission errors and other I/O errors still propagate.
    """
    for attempt, delay in enumerate(_PUBLICATION_RETRY_DELAYS):
        if delay:
            time.sleep(delay)
        try:
            os.rename(temporary, target)
            return
        except PermissionError:
            if attempt == 5:
                raise


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
