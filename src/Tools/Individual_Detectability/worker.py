"""Qt signal adapter for Individual Detectability export."""

from __future__ import annotations

import traceback

from PySide6.QtCore import QObject, Signal

from Main_App.processing.canonical_harmonics import CanonicalHarmonicSelectionError

from .core import ManagedDetectabilityInputError
from .export_run import RunRequest, run_detectability_export


class IndividualDetectabilityWorker(QObject):
    progress = Signal(int)
    status = Signal(str)
    log = Signal(str)
    error = Signal(str)
    finished = Signal(str)

    def __init__(self, request: RunRequest) -> None:
        super().__init__()
        self._request = request

    def _emit_log(self, message: str) -> None:
        self.log.emit(message)
        self.status.emit(message)

    def run(self) -> None:
        try:
            output_root = run_detectability_export(
                self._request,
                log=self._emit_log,
                status=self.status.emit,
                progress=self.progress.emit,
            )
            self.finished.emit(str(output_root))
        except (CanonicalHarmonicSelectionError, ManagedDetectabilityInputError) as exc:
            self.error.emit(str(exc))
        except Exception:
            self.error.emit(traceback.format_exc())
