"""Project-manifest cache helpers for Stats group-significant harmonics."""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from Main_App.projects.preprocessing_settings import (
    PREPROCESSING_CANONICAL_KEYS,
    normalize_preprocessing_settings,
)
from Main_App.projects.project import PROJECT_SCHEMA_VERSION
from Tools.Stats.analysis.dv_policy_settings import (
    DVPolicySettings,
    LOCKED_ODDBALL_FREQUENCY_HZ,
)

logger = logging.getLogger(__name__)

CACHE_SCHEMA_VERSION = 1
CACHE_MAX_ENTRIES = 8
CACHE_MANIFEST_PATH = ("tools", "stats", "group_significant_harmonics_cache")
GROUP_HARMONIC_METHOD_VERSION = "group_significant_harmonics_v1"
PREPROCESSING_ORDER_VERSION_LABEL = "filter_then_downsample_v1"
PROCESSING_FINGERPRINT_VERSION_LABEL = "processing_fingerprint_v4_removed_electrode_qc"


@dataclass(frozen=True)
class WorkbookFingerprint:
    subject: str
    condition: str
    path: str
    size_bytes: int | None
    mtime_ns: int | None

    def to_manifest(self) -> dict[str, object]:
        return {
            "subject": self.subject,
            "condition": self.condition,
            "path": self.path,
            "size_bytes": self.size_bytes,
            "mtime_ns": self.mtime_ns,
        }


@dataclass(frozen=True)
class GroupHarmonicCacheRequest:
    project_root: Path
    manifest_path: Path
    cache_key: str
    fingerprint: dict[str, object]
    project_processing_signature: dict[str, object]
    project_processing_signature_hash: str
    ledger_warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class GroupHarmonicCacheHit:
    cache_key: str
    saved_at: str
    selection_metadata: dict[str, object]


@dataclass(frozen=True)
class GroupHarmonicCacheLookup:
    hit: GroupHarmonicCacheHit | None
    reason: str


def build_group_harmonic_cache_request(
    *,
    project_root: str | Path | None,
    subjects: Sequence[object],
    conditions: Sequence[object],
    subject_data: Mapping[str, Mapping[str, str]],
    base_frequency_hz: float,
    max_freq_hz: float | None,
    settings: DVPolicySettings,
) -> GroupHarmonicCacheRequest | None:
    """Build the exact manifest-cache request for the current Stats selection."""

    if project_root in (None, ""):
        return None
    root = Path(project_root).resolve()
    manifest_path = root / "project.json"
    manifest = _read_manifest(manifest_path)
    if manifest is None:
        return None
    subject_key = tuple(str(subject) for subject in subjects)
    condition_key = tuple(str(condition) for condition in conditions)
    processing_signature = build_project_processing_signature(manifest)
    processing_signature_hash = _hash_payload(processing_signature)
    workbooks = [
        _workbook_fingerprint(
            root,
            subject=subject,
            condition=condition,
            file_path=(subject_data.get(subject, {}) or {}).get(condition),
        ).to_manifest()
        for subject in subject_key
        for condition in condition_key
    ]
    fingerprint: dict[str, object] = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "method_version": GROUP_HARMONIC_METHOD_VERSION,
        "selection_inputs": {
            "subjects": list(subject_key),
            "conditions": list(condition_key),
        },
        "source_workbooks": workbooks,
        "stats_settings": {
            "base_frequency_hz": float(base_frequency_hz),
            "oddball_frequency_hz": float(LOCKED_ODDBALL_FREQUENCY_HZ),
            "max_freq_hz": float(max_freq_hz) if max_freq_hz is not None else None,
            "z_threshold": float(settings.group_significant_z_threshold),
            "electrode_scope": str(settings.group_significant_electrode_scope),
        },
        "project_processing_signature": processing_signature,
        "project_processing_signature_hash": processing_signature_hash,
    }
    cache_key = _hash_payload(fingerprint)
    return GroupHarmonicCacheRequest(
        project_root=root,
        manifest_path=manifest_path,
        cache_key=cache_key,
        fingerprint=fingerprint,
        project_processing_signature=processing_signature,
        project_processing_signature_hash=processing_signature_hash,
        ledger_warnings=_processing_ledger_warnings(root, subject_key),
    )


