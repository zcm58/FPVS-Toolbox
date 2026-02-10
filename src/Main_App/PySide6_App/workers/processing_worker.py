from __future__ import annotations
from typing import Any, Dict, List, Optional, Callable
from PySide6.QtCore import QObject, Signal, Slot
from types import SimpleNamespace
from pathlib import Path
import time
import logging
from Main_App.PySide6_App.adapters.post_export_adapter import LegacyCtx, run_post_export


logger = logging.getLogger(__name__)


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
        self._epochs: Dict[str, Any] | None = epochs_dict
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
            started_at = time.perf_counter()
            # Ensure adapter-compatible save_folder_path (must expose .get())
            sf = self._save_folder
            folder_getter = getattr(sf, "get", None)
            if callable(folder_getter):
                save_folder_value = str(folder_getter())  # e.g., a QLineEdit-like object already providing .get()
            elif sf is None:
                save_folder_value = ""
            else:
                save_folder_value = str(Path(sf))
            save_folder_obj = SimpleNamespace(get=lambda value=save_folder_value: value)

            output_root = Path(save_folder_value).resolve() if save_folder_value else None

            def _excel_snapshot() -> dict[str, float]:
                if output_root is None or not output_root.is_dir():
                    return {}
                snapshot: dict[str, float] = {}
                for path in output_root.rglob("*.xls*"):
                    try:
                        snapshot[str(path.resolve())] = path.stat().st_mtime
                    except OSError:
                        continue
                return snapshot

            before_snapshot = _excel_snapshot()

            ctx = LegacyCtx(
                preprocessed_data=self._epochs or {},
                save_folder_path=save_folder_obj,
                data_paths=self._data_paths,
                settings=self._settings,
                log=self._log,
            )

            run_post_export(ctx, self._labels)
            after_snapshot = _excel_snapshot()

            generated_excel_paths = sorted(
                path
                for path, mtime in after_snapshot.items()
                if path not in before_snapshot or mtime > before_snapshot[path]
            )
            existing_excel_paths = sorted(after_snapshot.keys())

            logger.info(
                "pipeline_excel_export",
                extra={
                    "operation": "pipeline_excel_export",
                    "project_root": str(output_root.parent) if output_root else "",
                    "expected_output_dir": str(output_root) if output_root else "",
                    "export_reported_success": True,
                    "generated_excel_count": len(generated_excel_paths),
                    "glob_result_count": len(existing_excel_paths),
                    "elapsed_ms": int((time.perf_counter() - started_at) * 1000),
                },
            )

            # FIX 2: Immediate memory cleanup
            self._epochs = None

            self.progress.emit(100)
            self.finished.emit(
                {
                    "file": self._file,
                    "cancelled": False,
                    "output_root": str(output_root) if output_root else "",
                    "generated_excel_paths": generated_excel_paths,
                    "existing_excel_paths": existing_excel_paths,
                }
            )

        except Exception as e:
            logger.exception(
                "pipeline_excel_export_failed",
                extra={
                    "operation": "pipeline_excel_export",
                    "file": self._file,
                    "error": str(e),
                },
            )
            self.error.emit(str(e))
            # FIX 3: Ensure thread terminates even on error
            # Use a distinct status so Main App knows it failed, but thread still dies.
            self.finished.emit({"file": self._file, "cancelled": False, "error": str(e)})
