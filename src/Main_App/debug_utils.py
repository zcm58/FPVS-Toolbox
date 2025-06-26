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

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(level)

    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    formatter = logging.Formatter(fmt)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    mne.set_log_level("INFO" if debug_enabled else "WARNING")


def get_settings() -> SettingsManager:
    """Return a :class:`SettingsManager` instance."""
    return SettingsManager()