def build_project_processing_signature(manifest: Mapping[str, object] | None) -> dict[str, object]:
    """Return the project settings identity that invalidates saved harmonics."""

    source = manifest if isinstance(manifest, Mapping) else {}
    preprocessing_raw = source.get("preprocessing")
    preprocessing = normalize_preprocessing_settings(
        preprocessing_raw if isinstance(preprocessing_raw, Mapping) else {}
    )
    canonical_preprocessing = {
        key: _json_safe(preprocessing.get(key))
        for key in PREPROCESSING_CANONICAL_KEYS
    }
    event_map_raw = source.get("event_map")
    event_map: dict[str, int] = {}
    if isinstance(event_map_raw, Mapping):
        for key, value in event_map_raw.items():
            try:
                event_map[str(key)] = int(value)
            except (TypeError, ValueError):
                continue
    return {
        "project_schema_version": str(source.get("schema_version") or PROJECT_SCHEMA_VERSION),
        "preprocessing_order_version": PREPROCESSING_ORDER_VERSION_LABEL,
        "processing_fingerprint_version": PROCESSING_FINGERPRINT_VERSION_LABEL,
        "preprocessing": canonical_preprocessing,
        "event_map": dict(sorted(event_map.items())),
    }


def project_processing_signature_hash(project_root: str | Path | None) -> str | None:
    """Return the current project processing signature hash for in-memory caches."""

    if project_root in (None, ""):
        return None
    manifest = _read_manifest(Path(project_root).resolve() / "project.json")
    if manifest is None:
        return None
    return _hash_payload(build_project_processing_signature(manifest))


def lookup_cached_group_harmonic_selection(
    request: GroupHarmonicCacheRequest | None,
) -> GroupHarmonicCacheLookup:
    """Return a saved selection metadata match for this request, if any."""

    if request is None:
        return GroupHarmonicCacheLookup(hit=None, reason="No project manifest cache context.")
    manifest = _read_manifest(request.manifest_path)
    cache = _cache_from_manifest(manifest)
    entries = cache.get("entries")
    if not isinstance(entries, Mapping):
        return GroupHarmonicCacheLookup(hit=None, reason="No saved group-significant harmonics.")
    entry = entries.get(request.cache_key)
    if isinstance(entry, Mapping):
        selection_metadata = entry.get("selection_metadata")
        if isinstance(selection_metadata, Mapping):
            saved_at = str(entry.get("saved_at") or "")
            return GroupHarmonicCacheLookup(
                hit=GroupHarmonicCacheHit(
                    cache_key=request.cache_key,
                    saved_at=saved_at,
                    selection_metadata=copy.deepcopy(dict(selection_metadata)),
                ),
                reason="Saved harmonics match current inputs.",
            )
    return GroupHarmonicCacheLookup(
        hit=None,
        reason=_cache_miss_reason(entries, request),
    )


def save_cached_group_harmonic_selection(
    request: GroupHarmonicCacheRequest | None,
    selection_metadata: Mapping[str, object],
) -> str | None:
    """Persist a successful group-significant selection in project.json."""

    if request is None:
        return None
    manifest = _read_manifest(request.manifest_path)
    if manifest is None:
        return None
    cache = _cache_from_manifest(manifest)
    entries = cache.get("entries")
    if not isinstance(entries, dict):
        entries = {}
    saved_at = _now_utc_iso()
    entry = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "cache_key": request.cache_key,
        "saved_at": saved_at,
        "fingerprint": _json_safe(request.fingerprint),
        "project_processing_signature": _json_safe(request.project_processing_signature),
        "project_processing_signature_hash": request.project_processing_signature_hash,
        "selected_harmonics_hz": _json_safe(selection_metadata.get("selected_harmonics_hz", [])),
        "highest_significant_harmonic_hz": _json_safe(
            selection_metadata.get("highest_significant_harmonic_hz")
        ),
        "highest_significant_harmonic_index": _json_safe(
            selection_metadata.get("highest_significant_harmonic_index")
        ),
        "selection_metadata": _json_safe(dict(selection_metadata)),
    }
    entries[request.cache_key] = entry
    _prune_entries(entries)
    cache["schema_version"] = CACHE_SCHEMA_VERSION
    cache["entries"] = entries
    _set_manifest_cache(manifest, cache)
    _write_manifest_if_changed(request.manifest_path, manifest)
    return saved_at


