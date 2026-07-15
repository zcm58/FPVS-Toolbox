"""Project-local cache primitives for condition-aware preflight QC.

The cache is intentionally independent of project models, BDF readers, and GUI
code.  Callers provide every input that affects a QC result, including the raw
file identity and resolved event plan.  This module only fingerprints those
inputs and persists the matching JSON result beneath the explicit project root.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PREFLIGHT_QC_CACHE_SCHEMA_VERSION = 1
PREFLIGHT_QC_CACHE_METHOD_DIRECTORY = "v2"
PREFLIGHT_QC_CACHE_RELATIVE_DIRECTORY = (
    Path(".fpvs_processing")
    / "preflight_qc"
    / PREFLIGHT_QC_CACHE_METHOD_DIRECTORY
)
_CACHE_WRITE_LOCK = threading.Lock()


def preflight_qc_cache_directory(project_root: Path) -> Path:
    """Return the v2 cache directory beneath an explicit absolute project root."""

    root = Path(project_root)
    if not root.is_absolute():
        raise ValueError("project_root must be an explicit absolute path")
    return root / PREFLIGHT_QC_CACHE_RELATIVE_DIRECTORY


def _canonical_json(value: object) -> str:
    """Serialize JSON-compatible data deterministically and strictly."""

    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _json_snapshot(value: object) -> Any:
    """Detach caller-owned containers and normalize tuples to JSON arrays."""

    return json.loads(_canonical_json(value))


def _cache_key_payload(
    *,
    file_identity: Mapping[str, object],
    settings: Mapping[str, object],
    method: Mapping[str, object],
    event_plan: Sequence[Mapping[str, object]] | Mapping[str, object],
) -> dict[str, Any]:
    return _json_snapshot(
        {
            "file_identity": dict(file_identity),
            "settings": dict(settings),
            "method": dict(method),
            "event_plan": event_plan,
        }
    )


def build_preflight_qc_cache_fingerprint(
    *,
    file_identity: Mapping[str, object],
    settings: Mapping[str, object],
    method: Mapping[str, object],
    event_plan: Sequence[Mapping[str, object]] | Mapping[str, object],
) -> str:
    """Return a deterministic SHA-256 key for all caller-supplied QC inputs."""

    payload = _cache_key_payload(
        file_identity=file_identity,
        settings=settings,
        method=method,
        event_plan=event_plan,
    )
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def preflight_qc_cache_path(
    project_root: Path,
    *,
    file_identity: Mapping[str, object],
    settings: Mapping[str, object],
    method: Mapping[str, object],
    event_plan: Sequence[Mapping[str, object]] | Mapping[str, object],
) -> Path:
    """Return the cache path without creating project directories."""

    fingerprint = build_preflight_qc_cache_fingerprint(
        file_identity=file_identity,
        settings=settings,
        method=method,
        event_plan=event_plan,
    )
    return preflight_qc_cache_directory(project_root) / f"{fingerprint}.json"


def load_preflight_qc_cache(
    project_root: Path,
    *,
    file_identity: Mapping[str, object],
    settings: Mapping[str, object],
    method: Mapping[str, object],
    event_plan: Sequence[Mapping[str, object]] | Mapping[str, object],
) -> dict[str, Any] | None:
    """Return a validated cached result, or ``None`` for every cache miss."""

    key_payload = _cache_key_payload(
        file_identity=file_identity,
        settings=settings,
        method=method,
        event_plan=event_plan,
    )
    fingerprint = hashlib.sha256(
        _canonical_json(key_payload).encode("utf-8")
    ).hexdigest()
    path = preflight_qc_cache_directory(project_root) / f"{fingerprint}.json"
    if not path.is_file():
        return None

    try:
        envelope = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        logger.warning(
            "preflight_qc_cache_unreadable path=%s error=%s",
            path,
            exc,
        )
        return None

    if not isinstance(envelope, dict):
        return None
    if envelope.get("schema_version") != PREFLIGHT_QC_CACHE_SCHEMA_VERSION:
        return None
    if envelope.get("fingerprint") != fingerprint:
        return None
    if envelope.get("key") != key_payload:
        return None

    result = envelope.get("result")
    if not isinstance(result, dict):
        return None
    return result


def save_preflight_qc_cache(
    project_root: Path,
    *,
    file_identity: Mapping[str, object],
    settings: Mapping[str, object],
    method: Mapping[str, object],
    event_plan: Sequence[Mapping[str, object]] | Mapping[str, object],
    result: Mapping[str, object],
) -> Path:
    """Atomically save one JSON QC result and return its project-local path."""

    key_payload = _cache_key_payload(
        file_identity=file_identity,
        settings=settings,
        method=method,
        event_plan=event_plan,
    )
    result_payload = _json_snapshot(dict(result))
    fingerprint = hashlib.sha256(
        _canonical_json(key_payload).encode("utf-8")
    ).hexdigest()
    cache_directory = preflight_qc_cache_directory(project_root)
    destination = cache_directory / f"{fingerprint}.json"
    envelope = {
        "schema_version": PREFLIGHT_QC_CACHE_SCHEMA_VERSION,
        "fingerprint": fingerprint,
        "key": key_payload,
        "result": result_payload,
    }
    serialized = json.dumps(
        envelope,
        sort_keys=True,
        indent=2,
        ensure_ascii=False,
        allow_nan=False,
    ) + "\n"

    with _CACHE_WRITE_LOCK:
        cache_directory.mkdir(parents=True, exist_ok=True)
        file_descriptor, temporary_name = tempfile.mkstemp(
            dir=cache_directory,
            prefix=f".{fingerprint}.",
            suffix=".tmp",
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(
                file_descriptor,
                "w",
                encoding="utf-8",
                newline="\n",
            ) as stream:
                stream.write(serialized)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, destination)
        finally:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                logger.warning(
                    "preflight_qc_cache_temp_cleanup_failed path=%s",
                    temporary_path,
                )

    return destination


__all__ = [
    "PREFLIGHT_QC_CACHE_METHOD_DIRECTORY",
    "PREFLIGHT_QC_CACHE_RELATIVE_DIRECTORY",
    "PREFLIGHT_QC_CACHE_SCHEMA_VERSION",
    "build_preflight_qc_cache_fingerprint",
    "load_preflight_qc_cache",
    "preflight_qc_cache_directory",
    "preflight_qc_cache_path",
    "save_preflight_qc_cache",
]
