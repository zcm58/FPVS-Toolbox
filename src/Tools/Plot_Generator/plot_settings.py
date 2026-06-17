import configparser
import logging
from pathlib import Path

from Main_App.Shared.settings_paths import app_plot_settings_file, legacy_plot_settings_file

INI_NAME = "plot_settings.ini"
logger = logging.getLogger(__name__)


def _default_ini_path() -> Path:
    return app_plot_settings_file()


def _path_exists_for_migration(path: Path | None) -> bool:
    """Return whether a legacy plot settings path exists without failing startup."""

    if path is None:
        return False
    try:
        return path.exists()
    except OSError as exc:
        logger.warning(
            "legacy_plot_settings_probe_failed",
            extra={"path": str(path), "error": str(exc)},
        )
        return False


class PlotSettingsManager:
    """Simple INI manager for storing plot tool defaults."""

    def __init__(self, ini_path: Path | None = None) -> None:
        self._uses_default_path = ini_path is None
        self.ini_path = ini_path or _default_ini_path()
        self.config = configparser.ConfigParser()
        self.load()
        if not self.config.has_option("plot", "stem_color"):
            self.set("plot", "stem_color", "red")
        if not self.config.has_option("plot", "stem_color_b"):
            self.set("plot", "stem_color_b", "blue")

    def load(self) -> None:
        if self.ini_path.exists():
            self.config.read(self.ini_path)
            return
        if self._uses_default_path:
            old_path = legacy_plot_settings_file()
            if _path_exists_for_migration(old_path):
                self.config.read(old_path)

    def save(self) -> None:
        self.ini_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.ini_path, "w", encoding="utf-8") as f:
            self.config.write(f)

    def get(self, section: str, option: str, fallback: str = "") -> str:
        return self.config.get(section, option, fallback=fallback)

    def get_bool(self, section: str, option: str, fallback: bool = False) -> bool:
        return self.config.getboolean(section, option, fallback=fallback)

    def get_float(self, section: str, option: str, fallback: float = 0.0) -> float:
        try:
            return self.config.getfloat(section, option, fallback=fallback)
        except ValueError:
            return fallback

    def get_stem_color(self) -> str:
        """Return the stored stem plot line color."""
        return self.get("plot", "stem_color", "red")

    def get_second_color(self) -> str:
        """Return the stored second stem plot color."""
        return self.get("plot", "stem_color_b", "blue")

    def set(self, section: str, option: str, value: str) -> None:
        if not self.config.has_section(section):
            self.config.add_section(section)
        self.config.set(section, option, value)

    def set_stem_color(self, color: str) -> None:
        """Persist the stem plot line color."""
        self.set("plot", "stem_color", color)

    def set_second_color(self, color: str) -> None:
        """Persist the second stem plot line color."""
        self.set("plot", "stem_color_b", color)
