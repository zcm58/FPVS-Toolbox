"""GUI-neutral active-project context resolution for embedded tools."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def resolve_active_project_root(
    provided_root: str | os.PathLike[str] | None,
    *,
    current_project: Any = None,
) -> Path | None:
    """Return the first existing root from the established tool precedence.

    The project root is runtime context derived from the directory containing
    ``project.json``.  It is intentionally not persisted inside the manifest so
    copied or renamed projects continue to rebase safely.
    """

    if provided_root:
        root = Path(provided_root)
        if root.exists():
            return root

    environment_root = os.environ.get("FPVS_PROJECT_ROOT")
    if environment_root:
        root = Path(environment_root)
        if root.exists():
            return root

    if current_project:
        project_root = getattr(current_project, "project_root", None)
        if project_root:
            root = Path(project_root)
            if root.exists():
                return root
    return None


__all__ = ["resolve_active_project_root"]
