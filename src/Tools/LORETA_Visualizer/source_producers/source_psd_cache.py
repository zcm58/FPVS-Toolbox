"""Project-confined compact cache for participant source-PSD results.

Cache failures are deliberately represented as misses.  Callers may recompute
the same source-PSD method, but must not use a miss as a reason to fall back to
a different scientific method.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence
from uuid import uuid4

import numpy as np

SOURCE_PSD_CACHE_RELATIVE_ROOT = Path(".fpvs_processing") / "source_psd_cache" / "v1"
SOURCE_PSD_CACHE_FORMAT = "fpvs_source_psd_participant_cache_v1"
SOURCE_PSD_CACHE_KEY_FORMAT = "fpvs_source_psd_cache_key_v1"

CACHE_STATUS_HIT = "hit"
CACHE_STATUS_MISS_NOT_FOUND = "miss_not_found"
CACHE_STATUS_MISS_PARTIAL = "miss_partial"
CACHE_STATUS_MISS_METADATA_UNREADABLE = "miss_metadata_unreadable"
CACHE_STATUS_MISS_SCHEMA = "miss_schema"
CACHE_STATUS_MISS_KEY = "miss_key"
CACHE_STATUS_MISS_ARRAY_CHECKSUM = "miss_array_checksum"
CACHE_STATUS_MISS_ARRAYS_UNREADABLE = "miss_arrays_unreadable"
CACHE_STATUS_MISS_ARRAYS_SCHEMA = "miss_arrays_schema"
CACHE_STATUS_MISS_ARRAYS_INVALID = "miss_arrays_invalid"

_CACHE_KEY_RE = re.compile(r"^[0-9a-f]{64}$")
_DERIVATIVE_CHECKSUM_RE = re.compile(r"^[0-9a-f]{64}$")
_ARRAY_NAMES = (
    "values",
    "target_source_values",
    "noise_mean_values",
    "noise_std_values",
    "noise_offsets_used",
)
_HARMONIC_SELECTION_CACHE_BOOKKEEPING_FIELDS = frozenset(
    {
        "selection_cache_key",
        "selection_cache_saved_at",
        "selection_cache_source",
    }
)


def scientific_source_psd_method_metadata(
    method_metadata: Mapping[str, Any],
) -> dict[str, Any]:
    """Return method metadata containing only scientific cache-key inputs.

    Harmonic-selection cache provenance is retained in prepared manifests and
    sidecars, but it does not change the participant source calculation.  A
    recalculation that produces the same scientific selection should therefore
    reuse the same participant source-PSD cache entry.
    """

    normalized = _canonical_mapping(method_metadata, label="method_metadata")
    custom_metadata = normalized.get("custom_metadata")
    if not isinstance(custom_metadata, dict):
        return normalized
    harmonic_selection = custom_metadata.get("harmonic_selection")
    if not isinstance(harmonic_selection, dict):
        return normalized
    custom_metadata["harmonic_selection"] = {
        key: value
        for key, value in harmonic_selection.items()
        if key not in _HARMONIC_SELECTION_CACHE_BOOKKEEPING_FIELDS
    }
    return normalized


@dataclass(frozen=True)
class SourcePsdCacheKeyInputs:
    """Scientific inputs whose canonical JSON defines one cache key."""

    derivative_checksum_sha256: str
    numerical_model_metadata: Mapping[str, Any]
    method_metadata: Mapping[str, Any]
    frequency_metadata: Mapping[str, Any]

    def __post_init__(self) -> None:
        checksum = _validated_sha256(
            self.derivative_checksum_sha256,
            label="derivative_checksum_sha256",
            pattern=_DERIVATIVE_CHECKSUM_RE,
        )
        object.__setattr__(self, "derivative_checksum_sha256", checksum)
        object.__setattr__(
            self,
            "numerical_model_metadata",
            _canonical_mapping(self.numerical_model_metadata, label="numerical_model_metadata"),
        )
        object.__setattr__(
            self,
            "method_metadata",
            scientific_source_psd_method_metadata(self.method_metadata),
        )
        object.__setattr__(
            self,
            "frequency_metadata",
            _canonical_mapping(self.frequency_metadata, label="frequency_metadata"),
        )

    def canonical_payload(self) -> dict[str, Any]:
        """Return the JSON-safe payload hashed to form the cache key."""
        return {
            "format": SOURCE_PSD_CACHE_KEY_FORMAT,
            "derivative_checksum_sha256": self.derivative_checksum_sha256,
            "numerical_model_metadata": dict(self.numerical_model_metadata),
            "method_metadata": dict(self.method_metadata),
            "frequency_metadata": dict(self.frequency_metadata),
        }

    @property
    def cache_key(self) -> str:
        """Return a stable SHA256 over canonical scientific metadata."""
        return hashlib.sha256(_canonical_json_bytes(self.canonical_payload())).hexdigest()


@dataclass(frozen=True)
class SourcePsdParticipantResult:
    """Compact participant arrays sufficient to rebuild the existing value object."""

    participant_id: str
    values: np.ndarray
    target_source_values: np.ndarray
    noise_mean_values: np.ndarray
    noise_std_values: np.ndarray
    noise_offsets_used: tuple[int, ...]
    zero_noise_sd_source_count: int
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        participant_id = str(self.participant_id).strip()
        if not participant_id:
            raise ValueError("Source-PSD cache participant_id cannot be empty.")
        vectors = {
            "values": _finite_vector(self.values, label="values"),
            "target_source_values": _finite_vector(
                self.target_source_values,
                label="target_source_values",
            ),
            "noise_mean_values": _finite_vector(self.noise_mean_values, label="noise_mean_values"),
            "noise_std_values": _finite_vector(self.noise_std_values, label="noise_std_values"),
        }
        lengths = {len(vector) for vector in vectors.values()}
        if len(lengths) != 1:
            raise ValueError("Source-PSD cache participant vectors must have identical lengths.")
        offsets = tuple(int(value) for value in self.noise_offsets_used)
        if not offsets or len(set(offsets)) != len(offsets):
            raise ValueError("Source-PSD cache noise offsets must be non-empty and unique.")
        zero_count = int(self.zero_noise_sd_source_count)
        source_count = next(iter(lengths))
        if zero_count != self.zero_noise_sd_source_count or not 0 <= zero_count <= source_count:
            raise ValueError("zero_noise_sd_source_count must be an integer within the source count.")
        object.__setattr__(self, "participant_id", participant_id)
        for name, vector in vectors.items():
            object.__setattr__(self, name, vector)
        object.__setattr__(self, "noise_offsets_used", offsets)
        object.__setattr__(self, "zero_noise_sd_source_count", zero_count)
        object.__setattr__(self, "metadata", _canonical_mapping(self.metadata, label="metadata"))

    @property
    def source_count(self) -> int:
        return int(len(self.values))

    def to_l2_mne_participant_zscore_values(self):  # noqa: ANN201
        """Reconstruct the existing producer value object without importing it at cache load."""
        from Tools.LORETA_Visualizer.source_producers.l2_mne_hauk_zscore import (
            L2MNEHaukParticipantZScoreValues,
        )

        return L2MNEHaukParticipantZScoreValues(
            participant_id=self.participant_id,
            values=self.values.copy(),
            target_source_values=self.target_source_values.copy(),
            noise_mean_values=self.noise_mean_values.copy(),
            noise_std_values=self.noise_std_values.copy(),
            noise_offsets_used=self.noise_offsets_used,
            zero_noise_sd_source_count=self.zero_noise_sd_source_count,
        )

    @classmethod
    def from_l2_mne_participant_zscore_values(
        cls,
        values: Any,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> SourcePsdParticipantResult:
        """Copy fields from the existing producer value object into a cache result."""
        return cls(
            participant_id=values.participant_id,
            values=values.values,
            target_source_values=values.target_source_values,
            noise_mean_values=values.noise_mean_values,
            noise_std_values=values.noise_std_values,
            noise_offsets_used=tuple(values.noise_offsets_used),
            zero_noise_sd_source_count=values.zero_noise_sd_source_count,
            metadata={} if metadata is None else metadata,
        )


@dataclass(frozen=True)
class SourcePsdCachePaths:
    """Validated project-local paths for one cache key."""

    root: Path
    arrays_path: Path
    metadata_path: Path


@dataclass(frozen=True)
class SourcePsdCacheWriteResult:
    """Paths and key committed by an atomic cache write."""

    cache_key: str
    paths: SourcePsdCachePaths


@dataclass(frozen=True)
class SourcePsdCacheLookup:
    """Typed hit/miss result; corrupt entries never escape as participant values."""

    cache_key: str
    status: str
    paths: SourcePsdCachePaths
    result: SourcePsdParticipantResult | None = None
    detail: str = ""

    @property
    def hit(self) -> bool:
        return self.status == CACHE_STATUS_HIT and self.result is not None


def build_source_psd_cache_key(
    *,
    derivative_checksum_sha256: str,
    numerical_model_metadata: Mapping[str, Any],
    method_metadata: Mapping[str, Any],
    frequency_metadata: Mapping[str, Any],
) -> str:
    """Build a stable cache key from the derivative and numerical metadata."""
    return SourcePsdCacheKeyInputs(
        derivative_checksum_sha256=derivative_checksum_sha256,
        numerical_model_metadata=numerical_model_metadata,
        method_metadata=method_metadata,
        frequency_metadata=frequency_metadata,
    ).cache_key


def source_psd_cache_root(project_root: str | Path) -> Path:
    """Return the confined v1 cache root beneath an explicit project root."""
    root = Path(project_root).expanduser()
    if not root.is_absolute():
        raise ValueError("project_root must be an explicit absolute path.")
    resolved_root = root.resolve(strict=False)
    if not resolved_root.is_dir():
        raise FileNotFoundError(f"Project root does not exist: {resolved_root}")
    target = (resolved_root / SOURCE_PSD_CACHE_RELATIVE_ROOT).resolve(strict=False)
    if target == resolved_root or not target.is_relative_to(resolved_root):
        raise ValueError(f"Refusing source-PSD cache path outside the project root: {target}")
    return target


def source_psd_cache_paths(project_root: str | Path, cache_key: str) -> SourcePsdCachePaths:
    """Return confined final paths for a validated key."""
    key = _validated_sha256(cache_key, label="cache_key", pattern=_CACHE_KEY_RE)
    root = source_psd_cache_root(project_root)
    arrays_path = (root / f"{key}.npz").resolve(strict=False)
    metadata_path = (root / f"{key}.json").resolve(strict=False)
    for path in (arrays_path, metadata_path):
        if not path.is_relative_to(root):
            raise ValueError(f"Refusing source-PSD cache path outside the cache root: {path}")
    return SourcePsdCachePaths(root=root, arrays_path=arrays_path, metadata_path=metadata_path)


def store_source_psd_cache_entry(
    *,
    project_root: str | Path,
    key_inputs: SourcePsdCacheKeyInputs,
    result: SourcePsdParticipantResult,
) -> SourcePsdCacheWriteResult:
    """Atomically store compact arrays followed by their integrity metadata."""
    if not isinstance(key_inputs, SourcePsdCacheKeyInputs):
        raise TypeError("key_inputs must be SourcePsdCacheKeyInputs.")
    if not isinstance(result, SourcePsdParticipantResult):
        raise TypeError("result must be SourcePsdParticipantResult.")
    cache_key = key_inputs.cache_key
    paths = source_psd_cache_paths(project_root, cache_key)
    paths.root.mkdir(parents=True, exist_ok=True)
    token = uuid4().hex
    arrays_tmp = paths.root / f".{cache_key}.{token}.npz.tmp"
    metadata_tmp = paths.root / f".{cache_key}.{token}.json.tmp"
    try:
        _write_npz(arrays_tmp, result=result)
        arrays_checksum = _sha256_file(arrays_tmp)
        metadata = {
            "format": SOURCE_PSD_CACHE_FORMAT,
            "cache_key": cache_key,
            "key_payload": key_inputs.canonical_payload(),
            "arrays_file": paths.arrays_path.name,
            "arrays_sha256": arrays_checksum,
            "participant_id": result.participant_id,
            "source_count": result.source_count,
            "noise_offsets_used": [int(value) for value in result.noise_offsets_used],
            "zero_noise_sd_source_count": int(result.zero_noise_sd_source_count),
            "array_shapes": {
                "values": [result.source_count],
                "target_source_values": [result.source_count],
                "noise_mean_values": [result.source_count],
                "noise_std_values": [result.source_count],
                "noise_offsets_used": [len(result.noise_offsets_used)],
            },
            "result_metadata": dict(result.metadata),
        }
        _write_bytes(metadata_tmp, _canonical_json_bytes(metadata))
        os.replace(arrays_tmp, paths.arrays_path)
        os.replace(metadata_tmp, paths.metadata_path)
    finally:
        arrays_tmp.unlink(missing_ok=True)
        metadata_tmp.unlink(missing_ok=True)
    return SourcePsdCacheWriteResult(cache_key=cache_key, paths=paths)


def load_source_psd_cache_entry(
    *,
    project_root: str | Path,
    key_inputs: SourcePsdCacheKeyInputs,
) -> SourcePsdCacheLookup:
    """Load a valid compact result or return a diagnostic cache miss."""
    if not isinstance(key_inputs, SourcePsdCacheKeyInputs):
        raise TypeError("key_inputs must be SourcePsdCacheKeyInputs.")
    cache_key = key_inputs.cache_key
    paths = source_psd_cache_paths(project_root, cache_key)
    arrays_exists = paths.arrays_path.is_file()
    metadata_exists = paths.metadata_path.is_file()
    if not arrays_exists and not metadata_exists:
        return _miss(cache_key, paths, CACHE_STATUS_MISS_NOT_FOUND)
    if not arrays_exists or not metadata_exists:
        return _miss(cache_key, paths, CACHE_STATUS_MISS_PARTIAL, "Only one final cache file exists.")

    try:
        metadata = json.loads(paths.metadata_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return _miss(cache_key, paths, CACHE_STATUS_MISS_METADATA_UNREADABLE, str(exc))
    if not isinstance(metadata, dict) or metadata.get("format") != SOURCE_PSD_CACHE_FORMAT:
        return _miss(cache_key, paths, CACHE_STATUS_MISS_SCHEMA, "Cache metadata format mismatch.")
    if metadata.get("cache_key") != cache_key:
        return _miss(cache_key, paths, CACHE_STATUS_MISS_KEY, "Stored cache key mismatch.")
    try:
        stored_key_payload = _canonical_json_bytes(metadata.get("key_payload"))
        requested_key_payload = _canonical_json_bytes(key_inputs.canonical_payload())
    except (TypeError, ValueError) as exc:
        return _miss(cache_key, paths, CACHE_STATUS_MISS_KEY, str(exc))
    if stored_key_payload != requested_key_payload:
        return _miss(cache_key, paths, CACHE_STATUS_MISS_KEY, "Stored scientific key payload mismatch.")
    if metadata.get("arrays_file") != paths.arrays_path.name:
        return _miss(cache_key, paths, CACHE_STATUS_MISS_SCHEMA, "Stored arrays filename mismatch.")
    try:
        arrays_bytes = paths.arrays_path.read_bytes()
    except OSError as exc:
        return _miss(cache_key, paths, CACHE_STATUS_MISS_ARRAYS_UNREADABLE, str(exc))
    actual_arrays_checksum = hashlib.sha256(arrays_bytes).hexdigest()
    if metadata.get("arrays_sha256") != actual_arrays_checksum:
        return _miss(cache_key, paths, CACHE_STATUS_MISS_ARRAY_CHECKSUM, "Array checksum mismatch.")

    try:
        arrays = _read_npz_bytes(arrays_bytes)
    except (OSError, EOFError, ValueError, zipfile.BadZipFile) as exc:
        return _miss(cache_key, paths, CACHE_STATUS_MISS_ARRAYS_UNREADABLE, str(exc))
    if set(arrays) != set(_ARRAY_NAMES):
        return _miss(cache_key, paths, CACHE_STATUS_MISS_ARRAYS_SCHEMA, "Cached array names mismatch.")
    try:
        offsets_array = np.asarray(arrays["noise_offsets_used"])
        if offsets_array.ndim != 1 or not np.issubdtype(offsets_array.dtype, np.integer):
            raise ValueError("noise_offsets_used must be a 1D integer array.")
        offsets = tuple(int(value) for value in offsets_array.tolist())
        result = SourcePsdParticipantResult(
            participant_id=metadata["participant_id"],
            values=arrays["values"],
            target_source_values=arrays["target_source_values"],
            noise_mean_values=arrays["noise_mean_values"],
            noise_std_values=arrays["noise_std_values"],
            noise_offsets_used=offsets,
            zero_noise_sd_source_count=metadata["zero_noise_sd_source_count"],
            metadata=metadata.get("result_metadata", {}),
        )
        _validate_stored_metadata(metadata, result=result)
    except (KeyError, TypeError, ValueError) as exc:
        return _miss(cache_key, paths, CACHE_STATUS_MISS_ARRAYS_INVALID, str(exc))
    return SourcePsdCacheLookup(
        cache_key=cache_key,
        status=CACHE_STATUS_HIT,
        paths=paths,
        result=result,
    )


def cleanup_source_psd_cache_temp_files(project_root: str | Path) -> int:
    """Remove abandoned temp files; normal lookup ignores them entirely."""
    root = source_psd_cache_root(project_root)
    if not root.is_dir():
        return 0
    removed = 0
    for path in root.glob(".*.tmp"):
        if path.is_dir() and not path.is_symlink():
            continue
        path.unlink(missing_ok=True)
        removed += 1
    return removed


def _validate_stored_metadata(metadata: Mapping[str, Any], *, result: SourcePsdParticipantResult) -> None:
    if int(metadata.get("source_count", -1)) != result.source_count:
        raise ValueError("Stored source count does not match cached arrays.")
    if metadata.get("participant_id") != result.participant_id:
        raise ValueError("Stored participant ID does not match cached result.")
    if metadata.get("noise_offsets_used") != list(result.noise_offsets_used):
        raise ValueError("Stored noise offsets do not match cached arrays.")
    expected_shapes = {
        "values": [result.source_count],
        "target_source_values": [result.source_count],
        "noise_mean_values": [result.source_count],
        "noise_std_values": [result.source_count],
        "noise_offsets_used": [len(result.noise_offsets_used)],
    }
    if metadata.get("array_shapes") != expected_shapes:
        raise ValueError("Stored array shapes do not match cached arrays.")


def _write_npz(path: Path, *, result: SourcePsdParticipantResult) -> None:
    with path.open("xb") as stream:
        np.savez_compressed(
            stream,
            values=result.values,
            target_source_values=result.target_source_values,
            noise_mean_values=result.noise_mean_values,
            noise_std_values=result.noise_std_values,
            noise_offsets_used=np.asarray(result.noise_offsets_used, dtype=np.int64),
        )
        stream.flush()
        os.fsync(stream.fileno())


def _read_npz_bytes(content: bytes) -> dict[str, np.ndarray]:
    with np.load(io.BytesIO(content), allow_pickle=False) as archive:
        return {name: np.asarray(archive[name]).copy() for name in archive.files}


def _write_bytes(path: Path, content: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _miss(
    cache_key: str,
    paths: SourcePsdCachePaths,
    status: str,
    detail: str = "",
) -> SourcePsdCacheLookup:
    return SourcePsdCacheLookup(
        cache_key=cache_key,
        status=status,
        paths=paths,
        detail=str(detail),
    )


def _finite_vector(values: Sequence[float] | np.ndarray, *, label: str) -> np.ndarray:
    vector = np.asarray(values, dtype=float)
    if vector.ndim != 1 or len(vector) == 0:
        raise ValueError(f"{label} must be a non-empty 1D array.")
    if not np.all(np.isfinite(vector)):
        raise ValueError(f"{label} must contain only finite values.")
    return vector.astype(float, copy=True)


def _validated_sha256(value: Any, *, label: str, pattern: re.Pattern[str]) -> str:
    checksum = str(value).strip().lower()
    if not pattern.fullmatch(checksum):
        raise ValueError(f"{label} must be a 64-character hexadecimal SHA256 value.")
    return checksum


def _canonical_mapping(value: Mapping[str, Any], *, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be a mapping.")
    normalized = _json_safe(value)
    if not isinstance(normalized, dict):  # pragma: no cover - guarded above
        raise TypeError(f"{label} must normalize to a JSON object.")
    return normalized


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        _json_safe(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _json_safe(value: Any) -> Any:
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not np.isfinite(value):
            raise ValueError("Canonical cache metadata cannot contain NaN or infinity.")
        return value
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("Canonical cache metadata object keys must be strings.")
            result[key] = _json_safe(item)
        return result
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    raise TypeError(f"Unsupported canonical cache metadata value: {type(value).__name__}")


__all__ = [
    "CACHE_STATUS_HIT",
    "CACHE_STATUS_MISS_ARRAYS_INVALID",
    "CACHE_STATUS_MISS_ARRAYS_SCHEMA",
    "CACHE_STATUS_MISS_ARRAYS_UNREADABLE",
    "CACHE_STATUS_MISS_ARRAY_CHECKSUM",
    "CACHE_STATUS_MISS_KEY",
    "CACHE_STATUS_MISS_METADATA_UNREADABLE",
    "CACHE_STATUS_MISS_NOT_FOUND",
    "CACHE_STATUS_MISS_PARTIAL",
    "CACHE_STATUS_MISS_SCHEMA",
    "SOURCE_PSD_CACHE_FORMAT",
    "SOURCE_PSD_CACHE_KEY_FORMAT",
    "SOURCE_PSD_CACHE_RELATIVE_ROOT",
    "SourcePsdCacheKeyInputs",
    "SourcePsdCacheLookup",
    "SourcePsdCachePaths",
    "SourcePsdCacheWriteResult",
    "SourcePsdParticipantResult",
    "build_source_psd_cache_key",
    "cleanup_source_psd_cache_temp_files",
    "load_source_psd_cache_entry",
    "source_psd_cache_paths",
    "source_psd_cache_root",
    "scientific_source_psd_method_metadata",
    "store_source_psd_cache_entry",
]
