import logging

from .settings_manager import SettingsManager


def configure_logging(debug_enabled: bool, log_file: str | None = None) -> None:
    """Attach console/file handlers and set global logging level."""
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


def get_settings() -> SettingsManager:
    """Return a :class:`SettingsManager` instance."""
    return SettingsManager()
