from __future__ import annotations

import logging
import time
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QObject, QThread, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMessageBox

from Main_App import SettingsManager
from Main_App.PySide6_App.utils.op_guard import OpGuard
from Tools.Ratio_Calculator.PySide6.model import RatioCalcInputs, RatioCalcResult
from Tools.Ratio_Calculator.PySide6.worker import RatioCalcWorker, compute_ratios
from Tools.Stats.PySide6.stats_data_loader import ScanError, scan_folder_simple
from Tools.Stats.roi_resolver import ROI

logger = logging.getLogger(__name__)


class RatioCalculatorController(QObject):
    def __init__(self, view: QObject) -> None:
        super().__init__(view)
        self.view = view
        self._guard = OpGuard()
        self._thread: QThread | None = None
        self._worker: RatioCalcWorker | None = None
        self._rois: list[ROI] = []

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
            rois = self._load_settings_rois()
            self._rois = rois
            if hasattr(self.view, "set_rois"):
                self.view.set_rois(rois)
            if not rois and hasattr(self.view, "append_log"):
                self.view.append_log("No ROIs defined in Settings. Please add ROI pairs in Settings to proceed.")
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to load ROIs: %s", exc)
            if hasattr(self.view, "append_log"):
                self.view.append_log(f"Failed to load ROIs: {exc}")
        if hasattr(self.view, "append_log"):
            self.view.append_log(f"Detected {len(subjects)} participant(s) and {len(conds)} condition(s).")

    def compute_ratios(self, inputs: RatioCalcInputs) -> None:
        if not self._rois:
            if hasattr(self.view, "append_log"):
                self.view.append_log("No ROIs available. Define ROIs in Settings before computing ratios.")
            return
        if not self._guard.start():
            if hasattr(self.view, "append_log"):
                self.view.append_log("Computation already in progress.")
            return
        start = time.perf_counter()
        if hasattr(self.view, "set_busy"):
            self.view.set_busy(True)
        if hasattr(self.view, "set_progress"):
            self.view.set_progress(0)

        worker = RatioCalcWorker(self._prepare_inputs(inputs))
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
        return compute_ratios(self._prepare_inputs(inputs))

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
        if result.output_path.exists():
            self._prompt_open_results(result.output_path)

    def _prepare_inputs(self, inputs: RatioCalcInputs) -> RatioCalcInputs:
        return replace(inputs, rois=self._rois)

    def _load_settings_rois(self) -> list[ROI]:
        mgr = SettingsManager()
        get_roi_pairs = getattr(mgr, "get_roi_pairs", None)
        pairs = get_roi_pairs() if callable(get_roi_pairs) else []
        if isinstance(pairs, dict):
            pairs = list(pairs.items())
        rois: list[ROI] = []
        for name, electrodes in pairs:
            if not name or not electrodes:
                continue
            channels = [str(ch).upper() for ch in electrodes if str(ch).strip()]
            if channels:
                rois.append(ROI(name=str(name), channels=channels))
        return rois

    def _prompt_open_results(self, output_path: Path) -> None:
        parent = self.view if isinstance(self.view, QObject) else None
        reply = QMessageBox.question(
            parent,
            "Ratio Calculator",
            "Ratio calculations complete. View results?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply == QMessageBox.Yes:
            folder = output_path.parent
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
