"""Export, post-export, and figure style helpers for Main App outputs."""

from __future__ import annotations

import importlib
from typing import Any

from Main_App.exports.figure_style import (
    FIGURE_EXPORT_DPI,
    FIGURE_FONT_FAMILY,
    FIGURE_OUTPUT_FORMATS,
    FIGURE_PANEL_LABEL_SIZE_PT,
    FIGURE_SMALL_TEXT_MIN_SIZE_PT,
    FIGURE_SUBSCRIPT_SUPERSCRIPT_MIN_SIZE_PT,
    FIGURE_TEXT_SIZE_PT,
    apply_matplotlib_figure_style,
    figure_text_kwargs,
)

_ANALYSIS_READY_NAMES = {
    "ANALYSIS_READY_RELATIVE_PATH",
    "ANALYSIS_READY_WORKBOOK_NAME",
    "AnalysisReadyWorkbookResult",
    "default_analysis_ready_workbook_path",
    "export_analysis_ready_workbook",
    "write_analysis_ready_workbook",
}
_POST_EXPORT_NAMES = {"LegacyCtx", "run_post_export"}

__all__ = [
    "ANALYSIS_READY_RELATIVE_PATH",
    "ANALYSIS_READY_WORKBOOK_NAME",
    "AnalysisReadyWorkbookResult",
    "FIGURE_EXPORT_DPI",
    "FIGURE_FONT_FAMILY",
    "FIGURE_OUTPUT_FORMATS",
    "FIGURE_PANEL_LABEL_SIZE_PT",
    "FIGURE_SMALL_TEXT_MIN_SIZE_PT",
    "FIGURE_SUBSCRIPT_SUPERSCRIPT_MIN_SIZE_PT",
    "FIGURE_TEXT_SIZE_PT",
    "LegacyCtx",
    "apply_matplotlib_figure_style",
    "default_analysis_ready_workbook_path",
    "figure_text_kwargs",
    "export_analysis_ready_workbook",
    "run_post_export",
    "write_analysis_ready_workbook",
]


def __getattr__(name: str) -> Any:
    """Load heavy processing exports only when callers request them."""

    if name in _ANALYSIS_READY_NAMES:
        module = importlib.import_module(
            "Main_App.exports.analysis_ready_workbook"
        )
        return getattr(module, name)
    if name in _POST_EXPORT_NAMES:
        module = importlib.import_module("Main_App.exports.post_export_adapter")
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
