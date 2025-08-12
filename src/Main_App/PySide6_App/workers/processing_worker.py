from __future__ import annotations
from typing import Any, Dict, List, Optional, Callable
from PySide6.QtCore import QObject, Signal, Slot
from Main_App.PySide6_App.adapters.post_export_adapter import LegacyCtx, run_post_export


class PostProcessWorker(QObject):
    """Run legacy post_process off the UI thread."""

    progress = Signal(int)
    error = Signal(str)
    finished = Signal(dict)

    def __init__(
        self,
        file_name: str,
        epochs_dict: Dict[str, Any],
        labels: List[str],
        save_folder: Any | None,
        data_paths: List[str] | None,
        settings: Optional[Any] = None,
        logger: Optional[Callable[[str], None]] = None,
    ) -> None:
        super().__init__()
        self._file = file_name
        self._epochs = epochs_dict
        self._labels = labels
        self._save_folder = save_folder
        self._data_paths = data_paths
        self._settings = settings
        self._log = logger or (lambda _m: None)
        self._cancelled = False

    def stop(self) -> None:
        self._cancelled = True

    @Slot()
    def run(self) -> None:
        if self._cancelled:
            self.finished.emit({"file": self._file, "cancelled": True})
            return
        try:
            ctx = LegacyCtx(
                preprocessed_data=self._epochs,
                save_folder_path=self._save_folder,
                data_paths=self._data_paths,
                settings=self._settings,
                log=self._log,
            )
            run_post_export(ctx, self._labels)
            self.progress.emit(100)
            self.finished.emit({"file": self._file, "cancelled": False})
        except Exception as e:  # pragma: no cover
            self.error.emit(str(e))
