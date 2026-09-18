"""Generate dependency-free version data from the existing config.py owner."""

import ast
import json
from pathlib import Path


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
