"""Publication scalp map tool package."""

from __future__ import annotations

__all__ = ("PublicationMapsWindow",)


def __getattr__(name: str):
    if name == "PublicationMapsWindow":
        from Tools.Publication_Maps.gui import PublicationMapsWindow

        return PublicationMapsWindow
    raise AttributeError(name)
