"""Filesystem helpers for locating bundled application resources."""
from __future__ import annotations

from pathlib import Path
import sys


def bundle_path(*parts: str) -> Path:
    """Resolve a resource path for both source and frozen bundles."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return (base / Path(*parts)).resolve()


__all__ = ["bundle_path"]
