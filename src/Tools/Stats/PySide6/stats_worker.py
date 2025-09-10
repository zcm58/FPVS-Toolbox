from __future__ import annotations

import logging
import time
from PySide6.QtCore import QObject, Signal, Slot, QRunnable, QThreadPool
from PySide6.QtWidgets import QWidget, QPushButton, QLabel, QProgressBar
from PySide6.QtGui import QAction

_qt_refs = (QWidget, QPushButton, QLabel, QProgressBar, QAction, QThreadPool)

logger = logging.getLogger("Tools.Stats")


class StatsWorker(QRunnable):
    class Signals(QObject):
        progress = Signal(int)
        message = Signal(str)
        error = Signal(str)
        finished = Signal(dict)

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.signals = self.Signals()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs

    @Slot()
    def run(self) -> None:
        t0 = time.perf_counter()
        try:
            result = self._fn(
                self.signals.progress.emit, self.signals.message.emit, *self._args, **self._kwargs
            )
            payload = result if isinstance(result, dict) else {"result": result}
            self.signals.finished.emit(payload)
        except Exception as exc:  # noqa: BLE001
            logger.exception("stats_run_failed")
            self.signals.error.emit(str(exc))
        finally:
            dt = (time.perf_counter() - t0) * 1000
            logger.info("stats_run_done", extra={"elapsed_ms": dt})
