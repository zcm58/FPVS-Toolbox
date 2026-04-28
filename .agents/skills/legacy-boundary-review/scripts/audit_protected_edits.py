from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "scripts" / "agent_audit.py"
        if candidate.exists():
            return parent
    raise SystemExit("Could not find repo root containing scripts/agent_audit.py")


if __name__ == "__main__":
    root = _repo_root()
    protected = subprocess.run(
        [sys.executable, str(root / "scripts" / "agent_audit.py"), "--check", "protected"],
        cwd=root,
        check=False,
    )
    source_localization = subprocess.run(
        [sys.executable, str(root / "scripts" / "agent_audit.py"), "--check", "source-localization"],
        cwd=root,
        check=False,
    )
    raise SystemExit(protected.returncode or source_localization.returncode)
