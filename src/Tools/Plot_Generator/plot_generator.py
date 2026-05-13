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
from Tools.Plot_Generator.gui import ALL_CONDITIONS_OPTION


class _LazyWorkerAttr:
    def __init__(self, name: str) -> None:
        object.__setattr__(self, "_name", name)

    def _resolve(self):
        from Tools.Plot_Generator import worker

        return getattr(worker, self._name)

    def __call__(self, *args, **kwargs):
        return self._resolve()(*args, **kwargs)

    def __getattr__(self, name: str):
        return getattr(self._resolve(), name)

    def __setattr__(self, name: str, value) -> None:
        if name == "_name":
            object.__setattr__(self, name, value)
            return
        setattr(self._resolve(), name, value)


_Worker = _LazyWorkerAttr("_Worker")
matplotlib = _LazyWorkerAttr("matplotlib")
plt = _LazyWorkerAttr("plt")


class PlotGeneratorWindow(_gui.PlotGeneratorWindow):
    """Script entry-point wrapper that preserves patchable module hooks."""

    def _start_next_condition(self) -> None:
        old_worker = getattr(_gui, "_Worker", None)
        old_thread = _gui.QThread
        old_workflow_thread = _generation_workflow.QThread
        _gui._Worker = _Worker
        _gui.QThread = QThread
        _generation_workflow.QThread = QThread
        try:
            super()._start_next_condition()
        finally:
            if old_worker is None:
                delattr(_gui, "_Worker")
            else:
                _gui._Worker = old_worker
            _gui.QThread = old_thread
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
