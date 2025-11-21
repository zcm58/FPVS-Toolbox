# src/Tools/Stats/PySide6/stats_main_window.py
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from PySide6.QtCore import Qt, QTimer, QThreadPool, Slot, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QFontMetrics, QTextCursor
from PySide6.QtWidgets import (
    QFileDialog,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QComboBox,
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
from Tools.Stats.PySide6.stats_core import PipelineId, PipelineStep, RESULTS_SUBFOLDER_NAME, StepId
from Tools.Stats.PySide6.stats_data_loader import (
    ScanError,
    auto_detect_project_dir,
    load_manifest_data,
    load_project_scan,
    resolve_project_subfolder,
)
from Tools.Stats.PySide6.stats_logging import format_log_line, format_section_header
from Tools.Stats.PySide6.stats_worker import StatsWorker
from Tools.Stats.PySide6.summary_utils import (
    StatsSummaryFrames,
    SummaryConfig,
    build_summary_from_frames,
)

logger = logging.getLogger(__name__)
_unused_qaction = QAction  # keep import alive for Qt resource checkers

# --------------------------- constants ---------------------------
ANOVA_XLS = "RM-ANOVA Results.xlsx"
LMM_XLS = "Mixed Model Results.xlsx"
POSTHOC_XLS = "Posthoc Results.xlsx"
HARMONIC_XLS = "Harmonic Results.xlsx"
ANOVA_BETWEEN_XLS = "Mixed ANOVA Between Groups.xlsx"
LMM_BETWEEN_XLS = "Mixed Model Between Groups.xlsx"
GROUP_CONTRAST_XLS = "Group Contrasts.xlsx"


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

        self._guard = OpGuard()
        if not hasattr(self._guard, "done"):
            self._guard.done = self._guard.end  # type: ignore[attr-defined]
        self.pool = QThreadPool.globalInstance()
        self._focus_calls = 0

        self.setMinimumSize(900, 600)
        self.resize(1000, 750)

        # re-entrancy guard for scan
        self._scan_guard = OpGuard()
        if not hasattr(self._scan_guard, "done"):
            self._scan_guard.done = self._scan_guard.end  # type: ignore[attr-defined]

        # --- state ---
        self.subject_data: Dict = {}
        self.subject_groups: Dict[str, str | None] = {}
        self.subjects: List[str] = []
        self.conditions: List[str] = []
        self._multi_group_manifest: bool = False
        self.rm_anova_results_data: Optional[pd.DataFrame] = None
        self.mixed_model_results_data: Optional[pd.DataFrame] = None
        self.between_anova_results_data: Optional[pd.DataFrame] = None
        self.between_mixed_model_results_data: Optional[pd.DataFrame] = None
        self.group_contrasts_results_data: Optional[pd.DataFrame] = None
        self.posthoc_results_data: Optional[pd.DataFrame] = None
        self.harmonic_check_results_data: List[dict] = []
        self.rois: Dict[str, List[str]] = {}
        self._harmonic_metric: str = ""
        self._current_base_freq: float = 6.0
        self._current_alpha: float = 0.05
        self._active_pipeline: PipelineId | None = None

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
            getattr(self, "run_harm_btn", None),
            getattr(self, "export_harm_btn", None),
            getattr(self, "analyze_between_btn", None),
            getattr(self, "between_advanced_btn", None),
            getattr(self, "btn_open_results", None),
        ]
        for b in buttons:
            if b:
                b.setEnabled(not running)
        if running:
            self.spinner.show()
            self.spinner.start()
        else:
            self.spinner.stop()
            self.spinner.hide()

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

    def _get_z_threshold_from_gui(self) -> float:
        try:
            return float(self.threshold_spin.value())
        except Exception:
            return 1.64

    # --------- centralized pre-run guards ---------

    def _precheck(self, *, require_anova: bool = False, start_guard: bool = True) -> bool:
        if self._check_for_open_excel_files(self.le_folder.text()):
            return False
        if not self.subject_data:
            QMessageBox.warning(self, "No Data", "Please select a valid data folder first.")
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
        if start_guard and not self._begin_run():
            return False
        return True

    # --------- exports plumbing ---------

    def _group_harmonic(self, data) -> dict:
        """list[dict] -> {condition: {roi: [records]}}"""
        if isinstance(data, dict):
            return data
        grouped: dict[str, dict[str, list[dict]]] = {}
        for rec in data or []:
            if not isinstance(rec, dict):
                continue
            cond = rec.get("Condition") or rec.get("condition") or "Unknown"
            roi = rec.get("ROI") or rec.get("roi") or "Unknown"
            grouped.setdefault(cond, {}).setdefault(roi, []).append(rec)
        return grouped

    def _safe_export_call(self, func, data_obj, out_dir: str, base_name: str) -> None:
        os.makedirs(out_dir, exist_ok=True)
        fname = base_name if base_name.lower().endswith(".xlsx") else f"{base_name}.xlsx"
        save_path = os.path.join(out_dir, fname)
        try:
            func(
                data_obj,
                save_path=save_path,
                log_func=self._set_status,
            )
            return
        except TypeError:
            func(data_obj, out_dir, log_func=self._set_status)

    def export_results(self, kind: str, data, out_dir: str) -> None:
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
        if kind == "harmonic":
            grouped = self._group_harmonic(data)

            def _adapter(_ignored, *, save_path, log_func):
                export_harmonic_results_to_excel(
                    grouped,
                    save_path,
                    log_func,
                    metric=(self._harmonic_metric or ""),
                )

            self._safe_export_call(_adapter, None, out_dir, fname)
            return

        self._safe_export_call(func, data, out_dir, fname)

    def _ensure_results_dir(self) -> str:
        target = resolve_project_subfolder(
            self._project_path,
            self._results_folder_hint,
            self._subfolder_hints,
            "stats",
            STATS_SUBFOLDER_NAME,
        )
        target.mkdir(parents=True, exist_ok=True)
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
        _maybe_enable("export_harm_btn", bool(self.harmonic_check_results_data))
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

    def _to_dataframe(self, data) -> Optional[pd.DataFrame]:
        if isinstance(data, pd.DataFrame):
            return data
        if isinstance(data, list) and data:
            try:
                df = pd.DataFrame(data)
                return df if not df.empty else None
            except Exception:
                return None
        if isinstance(data, dict) and data:
            try:
                df = pd.DataFrame(data)
                if not df.empty:
                    return df
            except Exception:
                pass
            try:
                flattened: list = []
                for value in data.values():
                    if isinstance(value, dict):
                        flattened.extend(value.values())
                    else:
                        flattened.append(value)
                if flattened:
                    df = pd.DataFrame(flattened)
                    return df if not df.empty else None
            except Exception:
                return None
        return None

    def _build_summary_frames(self, pipeline_id: PipelineId) -> StatsSummaryFrames:
        frames = StatsSummaryFrames()
        if pipeline_id is PipelineId.SINGLE:
            frames.single_posthoc = self._to_dataframe(self.posthoc_results_data)
            frames.anova_terms = self._to_dataframe(self.rm_anova_results_data)
            frames.mixed_model_terms = self._to_dataframe(self.mixed_model_results_data)
        elif pipeline_id is PipelineId.BETWEEN:
            frames.between_contrasts = self._to_dataframe(self.group_contrasts_results_data)
            frames.anova_terms = self._to_dataframe(self.between_anova_results_data)
            frames.mixed_model_terms = self._to_dataframe(self.between_mixed_model_results_data)
        frames.harmonic_results = self._to_dataframe(self.harmonic_check_results_data)
        return frames

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
        except Exception:  # noqa: BLE001
            logger.exception("stats_set_busy_failed", exc_info=True)

    def start_step_worker(
        self,
        pipeline_id: PipelineId,
        step: PipelineStep,
        *,
        finished_cb,
        error_cb,
    ) -> None:
        self._log_pipeline_event(pipeline=pipeline_id, step=step.id, event="start")
        worker = StatsWorker(step.worker_fn, **step.kwargs)
        worker.signals.finished.connect(
            lambda payload, pid=pipeline_id, sid=step.id: finished_cb(pid, sid, payload)
        )
        worker.signals.error.connect(
            lambda msg, pid=pipeline_id, sid=step.id: error_cb(pid, sid, msg)
        )
        worker.signals.message.connect(self._on_worker_message)
        worker.signals.progress.connect(self._on_worker_progress)
        self.pool.start(worker)

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
        except Exception:  # noqa: BLE001
            logger.exception("stats_on_analysis_finished_failed", exc_info=True)
        finally:
            try:
                if btn:
                    btn.setEnabled(True)
            except Exception:  # noqa: BLE001
                logger.exception("stats_finish_button_enable_failed", exc_info=True)
            self._update_export_buttons()
            self._log_pipeline_event(
                pipeline=pipeline_id, event="complete", extra={"success": success}
            )

    def build_and_render_summary(self, pipeline_id: PipelineId) -> None:
        cfg = SummaryConfig(
            alpha=0.05,
            min_effect=0.50,
            max_bullets=3,
            z_threshold=self._get_z_threshold_from_gui(),
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

    def get_step_config(
        self, pipeline_id: PipelineId, step_id: StepId
    ) -> tuple[dict, Callable[[dict], None]]:
        if pipeline_id is PipelineId.SINGLE:
            if step_id is StepId.RM_ANOVA:
                kwargs = dict(
                    subjects=self.subjects,
                    conditions=self.conditions,
                    subject_data=self.subject_data,
                    base_freq=self._current_base_freq,
                    rois=self.rois,
                )
                def handler(payload):
                    self._apply_rm_anova_results(payload, update_text=False)

                return kwargs, handler
            if step_id is StepId.MIXED_MODEL:
                kwargs = dict(
                    subjects=self.subjects,
                    conditions=self.conditions,
                    subject_data=self.subject_data,
                    base_freq=self._current_base_freq,
                    alpha=self._current_alpha,
                    rois=self.rois,
                    subject_groups=self.subject_groups,
                )
                def handler(payload):
                    self._apply_mixed_model_results(payload, update_text=False)

                return kwargs, handler
            if step_id is StepId.INTERACTION_POSTHOCS:
                kwargs = dict(
                    subjects=self.subjects,
                    conditions=self.conditions,
                    subject_data=self.subject_data,
                    base_freq=self._current_base_freq,
                    alpha=self._current_alpha,
                    rois=self.rois,
                    subject_groups=self.subject_groups,
                )
                def handler(payload):
                    self._apply_posthoc_results(payload, update_text=True)

                return kwargs, handler
            if step_id is StepId.HARMONIC_CHECK:
                selected_metric = self.cb_metric.currentText()
                mean_value_threshold = float(self.threshold_spin.value())
                self._harmonic_metric = selected_metric
                kwargs = dict(
                    subject_data=self.subject_data,
                    subjects=self.subjects,
                    conditions=self.conditions,
                    selected_metric=selected_metric,
                    mean_value_threshold=mean_value_threshold,
                    base_freq=self._current_base_freq,
                    alpha=self._current_alpha,
                    rois=self.rois,
                )
                def handler(payload):
                    self._apply_harmonic_results(payload, update_text=True)

                return kwargs, handler
        if pipeline_id is PipelineId.BETWEEN:
            if step_id is StepId.BETWEEN_GROUP_ANOVA:
                kwargs = dict(
                    subjects=self.subjects,
                    conditions=self.conditions,
                    subject_data=self.subject_data,
                    base_freq=self._current_base_freq,
                    rois=self.rois,
                    subject_groups=self.subject_groups,
                )
                def handler(payload):
                    self._apply_between_anova_results(payload, update_text=False)

                return kwargs, handler
            if step_id is StepId.BETWEEN_GROUP_MIXED_MODEL:
                kwargs = dict(
                    subjects=self.subjects,
                    conditions=self.conditions,
                    subject_data=self.subject_data,
                    base_freq=self._current_base_freq,
                    alpha=self._current_alpha,
                    rois=self.rois,
                    subject_groups=self.subject_groups,
                    include_group=True,
                )
                def handler(payload):
                    self._apply_between_mixed_results(payload, update_text=False)

                return kwargs, handler
            if step_id is StepId.GROUP_CONTRASTS:
                kwargs = dict(
                    subjects=self.subjects,
                    conditions=self.conditions,
                    subject_data=self.subject_data,
                    base_freq=self._current_base_freq,
                    alpha=self._current_alpha,
                    rois=self.rois,
                    subject_groups=self.subject_groups,
                )
                def handler(payload):
                    self._apply_group_contrasts_results(payload, update_text=True)

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
        ]
        out_dir = self._ensure_results_dir()
        try:
            paths: list[str] = []
            for kind, data_obj, label in exports:
                if data_obj is None:
                    self.append_log(section, f"  • Skipping export for {label} (no data)", level="warning")
                    return False
                self.export_results(kind, data_obj, out_dir)
                fname = {
                    "anova": ANOVA_XLS,
                    "lmm": LMM_XLS,
                    "posthoc": POSTHOC_XLS,
                }.get(kind, "results.xlsx")
                paths.append(os.path.join(out_dir, fname))
            if paths:
                self.append_log(section, "  • Results exported to:")
                for p in paths:
                    self.append_log(section, f"      {p}")
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
        ]
        out_dir = self._ensure_results_dir()
        try:
            paths: list[str] = []
            for kind, data_obj, label in exports:
                if data_obj is None:
                    self.append_log(section, f"  • Skipping export for {label} (no data)", level="warning")
                    return False
                self.export_results(kind, data_obj, out_dir)
                fname = {
                    "anova_between": ANOVA_BETWEEN_XLS,
                    "lmm_between": LMM_BETWEEN_XLS,
                    "group_contrasts": GROUP_CONTRAST_XLS,
                }.get(kind, "results.xlsx")
                paths.append(os.path.join(out_dir, fname))
            if paths:
                self.append_log(section, "  • Results exported to:")
                for p in paths:
                    self.append_log(section, f"      {p}")
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

    def _format_rm_anova_summary(self, df: pd.DataFrame, alpha: float) -> str:
        out = []
        p_candidates = ["Pr > F", "p-value", "p_value", "p", "P", "pvalue"]
        eff_candidates = ["Effect", "Source", "Factor", "Term"]
        p_col = next((c for c in p_candidates if c in df.columns), None)
        eff_col = next((c for c in eff_candidates if c in df.columns), None)

        if p_col is None:
            out.append("No interpretable effects were found in the ANOVA table.")
            return "\n".join(out)

        for idx, row in df.iterrows():
            effect_source = row.get(eff_col, idx) if eff_col is not None else idx
            effect_name = str(effect_source).strip()
            effect_lower = effect_name.lower()
            effect_compact = effect_lower.replace(" ", "").replace("×", "x")
            p_raw = row.get(p_col, np.nan)
            try:
                p_val = float(p_raw)
            except Exception:
                p_val = np.nan

            if (
                "group" in effect_lower
                and "condition" in effect_lower
                and "roi" in effect_lower
            ):
                tag = "group by condition by ROI interaction"
            elif "group" in effect_lower and "condition" in effect_lower:
                tag = "group-by-condition interaction"
            elif "group" in effect_lower and "roi" in effect_lower:
                tag = "group-by-ROI interaction"
            elif effect_lower.startswith("group") or effect_lower == "group":
                tag = "difference between groups"
            elif effect_compact in {
                "condition*roi",
                "condition:roi",
                "conditionxroi",
                "roi*condition",
                "roi:condition",
                "roixcondition",
            }:
                tag = "condition-by-ROI interaction"
            elif "condition" == effect_lower or effect_lower.startswith("conditions"):
                tag = "difference between conditions"
            elif effect_lower == "roi" or "region" in effect_lower:
                tag = "difference between ROIs"
            else:
                continue

            if np.isfinite(p_val) and p_val < alpha:
                out.append(f"  - Significant {tag} (p = {p_val:.4g}).")
            elif np.isfinite(p_val):
                out.append(f"  - No significant {tag} (p = {p_val:.4g}).")
            else:
                out.append(f"  - {tag.capitalize()}: p-value unavailable.")
        if not out:
            out.append("No interpretable effects were found in the ANOVA table.")
        return "\n".join(out)

    def _apply_rm_anova_results(self, payload: dict, *, update_text: bool = True) -> str:
        self.rm_anova_results_data = payload.get("anova_df_results")
        alpha = getattr(self, "_current_alpha", 0.05)

        output_text = "============================================================\n"
        output_text += "       Repeated Measures ANOVA (RM-ANOVA) Results\n"
        output_text += "       Analysis conducted on: Summed BCA Data\n"
        output_text += "============================================================\n\n"
        output_text += (
            "This test examines the overall effects of your experimental conditions (e.g., different stimuli),\n"
            "the different brain regions (ROIs) you analyzed, and whether the\n"
            "effect of the conditions changes depending on the brain region (interaction effect).\n\n"
        )

        anova_df_results = self.rm_anova_results_data
        if isinstance(anova_df_results, pd.DataFrame) and not anova_df_results.empty:
            output_text += self._format_rm_anova_summary(anova_df_results, alpha) + "\n"
            output_text += "--------------------------------------------\n"
            output_text += "NOTE: For detailed reporting and post-hoc tests, refer to the tables above.\n"
            output_text += "--------------------------------------------\n"
        else:
            output_text += "RM-ANOVA returned no results.\n"

        if update_text:
            self.output_text.append(output_text)
        self._update_export_buttons()
        return output_text

    def _apply_between_anova_results(self, payload: dict, *, update_text: bool = True) -> str:
        self.between_anova_results_data = payload.get("anova_df_results")
        alpha = getattr(self, "_current_alpha", 0.05)
        output_text = "============================================================\n"
        output_text += "       Between-Group Mixed ANOVA Results\n"
        output_text += "============================================================\n\n"
        output_text += (
            "Group was treated as a between-subject factor with Condition and ROI as\n"
            "within-subject factors. Only subjects with known group assignments were\n"
            "included in this analysis.\n\n"
        )
        anova_df_results = self.between_anova_results_data
        if isinstance(anova_df_results, pd.DataFrame) and not anova_df_results.empty:
            output_text += self._format_rm_anova_summary(anova_df_results, alpha) + "\n"
            output_text += "--------------------------------------------\n"
            output_text += "Refer to the exported table for all Group main and interaction effects.\n"
            output_text += "--------------------------------------------\n"
        else:
            output_text += "Between-group ANOVA returned no results.\n"

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

    def _apply_harmonic_results(self, payload: dict, *, update_text: bool = True) -> str:
        output_text = payload.get("output_text") or ""
        findings = payload.get("findings") or []
        if update_text:
            self.output_text.append(
                output_text.strip() or "(Harmonic check returned empty text. See logs for details.)"
            )
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
        self._apply_harmonic_results(payload)
        self._end_run()

    # --------------------------- UI building ---------------------------

    def _init_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

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

        # status + ROI labels
        self.lbl_status = QLabel("Select a folder containing FPVS results.")
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        main_layout.addWidget(self.lbl_status)

        self.lbl_rois = QLabel("")
        self.lbl_rois.setWordWrap(True)
        self.lbl_rois.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        main_layout.addWidget(self.lbl_rois)

        # spinner
        prog_row = QHBoxLayout()
        self.spinner = BusySpinner()
        self.spinner.setFixedSize(18, 18)
        self.spinner.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.spinner.hide()
        prog_row.addWidget(self.spinner, alignment=Qt.AlignLeft)
        prog_row.addStretch(1)
        main_layout.addLayout(prog_row)

        sections_layout = QHBoxLayout()
        sections_layout.setSpacing(10)

        # single group section
        single_group_box = QGroupBox("Single Group Analysis")
        single_group_box.setSizePolicy(QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed))
        single_layout = QVBoxLayout(single_group_box)

        settings_box = QGroupBox("Detection / Harmonic Settings")
        settings_layout = QFormLayout(settings_box)
        settings_layout.setLabelAlignment(Qt.AlignLeft)

        metric_row = QHBoxLayout()
        self.cb_metric = QComboBox()
        self.cb_metric.addItems(["Z Score", "SNR", "Amplitude"])
        metric_row.addWidget(self.cb_metric)
        metric_row.addStretch(1)
        settings_layout.addRow(QLabel("Metric:"), metric_row)

        threshold_row = QHBoxLayout()
        self.threshold_spin = QDoubleSpinBox()
        self.threshold_spin.setRange(0.0, 10.0)
        self.threshold_spin.setSingleStep(0.01)
        self.threshold_spin.setValue(1.64)
        threshold_row.addWidget(self.threshold_spin)
        threshold_row.addStretch(1)
        settings_layout.addRow(QLabel("Mean Threshold:"), threshold_row)

        harm_row = QHBoxLayout()
        self.run_harm_btn = QPushButton("Run Harmonic Check")
        self.run_harm_btn.clicked.connect(self.on_run_harmonic_check)
        self.run_harm_btn.setShortcut("Ctrl+H")
        harm_row.addWidget(self.run_harm_btn)

        self.export_harm_btn = QPushButton("Export Harmonic Results")
        self.export_harm_btn.clicked.connect(self.on_export_harmonic)
        self.export_harm_btn.setShortcut("Ctrl+Shift+H")
        harm_row.addWidget(self.export_harm_btn)
        harm_row.addStretch(1)
        settings_layout.addRow(QLabel("Harmonic Tools:"), harm_row)

        single_layout.addWidget(settings_box)

        single_action_row = QHBoxLayout()
        single_action_row.addStretch(1)
        self.analyze_single_btn = QPushButton("Analyze Single Group")
        self.analyze_single_btn.clicked.connect(self.on_analyze_single_group_clicked)
        single_action_row.addWidget(self.analyze_single_btn)

        self.single_advanced_btn = QPushButton("Advanced…")
        self.single_advanced_btn.clicked.connect(self.on_single_advanced_clicked)
        single_action_row.addWidget(self.single_advanced_btn)
        single_action_row.addStretch(1)
        single_layout.addLayout(single_action_row)

        self.single_status_lbl = QLabel("Idle")
        self.single_status_lbl.setWordWrap(True)
        single_layout.addWidget(self.single_status_lbl)

        # between-group section
        between_box = QGroupBox("Between-Group Analysis")
        between_box.setSizePolicy(QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed))
        between_layout = QVBoxLayout(between_box)

        between_action_row = QHBoxLayout()
        between_action_row.addStretch(1)
        self.analyze_between_btn = QPushButton("Analyze Group Differences")
        self.analyze_between_btn.clicked.connect(self.on_analyze_between_groups_clicked)
        between_action_row.addWidget(self.analyze_between_btn)

        self.between_advanced_btn = QPushButton("Advanced…")
        self.between_advanced_btn.clicked.connect(self.on_between_advanced_clicked)
        between_action_row.addWidget(self.between_advanced_btn)
        between_action_row.addStretch(1)
        between_layout.addLayout(between_action_row)

        self.between_status_lbl = QLabel("Idle")
        self.between_status_lbl.setWordWrap(True)
        between_layout.addWidget(self.between_status_lbl)

        sections_layout.addWidget(single_group_box)
        sections_layout.addWidget(between_box)
        main_layout.addLayout(sections_layout)

        # output pane
        self.output_text = QTextEdit()
        self.output_text.setReadOnly(True)
        self.output_text.setAcceptRichText(True)
        self.output_text.setPlaceholderText("Analysis output")
        self.output_text.setMinimumHeight(140)
        main_layout.addWidget(self.output_text, 1)

        main_layout.setStretch(0, 0)  # folder row
        main_layout.setStretch(1, 0)  # tools row
        main_layout.setStretch(2, 0)  # status label
        main_layout.setStretch(3, 0)  # ROI label
        main_layout.setStretch(4, 0)  # spinner row
        main_layout.setStretch(5, 0)  # analysis sections row
        main_layout.setStretch(6, 1)  # unified output pane

        # initialize export buttons
        self._update_export_buttons()

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
        if not folder_path or not os.path.isdir(folder_path):
            return False
        open_files = []
        for name in os.listdir(folder_path):
            if name.lower().endswith((".xlsx", ".xls")):
                fpath = os.path.join(folder_path, name)
                try:
                    os.rename(fpath, fpath)
                except OSError:
                    open_files.append(name)
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

    def on_run_harmonic_check(self) -> None:
        selected_metric = self.cb_metric.currentText()

        self.output_text.clear()
        self.harmonic_check_results_data = []
        self._update_export_buttons()
        self._harmonic_metric = selected_metric  # for legacy exporter
        self._controller.run_harmonic_check_only()

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
            QMessageBox.critical(self, "Export Failed", str(e))

    def on_export_mixed_model(self) -> None:
        if not isinstance(self.mixed_model_results_data, pd.DataFrame) or self.mixed_model_results_data.empty:
            QMessageBox.information(self, "No Results", "Run Mixed Model first.")
            return
        out_dir = self._ensure_results_dir()
        try:
            self.export_results("lmm", self.mixed_model_results_data, out_dir)
            self._set_status(f"Mixed Model results exported to: {out_dir}")
        except Exception as e:
            QMessageBox.critical(self, "Export Failed", str(e))

    def on_export_between_anova(self) -> None:
        if not isinstance(self.between_anova_results_data, pd.DataFrame) or self.between_anova_results_data.empty:
            QMessageBox.information(self, "No Results", "Run Between-Group ANOVA first.")
            return
        out_dir = self._ensure_results_dir()
        try:
            self.export_results("anova_between", self.between_anova_results_data, out_dir)
            self._set_status(f"Between-group ANOVA exported to: {out_dir}")
        except Exception as e:
            QMessageBox.critical(self, "Export Failed", str(e))

    def on_export_between_mixed(self) -> None:
        if not isinstance(self.between_mixed_model_results_data, pd.DataFrame) or self.between_mixed_model_results_data.empty:
            QMessageBox.information(self, "No Results", "Run Between-Group Mixed Model first.")
            return
        out_dir = self._ensure_results_dir()
        try:
            self.export_results("lmm_between", self.between_mixed_model_results_data, out_dir)
            self._set_status(f"Between-group Mixed Model exported to: {out_dir}")
        except Exception as e:
            QMessageBox.critical(self, "Export Failed", str(e))

    def on_export_posthoc(self) -> None:
        if not isinstance(self.posthoc_results_data, pd.DataFrame) or self.posthoc_results_data.empty:
            QMessageBox.information(self, "No Results", "Run Interaction Post-hocs first.")
            return
        out_dir = self._ensure_results_dir()
        try:
            self.export_results("posthoc", self.posthoc_results_data, out_dir)
            self._set_status(f"Post-hoc results exported to: {out_dir}")
        except Exception as e:
            QMessageBox.critical(self, "Export Failed", str(e))

    def on_export_group_contrasts(self) -> None:
        if not isinstance(self.group_contrasts_results_data, pd.DataFrame) or self.group_contrasts_results_data.empty:
            QMessageBox.information(self, "No Results", "Run Group Contrasts first.")
            return
        out_dir = self._ensure_results_dir()
        try:
            self.export_results("group_contrasts", self.group_contrasts_results_data, out_dir)
            self._set_status(f"Group contrasts exported to: {out_dir}")
        except Exception as e:
            QMessageBox.critical(self, "Export Failed", str(e))

    def on_export_harmonic(self) -> None:
        if not self.harmonic_check_results_data:
            QMessageBox.information(self, "No Results", "Run Harmonic Check first.")
            return
        out_dir = self._ensure_results_dir()
        try:
            self.export_results("harmonic", self.harmonic_check_results_data, out_dir)
            self._set_status(f"Harmonic check results exported to: {out_dir}")
        except Exception as e:
            QMessageBox.critical(self, "Export Failed", str(e))

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


