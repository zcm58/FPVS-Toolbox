import configparser
import os
from pathlib import Path

INI_NAME = 'plot_settings.ini'


def _default_ini_path() -> Path:
    if os.name == 'nt':
        base = Path(os.environ.get('APPDATA', Path.home()))
    else:
        base = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config'))
    return base / 'FPVS_Toolbox' / INI_NAME


class PlotSettingsManager:
    """Simple INI manager for storing plot tool defaults."""

    def __init__(self, ini_path: Path | None = None) -> None:
        self.ini_path = ini_path or _default_ini_path()
        self.config = configparser.ConfigParser()
        self.load()
        if not self.config.has_option("plot", "stem_color"):
            self.set("plot", "stem_color", "red")
        if not self.config.has_option("plot", "stem_color_b"):
            self.set("plot", "stem_color_b", "blue")

    def load(self) -> None:
        self.config.read(self.ini_path)

    def save(self) -> None:
        self.ini_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.ini_path, 'w') as f:
            self.config.write(f)

    def get(self, section: str, option: str, fallback: str = '') -> str:
        return self.config.get(section, option, fallback=fallback)

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
