"""Processing helpers extracted from main_window.py."""
from __future__ import annotations

from pathlib import Path
import logging

from PySide6.QtWidgets import QFileDialog, QMessageBox

from Main_App.Legacy_App.load_utils import load_eeg_file
from Main_App.Legacy_App.app_logic import preprocess_raw
from Main_App.Legacy_App.eeg_preprocessing import perform_preprocessing
from Main_App.PySide6_App.Backend.processing import process_data
from Main_App.Legacy_App.post_process import post_process

logger = logging.getLogger(__name__)


def _animate_progress_to(self, value: int) -> None:
    """Animate the progress bar smoothly to the target value."""
    self._progress_anim.stop()
    self._progress_anim.setStartValue(self.progress_bar.value())
    self._progress_anim.setEndValue(value)
    self._progress_anim.start()


def start_processing(self) -> None:
    """Run the full legacy pipeline, ensuring load_eeg_file() is called with individual .bdf file paths."""
    try:
        input_dir = Path(self.currentProject.input_folder)
        run_loreta = self.cb_loreta.isChecked()

        if self.rb_batch.isChecked():
            bdf_files = list(input_dir.glob("*.bdf"))
            if not bdf_files:
                raise FileNotFoundError(f"No .bdf files in {input_dir}")
        else:
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                "Select .BDF File",
                str(input_dir),
                "BDF Files (*.bdf)",
            )
            if not file_path:
                self.log("No file selected, aborting.")
                return
            bdf_files = [Path(file_path)]

        for fp in bdf_files:
            self.log(f"Loading EEG file: {fp.name}")
            raw = load_eeg_file(self, str(fp))

            self.log("Preprocessing raw data")
            preprocessed = preprocess_raw(self, raw)
            preprocessed = perform_preprocessing(preprocessed)

            out_dir = str(
                self.currentProject.project_root / self.currentProject.subfolders["excel"]
            )
            self.log(f"Running main processing (run_loreta={run_loreta})")
            result = process_data(preprocessed, out_dir, run_loreta)

            self.log("Post-processing results")
            condition_labels = list(self.currentProject.event_map.keys())
            post_process(self, result, condition_labels)

        _animate_progress_to(self, 100)
        self.log("Processing complete")

    except Exception as e:
        self.log(f"Processing failed: {e}", level=logging.ERROR)
        QMessageBox.critical(self, "Processing Error", str(e))
