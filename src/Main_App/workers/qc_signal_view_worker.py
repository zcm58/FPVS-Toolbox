"""Read-only bounded signal inspection outside the GUI thread."""

from __future__ import annotations

import logging
from threading import Event

from PySide6.QtCore import QObject, Signal, Slot

from Main_App.processing.qc_signal_view import QcSignalViewRequest, load_qc_signal_view

logger = logging.getLogger(__name__)


class QcSignalViewWorker(QObject):
    result = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, request: QcSignalViewRequest) -> None:
        super().__init__()
        self._request = request
        self._cancel = Event()

    def cancel(self) -> None:
        self._cancel.set()

    @Slot()
    def run(self) -> None:
        try:
            result = load_qc_signal_view(self._request, should_cancel=self._cancel.is_set)
            if not self._cancel.is_set():
                self.result.emit(result)
        except InterruptedError:
            pass
        except Exception as exc:  # noqa: BLE001 - diagnostic I/O never strands a thread
            if not self._cancel.is_set():
                logger.exception("qc_signal_view_failed")
                self.failed.emit(str(exc))
        finally:
            self.finished.emit()


__all__ = ["QcSignalViewWorker"]
