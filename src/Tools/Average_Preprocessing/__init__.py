"""Average preprocessing tool exports."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from Tools.Average_Preprocessing.Legacy.advanced_analysis_core import (
        run_advanced_averaging_processing,
    )
    from Tools.Average_Preprocessing.New_PySide6.main_window import AdvancedAveragingWindow


def get_advanced_averaging_window() -> "type[AdvancedAveragingWindow]":
    """Lazy-load the active PySide6 advanced averaging window."""
    from Tools.Average_Preprocessing.New_PySide6.main_window import AdvancedAveragingWindow

    return AdvancedAveragingWindow


def get_advanced_averaging_processing() -> "run_advanced_averaging_processing":
    """Lazy-load the UI-agnostic advanced averaging processing function."""
    from Tools.Average_Preprocessing.Legacy.advanced_analysis_core import (
        run_advanced_averaging_processing,
    )

    return run_advanced_averaging_processing


def __getattr__(name: str):
    if name in {"AdvancedAveragingWindow", "AdvancedAnalysisWindow"}:
        value = get_advanced_averaging_window()
        globals()[name] = value
        return value
    if name == "run_advanced_averaging_processing":
        value = get_advanced_averaging_processing()
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "AdvancedAnalysisWindow",
    "AdvancedAveragingWindow",
    "get_advanced_averaging_window",
    "get_advanced_averaging_processing",
    "run_advanced_averaging_processing",
]
