"""Static inventory of active application modules for PyInstaller's lazy APIs.

Public package adapters resolve several modules by name at runtime. Enumerate
only the two active application packages, without importing or scanning other
source-tree boundaries while building the bundle.
"""

from __future__ import annotations

from pathlib import Path


def active_runtime_imports(source_root: Path) -> list[str]:
    modules = set()
    for package in ("Main_App", "Tools"):
        root = source_root / package
        if not root.is_dir():
            raise RuntimeError(f"Active runtime package is missing: {root}")
        for path in root.rglob("*.py"):
            relative = path.relative_to(source_root).with_suffix("")
            parts = relative.parts[:-1] if relative.name == "__init__" else relative.parts
            modules.add(".".join(parts))
    return sorted(modules)
