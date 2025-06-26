"""Mixin that timestamps and routes messages to the GUI and ``logging``.

The mixin writes messages to a Tk ``Text`` widget if present while also
forwarding them through :mod:`logging` for console output. Debug messages
are only shown when the global logging level allows them, which is
controlled via ``debug_utils.configure_logging``.
"""
import logging
import tkinter as tk
import pandas as pd

logger = logging.getLogger(__name__)


class LoggingMixin:
    """Adds a timestamped logging function used across the toolbox."""

    def log(self, message: str, level: int = logging.INFO) -> None:
        """Write ``message`` to the GUI log widget and :mod:`logging`."""
        if tk is None:  # During interpreter shutdown ``tk`` may be ``None``
            return
        ts = pd.Timestamp.now().strftime('%H:%M:%S.%f')[:-3]
        formatted = f"{ts} [GUI]: {message}\n"

        try:
            if hasattr(self, 'log_text') and self.log_text and self.log_text.winfo_exists():
                if level != logging.DEBUG or logger.isEnabledFor(logging.DEBUG):
                    self.log_text.configure(state="normal")
                    self.log_text.insert(tk.END, formatted)
                    self.log_text.see(tk.END)
                    self.log_text.configure(state="disabled")
        except Exception as e:  # pragma: no cover - best effort logging
            logger.exception("Error writing log message to GUI: %s", e)

        logger.log(level, message)

    def debug(self, message: str) -> None:
        if logger.isEnabledFor(logging.DEBUG):
            self.log(f"[DEBUG] {message}", level=logging.DEBUG)
