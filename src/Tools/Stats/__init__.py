"""Public package surface for the Stats tool."""

__all__ = ["StatsWindow"]


def __getattr__(name: str):
    if name == "StatsWindow":
        from .ui.stats_window import StatsWindow

        return StatsWindow
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
