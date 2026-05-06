"""Compatibility wrapper for :mod:`Main_App.projects.project_manager`."""

from Main_App.projects.project_manager import (  # noqa: F401
    CANCEL_SCAN_MESSAGE,
    _ProjectScanJob,
    edit_project_settings,
    loadProject,
    new_project,
    openProjectPath,
    open_existing_project,
    select_projects_root,
)

__all__ = [
    "CANCEL_SCAN_MESSAGE",
    "_ProjectScanJob",
    "edit_project_settings",
    "loadProject",
    "new_project",
    "openProjectPath",
    "open_existing_project",
    "select_projects_root",
]
