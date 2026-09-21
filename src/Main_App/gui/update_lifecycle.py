"""App-owned, cancellable updater jobs and asynchronous shutdown coordination.

Updater jobs outlive the window that requested them. Their results become visible only
after the worker thread has stopped, and application quit is deferred while cancellation
finishes. No GUI thread waits on a worker or performs cache/download/verification I/O.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from threading import Event
from typing import cast

from PySide6.QtCore import QEvent, QObject, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtWidgets import QApplication

from Main_App.updates.models import UpdateCancelled, UpdatePhase

ProgressReporter = Callable[[int | UpdatePhase, int | None], None]
UpdateCallback = Callable[[ProgressReporter, Event], object]


@dataclass(frozen=True)
class UpdateTaskResult:
    """Outcome delivered on the GUI thread only after the native thread finishes."""

    value: object = None
    error: Exception | None = None
    cancelled: bool = False


@dataclass
class _WorkerOutcome:
    value: object = None
    error: Exception | None = None


class _UpdateWorker(QObject):
    # Byte counts may exceed Qt's signed 32-bit ``int`` signal arguments.
    progress_changed = Signal(object, object)
    finished = Signal()

    def __init__(
        self,
        callback: UpdateCallback,
        cancel_event: Event,
        outcome: _WorkerOutcome,
    ) -> None:
        super().__init__()
        self._callback = callback
        self._cancel_event = cancel_event
        self._outcome = outcome

    @Slot()
    def run(self) -> None:
        try:
            if self._cancel_event.is_set():
                raise UpdateCancelled("The update operation was canceled.")
            self._outcome.value = self._callback(self._report_progress, self._cancel_event)
        except Exception as error:
            self._outcome.error = error
        finally:
            self.finished.emit()

    def _report_progress(self, downloaded: int | UpdatePhase, total: int | None) -> None:
        if not self._cancel_event.is_set():
            self.progress_changed.emit(downloaded, total)


class UpdateJob(QObject):
    """Own one worker until ``QThread.finished``, even if its dialog disappears."""

    finished = Signal(object)
    progress_changed = Signal(object, object)

    def __init__(
        self,
        callback: UpdateCallback,
        *,
        parent: QObject,
        keep_success_on_cancel: bool = False,
    ) -> None:
        super().__init__(parent)
        self.callback = callback
        self.cancel_event = Event()
        self.keep_success_on_cancel = keep_success_on_cancel
        self.finish_on_shutdown = False
        self._outcome = _WorkerOutcome()
        self._thread: QThread | None = None
        self._worker: _UpdateWorker | None = None
        self._started = False
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def worker_thread(self) -> QThread | None:
        return self._thread

    def start(self) -> None:
        if self._started:
            raise RuntimeError("An updater job can only be started once.")
        self._started = True
        self._running = True
        thread = QThread(self)
        thread.setObjectName("fpvs-toolbox-update-thread")
        worker = _UpdateWorker(self.callback, self.cancel_event, self._outcome)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress_changed.connect(self.progress_changed)
        # quit() is thread-safe. A direct connection lets it run even during shutdown;
        # the result still waits for the subsequent queued QThread.finished delivery.
        worker.finished.connect(thread.quit, Qt.ConnectionType.DirectConnection)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._finish)
        thread.finished.connect(thread.deleteLater)
        self._thread = thread
        self._worker = worker
        thread.start()

    @Slot()
    def cancel(self) -> None:
        self.cancel_event.set()

    @Slot()
    def _finish(self) -> None:
        self._running = False
        self._thread = None
        self._worker = None
        error = self._outcome.error
        cancelled = isinstance(error, UpdateCancelled) or (
            self.cancel_event.is_set()
            and not (self.keep_success_on_cancel and error is None)
        )
        self.finished.emit(
            UpdateTaskResult(value=self._outcome.value, error=error, cancelled=cancelled)
        )


class UpdateLifecycle(QObject):
    """Keep updater jobs alive and make Quit/last-window shutdown cancellation-safe."""

    shutdown_started = Signal()
    manual_check_requested = Signal()
    idle = Signal()

    def __init__(
        self,
        app: QApplication,
        *,
        quit_callback: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(app)
        self.setObjectName("Main_App_update_lifecycle")
        self._app = app
        self._quit_callback = quit_callback or app.quit
        self._jobs: set[UpdateJob] = set()
        self._committed_callbacks: dict[UpdateJob, Callable[[], None]] = {}
        self._restore_quit_on_last_window_closed: bool | None = None
        self._startup_pending = False
        self._shutdown_requested = False
        self._quit_scheduled = False
        self._allow_quit = False
        app.installEventFilter(self)
        app.lastWindowClosed.connect(self._last_window_closed)
        app.aboutToQuit.connect(self._about_to_quit)

    @property
    def has_active_jobs(self) -> bool:
        return bool(self._jobs)

    @property
    def is_shutting_down(self) -> bool:
        return self._shutdown_requested

    def start_task(
        self,
        callback: UpdateCallback,
        *,
        keep_success_on_cancel: bool = False,
        on_committed_success: Callable[[], None] | None = None,
        finish_on_shutdown: bool = False,
    ) -> UpdateJob:
        # Reserved for bounded local persistence, never network/update work.
        if self._shutdown_requested and not finish_on_shutdown:
            raise RuntimeError("FPVS Toolbox is closing; no updater work can be started.")
        self._hold_application_open()
        job = UpdateJob(
            callback,
            parent=self,
            keep_success_on_cancel=keep_success_on_cancel,
        )
        self._jobs.add(job)
        job.finish_on_shutdown = finish_on_shutdown
        if on_committed_success is not None:
            self._committed_callbacks[job] = on_committed_success
        job.finished.connect(self._job_finished)
        # Defer start so callers can attach their GUI slots before a fast job finishes.
        QTimer.singleShot(0, job.start)
        return job

    def begin_startup(self) -> None:
        """Keep first-run root-picker transitions from looking like an app exit."""

        self._startup_pending = True
        self._hold_application_open()

    def finish_startup(self) -> None:
        self._startup_pending = False
        self._restore_auto_quit_if_idle()

    def _hold_application_open(self) -> None:
        if self._restore_quit_on_last_window_closed is None:
            self._restore_quit_on_last_window_closed = self._app.quitOnLastWindowClosed()
            self._app.setQuitOnLastWindowClosed(False)

    def _restore_auto_quit_if_idle(self) -> None:
        if self._jobs or self._startup_pending:
            return
        if self._restore_quit_on_last_window_closed is not None:
            self._app.setQuitOnLastWindowClosed(self._restore_quit_on_last_window_closed)
            self._restore_quit_on_last_window_closed = None

    @Slot()
    def request_shutdown(self) -> None:
        if not self._shutdown_requested:
            self._shutdown_requested = True
            self.shutdown_started.emit()
        for job in tuple(self._jobs):
            if not job.finish_on_shutdown:
                job.cancel()
        if not self._jobs:
            self._schedule_quit()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if watched is self._app and event.type() == QEvent.Type.Quit:
            if self._jobs and not self._allow_quit:
                self.request_shutdown()
                return True
        # QObject's base filter only returns False. Avoid sending unrelated
        # application-wide deliveries back through PySide's typed overload;
        # the item wrapper in the reported exclusions-scroll callback fails it.
        return False

    @Slot(object)
    def _job_finished(self, result: object) -> None:
        job = cast(UpdateJob, self.sender())
        self._jobs.discard(job)
        committed_callback = self._committed_callbacks.pop(job, None)
        job.deleteLater()
        if (
            committed_callback is not None
            and isinstance(result, UpdateTaskResult)
            and result.error is None
            and not result.cancelled
        ):
            # The installer has launched even if its dialog was destroyed during the
            # final worker stage. The application, not that dialog, owns this handoff.
            QTimer.singleShot(0, committed_callback)
        if self._jobs:
            return
        self._restore_auto_quit_if_idle()
        self.idle.emit()
        if self._shutdown_requested:
            self._schedule_quit()

    @Slot()
    def _last_window_closed(self) -> None:
        if (
            self._jobs
            and not self._startup_pending
            and self._restore_quit_on_last_window_closed
        ):
            self.request_shutdown()

    @Slot()
    def _about_to_quit(self) -> None:
        # QApplication.exit() can bypass the Quit event filter. run_gui_app keeps an
        # event loop available in that case until these jobs have really finished.
        self.request_shutdown()

    def _schedule_quit(self) -> None:
        if not self._quit_scheduled:
            self._quit_scheduled = True
            QTimer.singleShot(0, self._finish_shutdown)

    @Slot()
    def _finish_shutdown(self) -> None:
        self._quit_scheduled = False
        if self._jobs:
            return
        self._allow_quit = True
        self._quit_callback()


def update_lifecycle(app: QApplication | None = None) -> UpdateLifecycle:
    """Return the single application-owned coordinator without starting any work."""

    instance = app or QApplication.instance()
    if not isinstance(instance, QApplication):
        raise RuntimeError("Updater jobs require a running QApplication.")
    lifecycle = getattr(instance, "_fpvs_update_lifecycle", None)
    if not isinstance(lifecycle, UpdateLifecycle):
        lifecycle = UpdateLifecycle(instance)
        instance._fpvs_update_lifecycle = lifecycle  # type: ignore[attr-defined]
    return lifecycle
