# main_window.py
from __future__ import annotations

# ruff: noqa: E402

import logging
import os
import queue
import sys
from pathlib import Path
from Main_App.Shared.post_process import post_process as _shared_post_process
from Main_App.gui.theme import apply_fpvs_theme
from typing import Callable
from types import MethodType, SimpleNamespace
from collections import deque

import psutil

# Qt / PySide6
from PySide6.QtCore import QObject, QEvent, QTimer, Signal, Slot
from PySide6.QtGui import QCloseEvent, QAction, QShowEvent  # noqa: F401
from PySide6.QtWidgets import (
    QApplication,
    QAbstractButton,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QWidget,
)

# ----------------------------------------------------------------------
# Canonical Qt messagebox adapters
# ----------------------------------------------------------------------

logger = logging.getLogger(__name__)
# Keep this module quiet unless the app configures handlers; avoids accidental console output.
logger.addHandler(logging.NullHandler())

from Main_App.Shared.processing_mixin import ProcessingMixin
from Main_App.Shared.settings_manager import SettingsManager
from Main_App.projects import Project
from Main_App.processing.processing_controller import (
    _animate_progress_to,
)
from Main_App.projects.project_manager import select_projects_root
from Main_App.workers.mp_env import (
    compute_effective_max_workers,
)
from Tools.Average_Preprocessing.New_PySide6.main_window import (
    AdvancedAveragingWindow,
)
from Tools.Image_Resizer.pyside_resizer import FPVSImageResizerQt
from Tools.Individual_Detectability.main_window import IndividualDetectabilityWindow
from Tools.Plot_Generator.plot_generator import PlotGeneratorWindow
from Tools.Publication_Maps.gui import PublicationMapsWindow
from Tools.Publication_Report.gui import PublicationReportWindow
from Tools.Ratio_Calculator.gui import RatioCalculatorWindow
from Tools.Stats import StatsWindow as PysideStatsWindow
from config import FPVS_TOOLBOX_VERSION
from Main_App.gui import update_manager
from Main_App.gui import event_map
from Main_App.gui.file_menu import init_file_menu
from Main_App.gui.settings_panel import EmbeddedSettingsPage
from Main_App.gui.sidebar import init_sidebar
from Main_App.gui.ui_main import init_ui
from Main_App.gui import project_workflows
from Main_App.gui import processing_workflows
from Main_App.gui import processing_inputs
from Main_App.gui import post_export_workflows
from Main_App.gui import tool_workflows
from Main_App.gui import shell_status
from Main_App.gui.post_export_workflows import (
    excel_snapshot as _excel_snapshot,  # noqa: F401 - compatibility re-export
    should_show_no_excel_popup as _should_show_no_excel_popup,  # noqa: F401 - compatibility re-export
)
from Main_App.gui.op_guard import OpGuard

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
                "btn_add_event", "btn_add_row",
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
    * We **do not** inherit the old validation mixin anymore.
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
        from Main_App.gui.update_manager import cleanup_old_executable, check_for_updates_on_launch
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
        self._settings_page = None
        self.processor = Processor()
        self.setWindowTitle(f"FPVS Toolbox v{FPVS_TOOLBOX_VERSION}")
        self.setMinimumSize(1280, 900)
        self.resize(1280, 900)
        self.currentProject: Project | None = None

        # Build UI
        init_ui(self)
        self._bind_existing_event_map_rows()
        shell_status.init_launch_reveal_state(self)

        # Poll the worker queue so the GUI stays responsive
        self._processing_timer = QTimer(self)
        self._processing_timer.setSingleShot(False)
        self._processing_timer.timeout.connect(self._periodic_queue_check)

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
        shell_status.ensure_processing_navigation_unlocked(self)
        select_projects_root(self)
        init_file_menu(self)
        if hasattr(self, "stacked"):
            self.stacked.currentChanged.connect(self._sync_menu_bar_for_current_page)
        self._sync_menu_bar_for_current_page()

        # Wire landing page buttons if present
        if hasattr(self, "btn_create_project"):
            self.btn_create_project.clicked.connect(self.actionCreateNewProject.trigger)
        if hasattr(self, "btn_open_project"):
            self.btn_open_project.clicked.connect(self.actionOpenExistingProject.trigger)

        # Default page and initial logs
        if hasattr(self, "stacked"):
            self.stacked.setCurrentIndex(0)
            self._sync_menu_bar_for_current_page()
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
        self._post_worker = None
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
        return shell_status.launch_reveal_widget(self)

    def _start_launch_reveal(self) -> None:
        shell_status.start_launch_reveal(self)

    def _finish_launch_reveal(self) -> None:
        shell_status.finish_launch_reveal(self)

    # ---------------------------- logging --------------------------- #
    def _emit_backend_log(self, level: int, message: str) -> None:
        shell_status.emit_backend_log(self, logger, level, message)

    def log(self, message: str, level: int = logging.INFO) -> None:
        shell_status.log_message(self, logger, message, level)

    def _show_processing_started_notice(self) -> None:
        shell_status.show_processing_started_notice(self)

    # -------------------------- processing -------------------------- #

    def _sync_menu_bar_for_current_page(self, _index: int | None = None) -> None:
        """Hide app-level menus on the welcome page until a project flow starts."""
        menu_bar = self.menuBar()
        landing_page = getattr(self, "landing_page", None)
        current_page = self.stacked.currentWidget() if hasattr(self, "stacked") else None
        menu_bar.setVisible(current_page is not landing_page)

    def stop_processing(self) -> None:
        processing_workflows.stop_processing(self)

    # -------------------------- processing -------------------------- #
    def start_processing(self) -> None:
        processing_workflows.start_processing(self, log=logger)

    # --- Busy spinner helpers ---
    def _busy_start(self) -> None:
        shell_status.busy_start(self)

    def _busy_stop(self) -> None:
        shell_status.busy_stop(self)

    def _tick_busy(self) -> None:
        shell_status.tick_busy(self)

    def _prepare_processing_activity(self, files: list[Path]) -> None:
        shell_status.prepare_processing_activity(self, files)

    def _update_processing_progress(self, pct: int) -> None:
        shell_status.update_processing_progress(self, pct)

    def _on_processing_file_status(self, result: dict[str, object]) -> None:
        shell_status.update_processing_file_status(self, result)

    # --------------------------------

    def _on_processing_finished(self, payload: dict | None = None) -> None:
        processing_workflows.on_processing_finished(self, payload)

    def _on_processing_error(self, message: str) -> None:
        processing_workflows.on_processing_error(self, message)

    @Slot()
    def _periodic_queue_check(self) -> None:
        processing_workflows.periodic_queue_check(self)

    def _start_post_worker(self, file_name: str, epochs_dict: dict, labels: list[str]) -> None:
        post_export_workflows.start_post_worker(self, file_name, epochs_dict, labels)

    def _on_worker_error(self, message: str) -> None:
        post_export_workflows.on_worker_error(self, message)

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

    # The ProcessingMixin looks for this; validation now lives in processing_inputs.
    def _validate_inputs(self) -> bool:  # called inside ProcessingMixin.start_processing
        return processing_inputs.validate_inputs(self)

    def _build_validated_params(self) -> dict | None:
        return processing_inputs.build_validated_params(self)

    # ------------------------- settings UI -------------------------- #
    def open_settings_window(self) -> None:
        if hasattr(self, "stacked"):
            self.stacked.setCurrentIndex(1)
        self.workspace_stack.setCurrentWidget(self._ensure_settings_page())
        self._set_sidebar_selection("btn_settings")

    def _ensure_settings_page(self) -> EmbeddedSettingsPage:
        project = getattr(self, "currentProject", None)
        page = getattr(self, "_settings_page", None)
        if page is None or getattr(page, "project", None) is not project:
            if page is not None:
                self.workspace_stack.removeWidget(page)
                page.deleteLater()
            page = EmbeddedSettingsPage(self.settings, self, project)
            page.setObjectName("embedded_settings_page")
            self.workspace_stack.addWidget(page)
            self._settings_page = page
        return page

    def check_for_updates(self) -> None:
        tool_workflows.check_for_updates(self, update_manager)

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
        project_workflows.reset_project_context_workspace(self)

    # --------------------------- tools UI --------------------------- #
    def _set_sidebar_selection(self, role: str) -> None:
        sidebar = getattr(self, "sidebar", None)
        if sidebar is None:
            return
        for widget in sidebar.findChildren(QWidget):
            setter = getattr(widget, "set_selected", None)
            if callable(setter) and widget.property("role"):
                setter(widget.property("role") == role)

    def show_home_page(self) -> None:
        if not getattr(self, "_run_active", False):
            shell_status.ensure_processing_navigation_unlocked(self)
        if hasattr(self, "stacked"):
            self.stacked.setCurrentIndex(1)
        if hasattr(self, "workspace_stack") and hasattr(self, "homeWidget"):
            self.workspace_stack.setCurrentWidget(self.homeWidget)
        self._set_sidebar_selection("btn_home")

    def _ensure_stats_page(self) -> PysideStatsWindow:
        project = getattr(self, "currentProject", None)
        project_root = Path(project.project_root).resolve() if project is not None else None
        page = getattr(self, "_stats_page", None)
        page_root = Path(getattr(page, "project_dir", "")).resolve() if page is not None else None
        if page is None or (project_root is not None and page_root != project_root):
            if page is not None:
                self.workspace_stack.removeWidget(page)
                page.deleteLater()
            page = PysideStatsWindow(parent=self)
            page.setObjectName("embedded_stats_page")
            self.workspace_stack.addWidget(page)
            self._stats_page = page
        return page

    def open_stats_analyzer(self) -> None:
        if hasattr(self, "stacked"):
            self.stacked.setCurrentIndex(1)
        self.workspace_stack.setCurrentWidget(self._ensure_stats_page())
        self._set_sidebar_selection("btn_data")

    def _ensure_image_resizer_page(self) -> FPVSImageResizerQt:
        page = getattr(self, "_image_resizer_page", None)
        if page is None:
            page = FPVSImageResizerQt(self.workspace_stack)
            page.setObjectName("embedded_image_resizer_page")
            self.workspace_stack.addWidget(page)
            self._image_resizer_page = page
        return page

    def open_image_resizer(self) -> None:
        if hasattr(self, "stacked"):
            self.stacked.setCurrentIndex(1)
        self.workspace_stack.setCurrentWidget(self._ensure_image_resizer_page())
        self._set_sidebar_selection("btn_image")

    def _ensure_ratio_calculator_page(self) -> RatioCalculatorWindow:
        page = getattr(self, "_ratio_calculator_page", None)
        if page is None:
            project_root = None
            project = getattr(self, "currentProject", None)
            if project is not None and hasattr(project, "project_root"):
                project_root = str(project.project_root)
            page = RatioCalculatorWindow(parent=self, project_root=project_root)
            page.setObjectName("embedded_ratio_calculator_page")
            self.workspace_stack.addWidget(page)
            self._ratio_calculator_page = page
        return page

    def open_ratio_calculator(self) -> None:
        if hasattr(self, "stacked"):
            self.stacked.setCurrentIndex(1)
        self.workspace_stack.setCurrentWidget(self._ensure_ratio_calculator_page())
        self._set_sidebar_selection("btn_ratio")

    def _ensure_individual_detectability_page(self) -> IndividualDetectabilityWindow:
        page = getattr(self, "_individual_detectability_page", None)
        if page is None:
            project_root = None
            project = getattr(self, "currentProject", None)
            if project is not None and hasattr(project, "project_root"):
                project_root = str(project.project_root)
            page = IndividualDetectabilityWindow(
                parent=self.workspace_stack,
                project_root=project_root,
                embedded=True,
            )
            page.setObjectName("embedded_individual_detectability_page")
            self.workspace_stack.addWidget(page)
            self._individual_detectability_page = page
        return page

    def open_individual_detectability(self) -> None:
        if hasattr(self, "stacked"):
            self.stacked.setCurrentIndex(1)
        self.workspace_stack.setCurrentWidget(self._ensure_individual_detectability_page())
        self._set_sidebar_selection("btn_individual_detectability")

    def _ensure_plot_generator_page(self) -> PlotGeneratorWindow:
        page = getattr(self, "_plot_generator_page", None)
        if page is None:
            page = PlotGeneratorWindow(parent=self)
            page.setObjectName("embedded_plot_generator_page")
            self.workspace_stack.addWidget(page)
            self._plot_generator_page = page
        return page

    def _ensure_publication_maps_page(self) -> PublicationMapsWindow:
        page = getattr(self, "_publication_maps_page", None)
        if page is None:
            project_root = None
            project = getattr(self, "currentProject", None)
            if project is not None and hasattr(project, "project_root"):
                project_root = str(project.project_root)
            page = PublicationMapsWindow(
                parent=self,
                project_root=project_root,
                embedded=True,
            )
            page.setObjectName("embedded_publication_maps_page")
            self.workspace_stack.addWidget(page)
            self._publication_maps_page = page
        return page

    def _ensure_publication_report_page(self) -> PublicationReportWindow:
        page = getattr(self, "_publication_report_page", None)
        if page is None:
            project_root = None
            project = getattr(self, "currentProject", None)
            if project is not None and hasattr(project, "project_root"):
                project_root = str(project.project_root)
            page = PublicationReportWindow(
                parent=self,
                project_root=project_root,
                embedded=True,
            )
            page.setObjectName("embedded_publication_report_page")
            self.workspace_stack.addWidget(page)
            self._publication_report_page = page
        return page

    def _ensure_loreta_visualizer_page(self) -> QWidget:
        page = getattr(self, "_loreta_visualizer_page", None)
        if page is None:
            from Tools.LORETA_Visualizer import LoretaVisualizerWindow

            project_root = None
            project = getattr(self, "currentProject", None)
            if project is not None and hasattr(project, "project_root"):
                project_root = str(project.project_root)
            page = LoretaVisualizerWindow(
                parent=self.workspace_stack,
                project_root=project_root,
                embedded=True,
            )
            page.setObjectName("embedded_loreta_visualizer_page")
            self.workspace_stack.addWidget(page)
            self._loreta_visualizer_page = page
        return page

    def _acknowledge_loreta_beta_warning(self) -> None:
        if getattr(self, "_loreta_beta_warning_acknowledged", False):
            return
        QMessageBox.warning(
            self,
            "Source Localization Beta",
            "Warning: the source localization tool is currently in beta. Features are subject to change.",
            QMessageBox.StandardButton.Ok,
            QMessageBox.StandardButton.Ok,
        )
        self._loreta_beta_warning_acknowledged = True

    def _acknowledge_publication_report_beta_warning(self) -> None:
        if getattr(self, "_publication_report_beta_warning_acknowledged", False):
            return
        QMessageBox.warning(
            self,
            "Publication Report Beta",
            "Warning: the publication report tool is currently in beta. Features are subject to change.",
            QMessageBox.StandardButton.Ok,
            QMessageBox.StandardButton.Ok,
        )
        self._publication_report_beta_warning_acknowledged = True

    def _ensure_epoch_averaging_page(self) -> AdvancedAveragingWindow | None:
        paths = tool_workflows.resolve_epoch_averaging_paths(self)
        if paths is None:
            return None

        page = getattr(self, "_epoch_page", None)
        if page is None:
            data_dir, excel_dir = paths
            page = AdvancedAveragingWindow(
                parent=self,
                input_dir=data_dir,
                output_dir=excel_dir,
            )
            page.setObjectName("embedded_epoch_averaging_page")
            try:
                page.btn_close.clicked.disconnect(page.close)
            except (RuntimeError, TypeError):
                pass
            page.btn_close.clicked.connect(self.show_home_page)
            self.workspace_stack.addWidget(page)
            self._epoch_page = page
            self._epoch_win = page
        return page

    def open_plot_generator(self) -> None:
        if hasattr(self, "stacked"):
            self.stacked.setCurrentIndex(1)
        self.workspace_stack.setCurrentWidget(self._ensure_plot_generator_page())
        self._set_sidebar_selection("btn_graphs")

    def open_publication_maps(self) -> None:
        if hasattr(self, "stacked"):
            self.stacked.setCurrentIndex(1)
        self.workspace_stack.setCurrentWidget(self._ensure_publication_maps_page())
        self._set_sidebar_selection("btn_publication_maps")

    def open_publication_report(self) -> None:
        self._acknowledge_publication_report_beta_warning()
        if hasattr(self, "stacked"):
            self.stacked.setCurrentIndex(1)
        self.workspace_stack.setCurrentWidget(self._ensure_publication_report_page())
        self._set_sidebar_selection("btn_publication_report")

    def open_loreta_visualizer(self) -> None:
        self._acknowledge_loreta_beta_warning()
        if hasattr(self, "stacked"):
            self.stacked.setCurrentIndex(1)
        self.workspace_stack.setCurrentWidget(self._ensure_loreta_visualizer_page())
        self._set_sidebar_selection("btn_loreta_visualizer")

    def open_epoch_averaging(self) -> None:
        page = self._ensure_epoch_averaging_page()
        if page is None:
            return
        if hasattr(self, "stacked"):
            self.stacked.setCurrentIndex(1)
        self.workspace_stack.setCurrentWidget(page)
        self._set_sidebar_selection("btn_epoch")

    def open_advanced_analysis_window(self) -> None:
        self.open_epoch_averaging()

    def show_about_dialog(self) -> None:
        tool_workflows.show_about_dialog(self, FPVS_TOOLBOX_VERSION)

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
        processing_inputs.on_mode_changed(self, mode)

    def _set_controls_enabled(self, enabled: bool) -> None:
        processing_inputs.set_controls_enabled(self, enabled)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._post_worker and self._post_thread:
            self._post_worker.stop()
            self._post_thread.quit()
            self._post_thread.wait(2000)
        super().closeEvent(event)

    def _update_start_enabled(self) -> None:
        processing_inputs.update_start_enabled(self)

    def select_single_file(self) -> None:
        processing_inputs.select_single_file(self)

# ----------------------------------------------------------------------
def main() -> None:
    app = QApplication(sys.argv)
    apply_fpvs_theme(app)
    win = MainWindow()
    win.show()
    app.exec()


if __name__ == "__main__":
    main()
