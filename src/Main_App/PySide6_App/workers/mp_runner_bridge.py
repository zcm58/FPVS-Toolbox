from __future__ import annotations

"""Qt bridge that launches process-based preprocessing and relays progress."""

from multiprocessing import Event, Queue, get_context
from pathlib import Path
from typing import Dict, List, Optional
from threading import Thread
from PySide6.QtCore import QObject, QTimer, Signal, Slot

from Main_App.Performance.mp_env import set_blas_threads_single_process
from Main_App.Performance.process_runner import RunParams, run_project_parallel


class MpRunnerBridge(QObject):
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
        if self._running:
            return

        if not data_files:
            self._total = 0
            self._results = []
            self.finished.emit({"files": 0, "results": [], "cancelled": False})
            return

        self._running = True
        self._cancel_event = Event()
        self._q = get_context("spawn").Queue()
        params = RunParams(
            project_root=project_root,
            data_files=data_files,
            settings=settings,
            event_map=event_map,
            save_folder=save_folder,
            max_workers=max_workers,
        )

        set_blas_threads_single_process()

        self._worker_thread = Thread(
            target=run_project_parallel,
            args=(params, self._q, self._cancel_event),
            daemon=True,
        )
        self._worker_thread.start()

        self._total = len(data_files)
        self._results = []
        self._timer.start()

    def cancel(self) -> None:
        """Cooperatively request cancellation of the current run."""
        if not self._running:
            return
        if self._cancel_event is not None:
            self._cancel_event.set()

    @Slot()
    def cancel(self) -> None:
        """
        Request cooperative cancellation of the current run.
        This sets an Event that run_project_parallel checks periodically.
        """
        if not self._running:
            return
        if self._cancel_event is not None:
            self._cancel_event.set()

    @Slot()
    def _poll(self) -> None:
        if not self._q:
            return
        try:
            while True:
                msg = self._q.get_nowait()
                mtype = msg.get("type")
                if mtype == "progress":
                    done = msg.get("completed", 0)
                    pct = int(100 * done / max(1, self._total))
                    self.progress.emit(pct)

                    result = msg.get("result", {})
                    if result.get("status") == "error":
                        # Compose a richer error message that includes file and stage,
                        # while remaining backward-compatible with older payloads.
                        raw_error = str(result.get("error") or "Unknown error")
                        stage = str(result.get("stage") or "unknown")
                        file_str = str(result.get("file") or "unknown")
                        try:
                            file_name = Path(file_str).name
                        except Exception:
                            file_name = file_str
                        message = f"{file_name} [{stage}]: {raw_error}"
                        self.error.emit(message)
                    elif result.get("status") == "ok":
                        self._results.append(result)

                elif mtype == "done":
                    self._timer.stop()
                    cancelled = bool(msg.get("cancelled", False))

                    payload: Dict[str, object] = {
                        "files": self._total,
                        "results": list(self._results),
                        "cancelled": cancelled,
                    }

                    self._running = False
                    self._cancel_event = None
                    self._worker_thread = None
                    self._q = None

                    self.finished.emit(payload)
                    break
        except Exception:
            # Any queue/poll issues are non-fatal to the GUI; ignore.
            pass

