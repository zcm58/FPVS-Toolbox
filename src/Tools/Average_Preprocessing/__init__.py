"""Average preprocessing tool exports."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable, TypeVar

logger = logging.getLogger(__name__)

LEGACY_AVERAGE_PREPROCESSING_UI_ERROR_MESSAGE = (
    "Legacy Average Preprocessing UI requires CustomTkinter/Tkinter and is not available in this build."
)

_T = TypeVar("_T")

if TYPE_CHECKING:
    from Tools.Average_Preprocessing.Legacy.advanced_analysis import AdvancedAnalysisWindow
    from Tools.Average_Preprocessing.Legacy.advanced_analysis_core import (
        run_advanced_averaging_processing,
    )


def _log_tkinter_diagnostics() -> None:
    try:
        import tkinter as tk
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.warning(
            "Failed to import tkinter for legacy Average Preprocessing diagnostics: %s",
            exc,
        )
        return

    logger.info(
        "Legacy Average Preprocessing tkinter diagnostics: tkinter=%s has_canvas=%s",
        getattr(tk, "__file__", "unknown"),
        hasattr(tk, "Canvas"),
    )


def _import_legacy(symbol_name: str, importer: Callable[[], _T]) -> _T:
    try:
        return importer()
    except Exception as exc:
        logger.error("Failed to import legacy Average Preprocessing %s.", symbol_name, exc_info=exc)
        raise RuntimeError(LEGACY_AVERAGE_PREPROCESSING_UI_ERROR_MESSAGE) from exc


def get_legacy_advanced_analysis_window() -> "type[AdvancedAnalysisWindow]":
    """Lazy-load the legacy AdvancedAnalysisWindow UI class."""
    _log_tkinter_diagnostics()

    def _importer() -> "type[AdvancedAnalysisWindow]":
        from Tools.Average_Preprocessing.Legacy.advanced_analysis import AdvancedAnalysisWindow

        return AdvancedAnalysisWindow

    return _import_legacy("AdvancedAnalysisWindow", _importer)


def get_legacy_advanced_averaging_processing() -> "run_advanced_averaging_processing":
    """Lazy-load the legacy advanced averaging processing function."""

    def _importer() -> "run_advanced_averaging_processing":
        from Tools.Average_Preprocessing.Legacy.advanced_analysis_core import (
            run_advanced_averaging_processing,
        )

        return run_advanced_averaging_processing

    return _import_legacy("run_advanced_averaging_processing", _importer)


def __getattr__(name: str):
    if name == "AdvancedAnalysisWindow":
        value = get_legacy_advanced_analysis_window()
        globals()[name] = value
        return value
    if name == "run_advanced_averaging_processing":
        value = get_legacy_advanced_averaging_processing()
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "AdvancedAnalysisWindow",
    "LEGACY_AVERAGE_PREPROCESSING_UI_ERROR_MESSAGE",
    "get_legacy_advanced_analysis_window",
    "get_legacy_advanced_averaging_processing",
    "run_advanced_averaging_processing",
]
