"""Bind the Windows installer handoff to its source, build run, and file bytes."""

from __future__ import annotations

import argparse
import json
import stat
from pathlib import Path

from build_installer_inventory import (
    is_reparse_stat,
    require_safe_directory,
    sha256_file,
    validate_version,
)
from updater_metadata import source_version


PROVENANCE = Path("build/release-acceptance/build-provenance.json")
RECEIPT = Path("build/release-acceptance/candidate-artifacts.json")
INVENTORY = Path("build/installer-inventory/current-owned-files.txt")


def _regular_file(path: Path) -> Path:
    require_safe_directory(path.parent)
    details = path.lstat()
    if is_reparse_stat(details) or not stat.S_ISREG(details.st_mode) or details.st_nlink != 1:
        raise RuntimeError(f"Expected a regular release file: {path.name}")
    return path


def candidate_receipt(repo: Path, commit: str, run_id: str) -> dict[str, object]:
    provenance = json.loads(_regular_file(repo / PROVENANCE).read_text(encoding="utf-8-sig"))
    if provenance["commit"] != commit or provenance["run_id"] != run_id:
        raise RuntimeError("Installer was built for a different commit or workflow run.")
    version = validate_version(source_version(repo))
    installer = Path("installers") / f"FPVSToolbox-{version}-setup.exe"
    metadata = installer.with_name(f"FPVSToolbox-Update-{version}.json")
    sidecars = [path.with_name(path.name + ".sha256") for path in (installer, metadata)]
    assets = [installer, metadata, *sidecars]
    installer_dir = require_safe_directory(repo / installer.parent)
    if {path.name for path in installer_dir.iterdir()} != {path.name for path in assets}:
        raise RuntimeError("Installer directory must contain the exact full-release asset set.")
    digests = {
        relative.as_posix(): sha256_file(_regular_file(repo / relative))
        for relative in (*assets, INVENTORY, PROVENANCE)
    }
    for asset, sidecar in zip((installer, metadata), sidecars, strict=True):
        expected = f"{digests[asset.as_posix()]}  {asset.name}"
        if (repo / sidecar).read_text(encoding="ascii").strip() != expected:
            raise RuntimeError(f"Release checksum sidecar differs from candidate bytes: {asset.name}")
    return {"schema": 1, "commit": commit, "run_id": run_id, "version": version, "sha256": digests}


def verify_candidate(repo: Path, commit: str, run_id: str) -> None:
    receipt = json.loads(_regular_file(repo / RECEIPT).read_text(encoding="utf-8"))
    if receipt != candidate_receipt(repo, commit, run_id):
        raise RuntimeError("Installer candidate differs from its build receipt.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("record", "verify"))
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    repo = args.repo_root.absolute()
    if args.action == "record":
        receipt = candidate_receipt(repo, args.commit, args.run_id)
        with (repo / RECEIPT).open("x", encoding="utf-8") as stream:
            json.dump(receipt, stream, indent=2)
            stream.write("\n")
    else:
        verify_candidate(repo, args.commit, args.run_id)


if __name__ == "__main__":
    main()
