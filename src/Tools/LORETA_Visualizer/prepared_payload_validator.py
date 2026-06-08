"""Producer-facing validation for prepared LORETA visualizer JSON payloads.

This module validates already-computed source payload files only. It does not
calculate source-localization values, choose an inverse method, render meshes,
or inspect project outputs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

import numpy as np

from Tools.LORETA_Visualizer.source_payloads import (
    SOURCE_KIND_ROI_MESH,
    SOURCE_KIND_SURFACE_MESH,
    SOURCE_KIND_SURFACE_POINTS,
    SOURCE_KIND_VOLUME_MESH,
    SOURCE_KIND_VOLUME_POINTS,
)

PREPARED_SOURCE_PAYLOAD_FORMAT = "fpvs-loreta-source-payload-v1"
PREPARED_SOURCE_MANIFEST_FORMAT = "fpvs-loreta-source-manifest-v1"

SUPPORTED_SOURCE_KINDS = frozenset(
    {
        SOURCE_KIND_SURFACE_POINTS,
        SOURCE_KIND_SURFACE_MESH,
        SOURCE_KIND_VOLUME_POINTS,
        SOURCE_KIND_VOLUME_MESH,
        SOURCE_KIND_ROI_MESH,
    }
)


class PreparedSourcePayloadValidationError(ValueError):
    """Raised when prepared source JSON does not satisfy the producer contract."""


@dataclass(frozen=True)
class PreparedSourcePayloadSpec:
    """Validated raw source payload data before renderer display conversion."""

    label: str
    kind: str
    coordinate_space: str
    source_model: str
    value_label: str
    points: np.ndarray
    values: np.ndarray
    faces: np.ndarray | None
    metadata: dict[str, Any]


@dataclass(frozen=True)
class PreparedSourceManifestConditionSpec:
    """Validated raw condition entry from a prepared source manifest."""

    condition_id: str
    raw_id: str
    label: str
    file: str
    payload_path: Path | None
    metadata: dict[str, Any]


@dataclass(frozen=True)
class PreparedSourceManifestSpec:
    """Validated prepared source manifest before GUI condition registration."""

    label: str
    conditions: tuple[PreparedSourceManifestConditionSpec, ...]


PREPARED_SOURCE_PAYLOAD_SCHEMA: dict[str, Any] = {
    "format": PREPARED_SOURCE_PAYLOAD_FORMAT,
    "required": ("format", "coordinate_space", "points", "values"),
    "optional": ("label", "kind", "source_model", "value_label", "faces", "metadata"),
    "supported_kinds": tuple(sorted(SUPPORTED_SOURCE_KINDS)),
    "cross_field_rules": (
        "points must be a finite N x 3 numeric array",
        "values must be finite and have one scalar per point",
        "faces, when present, must be triangle rows or VTK-style triangular records",
        "face indices must refer to existing points",
    ),
}

PREPARED_SOURCE_MANIFEST_SCHEMA: dict[str, Any] = {
    "format": PREPARED_SOURCE_MANIFEST_FORMAT,
    "required": ("format", "conditions"),
    "optional": ("label",),
    "condition_required": ("label", "file"),
    "condition_optional": ("id", "metadata"),
    "cross_field_rules": (
        "condition ids must be unique after defaulting from labels",
        "manifest file paths must be relative .json paths",
        "manifest file paths must stay inside the manifest folder",
    ),
}


def validate_prepared_source_payload_json(path: str | Path) -> PreparedSourcePayloadSpec:
    """Validate a prepared source payload JSON file for producer preflight checks."""
    payload_path = Path(path)
    if payload_path.suffix.lower() != ".json":
        raise PreparedSourcePayloadValidationError("Prepared source payload files must use the .json extension.")
    raw_payload = _load_json(payload_path, description="prepared source payload")
    return validate_prepared_source_payload_mapping(raw_payload)


def validate_prepared_source_payload_mapping(raw_payload: Any) -> PreparedSourcePayloadSpec:
    """Validate a prepared source payload mapping without rendering or transforming it."""
    if not isinstance(raw_payload, dict):
        raise PreparedSourcePayloadValidationError("Prepared source payload must be a JSON object.")
    payload_format = str(raw_payload.get("format", "")).strip()
    if payload_format != PREPARED_SOURCE_PAYLOAD_FORMAT:
        raise PreparedSourcePayloadValidationError(
            f"Unsupported prepared source payload format: {payload_format or '<missing>'}."
        )

    coordinate_space = _required_string(raw_payload, "coordinate_space")
    label = _optional_string(raw_payload, "label", "Imported prepared source payload")
    source_model = _optional_string(raw_payload, "source_model", "prepared_source_payload")
    kind = _optional_string(raw_payload, "kind", SOURCE_KIND_VOLUME_MESH)
    if kind not in SUPPORTED_SOURCE_KINDS:
        raise PreparedSourcePayloadValidationError(
            f"Prepared source payload 'kind' must be one of {', '.join(sorted(SUPPORTED_SOURCE_KINDS))}."
        )
    value_label = _optional_string(raw_payload, "value_label", "activation")
    points = _array_field(raw_payload, "points", expected_columns=3, dtype=float)
    values = _values_field(raw_payload)
    if len(points) != len(values):
        raise PreparedSourcePayloadValidationError("Prepared source payload values must have one value per point.")
    faces = _faces_field(raw_payload.get("faces"), point_count=len(points))
    return PreparedSourcePayloadSpec(
        label=label,
        kind=kind,
        coordinate_space=coordinate_space,
        source_model=source_model,
        value_label=value_label,
        points=points,
        values=values,
        faces=faces,
        metadata=_metadata(raw_payload.get("metadata")),
    )


def validate_prepared_source_manifest_json(
    path: str | Path,
    *,
    require_payload_files: bool = False,
) -> PreparedSourceManifestSpec:
    """Validate a prepared source manifest JSON file for producer preflight checks."""
    manifest_path = Path(path)
    if manifest_path.suffix.lower() != ".json":
        raise PreparedSourcePayloadValidationError("Prepared source manifests must use the .json extension.")
    raw_manifest = _load_json(manifest_path, description="prepared source manifest")
    return validate_prepared_source_manifest_mapping(
        raw_manifest,
        manifest_path=manifest_path,
        require_payload_files=require_payload_files,
    )


def validate_prepared_source_manifest_mapping(
    raw_manifest: Any,
    *,
    manifest_path: Path | None = None,
    require_payload_files: bool = False,
) -> PreparedSourceManifestSpec:
    """Validate a prepared source manifest mapping without loading renderer payloads."""
    if not isinstance(raw_manifest, dict):
        raise PreparedSourcePayloadValidationError("Prepared source manifest must be a JSON object.")
    manifest_format = str(raw_manifest.get("format", "")).strip()
    if manifest_format != PREPARED_SOURCE_MANIFEST_FORMAT:
        raise PreparedSourcePayloadValidationError(
            f"Unsupported prepared source manifest format: {manifest_format or '<missing>'}."
        )
    label = _optional_string(raw_manifest, "label", "Prepared source manifest")
    raw_conditions = raw_manifest.get("conditions")
    if not isinstance(raw_conditions, list) or not raw_conditions:
        raise PreparedSourcePayloadValidationError("Prepared source manifest requires a non-empty 'conditions' list.")

    manifest_dir = manifest_path.parent.resolve() if manifest_path is not None else None
    conditions: list[PreparedSourceManifestConditionSpec] = []
    seen_ids: set[str] = set()
    for index, raw_entry in enumerate(raw_conditions, start=1):
        if not isinstance(raw_entry, dict):
            raise PreparedSourcePayloadValidationError(
                "Prepared source manifest condition entries must be objects."
            )
        condition_label = _required_string(raw_entry, "label")
        raw_id = _optional_string(raw_entry, "id", _slug(condition_label))
        if raw_id in seen_ids:
            raise PreparedSourcePayloadValidationError(
                f"Duplicate prepared source manifest condition id: {raw_id!r}."
            )
        seen_ids.add(raw_id)
        file_value, payload_path = _validate_manifest_payload_path(
            raw_entry,
            manifest_dir=manifest_dir,
            require_payload_file=require_payload_files,
        )
        conditions.append(
            PreparedSourceManifestConditionSpec(
                condition_id=f"manifest:{index}:{raw_id}",
                raw_id=raw_id,
                label=condition_label,
                file=file_value,
                payload_path=payload_path,
                metadata=_metadata(raw_entry.get("metadata")),
            )
        )
    return PreparedSourceManifestSpec(label=label, conditions=tuple(conditions))


def _load_json(path: Path, *, description: str) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except json.JSONDecodeError as exc:
        raise PreparedSourcePayloadValidationError(f"{description.title()} is not valid JSON: {exc}") from exc
    except OSError as exc:
        raise PreparedSourcePayloadValidationError(f"Unable to read {description}: {exc}") from exc


def _required_string(raw_payload: dict[str, Any], key: str) -> str:
    value = raw_payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PreparedSourcePayloadValidationError(f"Prepared source payload requires a non-empty {key!r} string.")
    return value.strip()


def _optional_string(raw_payload: dict[str, Any], key: str, default: str) -> str:
    value = raw_payload.get(key, default)
    if not isinstance(value, str) or not value.strip():
        raise PreparedSourcePayloadValidationError(f"Prepared source payload {key!r} must be a non-empty string.")
    return value.strip()


def _array_field(raw_payload: dict[str, Any], key: str, *, expected_columns: int, dtype: Any) -> np.ndarray:
    if key not in raw_payload:
        raise PreparedSourcePayloadValidationError(f"Prepared source payload requires {key!r}.")
    values = np.asarray(raw_payload[key], dtype=dtype)
    if values.ndim != 2 or values.shape[1] != expected_columns or len(values) == 0:
        raise PreparedSourcePayloadValidationError(
            f"Prepared source payload {key!r} must be a non-empty N x {expected_columns} array."
        )
    if not np.all(np.isfinite(values)):
        raise PreparedSourcePayloadValidationError(f"Prepared source payload {key!r} must contain finite values.")
    return values


def _values_field(raw_payload: dict[str, Any]) -> np.ndarray:
    if "values" not in raw_payload:
        raise PreparedSourcePayloadValidationError("Prepared source payload requires 'values'.")
    values = np.asarray(raw_payload["values"], dtype=float).reshape(-1)
    if len(values) == 0:
        raise PreparedSourcePayloadValidationError("Prepared source payload 'values' must not be empty.")
    if not np.all(np.isfinite(values)):
        raise PreparedSourcePayloadValidationError("Prepared source payload 'values' must contain finite values.")
    return values


def _faces_field(raw_faces: Any, *, point_count: int) -> np.ndarray | None:
    if raw_faces is None:
        return None
    faces = np.asarray(raw_faces, dtype=np.int64)
    if faces.ndim == 1:
        if len(faces) % 4 != 0:
            raise PreparedSourcePayloadValidationError("Flat faces must use VTK-style [3, i, j, k] records.")
        reshaped = faces.reshape(-1, 4)
        if len(reshaped) == 0 or not np.all(reshaped[:, 0] == 3):
            raise PreparedSourcePayloadValidationError("Flat faces must use triangular VTK-style face records.")
        triangle_rows = reshaped[:, 1:4]
        _validate_face_indices(triangle_rows, point_count=point_count)
        return faces
    if faces.ndim == 2 and faces.shape[1] == 3 and len(faces) > 0:
        _validate_face_indices(faces, point_count=point_count)
        counts = np.full((len(faces), 1), 3, dtype=np.int64)
        return np.hstack((counts, faces)).reshape(-1)
    raise PreparedSourcePayloadValidationError("Faces must be triangle rows or flat VTK-style triangular records.")


def _validate_face_indices(faces: np.ndarray, *, point_count: int) -> None:
    if not np.all(faces >= 0):
        raise PreparedSourcePayloadValidationError("Prepared source payload faces must not contain negative indices.")
    if int(np.max(faces)) >= point_count:
        raise PreparedSourcePayloadValidationError("Prepared source payload faces must refer to existing points.")


def _metadata(raw_metadata: Any) -> dict[str, Any]:
    if raw_metadata is None:
        return {}
    if not isinstance(raw_metadata, dict):
        raise PreparedSourcePayloadValidationError("Prepared source payload metadata must be a JSON object.")
    return dict(raw_metadata)


def _validate_manifest_payload_path(
    raw_entry: dict[str, Any],
    *,
    manifest_dir: Path | None,
    require_payload_file: bool,
) -> tuple[str, Path | None]:
    file_value = raw_entry.get("file")
    if not isinstance(file_value, str) or not file_value.strip():
        raise PreparedSourcePayloadValidationError(
            "Prepared source manifest entries require a non-empty 'file' string."
        )
    file_text = file_value.strip()
    payload_path = Path(file_text)
    if _is_absolute_or_drive_path(file_text):
        raise PreparedSourcePayloadValidationError("Prepared source manifest file paths must be relative paths.")
    if ".." in payload_path.parts or ".." in PureWindowsPath(file_text).parts:
        raise PreparedSourcePayloadValidationError(
            "Prepared source manifest file paths must stay inside the manifest folder."
        )
    if payload_path.suffix.lower() != ".json":
        raise PreparedSourcePayloadValidationError(
            "Prepared source manifest entries must point to .json payload files."
        )
    if manifest_dir is None:
        return file_text, None

    resolved = (manifest_dir / payload_path).resolve()
    try:
        resolved.relative_to(manifest_dir)
    except ValueError as exc:
        raise PreparedSourcePayloadValidationError(
            "Prepared source manifest file paths must stay inside the manifest folder."
        ) from exc
    if require_payload_file and not resolved.is_file():
        raise PreparedSourcePayloadValidationError(
            f"Prepared source manifest payload file is missing: {payload_path}."
        )
    return file_text, resolved


def _is_absolute_or_drive_path(file_text: str) -> bool:
    windows_path = PureWindowsPath(file_text)
    return bool(
        Path(file_text).is_absolute()
        or PurePosixPath(file_text).is_absolute()
        or windows_path.is_absolute()
        or windows_path.drive
    )


def _slug(label: str) -> str:
    lowered = label.strip().lower()
    chars = [char if char.isalnum() else "_" for char in lowered]
    slug = "_".join(part for part in "".join(chars).split("_") if part)
    return slug or "condition"
