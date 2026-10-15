"""Compile the real Inno script with a tiny synthetic bundle; never run its output."""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

from build_installer_inventory import build_inventories, sha256_file


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inno-compiler", type=Path, required=True)
    arguments = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[2]
    check_root = repo_root / "build" / "installer-compile-checks"
    check_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="synthetic-", dir=check_root) as directory:
        fixture = Path(directory)
        # Both fixture creation and automatic teardown stay under this fresh test root.
        fixture.resolve().relative_to(check_root.resolve())
        bundle = fixture / "bundle"
        bundle.mkdir()
        executable = bundle / "FPVS_Toolbox.exe"
        executable.write_bytes(b"This is a non-executable packaging compile fixture.\n")
        (bundle / "_internal").mkdir()
        (bundle / "_internal" / "fixture.txt").write_text("compile only", encoding="utf-8")
        legacy = fixture / "synthetic-legacy.json"
        legacy.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "application": "fpvs-toolbox",
                    "releases": [
                        {
                            "tag": "v0.0.1",
                            "asset_name": "FPVSToolbox-0.0.1-setup.exe",
                            "asset_id": 1,
                            "sha256": "a" * 64,
                            "size_bytes": 1,
                        }
                    ],
                    "files": [{"path": "FPVS_Toolbox.exe", "sha256": [sha256_file(executable)]}],
                }
            ),
            encoding="utf-8",
        )
        inventories = fixture / "inventories"
        build_inventories(
            bundle_root=bundle,
            app_version="0.0.2",
            legacy_inventory=legacy,
            output_dir=inventories,
        )
        completed = subprocess.run(
            [
                str(arguments.inno_compiler.resolve()),
                "/Qp",
                "/DAppVersion=0.0.2",
                "/DWindowsVersion=0.0.2.0",
                f"/DBundleRoot={bundle}",
                f"/DOwnedInventoryRoot={inventories}",
                f"/O{fixture / 'compiled'}",
                "/FFPVSToolbox-Compile-Check",
                str(repo_root / "scripts" / "packaging" / "FPVS Toolbox Setup Script.iss"),
            ],
            check=False,
            timeout=120,
        )
        return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
