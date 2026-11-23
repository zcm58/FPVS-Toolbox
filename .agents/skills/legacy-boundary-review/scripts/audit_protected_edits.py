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


def main() -> int:
    parser = argparse.ArgumentParser(description="Check the Toolbox's retired package boundaries.")
    parser.add_argument(
        "--base-ref",
        help="Compare new references against this Git revision. Defaults to FPVS_AGENT_AUDIT_BASE_REF, then HEAD.",
    )
    args = parser.parse_args()
    root = _repo_root()
    audit = root / ".agents" / "scripts" / "audit" / "agent_audit.py"
    comparison_args = ["--base-ref", args.base_ref] if args.base_ref is not None else []
    returncode = 0
    for check in ("protected", "source-localization", "source-localization-refs"):
        result = subprocess.run(
            [sys.executable, str(audit), "--check", check, *comparison_args],
            cwd=root,
            check=False,
        )
        returncode = returncode or result.returncode
    return returncode


if __name__ == "__main__":
    raise SystemExit(main())
