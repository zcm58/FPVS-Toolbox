"""Public surface for the embedded LORETA brain visualizer."""

from __future__ import annotations

__all__ = ["LoretaVisualizerWindow"]


def __getattr__(name: str):
    if name == "LoretaVisualizerWindow":
        from .gui import LoretaVisualizerWindow

        return LoretaVisualizerWindow
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
