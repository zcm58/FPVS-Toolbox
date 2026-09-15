"""Read-only installed-file parity check for an explicitly selected test installation.

This does not install, uninstall, clean directories, or run FPVS Toolbox. Unknown user
files are preserved and are not silently promoted into installer ownership.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from build_installer_inventory import (
    CURRENT_MANIFEST_NAME,
    PENDING_MANIFEST_NAME,
    Inventory,
    InventoryError,
    inspect_obsolete_inventory,
    load_legacy_inventory,
    obsolete_inventory,
    read_manifest_file,
    require_safe_directory,
)


def check_tree(
    *, install_root: Path, expected_manifest: Path, legacy_inventory: Path
) -> dict[str, object]:
    require_safe_directory(install_root)
    expected_bytes, current = read_manifest_file(
        expected_manifest.absolute(), expected_kind="current"
    )
    installed_bytes, _ = read_manifest_file(
        install_root / CURRENT_MANIFEST_NAME, expected_kind="current"
    )
    actual = inspect_obsolete_inventory(install_root, current)
    legacy, _ = load_legacy_inventory(legacy_inventory)
    histories = dict(legacy.files)
    pending_path = install_root / PENDING_MANIFEST_NAME
    if pending_path.exists():
        _, pending = read_manifest_file(pending_path, expected_kind="pending")
        canonical = {path.casefold(): path for path in histories}
        for path, hashes in pending.files.items():
            key = canonical.get(path.casefold(), path)
            histories[key] = tuple(sorted(set(histories.get(key, ())) | set(hashes)))
    obsolete = inspect_obsolete_inventory(
        install_root, obsolete_inventory(Inventory(histories), current)
    )
    invalid_current = {path: status for path, status in actual.items() if status != "owned"}
    remaining_owned = sorted(path for path, status in obsolete.items() if status == "owned")
    unverified = {
        path: status for path, status in obsolete.items() if status in {"unsafe", "unavailable"}
    }
    return {
        "ok": not invalid_current
        and not remaining_owned
        and not unverified
        and installed_bytes == expected_bytes,
        "manifest_matches": installed_bytes == expected_bytes,
        "current_file_count": len(current.files),
        "invalid_current_files": invalid_current,
        "remaining_obsolete_owned_files": remaining_owned,
        "preserved_modified_files": sorted(
            path for path, status in obsolete.items() if status == "modified"
        ),
        "unverified_obsolete_paths": unverified,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install-root", type=Path, required=True)
    parser.add_argument("--expected-manifest", type=Path, required=True)
    parser.add_argument("--legacy-inventory", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        report = check_tree(
            install_root=arguments.install_root.absolute(),
            expected_manifest=arguments.expected_manifest,
            legacy_inventory=arguments.legacy_inventory,
        )
    except (InventoryError, OSError) as error:
        sys.stderr.write(f"Installer tree check failed: {error}\n")
        return 1
    sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
