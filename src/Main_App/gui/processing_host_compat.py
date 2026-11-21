"""Compatibility hooks for callers of the older processing host interface."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from functools import cached_property
from types import SimpleNamespace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QLineEdit


class QtEntryAdapter:
    """Expose the historical entry interface for a visible edit or a saved value."""

    def __init__(self, line_edit: QLineEdit | str) -> None:
        self._source = line_edit

    @property
    def _edit(self) -> QLineEdit:
        if isinstance(self._source, str):
            from PySide6.QtWidgets import QLineEdit

            self._source = QLineEdit(self._source)
        return self._source

    def get(self) -> str:
        return self._edit.text()

    def focus_set(self) -> None:
        self._edit.setFocus()


class ProcessingHostCompatibility:
    """Provide historical shell hooks on demand using the Qt event loop."""

    _queue_job_id: int | None = None

    @cached_property
    def save_fif_var(self) -> SimpleNamespace:
        return SimpleNamespace(get=lambda: False)

    @cached_property
    def file_type(self) -> SimpleNamespace:
        return SimpleNamespace(set=lambda v: None)

    @cached_property
    def _after_timers(self) -> dict[int, QTimer]:
        return {}

    def after(self, delay_ms: int, callback: Callable[[], None]) -> int:
        """Schedule a one-shot callback and return its cancellation handle."""
        from PySide6.QtCore import QTimer

        timer = QTimer(self)
        timer.setSingleShot(True)
        job_id = id(timer)

        def run_and_cleanup() -> None:
            try:
                callback()
            finally:
                self._after_timers.pop(job_id, None)
                timer.deleteLater()

        timer.timeout.connect(run_and_cleanup)
        self._after_timers[job_id] = timer
        timer.start(int(delay_ms))
        return job_id

    def after_cancel(self, job_id: int) -> None:
        """Cancel a callback previously scheduled on this host."""
        timer = self._after_timers.pop(job_id, None)
        if timer:
            timer.stop()
            timer.deleteLater()


def reset_compatibility_host_data(host) -> None:
    """Reset host data between the optional time and ready-text updates."""
    if hasattr(host, "remaining_time_var") and host.remaining_time_var is not None:
        host.remaining_time_var.set("")
    host.preprocessed_data = {}

    log_text = getattr(host, "log_text", None)
    winfo_exists = getattr(log_text, "winfo_exists", None)
    if callable(winfo_exists) and winfo_exists():
        log_text.configure(state="normal")
        ready_msg = (
            f"{datetime.now().strftime('%H:%M:%S.%f')[:-3]} [GUI]: "
            "Ready for next file selection...\n"
        )
        log_text.insert("end", ready_msg)
        log_text.see("end")
        log_text.configure(state="disabled")
