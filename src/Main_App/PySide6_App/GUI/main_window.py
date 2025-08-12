# main_window.py
from __future__ import annotations

import logging
import os
import queue
import subprocess
import sys
import re
from typing import Callable
from datetime import datetime
from pathlib import Path
from types import MethodType, SimpleNamespace

# Qt / PySide6
import tkinter.messagebox as tk_messagebox
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QFont, QIntValidator
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QAbstractButton,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStatusBar,
    QWidget,
)

# App imports
import config
from Main_App.Legacy_App.file_selection import FileSelectionMixin
from Main_App.Legacy_App.processing_utils import ProcessingMixin
from Main_App.Legacy_App.settings_manager import SettingsManager
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
# Keep this module quiet unless the app configures handlers; avoids accidental console output.
logger.addHandler(logging.NullHandler())

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

    # Legacy mixin hook: enable/disable controls during run
    def _set_controls_enabled(self, enabled: bool) -> None:
        """
        Adapter required by Legacy_App.processing_utils.
        Disables common inputs while a run is active; safe if widgets are missing.
        """
        self.busy = not enabled

        def _safe(name: str) -> None:
            w = getattr(self, name, None)
            if w and hasattr(w, "setEnabled"):
                try:
                    w.setEnabled(enabled)
                except Exception:
                    pass

        # Common selectors / actions (exists-if-present)
        for n in (
            "btn_start",
            "btn_select_input_file", "le_input_file",
            "btn_select_input_folder", "le_input_folder",
            "btn_add_event", "btn_detect",
            "cb_loreta",
            "btn_create_project", "btn_open_project",
        ):
            _safe(n)

        # Event-map row edits/buttons
        for row in getattr(self, "event_rows", []):
            for w in row.findChildren((QLineEdit, QAbstractButton)):
                w.setEnabled(enabled)


