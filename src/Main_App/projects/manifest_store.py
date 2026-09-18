"""Coordinated, atomic publication of the active project's manifest.

Keep the transaction open for the complete read, patch, and publish operation.
The stable sidecar lock is deliberately retained: unlinking it could let two
processes lock different files while both believe they own the manifest.
"""

from __future__ import annotations

import errno
import json
import os
import tempfile
import threading
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path

_locks: dict[Path, threading.RLock] = {}
_locks_guard = threading.Lock()
_local = threading.local()


@contextmanager
def project_manifest_transaction(manifest_path: str | Path) -> Iterator["ManifestTransaction"]:
    """Serialize updates across threads and processes, including nested helpers."""

    path = Path(manifest_path).resolve()
    with _locks_guard:
        lock = _locks.setdefault(path, threading.RLock())
    if not lock.acquire(timeout=30.0):
        raise TimeoutError(f"Timed out waiting to update project manifest: {path}")
    try:
        active = getattr(_local, "active", None)
        if active is None:
            active = _local.active = {}
        if path in active:
            yield active[path]
            return
        with path.with_name(f".{path.name}.lock").open("a+b") as stream:
            if os.name == "nt":
                import msvcrt

                stream.seek(0, os.SEEK_END)
                if stream.tell() == 0:
                    stream.write(b"\0")
                    stream.flush()
                deadline = time.monotonic() + 30.0
                while True:
                    stream.seek(0)
                    try:
                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                        break
                    except OSError as exc:
                        if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                            raise
                        if time.monotonic() >= deadline:
                            raise TimeoutError(f"Timed out waiting to update project manifest: {path}") from exc
                        time.sleep(0.01)
            else:
                import fcntl

                deadline = time.monotonic() + 30.0
                while True:
                    try:
                        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except OSError as exc:
                        if exc.errno not in (errno.EACCES, errno.EAGAIN):
                            raise
                        if time.monotonic() >= deadline:
                            raise TimeoutError(f"Timed out waiting to update project manifest: {path}") from exc
                        time.sleep(0.01)
            transaction = ManifestTransaction(path)
            active[path] = transaction
            try:
                yield transaction
            finally:
                del active[path]
                if os.name == "nt":
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    finally:
        lock.release()


class ManifestTransaction:
    """Publisher available only while its enclosing manifest lock is held."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def write(self, manifest: Mapping[str, object]) -> bool:
        """Publish JSON without touching an unchanged manifest."""

        payload = json.dumps(dict(manifest), indent=2, ensure_ascii=False).encode("utf-8")
        return self.write_bytes(payload)

    def write_bytes(self, payload: bytes) -> bool:
        """Publish already serialized JSON, retaining caller formatting."""

        if getattr(_local, "active", {}).get(self.path) is not self:
            raise RuntimeError("Project manifest publication requires an active transaction.")
        parsed = json.loads(payload)
        if not isinstance(parsed, dict):
            raise ValueError(f"Project manifest must contain an object: {self.path}")
        try:
            current = json.loads(self.path.read_bytes())
        except FileNotFoundError:
            current = None
        else:
            if not isinstance(current, dict):
                raise ValueError(f"Project manifest must contain an object: {self.path}")
        if current is not None and json.dumps(
            current, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        ) == json.dumps(parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=False):
            return False
        descriptor, name = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent,
        )
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            _replace_manifest(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)
        return True


def _replace_manifest(temporary: Path, target: Path) -> None:
    """Allow brief Windows scanner locks; propagate a persistent failure."""

    for attempt, delay in enumerate((0.0, 0.01, 0.02, 0.05, 0.1, 0.1)):
        if delay:
            time.sleep(delay)
        try:
            os.replace(temporary, target)
            return
        except PermissionError:
            if attempt == 5:
                raise
