# main_window.py
from __future__ import annotations
from Main_App.PySide6_App.workers.processing_worker import PostProcessWorker
from Main_App.PySide6_App.utils.op_guard import OpGuard
from Main_App.Performance.mp_env import set_blas_threads_single_process
import logging
import os
import queue
import subprocess
import sys
import re
from Main_App.Legacy_App.post_process import post_process as _legacy_post_process
from typing import Callable
from datetime import datetime
from pathlib import Path
from types import MethodType, SimpleNamespace, ModuleType
from collections import deque

# Qt / PySide6
from PySide6.QtCore import QObject, QTimer, Signal, QThread, Slot
from PySide6.QtGui import QFont, QIntValidator, QCloseEvent, QAction  # noqa: F401
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

# ----------------------------------------------------------------------
# Canonical Qt messagebox adapters
# ----------------------------------------------------------------------

logger = logging.getLogger(__name__)
# Keep this module quiet unless the app configures handlers; avoids accidental console output.
logger.addHandler(logging.NullHandler())

# ----------------------------------------------------------------------
# Canonical Qt messagebox adapters (used for both tk and legacy debug utils)
# ----------------------------------------------------------------------

def _qt_showerror(title, message, **options):
    parent = QApplication.activeWindow()
    QMessageBox.critical(parent, title, message)


def _qt_showwarning(title, message, **options):
    parent = QApplication.activeWindow()
    QMessageBox.warning(parent, title, message)


def _qt_showinfo(title, message, **options):
    parent = QApplication.activeWindow()
    # If a run just finished, only show the "Processing Complete" info dialog
    # when the window reports a successful export (set by our post-process wrapper).
    if str(title).lower().startswith("processing complete"):
        ok = getattr(parent, "_last_job_success", True)
        if not ok:
            # Downgrade to a warning with a clearer message and skip the legacy text.
            QMessageBox.warning(
                parent,
                "Processing Finished",
                "No Excel files were generated. Check the log for details.",
            )
            return
    QMessageBox.information(parent, title, message)

def _qt_askyesno(title, message, **options):
    parent = QApplication.activeWindow()
    result = QMessageBox.question(
        parent, title, message,
        QMessageBox.Yes | QMessageBox.No,
        QMessageBox.No
    )
    return result == QMessageBox.Yes


# Provide a tkinter.messagebox shim without importing Tk
_tk_module = ModuleType("tkinter")
_tk_msg_module = ModuleType("tkinter.messagebox")
_tk_msg_module.showerror = _qt_showerror
_tk_msg_module.showwarning = _qt_showwarning
_tk_msg_module.showinfo = _qt_showinfo
_tk_msg_module.askyesno = _qt_askyesno
_tk_module.messagebox = _tk_msg_module
_tk_module.END = "end"
sys.modules.setdefault("tkinter", _tk_module)
sys.modules["tkinter.messagebox"] = _tk_msg_module


# Import after stubbing tkinter to avoid loading the real toolkit
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

from Main_App.PySide6_App.utils.op_guard import OpGuard
from Main_App.PySide6_App.workers.processing_worker import PostProcessWorker

