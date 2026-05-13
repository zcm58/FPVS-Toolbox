"""Tool for generating SNR line plots."""

from .gui import PlotGeneratorWindow

__all__ = ["_Worker", "PlotGeneratorWindow", "main"]


def __getattr__(name: str):
    if name == "_Worker":
        from .worker import _Worker

        return _Worker
    if name == "main":
        from .plot_generator import main

        return main
    raise AttributeError(name)
