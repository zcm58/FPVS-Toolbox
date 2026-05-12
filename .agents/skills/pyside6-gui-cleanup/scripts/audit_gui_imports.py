from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "scripts" / "audit" / "agent_audit.py"
        if candidate.exists():
            return parent
    raise SystemExit("Could not find repo root containing scripts/audit/agent_audit.py")


if __name__ == "__main__":
    root = _repo_root()
    raise SystemExit(
        subprocess.run(
            [sys.executable, str(root / "scripts" / "audit" / "agent_audit.py"), "--check", "gui"],
            cwd=root,
            check=False,
        ).returncode
    )
