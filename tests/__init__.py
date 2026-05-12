# Tests package marker for reliable intra-test imports.
from __future__ import annotations

from pathlib import Path


def repo_root() -> Path:
    root = Path(__file__).resolve().parents[1]
    if not (root / "src").is_dir():
        raise RuntimeError(f"Unable to resolve repository root from {__file__}")
    return root
