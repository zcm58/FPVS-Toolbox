"""Compatibility wrapper for :mod:`Main_App.projects.projects_root`."""

from Main_App.projects.projects_root import (  # noqa: F401
    changeProjectsRoot,
    ensure_projects_root,
)

__all__ = ["changeProjectsRoot", "ensure_projects_root"]
