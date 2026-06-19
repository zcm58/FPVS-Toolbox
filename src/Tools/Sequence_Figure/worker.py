"""Worker shell for sequence figure export."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from .renderer import SequenceFigureResult, SequenceFigureSpec, render_sequence_figure


class SequenceFigureWorker(QObject):
    """Run figure rendering outside the UI thread."""

    progress = Signal(str)
    failed = Signal(str)
    finished = Signal(object)

    def __init__(self, spec: SequenceFigureSpec) -> None:
        super().__init__()
        self._spec = spec

    def run(self) -> None:
        self.progress.emit("Rendering sequence figure...")
        try:
            result: SequenceFigureResult = render_sequence_figure(self._spec)
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.progress.emit("Export complete.")
        self.finished.emit(result)
