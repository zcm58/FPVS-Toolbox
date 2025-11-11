from __future__ import annotations

"""Qt bridge that launches process-based preprocessing and relays progress."""

from multiprocessing import Queue, get_context
from pathlib import Path
from typing import Dict, List, Optional

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
        self._running = False
        self._results: List[Dict[str, object]] = []

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
        self._running = True
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
        from threading import Thread

        Thread(target=run_project_parallel, args=(params, self._q), daemon=True).start()
        self._total = len(data_files)
        self._results = []
        self._timer.start()

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
                        self.error.emit(str(result.get("error")))
                    elif result.get("status") == "ok":
                        self._results.append(result)
                elif mtype == "done":
                    self._timer.stop()
                    self._running = False
                    self.finished.emit({"files": self._total, "results": list(self._results)})
                    break
        except Exception:
            pass

