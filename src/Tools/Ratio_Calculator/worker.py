from __future__ import annotations

import traceback
from typing import Iterable

from PySide6.QtCore import QObject, Signal

from .constants import RatioCalculatorSettings
from .pipeline import run_ratio_calculator


class RatioCalculatorWorker(QObject):
    progress = Signal(int)
    status = Signal(str)
    error = Signal(str)
    finished = Signal(str, str)
    log = Signal(str)

    def __init__(
        self,
        input_dir_a: str,
        condition_label_a: str,
        input_dir_b: str,
        condition_label_b: str,
        output_dir: str,
        run_label: str,
        manual_exclude: Iterable[str],
        settings: RatioCalculatorSettings,
        roi_defs: dict[str, list[str]],
    ) -> None:
        super().__init__()
        self._input_dir_a = input_dir_a
        self._condition_label_a = condition_label_a
        self._input_dir_b = input_dir_b
        self._condition_label_b = condition_label_b
        self._output_dir = output_dir
        self._run_label = run_label
        self._manual_exclude = list(manual_exclude)
        self._settings = settings
        self._roi_defs = roi_defs

    def _log(self, message: str) -> None:
        self.log.emit(message)
        self.status.emit(message)

    def run(self) -> None:
        try:
            self.progress.emit(0)
            self.status.emit("Starting ratio calculations...")
            self.progress.emit(5)
            result = run_ratio_calculator(
                input_dir_a=self._input_dir_a,
                condition_label_a=self._condition_label_a,
                input_dir_b=self._input_dir_b,
                condition_label_b=self._condition_label_b,
                output_dir=self._output_dir,
                run_label=self._run_label,
                manual_exclude=self._manual_exclude,
                settings=self._settings,
                roi_defs=self._roi_defs,
                log=self._log,
            )
            self.progress.emit(100)
            self.status.emit("Ratio calculations complete.")
            self.finished.emit(str(result.output_dir), str(result.excel_path))
        except Exception:
            self.error.emit(traceback.format_exc())
