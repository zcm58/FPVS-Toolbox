from __future__ import annotations

import logging
from typing import Any, Dict, List
from types import SimpleNamespace

from PySide6.QtCore import QObject, Signal

from Main_App.PySide6_App.adapters.post_export_adapter import LegacyCtx, run_post_export


class PostProcessWorker(QObject):
    """Run legacy post processing off the GUI thread."""

    progress = Signal(int)
    error = Signal(str)
    finished = Signal(dict)

    def __init__(self, file_name: str, epochs_dict: Dict[str, Any], labels: List[str]) -> None:
        super().__init__()
        self._file_name = file_name
        self._epochs_dict = epochs_dict
        self._labels = labels
        self._cancelled = False
        self.output_folder: str = ""
        self.data_paths: List[str] = []
        self._logs: List[str] = []

    def stop(self) -> None:
        self._cancelled = True

    def _log(self, message: str) -> None:
        self._logs.append(str(message))

    def run(self) -> None:
        if self._cancelled:
            self.finished.emit({"logs": []})
            return
        try:
            ctx = LegacyCtx(
                preprocessed_data=self._epochs_dict,
                save_folder_path=SimpleNamespace(get=lambda: self.output_folder),
                data_paths=self.data_paths,
                log=self._log,
            )
            run_post_export(ctx, self._labels)
            if self._cancelled:
                self.finished.emit({"logs": self._logs, "cancelled": True})
            else:
                self.progress.emit(100)
                self.finished.emit({"logs": self._logs})
        except Exception as e:  # pragma: no cover - worker error path
            logging.getLogger(__name__).exception(e)
            self.error.emit(str(e))
            self.finished.emit({"logs": self._logs, "error": str(e)})
