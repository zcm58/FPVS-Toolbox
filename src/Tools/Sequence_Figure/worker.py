"""Worker shell for sequence figure export."""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal

from .renderer import SequenceFigureResult, SequenceFigureSpec, render_sequence_figure

logger = logging.getLogger(__name__)


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
            logger.exception("Sequence figure export failed.", extra={"operation": "sequence_figure_export"})
            self.failed.emit(str(exc))
            return
        self.progress.emit("Export complete.")
        self.finished.emit(result)
