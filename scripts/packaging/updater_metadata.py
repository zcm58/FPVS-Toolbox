"""Extract config-owned version data without importing the scientific runtime."""

import ast
import json
from pathlib import Path

from packaging.version import Version


def windows_version(display_version: str) -> str:
    """Map a release/prerelease label to Inno's four numeric version fields."""
    version = Version(display_version)
    release = version.release
    if version.epoch or len(release) > 4 or any(part > 65535 for part in release):
        raise ValueError("Windows versions require at most four fields in 0..65535, with no epoch.")
    return ".".join(str(part) for part in (*release, *(0 for _ in range(4 - len(release)))))


def version_data(repo: Path) -> tuple[Path, str]:
    tree = ast.parse((repo / "src/config.py").read_text(encoding="utf-8-sig"))
    values = [
        ast.literal_eval(n.value)
        for n in tree.body
        if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name) and n.target.id == "FPVS_TOOLBOX_VERSION"
    ]
    if len(values) != 1 or not isinstance(values[0], str):
        raise RuntimeError("Toolbox config.py must declare one version.")
    destination = repo / "build/updater-metadata/toolbox-updater-version.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps({"version": values[0]}), encoding="utf-8")
    return destination, values[0]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--windows-version", required=True)
    sys.stdout.write(windows_version(parser.parse_args().windows_version))
