from __future__ import annotations

import ast
import os
from pathlib import Path
import subprocess
import sys


def test_default_snr_tool_does_not_import_beta_stats_package() -> None:
    tool_root = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "Tools"
        / "Plot_Generator"
    )
    violations: list[str] = []
    for source_path in sorted(tool_root.glob("*.py")):
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            if any(
                name == "Tools.Stats" or name.startswith("Tools.Stats.")
                for name in names
            ):
                violations.append(f"{source_path.name}:{node.lineno}")
    assert violations == []


def test_snr_worker_import_does_not_load_beta_stats_package() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(repo_root / "src")
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import Tools.Plot_Generator.worker; "
                "assert not any(name == 'Tools.Stats' or "
                "name.startswith('Tools.Stats.') for name in sys.modules)"
            ),
        ],
        cwd=repo_root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr or result.stdout
