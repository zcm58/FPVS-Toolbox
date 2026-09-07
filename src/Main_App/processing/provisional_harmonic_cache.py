"""Short-lived scientific evidence reuse across one frequency-QC review loop.

The caller owns this cache and clears it when the review workflow ends. It
never saves reports or decisions, and writes no project files.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import asdict, is_dataclass
import hashlib
import json
import logging
from pathlib import Path
import struct
from threading import RLock
from time import perf_counter
from typing import Any

logger = logging.getLogger(__name__)
PROVISIONAL_HARMONIC_CACHE_VERSION = "frequency_qc_provisional_evidence_v1"
_MAX_ENTRIES = 2
_Result = tuple[tuple[float, ...], dict[str, object]]


class ProvisionalHarmonicCache:
    """Own at most two detached provisional selections for one review workflow."""

    def __init__(self) -> None:
        self._entries: OrderedDict[str, tuple[str, _Result]] = OrderedDict()
        self._lock = RLock()
        self._generation = 0

    def clear(self) -> None:
        """Release evidence, including a computation still finishing elsewhere."""

        with self._lock:
            self._entries.clear()
            self._generation += 1

    def resolve(self, compute: Callable[..., _Result], **inputs: Any) -> _Result:
        """Reuse only matching source bytes, ordered inputs and scientific state."""

        started = perf_counter()
        with self._lock:
            generation = self._generation
        key = _request_key_or_none(inputs)
        if key is not None:
            with self._lock:
                entry = self._entries.get(key)
                if entry is not None:
                    digest, evidence = entry
                    try:
                        intact = digest == _digest(evidence)
                    except (TypeError, ValueError):
                        intact = False
                    if intact:
                        self._entries.move_to_end(key)
                        result = deepcopy(evidence)
                        _log_cache("hit", started)
                        return result
                    del self._entries[key]
        result = compute(**inputs)
        # Do not publish evidence if an input changed while it was computed.
        if key is not None and _request_key_or_none(inputs) == key:
            evidence = deepcopy(result)
            try:
                digest = _digest(evidence)
            except (TypeError, ValueError):
                _log_cache("bypass", started)
                return result
            with self._lock:
                if generation == self._generation:
                    self._entries[key] = (digest, evidence)
                    self._entries.move_to_end(key)
                    while len(self._entries) > _MAX_ENTRIES:
                        self._entries.popitem(last=False)
        _log_cache("miss" if key is not None else "bypass", started)
        return result


def _log_cache(status: str, started: float) -> None:
    logger.info(
        "frequency_domain_qc_provisional_cache status=%s elapsed_s=%.3f",
        status, perf_counter() - started,
    )


def _request_key_or_none(inputs: Mapping[str, Any]) -> str | None:
    try:
        return _request_key(inputs)
    except (OSError, ValueError, TypeError, KeyError):
        # Cache eligibility must never replace the computation's own failures
        # or its normal source-integrity diagnostics.
        logger.debug("frequency_domain_qc_provisional_cache_ineligible", exc_info=True)
        return None


def _request_key(inputs: Mapping[str, Any]) -> str:
    from Tools.Stats.data.group_harmonic_cache import (
        GROUP_HARMONIC_METHOD_VERSION,
        REPEATED_SESSION_POOLING_METHOD_VERSION,
        build_project_processing_signature,
    )

    root = Path(inputs["project_root"]).resolve()
    with (root / "project.json").open(encoding="utf-8") as stream:
        manifest = json.load(stream)
    processing = build_project_processing_signature(manifest)
    # Current effective cohort/electrode decisions are explicit inputs. Review
    # timestamps, Retain receipts and workflow status do not alter the signal.
    processing.pop("frequency_domain_qc", None)
    project_context = {
        field: manifest.get(field)
        for field in (
            "schema_version", "recording_mode", "groups", "participants",
            "recordings", "sessions",
        )
    }
    sources = []
    for subject in inputs["subjects"]:
        for condition in inputs["conditions"]:
            path = inputs["subject_data"].get(subject, {}).get(condition)
            sources.append((subject, condition, _source_identity(Path(path)) if path else None))
    return _digest({
        "version": PROVISIONAL_HARMONIC_CACHE_VERSION,
        "harmonic_method": GROUP_HARMONIC_METHOD_VERSION,
        "repeated_pooling_method": REPEATED_SESSION_POOLING_METHOD_VERSION,
        "project_root": str(root),
        "project_context": project_context,
        "processing": processing,
        "inputs": {key: value for key, value in inputs.items() if key != "log_func"},
        "sources": sources,
    })


def _source_identity(path: Path) -> tuple[object, ...]:
    from Main_App.io import condition_companion_identity, spectral_companion_identity
    from Main_App.io.result_manifest import is_result_manifest, read_result_manifest

    anchor = _file_identity(path)
    if is_result_manifest(path):
        declaration = read_result_manifest(path)
        companions = (
            declaration["spectral_companion"], declaration["condition_companion"],
        )
    else:
        companions = (spectral_companion_identity(path), condition_companion_identity(path))
    identities = []
    for descriptor in companions:
        if descriptor is None:
            identities.append(None)
            continue
        companion = path.with_name(descriptor["path"])
        identity = _file_identity(companion)
        if identity[-1] != descriptor["sha256"] or identity[1] != descriptor["size_bytes"]:
            raise ValueError("Processed companion bytes do not match their declaration.")
        identities.append((descriptor, identity))
    if _file_identity(path) != anchor:
        raise ValueError("Processed result changed while its evidence identity was read.")
    return anchor, tuple(identities)


def _file_identity(path: Path) -> tuple[str, int, int, int, str]:
    before = path.stat()
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    after = path.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
        after.st_size, after.st_mtime_ns, after.st_ctime_ns,
    ):
        raise ValueError("Processed source changed while its content was hashed.")
    return str(path.resolve()), after.st_size, after.st_mtime_ns, after.st_ctime_ns, digest


def _digest(value: object) -> str:
    encoded = json.dumps(_identity_value(value), ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _identity_value(value: object) -> object:
    """Preserve float bits, container types and scientifically relevant ordering."""

    if is_dataclass(value) and not isinstance(value, type):
        return ["dataclass", type(value).__qualname__, _identity_value(asdict(value))]
    if isinstance(value, Mapping):
        return ["mapping", [[_identity_value(key), _identity_value(item)] for key, item in value.items()]]
    if isinstance(value, (tuple, list)):
        return [type(value).__name__, [_identity_value(item) for item in value]]
    if isinstance(value, (set, frozenset)):
        return ["set", sorted((_identity_value(item) for item in value), key=repr)]
    if isinstance(value, Path):
        return ["path", str(value.resolve())]
    if isinstance(value, float):
        return ["float", struct.pack(">d", value).hex()]
    if value is None or isinstance(value, (str, int, bool)):
        return [type(value).__name__, value]
    raise TypeError(f"Unsupported provisional evidence identity value: {type(value).__name__}")
