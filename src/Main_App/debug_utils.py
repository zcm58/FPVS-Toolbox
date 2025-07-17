import logging

from .settings_manager import SettingsManager
from tkinter import messagebox

import mne



def configure_logging(debug_enabled: bool, log_file: str | None = None) -> None:
    """Configure root logging and MNE log levels.

    Parameters
    ----------
    debug_enabled : bool
        When ``True`` the root logger is set to ``DEBUG`` and MNE logs are
        raised to ``INFO`` for verbose output. Otherwise only ``INFO`` messages
        are shown and MNE logs are restricted to ``WARNING``.
    log_file : str | None, optional
        Optional path to a log file. When provided, log messages will also be
        written to this file using UTF-8 encoding.
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


def install_messagebox_logger(debug_enabled: bool) -> None:
    """Wrap tkinter messagebox functions to emit debug logs when called."""
    if not debug_enabled:
        return

    logger = logging.getLogger(__name__)

    def _wrap(func):
        def inner(*args, **kwargs):
            logger.debug("messagebox.%s called args=%s kwargs=%s", func.__name__, args, kwargs)
            return func(*args, **kwargs)
        return inner

    for name in ("showerror", "showinfo", "showwarning", "askyesno"):
        if hasattr(messagebox, name):
            setattr(messagebox, name, _wrap(getattr(messagebox, name)))
