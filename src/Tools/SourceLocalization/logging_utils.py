from __future__ import annotations

import logging
from multiprocessing import Queue

PKG_LOG_NAME = "Tools.SourceLocalization"


class QueueLogHandler(logging.Handler):
    """Forward log messages to a ``multiprocessing.Queue``."""

    def __init__(self, queue: Queue, level: int = logging.INFO) -> None:
        super().__init__(level=level)
        self.queue = queue
        self.setFormatter(logging.Formatter("%(message)s"))

    def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover
        try:
            msg = self.format(record)
            self.queue.put({"type": "log", "message": msg})
        except Exception:
            # Use standard handler error path instead of silently swallowing.
            self.handleError(record)


def get_pkg_logger() -> logging.Logger:
    """Return the package logger without altering the root logger."""
    return logging.getLogger(PKG_LOG_NAME)


__all__ = ["QueueLogHandler", "get_pkg_logger", "PKG_LOG_NAME"]
