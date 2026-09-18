"""Build sparse Inno payloads from an authenticated published ownership inventory.

The caller obtains the baseline manifest and its checksum from the exact published
installer. A local installed tree is never a source of release ownership.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

from build_installer_inventory import (
    Inventory,
    InventoryError,
    inventory_bundle,
    read_manifest_file,
    require_safe_directory,
    serialize_manifest,
    sha256_file,
    validate_sha256,
    validate_version,
)
from packaging.version import Version

PATCH_MARKER_NAME = "fpvs-patch-transaction-v1.txt"


def current_inventory(path: Path) -> tuple[bytes, Inventory, str]:
    data, inventory = read_manifest_file(path, expected_kind="current")
    version = data.decode("utf-8-sig").splitlines()[2][8:]
    if any(len(hashes) != 1 for hashes in inventory.files.values()):
        raise InventoryError("A patch baseline must identify exactly one hash per file.")
    return data, inventory, version


def _check_metadata(bundle: Path, version: str) -> None:
    metadata = bundle / "_internal/toolbox-updater-version.json"
    try:
        actual = json.loads(metadata.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise InventoryError("Patch target requires bundled Toolbox version metadata.") from error
    if actual != {"version": version}:
        raise InventoryError("Patch target package metadata does not match the target version.")


def prepare_patch(
    *,
    baseline_inventory: Path,
    source_inventory_sha256: str,
    bundle_root: Path,
    target_inventory: Path,
    target_version: str,
    output_dir: Path,
) -> dict[str, object]:
    """Validate both inputs, then create only added/changed target files in a new dir."""

    validate_sha256(source_inventory_sha256)
    validate_version(target_version)
    source_data, source, source_version = current_inventory(baseline_inventory)
    if hashlib.sha256(source_data).hexdigest() != source_inventory_sha256:
        raise InventoryError("Baseline inventory does not match its authenticated SHA-256.")
    if Version(source_version) >= Version(target_version):
        raise InventoryError("Patch source version must be older than the target version.")
    target_data, target, inventory_version = current_inventory(target_inventory)
    if inventory_version != target_version:
        raise InventoryError("Target inventory version does not match the requested release.")
    actual = inventory_bundle(bundle_root)
    if actual != target:
        raise InventoryError("Target bundle differs from its final installer inventory.")
    for relative in actual.files:
        if (bundle_root / relative).stat().st_nlink != 1:
            raise InventoryError(f"Patch target contains a hardlink: {relative}")
    _check_metadata(bundle_root, target_version)
    source_keys = {path.casefold(): (path, hashes) for path, hashes in source.files.items()}
    target_keys = {path.casefold() for path in target.files}
    changed: dict[str, tuple[str, ...]] = {}
    for path, hashes in target.files.items():
        old = source_keys.get(path.casefold())
        if old is not None and old[0] != path:
            raise InventoryError(f"Case-only path renames require a full installer: {path}")
        if old is None or old[1] != hashes:
            changed[path] = hashes
    if not changed:
        raise InventoryError("The patch contains no changed files.")
    require_safe_directory(output_dir)
    if output_dir.exists():
        raise InventoryError("Patch output must be a new directory; stale payloads are not reused.")
    output_dir.mkdir(parents=True)
    payload = output_dir / "payload"
    payload.mkdir()
    for relative, hashes in changed.items():
        destination = payload / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(bundle_root / relative, destination)
        if sha256_file(destination) != hashes[0]:
            raise InventoryError(f"Target changed while copying patch payload: {relative}")
    (output_dir / "source-owned-files.txt").write_bytes(source_data)
    target_sha256 = hashlib.sha256(target_data).hexdigest()
    marker = (
        "FPVS-TOOLBOX-PATCH-TRANSACTION-1\r\n"
        f"from={source_version}\r\nto={target_version}\r\n"
        f"source={source_inventory_sha256}\r\ntarget={target_sha256}\r\n"
    ).encode("utf-8-sig")
    (output_dir / "patch-transaction.txt").write_bytes(marker)
    # Native verification uses the same validated record parser for the sparse set.
    (output_dir / "patch-payload-files.txt").write_text(
        serialize_manifest(Inventory(changed), kind="pending", version="pending"),
        encoding="utf-8-sig",
        newline="",
    )
    result: dict[str, object] = {
        "from_version": source_version,
        "target_version": target_version,
        "source_inventory_sha256": source_inventory_sha256,
        "target_inventory_sha256": target_sha256,
        "transaction_sha256": hashlib.sha256(marker).hexdigest(),
        "asset_name": f"FPVSToolbox-Patch-{source_version}-to-{target_version}.exe",
        "payload_files": len(changed),
        "retained_files": len(target.files) - len(changed),
        "removed_files": sum(path.casefold() not in target_keys for path in source.files),
        "payload_bytes": sum((payload / path).stat().st_size for path in changed),
    }
    (output_dir / "patch-build.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def build_release_manifest(
    *, target_version: str, installer_dir: Path, patch_builds: list[Path]
) -> Path:
    """Bind release metadata to the final installer bytes, not compiler inputs."""

    validate_version(target_version)
    require_safe_directory(installer_dir)
    full = installer_dir / f"FPVSToolbox-{target_version}-setup.exe"
    if not full.is_file() or full.stat().st_size <= 0:
        raise InventoryError("The full installer must exist before release metadata is generated.")
    patches: list[dict[str, object]] = []
    versions: set[str] = set()
    for build_path in patch_builds:
        build = json.loads(build_path.read_text(encoding="utf-8"))
        source = validate_version(build["from_version"])
        if source in versions or build["target_version"] != target_version:
            raise InventoryError("Patch metadata has a duplicate source or mismatched target.")
        versions.add(source)
        name = f"FPVSToolbox-Patch-{source}-to-{target_version}.exe"
        if build["asset_name"] != name:
            raise InventoryError("Patch filename does not match its versions.")
        artifact = installer_dir / name
        size = artifact.stat().st_size
        if size <= 0 or artifact.is_symlink() or artifact.stat().st_nlink != 1:
            raise InventoryError("Patch artifact must be a nonempty regular single-link file.")
        patches.append(
            {
                "from_version": source,
                "source_inventory_sha256": validate_sha256(build["source_inventory_sha256"]),
                "asset_name": name,
                "size_bytes": size,
                "sha256": sha256_file(artifact),
            }
        )
    output = installer_dir / f"FPVSToolbox-Update-{target_version}.json"
    output.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "target_version": target_version,
                "platform": "windows-x64",
                "patches": sorted(patches, key=lambda patch: Version(str(patch["from_version"]))),
            },
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    artifacts = [full, *(installer_dir / str(patch["asset_name"]) for patch in patches), output]
    for artifact in artifacts:
        artifact.with_suffix(artifact.suffix + ".sha256").write_text(
            f"{sha256_file(artifact)}  {artifact.name}\n", encoding="ascii"
        )
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--baseline-inventory", type=Path, required=True)
    prepare.add_argument("--source-inventory-sha256", required=True)
    prepare.add_argument("--bundle-root", type=Path, required=True)
    prepare.add_argument("--target-inventory", type=Path, required=True)
    prepare.add_argument("--target-version", required=True)
    prepare.add_argument("--output-dir", type=Path, required=True)
    manifest = commands.add_parser("manifest")
    manifest.add_argument("--target-version", required=True)
    manifest.add_argument("--installer-dir", type=Path, required=True)
    manifest.add_argument("--patch-build", type=Path, action="append", default=[])
    arguments = vars(parser.parse_args())
    command = arguments.pop("command")
    try:
        if command == "prepare":
            result = prepare_patch(**arguments)
        else:
            arguments["patch_builds"] = arguments.pop("patch_build")
            result = str(build_release_manifest(**arguments))
    except (InventoryError, OSError, ValueError, KeyError) as error:
        sys.stderr.write(f"Patch packaging failed: {error}\n")
        return 1
    sys.stdout.write(json.dumps(result) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
