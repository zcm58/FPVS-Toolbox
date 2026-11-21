"""FPVS stimulus sequence figure generator."""

from __future__ import annotations

from .renderer import SequenceFigureResult, SequenceFigureSpec, render_sequence_figure

__all__ = [
    "SequenceFigureResult",
    "SequenceFigureSpec",
    "SequenceFigureWindow",
    "render_sequence_figure",
]


def __getattr__(name: str):
    if name == "SequenceFigureWindow":
        from .gui import SequenceFigureWindow

        return SequenceFigureWindow
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
