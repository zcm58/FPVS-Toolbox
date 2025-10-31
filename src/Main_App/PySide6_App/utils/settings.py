"""Shared application settings helpers."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

from PySide6.QtCore import QCoreApplication, QSettings, QStandardPaths

_SETTINGS_INSTANCE: QSettings | None = None
_MIGRATED = False

_LEGACY_KEYS: Iterable[str] = (
    "paths/projectsRoot",
    "recentProjects",
    "loreta/mri_path",
)


def _settings_file() -> Path:
    """Return the path to the user-specific INI settings file."""
    if not QCoreApplication.organizationName():
        QCoreApplication.setOrganizationName("MississippiStateUniversity")
    if not QCoreApplication.applicationName():
        QCoreApplication.setApplicationName("FPVS Toolbox")
    location = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
    if not location:
        raise RuntimeError("Unable to determine writable AppData location for settings storage.")
    base = Path(location)
    base.mkdir(parents=True, exist_ok=True)
    return base / "settings.ini"


def _migrate_legacy_settings(settings: QSettings) -> None:
    """Copy values from legacy native storage into the INI file once."""
    legacy = QSettings()
    migrated = False
    for key in _LEGACY_KEYS:
        if settings.contains(key):
            continue
        value = legacy.value(key, None)
        if value in (None, ""):
            continue
        settings.setValue(key, value)
        migrated = True
    if migrated:
        settings.sync()


def get_app_settings() -> QSettings:
    """Return the singleton settings object stored in the user's AppData directory."""
    global _SETTINGS_INSTANCE, _MIGRATED
    if _SETTINGS_INSTANCE is None:
        ini_path = _settings_file()
        _SETTINGS_INSTANCE = QSettings(str(ini_path), QSettings.IniFormat)
        _SETTINGS_INSTANCE.setFallbacksEnabled(False)
    if not _MIGRATED:
        _migrate_legacy_settings(_SETTINGS_INSTANCE)
        _MIGRATED = True
    return _SETTINGS_INSTANCE


__all__ = ["get_app_settings"]
