"""Qt workers for project inspection and one-shot clustering analysis."""

from __future__ import annotations

from pathlib import Path
from threading import Event
from time import perf_counter

import logging

from PySide6.QtCore import QObject, Signal, Slot

from Main_App.processing.full_fft_provenance import (
    FullFftProvenanceMissingError,
    FullFftProvenanceStaleError,
)

from .backend_adapter import FreeHarmonicBackend
from .models import (
    AnalysisSetup,
    AnalysisWorkerOutcome,
    ProjectAnalysisOptions,
    ProjectFrequencySnapshot,
    RepeatedBatchSetup,
    RepeatedBatchWorkerOutcome,
)


logger = logging.getLogger(__name__)


def _requires_post_processing(error: BaseException) -> bool:
    """Return whether an error was caused by stale/missing FullFFT provenance."""

    current: BaseException | None = error
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        if isinstance(
            current,
            (FullFftProvenanceMissingError, FullFftProvenanceStaleError),
        ):
            return True
        current = current.__cause__ or current.__context__
    return False


class _CancellableWorker(QObject):
    """Signal shell shared by background operations."""

    progress = Signal(int, int, str)
    completed = Signal(object)
    failed = Signal(str)
    post_processing_required = Signal(str)
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
        started_at = perf_counter()
        worker_type = type(self).__name__
        outcome = "failed"
        logger.info(
            "free_harmonic_gui_worker_started",
            extra={"worker": worker_type},
        )
        try:
            result = self._execute()
        except Exception as exc:
            if self._should_cancel() or exc.__class__.__name__ in {
                "FreeHarmonicCancelledError",
                "AnalysisCancelled",
            }:
                outcome = "cancelled"
                self.cancelled.emit()
            elif _requires_post_processing(exc):
                outcome = "post_processing_required"
                logger.warning(
                    "free_harmonic_gui_post_processing_required",
                    exc_info=True,
                    extra={"worker": worker_type},
                )
                self.post_processing_required.emit(str(exc))
            else:
                logger.exception(
                    "free_harmonic_gui_worker_failed",
                    extra={"worker": worker_type},
                )
                self.failed.emit(str(exc))
        else:
            # A returned operation is complete. In particular, cancellation
            # can arrive while the final atomic export is already publishing;
            # do not hide a successfully returned receipt as "cancelled".
            outcome = "completed"
            self.completed.emit(result)
        finally:
            logger.info(
                "free_harmonic_gui_worker_finalized",
                extra={
                    "worker": worker_type,
                    "outcome": outcome,
                    "elapsed_ms": round((perf_counter() - started_at) * 1000.0, 3),
                },
            )
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


class AnalysisWorker(_CancellableWorker):
    """Prepare, analyze, and export one contrast on a single worker thread."""

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
        self._emit_progress(
            0,
            0,
            "Preparing participant x electrode x harmonic data...",
        )
        prepared = self._backend.prepare(
            self._project_root,
            self._frequencies,
            self._options,
            self._setup,
            progress=self._emit_progress,
            cancel_check=self._should_cancel,
        )
        if self._should_cancel():
            raise RuntimeError("Operation cancelled after preparation.")
        self._emit_progress(
            1,
            1,
            "Preparation complete. Starting cluster permutations...",
        )
        self._emit_progress(
            0,
            0,
            "Running whole-participant cluster permutations...",
        )
        run_outcome = self._backend.run(
            prepared,
            progress=self._emit_progress,
            cancel_check=self._should_cancel,
        )
        # Do not re-check cancellation after ``run`` returns. A returned run
        # has committed its additive export and must remain visible as success.
        return AnalysisWorkerOutcome(
            prepared=prepared,
            run_outcome=run_outcome,
        )


class RepeatedSessionBatchWorker(_CancellableWorker):
    """Prepare, analyze, correct, and export the full repeated-session batch."""

    def __init__(
        self,
        backend: FreeHarmonicBackend,
        project_root: Path,
        frequencies: ProjectFrequencySnapshot,
        options: ProjectAnalysisOptions,
        setup: RepeatedBatchSetup,
    ) -> None:
        super().__init__()
        self._backend = backend
        self._project_root = Path(project_root)
        self._frequencies = frequencies
        self._options = options
        self._setup = setup

    def _execute(self) -> object:
        self._emit_progress(
            0,
            0,
            "Preparing the shared repeated-session harmonic domain and cohorts...",
        )
        run = self._backend.run_repeated_batch(
            self._project_root,
            self._frequencies,
            self._options,
            self._setup,
            progress=self._emit_progress,
            cancel_check=self._should_cancel,
        )
        # A returned batch has already published its additive result bundle.
        return RepeatedBatchWorkerOutcome(run=run)


__all__ = [
    "AnalysisWorker",
    "ProjectInspectionWorker",
    "RepeatedSessionBatchWorker",
]
