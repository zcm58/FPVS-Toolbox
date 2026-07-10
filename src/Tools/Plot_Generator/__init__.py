"""Tool for generating SNR line plots."""

from .gui import PlotGeneratorWindow

__all__ = ["_Worker", "PlotGeneratorWindow"]


def __getattr__(name: str):
    if name == "_Worker":
        from .worker import _Worker

        return _Worker
    raise AttributeError(name)
