"""Tool for generating SNR line plots."""

from .gui import PlotGeneratorWindow
from .worker import _Worker
from .plot_generator import main

__all__ = ["_Worker", "PlotGeneratorWindow", "main"]
