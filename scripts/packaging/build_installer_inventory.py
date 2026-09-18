"""Generate installer-owned file inventories from the final, immutable bundle.

This is a developer packaging tool, not an application dependency. Legacy records
must come from authenticated, published setup artifacts; scanning an existing user
installation is deliberately not a supported source of ownership.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any

from packaging.version import InvalidVersion, Version

APPLICATION = "fpvs-toolbox"
MANIFEST_HEADER = "FPVS-TOOLBOX-OWNED-FILES-1"
CURRENT_MANIFEST_NAME = "fpvs-owned-files-v1.txt"
PENDING_MANIFEST_NAME = "fpvs-pending-owned-files-v1.txt"
MAX_MANIFEST_BYTES = 64 * 1024 * 1024
MAX_RECORDS = 250_000
MAX_PATH_LENGTH = 1024
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
VERSION_PATTERN = re.compile(r"[0-9][A-Za-z0-9._+-]*\Z")
PROTECTED_TOP_LEVEL = frozenset(
    {
        ".fpvs-toolbox",
        "cache",
        "logs",
        "project.json",
        "runs",
        "stimuli",
        CURRENT_MANIFEST_NAME,
        PENDING_MANIFEST_NAME,
        "fpvs-patch-transaction-v1.txt",
    }
)
WINDOWS_DEVICE = re.compile(r"(?:con|prn|aux|nul|clock\$|com[1-9¹²³]|lpt[1-9¹²³])\Z", re.I)


class InventoryError(ValueError):
    """An inventory cannot safely establish ownership."""


@dataclass(frozen=True)
class Inventory:
    """Case-insensitively unique relative paths and their known content hashes."""

    files: dict[str, tuple[str, ...]]


def validate_relative_path(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > MAX_PATH_LENGTH:
        raise InventoryError("Owned paths must be nonempty strings of at most 1024 characters.")
    if PureWindowsPath(value).is_absolute() or PureWindowsPath(value).drive:
        raise InventoryError(f"Owned path is rooted: {value!r}")
    if any(ord(char) < 32 or ord(char) == 127 or char in '<>:"\\|?*' for char in value):
        raise InventoryError(f"Owned path contains unsafe Windows characters: {value!r}")
    parts = value.split("/")
    for part in parts:
        if part in {"", ".", ".."} or part.endswith((".", " ")):
            raise InventoryError(f"Owned path has an unsafe component: {value!r}")
        if WINDOWS_DEVICE.fullmatch(part.split(".", 1)[0]):
            raise InventoryError(f"Owned path names a Windows device: {value!r}")
    top = parts[0].casefold()
    if top in PROTECTED_TOP_LEVEL or (len(parts) == 1 and top.startswith("unins")):
        raise InventoryError(f"Owned path names user data or installer bookkeeping: {value!r}")
    return value


def validate_sha256(value: object) -> str:
    if not isinstance(value, str) or SHA256_PATTERN.fullmatch(value) is None:
        raise InventoryError("SHA-256 values must be exactly 64 lowercase hexadecimal characters.")
    return value


def validate_version(value: str) -> str:
    if VERSION_PATTERN.fullmatch(value) is None:
        raise InventoryError(f"Unsafe app version: {value!r}")
    try:
        Version(value)
    except InvalidVersion as error:
        raise InventoryError(f"Invalid app version: {value!r}") from error
    return value


def _validated_files(rows: object) -> Inventory:
    if not isinstance(rows, list) or len(rows) > MAX_RECORDS:
        raise InventoryError("Inventory files must be a bounded list.")
    files: dict[str, tuple[str, ...]] = {}
    seen: set[str] = set()
    count = 0
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"path", "sha256"}:
            raise InventoryError("Each owned file must have exactly path and sha256 fields.")
        path = validate_relative_path(row["path"])
        if path.casefold() in seen:
            raise InventoryError(f"Duplicate case-insensitive owned path: {path!r}")
        hashes = row["sha256"]
        if not isinstance(hashes, list) or not hashes:
            raise InventoryError(f"Owned file has no known SHA-256 hashes: {path!r}")
        valid_hashes = tuple(sorted({validate_sha256(digest) for digest in hashes}))
        if len(valid_hashes) != len(hashes):
            raise InventoryError(f"Duplicate SHA-256 record: {path!r}")
        count += len(valid_hashes)
        if count > MAX_RECORDS:
            raise InventoryError("Inventory has too many hash records.")
        seen.add(path.casefold())
        files[path] = valid_hashes
    return Inventory(dict(sorted(files.items(), key=lambda item: item[0].casefold())))


def _read_bounded(path: Path) -> bytes:
    with path.open("rb") as source:
        data = source.read(MAX_MANIFEST_BYTES + 1)
    if len(data) > MAX_MANIFEST_BYTES:
        raise InventoryError(f"Inventory is too large: {path}")
    return data


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise InventoryError(f"Duplicate JSON field: {key}")
        result[key] = value
    return result


def load_legacy_inventory(path: Path) -> tuple[Inventory, list[dict[str, Any]]]:
    try:
        document = json.loads(_read_bounded(path), object_pairs_hook=_unique_object)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise InventoryError(f"Invalid legacy inventory JSON: {path}") from error
    if not isinstance(document, dict) or set(document) != {
        "schema_version",
        "application",
        "releases",
        "files",
    }:
        raise InventoryError("Legacy inventory has an unknown schema.")
    if type(document["schema_version"]) is not int or document["schema_version"] != 1:
        raise InventoryError("Unsupported legacy inventory schema version.")
    if document["application"] != APPLICATION:
        raise InventoryError("Legacy inventory belongs to a different application.")
    releases = document["releases"]
    if not isinstance(releases, list) or not releases:
        raise InventoryError("Legacy inventory requires published-artifact provenance.")
    tags: set[str] = set()
    asset_ids: set[int] = set()
    for release in releases:
        if not isinstance(release, dict) or set(release) != {
            "tag",
            "asset_name",
            "asset_id",
            "sha256",
            "size_bytes",
        }:
            raise InventoryError("Legacy release provenance has an unknown schema.")
        tag = release["tag"]
        if not isinstance(tag, str) or not tag.startswith("v"):
            raise InventoryError("Legacy release provenance needs a version tag.")
        validate_version(tag[1:])
        if tag in tags:
            raise InventoryError(f"Duplicate legacy release tag: {tag}")
        tags.add(tag)
        asset_name = release["asset_name"]
        if not isinstance(asset_name, str) or not asset_name.startswith("FPVSToolbox-"):
            raise InventoryError("Legacy provenance does not name an FPVS Toolbox installer.")
        if not asset_name.endswith(".exe"):
            raise InventoryError("Legacy installer provenance needs an .exe asset.")
        # One published tag (v0.9.9.10) shipped 0.9.10; provenance retains both names.
        validate_version(asset_name[len("FPVSToolbox-") : -10])
        validate_sha256(release["sha256"])
        for field in ("asset_id", "size_bytes"):
            if type(release[field]) is not int or release[field] <= 0:
                raise InventoryError(f"Legacy {field} must be a positive integer.")
        if release["asset_id"] in asset_ids:
            raise InventoryError("Duplicate legacy release asset ID.")
        asset_ids.add(release["asset_id"])
    inventory = _validated_files(document["files"])
    if not any(path.casefold() == "fpvs_toolbox.exe" for path in inventory.files):
        raise InventoryError("Legacy inventory has no published FPVS Toolbox executable identity.")
    return inventory, releases


def is_reparse_stat(value: os.stat_result) -> bool:
    return stat.S_ISLNK(value.st_mode) or bool(
        getattr(value, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
    )


def require_safe_directory(path: Path) -> Path:
    """Reject ambiguous roots and every existing symlink/junction ancestor."""

    if not path.is_absolute() or path == Path(path.anchor) or path == Path.home():
        raise InventoryError(f"A specific absolute directory is required: {path}")
    if ".." in path.parts:
        raise InventoryError(f"Parent traversal is not allowed: {path}")
    for candidate in (*reversed(path.parents), path):
        try:
            details = candidate.lstat()
        except FileNotFoundError:
            continue
        if is_reparse_stat(details) or not stat.S_ISDIR(details.st_mode):
            raise InventoryError(
                f"Directory path includes a reparse point or non-directory: {candidate}"
            )
    return path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inventory_bundle(bundle_root: Path) -> Inventory:
    require_safe_directory(bundle_root)
    if not bundle_root.is_dir():
        raise InventoryError(f"Bundle directory does not exist: {bundle_root}")
    rows: list[dict[str, object]] = []
    for directory, directories, filenames in os.walk(bundle_root, followlinks=False):
        parent = Path(directory)
        for name in directories:
            details = (parent / name).lstat()
            if is_reparse_stat(details) or not stat.S_ISDIR(details.st_mode):
                raise InventoryError(f"Bundle contains an unsafe directory: {parent / name}")
        for name in filenames:
            path = parent / name
            details = path.lstat()
            if is_reparse_stat(details) or not stat.S_ISREG(details.st_mode):
                raise InventoryError(f"Bundle contains an unsafe file: {path}")
            relative = validate_relative_path(path.relative_to(bundle_root).as_posix())
            rows.append({"path": relative, "sha256": [sha256_file(path)]})
    inventory = _validated_files(rows)
    if "FPVS_Toolbox.exe" not in inventory.files:
        raise InventoryError("Final bundle must contain FPVS_Toolbox.exe.")
    return inventory


def serialize_manifest(inventory: Inventory, *, kind: str, version: str) -> str:
    if kind not in {"current", "legacy", "pending"}:
        raise InventoryError(f"Unknown manifest kind: {kind}")
    if kind == "current":
        validate_version(version)
    elif version != kind:
        raise InventoryError("Legacy and pending manifests use their kind as the version marker.")
    lines = [MANIFEST_HEADER, f"kind={kind}", f"version={version}"]
    for path, hashes in sorted(inventory.files.items(), key=lambda item: item[0].casefold()):
        validate_relative_path(path)
        for digest in sorted(hashes):
            lines.append(f"{path}|{validate_sha256(digest)}")
    if len(lines) - 3 > MAX_RECORDS:
        raise InventoryError("Manifest has too many records.")
    return "\r\n".join(lines) + "\r\n"


def parse_manifest(data: bytes, *, expected_kind: str) -> Inventory:
    if expected_kind not in {"current", "legacy", "pending"}:
        raise InventoryError("Unknown manifest kind.")
    if len(data) > MAX_MANIFEST_BYTES:
        raise InventoryError("Manifest is too large.")
    try:
        lines = data.decode("utf-8-sig").splitlines()
    except UnicodeError as error:
        raise InventoryError("Manifest must be UTF-8.") from error
    if len(lines) < 3 or lines[:2] != [MANIFEST_HEADER, f"kind={expected_kind}"]:
        raise InventoryError("Manifest header or kind is invalid.")
    if not lines[2].startswith("version="):
        raise InventoryError("Manifest has no version marker.")
    version = lines[2][8:]
    if expected_kind == "current":
        validate_version(version)
    elif version != expected_kind:
        raise InventoryError("Invalid legacy or pending version marker.")
    files: dict[str, list[str]] = {}
    canonical: dict[str, str] = {}
    for line in lines[3:]:
        fields = line.split("|")
        if len(fields) != 2:
            raise InventoryError("Manifest file record is malformed.")
        path = validate_relative_path(fields[0])
        digest = validate_sha256(fields[1])
        key = path.casefold()
        if key in canonical and canonical[key] != path:
            raise InventoryError("Manifest has inconsistent path casing.")
        canonical[key] = path
        files.setdefault(path, []).append(digest)
    result = _validated_files([{"path": path, "sha256": hashes} for path, hashes in files.items()])
    if (expected_kind == "current" or (expected_kind == "legacy" and canonical)) and "fpvs_toolbox.exe" not in canonical:
        raise InventoryError("Manifest does not identify the application executable.")
    return result


def read_manifest_file(path: Path, *, expected_kind: str) -> tuple[bytes, Inventory]:
    require_safe_directory(path.parent)
    details = path.lstat()
    if is_reparse_stat(details) or not stat.S_ISREG(details.st_mode) or details.st_nlink != 1:
        raise InventoryError(f"Manifest is not a regular single-link file: {path}")
    data = _read_bounded(path)
    return data, parse_manifest(data, expected_kind=expected_kind)


def obsolete_inventory(previous: Inventory, current: Inventory) -> Inventory:
    """Compute candidates only; this developer helper never deletes installed files."""

    current_paths = {path.casefold() for path in current.files}
    return Inventory(
        {
            path: hashes
            for path, hashes in previous.files.items()
            if path.casefold() not in current_paths
        }
    )


def inspect_obsolete_inventory(root: Path, candidates: Inventory) -> dict[str, str]:
    """Read-only lifecycle diagnostic; never delete or infer additional ownership.

    Unit tests exercise this diagnostic and generated wire records. They do not
    substitute for executing the native Inno filesystem lifecycle in a disposable VM.
    """

    require_safe_directory(root)
    outcomes: dict[str, str] = {}
    for relative, hashes in candidates.files.items():
        validate_relative_path(relative)
        path = root.joinpath(*relative.split("/"))
        try:
            require_safe_directory(path.parent)
            details = path.lstat()
            if (
                is_reparse_stat(details)
                or not stat.S_ISREG(details.st_mode)
                or details.st_nlink != 1
            ):
                outcomes[relative] = "unsafe"
            else:
                outcomes[relative] = "owned" if sha256_file(path) in hashes else "modified"
        except FileNotFoundError:
            outcomes[relative] = "missing"
        except InventoryError:
            outcomes[relative] = "unsafe"
        except OSError:
            outcomes[relative] = "unavailable"
    return outcomes


def pending_after_confirmed_cleanup(candidates: Inventory, completed: set[str]) -> Inventory:
    """Keep every unconfirmed record; failed cleanup must not forget its own history."""

    completed_keys = {validate_relative_path(path).casefold() for path in completed}
    return Inventory(
        {
            path: hashes
            for path, hashes in candidates.files.items()
            if path.casefold() not in completed_keys
        }
    )


def _write_generated(path: Path, text: str) -> None:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=".inventory-", delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(text.encode("utf-8-sig"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def build_inventories(
    *, bundle_root: Path, app_version: str, legacy_inventory: Path | None, output_dir: Path
) -> dict[str, object]:
    validate_version(app_version)
    current = inventory_bundle(bundle_root)
    legacy, releases = load_legacy_inventory(legacy_inventory) if legacy_inventory else (Inventory({}), [])
    require_safe_directory(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_generated(
        output_dir / "current-owned-files.txt",
        serialize_manifest(current, kind="current", version=app_version),
    )
    _write_generated(
        output_dir / "legacy-owned-files.txt",
        serialize_manifest(legacy, kind="legacy", version="legacy"),
    )
    return {
        "app_version": app_version,
        "current_paths": len(current.files),
        "legacy_paths": len(legacy.files),
        "legacy_releases": len(releases),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-root", type=Path, required=True)
    parser.add_argument("--app-version", required=True)
    parser.add_argument("--legacy-inventory", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    arguments = parser.parse_args(argv)
    try:
        result = build_inventories(
            bundle_root=arguments.bundle_root.absolute(),
            app_version=arguments.app_version,
            legacy_inventory=arguments.legacy_inventory,
            output_dir=arguments.output_dir.absolute(),
        )
    except (InventoryError, OSError) as error:
        sys.stderr.write(f"Installer inventory failed: {error}\n")
        return 1
    sys.stdout.write(json.dumps(result, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
