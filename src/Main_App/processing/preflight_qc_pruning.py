"""Conservative retention for completed, project-owned preflight caches.

The small ``.slots`` index is initialized once without deleting anything. A
successful publication may then replace earlier generations of its logical
recording or occurrence. Scientific cache fingerprints still include all inputs.
"""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import stat
import tempfile
from typing import Any, Iterator, Mapping

logger = logging.getLogger(__name__)
_CACHE_NAME = re.compile(r"[0-9a-f]{64}\.json\Z")
_INDEX_VERSION = 1


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _plain(path: Path, *, directory: bool = False) -> bool:
    try:
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            return False
        if directory:
            return stat.S_ISDIR(info.st_mode)
        return stat.S_ISREG(info.st_mode) and info.st_nlink == 1
    except OSError:
        return False


def safe_cache_directory(project_root: Path, directory: Path) -> bool:
    """Reject redirection through symlinks/junctions before deletion or writes."""
    try:
        root = Path(project_root)
        relative = directory.relative_to(root)
        if not root.is_absolute():
            return False
        if any(path.is_symlink() or (path.exists() and not _plain(path, directory=True)) for path in (root, *root.parents)):
            return False
        current = root
        for part in relative.parts:
            if part in (".", ".."):
                return False
            current = current / part
            if current.exists() and not _plain(current, directory=True):
                return False
            if current.is_symlink():
                return False
        return directory.resolve().is_relative_to(root.resolve())
    except (OSError, ValueError, RuntimeError):
        return False


@contextmanager
def namespace_cache_publication_lock(cache_directory: Path) -> Iterator[bool]:
    """Nonblocking OS advisory lock; keep its inode when clearing a namespace.

    The OS releases the lock on process exit, including crashes. An existing
    lock file therefore does not represent a stale lock requiring deletion.
    """
    stream = None
    acquired = False
    if any(not _plain(path, directory=True) for path in (cache_directory, *cache_directory.parents)):
        yield False
        return
    lock_path = cache_directory / ".publication.lock"
    if (lock_path.exists() or lock_path.is_symlink()) and not _plain(lock_path):
        yield False
        return
    try:
        descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        stream = os.fdopen(descriptor, "r+b")
        if os.fstat(stream.fileno()).st_size == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        acquired = True
    except OSError:
        pass
    try:
        yield acquired
    finally:
        if stream is not None:
            if acquired:
                try:
                    if os.name == "nt":
                        import msvcrt
                        stream.seek(0)
                        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
            stream.close()


def _stat_identity(path: Path) -> dict[str, int]:
    info = path.lstat()
    return {name: int(getattr(info, name)) for name in ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")}


def _slot(key: Mapping[str, Any], namespace: str, method_directory: str) -> dict[str, Any] | None:
    try:
        source = key["file_identity"]
        method = key["method"]
        plan = key["event_plan"]
        if method.get("name") != "condition_aware_preflight_qc" or method.get("version") != method_directory:
            return None
        source_path = source["resolved_path"]
        if not isinstance(source_path, str) or not Path(source_path).is_absolute():
            return None
        recording_id = source.get("recording_id")
        if recording_id is not None and not isinstance(recording_id, str):
            return None
        slot = {"source": source_path, "recording_id": recording_id, "namespace": namespace}
        if namespace == "occurrences":
            if method.get("evidence_codec") != "typed_float64_v1":
                return None
            span = plan["span"]
            identity = {name: span[name] for name in ("condition_id", "condition_label", "repetition_index", "onset_sample")}
            if not isinstance(identity["condition_label"], str) or not identity["condition_label"]:
                return None
            if any(type(identity[name]) is not int for name in ("condition_id", "repetition_index", "onset_sample")):
                return None
            slot["occurrence"] = identity
        elif namespace == "events":
            if method.get("event_extractor") != "mne_shortest_1_annotation_fallback_v1":
                return None
        elif namespace == "":
            scope = key["settings"]["recording_scope"]
            if set(scope) != {"participant_id", "recording_id"} or not isinstance(scope["participant_id"], str):
                return None
            if scope["recording_id"] != recording_id:
                return None
            slot["recording_scope"] = scope
        else:
            return None
        return slot
    except (AttributeError, KeyError, TypeError, ValueError):
        return None


def _read_json(path: Path) -> Any:
    if not _plain(path):
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, RecursionError):
        return None


def _read_entry(path: Path, namespace: str, schema_version: int, method_directory: str):
    if not _CACHE_NAME.fullmatch(path.name):
        return None
    value = _read_json(path)
    try:
        if not isinstance(value, dict) or value.get("schema_version") != schema_version:
            return None
        if value.get("fingerprint") != path.stem or _digest(value["key"]) != path.stem:
            return None
        if not isinstance(value["result"], dict) or _digest(value["result"]) != value.get("result_sha256"):
            return None
        slot = _slot(value["key"], namespace, method_directory)
        return (value, slot) if slot is not None else None
    except (KeyError, TypeError, ValueError, RecursionError):
        return None


