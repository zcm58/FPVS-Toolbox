"""Qt lifecycle wrapper for temporary preprocessing-QC source preloading."""

from __future__ import annotations

import logging
from threading import Event
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal, Slot

if TYPE_CHECKING:
    from Main_App.processing.qc_source_prefetch import QcSourcePrefetch

logger = logging.getLogger(__name__)


class QcSourcePrefetchWorker(QObject):
    """Keep prefetched recordings alive through review and clean up off-thread."""

    finished = Signal()

    def __init__(self, prefetch: QcSourcePrefetch) -> None:
        super().__init__()
        self._prefetch = prefetch
        self._finish_requested = Event()

    def request_finish(self) -> None:
        """Request cancellation directly from the GUI without waiting for I/O.

        This is deliberately a thread-safe direct call: ``run`` occupies the
        worker thread until release, so a queued Qt slot cannot deliver it.
        """
        try:
            self._prefetch.cancel()
        except Exception:  # noqa: BLE001 - cleanup must still release the thread
            logger.exception("qc_source_prefetch_cancel_failed")
        finally:
            self._finish_requested.set()

    @Slot()
    def run(self) -> None:
        try:
            try:
                if not self._finish_requested.is_set():
                    self._prefetch.run()
            except Exception:  # noqa: BLE001 - normal loading remains the fallback
                logger.exception("qc_source_prefetch_background_failed")
            # Loading may finish long before review. Keep cached sources until
            # the GUI has finished the consumer scan or cancelled the workflow.
            try:
                while not self._finish_requested.wait(timeout=0.1):
                    self._prefetch.maintain()
            except Exception:  # noqa: BLE001 - final cleanup still waits for the consumer to finish.
                logger.exception("qc_source_prefetch_maintenance_failed")
                self._finish_requested.wait()
        finally:
            try:
                self._prefetch.close()
            except Exception:  # noqa: BLE001 - never strand the owning QThread
                logger.exception("qc_source_prefetch_cleanup_failed")
            finally:
                self.finished.emit()


__all__ = ["QcSourcePrefetchWorker"]
