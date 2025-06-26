import logging

from .settings_manager import SettingsManager

import mne


def configure_logging(debug_enabled: bool) -> None:
    """Configure root logging and MNE log levels.

    Parameters
    ----------
    debug_enabled : bool
        When ``True`` the root logger is set to ``DEBUG`` and MNE logs are
        raised to ``INFO`` for verbose output. Otherwise only ``INFO`` messages
        are shown and MNE logs are restricted to ``WARNING``.
    """

    level = logging.DEBUG if debug_enabled else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    mne.set_log_level("INFO" if debug_enabled else "WARNING")


def get_settings() -> SettingsManager:
    """Return a :class:`SettingsManager` instance."""
    return SettingsManager()
