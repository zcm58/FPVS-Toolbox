from __future__ import annotations

from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
)
from PySide6.QtCore import QObject, Signal, QTimer
import tkinter.messagebox as tk_messagebox
from PySide6.QtWidgets import QMessageBox
from Main_App.Legacy_App.post_process import post_process as _legacy_post_process
import logging
import pandas as pd
from pathlib import Path
import subprocess
import sys
import queue
from .settings_panel import SettingsDialog
from .sidebar import init_sidebar
from .file_menu import init_file_menu
from .ui_main import init_ui
from Main_App.Legacy_App.settings_manager import SettingsManager
from Main_App.PySide6_App.Backend import Project
from Main_App.PySide6_App.Backend.processing_controller import (
    _animate_progress_to,
)

from Main_App.Legacy_App.file_selection import FileSelectionMixin
from Main_App.Legacy_App.validation_mixins import ValidationMixin
from Main_App.Legacy_App.processing_utils import ProcessingMixin
from Main_App.PySide6_App.Backend.project_manager import (
    select_projects_root,
    new_project,
    open_existing_project,
    openProjectPath,
    loadProject,
)
from types import SimpleNamespace

# Redirect legacy tkinter dialogs to Qt
def _qt_showerror(title, message, **options):
    QMessageBox.critical(None, title, message)


def _qt_showwarning(title, message, **options):
    QMessageBox.warning(None, title, message)


tk_messagebox.showerror = _qt_showerror
tk_messagebox.showwarning = _qt_showwarning
class Processor(QObject):
    """Minimal processing stub emitting progress updates."""

    progressChanged = Signal(int)

    def emit_progress(self, value: int) -> None:
        self.progressChanged.emit(value)

logger = logging.getLogger(__name__)


class _QtEntryAdapter:
    """Provide Tk-like ``get`` and ``focus_set`` for :class:`QLineEdit`."""

    def __init__(self, line_edit: QLineEdit) -> None:
        self._edit = line_edit

    def get(self) -> str:  # type: ignore[override]
        return self._edit.text()

    def focus_set(self) -> None:  # type: ignore[override]
        self._edit.setFocus()


