"""Compatibility wrapper for :mod:`Main_App.projects.project_metadata`."""

from Main_App.projects.project_metadata import (  # noqa: F401
    ProjectMetadata,
    enumerate_project_metadata,
    read_project_metadata,
)

__all__ = [
    "ProjectMetadata",
    "enumerate_project_metadata",
    "read_project_metadata",
]