def _atomic_json(path: Path, value: Any) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=".index-", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(_json(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _index_payload(slot: Mapping[str, Any], entries: list[dict[str, Any]]) -> dict[str, Any]:
    return {"schema_version": _INDEX_VERSION, "slot": dict(slot), "entries": entries}


def _source_matches(source: Mapping[str, Any]) -> bool:
    info = Path(source["resolved_path"]).stat()
    return all(source.get(key) == int(getattr(info, attr)) for key, attr in (
        ("size", "st_size"), ("mtime_ns", "st_mtime_ns"), ("ctime_ns", "st_ctime_ns"),
    ))


def prepare_pruning_candidates(
    project_root: Path, directory: Path, key: Mapping[str, Any], *, namespace: str,
    schema_version: int, method_directory: str,
) -> tuple[Path, dict[str, Any], list[dict[str, Any]]] | None:
    """Capture this slot's known generations before publication; never delete."""
    slot = _slot(key, namespace, method_directory)
    if slot is None or not safe_cache_directory(project_root, directory):
        return None
    slots = directory / ".slots"
    if not safe_cache_directory(project_root, slots):
        return None
    try:
        slots.mkdir(exist_ok=True)
        state_path = slots / "index-state.json"
        if not state_path.exists() and not state_path.is_symlink():
            # Write the attempt first: interruption or uncertainty must not cause
            # another expensive namespace-wide scan on each condition save.
            _atomic_json(state_path, {"schema_version": _INDEX_VERSION, "state": "started"})
            grouped: dict[str, tuple[dict[str, Any], list[dict[str, Any]]]] = {}
            for candidate in directory.iterdir():
                entry = _read_entry(candidate, namespace, schema_version, method_directory)
                if entry is None:
                    continue
                _envelope, candidate_slot = entry
                slot_id = _digest(candidate_slot)
                grouped.setdefault(slot_id, (candidate_slot, []))[1].append({"name": candidate.name, "stat": _stat_identity(candidate)})
            for slot_id, (candidate_slot, entries) in grouped.items():
                index_path = slots / f"{slot_id}.json"
                if not index_path.exists() and not index_path.is_symlink():
                    _atomic_json(index_path, _index_payload(candidate_slot, entries))
            _atomic_json(state_path, {"schema_version": _INDEX_VERSION, "state": "complete"})
        state = _read_json(state_path)
        if not isinstance(state, dict) or state.get("schema_version") != _INDEX_VERSION or state.get("state") not in {"started", "complete"}:
            return None
        index_path = slots / f"{_digest(slot)}.json"
        if not index_path.exists() and not index_path.is_symlink():
            return index_path, slot, []
        indexed = _read_json(index_path)
        if not isinstance(indexed, dict) or indexed.get("schema_version") != _INDEX_VERSION or indexed.get("slot") != slot or not isinstance(indexed.get("entries"), list):
            return None
        return index_path, slot, indexed["entries"]
    except (OSError, TypeError, ValueError, RecursionError):
        logger.warning("preflight_cache_index_unavailable path=%s", slots)
        return None


def prune_after_publication(
    project_root: Path, destination: Path, prepared, *, namespace: str,
    schema_version: int, method_directory: str,
) -> None:
    """Delete only captured, validated predecessors of this completed slot."""
    if prepared is None:
        return
    index_path, slot, candidates = prepared
    directory = destination.parent
    if not safe_cache_directory(project_root, directory) or not safe_cache_directory(project_root, index_path.parent):
        return
    try:
        replacement = _read_entry(destination, namespace, schema_version, method_directory)
        if replacement is None or replacement[1] != slot:
            return
        source = replacement[0]["key"]["file_identity"]
        if not _source_matches(source):
            return
        current_stat = _stat_identity(destination)
        if (index_path.exists() or index_path.is_symlink()) and not _plain(index_path):
            return
        current_entry = {"name": destination.name, "stat": current_stat}
        pending = [candidate for candidate in candidates if isinstance(candidate, dict) and candidate.get("name") != destination.name]
        # Preserve pending generations before unlinking: a crash or locked file
        # must not discard the authority needed to retry on a later replacement.
        _atomic_json(index_path, _index_payload(slot, [current_entry, *pending]))
        survivors = []
        for candidate in candidates:
            if not isinstance(candidate, dict) or not isinstance(candidate.get("name"), str) or not _CACHE_NAME.fullmatch(candidate["name"]):
                continue
            old_path = directory / candidate["name"]
            try:
                if old_path == destination or not _plain(old_path):
                    continue
                if _stat_identity(old_path) != candidate.get("stat"):
                    continue
                previous = _read_entry(old_path, namespace, schema_version, method_directory)
                if previous is None or previous[1] != slot:
                    continue
                if not safe_cache_directory(project_root, directory) or _stat_identity(destination) != current_stat or not _source_matches(source):
                    return
                if _stat_identity(old_path) != candidate["stat"]:
                    continue
                old_path.unlink()
            except OSError:
                survivors.append(candidate)
                logger.warning("preflight_cache_predecessor_locked path=%s", old_path)
        _atomic_json(index_path, _index_payload(slot, [current_entry, *survivors]))
    except (OSError, TypeError, ValueError, KeyError, RecursionError):
        logger.warning("preflight_cache_prune_skipped path=%s", destination)
