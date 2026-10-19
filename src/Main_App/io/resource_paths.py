"""Filesystem helpers for locating bundled application resources."""
from __future__ import annotations

from pathlib import Path
import sys


def bundle_path(*parts: str) -> Path:
    """Resolve a resource path for both source and frozen bundles."""
    # Preserve the source resource root of the historical Shared.paths API.
    source_root = Path(__file__).resolve().parents[1] / "Shared"
    base = Path(getattr(sys, "_MEIPASS", source_root))
    return (base / Path(*parts)).resolve()


__all__ = ["bundle_path"]
