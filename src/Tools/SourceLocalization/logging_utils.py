"""Logging helpers for the source localization module."""

from __future__ import annotations

import logging
from multiprocessing import Queue


class QueueLogHandler(logging.Handler):
    """Forward log messages to a ``multiprocessing.Queue``."""

    def __init__(self, queue: Queue, level: int = logging.INFO) -> None:
        super().__init__(level=level)
        self.queue = queue
        self.setFormatter(logging.Formatter("%(message)s"))

    def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover - best effort
        try:
            msg = self.format(record)
            self.queue.put({"type": "log", "message": msg})
        except Exception:
            pass

__all__ = ["QueueLogHandler"]