def clear_cached_group_harmonic_selections(project_root: str | Path | None) -> int:
    """Clear saved group-significant harmonic entries for the project."""

    if project_root in (None, ""):
        return 0
    manifest_path = Path(project_root).resolve() / "project.json"
    manifest = _read_manifest(manifest_path)
    if manifest is None:
        return 0
    cache = _cache_from_manifest(manifest)
    entries = cache.get("entries")
    count = len(entries) if isinstance(entries, Mapping) else 0
    cache["schema_version"] = CACHE_SCHEMA_VERSION
    cache["entries"] = {}
    _set_manifest_cache(manifest, cache)
    _write_manifest_if_changed(manifest_path, manifest)
    return int(count)


def _workbook_fingerprint(
    project_root: Path,
    *,
    subject: str,
    condition: str,
    file_path: str | None,
) -> WorkbookFingerprint:
    if not file_path:
        return WorkbookFingerprint(str(subject), str(condition), "", None, None)
    path = Path(file_path)
    try:
        resolved = path.resolve(strict=False)
    except OSError:
        resolved = path
    path_value = _manifest_safe_path(project_root, resolved)
    try:
        stat = path.stat()
    except OSError:
        return WorkbookFingerprint(str(subject), str(condition), path_value, None, None)
    return WorkbookFingerprint(
        str(subject),
        str(condition),
        path_value,
        int(stat.st_size),
        int(stat.st_mtime_ns),
    )


def _manifest_safe_path(project_root: Path, path: Path) -> str:
    try:
        resolved_root = project_root.resolve()
        resolved_path = path.resolve(strict=False)
        if resolved_path == resolved_root or resolved_root in resolved_path.parents:
            return str(resolved_path.relative_to(resolved_root))
        return str(resolved_path)
    except OSError:
        return str(path)


def _processing_ledger_warnings(project_root: Path, subjects: Sequence[str]) -> tuple[str, ...]:
    ledger_path = project_root / ".fpvs_processing" / "processing_ledger.json"
    if not ledger_path.exists():
        return ()
    try:
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ("Processing ledger could not be read; verify Excel outputs are current.",)
    entries = ledger.get("entries") if isinstance(ledger, Mapping) else None
    if not isinstance(entries, Mapping):
        return ()
    stale_subjects: list[str] = []
    incomplete_subjects: list[str] = []
    for subject in subjects:
        entry = entries.get(subject) or entries.get(str(subject).upper())
        if not isinstance(entry, Mapping):
            continue
        if entry.get("processing_fingerprint_version") != PROCESSING_FINGERPRINT_VERSION_LABEL:
            stale_subjects.append(str(subject))
        if entry.get("status") not in (None, "completed"):
            incomplete_subjects.append(str(subject))
    warnings: list[str] = []
    if stale_subjects:
        warnings.append(
            "Processing metadata version changed for selected participant(s); "
            "rerun preprocessing before relying on Stats output: "
            + ", ".join(stale_subjects[:12])
        )
    if incomplete_subjects:
        warnings.append(
            "Processing ledger does not mark selected participant(s) complete; "
            "verify preprocessing outputs before relying on Stats output: "
            + ", ".join(incomplete_subjects[:12])
        )
    return tuple(warnings)


