"""Run-owned source prefetch between interactive QC and kurtosis preparation.

Only the loader's unmodified, disk-backed Raw is retained. A recording is lent
once to an exclusive consumer; review choices and processing remain downstream.
The producer and final cleanup must run outside the GUI thread.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import hashlib
import logging
import os
from pathlib import Path
import shutil
import tempfile
from threading import Condition, Event
from typing import Any

from Main_App.io import load_utils
from Main_App.io.eeg_geometry import BIOSEMI64_MONTAGE_ID
from Main_App.processing.toolbox_cache_paths import checked_path

logger = logging.getLogger(__name__)
_DEFAULT_MAX_BYTES = 16 * 1024**3
_DISK_RESERVE_BYTES = 2 * 1024**3
_HASH_CHUNK_BYTES = 1024**2


def _path_key(path: Path | str) -> str:
    # Do not resolve/stat paths during lightweight GUI-side construction.
    return os.path.normcase(os.path.abspath(path))


def _source_identity(path: Path) -> tuple:
    resolved = path.resolve(strict=True)
    stat = resolved.stat()
    return (str(resolved), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns,
            stat.st_dev, stat.st_ino)


def _source_sha256(path: Path, should_cancel: Callable[[], bool]) -> str | None:
    """Hash source bytes in bounded reads, including cooperative cancellation."""
    if should_cancel():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while not should_cancel():
            block = stream.read(_HASH_CHUNK_BYTES)
            if not block:
                return digest.hexdigest() if not should_cancel() else None
            digest.update(block)
    return None


def _loader_settings(settings: Mapping[str, Any]) -> dict[str, Any]:
    """Match the kurtosis scanner's effective source-loading arguments."""
    limit = settings.get("max_idx_keep")
    if limit is None:
        limit = settings.get("max_chan_idx_keep")
    if limit is None:
        limit = 64
    if isinstance(limit, bool) or (isinstance(limit, float) and not limit.is_integer()):
        raise ValueError("BioSemi64 channel limit must be an integer from 1 through 64.")
    limit = int(limit)
    if not 1 <= limit <= 64:
        raise ValueError("BioSemi64 channel limit must be an integer from 1 through 64.")
    return {
        "ref_pair": (
            str(settings.get("ref_channel1") or settings.get("ref_chan1") or settings.get("ref_ch1") or "EXG1"),
            str(settings.get("ref_channel2") or settings.get("ref_chan2") or settings.get("ref_ch2") or "EXG2"),
        ),
        "first_n_channels": limit,
        "stim_channel": str(settings.get("stim_channel") or settings.get("stim") or "Status"),
        "electrode_mapping_profile": settings.get("electrode_mapping_profile"),
        "electrode_montage": BIOSEMI64_MONTAGE_ID,
    }


@dataclass
class _Entry:
    path: Path
    status: str = "pending"
    identity: tuple | None = None
    source_sha256: str | None = None
    raw: Any = None
    mmap: Any = None
    preload_path: Path | None = None
    size_bytes: int = 0


class _LoaderLog:
    def log(self, message: str) -> None:
        logger.debug("qc_source_prefetch_loader message=%s", message)


