# main_window.py
from __future__ import annotations

import logging
import os
import queue
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from types import MethodType, SimpleNamespace

import tkinter.messagebox as tk_messagebox
from PySide6.QtCore import QObject, QRect, QPropertyAnimation, QTimer, Signal
from PySide6.QtGui import QFont, QIntValidator
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStatusBar,
    QWidget,
)

from Main_App.Legacy_App.file_selection import FileSelectionMixin
from Main_App.Legacy_App.processing_utils import ProcessingMixin
from Main_App.Legacy_App.settings_manager import SettingsManager
from Main_App.Legacy_App.validation_mixins import ValidationMixin
from Main_App.PySide6_App.Backend import Project
from Main_App.PySide6_App.Backend.processing_controller import _animate_progress_to
from Main_App.PySide6_App.Backend.project_manager import (
    edit_project_settings,
    loadProject,
    new_project,
    open_existing_project,
    openProjectPath,
    select_projects_root,
)
from Tools.Average_Preprocessing.New_PySide6.main_window import (
    AdvancedAveragingWindow,
)
from Tools.Stats import StatsWindow as PysideStatsWindow
from Tools.Stats.Legacy.stats import StatsAnalysisWindow as launch_ctk_stats
from config import FPVS_TOOLBOX_VERSION
from . import update_manager
from .file_menu import init_file_menu
from .settings_panel import SettingsDialog
from .sidebar import init_sidebar
from .ui_main import init_ui
import Main_App.Legacy_App.debug_utils as debug_utils
from Main_App.Legacy_App.post_process import post_process as _legacy_post_process

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# Canonical Qt messagebox adapters (used for both tk and legacy debug utils)
# ----------------------------------------------------------------------
def _qt_showerror(title: str, message: str, **options) -> None:
    parent = QApplication.activeWindow()
    QMessageBox.critical(parent, title, message)


def _qt_showwarning(title: str, message: str, **options) -> None:
    parent = QApplication.activeWindow()
    QMessageBox.warning(parent, title, message)


def _qt_showinfo(title: str, message: str, **options) -> None:
    parent = QApplication.activeWindow()
    QMessageBox.information(parent, title, message)


def _qt_askyesno(title: str, message: str, **options) -> bool:
    parent = QApplication.activeWindow()
    result = QMessageBox.question(
        parent, title, message, QMessageBox.Yes | QMessageBox.No
    )
    return result == QMessageBox.Yes


# Route legacy surfaces through the same functions
tk_messagebox.showerror = _qt_showerror
tk_messagebox.showwarning = _qt_showwarning
tk_messagebox.showinfo = _qt_showinfo
tk_messagebox.askyesno = _qt_askyesno
debug_utils.messagebox._qt_showinfo = _qt_showinfo
debug_utils.messagebox._qt_showerror = _qt_showerror

# Toggle which Stats GUI to launch
USE_PYSIDE6_STATS = True  # set to False to use the legacy CustomTkinter GUI


class Processor(QObject):
    """Minimal processing stub emitting progress updates."""

    progressChanged = Signal(int)

    def emit_progress(self, value: int) -> None:
        self.progressChanged.emit(value)


