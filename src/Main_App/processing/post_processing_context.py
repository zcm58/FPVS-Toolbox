"""Bounded reuse of validated processing reads during one operation.

Entries never outlive the explicit scope. Every hit checks the identities of
its source files, and callers retain ownership of semantic project/QC keys.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Hashable, Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Any


FileSnapshot = tuple[tuple[str, tuple[int | str, ...] | None], ...]
CACHE_MISS = object()
_MAX_ENTRIES = 32


@dataclass(frozen=True)
class _ValidatedRead:
    files: FileSnapshot
    value: Any


_ACTIVE_READS: ContextVar[OrderedDict | None] = ContextVar(
    "post_processing_validated_reads", default=None,
)


@contextmanager
def post_processing_validation_scope() -> Iterator[None]:
    """Share nested reads and discard them on completion, failure or cancellation."""
    if _ACTIVE_READS.get() is not None:
        yield
        return
    token = _ACTIVE_READS.set(OrderedDict())
    try:
        yield
    finally:
        _ACTIVE_READS.reset(token)


def validation_scope_active() -> bool:
    return _ACTIVE_READS.get() is not None


def _file_identity(path: str, *, hash_contents: bool = False) -> tuple[int | str, ...] | None:
    try:
        stat = Path(path).stat()
        if hash_contents:
            with Path(path).open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
    except OSError:
        return None
    identity = (
        stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns,
        stat.st_dev, stat.st_ino,
    )
    return (*identity, digest) if hash_contents else identity


def capture_validation_files(
    paths: Iterable[str | Path], *, hash_contents: bool = False,
) -> FileSnapshot:
    """Capture strong local identities, including replacement with restored mtime."""
    resolved = dict.fromkeys(str(Path(path).resolve(strict=False)) for path in paths)
    return tuple((path, _file_identity(path, hash_contents=hash_contents)) for path in resolved)


def validation_files_unchanged(files: FileSnapshot) -> bool:
    return all(
        _file_identity(path, hash_contents=identity is not None and len(identity) == 6) == identity
        for path, identity in files
    )


def cached_validation(namespace: str, key: Hashable) -> Any:
    """Return a detached validated result only while all dependencies still match."""
    cache = _ACTIVE_READS.get()
    entry_key = (namespace, key)
    if cache is None or entry_key not in cache:
        return CACHE_MISS
    entry = cache[entry_key]
    if not validation_files_unchanged(entry.files):
        del cache[entry_key]
        return CACHE_MISS
    cache.move_to_end(entry_key)
    return deepcopy(entry.value)


def remember_validation(
    namespace: str,
    key: Hashable,
    value: Any,
    *,
    files: FileSnapshot,
) -> None:
    """Retain successful validation only if inputs stayed unchanged during it."""
    cache = _ACTIVE_READS.get()
    if cache is None or not validation_files_unchanged(files):
        return
    entry_key = (namespace, key)
    cache[entry_key] = _ValidatedRead(files, deepcopy(value))
    cache.move_to_end(entry_key)
    while len(cache) > _MAX_ENTRIES:
        cache.popitem(last=False)
