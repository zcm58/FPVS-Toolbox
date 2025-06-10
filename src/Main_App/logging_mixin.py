"""Mixin that timestamps and routes messages to the on-screen log
and the console. It also exposes a tiny debug wrapper that respects
the application's settings."""
import tkinter as tk
import pandas as pd


class LoggingMixin:
    """Adds a timestamped logging function used across the toolbox."""

    def log(self, message: str) -> None:
        ts = pd.Timestamp.now().strftime('%H:%M:%S.%f')[:-3]
        formatted = f"{ts} [GUI]: {message}\n"
        try:
            if hasattr(self, 'log_text') and self.log_text and self.log_text.winfo_exists():
                self.log_text.configure(state="normal")
                self.log_text.insert(tk.END, formatted)
                self.log_text.see(tk.END)
                self.log_text.configure(state="disabled")
        except Exception as e:  # pragma: no cover - best effort logging
            print(f"[Log Error] {e}. Message: {message}")
        print(formatted, end="")

    def debug(self, message: str) -> None:
        if hasattr(self, 'settings') and getattr(self, 'settings').debug_enabled():
            self.log(f"[DEBUG] {message}")