class _QtEntryAdapter:
    """Provide Tk-like get/focus_set for QLineEdit or similar."""

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
        update_manager.cleanup_old_executable()

        self.settings = SettingsManager()
        self.output_folder: str = ""
        self.data_paths: list[str] = []
        self.event_rows: list[QWidget] = []
        self._settings_dialog = None
        self.processor = Processor()
        self.setWindowTitle("FPVS Toolbox")
        self.setMinimumSize(1024, 768)
        self.currentProject: Project | None = None

        # Build UI
        init_ui(self)

        # Sidebar appearance
        if hasattr(self, "sidebar"):
            self.sidebar.setStyleSheet("background-color: #2E2E2E;")

        # Style header bar via objectName (preferred)
        # Requires: the header container in ui_main sets setObjectName("HeaderBar")
        self.setStyleSheet(
            """
#HeaderBar { background-color: #2E2E2E; border-bottom: 1px solid #CCCCCC; }
#HeaderBar QLabel { color: white; padding: 6px 12px; background: transparent; }
"""
        )
        # Fallback for older UI trees where the objectName isn't set yet
        if hasattr(self, "lbl_currentProject"):
            font = self.lbl_currentProject.font()
            font.setPointSize(font.pointSize() + 2)
            font.setWeight(QFont.DemiBold)
            self.lbl_currentProject.setFont(font)
            fallback_parent = self.lbl_currentProject.parentWidget()
            if fallback_parent is not None and not getattr(
                fallback_parent, "objectName", lambda: ""
            )() == "HeaderBar":
                fallback_parent.setStyleSheet(
                    "background-color: #2E2E2E; border-bottom: 1px solid #CCCCCC;"
                )
                self.lbl_currentProject.setStyleSheet(
                    "background: transparent; color: white; padding: 6px 12px;"
                )

        # Progress bar baseline config
        if hasattr(self, "progress_bar"):
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)
            self.progress_bar.setTextVisible(True)
            if hasattr(self, "btn_start"):
                self.progress_bar.setMinimumHeight(self.btn_start.minimumHeight())
            # Legacy mixin compatibility: allow .set(value)
            self.progress_bar.set = self.progress_bar.setValue  # type: ignore[attr-defined]

        # Prevent spurious finalize/error dialogs until a run starts
        self._run_active = False

        # Build nav + menus
        init_sidebar(self)
        select_projects_root(self)
        init_file_menu(self)

        # Status bar
        status = QStatusBar(self)
        self.setStatusBar(status)
        status.showMessage(f"FPVS Toolbox v{FPVS_TOOLBOX_VERSION}")

        # Wire landing page buttons if present
        if hasattr(self, "btn_create_project"):
            self.btn_create_project.clicked.connect(self.actionCreateNewProject.trigger)
        if hasattr(self, "btn_open_project"):
            self.btn_open_project.clicked.connect(self.actionOpenExistingProject.trigger)

        # Default page and initial logs
        if hasattr(self, "stacked"):
            self.stacked.setCurrentIndex(0)
        self.log("Welcome to the FPVS Toolbox!")
        self.log(
            f"Appearance Mode: {self.settings.get('appearance', 'mode', 'System')}"
        )

        # Legacy mixin compatibility ----------------------------
        if hasattr(self, "btn_start"):
            self.btn_start.clicked.connect(self.start_processing)

        self.gui_queue: queue.Queue = queue.Queue()
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

        self._processing_timer = QTimer(self)
        self._processing_timer.timeout.connect(self._periodic_queue_check)
        self._processing_timer.start(50)  # will be gated by _run_active

        # Allow legacy processing_utils to call post_process via a safe wrapper
        self.post_process = MethodType(MainWindow._export_with_post_process, self)

        try:
            update_manager.check_for_updates_async(
                self, silent=True, notify_if_no_update=False
            )
        except Exception as e:
            self.log(f"Auto update check failed: {e}")

    # ------------------------------------------------------------------
    # Logging helpers
    def log(self, message: str, level: int = logging.INFO) -> None:
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        formatted = f"{ts} [GUI]: {message}"
        if hasattr(self, "text_log") and self.text_log:
            self.text_log.append(formatted)
        logger.log(level, message)

    def debug(self, message: str) -> None:
        if logger.isEnabledFor(logging.DEBUG):
            self.log(f"[DEBUG] {message}", level=logging.DEBUG)

    # ------------------------------------------------------------------
    # Mode switching
    def _on_mode_changed(self, mode: str) -> None:
        self.settings.set("processing", "mode", mode)
        self.settings.save()
        self._update_select_button_text()

    def _update_select_button_text(self) -> None:
        if not hasattr(self, "btn_select_data"):
            return
        if getattr(self, "rb_batch", None) and self.rb_batch.isChecked():
            self.btn_select_data.setText("Select Input Folder…")
        else:
            self.btn_select_data.setText("Select .BDF File…")

    # Tkinter after shim
    def after(self, ms: int, callback) -> int:
        QTimer.singleShot(ms, callback)
        return 0

    def _set_controls_enabled(self, enabled: bool) -> None:
        if hasattr(self, "btn_start"):
            self.btn_start.setEnabled(enabled)

    # ------------------------------------------------------------------
    # Processing lifecycle
    def start_processing(self) -> None:
        """Begin a processing run and (re)activate queue checks."""
        self._run_active = True
        # Ensure the timer is ticking for this run (we stop it in finalize)
        if not self._processing_timer.isActive():
            self._processing_timer.start(50)
        try:
            super().start_processing()
        except Exception as e:  # pragma: no cover - GUI error path
            logger.exception(e)
            QMessageBox.critical(self, "Processing Error", str(e))
            self._run_active = False

    def _periodic_queue_check(self) -> None:
        """Process queue messages only when a run is active."""
        if not self._run_active:
            return
        super()._periodic_queue_check()

    def _finalize_processing(self, *args, **kwargs) -> None:
        """Reset run state before delegating to the mixin finalization."""
        self._run_active = False
        if self._processing_timer.isActive():
            self._processing_timer.stop()
        super()._finalize_processing(*args, **kwargs)

    # ------------------------------------------------------------------
    # Settings / updates
    def open_settings_window(self) -> None:
        if self._settings_dialog and self._settings_dialog.isVisible():
            self._settings_dialog.raise_()
            self._settings_dialog.activateWindow()
            return
        dlg = SettingsDialog(self.settings, self)
        self._settings_dialog = dlg
        dlg.exec()
        if hasattr(self, "lbl_debug"):
            self.lbl_debug.setVisible(self.settings.debug_enabled())
        self._settings_dialog = None

    def check_for_updates(self) -> None:
        update_manager.check_for_updates_async(
            self, silent=False, notify_if_no_update=True
        )

    def quit(self) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Project actions
    def new_project(self) -> None:
        new_project(self)
        self._on_project_ready()

    def open_existing_project(self) -> None:
        open_existing_project(self)
        self._on_project_ready()

    def openProjectPath(self, folder: str) -> None:
        openProjectPath(self, folder)
        self._on_project_ready()

    def edit_project_settings(self) -> None:
        """Delegate project editing to project_manager."""
        edit_project_settings(self)

    # ------------------------------------------------------------------
    # Tools launchers
    def open_stats_analyzer(self) -> None:
        """Launch the statistical analysis tool based on USE_PYSIDE6_STATS."""
        if USE_PYSIDE6_STATS:
            window = PysideStatsWindow(self)
            window.show()
            if not hasattr(self, "_child_windows"):
                self._child_windows = []
            self._child_windows.append(window)
        else:
            launch_ctk_stats(master=self)

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
        env = os.environ.copy()
        proj = getattr(self, "currentProject", None)
        if proj and hasattr(proj, "project_root"):
            env["FPVS_PROJECT_ROOT"] = str(proj.project_root)
        subprocess.Popen(cmd, close_fds=True, env=env)

    def open_epoch_averaging(self) -> None:
        """Instantiate and show the Advanced Averaging Analysis window."""
        if not self.currentProject:
            QMessageBox.warning(self, "No Project", "Please load a project first.")
            return

        data_dir = self.currentProject.subfolders.get("data")
        if data_dir is None:
            data_dir = str(self.currentProject.input_folder)
        else:
            data_dir = str(self.currentProject.project_root / data_dir)
        excel_dir = str(
            self.currentProject.project_root
            / self.currentProject.subfolders.get("excel", "")
        )

        if not getattr(self, "_epoch_win", None):
            self._epoch_win = AdvancedAveragingWindow(
                parent=self, input_dir=data_dir, output_dir=excel_dir
            )
        self._epoch_win.show()
        self._epoch_win.raise_()
        self._epoch_win.activateWindow()

    def open_advanced_analysis_window(self) -> None:
        self.open_epoch_averaging()

    def show_relevant_publications(self) -> None:
        QMessageBox.information(
            self,
            "Relevant Publications",
            "This dialog is not yet implemented in the Qt interface.",
        )

    def show_about_dialog(self) -> None:
        QMessageBox.information(
            self,
            "About FPVS ToolBox",
            f"Version: {FPVS_TOOLBOX_VERSION} was developed by Zack Murphy at Mississippi State University.",
        )

    # ------------------------------------------------------------------
    # Project ready -> slide in main page
    def _on_project_ready(self) -> None:
        """Switch to the main page with a slide-in animation."""
        if not getattr(self, "currentProject", None):
            return
        if hasattr(self, "stacked"):
            self.stacked.setCurrentIndex(1)
        container = getattr(self, "page1_container", getattr(self, "homeWidget", None))
        if not container:
            return
        start = QRect(self.width(), 0, self.stacked.width(), self.stacked.height())
        end = QRect(0, 0, self.stacked.width(), self.stacked.height())
        container.setGeometry(start)
        anim = QPropertyAnimation(container, b"geometry")
        anim.setStartValue(start)
        anim.setEndValue(end)
        anim.setDuration(400)
        anim.start()
        self._page1_anim = anim

    # ------------------------------------------------------------------
    # Progress animation adapter
    def _animate_progress_to(self, value: float) -> None:
        _animate_progress_to(self, int(value * 100))

    # ------------------------------------------------------------------
    # Event Map helpers
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
        le_id.setValidator(QIntValidator(1, 999999, le_id))

        def _on_enter_in_label() -> None:
            self.btn_add_row.click()
            if self.event_rows:
                new_row = self.event_rows[-1]
                edits = new_row.findChildren(QLineEdit)
                if edits:
                    edits[0].setFocus()

        le_label.returnPressed.connect(_on_enter_in_label)
        le_id.returnPressed.connect(self.btn_add_row.click)

        btn_rm = QPushButton("✕", row)

        def _remove() -> None:
            self.event_layout.removeWidget(row)
            if row in self.event_rows:
                self.event_rows.remove(row)
            row.deleteLater()
            self.log("Event map row removed.")

        btn_rm.clicked.connect(_remove)

        hl.addWidget(le_label)
        hl.addWidget(le_id)
        hl.addWidget(btn_rm)
        self.event_layout.addWidget(row)
        self.event_rows.append(row)
        self.log("Added event map row")

    @property
    def event_map_entries(self) -> list[dict[str, _QtEntryAdapter]]:
        entries: list[dict[str, _QtEntryAdapter]] = []
        for row in self.event_rows:
            edits = row.findChildren(QLineEdit)
            if len(edits) >= 2:
                entries.append(
                    {"label": _QtEntryAdapter(edits[0]), "id": _QtEntryAdapter(edits[1])}
                )
        return entries

    # ------------------------------------------------------------------
    # Legacy post-process wrapper
    def _export_with_post_process(self, labels: list[str]) -> None:
        """Safely run the legacy post_process for Excel export."""
        excel_dir = self.save_folder_path.get()
        if not excel_dir or not Path(excel_dir).is_dir():
            self.gui_queue.put(
                {"type": "error", "message": f"Excel output folder not found:\n{excel_dir}"}
            )
            return

        original_log = self.log

        def queue_log(message: str, level: int = logging.INFO) -> None:
            self.gui_queue.put({"type": "log", "message": message})
            logger.log(level, message)

        self.log = queue_log

        try:
            _legacy_post_process(self, labels)
            self.gui_queue.put({"type": "log", "message": "Excel export completed"})
        except Exception as err:
            logger.exception("Excel export failed")
            self.gui_queue.put({"type": "error", "message": str(err)})
        finally:
            self.log = original_log

    # ------------------------------------------------------------------
    # Project (de)serialization
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
        self.log(f"Save folder path set: {self.save_folder_path.get()}")

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
        """Collect current UI settings and save them to project.json."""
        if not self.currentProject:
            QMessageBox.warning(
                self, "No Project", "Please open or create a project first."
            )
            return

        self.currentProject.options["mode"] = (
            "single" if getattr(self, "rb_single", None) and self.rb_single.isChecked() else "batch"
        )
        self.currentProject.options["run_loreta"] = (
            self.cb_loreta.isChecked() if hasattr(self, "cb_loreta") else False
        )

        mapping: dict[str, int] = {}
        for row in self.event_rows:
            edits = row.findChildren(QLineEdit)
            if len(edits) >= 2:
                label = edits[0].text().strip()
                ident = edits[1].text().strip()
                if label and ident.isdigit():
                    mapping[label] = int(ident)
        self.currentProject.event_map = mapping

        self.currentProject.save()
        QMessageBox.information(
            self, "Project Saved", "All settings written to project.json."
        )


# ----------------------------------------------------------------------
def main() -> None:
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    app.exec()


if __name__ == "__main__":
    main()
