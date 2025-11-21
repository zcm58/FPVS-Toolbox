# src/Tools/Stats/PySide6/stats_worker.py
from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict
from PySide6.QtCore import QObject, Signal, Slot, QRunnable

logger = logging.getLogger("Tools.Stats")


class StatsWorker(QRunnable):
    """
    QRunnable that executes a callable with (progress_emit, message_emit, *args, **kwargs)
    and emits results via signals. Drop-in compatible with the previous version.
    """

    class Signals(QObject):
        progress = Signal(int)
        message = Signal(str)
        error = Signal(str)
        finished = Signal(dict)

    def __init__(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self.setAutoDelete(True)  # avoid lingering runnables
        self.signals = self.Signals()
        self._fn: Callable[..., Any] = fn
        self._args = args
        # Optional op name for structured logs; removed from kwargs before calling fn
        self._op: str = kwargs.pop("_op", getattr(fn, "__name__", "stats_op"))
        self._kwargs = kwargs

    @Slot()
    def run(self) -> None:
        t0 = time.perf_counter()
        logger.info("stats_run_start", extra={"op": self._op})
        progress_emit = self.signals.progress.emit
        message_emit = self.signals.message.emit
        try:
            result = self._fn(progress_emit, message_emit, *self._args, **self._kwargs)
            payload: Dict[str, Any] = result if isinstance(result, dict) else {"result": result}
            try:
                self.signals.finished.emit(payload)
            except Exception as emit_exc:  # noqa: BLE001
                logger.exception(
                    "stats_run_emit_failed",
                    extra={"op": self._op, "exc_type": type(emit_exc).__name__},
                )
                self.signals.error.emit(str(emit_exc))
        except Exception as exc:  # noqa: BLE001
            logger.exception("stats_run_failed", extra={"op": self._op, "exc_type": type(exc).__name__})
            self.signals.error.emit(str(exc))
        finally:
            dt_ms = (time.perf_counter() - t0) * 1000.0
            logger.info("stats_run_done", extra={"op": self._op, "elapsed_ms": dt_ms})
