from __future__ import annotations

from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QMessageBox,
)
from PySide6.QtCore import QObject, Signal
import logging
import pandas as pd
from pathlib import Path
import subprocess
import sys
from .settings_panel import SettingsDialog
from .sidebar import init_sidebar
from .file_menu import init_file_menu
from .ui_main import init_ui
from Main_App.Legacy_App.settings_manager import SettingsManager
from Main_App.PySide6_App.Backend import Project
from Main_App.PySide6_App.Backend.processing_controller import (
    start_processing,
    _animate_progress_to,
)
from Main_App.PySide6_App.Backend.project_manager import (
    select_projects_root,
    new_project,
    open_existing_project,
    openProjectPath,
    loadProject,
)
class Processor(QObject):
    """Minimal processing stub emitting progress updates."""

    progressChanged = Signal(int)

    def emit_progress(self, value: int) -> None:
        self.progressChanged.emit(value)

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
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
        init_sidebar(self)

        select_projects_root(self)

        init_file_menu(self)
        self.log("Welcome to the FPVS Toolbox!")
        self.log(
            f"Appearance Mode: {self.settings.get('appearance', 'mode', 'System')}"
        )

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

    def start_processing(self) -> None:
        start_processing(self)

    def _animate_progress_to(self, value: int) -> None:
        _animate_progress_to(self, value)

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

    # ------------------------------------------------------------------
    def loadProject(self, project: Project) -> None:  # pragma: no cover - GUI stub
        loadProject(self, project)

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
