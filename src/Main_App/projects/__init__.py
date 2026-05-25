"""Canonical Main App project import surface."""

from __future__ import annotations

import importlib
from typing import Any

_PROJECT_NAMES = {
    "Project",
    "DEFAULTS",
    "EXCEL_SUBFOLDER_NAME",
    "PROJECT_SCHEMA_VERSION",
    "SNR_SUBFOLDER_NAME",
    "STATS_SUBFOLDER_NAME",
    "_LEGACY_BANDPASS_WARNED",
    "make_group_id",
}
_PREPROCESSING_NAMES = {
    "PREPROCESSING_CANONICAL_KEYS",
    "PREPROCESSING_DEFAULTS",
    "normalize_preprocessing_settings",
}

__all__ = sorted(_PROJECT_NAMES | _PREPROCESSING_NAMES)


def __getattr__(name: str) -> Any:
    if name in _PROJECT_NAMES:
        project = importlib.import_module("Main_App.projects.project")

        return getattr(project, name)
    if name in _PREPROCESSING_NAMES:
        preprocessing_settings = importlib.import_module("Main_App.projects.preprocessing_settings")

        return getattr(preprocessing_settings, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
