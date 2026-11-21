"""Small native discovery manifests for lossless processed NumPy results.

The manifest is published last, beside immutable companions. Historical XLSX
anchors remain supported; a present native anchor always takes precedence.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from io import BytesIO, TextIOWrapper
import json
import os
from pathlib import Path
import tempfile

RESULT_MANIFEST_SUFFIX = ".fpvs"
RESULT_MANIFEST_VERSION = "fpvs_result_manifest_v1"
_MAX_REUSED_MANIFEST_CHARS = 16 * 1024


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
    from Main_App.io.companion_schema import condition_descriptor, spectral_descriptor

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


def read_result_manifest(path: str | Path, *, contents: bytes | None = None) -> dict:
    """Validate the declaration on disk or bytes already read for a content digest."""

    return _read_declaration(Path(path), contents=contents)[1]


def _read_declaration(
    source: Path, *, contents: bytes | None = None,
    previous: tuple[str | None, dict] | None = None,
) -> tuple[str | None, dict]:
    try:
        with (
            source.open("r", encoding="utf-8") if contents is None
            else TextIOWrapper(BytesIO(contents), encoding="utf-8")
        ) as stream:
            text = stream.read()
        if previous is not None and text == previous[0]:
            return previous
        manifest = _validate_manifest(json.loads(text))
        return (text if len(text) <= _MAX_REUSED_MANIFEST_CHARS else None), manifest
    except (OSError, ValueError, TypeError) as exc:
        raise ResultManifestError(f"Cannot read FPVS results {source.name}: {exc}") from exc


def result_companion_identities(path: str | Path) -> tuple[dict | None, dict | None]:
    """Validate spectral then condition identity at their original read boundaries."""
    from Main_App.io import condition_data, spectral_data

    source = Path(path)
    if not is_result_manifest(source):
        return spectral_data.spectral_companion_identity(source), condition_data.condition_companion_identity(source)

    first = _read_declaration(source)
    spectral = spectral_data._identity_from_descriptor(source, first[1]["spectral_companion"])
    # A publisher may replace the anchor, edit it in place with restored stat
    # fields, or remove read access while the spectral archive is validated.
    # Reopen the live path. Only identical input to the JSON parser may reuse
    # its result. A file handle held across validation would block Windows rename.
    _, current = _read_declaration(source, previous=first)
    condition = condition_data._identity_from_descriptor(source, current["condition_companion"])
    return spectral, condition


def write_result_manifest(
    path: str | Path, *, sheet_names: Sequence[str],
    spectral_companion: Mapping | None, condition_companion: Mapping | None,
    _publishing_own_companions: bool = False,
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
    if manifest["spectral_companion"] is not None:
        validate_spectral_companion(target, manifest["spectral_companion"])
    if manifest["condition_companion"] is not None:
        validate_condition_companion(target, manifest["condition_companion"], for_publication=_publishing_own_companions)
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
