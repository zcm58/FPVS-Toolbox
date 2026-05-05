# main_window.py
from __future__ import annotations

# ruff: noqa: E402

import logging
import os
import queue
import subprocess
import sys
from Main_App.Shared.post_process import post_process as _shared_post_process
from Main_App.PySide6_App.utils.theme import apply_fpvs_theme
from typing import Callable
from datetime import datetime
from pathlib import Path
from types import MethodType, SimpleNamespace
from collections import deque

import psutil

# Qt / PySide6
from PySide6.QtCore import QObject, QEvent, QEasingCurve, QPropertyAnimation, QTimer, Signal, QThread, Slot, Qt
from PySide6.QtGui import QFont, QCloseEvent, QAction, QShowEvent  # noqa: F401
from PySide6.QtWidgets import (
    QApplication,
    QAbstractButton,
    QGraphicsOpacityEffect,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QFileDialog,
    QStatusBar,
    QWidget,
)

# ----------------------------------------------------------------------
# Canonical Qt messagebox adapters
# ----------------------------------------------------------------------

logger = logging.getLogger(__name__)
# Keep this module quiet unless the app configures handlers; avoids accidental console output.
logger.addHandler(logging.NullHandler())

import config
from Main_App.Shared.processing_mixin import ProcessingMixin
from Main_App.Shared.settings_manager import SettingsManager
from Main_App.projects import Project
from Main_App.PySide6_App.Backend.processing_controller import (
    _animate_progress_to,
    prepare_batch_files,
)
from Main_App.projects.project_manager import select_projects_root
from Main_App.projects.preprocessing_settings import (
    normalize_preprocessing_settings,
    PREPROCESSING_CANONICAL_KEYS,
)
from Main_App.workers.mp_env import (
    compute_effective_max_workers,
    get_ram_tier_recommendation,
)
from Tools.Average_Preprocessing.New_PySide6.main_window import (
    AdvancedAveragingWindow,
)
from Tools.Stats import StatsWindow as PysideStatsWindow
from config import FPVS_TOOLBOX_VERSION
from . import update_manager
from . import event_map
from .file_menu import init_file_menu
from .settings_panel import SettingsDialog
from .sidebar import init_sidebar
from .ui_main import init_ui
from Main_App.gui import project_workflows
from Main_App.gui import processing_workflows
from Main_App.gui import post_export_workflows
from Main_App.gui.post_export_workflows import (
    excel_snapshot as _excel_snapshot,
    should_show_no_excel_popup as _should_show_no_excel_popup,
)
from Main_App.gui.project_workflows import (
    WINDOWS_FORBIDDEN_CONDITION_CHARS_TEXT,
    _illegal_condition_chars,
)

from Main_App.PySide6_App.utils.op_guard import OpGuard
from Main_App.workers.processing_worker import PostProcessWorker

