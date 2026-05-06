"""Compatibility wrapper for :mod:`Main_App.projects.project`."""

from Main_App.projects.project import (  # noqa: F401
    DEFAULTS,
    EXCEL_SUBFOLDER_NAME,
    SNR_SUBFOLDER_NAME,
    STATS_SUBFOLDER_NAME,
    Project,
    _LEGACY_BANDPASS_WARNED,
)

__all__ = [
    "DEFAULTS",
    "EXCEL_SUBFOLDER_NAME",
    "SNR_SUBFOLDER_NAME",
    "STATS_SUBFOLDER_NAME",
    "Project",
    "_LEGACY_BANDPASS_WARNED",
]