class MainWindow(QMainWindow, FileSelectionMixin, ValidationMixin, ProcessingMixin):
    """Main application window implemented with PySide6."""

    def __init__(self) -> None:
        super().__init__()
        self.settings = SettingsManager()
        self.output_folder: str = ""
        self.data_paths: list[str] = []
        self.event_rows: list[QWidget] = []
        self._settings_dialog = None
        self.processor = Processor()
        self.setWindowTitle("FPVS Toolbox")
        self.setMinimumSize(1024, 768)
        self.currentProject: Project | None = None
        init_ui(self)
        # Prevent spurious finalize/error dialogs until a run starts
        self._run_active = False
        # Support legacy .set() calls from processing_utils
        self.progress_bar.set = self.progress_bar.setValue
        init_sidebar(self)

        select_projects_root(self)

        init_file_menu(self)
        self.log("Welcome to the FPVS Toolbox!")
        self.log(
            f"Appearance Mode: {self.settings.get('appearance', 'mode', 'System')}"
        )

        # Legacy mixin compatibility ----------------------------
        self.gui_queue = queue.Queue()
        self.processing_thread = None
        self.detection_thread = None
        self.preprocessed_data = {}
        self.validated_params = {}
        self._max_progress = 1
        self.busy = False
        self.run_loreta_var = SimpleNamespace(get=lambda: self.cb_loreta.isChecked())
        self.save_fif_var = SimpleNamespace(get=lambda: True)
        self.save_folder_path = SimpleNamespace(get=lambda: "", set=lambda v: None)
        self.file_mode = SimpleNamespace(get=lambda: "Batch")
        self.file_type = SimpleNamespace(set=lambda v: None)
        # Connect temporary data selection button to legacy mixin
        if hasattr(self, "btn_select_data"):
            self.btn_select_data.clicked.connect(self.select_data_source)
        self._processing_timer = QTimer(self)
        self._processing_timer.timeout.connect(self._periodic_queue_check)
        self._processing_timer.start(50)

        # Allow legacy processing_utils to call self.post_process(...)
        self.post_process = _legacy_post_process

    # ------------------------------------------------------------------

    # ------------------------------------------------------------------

    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    def log(self, message: str, level: int = logging.INFO) -> None:
        ts = pd.Timestamp.now().strftime("%H:%M:%S.%f")[:-3]
        formatted = f"{ts} [GUI]: {message}"
        if hasattr(self, "text_log") and self.text_log:
            self.text_log.append(formatted)
        logger.log(level, message)

    def debug(self, message: str) -> None:
        if logger.isEnabledFor(logging.DEBUG):
            self.log(f"[DEBUG] {message}", level=logging.DEBUG)

    # ------------------------------------------------------------------
    def _on_mode_changed(self, mode: str) -> None:
        self.settings.set("processing", "mode", mode)
        self.settings.save()
        self._update_select_button_text()

    def _update_select_button_text(self) -> None:
        """Update the label of the EEG selection button based on the mode."""
        if not hasattr(self, "btn_open_eeg"):
            return
        if self.rb_batch.isChecked():
            self.btn_open_eeg.setText("Select Input Folder…")
        else:
            self.btn_open_eeg.setText("Select .BDF File…")

    def after(self, ms: int, callback) -> int:
        QTimer.singleShot(ms, callback)
        return 0

    def _set_controls_enabled(self, enabled: bool) -> None:
        if hasattr(self, "btn_start"):
            self.btn_start.setEnabled(enabled)

    def start_processing(self) -> None:
        """Begin a processing run and activate queue checks."""
        # Mark that a real run is active
        self._run_active = True
        # Delegate to the legacy mixin’s processing entry point
        super().start_processing()

    def _periodic_queue_check(self) -> None:
        """Process queue messages only when a run is active."""
        # Only process queue messages while a run is active
        if not self._run_active:
            return
        super()._periodic_queue_check()

    def _finalize_processing(self, *args, **kwargs) -> None:
        """Reset run state after mixin finalization."""
        # Call the mixin’s finalization (dialogs, control resets)
        super()._finalize_processing(*args, **kwargs)
        # Now that the run is fully done, disable run_active
        self._run_active = False

    # ------------------------------------------------------------------
    def open_settings_window(self) -> None:
        if self._settings_dialog and self._settings_dialog.isVisible():
            self._settings_dialog.raise_()
            self._settings_dialog.activateWindow()
            return
        dlg = SettingsDialog(self.settings, self)
        self._settings_dialog = dlg
        dlg.exec()
        self.lbl_debug.setVisible(self.settings.debug_enabled())
        self._settings_dialog = None

    def check_for_updates(self) -> None:
        from Main_App.Legacy_App import update_manager

        update_manager.check_for_updates_async(self, silent=False)

    def quit(self) -> None:
        self.close()

    # ------------------------------------------------------------------
    def new_project(self) -> None:
        new_project(self)

    def open_existing_project(self) -> None:
        open_existing_project(self)

    def openProjectPath(self, folder: str) -> None:
        openProjectPath(self, folder)

    def open_stats_analyzer(self) -> None:
        QMessageBox.information(
            self,
            "Stats Toolbox",
            "The statistics tool is not yet available in the Qt interface.",
        )

    def open_image_resizer(self) -> None:
        cmd = [sys.executable]
        if getattr(sys, "frozen", False):
            cmd.append("--run-image-resizer")
        else:
            script = (
                Path(__file__).resolve().parents[3]
                / "Tools"
                / "Image_Resizer"
                / "pyside_resizer.py"
            )
            cmd.append(str(script))
        subprocess.Popen(cmd, close_fds=True)

    def open_plot_generator(self) -> None:
        cmd = [sys.executable]
        if getattr(sys, "frozen", False):
            cmd.append("--run-plot-generator")
        else:
            script = (
                Path(__file__).resolve().parents[3]
                / "Tools"
                / "Plot_Generator"
                / "plot_generator.py"
            )
            cmd.append(str(script))
        subprocess.Popen(cmd, close_fds=True)

    def open_advanced_analysis_window(self) -> None:
        QMessageBox.information(
            self,
            "Advanced Analysis",
            "The advanced preprocessing tool is not yet available in the Qt interface.",
        )

    def show_relevant_publications(self) -> None:
        QMessageBox.information(
            self,
            "Relevant Publications",
            "This dialog is not yet implemented in the Qt interface.",
        )

    def show_about_dialog(self) -> None:
        from PySide6.QtWidgets import QMessageBox
        from config import FPVS_TOOLBOX_VERSION

        QMessageBox.information(
            self,
            "About FPVS ToolBox",
            f"Version: {FPVS_TOOLBOX_VERSION} was developed by Zack Murphy at Mississippi State University.",
        )

    # ------------------------------------------------------------------


    def _animate_progress_to(self, value: float) -> None:
        _animate_progress_to(self, int(value * 100))

    def detect_trigger_ids(self) -> None:  # pragma: no cover - GUI stub
        try:
            from Tools.Event_Map import event_map_utils

            pairs = event_map_utils.detect_trigger_ids(self.data_paths)
        except Exception as err:
            QMessageBox.warning(self, "Detection Failed", str(err))
            return

        added = 0
        for lbl, ident in pairs:
            self.add_event_row(str(lbl), str(ident))
            added += 1
        self.log(f"Detected and added {added} trigger ID(s)")

    def add_event_row(self, label: str = "", id: str = "") -> None:
        row = QWidget(self.event_container)
        hl = QHBoxLayout(row)
        le_label = QLineEdit(label, row)
        le_id = QLineEdit(id, row)
        btn_rm = QPushButton("✕", row)
        def _remove() -> None:
            row.setParent(None)
            self.log("Event map row removed.")
        btn_rm.clicked.connect(_remove)
        hl.addWidget(le_label)
        hl.addWidget(le_id)
        hl.addWidget(btn_rm)
        self.event_layout.addWidget(row)
        self.event_rows.append(row)
        self.log("Added event map row")

    @property
    def event_map_entries(self):
        entries = []
        for row in self.event_rows:
            edits = row.findChildren(QLineEdit)
            if len(edits) >= 2:
                entries.append(
                    {
                        "label": _QtEntryAdapter(edits[0]),
                        "id": _QtEntryAdapter(edits[1]),
                    }
                )
        return entries

    # ------------------------------------------------------------------
    def loadProject(self, project: Project) -> None:  # pragma: no cover - GUI stub
        loadProject(self, project)

        # Auto-populate data_paths from the project's input folder
        input_dir = Path(project.input_folder)
        bdf_files = sorted(input_dir.glob("*.bdf"))
        self.data_paths = [str(p) for p in bdf_files]
        if self.data_paths:
            self.log(
                f"Project data folder set: {input_dir} ({len(self.data_paths)} .bdf files)"
            )
        else:
            self.log(
                f"Warning: no .bdf files found in project input folder: {input_dir}",
                level=logging.WARNING,
            )

        # Provide legacy post_process with a .get() for the Excel output folder
        excel_dir = project.project_root / project.subfolders["excel"]
        self.save_folder_path = SimpleNamespace(get=lambda: str(excel_dir))

        def make_entry(value: str):
            edit = QLineEdit(str(value))
            return _QtEntryAdapter(edit)

        p = self.currentProject.preprocessing
        self.low_pass_entry = make_entry(p.get("low_pass"))
        self.high_pass_entry = make_entry(p.get("high_pass"))
        self.downsample_entry = make_entry(p.get("downsample"))
        self.epoch_start_entry = make_entry(
            self.settings.get("preprocessing", "epoch_start", "-1")
        )
        self.epoch_end_entry = make_entry(
            self.settings.get("preprocessing", "epoch_end", "125")
        )
        self.reject_thresh_entry = make_entry(p.get("rejection_z"))
        self.ref_channel1_entry = make_entry(p.get("ref_chan1"))
        self.ref_channel2_entry = make_entry(p.get("ref_chan2"))
        self.max_idx_keep_entry = make_entry(p.get("max_chan_idx"))
        self.max_bad_channels_alert_entry = make_entry(p.get("max_bad_chans"))

    def saveProjectSettings(self) -> None:
        """Collect current UI settings and save them to ``project.json``."""
        if not self.currentProject:
            QMessageBox.warning(self, "No Project", "Please open or create a project first.")
            return

        self.currentProject.options["mode"] = "single" if self.rb_single.isChecked() else "batch"
        self.currentProject.options["run_loreta"] = self.cb_loreta.isChecked()

        mapping: dict[str, int] = {}
        for row in self.event_rows:
            edits = row.findChildren(QLineEdit)
            if len(edits) >= 2:
                label = edits[0].text()
                ident = edits[1].text()
                if label and ident.isdigit():
                    mapping[label] = int(ident)
        self.currentProject.event_map = mapping

        self.currentProject.save()
        QMessageBox.information(self, "Project Saved", "All settings written to project.json.")

def main() -> None:
    app = QApplication([])
    win = MainWindow()
    win.show()
    app.exec()
if __name__ == "__main__":
    main()