STATS_TOOL_UNDER_DEVELOPMENT_WARNING = (
    "The Statistics Tool is currently under development. Certain features, like "
    "multigroup analysis, are not currently functional. Single Group Analysis mode "
    "does work as expected. Future updates will fix the Statistics Tool and add "
    "between group analysis."
)


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

    # ---------- legacy mixin hook: enable/disable controls during run ---------- #
    def _set_controls_enabled(self, enabled: bool) -> None:
        """
        Required by Main_App.Shared.processing_mixin.
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

        # Common controls (exists-if-present).
        # Note: we intentionally do NOT disable the main Start/Stop button here.
        for n in (
                "btn_select_input_file", "le_input_file",
                "btn_select_input_folder", "le_input_folder",
                "btn_add_event", "btn_add_row", "btn_detect",
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


class MainWindow(QMainWindow, ProcessingMixin):
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
        # Local, relative import avoids circulars and path issues
        from .update_manager import cleanup_old_executable, check_for_updates_on_launch
        cleanup_old_executable()

        self.settings = SettingsManager()

        # Ensure legacy appearance mode stays in sync with the PySide6 theme.
        # PySide6 now always uses a fixed light theme, so we normalize the
        # stored value to "Light" for any legacy consumers that still read it.
        try:
            current_mode = self.settings.get("appearance", "mode", "System")
            if current_mode != "Light":
                self.settings.set("appearance", "mode", "Light")
                self.settings.save()
        except Exception as exc:
            logger.debug("Unable to persist appearance.mode=Light: %s", exc)

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
        self._bind_existing_event_map_rows()
        self._launch_reveal_done = False
        self._launch_reveal_animation: QPropertyAnimation | None = None
        self._launch_reveal_effect: QGraphicsOpacityEffect | None = None
        self._launch_reveal_target: QWidget | None = None

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
        self._cancel_requested = False
        self._suppress_completion_dialogs = False

        # Parallel processing configuration
        self.parallel_mode = "process"
        default_cpu = os.cpu_count() or 1
        default_ram = psutil.virtual_memory().total
        self.max_workers = compute_effective_max_workers(default_ram, default_cpu, None)
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
        if hasattr(self, "landing_version_label"):
            self.landing_version_label.setText(f"FPVS Toolbox v{FPVS_TOOLBOX_VERSION}")

        # --- Busy spinner (ENLARGED) ---
        self.statusBar().setSizeGripEnabled(False)
        self.statusBar().setMinimumHeight(36)
        self.statusBar().setContentsMargins(8, 0, 8, 0)

        self._busyFrames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self._busyIdx = 0
        self._busyTimer = QTimer(self)
        self._busyTimer.setInterval(120)
        self._busyTimer.timeout.connect(self._tick_busy)

        self._busyLabel = QLabel("")
        _big = self._busyLabel.font()
        _big.setPointSize(max(_big.pointSize() + 4, 14))
        self._busyLabel.setFont(_big)
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
        # PySide6 now enforces a fixed light theme regardless of OS settings.
        self.log("Appearance Mode: Light (PySide6 fixed light theme)")
        # Announce the active preprocessor (visibility only)
        logger.info(
            "Using Main App preprocessing module: Main_App.processing.preprocess.perform_preprocessing"
        )

        self.log("Preprocessor: Main App processing module active")

        # Wire Start/Stop button – handler decides whether to start or stop
        if hasattr(self, "btn_start"):
            self.btn_start.clicked.connect(self._on_start_stop_clicked)

        # Wire Single-file selectors (if present in UI)
        if hasattr(self, "btn_select_input_file"):
            try:
                self.btn_select_input_file.clicked.connect(self.select_single_file)
            except Exception:
                pass
        if hasattr(self, "btn_select_input_folder"):
            try:
                self.btn_select_input_folder.clicked.connect(self.edit_project_settings)
            except Exception:
                pass
        if hasattr(self, "le_input_file"):
            try:
                self.le_input_file.textChanged.connect(self._update_start_enabled)
            except Exception:
                pass

        # Compatibility fields used by ProcessingMixin
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
        self.save_fif_var = SimpleNamespace(get=lambda: False)
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
        self._selected_bdf: str | None = None
        self._processing_notice = None
        self._event_row_return_in_progress = False
        self._run_had_successful_export = False
        self._run_excel_output_root = ""
        self._run_excel_snapshot_before: dict[str, tuple[int, int]] = {}

        # Auto update check on launch: prompt only if update exists
        QTimer.singleShot(1000, lambda: check_for_updates_on_launch(self))

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if not self._launch_reveal_done:
            self._launch_reveal_done = True
            QTimer.singleShot(0, self._start_launch_reveal)

    def _launch_reveal_widget(self) -> QWidget | None:
        if not hasattr(self, "stacked"):
            return None
        if self.stacked.currentWidget() is getattr(self, "landing_page", None):
            return getattr(self, "landing_card", None)
        return getattr(self, "page1_container", None)

    def _start_launch_reveal(self) -> None:
        target = self._launch_reveal_widget()
        if target is None or not target.isVisible():
            return

        effect = QGraphicsOpacityEffect(target)
        effect.setOpacity(0.0)
        target.setGraphicsEffect(effect)

        animation = QPropertyAnimation(effect, b"opacity", self)
        animation.setDuration(180)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.OutCubic)
        animation.finished.connect(self._finish_launch_reveal)

        self._launch_reveal_target = target
        self._launch_reveal_effect = effect
        self._launch_reveal_animation = animation
        animation.start()

    def _finish_launch_reveal(self) -> None:
        if self._launch_reveal_target is not None:
            self._launch_reveal_target.setGraphicsEffect(None)
        self._launch_reveal_target = None
        self._launch_reveal_effect = None
        self._launch_reveal_animation = None

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

    def _show_processing_started_notice(self) -> None:
        existing = getattr(self, "_processing_notice", None)
        if existing is not None:
            try:
                existing.close()
            except Exception:
                pass
            finally:
                self._processing_notice = None

        box = QMessageBox(self)
        box.setWindowTitle("Processing Started")
        box.setIcon(QMessageBox.Information)
        box.setText(
            "Processing Data has begun. Please be patient - your computer may "
            "become slow or unresponsive until processing is complete."
        )
        box.addButton("Dismiss", QMessageBox.AcceptRole)
        box.setWindowModality(Qt.NonModal)

        def _clear_notice(_: int | None = None) -> None:
            if getattr(self, "_processing_notice", None) is box:
                self._processing_notice = None

        box.finished.connect(_clear_notice)

        def _auto_close() -> None:
            if getattr(self, "_processing_notice", None) is box and box.isVisible():
                box.close()

        self._processing_notice = box
        box.show()
        QTimer.singleShot(10000, _auto_close)

    # -------------------------- processing -------------------------- #

    def stop_processing(self) -> None:
        processing_workflows.stop_processing(self)

    # -------------------------- processing -------------------------- #
    def start_processing(self) -> None:
        processing_workflows.start_processing(self, log=logger)

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

    def _on_processing_finished(self, payload: dict | None = None) -> None:
        processing_workflows.on_processing_finished(self, payload)

    def _on_processing_error(self, message: str) -> None:
        processing_workflows.on_processing_error(self, message)

    @Slot()
    def _periodic_queue_check(self) -> None:
        processing_workflows.periodic_queue_check(self)

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
        post_export_workflows.on_post_finished(self, payload, log=logger)

    def _refresh_run_excel_success_from_disk(self) -> None:
        post_export_workflows.refresh_run_excel_success_from_disk(self)

    def _finalize_processing(self, *args, **kwargs) -> None:
        processing_workflows.finalize_processing(
            self,
            *args,
            parent_finalize=super()._finalize_processing,
            **kwargs,
        )

    # ------------------------ Tk-style scheduling ------------------------ #
    def after(self, delay_ms: int, callback: Callable[[], None]) -> int:
        """Schedule a callback with QTimer.singleShot.
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

        # File selection rules differ in Single vs Batch
        mode_now = (self.file_mode.get() if hasattr(self, "file_mode") else "Batch")
        if mode_now == "Single":
            # In single mode, require an explicit .bdf selection
            if not self.data_paths:
                QMessageBox.warning(self, "No File Selected", "Please choose one .bdf file first.")
                return False

        # Batch: always build the file list from the project definition
        # (multi-group aware via prepare_batch_files). This ensures that
        # all .bdf files from all configured group input folders are used.
        if mode_now == "Batch":
            file_paths = prepare_batch_files(self.currentProject)
            if not file_paths:
                QMessageBox.warning(
                    self,
                    "No Data",
                    "No .bdf files found in the configured input folder(s).",
                )
                return False
            self.data_paths = [str(p) for p in file_paths]
            self.log(f"Processing: {len(self.data_paths)} file(s) selected.")

        # Single: if we somehow have no data_paths at this point, fall back to
        # the legacy input_folder glob (defensive-only; normal flow requires an
        # explicit file selection above).
        elif not self.data_paths:
            input_dir = Path(self.currentProject.input_folder)
            if not input_dir.is_dir():
                QMessageBox.critical(self, "Input Folder Missing", str(input_dir))
                return False
            bdf_files = sorted(str(p) for p in input_dir.glob("*.bdf"))
            if not bdf_files:
                QMessageBox.warning(
                    self,
                    "No Data",
                    "No .bdf files found in the input folder.",
                )
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
        debug_enabled = bool(self.settings.debug_enabled()) if hasattr(self, "settings") else False
        project_preproc = getattr(self.currentProject, "preprocessing", {}) or {}
        project_snapshot = {key: project_preproc.get(key) for key in PREPROCESSING_CANONICAL_KEYS}
        settings_snapshot = None
        if hasattr(self, "settings") and hasattr(self.settings, "config"):
            settings_snapshot = {}
            preproc_options = (
                "low_pass",
                "high_pass",
                "downsample",
                "epoch_start",
                "reject_thresh",
                "epoch_end",
                "ref_chan1",
                "ref_chan2",
                "max_idx_keep",
                "max_bad_chans",
            )
            for opt in preproc_options:
                if self.settings.config.has_option("preprocessing", opt):
                    settings_snapshot[opt] = self.settings.get("preprocessing", opt, "")
            if self.settings.config.has_option("stim", "channel"):
                settings_snapshot["stim_channel"] = self.settings.get("stim", "channel", "")
        dialog_snapshot = None
        if getattr(self, "_settings_dialog", None):
            try:
                dialog_preproc_keys = (
                    "low_pass",
                    "high_pass",
                    "downsample",
                    "epoch_start",
                    "reject_thresh",
                    "epoch_end",
                    "ref_chan1",
                    "ref_chan2",
                    "max_idx_keep",
                    "max_bad_chans",
                )
                dialog_snapshot = {
                    key: edit.text()
                    for key, edit in zip(dialog_preproc_keys, self._settings_dialog.preproc_edits)
                }
            except Exception:
                dialog_snapshot = {"error": "unavailable"}
        if debug_enabled:
            logger.debug(
                "PREPROC_SOURCE_SNAPSHOT project=%s settings=%s dialog=%s",
                project_snapshot,
                settings_snapshot,
                dialog_snapshot,
            )
        else:
            logger.debug(
                "PREPROC_SOURCE_SNAPSHOT project_keys=%s settings_keys=%s dialog_present=%s",
                list(project_snapshot.keys()),
                list(settings_snapshot.keys()) if settings_snapshot else [],
                bool(dialog_snapshot),
            )
        fp_hp = params.get("high_pass")
        fp_lp = params.get("low_pass")
        fp_ds = params.get("downsample")
        fp_rz = params.get("reject_thresh")
        fp_r1 = params.get("ref_channel1")
        fp_r2 = params.get("ref_channel2")
        fp_stim = params.get("stim_channel")
        validated_fingerprint = (
            f"hp={fp_hp}|lp={fp_lp}|ds={fp_ds}|rz={fp_rz}|"
            f"ref={fp_r1},{fp_r2}|stim={fp_stim}"
        )
        logger.debug("PREPROC_FINGERPRINT_VALIDATED %s", validated_fingerprint)
        self._preproc_fingerprint_validated = validated_fingerprint

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
        normalized = normalize_preprocessing_settings(self.currentProject.preprocessing)
        logger.debug(
            "NORMALIZED_PREPROC_SNAPSHOT file_mode=%s normalized.high_pass=%r "
            "normalized.low_pass=%r normalized.downsample=%r",
            getattr(self, "file_mode", None).get() if hasattr(self, "file_mode") else "UNKNOWN",
            normalized.get("high_pass"),
            normalized.get("low_pass"),
            normalized.get("downsample"),
        )

        # Event map from UI rows → {label: int_id}
        event_map: dict[str, int] = {}
        for row in self.event_rows:
            edits = row.findChildren(QLineEdit)
            if len(edits) >= 2:
                label_edit = edits[0]
                label = label_edit.text().strip()
                ident = edits[1].text().strip()
                if label:
                    illegal_chars = _illegal_condition_chars(label)
                    if illegal_chars:
                        bad = " ".join(illegal_chars)
                        QMessageBox.warning(
                            self,
                            "Invalid Condition Name",
                            (
                                "Condition names cannot contain characters that are invalid for "
                                "Windows file/folder names.\n\n"
                                f"Condition: {label}\n"
                                f"Illegal character(s): {bad}\n\n"
                                "Please rename this condition using only allowed characters.\n"
                                f"Not allowed: {WINDOWS_FORBIDDEN_CONDITION_CHARS_TEXT}"
                            ),
                        )
                        try:
                            label_edit.setFocus()
                            label_edit.selectAll()
                        except Exception:
                            pass
                        return None
                if label and ident.isdigit():
                    event_map[label] = int(ident)
        if not event_map:
            QMessageBox.warning(self, "No Events", "Please add at least one event map entry.")
            return None

        epoch_start = float(normalized.get("epoch_start_s", -1.0))
        epoch_end = float(normalized.get("epoch_end_s", 125.0))
        if epoch_end <= epoch_start:
            QMessageBox.warning(
                self,
                "Invalid Epoch Window",
                "Epoch end must be greater than epoch start.",
            )
            return None

        stim_channel = normalized.get("stim_channel") or config.DEFAULT_STIM_CHANNEL
        try:
            base_freq = float(self.settings.get("analysis", "base_freq", "6.0"))
        except Exception:
            base_freq = 6.0
        try:
            oddball_freq = float(
                self.settings.get("analysis", "oddball_freq", str(config.DEFAULT_ODDBALL_FREQ))
            )
        except Exception:
            oddball_freq = float(config.DEFAULT_ODDBALL_FREQ)
        try:
            bca_upper_limit = float(
                self.settings.get(
                    "analysis",
                    "bca_upper_limit",
                    str(config.DEFAULT_BCA_UPPER_LIMIT),
                )
            )
        except Exception:
            bca_upper_limit = float(config.DEFAULT_BCA_UPPER_LIMIT)

        params = {
            "low_pass": float(normalized.get("low_pass")),
            "high_pass": float(normalized.get("high_pass")),
            "downsample": int(normalized.get("downsample")),
            "downsample_rate": int(normalized.get("downsample")),
            "reject_thresh": float(normalized.get("rejection_z")),
            "ref_channel1": (normalized.get("ref_chan1") or None),
            "ref_channel2": (normalized.get("ref_chan2") or None),
            "max_idx_keep": int(normalized.get("max_chan_idx_keep")),
            "max_bad_channels_alert_thresh": int(normalized.get("max_bad_chans")),
            "epoch_start": epoch_start,
            "epoch_end": epoch_end,
            "stim_channel": stim_channel,
            "save_preprocessed_fif": False,
            "event_id_map": event_map,
            "base_freq": base_freq,
            "oddball_freq": oddball_freq,
            "bca_upper_limit": bca_upper_limit,
            "analysis": {
                "base_freq": base_freq,
                "oddball_freq": oddball_freq,
                "bca_upper_limit": bca_upper_limit,
            },
        }
        logger.debug(
            "VALIDATED_PARAMS_SNAPSHOT high_pass=%r low_pass=%r downsample_rate=%r "
            "reject_thresh=%r ref=(%r,%r) stim=%r",
            params.get("high_pass"),
            params.get("low_pass"),
            params.get("downsample_rate"),
            params.get("reject_thresh"),
            params.get("ref_channel1"),
            params.get("ref_channel2"),
            params.get("stim_channel"),
        )
        return params

    # ------------------------- settings UI -------------------------- #
    def open_settings_window(self) -> None:
        if self._settings_dialog and self._settings_dialog.isVisible():
            self._settings_dialog.raise_()
            self._settings_dialog.activateWindow()
            return
        dlg = SettingsDialog(self.settings, self, getattr(self, "currentProject", None))
        self._settings_dialog = dlg
        dlg.exec()
        if hasattr(self, "lbl_debug"):
            self.lbl_debug.setVisible(self.settings.debug_enabled())
        self._settings_dialog = None

    def check_for_updates(self) -> None:
        update_manager.check_for_updates_async(
            self, silent=False, notify_if_no_update=True, force=True
        )

    def quit(self) -> None:
        self.close()

    # --------------------------- projects --------------------------- #
    def new_project(self) -> None:
        project_workflows.new_project(self)

    def open_existing_project(self) -> None:
        project_workflows.open_existing_project(self)

    def openProjectPath(self, folder: str) -> None:  # noqa: N802 (compat)
        project_workflows.open_project_path(self, folder)

    def edit_project_settings(self) -> None:
        project_workflows.edit_project_settings(self)

    def _on_project_ready(self) -> None:
        project_workflows.on_project_ready(self)

    # --------------------------- tools UI --------------------------- #
    def open_stats_analyzer(self) -> None:
        QMessageBox.warning(
            self,
            "Statistics Tool Under Development",
            STATS_TOOL_UNDER_DEVELOPMENT_WARNING,
        )
        window = PysideStatsWindow(self)
        window.show()
        if not hasattr(self, "_child_windows"):
            self._child_windows = []
        self._child_windows.append(window)

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

    def _live_event_map_rows(self) -> list[QWidget]:
        return event_map.live_event_map_rows(self)

    def _event_row_edits(self, row: QWidget) -> tuple[QLineEdit | None, QLineEdit | None]:
        return event_map.event_row_edits(row)

    def _ensure_event_row_registered(self, row: QWidget) -> None:
        event_map.ensure_event_row_registered(self, row)

    def _bind_event_map_row_widgets(self, row: QWidget) -> None:
        event_map.bind_event_map_row_widgets(self, row)

    def _bind_existing_event_map_rows(self) -> None:
        event_map.bind_existing_event_map_rows(self)

    def _event_row_label_edit(self, row: QWidget) -> QLineEdit | None:
        return event_map.event_row_label_edit(row)

    def _event_row_id_edit(self, row: QWidget) -> QLineEdit | None:
        return event_map.event_row_id_edit(row)

    def _resolve_event_map_row(self, widget: QWidget) -> QWidget | None:
        return event_map.resolve_event_map_row(self, widget)

    def _event_map_scroll_area(self):
        return event_map.event_map_scroll_area(self)

    def _focus_event_row_label(self, row: QWidget) -> None:
        event_map.focus_event_row_label(self, row)

    def _is_valid_event_map_id(self, id_edit: QLineEdit) -> bool:
        return event_map.is_valid_event_map_id(id_edit)

    def _handle_event_map_id_enter(self, id_edit: QLineEdit) -> bool:
        return event_map.handle_event_map_id_enter(self, id_edit)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        handled = event_map.handle_event_filter(self, watched, event)
        if handled is not None:
            return handled
        return super().eventFilter(watched, event)

    def add_event_row(self, label: str = "", id: str = "") -> None:
        event_map.add_event_row(self, label, id)

    @property
    def event_map_entries(self) -> list[dict[str, _QtEntryAdapter]]:
        return event_map.event_map_entries(self, _QtEntryAdapter)

    def _on_start_stop_clicked(self) -> None:
        processing_workflows.on_start_stop_clicked(self)


    def _export_with_post_process(self, labels: list[str]) -> None:
        post_export_workflows.export_with_post_process(
            self,
            labels,
            _shared_post_process,
            log=logger,
        )

    # ------------------------ project load hook --------------------- #
    def loadProject(self, project: Project) -> None:  # pragma: no cover - GUI stub
        project_workflows.load_project(self, project, _QtEntryAdapter)

    def saveProjectSettings(self) -> None:
        project_workflows.save_project_settings(self)

    # --------------------------- UI helpers --------------------------- #
    def _sync_input_folder_display(self) -> None:
        project_workflows.sync_input_folder_display(self)

    def update_select_button_text(self) -> None:
        project_workflows.update_select_button_text(self)

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

        self.parallel_mode = "single" if is_single else "process"

        _safe_set_enabled("btn_select_input_file", is_single)
        _safe_set_enabled("le_input_file", is_single)
        _safe_set_enabled("btn_select_input_folder", not is_single)
        _safe_set_enabled("le_input_folder", not is_single)

        # Toggle visibility of the single-file row, if present
        row = getattr(self, "row_single_file", None)
        if row and hasattr(row, "setVisible"):
            try:
                row.setVisible(is_single)
            except Exception:
                pass
        file_label = getattr(self, "lbl_single_file", None)
        if file_label and hasattr(file_label, "setVisible"):
            try:
                file_label.setVisible(is_single)
            except Exception:
                pass

        folder_row = getattr(self, "row_input_folder", None)
        if folder_row and hasattr(folder_row, "setVisible"):
            try:
                folder_row.setVisible(not is_single)
            except Exception:
                pass
        folder_label = getattr(self, "lbl_input_folder", None)
        if folder_label and hasattr(folder_label, "setVisible"):
            try:
                folder_label.setVisible(not is_single)
            except Exception:
                pass

        self._sync_input_folder_display()
        self.update_select_button_text()

        # Optional label feedback
        lbl = getattr(self, "lbl_mode", None)
        if isinstance(lbl, QLabel):
            try:
                lbl.setText(f"Mode: {pretty}")
            except Exception:
                pass

        self._update_start_enabled()

    # ---------- legacy mixin hook: enable/disable controls during run ---------- #
    def _set_controls_enabled(self, enabled: bool) -> None:
        """
        Required by Main_App.Shared.processing_mixin.
        Disables common inputs while a run is active. No-ops if widgets missing.

        The main Start/Stop button is intentionally left enabled so the user can
        always request a stop.
        """
        self.busy = not enabled

        def _safe_enable(name: str) -> None:
            w = getattr(self, name, None)
            if w and hasattr(w, "setEnabled"):
                try:
                    w.setEnabled(enabled)
                except Exception:
                    self.log(f"_set_controls_enabled: could not toggle {name}", level=logging.DEBUG)

        # Common controls (exists-if-present).
        # NOTE: 'btn_start' is deliberately omitted.
        for n in (
                "btn_select_input_file", "le_input_file",
                "btn_select_input_folder", "le_input_folder",
                "btn_add_event", "btn_add_row", "btn_detect",
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

    # --------------------------- single-file helpers --------------------------- #
    def _update_start_enabled(self) -> None:
        """Enable Start only when valid selection exists in Single mode."""
        btn = getattr(self, "btn_start", None)
        if not btn:
            return
        try:
            mode = self.file_mode.get()
        except Exception:
            mode = "Batch"
        if mode == "Single":
            txt = getattr(self, "le_input_file", None).text() if hasattr(self, "le_input_file") else ""
            ok = bool(txt) and Path(txt).suffix.lower() == ".bdf" and Path(txt).exists()
            btn.setEnabled(ok)
        else:
            btn.setEnabled(True)

    def select_single_file(self) -> None:
        """Windows-native file dialog to pick one .bdf under the project's input folder."""
        if not getattr(self, "currentProject", None):
            QMessageBox.warning(self, "No Project", "Please open or create a project first.")
            return
        start_dir = str(Path(self.currentProject.input_folder))
        fname, _ = QFileDialog.getOpenFileName(
            self,
            "Select EEG File (.bdf)",
            start_dir,
            "EEG BioSemi (*.bdf)",
        )
        if not fname:
            self.log("Single-file selection canceled.")
            self._update_start_enabled()
            return
        p = Path(fname)
        if p.suffix.lower() != ".bdf":
            QMessageBox.warning(self, "Invalid File", "Please select a .bdf file.")
            self._update_start_enabled()
            return
        # Must be inside the project's input folder
        in_root = Path(self.currentProject.input_folder).resolve()
        try:
            inside = in_root in p.resolve().parents
        except Exception:
            inside = False
        if not inside:
            QMessageBox.warning(
                self,
                "Outside Project",
                "Please choose a .bdf inside this project's input folder.\n"
                f"Input folder:\n{in_root}",
            )
            self._update_start_enabled()
            return
        # Accept
        if hasattr(self, "le_input_file"):
            self.le_input_file.setText(str(p))
        self._selected_bdf = str(p)
        self.data_paths = [str(p)]
        self.log(f"Single-file selected: {p.name}")
        self._update_start_enabled()

# ----------------------------------------------------------------------
def main() -> None:
    app = QApplication(sys.argv)
    apply_fpvs_theme(app)
    win = MainWindow()
    win.show()
    app.exec()


if __name__ == "__main__":
    main()

