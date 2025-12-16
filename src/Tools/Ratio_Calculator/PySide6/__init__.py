"""PySide6 implementation of the Ratio Calculator tool."""

from pathlib import Path

from .controller import RatioCalculatorController
from .view import RatioCalculatorWindow

__all__ = [
    "RatioCalculatorWindow",
    "RatioCalculatorController",
    "create_ratio_calculator_window",
]


def create_ratio_calculator_window(
    parent=None, project_root: Path | None = None
) -> RatioCalculatorWindow:
    view = RatioCalculatorWindow(parent=parent, project_root=project_root)
    controller = RatioCalculatorController(view)
    view.compute_requested.connect(controller.compute_ratios)
    view.excel_root_changed.connect(controller.set_excel_root)
    view.controller = controller  # type: ignore[attr-defined]
    initial_root_text = view.excel_path_edit.text().strip()
    initial_root = Path(initial_root_text) if initial_root_text else None
    if initial_root and initial_root.exists():
        controller.set_excel_root(initial_root)
    return view
