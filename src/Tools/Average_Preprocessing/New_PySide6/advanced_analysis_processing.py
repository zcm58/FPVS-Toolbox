"""Processing mixin for the PySide6 averaging window."""

from __future__ import annotations

import traceback
from typing import Any, Dict, Optional

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import QMessageBox, QPushButton, QListWidget
import logging

# Assume this legacy function exists and is UI-agnostic
from Tools.Average_Preprocessing.Legacy.advanced_analysis_core import (
    run_advanced_averaging_processing,
)

logger = logging.getLogger(__name__)


class ProcessingWorker(QObject):
    """
    Worker object that runs the long processing task in a separate thread.
    Communicates with the main GUI thread via signals.
    """

    finished = Signal()
    progress = Signal(float)
    log_message = Signal(str)

    def __init__(
        self, defined_groups, main_app_params, output_dir, pid_extractor
    ):
        super().__init__()
        self.defined_groups = defined_groups
        self.main_app_params = main_app_params
        self.output_directory = output_dir
        self.pid_extraction_func = pid_extractor
        self._is_stopped = False

    def run(self):
        """The main work method that is executed in the new thread."""

        # Simple object to mimic threading.Event for the legacy function
        class StopEvent:
            def __init__(self, worker_instance):
                self.worker = worker_instance

            def is_set(self):
                return self.worker._is_stopped

        try:
            # This is the call to the long-running legacy function
            run_advanced_averaging_processing(
                self.defined_groups,
                self.main_app_params,
                None,  # load_file_method - assuming it's handled elsewhere or not needed
                None,  # preprocess_raw_method - same assumption
                None,  # external_post_process_func - same assumption
                self.output_directory,
                self.pid_extraction_func,
                log_callback=self.log_message.emit,
                progress_callback=self.progress.emit,
                stop_event=StopEvent(self),
            )
        except Exception:
            error_msg = f"!!! CRITICAL THREAD ERROR !!!\n{traceback.format_exc()}"
            self.log_message.emit(error_msg)
        finally:
            self.finished.emit()

    def stop(self):
        """Signals the worker to stop."""
        self._is_stopped = True


class AdvancedAnalysisProcessingMixin:
    """Validate configuration and handle starting/stopping processing."""

    defined_groups: list[dict]
    btn_start: QPushButton
    btn_stop: QPushButton
    btn_close: QPushButton
    grp_list: QListWidget
    processing_thread: Optional[QThread] = None
    worker: Optional[ProcessingWorker] = None

    def _update_start_processing_button_state(self) -> None:
        """Enable the start button only if all groups are valid and saved."""
        enabled = bool(
            self.defined_groups
            and all(
                g.get("config_saved")
                and g.get("file_paths")
                and g.get("condition_mappings")
                for g in self.defined_groups
            )
        )
        self.btn_start.setEnabled(enabled)

    def _validate_processing_setup(self) -> Optional[tuple[Dict[str, Any], str]]:
        """
        Validate all group configurations before starting the processing.
        Replicates the legacy validation logic with PySide6 dialogs.
        """
        main_app = self.parent()  # Assume main window is the parent

        # A simplified check for main app parameters
        main_app_params = getattr(main_app, "validated_params", None)
        output_directory = getattr(main_app, "save_folder_path", None)

        if not all([main_app_params, output_directory]):
            QMessageBox.critical(
                self,
                "Error",
                "Main application parameters or output folder are not configured.",
            )
            return None

        if not self.defined_groups:
            QMessageBox.warning(self, "Error", "No averaging groups defined.")
            return None

        for i, group in enumerate(self.defined_groups):
            if not group.get("config_saved", False):
                QMessageBox.warning(
                    self,
                    "Error",
                    f"Group '{group['name']}' has unsaved changes. Please save it first.",
                )
                self.grp_list.setCurrentRow(i)
                return None
            if not group.get("file_paths"):
                QMessageBox.warning(
                    self, "Error", f"Group '{group['name']}' contains no files."
                )
                self.grp_list.setCurrentRow(i)
                return None
            if not group.get("condition_mappings"):
                QMessageBox.warning(
                    self,
                    "Error",
                    f"Group '{group['name']}' has no mapping rules defined.",
                )
                self.grp_list.setCurrentRow(i)
                return None

        return main_app_params, output_directory.get()

    def start_advanced_processing(self) -> None:
        """Validate configuration and spawn the processing thread."""
        if self.processing_thread and self.processing_thread.isRunning():
            self.log("Processing is already in progress.")
            return

        self.log("=" * 30 + "\nValidating configuration before processing...")
        validation = self._validate_processing_setup()
        if not validation:
            return  # Validation failed, message was already shown

        main_app_params, output_directory = validation
        self.log("Validation successful. Starting processing thread...")

        # 1. Create a thread and a worker
        self.processing_thread = QThread()
        self.worker = ProcessingWorker(
            defined_groups=self.defined_groups,
            main_app_params=main_app_params,
            output_dir=output_directory,
            pid_extractor=self._extract_pid_for_group,
        )

        # 2. Move worker to the thread
        self.worker.moveToThread(self.processing_thread)

        # 3. Connect signals and slots
        self.processing_thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.processing_thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.processing_thread.finished.connect(self.processing_thread.deleteLater)
        self.worker.finished.connect(self._on_processing_finished)
        self.worker.log_message.connect(self.log)
        # self.worker.progress.connect(self.progress_bar.setValue) # If you add a progress bar

        # 4. Update UI to "running" state
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)

        # 5. Start the thread
        self.processing_thread.start()

    def stop_processing(self) -> None:
        """Request the running processing thread to stop."""
        if self.worker and self.processing_thread.isRunning():
            self.log("Stop requested. Waiting for the current step to finish...")
            self.btn_stop.setEnabled(False)  # Disable while stopping
            self.worker.stop()
        else:
            self.log("No processing task is currently running.")

    def _on_processing_finished(self):
        """Slot to clean up and reset the UI after processing is complete."""
        self.log("Processing thread has finished.")
        # self.progress_bar.setValue(0) # If you add a progress bar
        self.btn_stop.setEnabled(False)
        self._update_start_processing_button_state()  # Re-enable start if still valid
        self.processing_thread = None
        self.worker = None