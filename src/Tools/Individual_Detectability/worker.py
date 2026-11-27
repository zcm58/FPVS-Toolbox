"""Qt signal adapter for Individual Detectability export."""

from __future__ import annotations

import traceback
import logging
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Signal

from Main_App.processing.canonical_harmonics import CanonicalHarmonicSelectionError

from .core import ManagedDetectabilityInputError
from .export_run import RunRequest, run_detectability_export
from .project_coverage import discover_project_conditions


class _ScanSignals(QObject):
    finished = Signal(object, str)


class ManagedConditionScan(QRunnable):
    def __init__(self, project_root: Path, input_root: Path) -> None:
        super().__init__()
        self.project_root = project_root
        self.input_root = input_root
        self.signals = _ScanSignals()

    def run(self) -> None:
        try:
            conditions = discover_project_conditions(self.project_root, self.input_root)
        except Exception as exc:
            logging.getLogger(__name__).exception("Individual Detectability input discovery failed.")
            self.signals.finished.emit([], f"Could not read the processed results. {exc}")
        else:
            self.signals.finished.emit(conditions, "")


class IndividualDetectabilityWorker(QObject):
    progress = Signal(int)
    status = Signal(str)
    log = Signal(str)
    error = Signal(str)
    finished = Signal(object)

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
            self.finished.emit(str(output_root) if output_root is not None else None)
        except (CanonicalHarmonicSelectionError, ManagedDetectabilityInputError) as exc:
            self.error.emit(str(exc))
        except Exception:
            self.error.emit(traceback.format_exc())
