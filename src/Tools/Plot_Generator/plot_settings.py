import configparser
import os
from pathlib import Path

INI_NAME = "plot_settings.ini"


def _default_ini_path() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home()))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "FPVS_Toolbox" / INI_NAME


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
        if not self.config.has_option("plot", "include_scalp_maps"):
            self.set("plot", "include_scalp_maps", "false")
        if not self.config.has_option("plot", "scalp_min"):
            self.set("plot", "scalp_min", "-1.0")
        if not self.config.has_option("plot", "scalp_max"):
            self.set("plot", "scalp_max", "1.0")

    def load(self) -> None:
        self.config.read(self.ini_path)

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

    def get_scalp_bounds(self) -> tuple[float, float]:
        """Return stored scalp vmin/vmax bounds."""

        vmin = self.get_float("plot", "scalp_min", -1.0)
        vmax = self.get_float("plot", "scalp_max", 1.0)
        return vmin, vmax

    def set_scalp_bounds(self, vmin: float, vmax: float) -> None:
        self.set("plot", "scalp_min", str(vmin))
        self.set("plot", "scalp_max", str(vmax))

    def include_scalp_maps(self) -> bool:
        return self.get_bool("plot", "include_scalp_maps", False)

    def set_include_scalp_maps(self, enabled: bool) -> None:
        self.set("plot", "include_scalp_maps", str(enabled))
