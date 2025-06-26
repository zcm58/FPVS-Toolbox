import logging

from .settings_manager import SettingsManager


def configure_logging(debug_enabled: bool) -> None:
    """Configure root logging level based on debug flag."""
    level = logging.DEBUG if debug_enabled else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def get_settings() -> SettingsManager:
    """Return a :class:`SettingsManager` instance."""
    return SettingsManager()
