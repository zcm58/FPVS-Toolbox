"""Importer for prepared LORETA visualizer source payload files.

This imports already-computed source payloads only. It does not calculate
source-localization values or choose an inverse method.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from Tools.LORETA_Visualizer.source_payloads import (
    SOURCE_KIND_VOLUME_MESH,
    SourcePayload,
    make_source_payload,
    source_payload_to_display,
)
from Tools.LORETA_Visualizer.transforms import COORDINATE_SPACE_DISPLAY, MeshDisplayTransform

PREPARED_SOURCE_PAYLOAD_FORMAT = "fpvs-loreta-source-payload-v1"
PREPARED_SOURCE_MANIFEST_FORMAT = "fpvs-loreta-source-manifest-v1"


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
        with payload_path.open("r", encoding="utf-8") as handle:
            raw_payload = json.load(handle)
    except json.JSONDecodeError as exc:
        raise PreparedSourcePayloadImportError(f"Prepared source payload is not valid JSON: {exc}") from exc
    except OSError as exc:
        raise PreparedSourcePayloadImportError(f"Unable to read prepared source payload: {exc}") from exc
    return prepared_source_payload_from_mapping(
        raw_payload,
        display_transform=display_transform,
        source_path=payload_path,
    )


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
    if not isinstance(raw_manifest, dict):
        raise PreparedSourcePayloadImportError("Prepared source manifest must be a JSON object.")
    manifest_format = str(raw_manifest.get("format", "")).strip()
    if manifest_format != PREPARED_SOURCE_MANIFEST_FORMAT:
        raise PreparedSourcePayloadImportError(
            f"Unsupported prepared source manifest format: {manifest_format or '<missing>'}."
        )
    raw_conditions = raw_manifest.get("conditions")
    if not isinstance(raw_conditions, list) or not raw_conditions:
        raise PreparedSourcePayloadImportError("Prepared source manifest requires a non-empty 'conditions' list.")

    manifest_dir = manifest_path.parent.resolve()
    entries: list[PreparedSourceManifestEntry] = []
    seen_ids: set[str] = set()
    for index, raw_entry in enumerate(raw_conditions, start=1):
        if not isinstance(raw_entry, dict):
            raise PreparedSourcePayloadImportError("Prepared source manifest condition entries must be objects.")
        label = _required_string(raw_entry, "label")
        raw_id = _optional_string(raw_entry, "id", _slug(label))
        if raw_id in seen_ids:
            raise PreparedSourcePayloadImportError(f"Duplicate prepared source manifest condition id: {raw_id!r}.")
        seen_ids.add(raw_id)
        condition_id = f"manifest:{index}:{raw_id}"
        payload_path = _resolve_manifest_payload_path(
            raw_entry,
            manifest_dir=manifest_dir,
        )
        entries.append(
            PreparedSourceManifestEntry(
                condition_id=condition_id,
                label=label,
                payload_path=payload_path,
                metadata=_metadata(raw_entry.get("metadata")),
            )
        )
    return tuple(entries)


def prepared_source_payload_from_mapping(
    raw_payload: Any,
    *,
    display_transform: MeshDisplayTransform,
    source_path: Path | None = None,
) -> SourcePayload:
    """Validate a prepared source payload mapping and return display-space data."""
    if not isinstance(raw_payload, dict):
        raise PreparedSourcePayloadImportError("Prepared source payload must be a JSON object.")
    payload_format = str(raw_payload.get("format", "")).strip()
    if payload_format != PREPARED_SOURCE_PAYLOAD_FORMAT:
        raise PreparedSourcePayloadImportError(
            f"Unsupported prepared source payload format: {payload_format or '<missing>'}."
        )

    coordinate_space = _required_string(raw_payload, "coordinate_space")
    label = _optional_string(raw_payload, "label", "Imported prepared source payload")
    source_model = _optional_string(raw_payload, "source_model", "prepared_source_payload")
    kind = _optional_string(raw_payload, "kind", SOURCE_KIND_VOLUME_MESH)
    value_label = _optional_string(raw_payload, "value_label", "activation")
    points = _array_field(raw_payload, "points", expected_columns=3, dtype=float)
    values = _values_field(raw_payload)
    faces = _faces_field(raw_payload.get("faces"))
    metadata = _metadata(raw_payload.get("metadata"))
    metadata.update(
        {
            "source_file_format": PREPARED_SOURCE_PAYLOAD_FORMAT,
            "source_space": coordinate_space,
        }
    )
    if source_path is not None:
        metadata["source_file_name"] = source_path.name

    try:
        payload = make_source_payload(
            points=points,
            values=values,
            label=label,
            kind=kind,
            coordinate_space=coordinate_space,
            source_model=source_model,
            value_label=value_label,
            faces=faces,
            metadata=metadata,
            normalize_values=False,
        )
        return source_payload_to_display(payload, display_transform)
    except ValueError as exc:
        raise PreparedSourcePayloadImportError(str(exc)) from exc


def _required_string(raw_payload: dict[str, Any], key: str) -> str:
    value = raw_payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PreparedSourcePayloadImportError(f"Prepared source payload requires a non-empty {key!r} string.")
    return value.strip()


def _optional_string(raw_payload: dict[str, Any], key: str, default: str) -> str:
    value = raw_payload.get(key, default)
    if not isinstance(value, str) or not value.strip():
        raise PreparedSourcePayloadImportError(f"Prepared source payload {key!r} must be a non-empty string.")
    return value.strip()


def _array_field(raw_payload: dict[str, Any], key: str, *, expected_columns: int, dtype: Any) -> np.ndarray:
    if key not in raw_payload:
        raise PreparedSourcePayloadImportError(f"Prepared source payload requires {key!r}.")
    values = np.asarray(raw_payload[key], dtype=dtype)
    if values.ndim != 2 or values.shape[1] != expected_columns or len(values) == 0:
        raise PreparedSourcePayloadImportError(
            f"Prepared source payload {key!r} must be a non-empty N x {expected_columns} array."
        )
    if not np.all(np.isfinite(values)):
        raise PreparedSourcePayloadImportError(f"Prepared source payload {key!r} must contain finite values.")
    return values


def _values_field(raw_payload: dict[str, Any]) -> np.ndarray:
    if "values" not in raw_payload:
        raise PreparedSourcePayloadImportError("Prepared source payload requires 'values'.")
    values = np.asarray(raw_payload["values"], dtype=float).reshape(-1)
    if len(values) == 0:
        raise PreparedSourcePayloadImportError("Prepared source payload 'values' must not be empty.")
    if not np.all(np.isfinite(values)):
        raise PreparedSourcePayloadImportError("Prepared source payload 'values' must contain finite values.")
    return values


def _faces_field(raw_faces: Any) -> np.ndarray | None:
    if raw_faces is None:
        return None
    faces = np.asarray(raw_faces, dtype=np.int64)
    if faces.ndim == 1:
        if len(faces) % 4 != 0:
            raise PreparedSourcePayloadImportError("Flat faces must use VTK-style [3, i, j, k] records.")
        reshaped = faces.reshape(-1, 4)
        if not np.all(reshaped[:, 0] == 3):
            raise PreparedSourcePayloadImportError("Flat faces must use triangular VTK-style face records.")
        return faces
    if faces.ndim == 2 and faces.shape[1] == 3 and len(faces) > 0:
        counts = np.full((len(faces), 1), 3, dtype=np.int64)
        return np.hstack((counts, faces)).reshape(-1)
    raise PreparedSourcePayloadImportError("Faces must be triangle rows or flat VTK-style triangular records.")


def _metadata(raw_metadata: Any) -> dict[str, Any]:
    if raw_metadata is None:
        return {}
    if not isinstance(raw_metadata, dict):
        raise PreparedSourcePayloadImportError("Prepared source payload metadata must be a JSON object.")
    return dict(raw_metadata)


def _resolve_manifest_payload_path(raw_entry: dict[str, Any], *, manifest_dir: Path) -> Path:
    file_value = raw_entry.get("file")
    if not isinstance(file_value, str) or not file_value.strip():
        raise PreparedSourcePayloadImportError("Prepared source manifest entries require a non-empty 'file' string.")
    payload_path = Path(file_value.strip())
    if payload_path.is_absolute():
        raise PreparedSourcePayloadImportError("Prepared source manifest file paths must be relative paths.")
    resolved = (manifest_dir / payload_path).resolve()
    try:
        resolved.relative_to(manifest_dir)
    except ValueError as exc:
        raise PreparedSourcePayloadImportError(
            "Prepared source manifest file paths must stay inside the manifest folder."
        ) from exc
    if resolved.suffix.lower() != ".json":
        raise PreparedSourcePayloadImportError("Prepared source manifest entries must point to .json payload files.")
    if not resolved.is_file():
        raise PreparedSourcePayloadImportError(f"Prepared source manifest payload file is missing: {payload_path}.")
    return resolved


def _slug(label: str) -> str:
    lowered = label.strip().lower()
    chars = [char if char.isalnum() else "_" for char in lowered]
    slug = "_".join(part for part in "".join(chars).split("_") if part)
    return slug or "condition"


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
