"""Small native discovery manifests for lossless processed NumPy results.

The manifest is published last, beside immutable companions. Historical XLSX
anchors remain supported; a present native anchor always takes precedence.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
import os
from pathlib import Path
import tempfile

RESULT_MANIFEST_SUFFIX = ".fpvs"
RESULT_MANIFEST_VERSION = "fpvs_result_manifest_v1"


class ResultManifestError(ValueError):
    """A native result declaration is missing, invalid, or inconsistent."""


def is_result_manifest(path: str | Path) -> bool:
    return Path(path).suffix.lower() == RESULT_MANIFEST_SUFFIX


def result_manifest_path(path: str | Path) -> Path:
    return Path(path).with_suffix(RESULT_MANIFEST_SUFFIX)


def resolve_result_path(path: str | Path) -> Path:
    """Prefer native results, retaining historical XLSX until reprocessing."""

    source = Path(path)
    native = source if is_result_manifest(source) else result_manifest_path(source)
    legacy = source if source.suffix.lower() == ".xlsx" else source.with_suffix(".xlsx")
    if native.exists() or not legacy.exists():
        return native
    return legacy


def _validate_manifest(value: object) -> dict:
    # Import lazily: companion readers also use this declaration adapter.
    from Main_App.io.condition_data import _descriptor as condition_descriptor
    from Main_App.io.spectral_data import _descriptor as spectral_descriptor

    if not isinstance(value, Mapping) or set(value) != {
        "version", "sheet_names", "spectral_companion", "condition_companion",
    } or value.get("version") != RESULT_MANIFEST_VERSION:
        raise ResultManifestError("Unsupported or invalid FPVS result manifest.")
    result = dict(value)
    declared = []
    for key, validator in (
        ("spectral_companion", spectral_descriptor),
        ("condition_companion", condition_descriptor),
    ):
        if value[key] is not None:
            result[key] = validator(value[key])
            declared.extend(result[key]["sheets"])
    sheets = value["sheet_names"]
    if (
        not isinstance(sheets, list) or not sheets
        or any(not isinstance(name, str) for name in sheets)
        or len(set(sheets)) != len(sheets) or set(sheets) != set(declared)
    ):
        raise ResultManifestError("FPVS result sheets disagree with their companions.")
    return result


def read_result_manifest(path: str | Path) -> dict:
    """Read only the declaration; shared companion readers validate its data."""

    source = Path(path)
    try:
        with source.open("r", encoding="utf-8") as stream:
            return _validate_manifest(json.load(stream))
    except (OSError, ValueError, TypeError) as exc:
        raise ResultManifestError(f"Cannot read FPVS results {source.name}: {exc}") from exc


def write_result_manifest(
    path: str | Path, *, sheet_names: Sequence[str],
    spectral_companion: Mapping | None, condition_companion: Mapping | None,
) -> dict:
    """Validate companions then atomically publish their native declaration."""

    from Main_App.io.condition_data import validate_condition_companion
    from Main_App.io.spectral_data import validate_spectral_companion

    target = Path(path)
    if not is_result_manifest(target):
        raise ResultManifestError("Native result manifests require the .fpvs extension.")
    manifest = _validate_manifest({
        "version": RESULT_MANIFEST_VERSION, "sheet_names": list(sheet_names),
        "spectral_companion": spectral_companion,
        "condition_companion": condition_companion,
    })
    for key, validator in (
        ("spectral_companion", validate_spectral_companion),
        ("condition_companion", validate_condition_companion),
    ):
        if manifest[key] is not None:
            validator(target, manifest[key])
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=target.parent,
            prefix=f".{target.stem}.", suffix=".tmp", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(manifest, stream, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        if read_result_manifest(temporary) != manifest:
            raise ResultManifestError("Written FPVS result declaration failed validation.")
        os.replace(temporary, target)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return {"status": "passed", "sheet_names": manifest["sheet_names"],
            "format": RESULT_MANIFEST_VERSION}
