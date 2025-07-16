"""Plot generator tool for creating SNR/BCA line plots."""

from .gui import PlotGeneratorWindow
from .worker import _Worker
from .plot_generator import main

__all__ = ["_Worker", "PlotGeneratorWindow", "main"]
