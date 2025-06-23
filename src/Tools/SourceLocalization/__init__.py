"""Source localization tools using (s/e)LORETA."""

from .eloreta_gui import SourceLocalizationWindow
from .eloreta_runner import run_source_localization

__all__ = ["SourceLocalizationWindow", "run_source_localization"]
