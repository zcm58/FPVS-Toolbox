"""Qt workers for project inspection, preparation, and permutation inference."""

from __future__ import annotations

from pathlib import Path
from threading import Event

import logging

from PySide6.QtCore import QObject, Signal, Slot

from .backend_adapter import FreeHarmonicBackend
from .models import AnalysisSetup, ProjectAnalysisOptions, ProjectFrequencySnapshot


logger = logging.getLogger(__name__)


class _CancellableWorker(QObject):
    """Signal shell shared by the three sequential background operations."""

    progress = Signal(int, int, str)
    completed = Signal(object)
    failed = Signal(str)
    cancelled = Signal()
    finished = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._cancel_event = Event()

    @Slot()
    def cancel(self) -> None:
        self._cancel_event.set()

    def _should_cancel(self) -> bool:
        return self._cancel_event.is_set()

    def _emit_progress(self, completed: int, total: int, message: str) -> None:
        self.progress.emit(int(completed), int(total), str(message))

    def _execute(self) -> object:
        raise NotImplementedError

    @Slot()
    def run(self) -> None:
        try:
            result = self._execute()
        except Exception as exc:
            if self._should_cancel() or exc.__class__.__name__ in {
                "FreeHarmonicCancelledError",
                "AnalysisCancelled",
            }:
                self.cancelled.emit()
            else:
                logger.exception(
                    "free_harmonic_gui_worker_failed",
                    extra={"worker": type(self).__name__},
                )
                self.failed.emit(str(exc))
        else:
            # A returned operation is complete. In particular, cancellation
            # can arrive while the final atomic export is already publishing;
            # do not hide a successfully returned receipt as "cancelled".
            self.completed.emit(result)
        finally:
            self.finished.emit()


class ProjectInspectionWorker(_CancellableWorker):
    """Discover canonical choices and header-derived harmonics without writes."""

    def __init__(
        self,
        backend: FreeHarmonicBackend,
        project_root: Path,
        frequencies: ProjectFrequencySnapshot,
    ) -> None:
        super().__init__()
        self._backend = backend
        self._project_root = Path(project_root)
        self._frequencies = frequencies

    def _execute(self) -> object:
        return self._backend.inspect_project(
            self._project_root,
            self._frequencies,
            progress=self._emit_progress,
            cancel_check=self._should_cancel,
        )


class PreparationWorker(_CancellableWorker):
    """Read workbooks once and retain the prepared participant tensors."""

    def __init__(
        self,
        backend: FreeHarmonicBackend,
        project_root: Path,
        frequencies: ProjectFrequencySnapshot,
        options: ProjectAnalysisOptions,
        setup: AnalysisSetup,
    ) -> None:
        super().__init__()
        self._backend = backend
        self._project_root = Path(project_root)
        self._frequencies = frequencies
        self._options = options
        self._setup = setup

    def _execute(self) -> object:
        return self._backend.prepare(
            self._project_root,
            self._frequencies,
            self._options,
            self._setup,
            progress=self._emit_progress,
            cancel_check=self._should_cancel,
        )


class PermutationWorker(_CancellableWorker):
    """Analyze one exact prepared object and publish only on success."""

    def __init__(self, backend: FreeHarmonicBackend, prepared: object) -> None:
        super().__init__()
        self._backend = backend
        self._prepared = prepared

    def _execute(self) -> object:
        return self._backend.run(
            self._prepared,
            progress=self._emit_progress,
            cancel_check=self._should_cancel,
        )


__all__ = [
    "PermutationWorker",
    "PreparationWorker",
    "ProjectInspectionWorker",
]
