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
    initial_root = Path(view.excel_path_edit.text())
    if initial_root.exists():
        controller.set_excel_root(initial_root)
    return view