def _cache_miss_reason(
    entries: Mapping[object, object],
    request: GroupHarmonicCacheRequest,
) -> str:
    if not entries:
        return "No saved group-significant harmonics."
    current = request.fingerprint
    current_without_processing = _fingerprint_without_processing(current)
    for entry in entries.values():
        if not isinstance(entry, Mapping):
            continue
        fingerprint = entry.get("fingerprint")
        if not isinstance(fingerprint, Mapping):
            continue
        if _fingerprint_without_processing(fingerprint) == current_without_processing:
            return (
                "Project preprocessing/settings changed since saved harmonics; "
                "recalculating group-level significant harmonics."
            )
        if _selection_inputs(fingerprint) == _selection_inputs(current):
            if _stats_settings(fingerprint) != _stats_settings(current):
                return "Stats harmonic settings changed since saved harmonics; recalculating."
            if _source_workbooks(fingerprint) != _source_workbooks(current):
                return "Source workbook files changed since saved harmonics; recalculating."
    return "Saved harmonics do not match current participants, conditions, settings, or workbooks."


def _fingerprint_without_processing(fingerprint: Mapping[str, object]) -> dict[str, object]:
    out = dict(fingerprint)
    out.pop("project_processing_signature", None)
    out.pop("project_processing_signature_hash", None)
    return _json_safe(out)


def _selection_inputs(fingerprint: Mapping[str, object]) -> object:
    return _json_safe(fingerprint.get("selection_inputs"))


def _stats_settings(fingerprint: Mapping[str, object]) -> object:
    return _json_safe(fingerprint.get("stats_settings"))


def _source_workbooks(fingerprint: Mapping[str, object]) -> object:
    return _json_safe(fingerprint.get("source_workbooks"))


def _cache_from_manifest(manifest: Mapping[str, object] | None) -> dict[str, object]:
    current: object = manifest
    for key in CACHE_MANIFEST_PATH:
        if not isinstance(current, Mapping):
            return {"schema_version": CACHE_SCHEMA_VERSION, "entries": {}}
        current = current.get(key)
    if not isinstance(current, Mapping):
        return {"schema_version": CACHE_SCHEMA_VERSION, "entries": {}}
    cache = dict(current)
    if not isinstance(cache.get("entries"), dict):
        cache["entries"] = {}
    cache["schema_version"] = CACHE_SCHEMA_VERSION
    return cache


def _set_manifest_cache(manifest: dict[str, object], cache: Mapping[str, object]) -> None:
    node = manifest
    for key in CACHE_MANIFEST_PATH[:-1]:
        child = node.get(key)
        if not isinstance(child, dict):
            child = {}
            node[key] = child
        node = child
    node[CACHE_MANIFEST_PATH[-1]] = dict(cache)


def _prune_entries(entries: dict[str, object]) -> None:
    while len(entries) > CACHE_MAX_ENTRIES:
        oldest_key = min(
            entries,
            key=lambda key: str((entries.get(key) if isinstance(entries.get(key), Mapping) else {}).get("saved_at", "")),
        )
        entries.pop(oldest_key, None)


def _read_manifest(manifest_path: Path) -> dict[str, object] | None:
    if not manifest_path.is_file():
        return None
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to read project manifest for harmonic cache: %s", exc)
        return None
    return data if isinstance(data, dict) else None


def _write_manifest_if_changed(manifest_path: Path, data: Mapping[str, object]) -> None:
    payload = _json_safe(dict(data))
    new_compact = json.dumps(payload, separators=(",", ":"), sort_keys=True, ensure_ascii=False)
    if manifest_path.exists():
        try:
            current = json.loads(manifest_path.read_text(encoding="utf-8"))
            current_compact = json.dumps(
                _json_safe(current if isinstance(current, dict) else {}),
                separators=(",", ":"),
                sort_keys=True,
                ensure_ascii=False,
            )
            if current_compact == new_compact:
                return
        except (OSError, json.JSONDecodeError):
            pass
    tmp_path = manifest_path.with_name(f"{manifest_path.name}.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp_path.replace(manifest_path)


def _json_safe(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return float(value) if math.isfinite(value) else None
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return str(value)
    return float(number) if math.isfinite(number) else None


def _hash_payload(payload: object) -> str:
    encoded = json.dumps(_json_safe(payload), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _now_utc_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