class QcSourcePrefetch:
    """Sequential, byte-bounded staging with cooperative single-use handoff.

    Construction performs no filesystem I/O. Call ``run`` on a background
    worker, ``take`` on a scanner worker, and ``release`` in that consumer's
    finally block. ``cancel`` is nonblocking. ``close`` waits for the producer
    and every borrowed Raw before removing the private run directory, so it
    also belongs on a background worker. Files outside the staging budget are
    ordinary misses; the producer never waits for a possibly excluded file.
    """

    def __init__(
        self,
        project_root: Path | str,
        raw_file_infos: Sequence[Any],
        settings: Mapping[str, Any],
        *,
        max_prefetch_bytes: int = _DEFAULT_MAX_BYTES,
    ) -> None:
        self._project_root = Path(project_root)
        self._settings = _loader_settings(settings)
        self._entries = {
            _path_key(info.path): _Entry(Path(os.path.abspath(info.path))) for info in raw_file_infos
        }
        self._max_bytes = max(0, int(max_prefetch_bytes))
        self._retained_bytes = 0
        self._condition = Condition()
        self._cancelled = Event()
        self.finished = Event()
        self._started = False
        self._running = False
        self._closed = False
        self._consuming = False
        self._borrowed: dict[int, _Entry] = {}
        self._run_directory: Path | None = None
        self._resolved_root: Path | None = None

    def run(self) -> None:
        """Prepare eligible sources without allocating a recording-sized copy."""
        with self._condition:
            if self._started or self._closed:
                return
            self._started = True
            self._running = True
        try:
            if self._cancelled.is_set() or not self._max_bytes or self._consuming:
                return
            root = self._project_root.resolve(strict=True)
            parent = checked_path(root / ".fpvs_processing", root)
            parent.mkdir(parents=True, exist_ok=True)
            self._resolved_root = root
            # Explicit cleanup avoids a TemporaryDirectory finalizer deleting
            # through a redirected path after our containment check rejected it.
            self._run_directory = Path(tempfile.mkdtemp(prefix="qc-source-", dir=parent))
            checked_path(self._run_directory, root)
            for index, entry in enumerate(self._entries.values()):
                if self._cancelled.is_set():
                    break
                self._prepare(entry, index)
        except Exception:  # noqa: BLE001 - optional prefetch must preserve ordinary scanner fallback.
            # Prefetch must never replace the scanner's normal validation or
            # make a temporary-storage failure fail the scientific workflow.
            logger.warning("qc_source_prefetch_unavailable", exc_info=True)
        finally:
            with self._condition:
                for entry in self._entries.values():
                    if entry.status in {"pending", "loading"}:
                        entry.status = "miss"
                self._running = False
                self.finished.set()
                self._condition.notify_all()

    def _prepare(self, entry: _Entry, index: int) -> None:
        with self._condition:
            if entry.status != "pending" or self._consuming or self._cancelled.is_set():
                return
            # Claim before any file I/O, atomically with begin_consumption.
            entry.status = "loading"
        try:
            identity = _source_identity(entry.path)
            # BDF's packed 24-bit samples expand to float64. Four times the
            # complete source size conservatively covers the selected channels.
            estimate = int(identity[1]) * 4
            with self._condition:
                available_budget = self._max_bytes - self._retained_bytes
            available_disk = max(0, shutil.disk_usage(self._run_directory).free - _DISK_RESERVE_BYTES)
            if estimate > min(available_budget, available_disk):
                return
            source_digest = _source_sha256(entry.path, self._cancelled.is_set)
            if source_digest is None or _source_identity(entry.path) != identity:
                return
            entry.preload_path = self._run_directory / f"{index:06d}_raw.dat"
            raw = load_utils.load_eeg_file(
                _LoaderLog(), str(entry.path), **self._settings,
                preload_path=entry.preload_path,
            )
            entry.raw = raw
            if raw is None:
                return
            data = getattr(raw, "_data", None)
            entry.mmap = getattr(data, "_mmap", None)
            entry.size_bytes = int(getattr(data, "nbytes", 0))
            # Keep only actual disk-backed results; unsupported loader states
            # fall back instead of silently retaining whole recordings in RAM.
            if (entry.mmap is None
                    or _source_sha256(entry.path, self._cancelled.is_set) != source_digest
                    or _source_identity(entry.path) != identity):
                return
            with self._condition:
                if self._cancelled.is_set() or entry.size_bytes > self._max_bytes - self._retained_bytes:
                    return
                entry.identity = identity
                entry.source_sha256 = source_digest
                entry.status = "ready"
                self._retained_bytes += entry.size_bytes
                self._condition.notify_all()
            logger.info("qc_source_prefetch_ready file=%s bytes=%d", entry.path.name, entry.size_bytes)
        except Exception:  # noqa: BLE001 - one optional staging failure must not block other recordings.
            logger.debug("qc_source_prefetch_file_miss file=%s", entry.path, exc_info=True)
        finally:
            with self._condition:
                failed = entry.status in {"pending", "loading"}
            if failed:
                self._dispose(entry)
                with self._condition:
                    entry.status = "miss"
                    self._condition.notify_all()

    def begin_consumption(self) -> bool:
        """Stop new preloads and report whether a source is already in flight.

        Ready sources remain reusable. Unstarted sources become immediate
        misses so the scanner never queues behind a now-excluded recording.
        """
        with self._condition:
            self._consuming = True
            loading = False
            for entry in self._entries.values():
                if entry.status == "pending":
                    entry.status = "miss"
                elif entry.status == "loading":
                    loading = True
            self._condition.notify_all()
            return loading

    def take(
        self,
        path: Path | str,
        *,
        settings: Mapping[str, Any],
        should_cancel: Callable[[], bool] | None = None,
    ) -> Any | None:
        """Wait cooperatively for this source and transfer it at most once."""
        try:
            if _loader_settings(settings) != self._settings:
                return None
        except (TypeError, ValueError, OverflowError):
            return None
        with self._condition:
            entry = self._entries.get(_path_key(path))
            if entry is None:
                return None
            while entry.status == "loading":
                if self._cancelled.is_set() or self._closed or (should_cancel and should_cancel()):
                    return None
                self._condition.wait(timeout=0.05)
            if (entry.status != "ready" or self._cancelled.is_set() or self._closed
                    or (should_cancel and should_cancel())):
                return None
            raw = entry.raw
            entry.status = "taken"
            self._borrowed[id(raw)] = entry
        accepted = False
        try:
            if (_source_identity(entry.path) == entry.identity
                    and _source_sha256(
                        entry.path,
                        lambda: self._cancelled.is_set() or bool(should_cancel and should_cancel()),
                    ) == entry.source_sha256
                    and _source_identity(entry.path) == entry.identity
                    and not self._cancelled.is_set()
                    and not (should_cancel and should_cancel())):
                logger.info("qc_source_prefetch_hit file=%s", entry.path.name)
                accepted = True
                return raw
        except (OSError, RuntimeError, ValueError):
            pass
        finally:
            if not accepted:
                self.release(raw)
        return None

    def release(self, raw: Any) -> None:
        """Close a borrowed Raw and remove its preload after exclusive use."""
        with self._condition:
            entry = self._borrowed.get(id(raw))
            if entry is None or entry.status != "taken":
                return
            entry.status = "releasing"
        try:
            self._dispose(entry)
        finally:
            with self._condition:
                self._retained_bytes -= entry.size_bytes
                entry.status = "consumed"
                self._borrowed.pop(id(raw), None)
                self._condition.notify_all()

    def cancel(self) -> None:
        """Stop future loads and wake consumers; active MNE reads finish safely."""
        self._cancelled.set()
        with self._condition:
            self._condition.notify_all()

    def close(self) -> None:
        """Wait for active owners, then remove only this run's temporary data."""
        self.cancel()
        with self._condition:
            self._closed = True
            self._condition.notify_all()
            while self._running or self._borrowed:
                self._condition.wait(timeout=0.05)
        for entry in self._entries.values():
            self._dispose(entry)
        if self._run_directory is not None:
            try:
                checked_path(self._run_directory, self._resolved_root)
                if self._run_directory.exists():
                    shutil.rmtree(self._run_directory)
                self._run_directory = None
                for entry in self._entries.values():
                    entry.preload_path = None
            except (OSError, ValueError):
                logger.warning("qc_source_prefetch_cleanup_failed", exc_info=True)
        self.finished.set()

    def _dispose(self, entry: _Entry) -> None:
        raw, entry.raw = entry.raw, None
        if raw is not None:
            data = getattr(raw, "_data", None)
            filename = getattr(data, "filename", None)
            if ((entry.mmap is not None and getattr(data, "_mmap", None) is entry.mmap)
                    or (filename is not None and entry.preload_path is not None
                        and _path_key(filename) == _path_key(entry.preload_path))):
                # MNE Raw.__del__ unlinks _data.filename without checking the
                # run boundary. We own that removal and must prevent its later
                # destructor from bypassing a rejected containment check.
                raw._data = None
            try:
                raw.close()
            except Exception:  # noqa: BLE001 - cleanup must still close the mmap after any Raw.close failure.
                logger.debug("qc_source_prefetch_raw_close_failed", exc_info=True)
        mmap, entry.mmap = entry.mmap, None
        if mmap is not None:
            try:
                mmap.close()
            except (OSError, ValueError, BufferError):
                logger.debug("qc_source_prefetch_mmap_close_failed", exc_info=True)
        if entry.preload_path is not None:
            try:
                checked_path(entry.preload_path, self._run_directory)
                entry.preload_path.unlink(missing_ok=True)
                entry.preload_path = None
            except (OSError, ValueError):
                logger.debug("qc_source_prefetch_preload_cleanup_failed", exc_info=True)
