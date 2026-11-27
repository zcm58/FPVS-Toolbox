"""Appearance preferences shared with the standalone updater."""

from configparser import ConfigParser, Error
import logging

from Main_App.settings.settings_paths import SettingsPathError, app_settings_file, read_settings_text

APPEARANCE_MODES = ("Light", "Dark", "Auto")
DEFAULT_APPEARANCE_MODE = "Auto"
logger = logging.getLogger(__name__)


def normalize_appearance_mode(mode: str) -> str | None:
    mode = mode.strip().title()
    if mode == "System":
        return DEFAULT_APPEARANCE_MODE
    return mode if mode in APPEARANCE_MODES else None


def appearance_mode_from_config(config: ConfigParser) -> str:
    mode = config.get("appearance", "mode", fallback=DEFAULT_APPEARANCE_MODE, raw=True)
    normalized = normalize_appearance_mode(mode)
    if normalized is None:
        logger.warning("appearance_mode_invalid_using_auto")
        return DEFAULT_APPEARANCE_MODE
    return normalized


def read_saved_appearance_mode() -> str:
    """Read the shared preference without creating or migrating files."""
    config = ConfigParser()
    config.read_dict({"appearance": {"mode": DEFAULT_APPEARANCE_MODE}})
    try:
        path = app_settings_file(ensure_writable=False)
        config.read_string(read_settings_text(path), source=str(path))
    except FileNotFoundError:
        return DEFAULT_APPEARANCE_MODE
    except (Error, OSError, SettingsPathError, UnicodeError):
        logger.warning("appearance_settings_read_failed", exc_info=True)
        return DEFAULT_APPEARANCE_MODE
    return appearance_mode_from_config(config)
