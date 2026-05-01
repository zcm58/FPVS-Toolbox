"""Centralized app-settings path resolution for FPVS Toolbox."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

APP_CONFIG_DIR_NAME = "FPVS Toolbox"
SETTINGS_SUBDIR_NAME = "settings"
APP_SETTINGS_INI_NAME = "settings.ini"
PLOT_SETTINGS_INI_NAME = "plot_settings.ini"
ENV_CONFIG_HOME = "FPVS_CONFIG_HOME"


class SettingsPathError(RuntimeError):
    """Raised when FPVS Toolbox cannot use the configured settings directory."""


def app_config_home() -> Path:
    """Return the app-level config root, preferring non-roaming user storage."""

    override = os.environ.get(ENV_CONFIG_HOME, "").strip()
    if override:
        return Path(override).expanduser()

    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA", "").strip()
        if not base:
            raise SettingsPathError(
                "Unable to determine %LOCALAPPDATA% for FPVS Toolbox settings. "
                f"Set {ENV_CONFIG_HOME} to a writable folder."
            )
        return Path(base) / APP_CONFIG_DIR_NAME

    base = os.environ.get("XDG_CONFIG_HOME", "").strip()
    if base:
        return Path(base) / APP_CONFIG_DIR_NAME
    return Path.home() / ".config" / APP_CONFIG_DIR_NAME


def app_settings_dir() -> Path:
    """Return the directory that owns app-level settings files."""

    return app_config_home() / SETTINGS_SUBDIR_NAME


def _ensure_writable_directory(path: Path) -> Path:
    """Create and verify a directory without silently falling back elsewhere."""

    try:
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix=".fpvs-write-", dir=path, delete=True):
            pass
    except OSError as exc:
        raise SettingsPathError(
            f"FPVS Toolbox settings directory is not writable: {path}. "
            f"Set {ENV_CONFIG_HOME} to a writable folder."
        ) from exc
    return path


def app_settings_file(*, ensure_writable: bool = True) -> Path:
    """Return the central app settings INI path."""

    directory = app_settings_dir()
    if ensure_writable:
        _ensure_writable_directory(directory)
    return directory / APP_SETTINGS_INI_NAME


def app_plot_settings_file(*, ensure_writable: bool = True) -> Path:
    """Return the legacy-compatible Plot Generator app defaults path."""

    directory = app_settings_dir()
    if ensure_writable:
        _ensure_writable_directory(directory)
    return directory / PLOT_SETTINGS_INI_NAME


def app_logs_dir(*, ensure_writable: bool = True) -> Path:
    """Return the app-level log directory."""

    directory = app_config_home() / "logs"
    if ensure_writable:
        _ensure_writable_directory(directory)
    return directory


def legacy_roaming_config_home() -> Path | None:
    """Return the old roaming AppData config root, if the environment exposes it."""

    base = os.environ.get("APPDATA", "").strip()
    if not base:
        return None
    return Path(base) / "FPVS_Toolbox"


def legacy_settings_file() -> Path | None:
    """Return the old shared settings path used before the strict-hybrid layout."""

    root = legacy_roaming_config_home()
    if root is None:
        return None
    return root / APP_SETTINGS_INI_NAME


def legacy_plot_settings_file() -> Path | None:
    """Return the old Plot Generator settings path used before the strict-hybrid layout."""

    root = legacy_roaming_config_home()
    if root is None:
        return None
    return root / PLOT_SETTINGS_INI_NAME


__all__ = [
    "ENV_CONFIG_HOME",
    "SettingsPathError",
    "app_config_home",
    "app_settings_dir",
    "app_settings_file",
    "app_plot_settings_file",
    "app_logs_dir",
    "legacy_roaming_config_home",
    "legacy_settings_file",
    "legacy_plot_settings_file",
]
