from __future__ import annotations

import logging
import time
from pathlib import Path

from PySide6.QtCore import QObject, QThread

from Main_App.PySide6_App.utils.op_guard import OpGuard
from Tools.Ratio_Calculator.PySide6.model import RatioCalcInputs, RatioCalcResult
from Tools.Ratio_Calculator.PySide6.worker import RatioCalcWorker, compute_ratios
from Tools.Stats.PySide6.stats_data_loader import ScanError, scan_folder_simple
from Tools.Stats.roi_resolver import resolve_active_rois

logger = logging.getLogger(__name__)


class RatioCalculatorController(QObject):
    def __init__(self, view: QObject) -> None:
        super().__init__(view)
        self.view = view
        self._guard = OpGuard()
        self._thread: QThread | None = None
        self._worker: RatioCalcWorker | None = None

    def set_excel_root(self, path: Path) -> None:
        try:
            subjects, conditions, _ = scan_folder_simple(str(path))
        except ScanError as exc:
            msg = f"Failed to scan Excel root: {exc}"
            logger.error(msg)
            if hasattr(self.view, "append_log"):
                self.view.append_log(msg)
            return

        conds = [c for c in conditions if c.lower() != "all conditions"]
        if hasattr(self.view, "set_conditions"):
            self.view.set_conditions(conds)
        try:
            rois = resolve_active_rois()
            roi_names = ["All ROIs", *[r.name for r in rois]]
            if hasattr(self.view, "set_rois"):
                self.view.set_rois(roi_names)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to load ROIs: %s", exc)
            if hasattr(self.view, "append_log"):
                self.view.append_log(f"Failed to load ROIs: {exc}")
        if hasattr(self.view, "append_log"):
            self.view.append_log(
                f"Detected {len(subjects)} participant(s) and {len(conds)} condition(s)."
            )

    def compute_ratios(self, inputs: RatioCalcInputs) -> None:
        if not self._guard.start():
            if hasattr(self.view, "append_log"):
                self.view.append_log("Computation already in progress.")
            return
        start = time.perf_counter()
        if hasattr(self.view, "set_busy"):
            self.view.set_busy(True)
        if hasattr(self.view, "set_progress"):
            self.view.set_progress(0)

        worker = RatioCalcWorker(inputs)
        thread = QThread()
        worker.moveToThread(thread)
        worker.progress.connect(getattr(self.view, "set_progress"))
        worker.error.connect(getattr(self.view, "append_log"))
        worker.finished.connect(self._on_finished)
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: self._on_thread_done(start))

        self._thread = thread
        self._worker = worker
        thread.start()

    def compute_ratios_sync(self, inputs: RatioCalcInputs) -> RatioCalcResult:
        return compute_ratios(inputs)

    def _on_thread_done(self, started_at: float) -> None:
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        if hasattr(self.view, "append_log"):
            self.view.append_log(f"Finished in {elapsed_ms:.1f} ms")
        if hasattr(self.view, "set_busy"):
            self.view.set_busy(False)
        self._guard.end()

    def _on_finished(self, result: RatioCalcResult) -> None:
        for warning in result.warnings:
            if hasattr(self.view, "status_message"):
                self.view.status_message(warning)
        if hasattr(self.view, "handle_result"):
            self.view.handle_result(result)