# Route legacy debug utils through Qt adapters
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
        self._last_job_success: bool = False

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
    * Queue polling uses a QTimer to keep the GUI responsive while the
      worker thread runs.
    """

    # Polling strategy:
    # - Baseline periodic timer at 100 ms keeps idle CPU low.
    # - After a burst (messages were processed), schedule a quick one-shot
    #   to finish draining without waiting a full baseline interval.
    _POLL_INTERVAL_MS = 100  # baseline; do not lower below 100 ms
    _BURST_FOLLOWUP_MS = 16  # ~60 Hz only after activity
    _IDLE_FOLLOWUP_MS = 50  # moderate follow-up when no messages

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
        # Poll the worker queue so the GUI stays responsive
        self._processing_timer = QTimer(self)
        self._processing_timer.setSingleShot(False)
        self._processing_timer.timeout.connect(self._periodic_queue_check)

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
        # Parallel processing configuration
        self.parallel_mode = "process"
        self.max_workers = max(1, (os.cpu_count() or 2) - 1)
        self._n_jobs_ignored_logged = False
        self._mp = None

        # Build nav + menus
        init_sidebar(self)
        select_projects_root(self)
        init_file_menu(self)

        # Status bar
        status = QStatusBar(self)
        self.setStatusBar(status)
        status.showMessage(f"FPVS Toolbox v{FPVS_TOOLBOX_VERSION}")

        # --- Busy spinner (ENLARGED) ---
        # Make the status bar taller & add padding
        self.statusBar().setSizeGripEnabled(False)
        self.statusBar().setMinimumHeight(36)  # ~36 px tall
        self.statusBar().setContentsMargins(8, 0, 8, 0)

        # Larger animated text spinner
        self._busyFrames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self._busyIdx = 0
        self._busyTimer = QTimer(self)
        self._busyTimer.setInterval(120)  # ~8 FPS
        self._busyTimer.timeout.connect(self._tick_busy)

        self._busyLabel = QLabel("")  # lives in the status bar
        # bump font size (keeps current family/theme)
        _big = self._busyLabel.font()
        _big.setPointSize(max(_big.pointSize() + 4, 14))  # +4pt or at least 14pt
        self._busyLabel.setFont(_big)
        # add padding so it doesn't feel cramped
        self._busyLabel.setStyleSheet("padding: 0 10px;")
        self._busyLabel.setVisible(False)
        self.statusBar().addPermanentWidget(self._busyLabel)
        # --------------------------------

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

        # Worker management
        self._post_worker = None
        self._post_thread = None
        self._start_guard = OpGuard()

        # Flags/vars the mixin expects
        self.run_loreta_var = SimpleNamespace(get=lambda: self.cb_loreta.isChecked())
        self.save_fif_var = SimpleNamespace(get=lambda: True)
        self.save_folder_path = SimpleNamespace(get=lambda: "", set=lambda v: None)
        self.file_mode = SimpleNamespace(get=lambda: "Batch")
        self.file_type = SimpleNamespace(set=lambda v: None)

        # Legacy mixin uses Tk's .after(); we emulate it with QTimer
        self._after_timers: dict[int, QTimer] = {}
        self._queue_job_id: int | None = None
        self.post_process = MethodType(MainWindow._export_with_post_process, self)
        self._post_thread = None
        self._post_worker: PostProcessWorker | None = None
        self._post_backlog: deque[tuple[str, dict, list[str]]] = deque()
        self._pending_finalize = False
        self._op_guard = OpGuard()
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
        """
        Begin a processing run. In 'process' mode we use a per-file process pool;
        in 'single' mode we defer to the legacy path. Spinner hooks included.
        """
        if not self._start_guard.start():
            QMessageBox.warning(self, "Busy", "Processing already started")
            return

        # Reset run state
        self._last_job_success = False
        self._run_active = True
        self._snr_tick = 0

        # Start spinner immediately (if present)
        try:
            if hasattr(self, "_busy_start"):
                self._busy_start()
        except Exception:
            pass

        # Default: timer on; we'll stop it in process mode
        if not self._processing_timer.isActive():
            self._processing_timer.start(self._POLL_INTERVAL_MS)

        try:
            if not getattr(self, "_n_jobs_ignored_logged", False):
                logger.info("n_jobs is ignored in this version; using parallel_mode=%s", self.parallel_mode)
                self._n_jobs_ignored_logged = True

            # Pull project overrides if present
            if getattr(self, "currentProject", None):
                opts = getattr(self.currentProject, "options", {})
                self.parallel_mode = opts.get("parallel_mode", getattr(self, "parallel_mode", "process"))
                self.max_workers = opts.get("max_workers", getattr(self, "max_workers", None))

            # ---------- Process mode (multiprocessing) ----------
            if self.parallel_mode == "process":
                # Do NOT kick legacy path. We stop the legacy poll timer here.
                if self._processing_timer.isActive():
                    self._processing_timer.stop()

                if not self._validate_inputs():
                    try:
                        if hasattr(self, "_busy_stop"): self._busy_stop()
                    except Exception:
                        pass
                    self._run_active = False
                    self._start_guard.end()
                    return

                self._set_controls_enabled(False)
                self._max_progress = len(self.data_paths)
                if hasattr(self, "progress_bar"):
                    self.progress_bar.setRange(0, 100)
                    self.progress_bar.setValue(0)
                self._processed_count = 0
                self.busy = True

                from pathlib import Path
                from Main_App.PySide6_App.workers.mp_runner_bridge import MpRunnerBridge

                project_root = Path(self.currentProject.project_root)
                save_folder = Path(self.save_folder_path.get())
                files = [Path(p) for p in self.data_paths]
                settings = self.validated_params.copy()
                event_map = settings.pop("event_id_map", {})

                self._mp = MpRunnerBridge(self)

                # Smooth progress if available
                self._mp.progress.connect(
                    lambda pct: (self._animate_progress_to(pct / 100.0)
                                 if hasattr(self, "_animate_progress_to")
                                 else self.progress_bar.setValue(int(pct)))
                )
                self._mp.error.connect(
                    lambda m: (
                        (self._busy_stop() if hasattr(self, "_busy_stop") else None),
                        QMessageBox.critical(self, "Processing Error", m),
                        setattr(self, "_run_active", False),
                        self._start_guard.end(),
                    )
                )
                self._mp.finished.connect(
                    lambda _p: (
                        (self._busy_stop() if hasattr(self, "_busy_stop") else None),
                        self._finalize_processing(True),
                        setattr(self, "_run_active", False),
                        self._start_guard.end(),
                    )
                )

                self._mp.start(
                    project_root=project_root,
                    data_files=files,
                    settings=settings,
                    event_map=event_map,
                    save_folder=save_folder,
                    max_workers=self.max_workers,
                )
                return  # IMPORTANT: do not fall through to legacy

            # ---------- Single mode (legacy path) ----------
            from Main_App.Performance.mp_env import set_blas_threads_single_process
            set_blas_threads_single_process()
            if not self._processing_timer.isActive():
                self._processing_timer.start(self._POLL_INTERVAL_MS)
            super().start_processing()

        except Exception as e:
            logger.exception(e)
            QMessageBox.critical(self, "Processing Error", str(e))
            try:
                if hasattr(self, "_busy_stop"): self._busy_stop()
            except Exception:
                pass
            self._run_active = False
            self._start_guard.end()

    # --- Busy spinner helpers ---
    def _busy_start(self) -> None:
        if not self._busyTimer.isActive():
            self._busyIdx = 0
            self._busyLabel.setText(f"{self._busyFrames[0]} Processing…")
            self._busyLabel.setVisible(True)
            self._busyTimer.start()

    def _busy_stop(self) -> None:
        if self._busyTimer.isActive():
            self._busyTimer.stop()
        self._busyLabel.setVisible(False)

    def _tick_busy(self) -> None:
        self._busyIdx = (self._busyIdx + 1) % len(self._busyFrames)
        self._busyLabel.setText(f"{self._busyFrames[self._busyIdx]} Processing…")

    # --------------------------------

    def _on_processing_finished(self, _payload: dict | None = None) -> None:
        # Process-mode completion
        self._busy_stop()
        self._finalize_processing(True)
        self._run_active = False
        self._start_guard.end()

    def _on_processing_error(self, message: str) -> None:
        # Process-mode error
        self._busy_stop()
        QMessageBox.critical(self, "Processing Error", message)

    def _finalize_processing(self, success: bool) -> None:  # type: ignore[override]
        """Ensure spinner stops for the legacy (single) path, then defer."""
        try:
            self._busy_stop()
        except Exception:
            pass
        super()._finalize_processing(success)

    @Slot()
    def _periodic_queue_check(self) -> None:
        if not self._run_active:
            return

        processed = 0
        while processed < 50:
            try:
                msg = self.gui_queue.get_nowait()
            except queue.Empty:
                break

            processed += 1
            t = msg.get("type")
            if t == "log":
                self.log(msg.get("message", ""))
            elif t == "progress":
                self._processed_count = msg["value"]
                frac = msg["value"] / self._max_progress if self._max_progress else 0
                self._animate_progress_to(frac)
            elif t == "post":
                fname = msg["file"]
                epochs_dict = msg["epochs_dict"]
                labels = msg["labels"]
                self._start_post_worker(fname, epochs_dict, labels)
            elif t == "error":
                self.log("!!! THREAD ERROR: " + msg["message"])
                if (tb := msg.get("traceback")):
                    self.log(tb)
                self._finalize_processing(False)
                return
            elif t == "done":
                if self._post_worker or self._post_backlog:
                    self._pending_finalize = True
                else:
                    self._finalize_processing(True)
                return

        # Adaptive follow-up: quicker after activity, moderate when idle
        delay = self._BURST_FOLLOWUP_MS if processed else self._IDLE_FOLLOWUP_MS
        QTimer.singleShot(delay, self._periodic_queue_check)

    def _start_post_worker(self, file_name: str, epochs_dict: dict, labels: list[str]) -> None:
        """Queue-aware launcher for post-processing jobs."""
        payload = (file_name, epochs_dict, labels)

        # If a worker is active, enqueue and return
        if self._post_thread and self._post_thread.isRunning():
            self._post_backlog.append(payload)
            base = os.path.basename(str(file_name))
            self.log(f"Queued post-processing for {base}")
            return

        save_folder = (
            self.save_folder_path.get()
            if hasattr(self.save_folder_path, "get")
            else self.save_folder_path
        )

        worker = PostProcessWorker(
            file_name,
            epochs_dict,
            labels,
            save_folder=save_folder,
            data_paths=[file_name],
            settings=getattr(self, "settings", None),
            logger=lambda m: self.gui_queue.put({"type": "log", "message": m}),
        )

        thread = QThread(self)
        worker.moveToThread(thread)
        worker.error.connect(self._on_worker_error)
        worker.finished.connect(self._on_post_finished)   # will drain backlog
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._post_worker = worker
        self._post_thread = thread
        thread.start()

    def _on_worker_error(self, message: str) -> None:
        self.log(message, level=logging.ERROR)

    def _on_post_finished(self, payload: dict | None = None) -> None:
        if payload:
            for msg in payload.get("logs", []):
                self.log(msg)

        # Clear current worker
        self._post_worker = None
        self._post_thread = None

        # Start next queued job, if any
        if self._post_backlog:
            next_file, next_epochs, next_labels = self._post_backlog.popleft()
            self._start_post_worker(next_file, next_epochs, next_labels)
            return

        # If processing thread already signaled "done", finalize now
        if getattr(self, "_pending_finalize", False):
            self._pending_finalize = False
            self._finalize_processing(True)

    def _finalize_processing(self, *args, **kwargs) -> None:
        self._run_active = False
        self._start_guard.end()
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
        opts = getattr(self.currentProject, "options", {})
        self.parallel_mode = opts.get("parallel_mode", self.parallel_mode)
        self.max_workers = opts.get("max_workers", self.max_workers)
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

    def _export_with_post_process(self, labels: list[str]) -> None:
        """
        Run legacy post_process then decide whether *new* Excel files appeared.
        Treat "no new files" as a warning (not fatal) because files may be overwritten or stored in subfolders.
        """
        excel_dir = self.save_folder_path.get() if hasattr(self.save_folder_path, "get") else ""
        if not excel_dir or not Path(excel_dir).is_dir():
            self.gui_queue.put({"type": "error", "message": f"Excel output folder not found:\n{excel_dir}"})
            self._last_job_success = False
            return

        out_path = Path(excel_dir)

        def _excel_snapshot() -> tuple[int, float]:
            count = 0
            latest_mtime = 0.0
            for p in out_path.rglob("*.xls*"):
                try:
                    st = p.stat().st_mtime
                except OSError:
                    continue
                count += 1
                latest_mtime = max(latest_mtime, st)
            return count, latest_mtime

        original_log = self.log

        def queue_log(message: str, level: int = logging.INFO) -> None:
            self.gui_queue.put({"type": "log", "message": message})
            logger.log(level, message)

        self.log = queue_log

        pre_count, pre_mtime = _excel_snapshot()

        try:
            _legacy_post_process(self, labels)

            post_count, post_mtime = _excel_snapshot()
            created = post_count - pre_count
            changed = post_mtime > pre_mtime

            if created > 0 or changed:
                self._last_job_success = bool(self._last_job_success or True)
                msg = f"Excel export completed ({max(created, 0)} new file(s){' or overwrites' if created == 0 and changed else ''})."
                self.gui_queue.put({"type": "log", "message": msg})
            else:
                self.gui_queue.put({
                    "type": "log",
                    "message": "Post-process finished but no NEW Excel files were detected. "
                               "If files were overwritten or saved elsewhere, this can be expected.",
                })
        except Exception as err:
            logger.exception("Excel export failed")
            self._last_job_success = False
            self.gui_queue.put({"type": "error", "message": str(err)})
        finally:
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

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._post_worker and self._post_thread:
            self._post_worker.stop()
            self._post_thread.quit()
            self._post_thread.wait(2000)
        super().closeEvent(event)

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