class MainWindow(QMainWindow, FileSelectionMixin, ProcessingMixin):
    """Main application window implemented with PySide6.

    Notes
    -----
    * We **do not** inherit the legacy ValidationMixin anymore.
      ProcessingMixin expects ``_validate_inputs()``; we provide a
      modern implementation that collects inputs from the current
      Project + GUI and sets ``self.validated_params``.
    * We also wrap legacy post_process with a log silencer to suppress
      extremely verbose SNR-per-bin messages unless Debug mode is on.
    * Queue polling uses a QTimer to keep the GUI responsive while the
      worker thread runs.
    """

    # -------------------------- lifecycle --------------------------- #
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

        # Style header bar via objectName (preferred)
        if hasattr(self, "lbl_currentProject"):
            font = self.lbl_currentProject.font()
            font.setPointSize(font.pointSize() + 2)
            font.setWeight(QFont.DemiBold)
            self.lbl_currentProject.setFont(font)

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

        # Wire Start button
        if hasattr(self, "btn_start"):
            self.btn_start.clicked.connect(self.start_processing)

        # Legacy compat fields used by ProcessingMixin
        self.gui_queue: queue.Queue = queue.Queue()
        self.processing_thread = None
        self.detection_thread = None
        self.preprocessed_data = {}
        self.validated_params = {}
        self._max_progress = 1
        self.busy = False

        # Flags/vars the mixin expects
        self.run_loreta_var = SimpleNamespace(get=lambda: self.cb_loreta.isChecked())
        self.save_fif_var = SimpleNamespace(get=lambda: True)
        self.save_folder_path = SimpleNamespace(get=lambda: "", set=lambda v: None)
        self.file_mode = SimpleNamespace(get=lambda: "Batch")
        self.file_type = SimpleNamespace(set=lambda v: None)

        # Timer to poll the worker queue → keeps GUI responsive
        self._processing_timer = QTimer(self)
        self._processing_timer.timeout.connect(self._periodic_queue_check)
        # Legacy mixin uses Tk's .after(); we emulate it with QTimer
        self._use_legacy_after = True
        self._after_timers: dict[int, QTimer] = {}
        self._queue_job_id: int | None = None
        # Starts when a run begins; stops in _finalize_processing

        # Allow legacy processing_utils to call post_process via a safe wrapper
        self.post_process = MethodType(MainWindow._export_with_post_process, self)

        try:
            update_manager.check_for_updates_async(
                self, silent=True, notify_if_no_update=False
            )
        except Exception as e:
            self.log(f"Auto update check failed: {e}")

    # ---------------------------- logging --------------------------- #
    def _emit_backend_log(self, level: int, message: str) -> None:
        """
        Emit to the Python logging backend only when:
          * Debug mode is enabled, or
          * Level is WARNING or higher.
        Prevents noisy INFO logs in the IDE/console during normal runs.
        """
        try:
            debug_on = self.settings.debug_enabled()
        except Exception:
            debug_on = False
        if debug_on or level >= logging.WARNING:
            logger.log(level, message)

    def log(self, message: str, level: int = logging.INFO) -> None:
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        formatted = f"{ts} [GUI]: {message}"
        if hasattr(self, "text_log") and self.text_log:
            self.text_log.append(formatted)
        # Do not emit INFO-level messages to backend unless Debug is on.
        self._emit_backend_log(level, message)

    # -------------------------- processing -------------------------- #
    def start_processing(self) -> None:
        """Begin a processing run and (re)activate queue checks.

        We keep the GUI responsive by polling the queue via QTimer while
        the worker thread (in ProcessingMixin) does the heavy lifting.
        """
        # Make the run active & start the queue polling timer
        self._run_active = True
        # Avoid double scheduling: if legacy uses .after(), don't run our own timer
        if (not self._use_legacy_after) and (not self._processing_timer.isActive()):
            # Fallback path (not used when legacy .after is active)
            self._processing_timer.start(50)  # ~20fps UI updates

        # Reset SNR tick (used by throttled post-process logging)
        self._snr_tick = 0

        try:
            # The legacy mixin calls ``_validate_inputs()``. Provide our own
            # modern validation implementation (below) that builds the params
            # and ensures files/paths exist.
            super().start_processing()
        except Exception as e:  # pragma: no cover - GUI error path
            logger.exception(e)
            QMessageBox.critical(self, "Processing Error", str(e))
            self._run_active = False

    def _periodic_queue_check(self) -> None:
        if not self._run_active:
            return
        super()._periodic_queue_check()

    def _finalize_processing(self, *args, **kwargs) -> None:
        self._run_active = False
        self._processing_timer.stop()
        super()._finalize_processing(*args, **kwargs)

    # ------------------------ Tk-style scheduling ------------------------ #
    def after(self, delay_ms: int, callback: Callable[[], None]) -> int:
        """Tkinter-compatible .after() backed by QTimer.singleShot.
        Returns a job id usable with after_cancel.
        """
        timer = QTimer(self)
        timer.setSingleShot(True)
        job_id = id(timer)

        def _run_and_cleanup() -> None:
            try:
                callback()
            finally:
                # remove and delete timer
                self._after_timers.pop(job_id, None)
                timer.deleteLater()

        timer.timeout.connect(_run_and_cleanup)
        self._after_timers[job_id] = timer
        timer.start(int(delay_ms))
        return job_id

    def after_cancel(self, job_id: int) -> None:
        """Cancel a scheduled callback created by .after()."""
        t = self._after_timers.pop(job_id, None)
        if t:
            t.stop()
            t.deleteLater()

    # The ProcessingMixin looks for this. We replace legacy ValidationMixin.
    def _validate_inputs(self) -> bool:  # called inside ProcessingMixin.start_processing
        """Modern input validation + parameter collection.

        Returns
        -------
        bool
            True if everything looks good and ``self.validated_params`` is set.
        """
        if not getattr(self, "currentProject", None):
            QMessageBox.warning(self, "No Project", "Please open or create a project first.")
            return False

        # Build file list from project folder if needed
        if not self.data_paths:
            input_dir = Path(self.currentProject.input_folder)
            if not input_dir.is_dir():
                QMessageBox.critical(self, "Input Folder Missing", str(input_dir))
                return False
            bdf_files = sorted([str(p) for p in input_dir.glob("*.bdf")])
            if not bdf_files:
                QMessageBox.warning(self, "No Data", "No .bdf files found in the input folder.")
                return False
            self.data_paths = bdf_files
            self.log(f"Processing: {len(self.data_paths)} file(s) selected.")

        # Save/output folder from project
        excel_sub = self.currentProject.subfolders.get("excel")
        if not excel_sub:
            QMessageBox.critical(self, "Project Error", "Excel subfolder not configured in project.json.")
            return False
        excel_dir = Path(self.currentProject.project_root) / excel_sub
        excel_dir.mkdir(parents=True, exist_ok=True)
        self.save_folder_path = SimpleNamespace(get=lambda: str(excel_dir))

        # Build params from project + settings + event-map UI
        params = self._build_validated_params()
        if params is None:
            return False
        self.validated_params = params

        # We show a concise summary (not noisy) so users see what's about to run
        lp = params.get("low_pass")
        hp = params.get("high_pass")
        ds = params.get("downsample")
        rz = params.get("reject_thresh")
        r1, r2 = params.get("ref_channel1"), params.get("ref_channel2")
        ep = (params.get("epoch_start"), params.get("epoch_end"))
        stim = params.get("stim_channel")
        self.log(
            f"Preproc params → HPF={hp if hp is not None else 'DC'}Hz, "
            f"LPF={lp if lp is not None else 'Nyq'}Hz, DS={ds}Hz, "
            f"Zreject={rz}, ref=({r1},{r2}), epoch=[{ep[0]}, {ep[1]}], stim='{stim}', "
            f"events={len(params.get('event_id_map', {}))}"
        )
        return True

    def _build_validated_params(self) -> dict | None:
        s = self.settings
        p = self.currentProject.preprocessing

        def _to_float(val, default=None):
            try:
                return float(val) if val is not None and str(val) != "" else default
            except Exception:
                return default

        def _to_int(val, default=None):
            try:
                return int(val) if val is not None and str(val) != "" else default
            except Exception:
                return default

        # Event map from UI rows → {label: int_id}
        event_map: dict[str, int] = {}
        for row in self.event_rows:
            edits = row.findChildren(QLineEdit)
            if len(edits) >= 2:
                label = edits[0].text().strip()
                ident = edits[1].text().strip()
                if label and ident.isdigit():
                    event_map[label] = int(ident)
        if not event_map:
            QMessageBox.warning(self, "No Events", "Please add at least one event map entry.")
            return None

        params = {
            # filter / resample / reject
            "low_pass": _to_float(p.get("low_pass")),
            "high_pass": _to_float(p.get("high_pass")),
            "downsample": _to_int(p.get("downsample")),
            "downsample_rate": _to_int(p.get("downsample")),  # some helpers expect this key
            "reject_thresh": _to_float(p.get("rejection_z")),
            "ref_channel1": p.get("ref_chan1") or None,
            "ref_channel2": p.get("ref_chan2") or None,
            "max_idx_keep": _to_int(p.get("max_chan_idx")),
            "max_bad_channels_alert_thresh": _to_int(p.get("max_bad_chans"), 9999),
            # epoching / events
            "epoch_start": _to_float(s.get("preprocessing", "epoch_start", "-1"), -1.0),
            "epoch_end": _to_float(s.get("preprocessing", "epoch_end", "125"), 125.0),
            "stim_channel": s.get("preprocessing", "stim_channel", config.DEFAULT_STIM_CHANNEL),
            "event_id_map": event_map,
        }
        return params

    # ------------------------- settings UI -------------------------- #
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

    # --------------------------- projects --------------------------- #
    def new_project(self) -> None:
        new_project(self)
        self._on_project_ready()

    def open_existing_project(self) -> None:
        open_existing_project(self)
        self._on_project_ready()

    def openProjectPath(self, folder: str) -> None:  # noqa: N802 (compat)
        openProjectPath(self, folder)
        self._on_project_ready()

    def edit_project_settings(self) -> None:
        edit_project_settings(self)

    def _on_project_ready(self) -> None:
        if not getattr(self, "currentProject", None):
            return
        if hasattr(self, "stacked"):
            self.stacked.setCurrentIndex(1)

    # --------------------------- tools UI --------------------------- #
    def open_stats_analyzer(self) -> None:
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

    # ------------------------- progress/rows ------------------------- #
    def _animate_progress_to(self, value: float) -> None:
        _animate_progress_to(self, int(value * 100))

    def add_event_row(self, label: str = "", id: str = "") -> None:
        row = QWidget(self.event_container)
        hl = QHBoxLayout(row)

        le_label = QLineEdit(label, row)
        le_id = QLineEdit(id, row)
        le_id.setValidator(QIntValidator(1, 999999, le_id))

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

    # ------------------- legacy post-process wrapper ---------------- #
    # Silence SNR-per-bin spam unless Debug is enabled. Keep the GUI
    # responsive by pushing messages to the queue just like the worker.
    _SNR_RE = re.compile(r"\bSNR\b", re.IGNORECASE)

    def _export_with_post_process(self, labels: list[str]) -> None:
        """Safely run legacy post_process for Excel export.

        Suppresses ultra-verbose SNR lines when Debug is off and then
        verifies whether any .xlsx files changed under the Excel folder
        during this export. Results are sent via the GUI queue.
        """
        excel_dir = self.save_folder_path.get() if getattr(self, "save_folder_path", None) else ""
        export_started_ts = datetime.now().timestamp()
        if not excel_dir or not Path(excel_dir).is_dir():
            self.gui_queue.put(
                {"type": "error", "message": f"Excel output folder not found:\n{excel_dir}"}
            )
            return

        original_log = self.log

        def throttled_gui_log(message: str, level: int = logging.INFO) -> None:
            # Suppress SNR chatter unless Debug mode is on
            if not self.settings.debug_enabled():
                if MainWindow._SNR_RE.search(str(message)):
                    return  # drop
            # Route through the queue so the GUI stays responsive
            self.gui_queue.put({"type": "log", "message": str(message)})
            # Respect the same "no INFO unless debug" rule for backend
            self._emit_backend_log(level, str(message))

        # Temporarily replace self.log used by legacy post_process
        self.log = throttled_gui_log

        # Also filter any direct logger.info(...) from legacy code
        snr_filter = None
        filter_targets: list[logging.Logger] = []
        if not self.settings.debug_enabled():
            class _DropSNRFilter(logging.Filter):
                def __init__(self) -> None:
                    super().__init__()
                    self.count = 0
                def filter(self, record: logging.LogRecord) -> bool:
                    msg = record.getMessage() if hasattr(record, "getMessage") else str(record.msg)
                    if MainWindow._SNR_RE.search(str(msg)):
                        self.count += 1
                        return False
                    return True
            snr_filter = _DropSNRFilter()
            for name in ("", "Main_App", "Main_App.Legacy_App"):
                lg = logging.getLogger(name)
                lg.addFilter(snr_filter)
                filter_targets.append(lg)

        try:
            # Run legacy exporter (may call self.log many times)
            _legacy_post_process(self, labels)

            # ----- Post-export verification (non-blocking) -----
            try:
                root = Path(excel_dir)
                cutoff = export_started_ts - 1.0
                recent: list[Path] = []
                for p in root.rglob("*.xlsx"):
                    try:
                        if p.stat().st_mtime >= cutoff:
                            recent.append(p)
                    except OSError:
                        pass
                if recent:
                    recent.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                    sample = "; ".join(str(p.relative_to(root)) for p in recent[:5])
                    msg = (
                        f"Excel export completed • {len(recent)} file(s) updated under:\n"
                        f"{excel_dir}\nExamples: {sample}"
                    )
                    self.gui_queue.put({"type": "log", "message": msg})
                else:
                    msg = (
                        f"No new .xlsx files detected in:\n{excel_dir}\n"
                        f"(Verify write permissions and that condition folders exist.)"
                    )
                    self.gui_queue.put({"type": "error", "message": msg})
            except Exception as _verify_err:
                # Keep IDE quiet unless debug + avoid breaking UX
                self._emit_backend_log(logging.DEBUG, f"export verification skipped: {_verify_err}")

            self.gui_queue.put({"type": "log", "message": "Excel export completed"})
        except Exception as err:
            # Backend should see errors regardless of debug
            self._emit_backend_log(logging.ERROR, f"Excel export failed: {err}")
            self.gui_queue.put({"type": "error", "message": str(err)})
        finally:
            # Remove temporary filter(s) and restore logger
            if snr_filter:
                for lg in filter_targets:
                    try:
                        lg.removeFilter(snr_filter)
                    except Exception:
                        pass
                if snr_filter.count:
                    self.gui_queue.put(
                        {"type": "log", "message": f"Suppressed {snr_filter.count} SNR progress lines (Debug off)."}
                    )
            self.log = original_log

    # ------------------------ project load hook --------------------- #
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
        excel_subfolder = project.subfolders.get("excel")
        if excel_subfolder:
            excel_dir = project.project_root / excel_subfolder
            excel_dir.mkdir(parents=True, exist_ok=True)
            self.save_folder_path = SimpleNamespace(get=lambda: str(excel_dir))
            self.log(f"Save folder path set: {self.save_folder_path.get()}")
        else:
            QMessageBox.warning(
                self,
                "Missing Excel Folder",
                "No 'excel' subfolder configured. Please update the project settings.",
            )
            self.log(
                "Project missing 'excel' subfolder; save folder path not set.",
                level=logging.WARNING,
            )
            self.save_folder_path = None

        # Build ephemeral entry adapters for legacy helpers that expect .get()
        def make_entry(value: str | float | int | None):
            edit = QLineEdit(str(value) if value is not None else "")
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
        if not self.currentProject:
            QMessageBox.warning(
                self, "No Project", "Please open or create a project first."
            )
            return

        self.currentProject.options["mode"] = (
            "single"
            if getattr(self, "rb_single", None) and self.rb_single.isChecked()
            else "batch"
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

    # --------------------------- UI helpers --------------------------- #
    def update_select_button_text(self) -> None:
        """
        Ensure the file/folder select button(s) reflect the active mode.
        Safe if widgets are missing; no behavior changes.
        """
        try:
            mode = "Batch"
            if hasattr(self, "file_mode") and callable(getattr(self.file_mode, "get", None)):
                mode = self.file_mode.get()

            if mode == "Single":
                # Prefer file button text when present
                btn_file = getattr(self, "btn_select_input_file", None)
                if btn_file and hasattr(btn_file, "setText"):
                    btn_file.setText("Select EEG File…")
                # If only a generic button exists, set that
                btn_generic = getattr(self, "btn_select_input", None)
                if btn_generic and hasattr(btn_generic, "setText"):
                    btn_generic.setText("Select EEG File…")
            else:
                # Batch
                btn_folder = getattr(self, "btn_select_input_folder", None)
                if btn_folder and hasattr(btn_folder, "setText"):
                    btn_folder.setText("Select Data Folder…")
                btn_generic = getattr(self, "btn_select_input", None)
                if btn_generic and hasattr(btn_generic, "setText"):
                    btn_generic.setText("Select Data Folder…")
        except Exception as e:
            self.log(f"update_select_button_text failed: {e}", level=logging.WARNING)

    # Alias for ui_main.py which calls the underscored name
    def _update_select_button_text(self) -> None:
        self.update_select_button_text()

    # --------------------------- mode + detect --------------------------- #
    def _on_mode_changed(self, mode: str) -> None:
        """
        Adapter for UI radio buttons (wired in ui_main.py).
        Keeps legacy-compatible mode string and toggles any present selectors.
        """
        mode_norm = (mode or "").strip().lower()
        if mode_norm not in ("single", "batch"):
            self.log(f"Unknown mode '{mode}'; ignoring.", level=logging.WARNING)
            return

        # Maintain legacy-readable getter that some helpers expect
        pretty = "Single" if mode_norm == "single" else "Batch"
        self.file_mode = SimpleNamespace(get=lambda p=pretty: p)
        self.log(f"File mode changed to {pretty}")

        # Opportunistically toggle common widgets if they exist; no-ops otherwise
        def _safe_set_enabled(obj_name: str, enabled: bool) -> None:
            w = getattr(self, obj_name, None)
            if w and hasattr(w, "setEnabled"):
                try:
                    w.setEnabled(enabled)
                except Exception:
                    pass

        # Typical names used in our UI builder; harmless if missing
        is_single = (mode_norm == "single")
        _safe_set_enabled("btn_select_input_file", is_single)
        _safe_set_enabled("le_input_file", is_single)
        _safe_set_enabled("btn_select_input_folder", not is_single)
        _safe_set_enabled("le_input_folder", not is_single)

        self.update_select_button_text()

        # Optional label feedback
        lbl = getattr(self, "lbl_mode", None)
        if isinstance(lbl, QLabel):
            try:
                lbl.setText(f"Mode: {pretty}")
            except Exception:
                pass

    # ---------- legacy mixin hook: enable/disable controls during run ---------- #
    def _set_controls_enabled(self, enabled: bool) -> None:
        """
        Required by Main_App.Legacy_App.processing_utils.
        Disables common inputs while a run is active. No-ops if widgets missing.
        """
        self.busy = not enabled

        def _safe_enable(name: str) -> None:
            w = getattr(self, name, None)
            if w and hasattr(w, "setEnabled"):
                try:
                    w.setEnabled(enabled)
                except Exception:
                    self.log(f"_set_controls_enabled: could not toggle {name}", level=logging.DEBUG)

        # Common controls (exists-if-present)
        for n in (
            "btn_start",
            "btn_select_input_file", "le_input_file",
            "btn_select_input_folder", "le_input_folder",
            "btn_add_event", "btn_detect",
            "cb_loreta",
            "btn_create_project", "btn_open_project",
        ):
            _safe_enable(n)

        # Event-map row edits/buttons (query per-type; Qt doesn't accept tuple here)
        for row in getattr(self, "event_rows", []):
            try:
                for child in row.findChildren(QLineEdit):
                    child.setEnabled(enabled)
                for child in row.findChildren(QAbstractButton):
                    child.setEnabled(enabled)
            except Exception:
                # Be quiet but safe
                self.log("_set_controls_enabled: child toggle failed", level=logging.DEBUG)

    def detect_trigger_ids(self) -> None:
        """
        Non-blocking placeholder so the Detect button works without crashing.
        If/when a public legacy API is exposed for trigger detection, call it here.
        """
        try:
            # If we already have any event-map entries, just inform the user.
            has_entries = any(
                bool(edits.get("label").get() and edits.get("id").get())
                for edits in self.event_map_entries
            )
            if has_entries:
                self.log("Detect: event map already has entries; no changes made.")
                QMessageBox.information(self, "Detect Triggers",
                                        "Event map already contains entries.\nEdit as needed and Save Project.")
                return
            # Graceful notice; real detection can be wired to a worker later.
            self.log("Detect: auto trigger detection not available in Qt UI yet.")
            QMessageBox.information(self, "Detect Triggers",
                                    "Automatic trigger detection is not available yet in the Qt interface.\n"
                                    "Please enter event labels/IDs manually for now.")
        except Exception as e:
            self.log(f"Detect triggers failed: {e}", level=logging.ERROR)
            QMessageBox.warning(self, "Detect Triggers", f"Could not run detection: {e}")

# ----------------------------------------------------------------------
def main() -> None:
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    app.exec()


if __name__ == "__main__":
    main()
