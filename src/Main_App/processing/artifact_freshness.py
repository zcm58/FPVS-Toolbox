"""Project-local freshness tracking for harmonic-selection derivatives.

The original processed condition workbooks and their FullFFT sheets are source
artifacts.  They are deliberately outside this registry: changing the common
Summed-BCA harmonic definition must only invalidate outputs derived from that
definition.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import tempfile
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

ARTIFACT_FRESHNESS_SCHEMA_VERSION = 1
ARTIFACT_FRESHNESS_MANIFEST_PATH = (
    "tools",
    "post_processing",
    "artifact_freshness",
)

HARMONIC_SELECTION_SUMMARY_ARTIFACT = "harmonic_selection_summary"
STATS_READY_SUMMED_BCA_ARTIFACT = "stats_ready_summed_bca"
ANALYSIS_READY_FULL_AUDIT_ARTIFACT = "analysis_ready_full_audit"
L2_MNE_SOURCE_PSD_ARTIFACT = "l2_mne_source_psd"
ELORETA_VOLUME_SOURCE_PSD_ARTIFACT = "eloreta_volume_source_psd"

SELECTION_DEPENDENT_ARTIFACTS = (
    STATS_READY_SUMMED_BCA_ARTIFACT,
    ANALYSIS_READY_FULL_AUDIT_ARTIFACT,
    L2_MNE_SOURCE_PSD_ARTIFACT,
    ELORETA_VOLUME_SOURCE_PSD_ARTIFACT,
)

ARTIFACT_STATUS_CURRENT = "current"
ARTIFACT_STATUS_STALE = "stale"
ARTIFACT_STATUS_FAILED = "failed"
_VALID_ARTIFACT_STATUSES = {
    ARTIFACT_STATUS_CURRENT,
    ARTIFACT_STATUS_STALE,
    ARTIFACT_STATUS_FAILED,
}

_DEFAULT_ARTIFACT_PATHS = {
    HARMONIC_SELECTION_SUMMARY_ARTIFACT: Path("Quality Check")
    / "Harmonic_Selection_Summary.xlsx",
    STATS_READY_SUMMED_BCA_ARTIFACT: Path("3 - Statistical Analysis Results")
    / "Stats_Ready_Summed_BCA.xlsx",
    ANALYSIS_READY_FULL_AUDIT_ARTIFACT: Path("3 - Statistical Analysis Results")
    / "Analysis_Ready_Summed_BCA_Full_Audit.xlsx",
    L2_MNE_SOURCE_PSD_ARTIFACT: Path("6 - Source Localization")
    / "L2-MNE Hauk Source PSD Beta",
    ELORETA_VOLUME_SOURCE_PSD_ARTIFACT: Path("6 - Source Localization")
    / "eLORETA Hauk Source PSD Beta",
}

_LEGACY_FINGERPRINT_IGNORED_KEYS = {
    "selection_cache_source",
    "selection_cache_saved_at",
    "selection_cache_key",
    "selection_fingerprint",
    "canonical_selection_fingerprint",
    "methods_summary",
}


@dataclass(frozen=True, slots=True)
class ArtifactFreshnessRecord:
    artifact_id: str
    status: str
    path: str
    built_from_selection_fingerprint: str | None
    required_selection_fingerprint: str | None
    updated_at: str
    reason: str = ""
    last_error: str = ""
    archives: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ArtifactFreshnessRegistry:
    selection_fingerprint: str | None
    artifacts: dict[str, ArtifactFreshnessRecord]
    updated_at: str


@dataclass(frozen=True, slots=True)
class SelectionFreshnessTransition:
    previous_fingerprint: str | None
    selection_fingerprint: str
    changed: bool
    stale_artifact_ids: tuple[str, ...]


class StalePostProcessingArtifactError(RuntimeError):
    """Raised when a consumer tries to load a stale canonical derivative."""


def canonical_artifact_path(
    project_root: str | Path,
    artifact_id: str,
) -> Path:
    """Return the project-local canonical path for a tracked artifact."""

    root, _manifest_path = _project_paths(project_root, require_manifest=False)
    try:
        relative_path = _DEFAULT_ARTIFACT_PATHS[str(artifact_id)]
    except KeyError as exc:
        raise ValueError(f"Unknown post-processing artifact: {artifact_id}") from exc
    return root / relative_path


def selection_fingerprint_from_metadata(
    selection_metadata: Mapping[str, object],
    *,
    allow_legacy_migration: bool = True,
) -> str:
    """Return the canonical selection fingerprint from accepted metadata.

    New processing code must publish ``selection_fingerprint``.  The cache-key
    and deterministic metadata-hash branches exist only so an older project can
    enter the freshness registry before it is recalculated in the new schema.
    """

    fingerprint = str(selection_metadata.get("selection_fingerprint") or "").strip()
    if fingerprint:
        return fingerprint
    if not allow_legacy_migration:
        raise ValueError(
            "Accepted harmonic-selection metadata has no selection_fingerprint."
        )

    legacy_key = str(selection_metadata.get("selection_cache_key") or "").strip()
    if legacy_key:
        return f"legacy-cache:{legacy_key}"

    legacy_payload = {
        str(key): value
        for key, value in selection_metadata.items()
        if str(key) not in _LEGACY_FINGERPRINT_IGNORED_KEYS
    }
    if not legacy_payload:
        raise ValueError("Harmonic-selection metadata is empty.")
    return "legacy-metadata:" + _hash_payload(legacy_payload)


def load_artifact_freshness_registry(
    project_root: str | Path,
) -> ArtifactFreshnessRegistry:
    """Load the current registry without creating or changing project files."""

    root, manifest_path = _project_paths(project_root, require_manifest=False)
    if not manifest_path.is_file():
        return ArtifactFreshnessRegistry(None, {}, "")
    manifest = _read_manifest_required(manifest_path)
    raw_registry = _registry_from_manifest(manifest)
    raw_artifacts = raw_registry.get("artifacts")
    records: dict[str, ArtifactFreshnessRecord] = {}
    if isinstance(raw_artifacts, Mapping):
        for raw_id, raw_record in raw_artifacts.items():
            if not isinstance(raw_record, Mapping):
                continue
            artifact_id = str(raw_id)
            status = str(raw_record.get("status") or "")
            if status not in _VALID_ARTIFACT_STATUSES:
                continue
            raw_archives = raw_record.get("archives")
            archives = (
                tuple(str(value) for value in raw_archives)
                if isinstance(raw_archives, (list, tuple))
                else ()
            )
            records[artifact_id] = ArtifactFreshnessRecord(
                artifact_id=artifact_id,
                status=status,
                path=str(raw_record.get("path") or ""),
                built_from_selection_fingerprint=_optional_text(
                    raw_record.get("built_from_selection_fingerprint")
                ),
                required_selection_fingerprint=_optional_text(
                    raw_record.get("required_selection_fingerprint")
                ),
                updated_at=str(raw_record.get("updated_at") or ""),
                reason=str(raw_record.get("reason") or ""),
                last_error=str(raw_record.get("last_error") or ""),
                archives=archives,
            )
    _ = root
    return ArtifactFreshnessRegistry(
        selection_fingerprint=_optional_text(
            raw_registry.get("selection_fingerprint")
        ),
        artifacts=records,
        updated_at=str(raw_registry.get("updated_at") or ""),
    )


def load_active_selection_fingerprint(
    project_root: str | Path,
    *,
    allow_legacy_migration: bool = True,
) -> str | None:
    """Return the active fingerprint, preferring processing-owned state."""

    registry = load_artifact_freshness_registry(project_root)
    if registry.selection_fingerprint:
        return registry.selection_fingerprint
    if not allow_legacy_migration:
        return None

    _root, manifest_path = _project_paths(project_root, require_manifest=False)
    if not manifest_path.is_file():
        return None
    manifest = _read_manifest_required(manifest_path)
    processing_active = _nested_mapping(
        manifest,
        ("tools", "processing", "harmonic_selection", "active"),
    )
    if processing_active:
        fingerprint = _optional_text(processing_active.get("selection_fingerprint"))
        if fingerprint:
            return fingerprint
        metadata = processing_active.get("selection_metadata")
        if isinstance(metadata, Mapping):
            try:
                return selection_fingerprint_from_metadata(
                    metadata,
                    allow_legacy_migration=allow_legacy_migration,
                )
            except ValueError:
                pass
    if not allow_legacy_migration:
        return None

    entries = _nested_mapping(
        manifest,
        ("tools", "stats", "group_significant_harmonics_cache", "entries"),
    )
    if not entries:
        return None
    candidates: list[tuple[str, str, Mapping[str, object]]] = []
    for raw_key, raw_entry in entries.items():
        if not isinstance(raw_entry, Mapping):
            continue
        candidates.append(
            (
                str(raw_entry.get("saved_at") or ""),
                str(raw_key),
                raw_entry,
            )
        )
    if not candidates:
        return None
    _saved_at, cache_key, entry = max(candidates, key=lambda item: (item[0], item[1]))
    metadata = entry.get("selection_metadata")
    if isinstance(metadata, Mapping):
        try:
            return selection_fingerprint_from_metadata(
                metadata,
                allow_legacy_migration=True,
            )
        except ValueError:
            pass
    return f"legacy-cache:{cache_key}" if cache_key else None


def activate_selection_freshness(
    project_root: str | Path,
    selection_metadata: Mapping[str, object],
    *,
    previous_fingerprint: str | None = None,
    selection_summary_path: str | Path | None = None,
) -> SelectionFreshnessTransition:
    """Activate one accepted selection and stale changed derivatives atomically."""

    root, manifest_path = _project_paths(project_root, require_manifest=True)
    fingerprint = selection_fingerprint_from_metadata(selection_metadata)
    manifest = _read_manifest_required(manifest_path)
    registry = _registry_from_manifest(manifest)
    registered_previous = _optional_text(registry.get("selection_fingerprint"))
    previous = registered_previous or _optional_text(previous_fingerprint)
    changed = previous != fingerprint
    now = _now_utc_iso()
    artifacts = _artifact_payloads(registry)
    stale_ids: list[str] = []

    if changed:
        for artifact_id in SELECTION_DEPENDENT_ARTIFACTS:
            existing = artifacts.get(artifact_id)
            record = dict(existing) if isinstance(existing, Mapping) else {}
            record.update(
                {
                    "status": ARTIFACT_STATUS_STALE,
                    "path": str(
                        record.get("path")
                        or _DEFAULT_ARTIFACT_PATHS[artifact_id].as_posix()
                    ),
                    "built_from_selection_fingerprint": _optional_text(
                        record.get("built_from_selection_fingerprint")
                    )
                    or previous,
                    "required_selection_fingerprint": fingerprint,
                    "updated_at": now,
                    "reason": "The accepted harmonic selection changed.",
                    "last_error": "",
                    "archives": _archive_list(record.get("archives")),
                }
            )
            artifacts[artifact_id] = record
            stale_ids.append(artifact_id)

    summary_target = (
        _assert_project_artifact_path(root, selection_summary_path)
        if selection_summary_path is not None
        else root / _DEFAULT_ARTIFACT_PATHS[HARMONIC_SELECTION_SUMMARY_ARTIFACT]
    )
    summary_existing = artifacts.get(HARMONIC_SELECTION_SUMMARY_ARTIFACT)
    summary_record = (
        dict(summary_existing) if isinstance(summary_existing, Mapping) else {}
    )
    summary_record.update(
        {
            "status": ARTIFACT_STATUS_CURRENT,
            "path": _project_relative_path(root, summary_target),
            "built_from_selection_fingerprint": fingerprint,
            "required_selection_fingerprint": fingerprint,
            "updated_at": now,
            "reason": "",
            "last_error": "",
            "archives": _archive_list(summary_record.get("archives")),
        }
    )
    artifacts[HARMONIC_SELECTION_SUMMARY_ARTIFACT] = summary_record
    registry.update(
        {
            "schema_version": ARTIFACT_FRESHNESS_SCHEMA_VERSION,
            "selection_fingerprint": fingerprint,
            "updated_at": now,
            "artifacts": artifacts,
        }
    )
    _set_registry(manifest, registry)
    _write_manifest_atomic(manifest_path, manifest)
    return SelectionFreshnessTransition(
        previous_fingerprint=previous,
        selection_fingerprint=fingerprint,
        changed=changed,
        stale_artifact_ids=tuple(stale_ids),
    )


def mark_selection_derivatives_stale(
    project_root: str | Path,
    *,
    reason: str,
) -> tuple[str, ...]:
    """Invalidate accepted-selection outputs before a replacement is calculated.

    This deliberately leaves neutral FullFFT provenance untouched. It is used
    when project harmonic settings change but no new selection fingerprint is
    available yet (for example, when the user saves and rebuilds later).
    """

    _root, manifest_path = _project_paths(project_root, require_manifest=True)
    manifest = _read_manifest_required(manifest_path)
    registry = _registry_from_manifest(manifest)
    active = _optional_text(registry.get("selection_fingerprint"))
    artifacts = _artifact_payloads(registry)
    now = _now_utc_iso()
    stale_ids = (
        HARMONIC_SELECTION_SUMMARY_ARTIFACT,
        *SELECTION_DEPENDENT_ARTIFACTS,
    )
    for artifact_id in stale_ids:
        existing = artifacts.get(artifact_id)
        record = dict(existing) if isinstance(existing, Mapping) else {}
        record.update(
            {
                "status": ARTIFACT_STATUS_STALE,
                "path": str(
                    record.get("path")
                    or _DEFAULT_ARTIFACT_PATHS[artifact_id].as_posix()
                ),
                "built_from_selection_fingerprint": _optional_text(
                    record.get("built_from_selection_fingerprint")
                )
                or active,
                "required_selection_fingerprint": None,
                "updated_at": now,
                "reason": str(reason).strip()
                or "Harmonic-selection settings changed.",
                "last_error": "",
                "archives": _archive_list(record.get("archives")),
            }
        )
        artifacts[artifact_id] = record
    registry.update(
        {
            "schema_version": ARTIFACT_FRESHNESS_SCHEMA_VERSION,
            "updated_at": now,
            "artifacts": artifacts,
        }
    )
    _set_registry(manifest, registry)
    _write_manifest_atomic(manifest_path, manifest)
    return tuple(stale_ids)


def mark_artifact_current(
    project_root: str | Path,
    artifact_id: str,
    artifact_path: str | Path,
    selection_fingerprint: str,
    *,
    archived_path: str | Path | None = None,
) -> ArtifactFreshnessRecord:
    """Mark one successfully and completely published derivative current."""

    root, manifest_path = _project_paths(project_root, require_manifest=True)
    target = _assert_project_artifact_path(root, artifact_path)
    if not target.exists():
        raise FileNotFoundError(
            f"Cannot mark missing post-processing artifact current: {target}"
        )
    manifest = _read_manifest_required(manifest_path)
    registry = _registry_from_manifest(manifest)
    active = _optional_text(registry.get("selection_fingerprint"))
    if active != str(selection_fingerprint):
        raise RuntimeError(
            "Artifact completion belongs to a selection that is no longer active."
        )
    artifacts = _artifact_payloads(registry)
    existing = artifacts.get(str(artifact_id))
    record = dict(existing) if isinstance(existing, Mapping) else {}
    archives = _archive_list(record.get("archives"))
    if archived_path is not None:
        archive = _assert_project_artifact_path(root, archived_path)
        archive_value = _project_relative_path(root, archive)
        if archive_value not in archives:
            archives.append(archive_value)
    now = _now_utc_iso()
    record.update(
        {
            "status": ARTIFACT_STATUS_CURRENT,
            "path": _project_relative_path(root, target),
            "built_from_selection_fingerprint": str(selection_fingerprint),
            "required_selection_fingerprint": str(selection_fingerprint),
            "updated_at": now,
            "reason": "",
            "last_error": "",
            "archives": archives,
        }
    )
    artifacts[str(artifact_id)] = record
    registry.update(
        {
            "schema_version": ARTIFACT_FRESHNESS_SCHEMA_VERSION,
            "selection_fingerprint": str(selection_fingerprint),
            "updated_at": now,
            "artifacts": artifacts,
        }
    )
    _set_registry(manifest, registry)
    _write_manifest_atomic(manifest_path, manifest)
    return _record_from_payload(str(artifact_id), record)


def mark_artifact_failed(
    project_root: str | Path,
    artifact_id: str,
    artifact_path: str | Path,
    selection_fingerprint: str,
    error: object,
) -> ArtifactFreshnessRecord:
    """Record a failed rebuild without claiming that the old artifact is current."""

    root, manifest_path = _project_paths(project_root, require_manifest=True)
    target = _assert_project_artifact_path(root, artifact_path)
    manifest = _read_manifest_required(manifest_path)
    registry = _registry_from_manifest(manifest)
    active = _optional_text(registry.get("selection_fingerprint"))
    if active != str(selection_fingerprint):
        raise RuntimeError(
            "Artifact failure belongs to a selection that is no longer active."
        )
    artifacts = _artifact_payloads(registry)
    existing = artifacts.get(str(artifact_id))
    record = dict(existing) if isinstance(existing, Mapping) else {}
    now = _now_utc_iso()
    record.update(
        {
            "status": ARTIFACT_STATUS_FAILED,
            "path": _project_relative_path(root, target),
            "built_from_selection_fingerprint": _optional_text(
                record.get("built_from_selection_fingerprint")
            ),
            "required_selection_fingerprint": str(selection_fingerprint),
            "updated_at": now,
            "reason": "The post-processing rebuild failed; the preceding artifact remains stale.",
            "last_error": str(error).strip(),
            "archives": _archive_list(record.get("archives")),
        }
    )
    artifacts[str(artifact_id)] = record
    registry.update(
        {
            "schema_version": ARTIFACT_FRESHNESS_SCHEMA_VERSION,
            "selection_fingerprint": str(selection_fingerprint),
            "updated_at": now,
            "artifacts": artifacts,
        }
    )
    _set_registry(manifest, registry)
    _write_manifest_atomic(manifest_path, manifest)
    return _record_from_payload(str(artifact_id), record)


def selection_dependent_artifacts_are_current(
    project_root: str | Path,
    selection_fingerprint: str,
) -> bool:
    """Return whether every canonical dependent is current for this selection."""

    registry = load_artifact_freshness_registry(project_root)
    if registry.selection_fingerprint != str(selection_fingerprint):
        return False
    for artifact_id in SELECTION_DEPENDENT_ARTIFACTS:
        record = registry.artifacts.get(artifact_id)
        if (
            record is None
            or record.status != ARTIFACT_STATUS_CURRENT
            or record.built_from_selection_fingerprint != str(selection_fingerprint)
            or record.required_selection_fingerprint != str(selection_fingerprint)
        ):
            return False
        try:
            target = _assert_project_artifact_path(
                Path(project_root).expanduser().resolve(strict=False),
                record.path,
            )
        except (OSError, ValueError):
            return False
        if not target.exists():
            return False
    return True


def require_current_artifact(
    project_root: str | Path,
    artifact_id: str,
    artifact_path: str | Path | None = None,
) -> ArtifactFreshnessRecord:
    """Validate a canonical derivative before a downstream consumer loads it."""

    root, _manifest_path = _project_paths(project_root, require_manifest=True)
    registry = load_artifact_freshness_registry(root)
    record = registry.artifacts.get(str(artifact_id))
    if record is None:
        raise StalePostProcessingArtifactError(
            f"{artifact_id} has no freshness record. Rebuild post-processing outputs."
        )
    if record.status != ARTIFACT_STATUS_CURRENT:
        detail = record.last_error or record.reason or "The artifact is not current."
        raise StalePostProcessingArtifactError(
            f"{artifact_id} is {record.status}: {detail}"
        )
    active = registry.selection_fingerprint
    if (
        not active
        or record.built_from_selection_fingerprint != active
        or record.required_selection_fingerprint != active
    ):
        raise StalePostProcessingArtifactError(
            f"{artifact_id} was not built from the active harmonic selection."
        )
    target = _assert_project_artifact_path(
        root,
        artifact_path if artifact_path is not None else record.path,
    )
    recorded_target = _assert_project_artifact_path(root, record.path)
    if target != recorded_target:
        raise StalePostProcessingArtifactError(
            f"{artifact_id} path does not match its freshness record."
        )
    if not target.exists():
        raise StalePostProcessingArtifactError(
            f"{artifact_id} is recorded as current but is missing: {target}"
        )
    return record


@contextmanager
def preserve_artifact_for_rebuild(
    project_root: str | Path,
    artifact_id: str,
    artifact_path: str | Path,
    previous_selection_fingerprint: str | None,
) -> Iterator[Path | None]:
    """Archive an old artifact and restore it if replacement publication fails.

    Moving within the same project volume avoids copying potentially large
    source-map directories.  On an exception, any partial replacement is
    removed and the preceding artifact is moved back to its canonical path.
    """

    root, _manifest_path = _project_paths(project_root, require_manifest=True)
    target = _assert_project_artifact_path(root, artifact_path)
    archive: Path | None = None
    if target.exists():
        archive = _next_archive_path(
            root,
            artifact_id=str(artifact_id),
            target_name=target.name,
            previous_selection_fingerprint=previous_selection_fingerprint,
        )
        archive.parent.mkdir(parents=True, exist_ok=False)
        target.replace(archive)
    try:
        yield archive
        if not target.exists():
            raise FileNotFoundError(
                "Post-processing rebuild completed without publishing the expected "
                f"artifact: {target}"
            )
    except BaseException:
        _remove_artifact_path(root, target)
        if archive is not None and archive.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            archive.replace(target)
            _remove_empty_archive_parents(root, archive.parent)
        raise


def restore_preserved_artifact(
    project_root: str | Path,
    artifact_path: str | Path,
    archived_path: str | Path,
) -> None:
    """Restore an archived artifact when final freshness publication fails."""

    root, _manifest_path = _project_paths(project_root, require_manifest=True)
    target = _assert_project_artifact_path(root, artifact_path)
    archive = _assert_project_artifact_path(root, archived_path)
    if not archive.exists():
        raise FileNotFoundError(
            f"Preserved post-processing artifact is missing: {archive}"
        )
    _remove_artifact_path(root, target)
    target.parent.mkdir(parents=True, exist_ok=True)
    archive.replace(target)
    _remove_empty_archive_parents(root, archive.parent)


def _project_paths(
    project_root: str | Path,
    *,
    require_manifest: bool,
) -> tuple[Path, Path]:
    root = Path(project_root).expanduser().resolve(strict=False)
    if not root.is_absolute():
        raise ValueError("Artifact freshness requires an absolute project root.")
    if not root.is_dir():
        raise FileNotFoundError(f"Project folder does not exist: {root}")
    manifest_path = root / "project.json"
    if require_manifest and not manifest_path.is_file():
        raise FileNotFoundError(f"Project manifest does not exist: {manifest_path}")
    return root, manifest_path


def _assert_project_artifact_path(root: Path, value: str | Path) -> Path:
    path = Path(value).expanduser()
    target = path.resolve(strict=False) if path.is_absolute() else (root / path).resolve(strict=False)
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError(
            f"Post-processing artifact must stay inside the active project root: {target}"
        ) from exc
    if target == root:
        raise ValueError("The project root cannot be registered as one artifact.")
    return target


def _project_relative_path(root: Path, path: Path) -> str:
    return path.resolve(strict=False).relative_to(root).as_posix()


def _registry_from_manifest(manifest: Mapping[str, object]) -> dict[str, object]:
    current: object = manifest
    for key in ARTIFACT_FRESHNESS_MANIFEST_PATH:
        if not isinstance(current, Mapping):
            return {
                "schema_version": ARTIFACT_FRESHNESS_SCHEMA_VERSION,
                "selection_fingerprint": None,
                "updated_at": "",
                "artifacts": {},
            }
        current = current.get(key)
    if not isinstance(current, Mapping):
        return {
            "schema_version": ARTIFACT_FRESHNESS_SCHEMA_VERSION,
            "selection_fingerprint": None,
            "updated_at": "",
            "artifacts": {},
        }
    registry = dict(current)
    if not isinstance(registry.get("artifacts"), Mapping):
        registry["artifacts"] = {}
    return registry


def _set_registry(
    manifest: dict[str, object],
    registry: Mapping[str, object],
) -> None:
    node = manifest
    for key in ARTIFACT_FRESHNESS_MANIFEST_PATH[:-1]:
        child = node.get(key)
        if not isinstance(child, dict):
            child = {}
            node[key] = child
        node = child
    node[ARTIFACT_FRESHNESS_MANIFEST_PATH[-1]] = _json_safe(dict(registry))


def _artifact_payloads(registry: Mapping[str, object]) -> dict[str, object]:
    raw = registry.get("artifacts")
    return dict(raw) if isinstance(raw, Mapping) else {}


def _record_from_payload(
    artifact_id: str,
    record: Mapping[str, object],
) -> ArtifactFreshnessRecord:
    status = str(record.get("status") or "")
    if status not in _VALID_ARTIFACT_STATUSES:
        raise ValueError(f"Invalid artifact freshness status: {status}")
    return ArtifactFreshnessRecord(
        artifact_id=artifact_id,
        status=status,
        path=str(record.get("path") or ""),
        built_from_selection_fingerprint=_optional_text(
            record.get("built_from_selection_fingerprint")
        ),
        required_selection_fingerprint=_optional_text(
            record.get("required_selection_fingerprint")
        ),
        updated_at=str(record.get("updated_at") or ""),
        reason=str(record.get("reason") or ""),
        last_error=str(record.get("last_error") or ""),
        archives=tuple(_archive_list(record.get("archives"))),
    )


def _archive_list(value: object) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    out: list[str] = []
    for item in value:
        text = str(item).strip()
        if text and text not in out:
            out.append(text)
    return out


def _nested_mapping(
    source: Mapping[str, object],
    keys: tuple[str, ...],
) -> Mapping[str, object]:
    current: object = source
    for key in keys:
        if not isinstance(current, Mapping):
            return {}
        current = current.get(key)
    return current if isinstance(current, Mapping) else {}


def _read_manifest_required(manifest_path: Path) -> dict[str, object]:
    try:
        parsed = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Project manifest is not valid JSON: {manifest_path}") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError(f"Project manifest must contain a JSON object: {manifest_path}")
    return parsed


def _write_manifest_atomic(
    manifest_path: Path,
    manifest: Mapping[str, object],
) -> None:
    payload = json.dumps(
        _json_safe(dict(manifest)),
        indent=2,
        ensure_ascii=False,
    )
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{manifest_path.name}.artifact-freshness-",
        suffix=".tmp",
        dir=manifest_path.parent,
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        _replace_manifest_with_retry(temporary_path, manifest_path)
    finally:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass


def _next_archive_path(
    root: Path,
    *,
    artifact_id: str,
    target_name: str,
    previous_selection_fingerprint: str | None,
) -> Path:
    safe_artifact_id = re.sub(r"[^0-9A-Za-z_.-]+", "_", artifact_id).strip("._")
    if not safe_artifact_id:
        raise ValueError("Artifact ID cannot be empty.")
    fingerprint_token = re.sub(
        r"[^0-9A-Za-z]+",
        "",
        str(previous_selection_fingerprint or "unknown"),
    )[:12] or "unknown"
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    archive_root = (
        root
        / ".fpvs_processing"
        / "stale_artifacts"
        / safe_artifact_id
        / f"{timestamp}_{fingerprint_token}"
    )
    candidate = archive_root / target_name
    counter = 1
    while candidate.parent.exists():
        candidate = archive_root.with_name(f"{archive_root.name}_{counter}") / target_name
        counter += 1
    return candidate


def _replace_manifest_with_retry(temporary_path: Path, manifest_path: Path) -> None:
    """Tolerate brief Windows scanner/indexer locks around project.json."""

    delays_s = (0.0, 0.01, 0.02, 0.05, 0.1, 0.1)
    for attempt, delay_s in enumerate(delays_s, start=1):
        if delay_s:
            time.sleep(delay_s)
        try:
            os.replace(temporary_path, manifest_path)
            return
        except PermissionError:
            if attempt == len(delays_s):
                raise


def _remove_artifact_path(root: Path, target: Path) -> None:
    checked = _assert_project_artifact_path(root, target)
    if checked.is_symlink() or checked.is_file():
        checked.unlink(missing_ok=True)
    elif checked.is_dir():
        shutil.rmtree(checked)


def _remove_empty_archive_parents(root: Path, parent: Path) -> None:
    stop = root / ".fpvs_processing" / "stale_artifacts"
    current = parent
    while current != stop and current != root:
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent


def _optional_text(value: object) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _json_safe(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _json_safe(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Path):
        return value.as_posix()
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
    encoded = json.dumps(
        _json_safe(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _now_utc_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


__all__ = [
    "ANALYSIS_READY_FULL_AUDIT_ARTIFACT",
    "ARTIFACT_FRESHNESS_MANIFEST_PATH",
    "ARTIFACT_FRESHNESS_SCHEMA_VERSION",
    "ARTIFACT_STATUS_CURRENT",
    "ARTIFACT_STATUS_FAILED",
    "ARTIFACT_STATUS_STALE",
    "ArtifactFreshnessRecord",
    "ArtifactFreshnessRegistry",
    "ELORETA_VOLUME_SOURCE_PSD_ARTIFACT",
    "HARMONIC_SELECTION_SUMMARY_ARTIFACT",
    "L2_MNE_SOURCE_PSD_ARTIFACT",
    "SELECTION_DEPENDENT_ARTIFACTS",
    "STATS_READY_SUMMED_BCA_ARTIFACT",
    "SelectionFreshnessTransition",
    "StalePostProcessingArtifactError",
    "activate_selection_freshness",
    "canonical_artifact_path",
    "load_active_selection_fingerprint",
    "load_artifact_freshness_registry",
    "mark_artifact_current",
    "mark_artifact_failed",
    "mark_selection_derivatives_stale",
    "preserve_artifact_for_rebuild",
    "require_current_artifact",
    "restore_preserved_artifact",
    "selection_dependent_artifacts_are_current",
    "selection_fingerprint_from_metadata",
]
