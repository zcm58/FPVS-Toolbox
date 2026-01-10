from __future__ import annotations

"""Qt bridge that launches process-based preprocessing and relays progress."""

import logging
from multiprocessing import Event, Queue, get_context
from pathlib import Path
from threading import Thread
from typing import Dict, List, Optional
from queue import Empty  # <-- important: handle queue.Empty separately

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from Main_App.Performance.mp_env import set_blas_threads_single_process
from Main_App.Performance.process_runner import RunParams, run_project_parallel

logger = logging.getLogger(__name__)


class MpRunnerBridge(QObject):
    """Bridge between the Qt GUI and the multiprocessing-based project runner."""

    progress = Signal(int)
    error = Signal(str)
    finished = Signal(dict)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._poll)

        self._q: Optional[Queue] = None
        self._total: int = 0
        self._running: bool = False
        self._results: List[Dict[str, object]] = []
        self._cancel_event: Optional[Event] = None
        self._worker_thread: Optional[Thread] = None

    def start(
        self,
        project_root: Path,
        data_files: List[Path],
        settings: Dict[str, object],
        event_map: Dict[str, int],
        save_folder: Path,
        max_workers: Optional[int],
    ) -> None:
        """
        Launch the multiprocessing project run in a background thread and begin polling
        the inter-process queue for progress / completion messages.
        """
        if self._running:
            logger.warning(
                "MpRunnerBridge.start called while a run is already active; "
                "ignoring request. project_root=%s save_folder=%s",
                project_root,
                save_folder,
            )
            return

        if not data_files:
            logger.info(
                "MpRunnerBridge.start called with no data_files; emitting finished immediately. "
                "project_root=%s save_folder=%s",
                project_root,
                save_folder,
            )
            self._total = 0
            self._results = []
            self.finished.emit({"files": 0, "results": [], "cancelled": False})
            return

        self._running = True
        self._cancel_event = Event()
        self._q = get_context("spawn").Queue()
        self._total = len(data_files)
        self._results = []

        params = RunParams(
            project_root=project_root,
            data_files=data_files,
            settings=settings,
            event_map=event_map,
            save_folder=save_folder,
            max_workers=max_workers,
        )

        for file_path in data_files:
            logger.info(
                "BRIDGE_SETTINGS_SNAPSHOT n_files=%d high_pass=%r low_pass=%r "
                "downsample_rate=%r reject_thresh=%r ref=(%r,%r) stim=%r",
                len(data_files),
                settings.get("high_pass"),
                settings.get("low_pass"),
                settings.get("downsample_rate", settings.get("downsample")),
                settings.get("reject_thresh"),
                settings.get("ref_channel1"),
                settings.get("ref_channel2"),
                settings.get("stim_channel"),
                extra={
                    "source": "mp_runner_bridge",
                    "file": file_path.name,
                    "high_pass": settings.get("high_pass"),
                    "low_pass": settings.get("low_pass"),
                    "downsample_rate": settings.get("downsample_rate"),
                    "downsample": settings.get("downsample"),
                    "reject_thresh": settings.get("reject_thresh"),
                    "ref_channel1": settings.get("ref_channel1"),
                    "ref_channel2": settings.get("ref_channel2"),
                    "stim_channel": settings.get("stim_channel"),
                },
            )

        logger.info(
            "MpRunnerBridge starting run_project_parallel: project_root=%s "
            "save_folder=%s n_files=%d max_workers=%s",
            project_root,
            save_folder,
            self._total,
            max_workers,
        )

        set_blas_threads_single_process()

        self._worker_thread = Thread(
            target=run_project_parallel,
            args=(params, self._q, self._cancel_event),
            daemon=True,
        )
        self._worker_thread.start()

        self._timer.start()

    @Slot()
    def cancel(self) -> None:
        """
        Request cooperative cancellation of the current run.
        This sets an Event that run_project_parallel checks periodically.
        """
        if not self._running:
            logger.debug("MpRunnerBridge.cancel called but no run is active.")
            return

        if self._cancel_event is not None:
            logger.info("MpRunnerBridge cancellation requested for current run.")
            self._cancel_event.set()
        else:
            logger.warning(
                "MpRunnerBridge.cancel called but _cancel_event is None while _running is True."
            )

    @Slot()
    def _poll(self) -> None:
        """
        Periodically poll the multiprocessing queue for progress and completion messages.
        Emits Qt signals for progress, error, and finished.
        """
        if self._q is None:
            # Run is either not started yet or has already been torn down.
            logger.debug(
                "MpRunnerBridge._poll called with no active queue; stopping timer."
            )
            self._timer.stop()
            return

        try:
            while True:
                try:
                    msg = self._q.get_nowait()
                except Empty:
                    # No more messages available on this tick; let QTimer call us again later.
                    break

                if not isinstance(msg, dict):
                    logger.warning(
                        "MpRunnerBridge received non-dict message from worker queue: %r",
                        msg,
                    )
                    continue

                mtype = msg.get("type")
                if mtype == "progress":
                    done = int(msg.get("completed", 0))
                    pct = int(100 * done / max(1, self._total))
                    logger.debug(
                        "MpRunnerBridge progress update: completed=%d total=%d pct=%d",
                        done,
                        self._total,
                        pct,
                    )
                    self.progress.emit(pct)

                    result = msg.get("result")
                    if isinstance(result, dict):
                        status = result.get("status")
                        if status == "error":
                            raw_error = str(result.get("error") or "Unknown error")
                            stage = str(result.get("stage") or "unknown")
                            file_str = str(result.get("file") or "unknown")
                            try:
                                file_name = Path(file_str).name
                            except Exception:
                                file_name = file_str

                            logger.error(
                                "MpRunnerBridge file error: file=%s stage=%s error=%s",
                                file_name,
                                stage,
                                raw_error,
                            )

                            message = f"{file_name} [{stage}]: {raw_error}"
                            self.error.emit(message)
                        elif status == "ok":
                            self._results.append(result)
                            logger.debug(
                                "MpRunnerBridge recorded successful result for file=%r "
                                "(total_results=%d)",
                                result.get("file"),
                                len(self._results),
                            )
                        else:
                            logger.debug(
                                "MpRunnerBridge received progress result with unknown "
                                "status=%r for file=%r",
                                status,
                                result.get("file"),
                            )

                elif mtype == "done":
                    cancelled = bool(msg.get("cancelled", False))
                    logger.info(
                        "MpRunnerBridge run complete: files=%d successful=%d cancelled=%s",
                        self._total,
                        len(self._results),
                        cancelled,
                    )

                    payload: Dict[str, object] = {
                        "files": self._total,
                        "results": list(self._results),
                        "cancelled": cancelled,
                    }

                    self._timer.stop()
                    self._running = False
                    self._cancel_event = None
                    self._worker_thread = None
                    self._q = None

                    self.finished.emit(payload)
                    break

                else:
                    logger.warning(
                        "MpRunnerBridge received unknown message type from worker: "
                        "type=%r msg=%r",
                        mtype,
                        msg,
                    )

        except Exception as exc:
            logger.exception(
                "MpRunnerBridge._poll encountered an unexpected error while reading "
                "from the worker queue."
            )
            self.error.emit(f"Internal error while polling worker queue: {exc!r}")
