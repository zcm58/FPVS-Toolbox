"""Compatibility wrapper for :mod:`Main_App.projects.preprocessing_settings`."""

from Main_App.projects.preprocessing_settings import (  # noqa: F401
    PREPROCESSING_CANONICAL_KEYS,
    PREPROCESSING_DEFAULTS,
    normalize_preprocessing_settings,
)

__all__ = [
    "PREPROCESSING_CANONICAL_KEYS",
    "PREPROCESSING_DEFAULTS",
    "normalize_preprocessing_settings",
]
