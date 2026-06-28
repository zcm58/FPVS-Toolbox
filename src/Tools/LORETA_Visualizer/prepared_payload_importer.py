"""Importer for prepared LORETA visualizer source payload files.

This imports already-computed source payloads only. It does not calculate
source-localization values or choose an inverse method.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, replace
import json
from pathlib import Path
import threading
from typing import Any

from Tools.LORETA_Visualizer.prepared_payload_validator import (
    PREPARED_SOURCE_MANIFEST_FORMAT,
    PREPARED_SOURCE_PAYLOAD_FORMAT,
    PreparedSourcePayloadValidationError,
    validate_prepared_source_manifest_mapping,
    validate_prepared_source_payload_mapping,
)
from Tools.LORETA_Visualizer.source_payloads import (
    SOURCE_KIND_VOLUME_MESH,
    SourcePayload,
    make_source_payload,
    source_payload_to_display,
)
from Tools.LORETA_Visualizer.transforms import COORDINATE_SPACE_DISPLAY, MeshDisplayTransform

PREPARED_PAYLOAD_JSON_CACHE_MAX_ITEMS = 48
_PREPARED_PAYLOAD_JSON_CACHE: OrderedDict[tuple[object, ...], SourcePayload] = OrderedDict()
_PREPARED_PAYLOAD_JSON_CACHE_LOCK = threading.RLock()


class PreparedSourcePayloadImportError(ValueError):
    """Raised when a prepared source payload file cannot be imported."""


@dataclass(frozen=True)
class PreparedSourceManifestEntry:
    """One condition entry from a prepared source payload manifest."""

    condition_id: str
    label: str
    payload_path: Path
    metadata: dict[str, Any]


def load_prepared_source_payload_json(
    path: str | Path,
    *,
    display_transform: MeshDisplayTransform,
) -> SourcePayload:
    """Load a prepared source payload JSON file and convert it to display space."""
    payload_path = Path(path)
    if payload_path.suffix.lower() != ".json":
        raise PreparedSourcePayloadImportError("Prepared source payload files must use the .json extension.")
    try:
        stat = payload_path.stat()
    except OSError as exc:
        raise PreparedSourcePayloadImportError(f"Unable to read prepared source payload: {exc}") from exc

    cache_key = _prepared_payload_cache_key(
        payload_path,
        stat_mtime_ns=int(stat.st_mtime_ns),
        stat_size=int(stat.st_size),
        display_transform=display_transform,
    )
    cached_payload = _get_cached_prepared_payload(cache_key)
    if cached_payload is not None:
        return _copy_source_payload_for_caller(cached_payload)

    try:
        with payload_path.open("r", encoding="utf-8") as handle:
            raw_payload = json.load(handle)
    except json.JSONDecodeError as exc:
        raise PreparedSourcePayloadImportError(f"Prepared source payload is not valid JSON: {exc}") from exc
    except OSError as exc:
        raise PreparedSourcePayloadImportError(f"Unable to read prepared source payload: {exc}") from exc
    payload = prepared_source_payload_from_mapping(
        raw_payload,
        display_transform=display_transform,
        source_path=payload_path,
    )
    _remember_cached_prepared_payload(cache_key, payload)
    return _copy_source_payload_for_caller(payload)


def load_prepared_source_manifest_json(path: str | Path) -> tuple[PreparedSourceManifestEntry, ...]:
    """Load a prepared source manifest and resolve payload paths."""
    manifest_path = Path(path)
    if manifest_path.suffix.lower() != ".json":
        raise PreparedSourcePayloadImportError("Prepared source manifests must use the .json extension.")
    try:
        with manifest_path.open("r", encoding="utf-8") as handle:
            raw_manifest = json.load(handle)
    except json.JSONDecodeError as exc:
        raise PreparedSourcePayloadImportError(f"Prepared source manifest is not valid JSON: {exc}") from exc
    except OSError as exc:
        raise PreparedSourcePayloadImportError(f"Unable to read prepared source manifest: {exc}") from exc
    return prepared_source_manifest_from_mapping(raw_manifest, manifest_path=manifest_path)


def prepared_source_manifest_from_mapping(
    raw_manifest: Any,
    *,
    manifest_path: Path,
) -> tuple[PreparedSourceManifestEntry, ...]:
    """Validate a prepared source manifest mapping."""
    try:
        manifest = validate_prepared_source_manifest_mapping(
            raw_manifest,
            manifest_path=manifest_path,
            require_payload_files=True,
        )
    except PreparedSourcePayloadValidationError as exc:
        raise PreparedSourcePayloadImportError(str(exc)) from exc
    return tuple(
        PreparedSourceManifestEntry(
            condition_id=condition.condition_id,
            label=condition.label,
            payload_path=_required_payload_path(condition.payload_path),
            metadata=condition.metadata,
        )
        for condition in manifest.conditions
    )


def prepared_source_payload_from_mapping(
    raw_payload: Any,
    *,
    display_transform: MeshDisplayTransform,
    source_path: Path | None = None,
) -> SourcePayload:
    """Validate a prepared source payload mapping and return display-space data."""
    try:
        payload_spec = validate_prepared_source_payload_mapping(raw_payload)
    except PreparedSourcePayloadValidationError as exc:
        raise PreparedSourcePayloadImportError(str(exc)) from exc
    metadata = dict(payload_spec.metadata)
    metadata.update(
        {
            "source_file_format": PREPARED_SOURCE_PAYLOAD_FORMAT,
            "source_space": payload_spec.coordinate_space,
        }
    )
    if source_path is not None:
        metadata["source_file_name"] = source_path.name

    try:
        payload = make_source_payload(
            points=payload_spec.points,
            values=payload_spec.values,
            label=payload_spec.label,
            kind=payload_spec.kind,
            coordinate_space=payload_spec.coordinate_space,
            source_model=payload_spec.source_model,
            value_label=payload_spec.value_label,
            faces=payload_spec.faces,
            metadata=metadata,
            normalize_values=False,
        )
        return source_payload_to_display(payload, display_transform)
    except ValueError as exc:
        raise PreparedSourcePayloadImportError(str(exc)) from exc


def _required_payload_path(payload_path: Path | None) -> Path:
    if payload_path is None:
        raise PreparedSourcePayloadImportError("Prepared source manifest payload path was not resolved.")
    return payload_path


def _prepared_payload_cache_key(
    payload_path: Path,
    *,
    stat_mtime_ns: int,
    stat_size: int,
    display_transform: MeshDisplayTransform,
) -> tuple[object, ...]:
    return (
        str(payload_path.expanduser().resolve()),
        int(stat_mtime_ns),
        int(stat_size),
        _display_transform_cache_key(display_transform),
    )


def _display_transform_cache_key(display_transform: MeshDisplayTransform) -> tuple[object, ...]:
    return (
        tuple(float(value) for value in display_transform.center.reshape(-1)),
        float(display_transform.radius),
        display_transform.native_coordinate_space,
        display_transform.display_coordinate_space,
    )


def _get_cached_prepared_payload(cache_key: tuple[object, ...]) -> SourcePayload | None:
    with _PREPARED_PAYLOAD_JSON_CACHE_LOCK:
        payload = _PREPARED_PAYLOAD_JSON_CACHE.get(cache_key)
        if payload is None:
            return None
        _PREPARED_PAYLOAD_JSON_CACHE.move_to_end(cache_key)
        return payload


def _remember_cached_prepared_payload(cache_key: tuple[object, ...], payload: SourcePayload) -> None:
    with _PREPARED_PAYLOAD_JSON_CACHE_LOCK:
        _PREPARED_PAYLOAD_JSON_CACHE[cache_key] = payload
        _PREPARED_PAYLOAD_JSON_CACHE.move_to_end(cache_key)
        while len(_PREPARED_PAYLOAD_JSON_CACHE) > PREPARED_PAYLOAD_JSON_CACHE_MAX_ITEMS:
            _PREPARED_PAYLOAD_JSON_CACHE.popitem(last=False)


def _copy_source_payload_for_caller(payload: SourcePayload) -> SourcePayload:
    return replace(payload, metadata=dict(payload.metadata))


def prepared_source_payload_example() -> dict[str, Any]:
    """Return a minimal JSON-serializable prepared source payload example."""
    return {
        "format": PREPARED_SOURCE_PAYLOAD_FORMAT,
        "label": "Example prepared source payload",
        "kind": SOURCE_KIND_VOLUME_MESH,
        "coordinate_space": COORDINATE_SPACE_DISPLAY,
        "source_model": "prepared_source_payload",
        "value_label": "activation",
        "points": [[-0.2, -0.4, 0.1], [0.0, -0.45, 0.16], [0.2, -0.4, 0.1]],
        "values": [0.2, 0.8, 1.0],
        "faces": [[0, 1, 2]],
        "metadata": {"synthetic": True},
    }


def prepared_source_manifest_example() -> dict[str, Any]:
    """Return a minimal JSON-serializable prepared source manifest example."""
    return {
        "format": PREPARED_SOURCE_MANIFEST_FORMAT,
        "label": "Example prepared source manifest",
        "conditions": [
            {
                "id": "condition_a",
                "label": "Condition A",
                "file": "condition_a_source.json",
                "metadata": {"group": "demo"},
            },
            {
                "id": "condition_b",
                "label": "Condition B",
                "file": "condition_b_source.json",
                "metadata": {"group": "demo"},
            },
        ],
    }
