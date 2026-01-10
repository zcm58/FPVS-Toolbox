from __future__ import annotations

from typing import Any

from Tools.Ratio_Calculator.PySide6 import create_ratio_calculator_window


def open_ratio_calculator(parent: Any) -> None:
    existing = getattr(parent, "_ratio_calc_win", None)
    project_root = getattr(getattr(parent, "currentProject", None), "project_root", None)
    if existing:
        existing.show()
        existing.raise_()
        existing.activateWindow()
        return

    window = create_ratio_calculator_window(parent=parent, project_root=project_root)
    parent._ratio_calc_win = window
    window.show()
    window.raise_()
    window.activateWindow()
