"""PySide6 GUI for generating SNR line plots from Excel files."""
from __future__ import annotations

# Allow running this module directly by ensuring the package root is on sys.path
if __package__ is None:  # pragma: no cover - executed when run as script
    import sys
    from pathlib import Path

    sys.path.append(str(Path(__file__).resolve().parents[2]))

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication

from Main_App.gui.theme import apply_fpvs_theme

from Tools.Plot_Generator import gui as _gui
from Tools.Plot_Generator import generation_workflow as _generation_workflow
from Tools.Plot_Generator import worker as _worker_module
from Tools.Plot_Generator.worker import _Worker
from Tools.Plot_Generator.gui import ALL_CONDITIONS_OPTION

matplotlib = _worker_module.matplotlib
plt = _worker_module.plt


class PlotGeneratorWindow(_gui.PlotGeneratorWindow):
    """Script entry-point wrapper that preserves patchable module hooks."""

    def _start_next_condition(self) -> None:
        old_worker = _gui._Worker
        old_thread = _gui.QThread
        old_workflow_worker = _generation_workflow._Worker
        old_workflow_thread = _generation_workflow.QThread
        _gui._Worker = _Worker
        _gui.QThread = QThread
        _generation_workflow._Worker = _Worker
        _generation_workflow.QThread = QThread
        try:
            super()._start_next_condition()
        finally:
            _gui._Worker = old_worker
            _gui.QThread = old_thread
            _generation_workflow._Worker = old_workflow_worker
            _generation_workflow.QThread = old_workflow_thread

__all__ = [
    "ALL_CONDITIONS_OPTION",
    "QThread",
    "_Worker",
    "PlotGeneratorWindow",
    "main",
    "matplotlib",
    "plt",
]


def main() -> None:
    app = QApplication([])
    apply_fpvs_theme(app)
    win = PlotGeneratorWindow()
    win.show()
    app.exec()


if __name__ == "__main__":
    main()
