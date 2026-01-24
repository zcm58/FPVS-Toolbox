"""View layer for the PySide6 Stats tool.

StatsWindow renders the Stats UI, wires user gestures to StatsController entry
points, and reflects pipeline progress and logs for the user. All analysis logic
is delegated to the controller and workers; this module focuses on layout and
signal wiring only.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, Dict, List, NamedTuple, Optional, Tuple

import pandas as pd
from PySide6.QtCore import Qt, QTimer, QThreadPool, Slot, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QFontMetrics, QTextCursor
from PySide6.QtWidgets import (
    QFileDialog,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QScrollArea,
    QTextEdit,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

# Qt imports proof: QAction from PySide6.QtGui
from Main_App import SettingsManager
from Main_App.PySide6_App.Backend.project import (
    EXCEL_SUBFOLDER_NAME,
    STATS_SUBFOLDER_NAME,
)
from Main_App.PySide6_App.utils.op_guard import OpGuard
from Main_App.PySide6_App.widgets.busy_spinner import BusySpinner
from Tools.Stats.Legacy.stats_analysis import ALL_ROIS_OPTION, set_rois
from Tools.Stats.Legacy.stats_export import (
    export_mixed_model_results_to_excel,
    export_posthoc_results_to_excel,
    export_rm_anova_results_to_excel,
    export_significance_results_to_excel as export_harmonic_results_to_excel,
)
from Tools.Stats.Legacy.stats_helpers import apply_rois_to_modules, load_rois_from_settings
from Tools.Stats.PySide6.stats_controller import StatsController
from Tools.Stats.PySide6.stats_core import (
    ANOVA_BETWEEN_XLS,
    ANOVA_XLS,
    GROUP_CONTRAST_XLS,
    HARMONIC_XLS,
    LMM_BETWEEN_XLS,
    LMM_XLS,
    PipelineId,
    PipelineStep,
    POSTHOC_XLS,
    RESULTS_SUBFOLDER_NAME,
    StepId,
)
from Tools.Stats.PySide6.stats_data_loader import (
    check_for_open_excel_files,
    ensure_results_dir,
    group_harmonic_results,
    ScanError,
    auto_detect_project_dir,
    load_manifest_data,
    load_project_scan,
    safe_export_call,
    resolve_project_subfolder,
)
from Tools.Stats.PySide6.stats_logging import format_log_line, format_section_header
from Tools.Stats.PySide6.stats_workers import StatsWorker
from Tools.Stats.PySide6.dv_policies import (
    FIXED_K_POLICY_NAME,
    LEGACY_POLICY_NAME,
)
from Tools.Stats.PySide6.summary_utils import (
    StatsSummaryFrames,
    SummaryConfig,
    build_between_anova_output,
    build_rm_anova_output,
    build_summary_from_frames,
    build_summary_frames_from_results,
)

logger = logging.getLogger(__name__)
_unused_qaction = QAction  # keep import alive for Qt resource checkers

class HarmonicConfig(NamedTuple):
    metric: str
    threshold: float


# --------------------------- worker functions ---------------------------

# --------------------------- main window ---------------------------

class StatsWindow(QMainWindow):
    """PySide6 window wrapping the legacy FPVS Statistical Analysis Tool."""

    def __init__(self, parent: Optional[QMainWindow] = None, project_dir: Optional[str] = None):
        if project_dir and os.path.isdir(project_dir):
            self.project_dir = project_dir
        else:
            proj = getattr(parent, "currentProject", None)
            self.project_dir = (
                str(proj.project_root) if proj and hasattr(proj, "project_root") else auto_detect_project_dir()
            )

        self._project_path = Path(self.project_dir).resolve()
        self._results_folder_hint: str | None = None
        self._subfolder_hints: dict[str, str] = {}

        config_path = self._project_path / "project.json"
        try:
            cfg = json.loads(config_path.read_text(encoding="utf-8"))
            self.project_title = cfg.get("name", cfg.get("title", os.path.basename(self.project_dir)))
            self._results_folder_hint, self._subfolder_hints = load_manifest_data(self._project_path, cfg)
        except Exception:
            self.project_title = os.path.basename(self.project_dir)

        super().__init__(parent)
        self.setWindowFlags(self.windowFlags() | Qt.Window)
        self.setWindowTitle("FPVS Statistical Analysis Tool")
        logger.info(
            "stats_window_init",
            extra={
                "window_id": id(self),
                "project_dir": self.project_dir,
            },
        )

        self._guard = OpGuard()
        if not hasattr(self._guard, "done"):
            self._guard.done = self._guard.end  # type: ignore[attr-defined]
        self.pool = QThreadPool.globalInstance()
        self._focus_calls = 0
        # Strong references to active StatsWorker instances to avoid any
        # lifetime / GC edge cases that could drop Qt signals.
        self._active_workers: list[StatsWorker] = []

        self.setMinimumSize(400, 600)
        self.resize(400, 600)

        # re-entrancy guard for scan
        self._scan_guard = OpGuard()
        if not hasattr(self._scan_guard, "done"):
            self._scan_guard.done = self._scan_guard.end  # type: ignore[attr-defined]

        # --- state ---
        self.subject_data: Dict = {}
        self.subject_groups: Dict[str, str | None] = {}
        self.subjects: List[str] = []
        self.conditions: List[str] = []
        self.selected_conditions: List[str] = []
        self._multi_group_manifest: bool = False
        self.rm_anova_results_data: Optional[pd.DataFrame] = None
        self.mixed_model_results_data: Optional[pd.DataFrame] = None
        self.between_anova_results_data: Optional[pd.DataFrame] = None
        self.between_mixed_model_results_data: Optional[pd.DataFrame] = None
        self.group_contrasts_results_data: Optional[pd.DataFrame] = None
        self.posthoc_results_data: Optional[pd.DataFrame] = None
        self.harmonic_check_results_data: List[dict] = []
        self._harmonic_results: dict[PipelineId, list[dict]] = {
            PipelineId.SINGLE: [],
            PipelineId.BETWEEN: [],
        }
        self.rois: Dict[str, List[str]] = {}
        self._harmonic_config: HarmonicConfig = HarmonicConfig("Z Score", 1.64)
        self._current_base_freq: float = 6.0
        self._current_alpha: float = 0.05
        self._active_pipeline: PipelineId | None = None
        self._condition_checkboxes: dict[str, QCheckBox] = {}
        self._dv_policy_name: str = LEGACY_POLICY_NAME
        self._dv_fixed_k: int = 5
        self._dv_exclude_harmonic1: bool = True
        self._dv_exclude_base_harmonics: bool = True
        self._pipeline_conditions: dict[PipelineId, list[str]] = {}
        self._pipeline_dv_policy: dict[PipelineId, dict[str, object]] = {}
        self._pipeline_base_freq: dict[PipelineId, float] = {}

        # --- legacy UI proxies ---
        self.stats_data_folder_var = SimpleNamespace(get=lambda: self.le_folder.text() if hasattr(self, "le_folder") else "",
                                                     set=lambda v: self.le_folder.setText(v) if hasattr(self, "le_folder") else None)
        self.detected_info_var = SimpleNamespace(set=lambda t: self._set_status(t))
        self.roi_var = SimpleNamespace(get=lambda: ALL_ROIS_OPTION, set=lambda v: None)
        self.alpha_var = SimpleNamespace(get=lambda: "0.05", set=lambda v: None)

        # UI
        self._init_ui()
        self.results_textbox = self.output_text

        self.refresh_rois()
        QTimer.singleShot(100, self._load_default_data_folder)

        self._progress_updates: List[int] = []

        # controller
        self._controller = StatsController(view=self)

    # --------- ROI + status helpers ---------

    def refresh_rois(self) -> None:
        fresh = load_rois_from_settings() or {}
        try:
            set_rois({})
        except Exception:
            pass
        apply_rois_to_modules(fresh)
        set_rois(fresh)
        self.rois = fresh
        self._update_roi_label()

    def _update_roi_label(self) -> None:
        names = list(self.rois.keys())
        txt = "Using {} ROI{} from Settings: {}".format(
            len(names), "" if len(names) == 1 else "s", ", ".join(names)
        ) if names else "No ROIs defined in Settings."
        self._set_roi_status(txt)

    def _set_status(self, txt: str) -> None:
        if hasattr(self, "lbl_status"):
            self.lbl_status.setText(txt)

    def _set_roi_status(self, txt: str) -> None:
        if hasattr(self, "lbl_rois"):
            self.lbl_rois.setText(txt)

    def _set_detected_info(self, txt: str) -> None:
        """Route unknown worker messages to proper label."""
        lower_txt = txt.lower() if isinstance(txt, str) else str(txt).lower()
        if (" roi" in lower_txt) or lower_txt.startswith("using ") or lower_txt.startswith("rois"):
            self._set_roi_status(txt)
        else:
            self._set_status(txt)

    def _clear_conditions_layout(self) -> None:
        layout = self.conditions_list_layout
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _populate_conditions_panel(self, conditions: List[str]) -> None:
        self._clear_conditions_layout()
        self._condition_checkboxes.clear()
        if not conditions:
            placeholder = QLabel("No conditions detected yet.")
            placeholder.setWordWrap(True)
            self.conditions_list_layout.addWidget(placeholder)
            self.selected_conditions = []
            return

        for condition in conditions:
            checkbox = QCheckBox(condition)
            checkbox.setChecked(True)
            checkbox.stateChanged.connect(self._on_condition_toggled)
            self.conditions_list_layout.addWidget(checkbox)
            self._condition_checkboxes[condition] = checkbox

        self.conditions_list_layout.addStretch(1)
        self._sync_selected_conditions()

    def _sync_selected_conditions(self) -> None:
        self.selected_conditions = [
            name for name, checkbox in self._condition_checkboxes.items() if checkbox.isChecked()
        ]

    def _on_condition_toggled(self, _state: int) -> None:
        self._sync_selected_conditions()

    def _select_all_conditions(self) -> None:
        for checkbox in self._condition_checkboxes.values():
            checkbox.setChecked(True)
        self._sync_selected_conditions()

    def _select_no_conditions(self) -> None:
        for checkbox in self._condition_checkboxes.values():
            checkbox.setChecked(False)
        self._sync_selected_conditions()

    def _get_selected_conditions(self) -> List[str]:
        if self._condition_checkboxes:
            return list(self.selected_conditions)
        return list(self.conditions)

    def _get_dv_policy_payload(self) -> dict[str, object]:
        return {
            "name": self._dv_policy_name,
            "fixed_k": int(self._dv_fixed_k),
            "exclude_harmonic1": bool(self._dv_exclude_harmonic1),
            "exclude_base_harmonics": bool(self._dv_exclude_base_harmonics),
        }

    def get_dv_policy_snapshot(self) -> dict[str, object]:
        return dict(self._get_dv_policy_payload())

    def _set_fixed_k_controls_enabled(self, enabled: bool) -> None:
        widgets = [
            getattr(self, "fixed_k_spinbox", None),
            getattr(self, "fixed_k_exclude_h1", None),
            getattr(self, "fixed_k_exclude_base", None),
            getattr(self, "fixed_k_base_freq_value", None),
        ]
        for widget in widgets:
            if widget is not None:
                widget.setEnabled(enabled)

    def _update_fixed_k_base_freq_label(self) -> None:
        label = getattr(self, "fixed_k_base_freq_value", None)
        if label is None:
            return
        label.setText(f"{self._current_base_freq:g} Hz")

    def _on_dv_policy_changed(self, text: str) -> None:
        self._dv_policy_name = text
        self._set_fixed_k_controls_enabled(text == FIXED_K_POLICY_NAME)

    def _on_fixed_k_changed(self, value: int) -> None:
        self._dv_fixed_k = int(value)

    def _on_fixed_k_exclude_h1_changed(self, state: int) -> None:
        self._dv_exclude_harmonic1 = state == Qt.Checked

    def _on_fixed_k_exclude_base_changed(self, state: int) -> None:
        self._dv_exclude_base_harmonics = state == Qt.Checked

    def append_log(self, section: str, message: str, level: str = "info") -> None:
        line = format_log_line(f"[{section}] {message}", level=level)
        if hasattr(self, "output_text") and self.output_text is not None:
            self.output_text.append(line)
            self.output_text.ensureCursorVisible()
        level_lower = (level or "info").lower()
        log_func = getattr(logger, level_lower, logger.info)
        log_func(line)

    def _section_label(self, pipeline: PipelineId | None) -> str:
        if pipeline is PipelineId.SINGLE:
            return "Single"
        if pipeline is PipelineId.BETWEEN:
            return "Between"
        return "General"

    def _log_pipeline_event(
        self,
        *,
        pipeline: PipelineId | None,
        step: StepId | None = None,
        event: str,
        extra: Optional[dict] = None,
    ) -> None:
        if pipeline is None:
            return
        payload = {"pipeline": pipeline.name.lower(), "event": event}
        if step:
            payload["step_id"] = step.name
        if extra:
            payload.update(extra)
        logger.info(format_section_header("stats_pipeline_event"), extra=payload)

    def _warn_unknown_excel_files(self, subject_data: Dict[str, Dict[str, str]], participants_map: dict[str, str]) -> None:
        if not subject_data:
            return
        unknown_files: set[str] = set()
        for pid, cond_map in subject_data.items():
            if not isinstance(cond_map, dict):
                continue
            if pid.upper() in participants_map:
                continue
            for filepath in cond_map.values():
                try:
                    unknown_files.add(os.path.basename(filepath))
                except Exception:
                    continue
        if not unknown_files:
            return
        files_list = "\n".join(sorted(unknown_files))
        QMessageBox.warning(
            self,
            "Unrecognized Excel Files",
            (
                "Warning: The following Excel files are not recognized in this project's subject list:\n"
                f"{files_list}\n"
                "Please remove these files from the folder or update the project metadata."
            ),
        )

    def _known_group_labels(self) -> list[str]:
        return sorted({g for g in (self.subject_groups or {}).values() if g})

    def _ensure_between_ready(self) -> bool:
        groups = self._known_group_labels()
        if len(groups) < 2:
            if self._multi_group_manifest and not groups:
                msg = (
                    "No valid group assignments are available for between-group analysis. "
                    "Assign participants to project groups and rescan."
                )
            else:
                msg = (
                    "Between-group analysis requires at least two groups with assigned subjects."
                )
            QMessageBox.information(
                self,
                "Need Multiple Groups",
                msg,
            )
            return False
        return True

    # --------- window focus / run state ---------

    def _focus_self(self) -> None:
        self._focus_calls += 1
        self.raise_()
        self.activateWindow()

    def _set_running(self, running: bool) -> None:
        buttons = [
            getattr(self, "analyze_single_btn", None),
            getattr(self, "single_advanced_btn", None),
            getattr(self, "analyze_between_btn", None),
            getattr(self, "between_advanced_btn", None),
            getattr(self, "lela_mode_btn", None),
            getattr(self, "btn_open_results", None),
        ]
        for b in buttons:
            if b:
                b.setEnabled(not running)
        spinner = getattr(self, "spinner", None)
        if spinner:
            if running:
                spinner.show()
                spinner.start()
            else:
                spinner.stop()
                spinner.hide()

    def _begin_run(self) -> bool:
        if not self._guard.start():
            return False
        self._set_running(True)
        self._focus_self()
        return True

    def _end_run(self) -> None:
        self._set_running(False)
        self._guard.done()
        self._focus_self()

    # --------- settings helpers ---------

    def _safe_settings_get(self, section: str, key: str, default) -> Tuple[bool, object]:
        try:
            settings = SettingsManager()
            val = settings.get(section, key, default)
            return True, val
        except Exception as e:
            self._log_ui_error(f"settings_get:{section}/{key}", e)
            return False, default

    def _get_analysis_settings(self) -> Optional[Tuple[float, float]]:
        ok1, bf = self._safe_settings_get("analysis", "base_freq", 6.0)
        ok2, a = self._safe_settings_get("analysis", "alpha", 0.05)
        try:
            base_freq = float(bf)
            alpha = float(a)
        except Exception as e:
            QMessageBox.critical(self, "Settings Error", f"Invalid analysis settings: {e}")
            return None
        if not (ok1 and ok2):
            QMessageBox.critical(self, "Settings Error", "Could not load analysis settings.")
            return None
        return base_freq, alpha

    def _get_harmonic_settings(self) -> Optional[HarmonicConfig]:
        ok_metric, metric = self._safe_settings_get("analysis", "harmonic_metric", "Z Score")
        ok_threshold, threshold = self._safe_settings_get("analysis", "harmonic_threshold", 1.64)
        try:
            threshold_val = float(threshold)
        except Exception as exc:
            QMessageBox.critical(self, "Settings Error", f"Invalid harmonic threshold: {exc}")
            return None

        if not (ok_metric and ok_threshold):
            QMessageBox.critical(self, "Settings Error", "Could not load harmonic settings.")
            return None

        metric_str = str(metric) if metric is not None else "Z Score"
        return HarmonicConfig(metric_str, threshold_val)

    # --------- centralized pre-run guards ---------

    def _precheck(self, *, require_anova: bool = False, start_guard: bool = True) -> bool:
        if self._check_for_open_excel_files(self.le_folder.text()):
            return False
        if not self.subject_data:
            QMessageBox.warning(self, "No Data", "Please select a valid data folder first.")
            return False
        selected_conditions = self._get_selected_conditions()
        if len(selected_conditions) < 2:
            message = "Select at least two conditions to run the analysis."
            self._set_status(message)
            self.append_log("General", message, level="warning")
            return False
        if require_anova and self.rm_anova_results_data is None:
            QMessageBox.warning(
                self,
                "Run ANOVA First",
                "Please run a successful RM-ANOVA before running post-hoc tests for the interaction.",
            )
            return False
        self.refresh_rois()
        if not self.rois:
            QMessageBox.warning(self, "No ROIs", "Define at least one ROI in Settings before running stats.")
            return False
        got = self._get_analysis_settings()
        if not got:
            return False
        self._current_base_freq, self._current_alpha = got
        self._update_fixed_k_base_freq_label()
        harmonic_cfg = self._get_harmonic_settings()
        if not harmonic_cfg:
            return False
        self._harmonic_config = harmonic_cfg
        if start_guard and not self._begin_run():
            return False
        return True

    # --------- exports plumbing ---------

    def export_results(self, kind: str, data, out_dir: str) -> list[Path]:
        mapping = {
            "anova": (export_rm_anova_results_to_excel, ANOVA_XLS),
            "lmm": (export_mixed_model_results_to_excel, LMM_XLS),
            "posthoc": (export_posthoc_results_to_excel, POSTHOC_XLS),
            "harmonic": (export_harmonic_results_to_excel, HARMONIC_XLS),
            "anova_between": (export_rm_anova_results_to_excel, ANOVA_BETWEEN_XLS),
            "lmm_between": (export_mixed_model_results_to_excel, LMM_BETWEEN_XLS),
            "group_contrasts": (export_posthoc_results_to_excel, GROUP_CONTRAST_XLS),
        }
        func, fname = mapping[kind]

        # Special handling for harmonic exports
        if kind == "harmonic":
            grouped = group_harmonic_results(data)
            has_rows = any(
                roi_entries
                for roi_data in grouped.values()
                for roi_entries in roi_data.values()
            )
            if not has_rows:
                self._set_status("No harmonic check results to export.")
                return []

            def _adapter(_ignored, *, save_path, log_func):
                export_harmonic_results_to_excel(
                    grouped,
                    save_path,
                    log_func,
                    metric=self._harmonic_config.metric,
                )

            path = safe_export_call(
                _adapter,
                None,
                out_dir,
                fname,
                log_func=self._set_status,
            )
            return [path]

        # Non-harmonic exports: if there's no data, nothing to export
        if data is None:
            return []

        path = safe_export_call(
            func,
            data,
            out_dir,
            fname,
            log_func=self._set_status,
        )
        return [path]

    def _write_dv_metadata(self, out_dir: str, pipeline_id: PipelineId) -> None:
        dv_policy = self._pipeline_dv_policy.get(pipeline_id, self._get_dv_policy_payload())
        conditions = self._pipeline_conditions.get(pipeline_id, self._get_selected_conditions())
        base_freq = self._pipeline_base_freq.get(pipeline_id, self._current_base_freq)
        payload = {
            "policy_name": dv_policy.get("name", LEGACY_POLICY_NAME),
            "fixed_k": dv_policy.get("fixed_k", 5),
            "exclude_harmonic1": dv_policy.get("exclude_harmonic1", True),
            "exclude_base_harmonics": dv_policy.get("exclude_base_harmonics", True),
            "base_frequency_hz": base_freq,
            "selected_conditions": list(conditions),
        }
        try:
            out_path = Path(out_dir) / "dv_metadata.json"
            out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception:  # noqa: BLE001
            logger.exception("Failed to write DV metadata export.")

    def _ensure_results_dir(self) -> str:
        target = ensure_results_dir(
            self._project_path,
            self._results_folder_hint,
            self._subfolder_hints,
            results_subfolder_name=STATS_SUBFOLDER_NAME,
        )
        return str(target)

    def _open_results_folder(self) -> None:
        out_dir = self._ensure_results_dir()
        QDesktopServices.openUrl(QUrl.fromLocalFile(out_dir))

    def _update_export_buttons(self) -> None:
        def _maybe_enable(name: str, enabled: bool) -> None:
            btn = getattr(self, name, None)
            if btn:
                btn.setEnabled(enabled)

        _maybe_enable(
            "export_rm_anova_btn",
            isinstance(self.rm_anova_results_data, pd.DataFrame)
            and not self.rm_anova_results_data.empty,
        )
        _maybe_enable(
            "export_mixed_model_btn",
            isinstance(self.mixed_model_results_data, pd.DataFrame)
            and not self.mixed_model_results_data.empty,
        )
        _maybe_enable(
            "export_posthoc_btn",
            isinstance(self.posthoc_results_data, pd.DataFrame)
            and not self.posthoc_results_data.empty,
        )
        _maybe_enable(
            "export_between_anova_btn",
            isinstance(self.between_anova_results_data, pd.DataFrame)
            and not self.between_anova_results_data.empty,
        )
        _maybe_enable(
            "export_between_mixed_btn",
            isinstance(self.between_mixed_model_results_data, pd.DataFrame)
            and not self.between_mixed_model_results_data.empty,
        )
        _maybe_enable(
            "export_group_contrasts_btn",
            isinstance(self.group_contrasts_results_data, pd.DataFrame)
            and not self.group_contrasts_results_data.empty,
        )

    def _build_summary_frames(self, pipeline_id: PipelineId) -> StatsSummaryFrames:
        return build_summary_frames_from_results(
            pipeline_id,
            single_posthoc=self.posthoc_results_data,
            rm_anova_results=self.rm_anova_results_data,
            mixed_model_results=self.mixed_model_results_data,
            between_contrasts=self.group_contrasts_results_data,
            between_anova_results=self.between_anova_results_data,
            between_mixed_model_results=self.between_mixed_model_results_data,
            harmonic_results=self._harmonic_results.get(pipeline_id),
        )

    def _render_summary(self, summary_text: str) -> None:
        lines = (summary_text or "").splitlines()
        if not lines:
            self.output_text.append("(No summary generated.)")
            self.output_text.append("")
            return
        header = lines[0].strip()
        try:
            cursor = self.output_text.textCursor()
            cursor.movePosition(QTextCursor.End)
            self.output_text.setTextCursor(cursor)
            if header:
                self.output_text.insertHtml(f"<b>{header}</b><br>")
            for line in lines[1:]:
                self.output_text.append(line)
            self.output_text.append("")
        except Exception:  # noqa: BLE001
            logger.exception("Failed to render summary text", exc_info=True)
            if header:
                self.output_text.append(header)
            for line in lines[1:]:
                self.output_text.append(line)
            self.output_text.append("")

    # --------- worker signal wiring ---------

    def _wire_and_start(self, worker: StatsWorker, finished_slot) -> None:
        worker.signals.progress.connect(self._on_worker_progress)
        worker.signals.message.connect(self._on_worker_message)
        worker.signals.error.connect(self._on_worker_error)
        worker.signals.finished.connect(finished_slot)
        self.pool.start(worker)

    def set_busy(self, is_busy: bool) -> None:
        try:
            self._set_running(is_busy)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "stats_view_set_busy_error",
                exc_info=True,
                extra={"is_busy": is_busy, "error": str(exc)},
            )

    def start_step_worker(
            self,
            pipeline_id: PipelineId,
            step: PipelineStep,
            *,
            finished_cb,
            error_cb,
            message_cb=None,
    ) -> None:
        """Create and start a StatsWorker for a single pipeline step.

        Diagnostics:
          - Entry log with pipeline / step metadata.
          - Log when the worker is constructed and submitted to the pool.
          - Logs when the finished/error slots are entered, including payload type/keys.
          - Tracks workers in self._active_workers so signals can't be dropped by GC.
        """
        try:
            logger.info(
                "stats_view_start_step_worker_enter",
                extra={
                    "pipeline": getattr(pipeline_id, "name", str(pipeline_id)),
                    "step": getattr(step.id, "name", str(step.id)),
                    "step_name": getattr(step, "name", repr(step)),
                    "kwargs_keys": list(step.kwargs.keys()) if isinstance(step.kwargs, dict) else None,
                },
            )
        except Exception:
            logger.exception("stats_view_start_step_worker_log_enter_failed")

        self._log_pipeline_event(pipeline=pipeline_id, step=step.id, event="start")

        worker = StatsWorker(
            step.worker_fn,
            **step.kwargs,
            _op=step.name,
            _step_id=getattr(step.id, "name", str(step.id)),
        )

        try:
            logger.info(
                "stats_view_worker_created",
                extra={
                    "pipeline": getattr(pipeline_id, "name", str(pipeline_id)),
                    "step": getattr(step.id, "name", str(step.id)),
                    "worker_class": type(worker).__name__,
                },
            )
        except Exception:
            logger.exception("stats_view_worker_created_log_failed")

        # Track worker strongly so it cannot be garbage-collected while
        # signals are in-flight. This also gives us better diagnostics.
        try:
            if not hasattr(self, "_active_workers"):
                self._active_workers = []
            self._active_workers.append(worker)
            logger.info(
                "stats_view_worker_tracked",
                extra={
                    "pipeline": getattr(pipeline_id, "name", str(pipeline_id)),
                    "step": getattr(step.id, "name", str(step.id)),
                    "worker_id": id(worker),
                    "active_workers_len": len(self._active_workers),
                },
            )
        except Exception:
            logger.exception("stats_view_worker_tracked_log_failed")

        def _release_worker(w=worker, pid=pipeline_id, sid=step.id):
            """Remove the worker from the active set once it has finished/error'd."""
            try:
                active = getattr(self, "_active_workers", None)
                if active is not None and w in active:
                    active.remove(w)
                logger.info(
                    "stats_view_worker_released",
                    extra={
                        "pipeline": getattr(pid, "name", str(pid)),
                        "step": getattr(sid, "name", str(sid)),
                        "worker_id": id(w),
                        "active_workers_len": len(active) if active is not None else -1,
                    },
                )
            except Exception:
                logger.exception(
                    "stats_view_worker_release_failed",
                    extra={
                        "pipeline": getattr(pid, "name", str(pid)),
                        "step": getattr(sid, "name", str(sid)),
                    },
                )

        def _on_finished(payload, pid=pipeline_id, sid=step.id):
            # This is the first place we know the Qt finished signal reached the view.
            try:
                payload_type = type(payload).__name__
                payload_keys = list(payload.keys()) if isinstance(payload, dict) else None
            except Exception:
                payload_type = type(payload).__name__
                payload_keys = None

            logger.info(
                "stats_view_finished_slot_enter",
                extra={
                    "pipeline": getattr(pid, "name", str(pid)),
                    "step": getattr(sid, "name", str(sid)),
                    "payload_type": payload_type,
                    "payload_keys": payload_keys,
                    "is_harmonic_check": getattr(sid, "name", str(sid)) == "HARMONIC_CHECK",
                },
            )
            try:
                logger.info(
                    "stats_view_finished_before_controller",
                    extra={
                        "pipeline": getattr(pid, "name", str(pid)),
                        "step": getattr(sid, "name", str(sid)),
                    },
                )
                finished_cb(pid, sid, payload)
                logger.info(
                    "stats_view_finished_after_controller",
                    extra={
                        "pipeline": getattr(pid, "name", str(pid)),
                        "step": getattr(sid, "name", str(sid)),
                    },
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "stats_view_finished_controller_exception",
                    extra={
                        "pipeline": getattr(pid, "name", str(pid)),
                        "step": getattr(sid, "name", str(sid)),
                        "error": str(exc),
                    },
                )
                try:
                    section = self._section_label(pid)
                    self.append_log(
                        section,
                        f"ERROR handling results for {getattr(sid, 'name', sid)}: {exc}",
                        level="error",
                    )
                except Exception:
                    logger.exception("stats_view_finished_error_reporting_failed")
            finally:
                _release_worker()

        def _on_error(message: str, pid=pipeline_id, sid=step.id):
            logger.error(
                "stats_view_error_slot_enter",
                extra={
                    "pipeline": getattr(pid, "name", str(pid)),
                    "step": getattr(sid, "name", str(sid)),
                    "message": message,
                },
            )
            try:
                error_cb(pid, sid, message)
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "stats_view_error_slot_handler_error",
                    extra={
                        "pipeline": getattr(pid, "name", str(pid)),
                        "step": getattr(sid, "name", str(sid)),
                        "error": str(exc),
                    },
                )
            finally:
                _release_worker()

        worker.signals.finished.connect(_on_finished)
        worker.signals.error.connect(_on_error)
        worker.signals.message.connect(self._on_worker_message)
        if message_cb:
            worker.signals.message.connect(message_cb)
        worker.signals.progress.connect(self._on_worker_progress)

        try:
            logger.info(
                "stats_view_start_worker_submit",
                extra={
                    "pipeline": getattr(pipeline_id, "name", str(pipeline_id)),
                    "step": getattr(step.id, "name", str(step.id)),
                },
            )
        except Exception:
            logger.exception("stats_view_start_worker_submit_log_failed")

        self.pool.start(worker)

        try:
            logger.info(
                "stats_view_start_step_worker_exit",
                extra={
                    "pipeline": getattr(pipeline_id, "name", str(pipeline_id)),
                    "step": getattr(step.id, "name", str(step.id)),
                },
            )
        except Exception:
            logger.exception("stats_view_start_step_worker_exit_log_failed")

    def ensure_results_dir(self) -> str:
        return self._ensure_results_dir()

    def prompt_phase_folder(self, title: str, start_dir: str | None = None) -> Optional[str]:
        folder = QFileDialog.getExistingDirectory(self, title, start_dir or self.project_dir)
        return folder or None

    def get_analysis_settings_snapshot(self) -> tuple[float, float, dict, list[str]]:
        self.refresh_rois()
        got = self._get_analysis_settings()
        if not got:
            raise RuntimeError("Unable to load analysis settings.")
        self._current_base_freq, self._current_alpha = got
        self._update_fixed_k_base_freq_label()
        return self._current_base_freq, self._current_alpha, self.rois, self._get_selected_conditions()

    def ensure_pipeline_ready(
        self, pipeline_id: PipelineId, *, require_anova: bool = False
    ) -> bool:
        self._log_pipeline_event(pipeline=pipeline_id, event="start")
        if not self._precheck(require_anova=require_anova, start_guard=False):
            self._log_pipeline_event(
                pipeline=pipeline_id, event="end", extra={"reason": "precheck_failed"}
            )
            return False
        if pipeline_id is PipelineId.BETWEEN and not self._ensure_between_ready():
            self._log_pipeline_event(
                pipeline=pipeline_id, event="end", extra={"reason": "between_not_ready"}
            )
            return False
        self._log_pipeline_event(pipeline=pipeline_id, event="end")
        return True

    def on_pipeline_started(self, pipeline_id: PipelineId) -> None:
        self._active_pipeline = pipeline_id
        self._harmonic_results[pipeline_id] = []
        self._pipeline_conditions[pipeline_id] = self._get_selected_conditions()
        self._pipeline_dv_policy[pipeline_id] = self._get_dv_policy_payload()
        self._pipeline_base_freq[pipeline_id] = self._current_base_freq
        label = self.single_status_lbl if pipeline_id is PipelineId.SINGLE else self.between_status_lbl
        if label:
            label.setText("Running…")
        btn = self.analyze_single_btn if pipeline_id is PipelineId.SINGLE else self.analyze_between_btn
        if btn:
            btn.setEnabled(False)
        self._focus_self()
        self._log_pipeline_event(pipeline=pipeline_id, event="started")

    def on_analysis_finished(
        self,
        pipeline_id: PipelineId,
        success: bool,
        error_message: Optional[str],
        *,
        exports_ran: bool,
    ) -> None:
        logger.info(
            "stats_analysis_finished_enter",
            extra={
                "pipeline": pipeline_id.name,
                "success": success,
                "error_message": error_message or "",
                "exports_ran": bool(exports_ran),
            },
        )
        label = self.single_status_lbl if pipeline_id is PipelineId.SINGLE else self.between_status_lbl
        btn = self.analyze_single_btn if pipeline_id is PipelineId.SINGLE else self.analyze_between_btn
        try:
            if label:
                if success:
                    ts = datetime.now().strftime("%H:%M:%S")
                    label.setText(f"Last run OK at {ts}")
                else:
                    label.setText("Last run error (see log)")
            self._active_pipeline = None
            if success:
                section = self._section_label(pipeline_id)
                if exports_ran:
                    if pipeline_id is PipelineId.SINGLE:
                        self.append_log(section, "  • Results exported for Single Group Analysis")
                    elif pipeline_id is PipelineId.BETWEEN:
                        self.append_log(section, "  • Results exported for Between-Group Analysis")
                    stats_folder = Path(self._ensure_results_dir())
                    self._prompt_view_results(self._section_label(pipeline_id), stats_folder)
                else:
                    self.append_log(section, "  • Analysis completed", level="info")
            elif error_message:
                try:
                    QMessageBox.critical(self, "Analysis Error", error_message)
                except Exception:  # noqa: BLE001
                    logger.exception("Failed to display error dialog", exc_info=True)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "stats_view_on_finished_error",
                exc_info=True,
                extra={
                    "pipeline": pipeline_id.name,
                    "success": success,
                    "error_message": error_message,
                    "error": str(exc),
                },
            )
        finally:
            try:
                if btn:
                    btn.setEnabled(True)
            except Exception:  # noqa: BLE001
                logger.exception("stats_finish_button_enable_failed", exc_info=True)
            try:
                self._update_export_buttons()
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "stats_update_export_buttons_failed",
                    exc_info=True,
                    extra={"pipeline": pipeline_id.name, "error": str(exc)},
                )
            try:
                self._log_pipeline_event(
                    pipeline=pipeline_id, event="complete", extra={"success": success}
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "stats_pipeline_event_log_failed",
                    exc_info=True,
                    extra={"pipeline": pipeline_id.name, "error": str(exc)},
                )

    def closeEvent(self, event):  # type: ignore[override]
        logger.info(
            "stats_window_close_event",
            extra={
                "window_id": id(self),
                "project_dir": getattr(self, "project_dir", ""),
            },
        )
        super().closeEvent(event)

    def build_and_render_summary(self, pipeline_id: PipelineId) -> None:
        cfg = SummaryConfig(
            alpha=0.05,
            min_effect=0.50,
            max_bullets=3,
            z_threshold=self._harmonic_config.threshold,
            p_col="p_fdr",
            effect_col="effect_size",
        )
        frames = self._build_summary_frames(pipeline_id)
        summary_text = build_summary_from_frames(frames, cfg)
        self._render_summary(summary_text)

    def export_pipeline_results(self, pipeline_id: PipelineId) -> bool:
        if pipeline_id is PipelineId.SINGLE:
            return self._export_single_pipeline()
        if pipeline_id is PipelineId.BETWEEN:
            return self._export_between_pipeline()
        return False

    def _build_harmonic_kwargs(self) -> dict:
        # [SAFETY UPDATE] Load fresh ROIs from settings to ensure thread receives
        # the most up-to-date map, preventing 0xC0000005 errors.
        fresh_rois = load_rois_from_settings() or self.rois

        return dict(
            subject_data=self.subject_data,
            subjects=self.subjects,
            conditions=self._get_selected_conditions(),
            selected_metric=self._harmonic_config.metric,
            mean_value_threshold=self._harmonic_config.threshold,
            base_freq=self._current_base_freq,
            alpha=self._current_alpha,
            rois=fresh_rois,  # <--- Using fresh_rois instead of potentially stale self.rois
        )

    def get_step_config(
        self, pipeline_id: PipelineId, step_id: StepId
    ) -> tuple[dict, Callable[[dict], None]]:
        if pipeline_id is PipelineId.SINGLE:
            if step_id is StepId.RM_ANOVA:
                kwargs = dict(
                    subjects=self.subjects,
                    conditions=self._get_selected_conditions(),
                    subject_data=self.subject_data,
                    base_freq=self._current_base_freq,
                    rois=self.rois,
                    dv_policy=self._get_dv_policy_payload(),
                )
                if os.getenv("FPVS_RM_ANOVA_DIAG", "0").strip() == "1":
                    kwargs["results_dir"] = self._ensure_results_dir()
                def handler(payload):
                    self._apply_rm_anova_results(payload, update_text=False)

                return kwargs, handler
            if step_id is StepId.MIXED_MODEL:
                kwargs = dict(
                    subjects=self.subjects,
                    conditions=self._get_selected_conditions(),
                    subject_data=self.subject_data,
                    base_freq=self._current_base_freq,
                    alpha=self._current_alpha,
                    rois=self.rois,
                    subject_groups=self.subject_groups,
                    dv_policy=self._get_dv_policy_payload(),
                )
                def handler(payload):
                    self._apply_mixed_model_results(payload, update_text=False)

                return kwargs, handler
            if step_id is StepId.INTERACTION_POSTHOCS:
                kwargs = dict(
                    subjects=self.subjects,
                    conditions=self._get_selected_conditions(),
                    subject_data=self.subject_data,
                    base_freq=self._current_base_freq,
                    alpha=self._current_alpha,
                    rois=self.rois,
                    subject_groups=self.subject_groups,
                    dv_policy=self._get_dv_policy_payload(),
                )
                def handler(payload):
                    self._apply_posthoc_results(payload, update_text=True)

                return kwargs, handler
            if step_id is StepId.HARMONIC_CHECK:
                kwargs = self._build_harmonic_kwargs()

                def handler(payload, *, pid=pipeline_id):
                    self._apply_harmonic_results(payload, pipeline_id=pid, update_text=True)

                return kwargs, handler
        if pipeline_id is PipelineId.BETWEEN:
            if step_id is StepId.BETWEEN_GROUP_ANOVA:
                kwargs = dict(
                    subjects=self.subjects,
                    conditions=self._get_selected_conditions(),
                    subject_data=self.subject_data,
                    base_freq=self._current_base_freq,
                    rois=self.rois,
                    subject_groups=self.subject_groups,
                    dv_policy=self._get_dv_policy_payload(),
                )
                def handler(payload):
                    self._apply_between_anova_results(payload, update_text=False)

                return kwargs, handler
            if step_id is StepId.BETWEEN_GROUP_MIXED_MODEL:
                kwargs = dict(
                    subjects=self.subjects,
                    conditions=self._get_selected_conditions(),
                    subject_data=self.subject_data,
                    base_freq=self._current_base_freq,
                    alpha=self._current_alpha,
                    rois=self.rois,
                    subject_groups=self.subject_groups,
                    include_group=True,
                    dv_policy=self._get_dv_policy_payload(),
                )
                def handler(payload):
                    self._apply_between_mixed_results(payload, update_text=False)

                return kwargs, handler
            if step_id is StepId.GROUP_CONTRASTS:
                kwargs = dict(
                    subjects=self.subjects,
                    conditions=self._get_selected_conditions(),
                    subject_data=self.subject_data,
                    base_freq=self._current_base_freq,
                    alpha=self._current_alpha,
                    rois=self.rois,
                    subject_groups=self.subject_groups,
                    dv_policy=self._get_dv_policy_payload(),
                )
                def handler(payload):
                    self._apply_group_contrasts_results(payload, update_text=True)

                return kwargs, handler
            if step_id is StepId.HARMONIC_CHECK:
                kwargs = self._build_harmonic_kwargs()

                def handler(payload, *, pid=pipeline_id):
                    self._apply_harmonic_results(payload, pipeline_id=pid, update_text=True)

                return kwargs, handler
        raise ValueError(f"Unsupported step configuration for {pipeline_id} / {step_id}")

    def _prompt_view_results(self, section: str, stats_folder: Path) -> None:
        msg = QMessageBox(self)
        msg.setWindowTitle("Statistical Analysis Complete")
        msg.setText("Statistical analysis complete.\nView results?")
        msg.setIcon(QMessageBox.Information)
        msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        msg.setDefaultButton(QMessageBox.Yes)
        reply = msg.exec()

        if reply == QMessageBox.Yes:
            if stats_folder.is_dir():
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(stats_folder)))
            else:
                self.append_log(section, f"Stats folder not found: {stats_folder}", "error")

    def _export_single_pipeline(self) -> bool:
        section = "Single"
        exports = [
            ("anova", self.rm_anova_results_data, "RM-ANOVA"),
            ("lmm", self.mixed_model_results_data, "Mixed Model"),
            ("posthoc", self.posthoc_results_data, "Interaction Post-hocs"),
            ("harmonic", self._harmonic_results.get(PipelineId.SINGLE), "Harmonic Check"),
        ]
        out_dir = self._ensure_results_dir()

        try:
            paths: list[Path] = []

            for kind, data_obj, label in exports:
                if data_obj is None:
                    self.append_log(
                        section,
                        f"  • Skipping export for {label} (no data)",
                        level="warning",
                    )
                    continue

                result_paths = self.export_results(kind, data_obj, out_dir)

                if not result_paths:
                    # Only harmonic is allowed to “legitimately” export nothing
                    if kind == "harmonic":
                        self.append_log(
                            section,
                            f"  • Skipping export for {label} (no significant harmonics)",
                            level="warning",
                        )
                        continue

                    self.append_log(
                        section,
                        f"  • Export produced no files for {label}",
                        level="error",
                    )
                    return False

                paths.extend(result_paths)

            if paths:
                self.append_log(section, "  • Results exported to:")
                for p in paths:
                    self.append_log(section, f"      {p}")
                self._write_dv_metadata(out_dir, PipelineId.SINGLE)

            return True

        except Exception as exc:  # noqa: BLE001
            self.append_log(section, f"  • Export failed: {exc}", level="error")
            return False

    def _export_between_pipeline(self) -> bool:
        section = "Between"
        exports = [
            ("anova_between", self.between_anova_results_data, "Between-Group ANOVA"),
            ("lmm_between", self.between_mixed_model_results_data, "Between-Group Mixed Model"),
            ("group_contrasts", self.group_contrasts_results_data, "Group Contrasts"),
            ("harmonic", self._harmonic_results.get(PipelineId.BETWEEN), "Harmonic Check"),
        ]
        out_dir = self._ensure_results_dir()

        try:
            paths: list[Path] = []

            for kind, data_obj, label in exports:
                if data_obj is None:
                    self.append_log(
                        section,
                        f"  • Skipping export for {label} (no data)",
                        level="warning",
                    )
                    continue

                result_paths = self.export_results(kind, data_obj, out_dir)

                if not result_paths:
                    if kind == "harmonic":
                        self.append_log(
                            section,
                            f"  • Skipping export for {label} (no significant harmonics)",
                            level="warning",
                        )
                        continue

                    self.append_log(
                        section,
                        f"  • Export produced no files for {label}",
                        level="error",
                    )
                    return False

                paths.extend(result_paths)

            if paths:
                self.append_log(section, "  • Results exported to:")
                for p in paths:
                    self.append_log(section, f"      {p}")
                self._write_dv_metadata(out_dir, PipelineId.BETWEEN)

            return True

        except Exception as exc:  # noqa: BLE001
            self.append_log(section, f"  • Export failed: {exc}", level="error")
            return False

    # --------- worker signal handlers ---------

    @Slot(int)
    def _on_worker_progress(self, val: int) -> None:
        self._progress_updates.append(val)

    @Slot(str)
    def _on_worker_message(self, msg: str) -> None:
        self._set_detected_info(msg)

    @Slot(str)
    def _on_worker_error(self, msg: str) -> None:
        self.output_text.append(f"Error: {msg}")
        section = "General"
        try:
            if self._controller.is_running(PipelineId.SINGLE):
                section = "Single"
            elif self._controller.is_running(PipelineId.BETWEEN):
                section = "Between"
        except Exception:
            section = "General"
        self.append_log(section, f"Worker error: {msg}", level="error")
        self._end_run()

    def _apply_rm_anova_results(self, payload: dict, *, update_text: bool = True) -> str:
        self.rm_anova_results_data = payload.get("anova_df_results")
        alpha = getattr(self, "_current_alpha", 0.05)
        output_text = payload.get("output_text", "")

        if (
            (self.rm_anova_results_data is None or self.rm_anova_results_data.empty)
            and isinstance(output_text, str)
            and output_text.strip()
        ):
            section = self._section_label(PipelineId.SINGLE)
            self.append_log(
                section,
                f"  • RM-ANOVA note: {output_text.strip()}",
                level="warning",
            )

        output_text = build_rm_anova_output(self.rm_anova_results_data, alpha)
        if update_text:
            self.output_text.append(output_text)
        self._update_export_buttons()
        return output_text

    def _apply_between_anova_results(self, payload: dict, *, update_text: bool = True) -> str:
        self.between_anova_results_data = payload.get("anova_df_results")
        alpha = getattr(self, "_current_alpha", 0.05)

        output_text = build_between_anova_output(self.between_anova_results_data, alpha)
        if update_text:
            self.output_text.append(output_text)
        self._update_export_buttons()
        return output_text

    def _apply_mixed_model_results(self, payload: dict, *, update_text: bool = True) -> str:
        self.mixed_model_results_data = payload.get("mixed_results_df")
        output_text = payload.get("output_text", "")
        if update_text:
            self.output_text.append(output_text)
        self._update_export_buttons()
        return output_text

    def _apply_between_mixed_results(self, payload: dict, *, update_text: bool = True) -> str:
        if not isinstance(payload, dict):
            raise ValueError("Mixed-model payload must be a dict.")
        if "mixed_results_df" not in payload:
            raise ValueError("Mixed-model payload missing 'mixed_results_df'.")

        self.between_mixed_model_results_data = payload.get("mixed_results_df")
        output_text = payload.get("output_text", "")
        if update_text:
            self.output_text.append(output_text)
        self._update_export_buttons()
        return output_text

    def _apply_posthoc_results(self, payload: dict, *, update_text: bool = True) -> str:
        self.posthoc_results_data = payload.get("results_df")
        output_text = payload.get("output_text", "")
        if update_text:
            self.output_text.append(output_text)
        self._update_export_buttons()
        return output_text

    def _apply_group_contrasts_results(self, payload: dict, *, update_text: bool = True) -> str:
        self.group_contrasts_results_data = payload.get("results_df")
        output_text = payload.get("output_text", "")
        if update_text:
            self.output_text.append(output_text)
        self._update_export_buttons()
        return output_text

    def _apply_harmonic_results(
        self, payload: dict, *, pipeline_id: PipelineId, update_text: bool = True
    ) -> str:
        output_text = payload.get("output_text") or ""
        findings = payload.get("findings") or []
        if update_text:
            self.output_text.append(
                output_text.strip() or "(Harmonic check returned empty text. See logs for details.)"
            )
        self._harmonic_results[pipeline_id] = findings
        self.harmonic_check_results_data = findings
        self._update_export_buttons()
        return output_text

    @Slot(dict)
    def _on_rm_anova_finished(self, payload: dict) -> None:
        self._apply_rm_anova_results(payload)
        self._end_run()

    @Slot(dict)
    def _on_between_anova_finished(self, payload: dict) -> None:
        self._apply_between_anova_results(payload)
        self._end_run()

    @Slot(dict)
    def _on_mixed_model_finished(self, payload: dict) -> None:
        self._apply_mixed_model_results(payload)
        self._end_run()

    @Slot(dict)
    def _on_between_mixed_finished(self, payload: dict) -> None:
        self._apply_between_mixed_results(payload)
        self._end_run()

    @Slot(dict)
    def _on_posthoc_finished(self, payload: dict) -> None:
        self._apply_posthoc_results(payload)
        self._end_run()

    @Slot(dict)
    def _on_group_contrasts_finished(self, payload: dict) -> None:
        self._apply_group_contrasts_results(payload)
        self._end_run()

    @Slot(dict)
    def _on_harmonic_finished(self, payload: dict) -> None:
        pipeline_id = self._active_pipeline or PipelineId.SINGLE
        self._apply_harmonic_results(payload, pipeline_id=pipeline_id)
        self._end_run()

    @Slot(object)
    def _on_lela_mode_finished(self, stats_folder: Path | None = None) -> None:
        try:
            section = self._section_label(PipelineId.BETWEEN)
            self.append_log(section, "[Between] Lela Mode: complete — see Cross-Phase LMM Analysis.xlsx")
            if stats_folder:
                self.append_log(section, f"  • Excel: {stats_folder}")
        finally:
            self._end_run()

    @Slot(str)
    def _on_lela_mode_error(self, message: str) -> None:
        try:
            section = self._section_label(PipelineId.BETWEEN)
            self.append_log(section, f"[Between] Lela Mode error: {message}", level="error")
        finally:
            self._end_run()

    # --------------------------- UI building ---------------------------

    def _init_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        # included conditions panel
        self.conditions_group = QGroupBox("Included Conditions")
        self.conditions_group.setSizePolicy(QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed))
        conditions_layout = QVBoxLayout(self.conditions_group)
        conditions_layout.setSpacing(6)

        conditions_button_row = QHBoxLayout()
        self.conditions_select_all_btn = QPushButton("Select All")
        self.conditions_select_all_btn.clicked.connect(self._select_all_conditions)
        conditions_button_row.addWidget(self.conditions_select_all_btn)
        self.conditions_select_none_btn = QPushButton("Select None")
        self.conditions_select_none_btn.clicked.connect(self._select_no_conditions)
        conditions_button_row.addWidget(self.conditions_select_none_btn)
        conditions_button_row.addStretch(1)
        conditions_layout.addLayout(conditions_button_row)

        self.conditions_scroll_area = QScrollArea()
        self.conditions_scroll_area.setWidgetResizable(True)
        self.conditions_scroll_area.setMinimumHeight(120)
        conditions_list_widget = QWidget()
        self.conditions_list_layout = QVBoxLayout(conditions_list_widget)
        self.conditions_list_layout.setContentsMargins(0, 0, 0, 0)
        self.conditions_list_layout.setSpacing(4)
        self.conditions_scroll_area.setWidget(conditions_list_widget)
        conditions_layout.addWidget(self.conditions_scroll_area)

        main_layout.addWidget(self.conditions_group)

        # summed BCA definition panel
        self.dv_group = QGroupBox("Summed BCA definition")
        self.dv_group.setSizePolicy(QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed))
        dv_layout = QVBoxLayout(self.dv_group)
        dv_layout.setSpacing(6)

        dv_method_row = QHBoxLayout()
        dv_method_row.addWidget(QLabel("Method:"))
        self.dv_policy_combo = QComboBox()
        self.dv_policy_combo.addItems([LEGACY_POLICY_NAME, FIXED_K_POLICY_NAME])
        self.dv_policy_combo.setCurrentText(self._dv_policy_name)
        self.dv_policy_combo.currentTextChanged.connect(self._on_dv_policy_changed)
        dv_method_row.addWidget(self.dv_policy_combo, 1)
        dv_layout.addLayout(dv_method_row)

        fixed_form = QFormLayout()
        fixed_form.setLabelAlignment(Qt.AlignLeft)
        fixed_form.setFormAlignment(Qt.AlignLeft)
        fixed_form.setHorizontalSpacing(10)
        fixed_form.setVerticalSpacing(6)

        self.fixed_k_spinbox = QSpinBox()
        self.fixed_k_spinbox.setRange(1, 50)
        self.fixed_k_spinbox.setValue(self._dv_fixed_k)
        self.fixed_k_spinbox.valueChanged.connect(self._on_fixed_k_changed)
        fixed_form.addRow("K:", self.fixed_k_spinbox)

        self.fixed_k_exclude_h1 = QCheckBox("Exclude harmonic 1")
        self.fixed_k_exclude_h1.setChecked(self._dv_exclude_harmonic1)
        self.fixed_k_exclude_h1.stateChanged.connect(self._on_fixed_k_exclude_h1_changed)
        fixed_form.addRow("", self.fixed_k_exclude_h1)

        self.fixed_k_exclude_base = QCheckBox("Exclude base-rate harmonics")
        self.fixed_k_exclude_base.setChecked(self._dv_exclude_base_harmonics)
        self.fixed_k_exclude_base.stateChanged.connect(self._on_fixed_k_exclude_base_changed)
        fixed_form.addRow("", self.fixed_k_exclude_base)

        self.fixed_k_base_freq_value = QLabel(f"{self._current_base_freq:g} Hz")
        self.fixed_k_base_freq_value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        fixed_form.addRow("Base frequency:", self.fixed_k_base_freq_value)

        dv_layout.addLayout(fixed_form)
        self._set_fixed_k_controls_enabled(self._dv_policy_name == FIXED_K_POLICY_NAME)

        main_layout.addWidget(self.dv_group)

        # folder row
        folder_row = QHBoxLayout()
        folder_row.setSpacing(5)
        self.le_folder = QLineEdit()
        self.le_folder.setReadOnly(True)
        btn_browse = QPushButton("Browse…")
        btn_browse.clicked.connect(self.on_browse_folder)
        folder_row.addWidget(QLabel("Data Folder:"))
        folder_row.addWidget(self.le_folder, 1)
        folder_row.addWidget(btn_browse)
        main_layout.addLayout(folder_row)

        # open results (scan button removed)
        tools_row = QHBoxLayout()
        self.btn_open_results = QPushButton("Open Results Folder")
        self.btn_open_results.clicked.connect(self._open_results_folder)
        # widen a bit to pad text
        fm = QFontMetrics(self.btn_open_results.font())
        self.btn_open_results.setMinimumWidth(fm.horizontalAdvance(self.btn_open_results.text()) + 24)
        tools_row.addWidget(self.btn_open_results)
        self.info_button = QPushButton("Analysis Info")
        self.info_button.clicked.connect(self.on_show_analysis_info)
        tools_row.addWidget(self.info_button)
        tools_row.addStretch(1)
        main_layout.addLayout(tools_row)

        analysis_box = QGroupBox("Analysis Controls")
        analysis_box.setSizePolicy(QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed))
        analysis_layout = QVBoxLayout(analysis_box)
        analysis_layout.setSpacing(8)

        # single group section
        single_group_box = QGroupBox("Single Group Analysis")
        single_group_box.setSizePolicy(QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed))
        single_layout = QVBoxLayout(single_group_box)

        single_action_row = QHBoxLayout()
        self.analyze_single_btn = QPushButton("Analyze Single Group")
        self.analyze_single_btn.clicked.connect(self.on_analyze_single_group_clicked)
        single_action_row.addWidget(self.analyze_single_btn)

        self.single_advanced_btn = QPushButton("Advanced…")
        self.single_advanced_btn.clicked.connect(self.on_single_advanced_clicked)
        single_action_row.addWidget(self.single_advanced_btn)
        single_layout.addLayout(single_action_row)

        self.single_status_lbl = QLabel("Idle")
        self.single_status_lbl.setWordWrap(True)
        single_layout.addWidget(self.single_status_lbl)

        # between-group section
        between_box = QGroupBox("Between-Group Analysis")
        between_box.setSizePolicy(QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed))
        between_layout = QVBoxLayout(between_box)

        between_action_row = QHBoxLayout()
        self.analyze_between_btn = QPushButton("Analyze Group Differences")
        self.analyze_between_btn.clicked.connect(self.on_analyze_between_groups_clicked)
        between_action_row.addWidget(self.analyze_between_btn)

        self.between_advanced_btn = QPushButton("Advanced…")
        self.between_advanced_btn.clicked.connect(self.on_between_advanced_clicked)
        between_action_row.addWidget(self.between_advanced_btn)
        between_layout.addLayout(between_action_row)

        self.lela_mode_btn = QPushButton("Lela Mode (Cross-Phase LMM)")
        self.lela_mode_btn.clicked.connect(self.on_run_lela_mode)
        between_layout.addWidget(self.lela_mode_btn)

        self.between_status_lbl = QLabel("Idle")
        self.between_status_lbl.setWordWrap(True)
        between_layout.addWidget(self.between_status_lbl)

        analysis_layout.addWidget(single_group_box)
        analysis_layout.addWidget(between_box)
        main_layout.addWidget(analysis_box)

        # status + ROI labels with spinner
        status_row = QHBoxLayout()
        self.spinner = BusySpinner()
        self.spinner.setFixedSize(18, 18)
        self.spinner.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.spinner.hide()
        status_row.addWidget(self.spinner, alignment=Qt.AlignLeft)

        self.lbl_status = QLabel("Select a folder containing FPVS results.")
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        status_row.addWidget(self.lbl_status, 1)
        main_layout.addLayout(status_row)

        self.lbl_rois = QLabel("")
        self.lbl_rois.setWordWrap(True)
        self.lbl_rois.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        main_layout.addWidget(self.lbl_rois)

        # output pane
        self.output_text = QTextEdit()
        self.output_text.setReadOnly(True)
        self.output_text.setAcceptRichText(True)
        self.output_text.setPlaceholderText("Analysis output")
        self.output_text.setMinimumHeight(140)
        self.output_text.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        main_layout.addWidget(self.output_text, 1)

        main_layout.setStretch(0, 0)  # conditions panel
        main_layout.setStretch(1, 0)  # summed BCA panel
        main_layout.setStretch(2, 0)  # folder row
        main_layout.setStretch(3, 0)  # tools row
        main_layout.setStretch(4, 0)  # analysis controls
        main_layout.setStretch(5, 0)  # status row
        main_layout.setStretch(6, 0)  # ROI label
        main_layout.setStretch(7, 1)  # output pane

        # initialize export buttons
        self._update_export_buttons()
        self._populate_conditions_panel([])

    # --------------------------- actions ---------------------------

    def on_analyze_single_group_clicked(self) -> None:
        self._controller.run_single_group_analysis()

    def on_analyze_between_groups_clicked(self) -> None:
        self._controller.run_between_group_analysis()

    def _open_advanced_dialog(self, title: str, actions: list[tuple[str, Callable[[], None], bool]]) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        layout = QVBoxLayout(dialog)
        for text, cb, enabled in actions:
            btn = QPushButton(text)
            btn.setEnabled(enabled)
            btn.clicked.connect(cb)
            layout.addWidget(btn)
        layout.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    def on_single_advanced_clicked(self) -> None:
        actions = [
            ("Run RM-ANOVA", self.on_run_rm_anova, True),
            ("Run Mixed Model", self.on_run_mixed_model, True),
            ("Run Interaction/Post-hocs", self.on_run_interaction_posthocs, True),
            (
                "Export RM-ANOVA",
                self.on_export_rm_anova,
                isinstance(self.rm_anova_results_data, pd.DataFrame) and not self.rm_anova_results_data.empty,
            ),
            (
                "Export Mixed Model",
                self.on_export_mixed_model,
                isinstance(self.mixed_model_results_data, pd.DataFrame) and not self.mixed_model_results_data.empty,
            ),
            (
                "Export Post-hocs",
                self.on_export_posthoc,
                isinstance(self.posthoc_results_data, pd.DataFrame) and not self.posthoc_results_data.empty,
            ),
        ]
        self._open_advanced_dialog("Single Group – Advanced", actions)

    def on_between_advanced_clicked(self) -> None:
        actions = [
            ("Run Between-Group ANOVA", self.on_run_between_anova, True),
            ("Run Between-Group Mixed Model", self.on_run_between_mixed_model, True),
            ("Run Group Contrasts", self.on_run_group_contrasts, True),
            (
                "Export Between-Group ANOVA",
                self.on_export_between_anova,
                isinstance(self.between_anova_results_data, pd.DataFrame)
                and not self.between_anova_results_data.empty,
            ),
            (
                "Export Between-Group Mixed Model",
                self.on_export_between_mixed,
                isinstance(self.between_mixed_model_results_data, pd.DataFrame)
                and not self.between_mixed_model_results_data.empty,
            ),
            (
                "Export Group Contrasts",
                self.on_export_group_contrasts,
                isinstance(self.group_contrasts_results_data, pd.DataFrame)
                and not self.group_contrasts_results_data.empty,
            ),
        ]
        self._open_advanced_dialog("Between-Group – Advanced", actions)

    def on_show_analysis_info(self) -> None:
        """
        Show a brief summary of the statistical methods used in the Stats tool.
        This is read-only and does not modify any data or settings.
        """
        text = (
            "FPVS Toolbox – Statistical Pipeline Overview\n\n"
            "Data analyzed\n"
            "• All analyses use the summed baseline-corrected oddball amplitude "
            "(Summed BCA) per subject × condition × ROI.\n\n"
            "Single-group analyses\n"
            "• RM-ANOVA: Repeated-measures ANOVA with within-subject factors "
            "condition and ROI. When available, Pingouin's rm_anova is used and "
            "both uncorrected and Greenhouse–Geisser/Huynh–Feldt corrected p-values "
            "are reported; otherwise statsmodels' AnovaRM is used (uncorrected p-values).\n"
            "• Post-hoc tests: Paired t-tests between conditions, run separately within "
            "each ROI. P-values are corrected for multiple comparisons using the "
            "Benjamini–Hochberg false discovery rate (FDR) procedure; exports include "
            "raw p and FDR-adjusted p (p_fdr_bh) plus effect sizes.\n"
            "• Mixed model: Linear mixed-effects model with a random intercept for each "
            "subject and fixed effects for condition, ROI, and their interaction. No "
            "additional multiple-comparison correction is applied to these coefficients.\n\n"
            "Multi-group analyses\n"
            "• Between-group ANOVA: Mixed ANOVA with group as a between-subject factor "
            "and condition as a within-subject factor on Summed BCA (ROI collapsed). "
            "Pingouin's mixed_anova is used when available.\n"
            "• Between-group mixed model: Linear mixed-effects model on Summed BCA with "
            "fixed effects for group, condition, ROI, and their interactions, plus a "
            "random intercept per subject.\n"
            "• Group contrasts: Pairwise group comparisons (Welch's t-tests) computed "
            "separately for each condition × ROI. P-values are corrected for multiple "
            "comparisons using Benjamini–Hochberg FDR, and effect sizes (Cohen's d) "
            "are reported.\n\n"
            "General notes\n"
            "• Unless otherwise noted, the default alpha level is 0.05.\n"
            f"• Excel exports in the '{RESULTS_SUBFOLDER_NAME}' folder contain "
            "the full tables for all analyses, including raw and corrected p-values.\n"
        )

        QMessageBox.information(
            self,
            "FPVS Toolbox – Analysis Info",
            text,
        )

    def _check_for_open_excel_files(self, folder_path: str) -> bool:
        """Best-effort check to avoid writing to open Excel files."""
        open_files = check_for_open_excel_files(folder_path)
        if open_files:
            file_list_str = "\n - ".join(open_files)
            error_message = (
                "The following Excel file(s) appear to be open:\n\n"
                f"<b> - {file_list_str}</b>\n\n"
                "Please close all Excel files in the data directory and try again."
            )
            QMessageBox.critical(self, "Open Excel File Detected", error_message)
            return True
        return False

    # ---- run buttons ----

    def on_run_rm_anova(self) -> None:
        self.output_text.clear()
        self.rm_anova_results_data = None
        self._update_export_buttons()
        self._controller.run_single_group_rm_anova_only()

    def on_run_mixed_model(self) -> None:
        self.output_text.clear()
        self.mixed_model_results_data = None
        self._update_export_buttons()
        self._controller.run_single_group_mixed_model_only()

    def on_run_between_anova(self) -> None:
        self.output_text.clear()
        self.between_anova_results_data = None
        self._update_export_buttons()
        self._controller.run_between_group_anova_only()

    def on_run_between_mixed_model(self) -> None:
        self.output_text.clear()
        self.between_mixed_model_results_data = None
        self._update_export_buttons()
        self._controller.run_between_group_mixed_only()

    def on_run_lela_mode(self) -> None:
        """
        Run Lela mode (cross-phase single + between analyses).

        This mirrors the other run buttons by:
        - going through _precheck with start_guard=True (which calls _begin_run()),
        - delegating the actual work to the controller, and
        - making sure _end_run() is called if the controller raises.
        """
        # If your other run-* methods clear output/results first, you can mirror that here.
        # Keeping this minimal to avoid changing behavior.
        if not self._precheck(start_guard=True, require_anova=False):
            return

        try:
            self._controller.run_lela_mode_analysis()
        except Exception:
            # Ensure the guard / busy state is released even on error
            self._end_run()
            raise

    def on_run_group_contrasts(self) -> None:
        self.output_text.clear()
        self.group_contrasts_results_data = None
        self._update_export_buttons()
        self._controller.run_between_group_contrasts_only()

    def on_run_interaction_posthocs(self) -> None:
        self.output_text.clear()
        self.posthoc_results_data = None
        our = self._update_export_buttons  # keep line short
        our()
        self._controller.run_single_group_posthoc_only()

    # ---- exports ----

    def on_export_rm_anova(self) -> None:
        if not isinstance(self.rm_anova_results_data, pd.DataFrame) or self.rm_anova_results_data.empty:
            QMessageBox.information(self, "No Results", "Run RM-ANOVA first.")
            return
        out_dir = self._ensure_results_dir()
        try:
            self.export_results("anova", self.rm_anova_results_data, out_dir)
            self._set_status(f"RM-ANOVA exported to: {out_dir}")
        except Exception as e:
            import traceback
            logger.exception("RM-ANOVA export failed.")
            tb = traceback.format_exc()
            QMessageBox.critical(self, "Export Failed", f"{type(e).__name__}: {e}\n\n{tb}")

    def on_export_mixed_model(self) -> None:
        if not isinstance(self.mixed_model_results_data, pd.DataFrame) or self.mixed_model_results_data.empty:
            QMessageBox.information(self, "No Results", "Run Mixed Model first.")
            return
        out_dir = self._ensure_results_dir()
        try:
            self.export_results("lmm", self.mixed_model_results_data, out_dir)
            self._set_status(f"Mixed Model results exported to: {out_dir}")
        except Exception as e:
            import traceback
            logger.exception("Mixed Model export failed.")
            tb = traceback.format_exc()
            QMessageBox.critical(self, "Export Failed", f"{type(e).__name__}: {e}\n\n{tb}")

    def on_export_between_anova(self) -> None:
        if not isinstance(self.between_anova_results_data, pd.DataFrame) or self.between_anova_results_data.empty:
            QMessageBox.information(self, "No Results", "Run Between-Group ANOVA first.")
            return
        out_dir = self._ensure_results_dir()
        try:
            self.export_results("anova_between", self.between_anova_results_data, out_dir)
            self._set_status(f"Between-group ANOVA exported to: {out_dir}")
        except Exception as e:
            import traceback
            logger.exception("Between-group ANOVA export failed.")
            tb = traceback.format_exc()
            QMessageBox.critical(self, "Export Failed", f"{type(e).__name__}: {e}\n\n{tb}")

    def on_export_between_mixed(self) -> None:
        if not isinstance(self.between_mixed_model_results_data,
                          pd.DataFrame) or self.between_mixed_model_results_data.empty:
            QMessageBox.information(self, "No Results", "Run Between-Group Mixed Model first.")
            return
        out_dir = self._ensure_results_dir()
        try:
            self.export_results("lmm_between", self.between_mixed_model_results_data, out_dir)
            self._set_status(f"Between-group Mixed Model exported to: {out_dir}")
        except Exception as e:
            import traceback
            logger.exception("Between-group Mixed Model export failed.")
            tb = traceback.format_exc()
            QMessageBox.critical(self, "Export Failed", f"{type(e).__name__}: {e}\n\n{tb}")

    def on_export_posthoc(self) -> None:
        if not isinstance(self.posthoc_results_data, pd.DataFrame) or self.posthoc_results_data.empty:
            QMessageBox.information(self, "No Results", "Run Interaction Post-hocs first.")
            return
        out_dir = self._ensure_results_dir()
        try:
            self.export_results("posthoc", self.posthoc_results_data, out_dir)
            self._set_status(f"Post-hoc results exported to: {out_dir}")
        except Exception as e:
            import traceback
            logger.exception("Post-hoc export failed.")
            tb = traceback.format_exc()
            QMessageBox.critical(self, "Export Failed", f"{type(e).__name__}: {e}\n\n{tb}")

    def on_export_group_contrasts(self) -> None:
        if not isinstance(self.group_contrasts_results_data, pd.DataFrame) or self.group_contrasts_results_data.empty:
            QMessageBox.information(self, "No Results", "Run Group Contrasts first.")
            return
        out_dir = self._ensure_results_dir()
        try:
            self.export_results("group_contrasts", self.group_contrasts_results_data, out_dir)
            self._set_status(f"Group contrasts exported to: {out_dir}")
        except Exception as e:
            import traceback
            logger.exception("Group contrasts export failed.")
            tb = traceback.format_exc()
            QMessageBox.critical(self, "Export Failed", f"{type(e).__name__}: {e}\n\n{tb}")

    # ---- folder & scan ----

    def on_browse_folder(self) -> None:
        start_dir = self.le_folder.text() or self.project_dir
        folder = QFileDialog.getExistingDirectory(self, "Select Data Folder", start_dir)
        if folder:
            self.le_folder.setText(folder)
            self._scan_button_clicked()

    def _scan_button_clicked(self) -> None:
        if not self._scan_guard.start():
            return
        try:
            self.refresh_rois()
            folder = self.le_folder.text()
            if not folder:
                QMessageBox.warning(self, "No Folder", "Please select a data folder first.")
                return
            try:
                scan_result = load_project_scan(folder)
                self.subject_groups = {}
                self._multi_group_manifest = scan_result.multi_group_manifest

                if scan_result.multi_group_manifest:
                    self._warn_unknown_excel_files(scan_result.subject_data, scan_result.participants_map)

                self.subjects = scan_result.subjects
                self.conditions = scan_result.conditions
                self._populate_conditions_panel(self.conditions)
                self.subject_data = scan_result.subject_data
                self.subject_groups = scan_result.subject_groups
                self._set_status(
                    f"Scan complete: Found {len(scan_result.subjects)} subjects and {len(scan_result.conditions)} conditions."
                )
            except ScanError as e:
                self._set_status(f"Scan failed: {e}")
                QMessageBox.critical(self, "Scan Error", str(e))
        finally:
            self._scan_guard.done()


    def _preferred_stats_folder(self) -> Path:
        """Default Excel folder derived from the project manifest."""
        return resolve_project_subfolder(
            self._project_path,
            self._results_folder_hint,
            self._subfolder_hints,
            "excel",
            EXCEL_SUBFOLDER_NAME,
        )

    def _load_default_data_folder(self) -> None:
        """
        On open, auto-select the manifest-defined Excel folder (defaults to
        ``1 - Excel Data Files`` under the project root). If it doesn't exist,
        do nothing (user can Browse).
        """
        target = self._preferred_stats_folder()
        if target.exists() and target.is_dir():
            self.le_folder.setText(str(target))
            self._scan_button_clicked()
        else:
            # Leave UI as-is; user will browse. Status hint only.
            self._set_status(
                f"Select the project's '{EXCEL_SUBFOLDER_NAME}' folder to begin."
            )
