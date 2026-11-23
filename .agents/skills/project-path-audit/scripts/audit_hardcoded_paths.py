from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / ".agents" / "scripts" / "audit" / "agent_audit.py"
        if candidate.exists():
            return parent
    raise SystemExit("Could not find repo root containing .agents/scripts/audit/agent_audit.py")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Check added text for local user paths.")
    parser.add_argument("--base-ref", help="Compare against this revision instead of the audit default.")
    args = parser.parse_args()

    root = _repo_root()
    audit = root / ".agents" / "scripts" / "audit" / "agent_audit.py"
    command = [sys.executable, str(audit), "--check", "paths"]
    if args.base_ref is not None:
        command.extend(["--base-ref", args.base_ref])
    raise SystemExit(
        subprocess.run(
            command,
            cwd=root,
            check=False,
        ).returncode
    )
