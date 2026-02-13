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
import time
from types import SimpleNamespace
from typing import Callable, Dict, List, NamedTuple, Optional, Tuple

import pandas as pd
from PySide6.QtCore import Qt, QTimer, QThreadPool, Slot, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QFontMetrics, QGuiApplication, QTextCursor
from PySide6.QtWidgets import (
    QFileDialog,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QComboBox,
    QAbstractItemView,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QScrollArea,
    QSplitter,
    QSpinBox,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
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
from Tools.Stats.PySide6.stats_missingness import export_missingness_workbook
from Tools.Stats.PySide6.stats_group_contrasts import export_group_contrasts_workbook
from Tools.Stats.PySide6.stats_export_formatting import (
    apply_lmm_number_formats_and_metadata,
    apply_rm_anova_pvalue_number_formats,
    log_rm_anova_p_minima,
)
from Tools.Stats.PySide6.stats_qc_reports import export_qc_context_workbook
from Tools.Stats.PySide6.stats_workers import StatsWorker
from Tools.Stats.PySide6 import stats_workers as stats_worker_funcs
from Tools.Stats.PySide6.dv_policies import (
    EMPTY_LIST_ERROR,
    EMPTY_LIST_FALLBACK_FIXED_K,
    EMPTY_LIST_SET_ZERO,
    FIXED_K_POLICY_NAME,
    FIXED_SHARED_POLICY_NAME,
    LEGACY_POLICY_NAME,
    ROSSION_POLICY_NAME,
)
from Tools.Stats.PySide6.dv_variants import export_dv_variants_workbook
from Tools.Stats.PySide6.stats_outlier_exclusion import (
    build_flagged_details_map,
    build_flagged_participant_summary,
    collect_flagged_pid_map,
    build_flagged_participants_tables,
    export_excluded_participants_report,
    export_flagged_participants_report,
    format_flag_types_display,
    format_worst_value_display,
)
from Tools.Stats.PySide6.stats_manual_exclusion_dialog import ManualOutlierExclusionDialog
from Tools.Stats.PySide6.stats_qc_exclusion import (
    QC_DEFAULT_CRITICAL_ABS_FLOOR_MAXABS,
    QC_DEFAULT_CRITICAL_ABS_FLOOR_SUMABS,
    QC_DEFAULT_CRITICAL_THRESHOLD,
    QC_DEFAULT_WARN_ABS_FLOOR_MAXABS,
    QC_DEFAULT_WARN_ABS_FLOOR_SUMABS,
    QC_DEFAULT_WARN_THRESHOLD,
)
from Tools.Stats.PySide6.stats_run_report import StatsRunReport
from Tools.Stats.PySide6.summary_utils import (
    StatsSummaryFrames,
    SummaryConfig,
    build_between_anova_output,
    build_rm_anova_output,
    build_summary_from_frames,
    build_summary_frames_from_results,
)
from Tools.Stats.PySide6.reporting_summary import (
    ReportingSummaryContext,
    build_default_report_path,
    build_reporting_summary,
    safe_project_path_join,
)
from Tools.Stats.PySide6.stats_multigroup_scan import (
    MultiGroupScanResult,
    ScanIssue,
    run_multigroup_scan_worker,
)
from Tools.Stats.PySide6.widgets.elided_label import ElidedPathLabel

logger = logging.getLogger(__name__)
_unused_qaction = QAction  # keep import alive for Qt resource checkers

class HarmonicConfig(NamedTuple):
    """Represent the HarmonicConfig part of the Stats PySide6 tool."""
    metric: str
    threshold: float


# --------------------------- worker functions ---------------------------

# --------------------------- main window ---------------------------

class StatsWindow(QMainWindow):
    """PySide6 window wrapping the legacy FPVS Statistical Analysis Tool."""

    def __init__(self, parent: Optional[QMainWindow] = None, project_dir: Optional[str] = None):
        """Set up this object so it is ready to be used by the Stats tool."""
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

        self.setMinimumSize(1180, 760)
        self.resize(1400, 820)

        # re-entrancy guard for scan
        self._scan_guard = OpGuard()
        if not hasattr(self._scan_guard, "done"):
            self._scan_guard.done = self._scan_guard.end  # type: ignore[attr-defined]
        self._multigroup_scan_guard = OpGuard()
        if not hasattr(self._multigroup_scan_guard, "done"):
            self._multigroup_scan_guard.done = self._multigroup_scan_guard.end  # type: ignore[attr-defined]

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
        self._dv_policy_name: str = ROSSION_POLICY_NAME
        self._dv_fixed_k: int = 5
        self._dv_exclude_harmonic1: bool = True
        self._dv_exclude_base_harmonics: bool = True
        self._dv_group_mean_z_threshold: float = 1.64
        self._dv_empty_list_policy: str = EMPTY_LIST_FALLBACK_FIXED_K
        self._dv_variant_checkboxes: dict[str, QCheckBox] = {}
        self._dv_variants_selected: List[str] = []
        self._outlier_exclusion_enabled: bool = True
        self._outlier_abs_limit: float = 50.0
        self.manual_excluded_pids: set[str] = set()
        self._manual_exclusion_candidates: List[str] = []
        self._pipeline_conditions: dict[PipelineId, list[str]] = {}
        self._pipeline_dv_policy: dict[PipelineId, dict[str, object]] = {}
        self._pipeline_base_freq: dict[PipelineId, float] = {}
        self._pipeline_dv_metadata: dict[PipelineId, dict[str, object]] = {}
        self._pipeline_dv_variants: dict[PipelineId, list[str]] = {}
        self._pipeline_dv_variant_payloads: dict[PipelineId, dict[str, object]] = {}
        self._pipeline_outlier_config: dict[PipelineId, dict[str, object]] = {}
        self._pipeline_qc_config: dict[PipelineId, dict[str, object]] = {}
        self._pipeline_qc_state: dict[PipelineId, dict[str, object]] = {}
        self._pipeline_run_reports: dict[PipelineId, StatsRunReport | None] = {}
        self._group_mean_preview_data: dict[str, object] = {}
        self._qc_threshold_sumabs: float = QC_DEFAULT_WARN_THRESHOLD
        self._qc_threshold_maxabs: float = QC_DEFAULT_CRITICAL_THRESHOLD
        self._last_export_path: str | None = None
        self._multigroup_scan_result: MultiGroupScanResult | None = None
        self._shared_harmonics_payload: dict[str, object] = {}
        self._fixed_harmonic_dv_payload: dict[str, object] = {}
        self._between_missingness_payload: dict[str, object] = {}
        self._multigroup_issue_expanded = False
        self._multigroup_issue_preview_limit = 5
        self._reporting_summary_text: str = ""
        self._pipeline_start_perf: dict[PipelineId, float] = {}

        # --- legacy UI proxies ---
        self.stats_data_folder_var = SimpleNamespace(
            get=lambda: self.le_folder.text() if hasattr(self, "le_folder") else "",
            set=lambda v: self._set_data_folder_path(v) if hasattr(self, "le_folder") else None,
        )
        self.detected_info_var = SimpleNamespace(set=lambda t: self._set_status(t))
        self.roi_var = SimpleNamespace(get=lambda: ALL_ROIS_OPTION, set=lambda v: None)
        self.alpha_var = SimpleNamespace(get=lambda: "0.05", set=lambda v: None)

        # UI
        self._init_ui()
        self.results_textbox = self.summary_text
        self._update_manual_exclusion_summary()

        self.refresh_rois()
        QTimer.singleShot(100, self._load_default_data_folder)

        self._progress_updates: List[int] = []

        # controller
        self._controller = StatsController(view=self)
        self._refresh_fixed_harmonic_ui_state()

    # --------- ROI + status helpers ---------

    def refresh_rois(self) -> None:
        """Handle the refresh rois step for the Stats PySide6 workflow."""
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
        """Handle the update roi label step for the Stats PySide6 workflow."""
        names = list(self.rois.keys())
        txt = "Using {} ROI{} from Settings: {}".format(
            len(names), "" if len(names) == 1 else "s", ", ".join(names)
        ) if names else "No ROIs defined in Settings."
        self._set_roi_status(txt)

    def _set_status(self, txt: str) -> None:
        """Handle the set status step for the Stats PySide6 workflow."""
        if hasattr(self, "lbl_status"):
            self.lbl_status.setText(txt)

    def _set_roi_status(self, txt: str) -> None:
        """Handle the set roi status step for the Stats PySide6 workflow."""
        if hasattr(self, "lbl_rois"):
            self.lbl_rois.setText(txt)

    def _set_data_folder_path(self, path: str) -> None:
        """Handle the set data folder path step for the Stats PySide6 workflow."""
        if hasattr(self, "le_folder"):
            self.le_folder.setText(path or "")
            if not path:
                self.le_folder.setToolTip(
                    "Selected folder that contains the FPVS result spreadsheets."
                )
        if hasattr(self, "btn_copy_folder"):
            self.btn_copy_folder.setEnabled(bool(path))

    def _set_last_export_path(self, path: str | None) -> None:
        """Handle the set last export path step for the Stats PySide6 workflow."""
        self._last_export_path = path or ""
        if hasattr(self, "export_path_label"):
            self.export_path_label.set_full_text(self._last_export_path)
        exists = bool(self._last_export_path and Path(self._last_export_path).exists())
        if hasattr(self, "export_open_btn"):
            self.export_open_btn.setEnabled(exists)
        if hasattr(self, "export_copy_btn"):
            self.export_copy_btn.setEnabled(bool(self._last_export_path))

    def _copy_text_to_clipboard(self, text: str, *, context: str) -> None:
        """Handle the copy text to clipboard step for the Stats PySide6 workflow."""
        try:
            QGuiApplication.clipboard().setText(text or "")
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "stats_clipboard_copy_failed",
                exc_info=True,
                extra={"context": context, "error": str(exc)},
            )
            self._set_status(f"Copy failed ({context}).")

    def _copy_summary_text(self) -> None:
        """Handle the copy summary text step for the Stats PySide6 workflow."""
        text = self.summary_text.toPlainText()
        self._copy_text_to_clipboard(text, context="summary")

    def _copy_reporting_summary_text(self) -> None:
        """Handle the copy reporting summary text step for the Stats PySide6 workflow."""
        text = self.reporting_summary_text.toPlainText() if hasattr(self, "reporting_summary_text") else ""
        self._copy_text_to_clipboard(text, context="reporting_summary")

    def _save_reporting_summary_text(self) -> None:
        """Handle the save reporting summary text step for the Stats PySide6 workflow."""
        report_text = self.reporting_summary_text.toPlainText() if hasattr(self, "reporting_summary_text") else ""
        if not report_text.strip():
            self._set_status("No reporting summary available to save yet.")
            return
        default_path = build_default_report_path(self._project_path, datetime.now())
        default_path.parent.mkdir(parents=True, exist_ok=True)
        target, _ = QFileDialog.getSaveFileName(
            self,
            "Save Reporting Summary",
            str(default_path),
            "Text Files (*.txt)",
        )
        if not target:
            self._set_status("Reporting summary save canceled.")
            return
        try:
            target_path = safe_project_path_join(self._project_path, Path(target).relative_to(self._project_path).as_posix())
        except Exception:
            self._set_status("Save canceled: selected path must be under the active project root.")
            return
        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(report_text, encoding="utf-8")
            self._set_status(f"Reporting summary saved: {target_path}")
            self._set_last_export_path(str(target_path))
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "stats_reporting_summary_save_failed",
                exc_info=True,
                extra={
                    "operation": "save_reporting_summary_dialog",
                    "project": self.project_title,
                    "path": str(target_path),
                    "elapsed_ms": 0,
                    "exception": str(exc),
                },
            )
            self._set_status("Failed to save reporting summary text.")

    def _copy_log_text(self) -> None:
        """Handle the copy log text step for the Stats PySide6 workflow."""
        text = self.log_text.toPlainText()
        self._copy_text_to_clipboard(text, context="log")

    def _copy_data_folder_path(self) -> None:
        """Handle the copy data folder path step for the Stats PySide6 workflow."""
        path = self.le_folder.text()
        if not path:
            return
        self._copy_text_to_clipboard(path, context="data_folder")

    def _open_export_path(self) -> None:
        """Handle the open export path step for the Stats PySide6 workflow."""
        path = self._last_export_path or ""
        if not path:
            self._set_status("No export path available yet.")
            return
        if not Path(path).exists():
            self._set_status(f"Export path not found: {path}")
            logger.error("stats_export_open_missing", extra={"path": path})
            return
        try:
            os.startfile(path)  # noqa: S606
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "stats_export_open_failed",
                exc_info=True,
                extra={"path": path, "error": str(exc)},
            )
            self._set_status(f"Failed to open export path: {path}")

    def _copy_export_path(self) -> None:
        """Handle the copy export path step for the Stats PySide6 workflow."""
        path = self._last_export_path or ""
        if not path:
            return
        self._copy_text_to_clipboard(path, context="export_path")

    def _clear_output_views(self) -> None:
        """Handle the clear output views step for the Stats PySide6 workflow."""
        self.summary_text.clear()
        self.output_text.clear()

    def _set_detected_info(self, txt: str) -> None:
        """Route unknown worker messages to proper label."""
        lower_txt = txt.lower() if isinstance(txt, str) else str(txt).lower()
        if (" roi" in lower_txt) or lower_txt.startswith("using ") or lower_txt.startswith("rois"):
            self._set_roi_status(txt)
        else:
            self._set_status(txt)

    def _clear_conditions_layout(self) -> None:
        """Handle the clear conditions layout step for the Stats PySide6 workflow."""
        layout = self.conditions_list_layout
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _populate_conditions_panel(self, conditions: List[str]) -> None:
        """Handle the populate conditions panel step for the Stats PySide6 workflow."""
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
            checkbox.setToolTip(
                "Include this condition in the analysis."
            )
            checkbox.stateChanged.connect(self._on_condition_toggled)
            self.conditions_list_layout.addWidget(checkbox)
            self._condition_checkboxes[condition] = checkbox

        self.conditions_list_layout.addStretch(1)
        self._sync_selected_conditions()

    def _sync_selected_conditions(self) -> None:
        """Handle the sync selected conditions step for the Stats PySide6 workflow."""
        self.selected_conditions = [
            name for name, checkbox in self._condition_checkboxes.items() if checkbox.isChecked()
        ]

    def _on_condition_toggled(self, _state: int) -> None:
        """Handle the on condition toggled step for the Stats PySide6 workflow."""
        self._sync_selected_conditions()

    def _on_dv_variant_toggled(self, _state: int) -> None:
        """Handle the on dv variant toggled step for the Stats PySide6 workflow."""
        self._sync_selected_dv_variants()

    def _select_all_conditions(self) -> None:
        """Handle the select all conditions step for the Stats PySide6 workflow."""
        for checkbox in self._condition_checkboxes.values():
            checkbox.setChecked(True)
        self._sync_selected_conditions()

    def _select_no_conditions(self) -> None:
        """Handle the select no conditions step for the Stats PySide6 workflow."""
        for checkbox in self._condition_checkboxes.values():
            checkbox.setChecked(False)
        self._sync_selected_conditions()

    def _get_selected_conditions(self) -> List[str]:
        """Handle the get selected conditions step for the Stats PySide6 workflow."""
        if self._condition_checkboxes:
            return list(self.selected_conditions)
        return list(self.conditions)

    def _get_dv_policy_payload(self) -> dict[str, object]:
        """Handle the get dv policy payload step for the Stats PySide6 workflow."""
        return {
            "name": self._dv_policy_name,
            "fixed_k": int(self._dv_fixed_k),
            "exclude_harmonic1": bool(self._dv_exclude_harmonic1),
            "exclude_base_harmonics": bool(self._dv_exclude_base_harmonics),
            "z_threshold": float(self._dv_group_mean_z_threshold),
            "empty_list_policy": str(self._dv_empty_list_policy),
        }

    def _get_between_group_dv_policy_payload(self) -> dict[str, object]:
        """Handle the get between group dv policy payload step for the Stats PySide6 workflow."""
        payload = self._get_dv_policy_payload()
        harmonics_by_roi = self._shared_harmonics_payload.get("harmonics_by_roi", {})
        if isinstance(harmonics_by_roi, dict) and any((harmonics_by_roi.get(k) or []) for k in harmonics_by_roi):
            payload["name"] = FIXED_SHARED_POLICY_NAME
            payload["harmonics_by_roi"] = harmonics_by_roi
        return payload

    def _refresh_fixed_harmonic_ui_state(self) -> None:
        """Handle the refresh fixed harmonic ui state step for the Stats PySide6 workflow."""
        harmonics_by_roi = self._shared_harmonics_payload.get("harmonics_by_roi", {})
        has_shared_harmonics = isinstance(harmonics_by_roi, dict) and any(
            (harmonics_by_roi.get(k) or []) for k in harmonics_by_roi
        )
        button = getattr(self, "compute_fixed_harmonic_dv_btn", None)
        if button is not None:
            button.setEnabled(has_shared_harmonics)
        summary_label = getattr(self, "fixed_harmonic_dv_summary_value", None)
        if summary_label is not None:
            if self._fixed_harmonic_dv_payload:
                summary_label.setText(str(self._fixed_harmonic_dv_payload.get("summary", "Ready")))
            elif has_shared_harmonics:
                summary_label.setText("Shared harmonics ready; DV not computed.")
            else:
                summary_label.setText("Waiting for shared harmonics.")

    def get_dv_policy_snapshot(self) -> dict[str, object]:
        """Handle the get dv policy snapshot step for the Stats PySide6 workflow."""
        return dict(self._get_dv_policy_payload())

    def _sync_selected_dv_variants(self) -> None:
        """Handle the sync selected dv variants step for the Stats PySide6 workflow."""
        self._dv_variants_selected = [
            name
            for name, checkbox in self._dv_variant_checkboxes.items()
            if checkbox.isChecked()
        ]

    def _get_selected_dv_variants(self) -> List[str]:
        """Handle the get selected dv variants step for the Stats PySide6 workflow."""
        if self._dv_variant_checkboxes:
            return list(self._dv_variants_selected)
        return []

    def _get_dv_variant_payloads(self) -> list[dict[str, object]]:
        """Handle the get dv variant payloads step for the Stats PySide6 workflow."""
        selected = self._get_selected_dv_variants()
        if not selected:
            return []
        base_payload = self._get_dv_policy_payload()
        payloads = []
        for name in selected:
            variant_payload = dict(base_payload)
            variant_payload["name"] = name
            payloads.append(variant_payload)
        return payloads

    def get_dv_variants_snapshot(self) -> list[str]:
        """Handle the get dv variants snapshot step for the Stats PySide6 workflow."""
        return list(self._get_selected_dv_variants())

    def _get_outlier_exclusion_payload(self) -> dict[str, object]:
        """Handle the get outlier exclusion payload step for the Stats PySide6 workflow."""
        return {
            "enabled": True,
            "abs_limit": float(self._outlier_abs_limit),
        }

    def _get_qc_exclusion_payload(self) -> dict[str, object]:
        """Handle the get qc exclusion payload step for the Stats PySide6 workflow."""
        return {
            "warn_threshold": float(self._qc_threshold_sumabs),
            "critical_threshold": float(self._qc_threshold_maxabs),
            "warn_abs_floor_sumabs": QC_DEFAULT_WARN_ABS_FLOOR_SUMABS,
            "critical_abs_floor_sumabs": QC_DEFAULT_CRITICAL_ABS_FLOOR_SUMABS,
            "warn_abs_floor_maxabs": QC_DEFAULT_WARN_ABS_FLOOR_MAXABS,
            "critical_abs_floor_maxabs": QC_DEFAULT_CRITICAL_ABS_FLOOR_MAXABS,
        }

    def _on_outlier_exclusion_toggled(self, state: int) -> None:
        """Handle the on outlier exclusion toggled step for the Stats PySide6 workflow."""
        self._outlier_exclusion_enabled = True
        spinbox = getattr(self, "outlier_abs_limit_spin", None)
        if spinbox is not None:
            spinbox.setEnabled(True)

    def _on_outlier_abs_limit_changed(self, value: float) -> None:
        """Handle the on outlier abs limit changed step for the Stats PySide6 workflow."""
        self._outlier_abs_limit = float(value)

    def _current_flagged_pid_map(self) -> dict[str, list[str]]:
        """Handle the current flagged pid map step for the Stats PySide6 workflow."""
        report = None
        if self._active_pipeline is not None:
            report = self._pipeline_run_reports.get(self._active_pipeline)
        if report is None:
            for item in self._pipeline_run_reports.values():
                if item is not None:
                    report = item
                    break
        if report is None:
            return {}
        return collect_flagged_pid_map(report.qc_report, report.dv_report)

    def _current_flagged_details_map(self) -> dict[str, str]:
        """Handle the current flagged details map step for the Stats PySide6 workflow."""
        report = None
        if self._active_pipeline is not None:
            report = self._pipeline_run_reports.get(self._active_pipeline)
        if report is None:
            for item in self._pipeline_run_reports.values():
                if item is not None:
                    report = item
                    break
        if report is None:
            return {}
        return build_flagged_details_map(report.qc_report, report.dv_report)

    def _update_manual_exclusion_summary(self) -> None:
        """Handle the update manual exclusion summary step for the Stats PySide6 workflow."""
        excluded = sorted(self.manual_excluded_pids)
        self.manual_excluded_pids = set(excluded)
        summary_label = getattr(self, "manual_exclusion_summary_label", None)
        if summary_label is not None:
            summary_label.setText(f"Excluded: {len(excluded)}")
        list_widget = getattr(self, "manual_exclusion_list", None)
        if list_widget is not None:
            if not excluded:
                display_text = "None"
                tooltip_text = "None"
            elif len(excluded) <= 3:
                display_text = ", ".join(excluded)
                tooltip_text = display_text
            else:
                display_text = ", ".join(excluded[:3]) + f" (+{len(excluded) - 3})"
                tooltip_text = ", ".join(excluded)
            list_widget.set_full_text(display_text)
            list_widget.setToolTip(tooltip_text)

    def _reconcile_manual_exclusions(self, candidates: list[str]) -> None:
        """Handle the reconcile manual exclusions step for the Stats PySide6 workflow."""
        self._manual_exclusion_candidates = list(candidates)
        self.manual_excluded_pids = {
            pid for pid in self.manual_excluded_pids if pid in self._manual_exclusion_candidates
        }
        self._update_manual_exclusion_summary()

    def _clear_manual_exclusions(self) -> None:
        """Handle the clear manual exclusions step for the Stats PySide6 workflow."""
        self.manual_excluded_pids.clear()
        self._update_manual_exclusion_summary()

    def _open_manual_exclusion_dialog(self) -> None:
        """Handle the open manual exclusion dialog step for the Stats PySide6 workflow."""
        dialog = ManualOutlierExclusionDialog(
            candidates=self._manual_exclusion_candidates,
            flagged_map=self._current_flagged_pid_map(),
            flagged_details_map=self._current_flagged_details_map(),
            preselected=self.manual_excluded_pids,
            parent=self,
        )

        def _apply_changes(selections: set[str]) -> None:
            """Handle the apply changes step for the Stats PySide6 workflow."""
            self.manual_excluded_pids = set(selections)
            self._update_manual_exclusion_summary()

        dialog.manualExclusionsApplied.connect(_apply_changes)
        dialog.exec()

    def _set_fixed_k_controls_enabled(self, enabled: bool) -> None:
        """Handle the set fixed k controls enabled step for the Stats PySide6 workflow."""
        widgets = [
            getattr(self, "fixed_k_spinbox", None),
            getattr(self, "fixed_k_exclude_h1", None),
            getattr(self, "fixed_k_exclude_base", None),
            getattr(self, "fixed_k_base_freq_value", None),
        ]
        for widget in widgets:
            if widget is not None:
                widget.setEnabled(enabled)

    def _set_group_mean_controls_visible(self, visible: bool) -> None:
        """Handle the set group mean controls visible step for the Stats PySide6 workflow."""
        widget = getattr(self, "group_mean_controls", None)
        if widget is not None:
            widget.setVisible(visible)
        preview_button = getattr(self, "group_mean_preview_btn", None)
        if preview_button is not None:
            preview_button.setVisible(visible)
        preview_table = getattr(self, "group_mean_preview_table", None)
        if preview_table is not None:
            preview_table.setVisible(visible)

    def _on_group_mean_z_threshold_changed(self, value: float) -> None:
        """Handle the on group mean z threshold changed step for the Stats PySide6 workflow."""
        self._dv_group_mean_z_threshold = float(value)

    def _on_empty_list_policy_changed(self, text: str) -> None:
        """Handle the on empty list policy changed step for the Stats PySide6 workflow."""
        self._dv_empty_list_policy = text

    def _clear_group_mean_preview(self) -> None:
        """Handle the clear group mean preview step for the Stats PySide6 workflow."""
        table = getattr(self, "group_mean_preview_table", None)
        if table is None:
            return
        table.setRowCount(0)
        self._group_mean_preview_data = {}

    def _update_group_mean_preview_table(
        self,
        union_map: dict[str, list[float]],
        fallback_info: dict[str, dict[str, object]],
        stop_metadata: dict[str, dict[str, object]] | None = None,
    ) -> None:
        """Handle the update group mean preview table step for the Stats PySide6 workflow."""
        table = getattr(self, "group_mean_preview_table", None)
        if table is None:
            return
        stop_metadata = stop_metadata or {}
        rois = sorted(union_map.keys())
        table.setRowCount(len(rois))
        for row, roi_name in enumerate(rois):
            harmonics = union_map.get(roi_name, [])
            fallback = fallback_info.get(roi_name, {})
            fallback_used = bool(fallback.get("fallback_used"))
            policy = fallback.get("policy", "")
            if fallback_used:
                fallback_text = str(policy)
            elif policy == EMPTY_LIST_SET_ZERO and not harmonics:
                fallback_text = "DV=0"
            else:
                fallback_text = "None"

            harmonic_text = ", ".join(f"{freq:g}" for freq in harmonics) or "—"
            count_text = str(len(harmonics))
            stop_meta = stop_metadata.get(roi_name, {})
            stop_reason = stop_meta.get("stop_reason") or "—"
            stop_fail = ", ".join(
                f"{freq:g}" for freq in stop_meta.get("fail_harmonics", []) or []
            ) or "—"

            table.setItem(row, 0, QTableWidgetItem(str(roi_name)))
            table.setItem(row, 1, QTableWidgetItem(harmonic_text))
            table.setItem(row, 2, QTableWidgetItem(count_text))
            table.setItem(row, 3, QTableWidgetItem(fallback_text))
            table.setItem(row, 4, QTableWidgetItem(str(stop_reason)))
            table.setItem(row, 5, QTableWidgetItem(stop_fail))

        table.resizeColumnsToContents()

    def _on_preview_group_mean_z_clicked(self) -> None:
        """Handle the on preview group mean z clicked step for the Stats PySide6 workflow."""
        if self._dv_policy_name != ROSSION_POLICY_NAME:
            return
        if not self.subject_data:
            self._set_status("Load project data before previewing harmonic sets.")
            return
        self.refresh_rois()
        if not self.rois:
            self._set_status("Define at least one ROI before previewing.")
            return
        got = self._get_analysis_settings()
        if not got:
            return
        self._current_base_freq, self._current_alpha = got
        self._update_fixed_k_base_freq_label()

        self.group_mean_preview_btn.setEnabled(False)
        self._set_status("Previewing harmonic sets…")

        worker = StatsWorker(
            stats_worker_funcs.run_harmonics_preview,
            subjects=self.subjects,
            conditions=self._get_selected_conditions(),
            subject_data=self.subject_data,
            base_freq=self._current_base_freq,
            rois=self.rois,
            dv_policy=self._get_dv_policy_payload(),
            _op=f"{self._dv_policy_name} Preview",
        )

        try:
            if not hasattr(self, "_active_workers"):
                self._active_workers = []
            self._active_workers.append(worker)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to track preview worker")

        def _release():
            """Handle the release step for the Stats PySide6 workflow."""
            try:
                if worker in self._active_workers:
                    self._active_workers.remove(worker)
            except Exception:  # noqa: BLE001
                logger.exception("Failed to release preview worker")

        def _on_finished(payload: dict) -> None:
            """Handle the on finished step for the Stats PySide6 workflow."""
            try:
                self._group_mean_preview_data = payload or {}
                union_map = payload.get("union_harmonics_by_roi", {}) if isinstance(payload, dict) else {}
                fallback_info = payload.get("fallback_info_by_roi", {}) if isinstance(payload, dict) else {}
                stop_meta = payload.get("stop_metadata_by_roi", {}) if isinstance(payload, dict) else {}
                self._update_group_mean_preview_table(union_map, fallback_info, stop_meta)
                self._set_status("Preview updated.")
            finally:
                self.group_mean_preview_btn.setEnabled(True)
                _release()

        def _on_error(message: str) -> None:
            """Handle the on error step for the Stats PySide6 workflow."""
            try:
                self.append_log("General", f"Preview error: {message}", level="error")
                self._set_status(message)
            finally:
                self.group_mean_preview_btn.setEnabled(True)
                _release()

        worker.signals.message.connect(self._on_worker_message)
        worker.signals.error.connect(_on_error)
        worker.signals.finished.connect(_on_finished)
        worker.signals.progress.connect(self._on_worker_progress)
        self.pool.start(worker)

    def _update_fixed_k_base_freq_label(self) -> None:
        """Handle the update fixed k base freq label step for the Stats PySide6 workflow."""
        label = getattr(self, "fixed_k_base_freq_value", None)
        if label is None:
            return
        label.setText(f"{self._current_base_freq:g} Hz")

    def _on_dv_policy_changed(self, text: str) -> None:
        """Handle the on dv policy changed step for the Stats PySide6 workflow."""
        self._dv_policy_name = text
        self._set_fixed_k_controls_enabled(text == FIXED_K_POLICY_NAME)
        self._set_group_mean_controls_visible(text == ROSSION_POLICY_NAME)
        if text != ROSSION_POLICY_NAME:
            self._clear_group_mean_preview()

    def _on_fixed_k_changed(self, value: int) -> None:
        """Handle the on fixed k changed step for the Stats PySide6 workflow."""
        self._dv_fixed_k = int(value)

    def _on_fixed_k_exclude_h1_changed(self, state: int) -> None:
        """Handle the on fixed k exclude h1 changed step for the Stats PySide6 workflow."""
        self._dv_exclude_harmonic1 = state == Qt.Checked

    def _on_fixed_k_exclude_base_changed(self, state: int) -> None:
        """Handle the on fixed k exclude base changed step for the Stats PySide6 workflow."""
        self._dv_exclude_base_harmonics = state == Qt.Checked

    def append_log(self, section: str, message: str, level: str = "info") -> None:
        """Handle the append log step for the Stats PySide6 workflow."""
        line = format_log_line(f"[{section}] {message}", level=level)
        if hasattr(self, "output_text") and self.output_text is not None:
            self.output_text.appendPlainText(line)
            self.output_text.ensureCursorVisible()
        level_lower = (level or "info").lower()
        log_func = getattr(logger, level_lower, logger.info)
        log_func(line)

    def _section_label(self, pipeline: PipelineId | None) -> str:
        """Handle the section label step for the Stats PySide6 workflow."""
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
        """Handle the log pipeline event step for the Stats PySide6 workflow."""
        if pipeline is None:
            return
        payload = {"pipeline": pipeline.name.lower(), "event": event}
        if step:
            payload["step_id"] = step.name
        if extra:
            payload.update(extra)
        logger.info(format_section_header("stats_pipeline_event"), extra=payload)

    def _warn_unknown_excel_files(self, subject_data: Dict[str, Dict[str, str]], participants_map: dict[str, str]) -> None:
        """Handle the warn unknown excel files step for the Stats PySide6 workflow."""
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

    def _start_multigroup_scan(self, excel_root: Path | None = None) -> None:
        """Handle the start multigroup scan step for the Stats PySide6 workflow."""
        if not self._multigroup_scan_guard.start():
            return
        excel_root = excel_root or Path(self.le_folder.text() or self._preferred_stats_folder())
        project_root = self._project_path

        self._set_status("Scanning multi-group readiness…")

        worker = StatsWorker(
            run_multigroup_scan_worker,
            project_root=project_root,
            excel_root=excel_root,
            _op="multigroup_scan",
        )

        try:
            if not hasattr(self, "_active_workers"):
                self._active_workers = []
            self._active_workers.append(worker)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to track multigroup scan worker")

        def _release() -> None:
            """Handle the release step for the Stats PySide6 workflow."""
            try:
                if worker in self._active_workers:
                    self._active_workers.remove(worker)
            except Exception:  # noqa: BLE001
                logger.exception("Failed to release multigroup scan worker")
            finally:
                self._multigroup_scan_guard.done()

        def _on_finished(payload: dict) -> None:
            """Handle the on finished step for the Stats PySide6 workflow."""
            try:
                result = payload.get("result") if isinstance(payload, dict) else None
                if isinstance(result, MultiGroupScanResult):
                    self._multigroup_scan_result = result
                    self._update_multigroup_summary(result)
                else:
                    self._set_status("Multi-group scan failed to return results.")
                    self.append_log("General", "Multi-group scan failed to return results.", level="error")
            finally:
                _release()

        def _on_error(message: str) -> None:
            """Handle the on error step for the Stats PySide6 workflow."""
            try:
                self._set_status(f"Multi-group scan error: {message}")
                self.append_log("General", f"Multi-group scan error: {message}", level="error")
            finally:
                _release()

        worker.signals.message.connect(self._on_worker_message)
        worker.signals.error.connect(_on_error)
        worker.signals.finished.connect(_on_finished)
        worker.signals.progress.connect(self._on_worker_progress)
        self.pool.start(worker)

    def _format_multigroup_issue(self, issue: ScanIssue) -> str:
        """Handle the format multigroup issue step for the Stats PySide6 workflow."""
        context_bits = []
        context = issue.context or {}
        for key in ("pid", "group", "path"):
            value = context.get(key)
            if value:
                context_bits.append(f"{key}={value}")
        extra = f" ({', '.join(context_bits)})" if context_bits else ""
        return f"[{issue.severity.upper()}] {issue.message}{extra}"

    def _render_multigroup_issues(self, issues: list[ScanIssue]) -> None:
        """Handle the render multigroup issues step for the Stats PySide6 workflow."""
        if not hasattr(self, "multi_group_issue_text"):
            return
        if not issues:
            self.multi_group_issue_text.setPlainText("No issues detected.")
            self.multi_group_issue_toggle_btn.setEnabled(False)
            return
        self.multi_group_issue_toggle_btn.setEnabled(len(issues) > self._multigroup_issue_preview_limit)
        if self._multigroup_issue_expanded or len(issues) <= self._multigroup_issue_preview_limit:
            visible_issues = issues
            self.multi_group_issue_toggle_btn.setText("Hide details")
        else:
            visible_issues = issues[: self._multigroup_issue_preview_limit]
            remaining = len(issues) - len(visible_issues)
            if remaining > 0:
                visible_issues = visible_issues + [
                    ScanIssue(
                        severity="warning",
                        message=f"... {remaining} more issue(s).",
                        context={},
                    )
                ]
            self.multi_group_issue_toggle_btn.setText("Show details")
        lines = [self._format_multigroup_issue(issue) for issue in visible_issues]
        self.multi_group_issue_text.setPlainText("\n".join(lines))

    def _toggle_multigroup_issue_details(self) -> None:
        """Handle the toggle multigroup issue details step for the Stats PySide6 workflow."""
        self._multigroup_issue_expanded = not self._multigroup_issue_expanded
        if self._multigroup_scan_result:
            self._render_multigroup_issues(self._multigroup_scan_result.issues)

    def _update_multigroup_summary(self, result: MultiGroupScanResult) -> None:
        """Handle the update multigroup summary step for the Stats PySide6 workflow."""
        if hasattr(self, "multi_group_ready_value"):
            status_text = "Ready" if result.multi_group_ready else "Not ready"
            self.multi_group_ready_value.setText(status_text)
            self.multi_group_ready_value.setStyleSheet(
                "color: #1b8a2f;" if result.multi_group_ready else "color: #b02a37;"
            )
        if hasattr(self, "multi_group_discovered_value"):
            self.multi_group_discovered_value.setText(str(len(result.discovered_subjects)))
        if hasattr(self, "multi_group_assigned_value"):
            self.multi_group_assigned_value.setText(str(len(result.assigned_subjects)))
        if hasattr(self, "multi_group_groups_value"):
            self.multi_group_groups_value.setText(str(len(result.subject_groups)))
        if hasattr(self, "multi_group_unassigned_value"):
            self.multi_group_unassigned_value.setText(str(len(result.unassigned_subjects)))
        if hasattr(self, "compute_shared_harmonics_btn"):
            self.compute_shared_harmonics_btn.setEnabled(bool(result.multi_group_ready))
        if not result.multi_group_ready:
            self._shared_harmonics_payload = {}
            self._fixed_harmonic_dv_payload = {}
            self._between_missingness_payload = {}
        self._refresh_fixed_harmonic_ui_state()

        self._render_multigroup_issues(result.issues)

        blocking = [issue for issue in result.issues if issue.severity == "blocking"]
        if blocking:
            message = f"Multi-group scan found {len(blocking)} blocking issue(s)."
            self._set_status(message)
            self.append_log("General", message, level="warning")
        else:
            self._set_status("Multi-group scan complete.")
        for issue in result.issues:
            log_level = "error" if issue.severity == "blocking" else "warning"
            logger.log(
                logging.ERROR if log_level == "error" else logging.WARNING,
                "stats_multigroup_issue",
                extra={
                    "severity": issue.severity,
                    "message": issue.message,
                    **(issue.context or {}),
                },
            )

    def _on_compute_shared_harmonics_clicked(self) -> None:
        """Handle the on compute shared harmonics clicked step for the Stats PySide6 workflow."""
        if not self.subject_data or not self.subjects:
            self._set_status("Load project data before computing shared harmonics.")
            return
        selected_conditions = self._get_selected_conditions()
        if not selected_conditions:
            self._set_status("Select at least one condition before computing shared harmonics.")
            return
        if not self.rois:
            self._set_status("Define at least one ROI before computing shared harmonics.")
            return
        if not self._multigroup_scan_result or not self._multigroup_scan_result.multi_group_ready:
            message = (
                "Shared harmonics are available only when multi-group scan status is Ready. "
                "Fix scan issues and rescan."
            )
            self._set_status(message)
            self.append_log("General", message, level="warning")
            return

        out_dir = self._ensure_results_dir()
        export_path = Path(out_dir) / "Shared Harmonics Summary.xlsx"
        self.compute_shared_harmonics_btn.setEnabled(False)

        worker = StatsWorker(
            stats_worker_funcs.run_shared_harmonics_worker,
            subjects=self.subjects,
            conditions=selected_conditions,
            subject_data=self.subject_data,
            base_freq=self._current_base_freq,
            rois=self.rois,
            exclude_harmonic1=self._dv_exclude_harmonic1,
            project_path=self._project_path,
            export_path=export_path,
            _op="shared_harmonics",
        )

        self._active_workers.append(worker)

        def _release() -> None:
            """Handle the release step for the Stats PySide6 workflow."""
            if worker in self._active_workers:
                self._active_workers.remove(worker)
            self.compute_shared_harmonics_btn.setEnabled(
                bool(self._multigroup_scan_result and self._multigroup_scan_result.multi_group_ready)
            )

        def _on_finished(payload: dict) -> None:
            """Handle the on finished step for the Stats PySide6 workflow."""
            try:
                result = payload if isinstance(payload, dict) else {}
                self._shared_harmonics_payload = result
                self._fixed_harmonic_dv_payload = {}
                harmonics_by_roi = result.get("harmonics_by_roi", {}) if isinstance(result, dict) else {}
                roi_count = len(harmonics_by_roi) if isinstance(harmonics_by_roi, dict) else 0
                total_harmonics = 0
                if isinstance(harmonics_by_roi, dict):
                    total_harmonics = sum(len(v or []) for v in harmonics_by_roi.values())
                conditions_used = result.get("conditions_used", []) if isinstance(result, dict) else []
                exclude_h1 = bool(result.get("exclude_harmonic1_applied", False))
                export_target = str(result.get("export_path", export_path))
                summary = (
                    "Shared harmonics complete: "
                    f"ROIs={roi_count}, total harmonics={total_harmonics}, "
                    f"exclude harmonic 1={exclude_h1}, "
                    f"conditions={', '.join(conditions_used) if conditions_used else 'None'}, "
                    f"export={export_target}"
                )
                self._set_status(summary)
                self.append_log("General", summary, level="info")
                self._set_last_export_path(export_target)
                self._refresh_fixed_harmonic_ui_state()
            finally:
                _release()

        def _on_error(message: str) -> None:
            """Handle the on error step for the Stats PySide6 workflow."""
            try:
                self._set_status(f"Shared harmonics error: {message}")
                self.append_log("General", f"Shared harmonics error: {message}", level="error")
                self._refresh_fixed_harmonic_ui_state()
            finally:
                _release()

        worker.signals.message.connect(self._on_worker_message)
        worker.signals.error.connect(_on_error)
        worker.signals.finished.connect(_on_finished)
        worker.signals.progress.connect(self._on_worker_progress)
        self.pool.start(worker)

    def _on_compute_fixed_harmonic_dv_clicked(self) -> None:
        """Handle the on compute fixed harmonic dv clicked step for the Stats PySide6 workflow."""
        harmonics_by_roi = self._shared_harmonics_payload.get("harmonics_by_roi", {})
        if not isinstance(harmonics_by_roi, dict) or not any((harmonics_by_roi.get(k) or []) for k in harmonics_by_roi):
            self._set_status("Compute shared harmonics before fixed-harmonic DV.")
            self._refresh_fixed_harmonic_ui_state()
            return

        selected_conditions = self._get_selected_conditions()
        if not selected_conditions:
            self._set_status("Select at least one condition before computing fixed-harmonic DV.")
            return

        self.compute_fixed_harmonic_dv_btn.setEnabled(False)
        worker = StatsWorker(
            stats_worker_funcs.run_fixed_harmonic_dv_worker,
            subjects=self.subjects,
            conditions=selected_conditions,
            subject_data=self.subject_data,
            rois=self.rois,
            harmonics_by_roi=harmonics_by_roi,
            _op="fixed_harmonic_dv",
        )

        self._active_workers.append(worker)

        def _release() -> None:
            """Handle the release step for the Stats PySide6 workflow."""
            if worker in self._active_workers:
                self._active_workers.remove(worker)
            self._refresh_fixed_harmonic_ui_state()

        def _on_finished(payload: dict) -> None:
            """Handle the on finished step for the Stats PySide6 workflow."""
            try:
                result = payload if isinstance(payload, dict) else {}
                dv_table = result.get("dv_table")
                missing_rows = result.get("missing_harmonics", [])
                row_count = int(len(dv_table.index)) if isinstance(dv_table, pd.DataFrame) else 0
                summary = (
                    "Fixed-harmonic DV ready: "
                    f"rows={row_count}, missing entries={len(missing_rows)}, cache=self._fixed_harmonic_dv_payload"
                )
                self._fixed_harmonic_dv_payload = {
                    "summary": summary,
                    "dv_table": dv_table,
                    "missing_harmonics": missing_rows,
                    "dv_policy": result.get("dv_policy", {}),
                }
                self._set_status(summary)
                self.append_log("General", summary, level="info")
            finally:
                _release()

        def _on_error(message: str) -> None:
            """Handle the on error step for the Stats PySide6 workflow."""
            try:
                self._set_status(f"Fixed-harmonic DV error: {message}")
                self.append_log("General", f"Fixed-harmonic DV error: {message}", level="error")
            finally:
                _release()

        worker.signals.message.connect(self._on_worker_message)
        worker.signals.error.connect(_on_error)
        worker.signals.finished.connect(_on_finished)
        worker.signals.progress.connect(self._on_worker_progress)
        self.pool.start(worker)


    def _known_group_labels(self) -> list[str]:
        """Handle the known group labels step for the Stats PySide6 workflow."""
        return sorted({g for g in (self.subject_groups or {}).values() if g})

    def _ensure_between_ready(self) -> bool:
        """Handle the ensure between ready step for the Stats PySide6 workflow."""
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
        """Handle the focus self step for the Stats PySide6 workflow."""
        self._focus_calls += 1
        self.raise_()
        self.activateWindow()

    def _set_running(self, running: bool) -> None:
        """Handle the set running step for the Stats PySide6 workflow."""
        buttons = [
            getattr(self, "analyze_single_btn", None),
            getattr(self, "single_advanced_btn", None),
            getattr(self, "analyze_between_btn", None),
            getattr(self, "between_advanced_btn", None),
            getattr(self, "lela_mode_btn", None),
            getattr(self, "btn_open_results", None),
            getattr(self, "compute_shared_harmonics_btn", None),
            getattr(self, "compute_fixed_harmonic_dv_btn", None),
        ]
        for b in buttons:
            if b:
                b.setEnabled(not running)
        if not running and hasattr(self, "compute_shared_harmonics_btn"):
            self.compute_shared_harmonics_btn.setEnabled(
                bool(self._multigroup_scan_result and self._multigroup_scan_result.multi_group_ready)
            )
            self._refresh_fixed_harmonic_ui_state()
        spinner = getattr(self, "spinner", None)
        if spinner:
            if running:
                spinner.show()
                spinner.start()
            else:
                spinner.stop()
                spinner.hide()

    def _begin_run(self) -> bool:
        """Handle the begin run step for the Stats PySide6 workflow."""
        if not self._guard.start():
            return False
        self._set_running(True)
        self._focus_self()
        return True

    def _end_run(self) -> None:
        """Handle the end run step for the Stats PySide6 workflow."""
        self._set_running(False)
        self._guard.done()
        self._focus_self()

    # --------- settings helpers ---------

    def _safe_settings_get(self, section: str, key: str, default) -> Tuple[bool, object]:
        """Handle the safe settings get step for the Stats PySide6 workflow."""
        try:
            settings = SettingsManager()
            val = settings.get(section, key, default)
            return True, val
        except Exception as e:
            self._log_ui_error(f"settings_get:{section}/{key}", e)
            return False, default

    def _get_analysis_settings(self) -> Optional[Tuple[float, float]]:
        """Handle the get analysis settings step for the Stats PySide6 workflow."""
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
        """Handle the get harmonic settings step for the Stats PySide6 workflow."""
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

    def _get_qc_settings(self) -> Optional[tuple[float, float]]:
        """Handle the get qc settings step for the Stats PySide6 workflow."""
        ok_warn, warn = self._safe_settings_get(
            "analysis", "qc_warn_threshold", self._qc_threshold_sumabs
        )
        if not ok_warn:
            ok_warn, warn = self._safe_settings_get(
                "analysis", "qc_threshold_sumabs", self._qc_threshold_sumabs
            )
        ok_critical, critical = self._safe_settings_get(
            "analysis", "qc_critical_threshold", self._qc_threshold_maxabs
        )
        if not ok_critical:
            ok_critical, critical = self._safe_settings_get(
                "analysis", "qc_threshold_maxabs", self._qc_threshold_maxabs
            )
        try:
            warn_val = float(warn)
            critical_val = float(critical)
        except Exception as exc:
            QMessageBox.critical(self, "Settings Error", f"Invalid QC thresholds: {exc}")
            return None
        if not (ok_warn and ok_critical):
            QMessageBox.critical(self, "Settings Error", "Could not load QC thresholds.")
            return None
        return warn_val, critical_val

    # --------- centralized pre-run guards ---------

    def _precheck(self, *, require_anova: bool = False, start_guard: bool = True) -> bool:
        """Handle the precheck step for the Stats PySide6 workflow."""
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
        if self.subjects and set(self.subjects).issubset(self.manual_excluded_pids):
            message = "All participants are manually excluded. Clear exclusions to run analysis."
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
        qc_cfg = self._get_qc_settings()
        if not qc_cfg:
            return False
        self._qc_threshold_sumabs, self._qc_threshold_maxabs = qc_cfg
        if start_guard and not self._begin_run():
            return False
        return True

    # --------- exports plumbing ---------

    def export_results(self, kind: str, data, out_dir: str) -> list[Path]:
        """Handle the export results step for the Stats PySide6 workflow."""
        mapping = {
            "anova": (export_rm_anova_results_to_excel, ANOVA_XLS),
            "lmm": (export_mixed_model_results_to_excel, LMM_XLS),
            "posthoc": (export_posthoc_results_to_excel, POSTHOC_XLS),
            "harmonic": (export_harmonic_results_to_excel, HARMONIC_XLS),
            "anova_between": (export_rm_anova_results_to_excel, ANOVA_BETWEEN_XLS),
            "lmm_between": (export_mixed_model_results_to_excel, LMM_BETWEEN_XLS),
            "group_contrasts": (export_group_contrasts_workbook, GROUP_CONTRAST_XLS),
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
                """Handle the adapter step for the Stats PySide6 workflow."""
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

        if kind in {"anova", "anova_between"} and isinstance(data, pd.DataFrame):
            log_rm_anova_p_minima(data)

        path = safe_export_call(
            func,
            data,
            out_dir,
            fname,
            log_func=self._set_status,
        )
        if kind in {"anova", "anova_between"}:
            apply_rm_anova_pvalue_number_formats(path)
        if kind in {"lmm", "lmm_between"} and isinstance(data, pd.DataFrame):
            apply_lmm_number_formats_and_metadata(path, lmm_df=data)
        return [path]

    def _write_dv_metadata(self, out_dir: str, pipeline_id: PipelineId) -> None:
        """Handle the write dv metadata step for the Stats PySide6 workflow."""
        dv_policy = self._pipeline_dv_policy.get(pipeline_id, self._get_dv_policy_payload())
        conditions = self._pipeline_conditions.get(pipeline_id, self._get_selected_conditions())
        base_freq = self._pipeline_base_freq.get(pipeline_id, self._current_base_freq)
        dv_meta = self._pipeline_dv_metadata.get(pipeline_id, {})
        dv_variants = self._pipeline_dv_variants.get(pipeline_id, [])
        payload = {
            "policy_name": dv_meta.get("policy_name", dv_policy.get("name", LEGACY_POLICY_NAME)),
            "fixed_k": dv_meta.get("fixed_k", dv_policy.get("fixed_k", 5)),
            "exclude_harmonic1": dv_meta.get("exclude_harmonic1", dv_policy.get("exclude_harmonic1", True)),
            "exclude_base_harmonics": dv_meta.get(
                "exclude_base_harmonics", dv_policy.get("exclude_base_harmonics", True)
            ),
            "z_threshold": dv_meta.get("z_threshold", dv_policy.get("z_threshold", 1.64)),
            "empty_list_policy": dv_meta.get(
                "empty_list_policy", dv_policy.get("empty_list_policy", EMPTY_LIST_FALLBACK_FIXED_K)
            ),
            "base_frequency_hz": base_freq,
            "selected_conditions": list(conditions),
            "variant_methods": list(dv_variants),
        }
        try:
            out_path = Path(out_dir) / "dv_metadata.json"
            out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception:  # noqa: BLE001
            logger.exception("Failed to write DV metadata export.")

        rossion_meta = dv_meta.get("rossion_method") if isinstance(dv_meta, dict) else None
        if not isinstance(rossion_meta, dict):
            return

        try:
            summary_rows = [
                {"key": "Primary DV method", "value": payload["policy_name"]},
                {"key": "Base frequency (Hz)", "value": payload["base_frequency_hz"]},
                {"key": "Z threshold", "value": payload.get("z_threshold")},
                {"key": "Empty list policy", "value": payload.get("empty_list_policy")},
                {"key": "Selected conditions", "value": ", ".join(payload["selected_conditions"])},
                {
                    "key": "DV variants (exported)",
                    "value": ", ".join(payload.get("variant_methods", [])) or "None",
                },
            ]
            if isinstance(rossion_meta, dict):
                summary_rows.append(
                    {
                        "key": "Stop rule",
                        "value": "Stop after 2 consecutive non-significant harmonics",
                    }
                )
            summary_df = pd.DataFrame(summary_rows)

            union_map = rossion_meta.get("union_harmonics_by_roi", {}) or {}
            fallback_info = rossion_meta.get("fallback_info_by_roi", {}) or {}
            stop_meta = rossion_meta.get("stop_metadata_by_roi", {}) or {}
            roi_rows = []
            for roi_name, harmonics in union_map.items():
                fallback = fallback_info.get(roi_name, {})
                stop_info = stop_meta.get(roi_name, {})
                roi_rows.append(
                    {
                        "roi": roi_name,
                        "union_harmonics_hz": ", ".join(f"{freq:g}" for freq in harmonics) or "—",
                        "harmonic_count": len(harmonics),
                        "empty_list_policy": fallback.get("policy", payload.get("empty_list_policy")),
                        "fallback_used": bool(fallback.get("fallback_used", False)),
                        "fallback_harmonics_hz": ", ".join(
                            f"{freq:g}" for freq in fallback.get("fallback_harmonics", [])
                        )
                        or "—",
                        "stop_reason": stop_info.get("stop_reason", "—"),
                        "stop_fail_harmonics_hz": ", ".join(
                            f"{freq:g}" for freq in stop_info.get("fail_harmonics", []) or []
                        )
                        or "—",
                        "n_scanned": stop_info.get("n_scanned", "—"),
                    }
                )
            roi_df = pd.DataFrame(roi_rows)
            mean_z_table = rossion_meta.get("mean_z_table")

            dv_path = Path(out_dir) / "Summed BCA DV Definition.xlsx"
            with pd.ExcelWriter(dv_path, engine="openpyxl") as writer:
                summary_df.to_excel(writer, sheet_name="DV Definition", index=False)
                roi_df.to_excel(writer, sheet_name="ROI Harmonics", index=False)
                if isinstance(mean_z_table, pd.DataFrame):
                    mean_z_table.to_excel(writer, sheet_name="Mean Z Table", index=False)
            self._set_status(f"Exported DV definition to {dv_path}")
            self._set_last_export_path(str(dv_path))
        except Exception:  # noqa: BLE001
            logger.exception("Failed to write DV definition export.")

    def _ensure_results_dir(self) -> str:
        """Handle the ensure results dir step for the Stats PySide6 workflow."""
        target = ensure_results_dir(
            self._project_path,
            self._results_folder_hint,
            self._subfolder_hints,
            results_subfolder_name=STATS_SUBFOLDER_NAME,
        )
        return str(target)

    def _open_results_folder(self) -> None:
        """Handle the open results folder step for the Stats PySide6 workflow."""
        out_dir = self._ensure_results_dir()
        QDesktopServices.openUrl(QUrl.fromLocalFile(out_dir))

    def _update_export_buttons(self) -> None:
        """Handle the update export buttons step for the Stats PySide6 workflow."""
        def _maybe_enable(name: str, enabled: bool) -> None:
            """Handle the maybe enable step for the Stats PySide6 workflow."""
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
        fixed_payload = self._fixed_harmonic_dv_payload if isinstance(self._fixed_harmonic_dv_payload, dict) else {}
        fixed_table = fixed_payload.get("dv_table")
        _maybe_enable(
            "export_qc_context_btn",
            isinstance(fixed_table, pd.DataFrame) and not fixed_table.empty,
        )

    def _build_summary_frames(self, pipeline_id: PipelineId) -> StatsSummaryFrames:
        """Handle the build summary frames step for the Stats PySide6 workflow."""
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
        """Handle the render summary step for the Stats PySide6 workflow."""
        lines = (summary_text or "").splitlines()
        if not lines:
            self.summary_text.append("(No summary generated.)")
            self.summary_text.append("")
            return
        header = lines[0].strip()
        try:
            cursor = self.summary_text.textCursor()
            cursor.movePosition(QTextCursor.End)
            self.summary_text.setTextCursor(cursor)
            if header:
                self.summary_text.insertHtml(f"<b>{header}</b><br>")
            for line in lines[1:]:
                self.summary_text.append(line)
            self.summary_text.append("")
        except Exception:  # noqa: BLE001
            logger.exception("Failed to render summary text", exc_info=True)
            if header:
                self.summary_text.append(header)
            for line in lines[1:]:
                self.summary_text.append(line)
            self.summary_text.append("")

    def _collect_excluded_reasons(self, pipeline_id: PipelineId) -> dict[str, str]:
        """Handle the collect excluded reasons step for the Stats PySide6 workflow."""
        report = self._pipeline_run_reports.get(pipeline_id)
        if not isinstance(report, StatsRunReport):
            return {}
        reasons: dict[str, str] = {}
        for pid in report.manual_excluded_pids:
            reasons[str(pid)] = "manual exclusion"
        if report.qc_report:
            for participant in report.qc_report.participants:
                reasons[str(participant.participant_id)] = "QC exclusion"
        if report.required_exclusions:
            for violation in report.required_exclusions:
                reasons[str(violation.participant_id)] = f"required DV exclusion ({violation.reason})"
        return reasons

    def _build_reporting_summary_payload(self, pipeline_id: PipelineId, elapsed_ms: int) -> dict[str, object]:
        """Handle the build reporting summary payload step for the Stats PySide6 workflow."""
        selected_conditions = self._pipeline_conditions.get(pipeline_id, self._get_selected_conditions())
        selected_rois = sorted((self.rois or {}).keys())
        report = self._pipeline_run_reports.get(pipeline_id)
        included = report.final_modeled_pids if isinstance(report, StatsRunReport) else []
        context = ReportingSummaryContext(
            project_name=self.project_title,
            project_root=self._project_path,
            pipeline_name=pipeline_id.name,
            generated_local=datetime.now().astimezone(),
            elapsed_ms=int(elapsed_ms),
            timezone_label=str(datetime.now().astimezone().tzinfo or "Local"),
            total_participants=len(self.subjects),
            included_participants=list(included),
            excluded_reasons=self._collect_excluded_reasons(pipeline_id),
            selected_conditions=list(selected_conditions),
            selected_rois=selected_rois,
        )
        anova_df = self.rm_anova_results_data if pipeline_id is PipelineId.SINGLE else self.between_anova_results_data
        lmm_df = self.mixed_model_results_data if pipeline_id is PipelineId.SINGLE else self.between_mixed_model_results_data
        posthoc_df = self.posthoc_results_data if pipeline_id is PipelineId.SINGLE else self.group_contrasts_results_data
        auto_export = bool(getattr(self, "reporting_summary_export_checkbox", None) and self.reporting_summary_export_checkbox.isChecked())
        return {
            "context": context,
            "anova_df": anova_df,
            "lmm_df": lmm_df,
            "posthoc_df": posthoc_df,
            "auto_export": auto_export,
        }

    def _start_reporting_summary_worker(self, pipeline_id: PipelineId, elapsed_ms: int) -> None:
        """Handle the start reporting summary worker step for the Stats PySide6 workflow."""
        payload = self._build_reporting_summary_payload(pipeline_id, elapsed_ms)

        def _worker_fn(progress_emit, message_emit, *, worker_payload):
            """Handle the worker fn step for the Stats PySide6 workflow."""
            del progress_emit, message_emit
            context = worker_payload["context"]
            text = build_reporting_summary(
                context,
                anova_df=worker_payload.get("anova_df"),
                lmm_df=worker_payload.get("lmm_df"),
                posthoc_df=worker_payload.get("posthoc_df"),
            )
            result = {"report_text": text}
            if worker_payload.get("auto_export"):
                target = build_default_report_path(context.project_root, context.generated_local)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text, encoding="utf-8")
                result["report_path"] = str(target)
            return result

        worker = StatsWorker(_worker_fn, worker_payload=payload, _op="reporting_summary")

        def _on_finished(worker_result: dict) -> None:
            """Handle the on finished step for the Stats PySide6 workflow."""
            report_path = worker_result.get("report_path") if isinstance(worker_result, dict) else None
            if report_path:
                self._set_last_export_path(str(report_path))
                self._set_status(f"Reporting summary exported: {report_path}")

        def _on_error(message: str) -> None:
            """Handle the on error step for the Stats PySide6 workflow."""
            logger.error(
                "stats_reporting_summary_failed",
                extra={
                    "operation": "build_reporting_summary",
                    "project": self.project_title,
                    "path": "",
                    "elapsed_ms": int(elapsed_ms),
                    "exception": message,
                },
            )
            self._set_status("Reporting summary generation failed; statistics exports are still complete.")

        worker.signals.report_ready.connect(self._on_report_ready)
        worker.signals.finished.connect(_on_finished)
        worker.signals.error.connect(_on_error)
        self.pool.start(worker)

    @Slot(str)
    def _on_report_ready(self, report_text: str) -> None:
        """Handle the on report ready step for the Stats PySide6 workflow."""
        self._reporting_summary_text = report_text or ""
        self.reporting_summary_text.setPlainText(self._reporting_summary_text)

    # --------- worker signal wiring ---------

    def _wire_and_start(self, worker: StatsWorker, finished_slot) -> None:
        """Handle the wire and start step for the Stats PySide6 workflow."""
        worker.signals.progress.connect(self._on_worker_progress)
        worker.signals.message.connect(self._on_worker_message)
        worker.signals.error.connect(self._on_worker_error)
        worker.signals.finished.connect(finished_slot)
        self.pool.start(worker)

    def set_busy(self, is_busy: bool) -> None:
        """Handle the set busy step for the Stats PySide6 workflow."""
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
            """Handle the on finished step for the Stats PySide6 workflow."""
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
            """Handle the on error step for the Stats PySide6 workflow."""
            logger.error(
                "stats_view_error_slot_enter",
                extra={
                    "pipeline": getattr(pid, "name", str(pid)),
                    "step": getattr(sid, "name", str(sid)),
                    "error_message": message,
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
        """Handle the ensure results dir step for the Stats PySide6 workflow."""
        return self._ensure_results_dir()

    def prompt_phase_folder(self, title: str, start_dir: str | None = None) -> Optional[str]:
        """Handle the prompt phase folder step for the Stats PySide6 workflow."""
        folder = QFileDialog.getExistingDirectory(self, title, start_dir or self.project_dir)
        return folder or None

    def get_analysis_settings_snapshot(self) -> tuple[float, float, dict, list[str]]:
        """Handle the get analysis settings snapshot step for the Stats PySide6 workflow."""
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
        """Handle the ensure pipeline ready step for the Stats PySide6 workflow."""
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
        if pipeline_id is PipelineId.BETWEEN:
            if not (self._multigroup_scan_result and self._multigroup_scan_result.multi_group_ready):
                message = "Between-group analysis is blocked: multi-group readiness is not satisfied."
                self._set_status(message)
                self.append_log("Between", message, level="warning")
                return False
            harmonics_by_roi = self._shared_harmonics_payload.get("harmonics_by_roi", {})
            has_shared = isinstance(harmonics_by_roi, dict) and any(
                (harmonics_by_roi.get(key) or []) for key in harmonics_by_roi
            )
            if not has_shared:
                message = "Between-group analysis is blocked: compute shared harmonics first."
                self._set_status(message)
                self.append_log("Between", message, level="warning")
                return False
            dv_table = self._fixed_harmonic_dv_payload.get("dv_table")
            if not isinstance(dv_table, pd.DataFrame) or dv_table.empty:
                message = "Between-group analysis is blocked: compute fixed-harmonic DV first."
                self._set_status(message)
                self.append_log("Between", message, level="warning")
                return False
        self._log_pipeline_event(pipeline=pipeline_id, event="end")
        return True

    def on_pipeline_started(self, pipeline_id: PipelineId) -> None:
        """Handle the on pipeline started step for the Stats PySide6 workflow."""
        self._pipeline_start_perf[pipeline_id] = time.perf_counter()
        self._active_pipeline = pipeline_id
        self._harmonic_results[pipeline_id] = []
        self._pipeline_conditions[pipeline_id] = self._get_selected_conditions()
        self._pipeline_dv_policy[pipeline_id] = self._get_dv_policy_payload()
        self._pipeline_base_freq[pipeline_id] = self._current_base_freq
        self._pipeline_dv_metadata[pipeline_id] = {}
        self._pipeline_dv_variants[pipeline_id] = self._get_selected_dv_variants()
        self._pipeline_dv_variant_payloads[pipeline_id] = {}
        self._pipeline_outlier_config[pipeline_id] = self._get_outlier_exclusion_payload()
        self._pipeline_qc_config[pipeline_id] = self._get_qc_exclusion_payload()
        self._pipeline_qc_state[pipeline_id] = {"report": None}
        self._pipeline_run_reports[pipeline_id] = None
        if pipeline_id is PipelineId.BETWEEN:
            self._between_missingness_payload = {}
        label = self.single_status_lbl if pipeline_id is PipelineId.SINGLE else self.between_status_lbl
        if label:
            label.setText("Running…")
        btn = self.analyze_single_btn if pipeline_id is PipelineId.SINGLE else self.analyze_between_btn
        if btn:
            btn.setEnabled(False)
        self._focus_self()
        self._log_pipeline_event(pipeline=pipeline_id, event="started")

    def store_dv_variants_payload(
        self, pipeline_id: PipelineId, dv_variants: dict | None
    ) -> None:
        """Handle the store dv variants payload step for the Stats PySide6 workflow."""
        if not isinstance(dv_variants, dict) or not dv_variants:
            return
        self._store_dv_variants(pipeline_id, {"dv_variants": dv_variants})

    def on_analysis_finished(
        self,
        pipeline_id: PipelineId,
        success: bool,
        error_message: Optional[str],
        *,
        exports_ran: bool,
    ) -> None:
        """Handle the on analysis finished step for the Stats PySide6 workflow."""
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
                elapsed_ms = int((time.perf_counter() - self._pipeline_start_perf.get(pipeline_id, time.perf_counter())) * 1000)
                section = self._section_label(pipeline_id)
                if exports_ran:
                    if pipeline_id is PipelineId.SINGLE:
                        self.append_log(section, "  • Results exported for Single Group Analysis")
                    elif pipeline_id is PipelineId.BETWEEN:
                        self.append_log(section, "  • Results exported for Between-Group Analysis")
                        summary = self._between_missingness_payload.get("summary") if isinstance(self._between_missingness_payload, dict) else None
                        export_path = self._between_missingness_payload.get("export_path") if isinstance(self._between_missingness_payload, dict) else None
                        if isinstance(summary, dict):
                            line = (
                                "Between-group complete: "
                                f"groups={summary.get('n_groups', 0)}, "
                                f"mixed subjects={summary.get('n_mixed_subjects', 0)}, "
                                f"ANOVA complete-case={summary.get('n_anova_complete_case', 0)}, "
                                f"missingness export={export_path or 'pending export'}"
                            )
                            self._set_status(line)
                            self.append_log(section, line, level="info")
                    stats_folder = Path(self._ensure_results_dir())
                    self._prompt_view_results(self._section_label(pipeline_id), stats_folder)
                else:
                    self.append_log(section, "  • Analysis completed", level="info")
                self._start_reporting_summary_worker(pipeline_id, elapsed_ms)
            elif error_message:
                if "blocked" in error_message.lower():
                    self._set_status(error_message)
                    self.append_log(self._section_label(pipeline_id), error_message, level="warning")
                else:
                    try:
                        QMessageBox.critical(self, "Analysis Error", error_message)
                    except Exception:  # noqa: BLE001
                        logger.exception("Failed to display error dialog", exc_info=True)
            self._show_outlier_exclusion_dialog(pipeline_id)
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
        """Handle the closeEvent step for the Stats PySide6 workflow."""
        logger.info(
            "stats_window_close_event",
            extra={
                "window_id": id(self),
                "project_dir": getattr(self, "project_dir", ""),
            },
        )
        super().closeEvent(event)

    def build_and_render_summary(self, pipeline_id: PipelineId) -> None:
        """Handle the build and render summary step for the Stats PySide6 workflow."""
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
        """Handle the export pipeline results step for the Stats PySide6 workflow."""
        if pipeline_id is PipelineId.SINGLE:
            return self._export_single_pipeline()
        if pipeline_id is PipelineId.BETWEEN:
            return self._export_between_pipeline()
        return False

    def _build_harmonic_kwargs(self) -> dict:
        # [SAFETY UPDATE] Load fresh ROIs from settings to ensure thread receives
        # the most up-to-date map, preventing 0xC0000005 errors.
        """Handle the build harmonic kwargs step for the Stats PySide6 workflow."""
        fresh_rois = load_rois_from_settings() or self.rois
        manual_excluded = set(self.manual_excluded_pids)
        filtered_subjects = [pid for pid in self.subjects if pid not in manual_excluded]
        filtered_subject_data = {
            pid: data for pid, data in self.subject_data.items() if pid not in manual_excluded
        }

        return dict(
            subject_data=filtered_subject_data,
            subjects=filtered_subjects,
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
        """Handle the get step config step for the Stats PySide6 workflow."""
        dv_variants_payload = self._get_dv_variant_payloads()
        outlier_payload = self._pipeline_outlier_config.get(
            pipeline_id, self._get_outlier_exclusion_payload()
        )
        qc_payload = self._pipeline_qc_config.get(pipeline_id, self._get_qc_exclusion_payload())
        qc_state = self._pipeline_qc_state.get(pipeline_id, {"report": None})
        if pipeline_id is PipelineId.SINGLE:
            if step_id is StepId.RM_ANOVA:
                kwargs = dict(
                    subjects=self.subjects,
                    conditions=self._get_selected_conditions(),
                    conditions_all=self.conditions,
                    subject_data=self.subject_data,
                    base_freq=self._current_base_freq,
                    rois=self.rois,
                    rois_all=self.rois,
                    dv_policy=self._get_between_group_dv_policy_payload(),
                    dv_variants=dv_variants_payload,
                    outlier_exclusion_enabled=outlier_payload.get("enabled", True),
                    outlier_abs_limit=outlier_payload.get("abs_limit", 50.0),
                    qc_config=qc_payload,
                    qc_state=qc_state,
                    manual_excluded_pids=sorted(self.manual_excluded_pids),
                )
                if os.getenv("FPVS_RM_ANOVA_DIAG", "0").strip() == "1":
                    kwargs["results_dir"] = self._ensure_results_dir()
                def handler(payload):
                    """Handle the handler step for the Stats PySide6 workflow."""
                    self._apply_rm_anova_results(payload, update_text=False)

                return kwargs, handler
            if step_id is StepId.MIXED_MODEL:
                kwargs = dict(
                    subjects=self.subjects,
                    conditions=self._get_selected_conditions(),
                    conditions_all=self.conditions,
                    subject_data=self.subject_data,
                    base_freq=self._current_base_freq,
                    alpha=self._current_alpha,
                    rois=self.rois,
                    rois_all=self.rois,
                    subject_groups=self.subject_groups,
                    dv_policy=self._get_between_group_dv_policy_payload(),
                    dv_variants=dv_variants_payload,
                    outlier_exclusion_enabled=outlier_payload.get("enabled", True),
                    outlier_abs_limit=outlier_payload.get("abs_limit", 50.0),
                    qc_config=qc_payload,
                    qc_state=qc_state,
                    manual_excluded_pids=sorted(self.manual_excluded_pids),
                )
                def handler(payload):
                    """Handle the handler step for the Stats PySide6 workflow."""
                    self._apply_mixed_model_results(payload, update_text=False)

                return kwargs, handler
            if step_id is StepId.INTERACTION_POSTHOCS:
                kwargs = dict(
                    subjects=self.subjects,
                    conditions=self._get_selected_conditions(),
                    conditions_all=self.conditions,
                    subject_data=self.subject_data,
                    base_freq=self._current_base_freq,
                    alpha=self._current_alpha,
                    rois=self.rois,
                    rois_all=self.rois,
                    subject_groups=self.subject_groups,
                    dv_policy=self._get_between_group_dv_policy_payload(),
                    dv_variants=dv_variants_payload,
                    outlier_exclusion_enabled=outlier_payload.get("enabled", True),
                    outlier_abs_limit=outlier_payload.get("abs_limit", 50.0),
                    qc_config=qc_payload,
                    qc_state=qc_state,
                    manual_excluded_pids=sorted(self.manual_excluded_pids),
                )
                def handler(payload):
                    """Handle the handler step for the Stats PySide6 workflow."""
                    self._apply_posthoc_results(payload, update_text=True)

                return kwargs, handler
            if step_id is StepId.HARMONIC_CHECK:
                kwargs = self._build_harmonic_kwargs()

                def handler(payload, *, pid=pipeline_id):
                    """Handle the handler step for the Stats PySide6 workflow."""
                    self._apply_harmonic_results(payload, pipeline_id=pid, update_text=True)

                return kwargs, handler
        if pipeline_id is PipelineId.BETWEEN:
            fixed_dv_table = self._fixed_harmonic_dv_payload.get("dv_table")
            selected_conditions = self._get_selected_conditions()
            if step_id is StepId.BETWEEN_GROUP_ANOVA:
                kwargs = dict(
                    subjects=self.subjects,
                    conditions=selected_conditions,
                    conditions_all=self.conditions,
                    subject_data=self.subject_data,
                    base_freq=self._current_base_freq,
                    rois=self.rois,
                    rois_all=self.rois,
                    subject_groups=self.subject_groups,
                    dv_policy=self._get_between_group_dv_policy_payload(),
                    dv_variants=dv_variants_payload,
                    outlier_exclusion_enabled=outlier_payload.get("enabled", True),
                    outlier_abs_limit=outlier_payload.get("abs_limit", 50.0),
                    qc_config=qc_payload,
                    qc_state=qc_state,
                    manual_excluded_pids=sorted(self.manual_excluded_pids),
                    fixed_harmonic_dv_table=fixed_dv_table,
                    required_conditions=selected_conditions,
                    subject_to_group=self.subject_groups,
                )
                def handler(payload):
                    """Handle the handler step for the Stats PySide6 workflow."""
                    self._apply_between_anova_results(payload, update_text=False)

                return kwargs, handler
            if step_id is StepId.BETWEEN_GROUP_MIXED_MODEL:
                results_dir = self._ensure_results_dir()
                kwargs = dict(
                    subjects=self.subjects,
                    conditions=self._get_selected_conditions(),
                    conditions_all=self.conditions,
                    subject_data=self.subject_data,
                    base_freq=self._current_base_freq,
                    alpha=self._current_alpha,
                    rois=self.rois,
                    rois_all=self.rois,
                    subject_groups=self.subject_groups,
                    include_group=True,
                    dv_policy=self._get_between_group_dv_policy_payload(),
                    dv_variants=dv_variants_payload,
                    outlier_exclusion_enabled=outlier_payload.get("enabled", True),
                    outlier_abs_limit=outlier_payload.get("abs_limit", 50.0),
                    qc_config=qc_payload,
                    qc_state=qc_state,
                    manual_excluded_pids=sorted(self.manual_excluded_pids),
                    fixed_harmonic_dv_table=fixed_dv_table,
                    required_conditions=selected_conditions,
                    subject_to_group=self.subject_groups,
                    results_dir=results_dir,
                )
                def handler(payload):
                    """Handle the handler step for the Stats PySide6 workflow."""
                    self._apply_between_mixed_results(payload, update_text=False)

                return kwargs, handler
            if step_id is StepId.GROUP_CONTRASTS:
                kwargs = dict(
                    subjects=self.subjects,
                    conditions=self._get_selected_conditions(),
                    conditions_all=self.conditions,
                    subject_data=self.subject_data,
                    base_freq=self._current_base_freq,
                    alpha=self._current_alpha,
                    rois=self.rois,
                    rois_all=self.rois,
                    subject_groups=self.subject_groups,
                    dv_policy=self._get_between_group_dv_policy_payload(),
                    dv_variants=dv_variants_payload,
                    outlier_exclusion_enabled=outlier_payload.get("enabled", True),
                    outlier_abs_limit=outlier_payload.get("abs_limit", 50.0),
                    qc_config=qc_payload,
                    qc_state=qc_state,
                    manual_excluded_pids=sorted(self.manual_excluded_pids),
                )
                def handler(payload):
                    """Handle the handler step for the Stats PySide6 workflow."""
                    self._apply_group_contrasts_results(payload, update_text=True)

                return kwargs, handler
            if step_id is StepId.HARMONIC_CHECK:
                kwargs = self._build_harmonic_kwargs()

                def handler(payload, *, pid=pipeline_id):
                    """Handle the handler step for the Stats PySide6 workflow."""
                    self._apply_harmonic_results(payload, pipeline_id=pid, update_text=True)

                return kwargs, handler
        raise ValueError(f"Unsupported step configuration for {pipeline_id} / {step_id}")

    def _prompt_view_results(self, section: str, stats_folder: Path) -> None:
        """Handle the prompt view results step for the Stats PySide6 workflow."""
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

    def _show_outlier_exclusion_dialog(self, pipeline_id: PipelineId) -> None:
        """Handle the show outlier exclusion dialog step for the Stats PySide6 workflow."""
        dialog = self._build_flagged_participants_dialog(pipeline_id)
        if dialog is None:
            return
        dialog.exec()

    def _build_flagged_participants_dialog(self, pipeline_id: PipelineId) -> QDialog | None:
        """Handle the build flagged participants dialog step for the Stats PySide6 workflow."""
        report = self._pipeline_run_reports.get(pipeline_id)
        if not isinstance(report, StatsRunReport):
            return None

        qc_report = report.qc_report
        dv_report = report.dv_report
        summary_df, details_df = build_flagged_participants_tables(qc_report, dv_report)
        dv_meta = self._pipeline_dv_metadata.get(pipeline_id, {})
        dv_display_name = dv_meta.get("dv_display_name") if isinstance(dv_meta, dict) else None
        dv_unit = dv_meta.get("dv_unit") if isinstance(dv_meta, dict) else None

        dialog = QDialog(self)
        dialog.setWindowTitle("Flagged Participants Report")
        dialog.setModal(True)
        layout = QVBoxLayout(dialog)

        flag_count_definition = (
            "Flag count = number of individual condition×ROI QC checks "
            "(and/or DV cells) that triggered for this participant."
        )
        summary_lines = [
            "QC scanned all conditions/ROIs in the project, independent of selections.",
            "Flagged Participants Summary",
            flag_count_definition,
            f"Manual exclusions: {len(self.manual_excluded_pids)}",
            f"Required exclusions (non-finite DV): {len(report.required_exclusions)}",
            f"QC flagged: {qc_report.summary.n_subjects_flagged if qc_report else 0}",
            f"DV flagged: {dv_report.summary.n_subjects_flagged if dv_report else 0}",
        ]
        if summary_df.empty:
            summary_lines.append("No participants were flagged.")
        summary_text = "\n".join(summary_lines)

        summary_box = QTextEdit()
        summary_box.setReadOnly(True)
        summary_box.setPlainText(summary_text)
        summary_box.setMinimumHeight(160)
        summary_box.setToolTip(
            "Summary of QC/DV flags and manual/required exclusions."
        )
        layout.addWidget(summary_box)

        display_rows: list[dict[str, object]] = []
        details_map: dict[str, str] = {}
        table: QTableWidget | None = None
        if not summary_df.empty:
            table = QTableWidget(summary_df.shape[0], 7)
            table.setHorizontalHeaderLabels(
                [
                    "Participant",
                    "Flag types",
                    "Flag count",
                    "Worst value",
                    "Condition",
                    "ROI",
                    "Explanation",
                ]
            )
            header = table.horizontalHeader()
            for idx in range(6):
                header.setSectionResizeMode(idx, QHeaderView.ResizeToContents)
            header.setSectionResizeMode(6, QHeaderView.Stretch)
            header.setStretchLastSection(True)
            flag_count_header = table.horizontalHeaderItem(2)
            if flag_count_header is not None:
                flag_count_header.setToolTip(flag_count_definition)

            table.verticalHeader().setVisible(False)
            table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            table.setSelectionMode(QAbstractItemView.SingleSelection)
            table.setSelectionBehavior(QAbstractItemView.SelectRows)
            table.setWordWrap(False)
            table.setTextElideMode(Qt.ElideRight)
            table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            row_height = int(table.fontMetrics().height() * 1.6)
            table.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
            table.verticalHeader().setDefaultSectionSize(row_height)

            details_map = {
                str(pid): "\n".join(
                    [
                        f"Flag types: {format_flag_types_display(group['flag_type'].tolist())}",
                        "",
                        "Violations:",
                        *[
                            f"- {format_flag_types_display([str(row['flag_type'])])}: "
                            f"{row['reason_text']}"
                            for _, row in group.iterrows()
                        ],
                    ]
                )
                for pid, group in details_df.groupby("participant_id", sort=True)
            }

            for row, (_, item) in enumerate(summary_df.iterrows()):
                participant_id = str(item["participant_id"])
                raw_flag_types = [flag.strip() for flag in str(item["flag_types"]).split(",") if flag]
                flag_types_display = format_flag_types_display(raw_flag_types)
                group = details_df[details_df["participant_id"] == participant_id]
                worst_flag_type = raw_flag_types[0] if raw_flag_types else None
                severity = "FLAG"
                if not group.empty:
                    match = group[
                        (group["condition"] == item["worst_condition"])
                        & (group["roi"] == item["worst_roi"])
                        & (group["metric_value"] == item["worst_value"])
                    ]
                    if match.empty:
                        match = group
                    worst_flag_type = str(match.iloc[0]["flag_type"])
                    severity = str(match.iloc[0]["severity"])

                worst_value = item["worst_value"]
                worst_value_float = float(worst_value) if pd.notna(worst_value) else float("nan")
                worst_text, worst_tooltip = format_worst_value_display(
                    worst_flag_type,
                    worst_value_float,
                    dv_display_name=dv_display_name if isinstance(dv_display_name, str) else None,
                    dv_unit=dv_unit if isinstance(dv_unit, str) else None,
                )
                summary_text = build_flagged_participant_summary(
                    severity=severity,
                    flag_type=worst_flag_type,
                    worst_text=worst_text,
                    n_flags=int(item["n_flags"]),
                )
                details_text = details_map.get(participant_id, str(item["reason_text"]))
                row_items = [
                    QTableWidgetItem(participant_id),
                    QTableWidgetItem(flag_types_display),
                    QTableWidgetItem(str(item["n_flags"])),
                    QTableWidgetItem(worst_text),
                    QTableWidgetItem(str(item["worst_condition"])),
                    QTableWidgetItem(str(item["worst_roi"])),
                    QTableWidgetItem(summary_text),
                ]
                row_items[1].setToolTip(flag_types_display)
                if worst_tooltip:
                    row_items[3].setToolTip(worst_tooltip)
                if details_text:
                    row_items[6].setToolTip(details_text)
                for col, cell in enumerate(row_items):
                    table.setItem(row, col, cell)

                display_rows.append(
                    {
                        "Participant": participant_id,
                        "Flag types": flag_types_display,
                        "Flag count": int(item["n_flags"]),
                        "Worst value": worst_text,
                        "Condition": str(item["worst_condition"]),
                        "ROI": str(item["worst_roi"]),
                        "Explanation": summary_text,
                    }
                )

            layout.addWidget(table)

            details_panel = QTextEdit()
            details_panel.setReadOnly(True)
            details_panel.setPlaceholderText("Select a participant to view full details.")
            details_panel.setMinimumHeight(140)
            layout.addWidget(details_panel)

            def _update_details() -> None:
                """Handle the update details step for the Stats PySide6 workflow."""
                current = table.currentRow()
                if current < 0:
                    details_panel.clear()
                    details_panel.setPlaceholderText("Select a participant to view full details.")
                    return
                pid_item = table.item(current, 0)
                if pid_item is None:
                    return
                pid = str(pid_item.text())
                details_panel.setPlainText(details_map.get(pid, ""))

            table.itemSelectionChanged.connect(_update_details)
        else:
            layout.addWidget(QLabel("No participants were flagged."))

        button_row = QHBoxLayout()
        copy_summary_btn = QPushButton("Copy summary")
        copy_btn = QPushButton("Copy table")
        copy_details_btn = QPushButton("Copy details")
        edit_manual_btn = QPushButton("Edit manual exclusions")
        close_btn = QPushButton("Close")
        button_row.addStretch(1)
        button_row.addWidget(copy_summary_btn)
        button_row.addWidget(copy_btn)
        button_row.addWidget(copy_details_btn)
        button_row.addWidget(edit_manual_btn)
        button_row.addWidget(close_btn)
        layout.addLayout(button_row)

        def _copy_summary() -> None:
            """Handle the copy summary step for the Stats PySide6 workflow."""
            if summary_text:
                QGuiApplication.clipboard().setText(summary_text)

        def _copy_table() -> None:
            """Handle the copy table step for the Stats PySide6 workflow."""
            if not display_rows:
                return
            display_df = pd.DataFrame(
                display_rows,
                columns=[
                    "Participant",
                    "Flag types",
                    "Flag count",
                    "Worst value",
                    "Condition",
                    "ROI",
                    "Explanation",
                ],
            )
            QGuiApplication.clipboard().setText(display_df.to_csv(sep="\t", index=False))

        def _copy_details() -> None:
            """Handle the copy details step for the Stats PySide6 workflow."""
            if not details_map or table is None:
                return
            current = table.currentRow()
            if current < 0:
                return
            pid_item = table.item(current, 0)
            if pid_item is None:
                return
            pid = str(pid_item.text())
            details_text = details_map.get(pid, "")
            if details_text:
                QGuiApplication.clipboard().setText(details_text)

        copy_summary_btn.clicked.connect(_copy_summary)
        copy_btn.clicked.connect(_copy_table)
        copy_details_btn.clicked.connect(_copy_details)
        copy_btn.setEnabled(bool(display_rows))
        copy_details_btn.setEnabled(bool(display_rows))
        edit_manual_btn.clicked.connect(self._open_manual_exclusion_dialog)
        close_btn.clicked.connect(dialog.accept)

        return dialog

    def _export_single_pipeline(self) -> bool:
        """Handle the export single pipeline step for the Stats PySide6 workflow."""
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

            dv_variant_paths = self._export_dv_variants(PipelineId.SINGLE, out_dir)
            if dv_variant_paths:
                paths.extend(dv_variant_paths)

            exclusion_paths = self._export_outlier_exclusions(PipelineId.SINGLE, out_dir)
            if exclusion_paths:
                paths.extend(exclusion_paths)

            if paths:
                self.append_log(section, "  • Results exported to:")
                for p in paths:
                    self.append_log(section, f"      {p}")
                self._write_dv_metadata(out_dir, PipelineId.SINGLE)

            return True

        except Exception as exc:  # noqa: BLE001
            self.append_log(section, f"  • Export failed: {exc}", level="error")
            return False

    def _export_dv_variants(self, pipeline_id: PipelineId, out_dir: str) -> list[Path]:
        """Handle the export dv variants step for the Stats PySide6 workflow."""
        selected = self._pipeline_dv_variants.get(pipeline_id, [])
        if not selected:
            return []

        payload = self._pipeline_dv_variant_payloads.get(pipeline_id, {})
        if not payload:
            section = self._section_label(pipeline_id)
            self.append_log(
                section,
                "  • Skipping DV variants export (no variant payload).",
                level="warning",
            )
            return []

        primary_df = payload.get("primary_df")
        variant_dfs = payload.get("variant_dfs", {}) or {}
        summary_df = payload.get("summary_df")
        errors = payload.get("errors", []) or []
        primary_name = payload.get(
            "primary_name", self._pipeline_dv_policy.get(pipeline_id, {}).get("name", "")
        )

        if not isinstance(primary_df, pd.DataFrame):
            section = self._section_label(pipeline_id)
            self.append_log(
                section,
                "  • DV variants export skipped (primary DV table missing).",
                level="error",
            )
            return []

        save_path = Path(out_dir) / "DV Variants.xlsx"
        export_dv_variants_workbook(
            save_path=save_path,
            primary_name=str(primary_name),
            primary_df=primary_df,
            variant_dfs=variant_dfs,
            summary_df=summary_df if isinstance(summary_df, pd.DataFrame) else pd.DataFrame(),
            errors=errors if isinstance(errors, list) else [],
            log_func=self._set_status,
        )
        return [save_path]

    def _export_outlier_exclusions(self, pipeline_id: PipelineId, out_dir: str) -> list[Path]:
        """Handle the export outlier exclusions step for the Stats PySide6 workflow."""
        report = self._pipeline_run_reports.get(pipeline_id)
        if not isinstance(report, StatsRunReport):
            return []
        paths: list[Path] = []
        flagged_path = Path(out_dir) / "Flagged Participants.xlsx"
        export_flagged_participants_report(
            flagged_path, report.qc_report, report.dv_report, self._set_status
        )
        paths.append(flagged_path)

        excluded_path = Path(out_dir) / "Excluded Participants.xlsx"
        export_excluded_participants_report(
            excluded_path,
            manual_excluded=report.manual_excluded_pids,
            required_exclusions=report.required_exclusions,
            log_func=self._set_status,
        )
        paths.append(excluded_path)
        return paths

    def _export_between_pipeline(self) -> bool:
        """Handle the export between pipeline step for the Stats PySide6 workflow."""
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

            dv_variant_paths = self._export_dv_variants(PipelineId.BETWEEN, out_dir)
            if dv_variant_paths:
                paths.extend(dv_variant_paths)

            exclusion_paths = self._export_outlier_exclusions(PipelineId.BETWEEN, out_dir)
            if exclusion_paths:
                paths.extend(exclusion_paths)

            missing_export = self._export_between_missingness(out_dir)
            if missing_export is not None:
                paths.append(missing_export)

            qc_context_export = self._export_qc_context_by_group(out_dir)
            if qc_context_export is not None:
                paths.append(qc_context_export)

            if paths:
                self.append_log(section, "  • Results exported to:")
                for p in paths:
                    self.append_log(section, f"      {p}")
                self._write_dv_metadata(out_dir, PipelineId.BETWEEN)

            return True

        except Exception as exc:  # noqa: BLE001
            self.append_log(section, f"  • Export failed: {exc}", level="error")
            return False

    def _export_between_missingness(self, out_dir: str) -> Path | None:
        """Handle the export between missingness step for the Stats PySide6 workflow."""
        payload = self._between_missingness_payload if isinstance(self._between_missingness_payload, dict) else {}
        mixed_rows = payload.get("mixed_model_missing_cells", [])
        anova_rows = payload.get("anova_excluded_subjects", [])
        summary = payload.get("summary", {})
        summary_rows = [
            {"Metric": "N groups", "Value": summary.get("n_groups", 0)},
            {"Metric": "N subjects mixed model", "Value": summary.get("n_mixed_subjects", 0)},
            {"Metric": "N complete-case ANOVA", "Value": summary.get("n_anova_complete_case", 0)},
            {"Metric": "N ANOVA excluded", "Value": len(anova_rows)},
            {"Metric": "N mixed-model missing cells", "Value": len(mixed_rows)},
            {"Metric": "N discovered", "Value": summary.get("n_discovered_subjects", 0)},
            {"Metric": "N assigned", "Value": summary.get("n_assigned_subjects", 0)},
        ]
        save_path = Path(out_dir) / "Missingness and Exclusions.xlsx"
        export_path = export_missingness_workbook(
            save_path=save_path,
            mixed_missing_rows=mixed_rows if isinstance(mixed_rows, list) else [],
            anova_excluded_rows=anova_rows if isinstance(anova_rows, list) else [],
            summary_rows=summary_rows,
            log_func=self._set_status,
        )
        self._between_missingness_payload["export_path"] = str(export_path)
        return export_path

    def _export_qc_context_by_group(self, out_dir: str) -> Path | None:
        """Handle the export qc context by group step for the Stats PySide6 workflow."""
        fixed_payload = self._fixed_harmonic_dv_payload if isinstance(self._fixed_harmonic_dv_payload, dict) else {}
        dv_table = fixed_payload.get("dv_table")
        if not isinstance(dv_table, pd.DataFrame) or dv_table.empty:
            return None

        run_report = self._pipeline_run_reports.get(PipelineId.BETWEEN)
        flagged_map: dict[str, list[str]] = {}
        if isinstance(run_report, StatsRunReport):
            flagged_map = collect_flagged_pid_map(run_report.qc_report, run_report.dv_report)

        save_path = Path(out_dir) / "QC_Context_ByGroup.xlsx"
        export_path = export_qc_context_workbook(
            save_path=save_path,
            dv_table=dv_table,
            subject_to_group=self.subject_groups,
            missing_harmonics_rows=fixed_payload.get("missing_harmonics", []),
            flagged_pid_map=flagged_map,
            log_func=self._set_status,
        )
        fixed_payload["qc_context_export_path"] = str(export_path)
        return export_path

    # --------- worker signal handlers ---------

    @Slot(int)
    def _on_worker_progress(self, val: int) -> None:
        """Handle the on worker progress step for the Stats PySide6 workflow."""
        self._progress_updates.append(val)

    @Slot(str)
    def _on_worker_message(self, msg: str) -> None:
        """Handle the on worker message step for the Stats PySide6 workflow."""
        self._set_detected_info(msg)

    @Slot(str)
    def _on_worker_error(self, msg: str) -> None:
        """Handle the on worker error step for the Stats PySide6 workflow."""
        self.output_text.appendPlainText(f"Error: {msg}")
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

    def _store_dv_metadata(self, pipeline_id: PipelineId, payload: dict) -> None:
        """Handle the store dv metadata step for the Stats PySide6 workflow."""
        dv_meta = payload.get("dv_metadata")
        if isinstance(dv_meta, dict) and dv_meta:
            self._pipeline_dv_metadata[pipeline_id] = dv_meta
        self._store_dv_variants(pipeline_id, payload)

    def _store_dv_variants(self, pipeline_id: PipelineId, payload: dict) -> None:
        """Handle the store dv variants step for the Stats PySide6 workflow."""
        dv_variants = payload.get("dv_variants")
        if not isinstance(dv_variants, dict) or not dv_variants:
            return
        self._pipeline_dv_variant_payloads[pipeline_id] = dv_variants
        selected = dv_variants.get("selected_variants")
        if isinstance(selected, list):
            self._pipeline_dv_variants[pipeline_id] = list(selected)
        errors = dv_variants.get("errors", [])
        if errors:
            section = self._section_label(pipeline_id)
            for err in errors:
                variant_name = err.get("variant", "Unknown")
                message = err.get("error", "Unknown error")
                self.append_log(
                    section,
                    f"DV variant {variant_name} failed: {message}",
                    level="warning",
                )

    def _store_run_report(self, pipeline_id: PipelineId, payload: dict) -> None:
        """Handle the store run report step for the Stats PySide6 workflow."""
        report = payload.get("run_report")
        if isinstance(report, StatsRunReport):
            self._pipeline_run_reports[pipeline_id] = report

    def store_run_report(self, pipeline_id: PipelineId, report: StatsRunReport) -> None:
        """Handle the store run report step for the Stats PySide6 workflow."""
        if isinstance(report, StatsRunReport):
            self._pipeline_run_reports[pipeline_id] = report

    def _refresh_between_missingness_summary(self) -> None:
        """Handle the refresh between missingness summary step for the Stats PySide6 workflow."""
        payload = self._between_missingness_payload
        if not isinstance(payload, dict):
            return
        mixed_subjects = 0
        if isinstance(self.between_mixed_model_results_data, pd.DataFrame) and not self.between_mixed_model_results_data.empty:
            subjects = payload.get("mixed_model_subjects")
            if isinstance(subjects, list):
                mixed_subjects = len(subjects)
        anova_subjects = payload.get("anova_complete_case_subjects", [])
        if not isinstance(anova_subjects, list):
            anova_subjects = []
        scan = self._multigroup_scan_result
        payload["summary"] = {
            "n_groups": len(self._known_group_labels()),
            "n_mixed_subjects": mixed_subjects or len(set(payload.get("mixed_model_subjects", []))),
            "n_anova_complete_case": len(anova_subjects),
            "n_discovered_subjects": len(scan.discovered_subjects) if scan else 0,
            "n_assigned_subjects": len(scan.assigned_subjects) if scan else 0,
        }

    def _apply_rm_anova_results(self, payload: dict, *, update_text: bool = True) -> str:
        """Handle the apply rm anova results step for the Stats PySide6 workflow."""
        self.rm_anova_results_data = payload.get("anova_df_results")
        self._store_dv_metadata(PipelineId.SINGLE, payload)
        self._store_run_report(PipelineId.SINGLE, payload)
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
            self.summary_text.append(output_text)
        self._update_export_buttons()
        return output_text

    def _apply_between_anova_results(self, payload: dict, *, update_text: bool = True) -> str:
        """Handle the apply between anova results step for the Stats PySide6 workflow."""
        self.between_anova_results_data = payload.get("anova_df_results")
        self._store_dv_metadata(PipelineId.BETWEEN, payload)
        self._store_run_report(PipelineId.BETWEEN, payload)
        missingness = payload.get("missingness", {}) if isinstance(payload, dict) else {}
        if isinstance(missingness, dict):
            self._between_missingness_payload.update(missingness)
        alpha = getattr(self, "_current_alpha", 0.05)

        output_text = build_between_anova_output(self.between_anova_results_data, alpha)
        self._refresh_between_missingness_summary()
        if update_text:
            self.summary_text.append(output_text)
        self._update_export_buttons()
        return output_text

    def _apply_mixed_model_results(self, payload: dict, *, update_text: bool = True) -> str:
        """Handle the apply mixed model results step for the Stats PySide6 workflow."""
        self.mixed_model_results_data = payload.get("mixed_results_df")
        self._store_dv_metadata(PipelineId.SINGLE, payload)
        self._store_run_report(PipelineId.SINGLE, payload)
        output_text = payload.get("output_text", "")
        if update_text:
            self.summary_text.append(output_text)
        self._update_export_buttons()
        return output_text

    def _apply_between_mixed_results(self, payload: dict, *, update_text: bool = True) -> str:
        """Handle the apply between mixed results step for the Stats PySide6 workflow."""
        if not isinstance(payload, dict):
            raise ValueError("Mixed-model payload must be a dict.")
        if "mixed_results_df" not in payload:
            raise ValueError("Mixed-model payload missing 'mixed_results_df'.")

        self.between_mixed_model_results_data = payload.get("mixed_results_df")
        self._store_dv_metadata(PipelineId.BETWEEN, payload)
        self._store_run_report(PipelineId.BETWEEN, payload)
        missingness = payload.get("missingness", {}) if isinstance(payload, dict) else {}
        if isinstance(missingness, dict):
            self._between_missingness_payload.update(missingness)
        output_text = payload.get("output_text", "")
        self._refresh_between_missingness_summary()
        if update_text:
            self.summary_text.append(output_text)
        self._update_export_buttons()
        return output_text

    def _apply_posthoc_results(self, payload: dict, *, update_text: bool = True) -> str:
        """Handle the apply posthoc results step for the Stats PySide6 workflow."""
        self.posthoc_results_data = payload.get("results_df")
        self._store_dv_metadata(PipelineId.SINGLE, payload)
        self._store_run_report(PipelineId.SINGLE, payload)
        output_text = payload.get("output_text", "")
        if update_text:
            self.summary_text.append(output_text)
        self._update_export_buttons()
        return output_text

    def _apply_group_contrasts_results(self, payload: dict, *, update_text: bool = True) -> str:
        """Handle the apply group contrasts results step for the Stats PySide6 workflow."""
        self.group_contrasts_results_data = payload.get("results_df")
        self._store_dv_metadata(PipelineId.BETWEEN, payload)
        self._store_run_report(PipelineId.BETWEEN, payload)
        output_text = payload.get("output_text", "")
        if update_text:
            self.summary_text.append(output_text)
        self._update_export_buttons()
        return output_text

    def _apply_harmonic_results(
        self, payload: dict, *, pipeline_id: PipelineId, update_text: bool = True
    ) -> str:
        """Handle the apply harmonic results step for the Stats PySide6 workflow."""
        output_text = payload.get("output_text") or ""
        findings = payload.get("findings") or []
        if update_text:
            self.summary_text.append("Harmonic details were exported to Harmonic Results.xlsx.")
        self._harmonic_results[pipeline_id] = findings
        self.harmonic_check_results_data = findings
        self._update_export_buttons()
        return output_text

    @Slot(dict)
    def _on_rm_anova_finished(self, payload: dict) -> None:
        """Handle the on rm anova finished step for the Stats PySide6 workflow."""
        self._apply_rm_anova_results(payload)
        self._end_run()

    @Slot(dict)
    def _on_between_anova_finished(self, payload: dict) -> None:
        """Handle the on between anova finished step for the Stats PySide6 workflow."""
        self._apply_between_anova_results(payload)
        self._end_run()

    @Slot(dict)
    def _on_mixed_model_finished(self, payload: dict) -> None:
        """Handle the on mixed model finished step for the Stats PySide6 workflow."""
        self._apply_mixed_model_results(payload)
        self._end_run()

    @Slot(dict)
    def _on_between_mixed_finished(self, payload: dict) -> None:
        """Handle the on between mixed finished step for the Stats PySide6 workflow."""
        self._apply_between_mixed_results(payload)
        self._end_run()

    @Slot(dict)
    def _on_posthoc_finished(self, payload: dict) -> None:
        """Handle the on posthoc finished step for the Stats PySide6 workflow."""
        self._apply_posthoc_results(payload)
        self._end_run()

    @Slot(dict)
    def _on_group_contrasts_finished(self, payload: dict) -> None:
        """Handle the on group contrasts finished step for the Stats PySide6 workflow."""
        self._apply_group_contrasts_results(payload)
        self._end_run()

    @Slot(dict)
    def _on_harmonic_finished(self, payload: dict) -> None:
        """Handle the on harmonic finished step for the Stats PySide6 workflow."""
        pipeline_id = self._active_pipeline or PipelineId.SINGLE
        self._apply_harmonic_results(payload, pipeline_id=pipeline_id)
        self._end_run()

    @Slot(object)
    def _on_lela_mode_finished(self, stats_folder: Path | None = None) -> None:
        """Handle the on lela mode finished step for the Stats PySide6 workflow."""
        try:
            section = self._section_label(PipelineId.BETWEEN)
            self.append_log(section, "[Between] Lela Mode: complete — see Cross-Phase LMM Analysis.xlsx")
            if stats_folder:
                self.append_log(section, f"  • Excel: {stats_folder}")
        finally:
            self._end_run()

    @Slot(str)
    def _on_lela_mode_error(self, message: str) -> None:
        """Handle the on lela mode error step for the Stats PySide6 workflow."""
        try:
            section = self._section_label(PipelineId.BETWEEN)
            self.append_log(section, f"[Between] Lela Mode error: {message}", level="error")
        finally:
            self._end_run()

    # --------------------------- UI building ---------------------------

    def _init_ui(self) -> None:
        """Handle the init ui step for the Stats PySide6 workflow."""
        central = QWidget(self)
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        # included conditions panel
        self.conditions_group = QGroupBox("Included Conditions")
        self.conditions_group.setSizePolicy(QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding))
        self.conditions_group.setToolTip(
            "Choose which conditions to include in the analysis."
        )
        conditions_layout = QVBoxLayout(self.conditions_group)
        conditions_layout.setContentsMargins(8, 8, 8, 8)
        conditions_layout.setSpacing(6)

        conditions_button_row = QHBoxLayout()
        self.conditions_select_all_btn = QPushButton("Select All")
        self.conditions_select_all_btn.setToolTip("Include every condition in the analysis.")
        self.conditions_select_all_btn.clicked.connect(self._select_all_conditions)
        conditions_button_row.addWidget(self.conditions_select_all_btn)
        self.conditions_select_none_btn = QPushButton("Select None")
        self.conditions_select_none_btn.setToolTip("Deselect all conditions.")
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

        # summed BCA definition panel
        self.dv_group = QGroupBox("Summed BCA definition")
        self.dv_group.setSizePolicy(QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding))
        self.dv_group.setToolTip(
            "Select how the primary Summed BCA DV is computed."
        )
        dv_layout = QVBoxLayout(self.dv_group)
        dv_layout.setContentsMargins(8, 8, 8, 8)
        dv_layout.setSpacing(6)

        dv_method_row = QHBoxLayout()
        dv_method_row.addWidget(QLabel("Method:"))
        self.dv_policy_combo = QComboBox()
        self.dv_policy_combo.setToolTip(
            "Choose the primary DV definition used for all statistical results."
        )
        self.dv_policy_combo.addItems(
            [
                LEGACY_POLICY_NAME,
                FIXED_K_POLICY_NAME,
                ROSSION_POLICY_NAME,
            ]
        )
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
        self.fixed_k_spinbox.setToolTip(
            "Number of harmonics to include when using the Fixed-K method."
        )
        self.fixed_k_spinbox.valueChanged.connect(self._on_fixed_k_changed)
        fixed_form.addRow("K:", self.fixed_k_spinbox)

        self.fixed_k_exclude_h1 = QCheckBox("Exclude harmonic 1")
        self.fixed_k_exclude_h1.setChecked(self._dv_exclude_harmonic1)
        self.fixed_k_exclude_h1.setToolTip(
            "Skip the first harmonic when building the Fixed-K DV."
        )
        self.fixed_k_exclude_h1.stateChanged.connect(self._on_fixed_k_exclude_h1_changed)
        fixed_form.addRow("", self.fixed_k_exclude_h1)

        self.fixed_k_exclude_base = QCheckBox("Exclude base-rate harmonics")
        self.fixed_k_exclude_base.setChecked(self._dv_exclude_base_harmonics)
        self.fixed_k_exclude_base.setToolTip(
            "Exclude base-rate harmonics from the Fixed-K DV."
        )
        self.fixed_k_exclude_base.stateChanged.connect(self._on_fixed_k_exclude_base_changed)
        fixed_form.addRow("", self.fixed_k_exclude_base)

        self.fixed_k_base_freq_value = QLabel(f"{self._current_base_freq:g} Hz")
        self.fixed_k_base_freq_value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.fixed_k_base_freq_value.setToolTip(
            "Base frequency from Settings used to identify harmonics."
        )
        fixed_form.addRow("Base frequency:", self.fixed_k_base_freq_value)

        dv_layout.addLayout(fixed_form)
        self._set_fixed_k_controls_enabled(self._dv_policy_name == FIXED_K_POLICY_NAME)

        self.group_mean_controls = QWidget()
        group_mean_layout = QVBoxLayout(self.group_mean_controls)
        group_mean_layout.setContentsMargins(0, 0, 0, 0)
        group_mean_layout.setSpacing(6)

        group_mean_form = QFormLayout()
        group_mean_form.setLabelAlignment(Qt.AlignLeft)
        group_mean_form.setFormAlignment(Qt.AlignLeft)
        group_mean_form.setHorizontalSpacing(10)
        group_mean_form.setVerticalSpacing(6)

        self.group_mean_z_threshold = QDoubleSpinBox()
        self.group_mean_z_threshold.setRange(-10.0, 10.0)
        self.group_mean_z_threshold.setDecimals(2)
        self.group_mean_z_threshold.setSingleStep(0.05)
        self.group_mean_z_threshold.setValue(self._dv_group_mean_z_threshold)
        self.group_mean_z_threshold.valueChanged.connect(
            self._on_group_mean_z_threshold_changed
        )
        self.group_mean_z_threshold.setToolTip(
            "Minimum group-mean Z value for a harmonic to count as significant."
        )
        group_mean_form.addRow("Z threshold:", self.group_mean_z_threshold)

        self.group_mean_empty_policy_combo = QComboBox()
        self.group_mean_empty_policy_combo.addItems(
            [
                EMPTY_LIST_FALLBACK_FIXED_K,
                EMPTY_LIST_SET_ZERO,
                EMPTY_LIST_ERROR,
            ]
        )
        self.group_mean_empty_policy_combo.setCurrentText(self._dv_empty_list_policy)
        self.group_mean_empty_policy_combo.currentTextChanged.connect(
            self._on_empty_list_policy_changed
        )
        self.group_mean_empty_policy_combo.setToolTip(
            "What to do if no significant harmonics are found for an ROI."
        )
        group_mean_form.addRow("Empty list policy:", self.group_mean_empty_policy_combo)

        union_label = QLabel(
            "Selected conditions are used to estimate group-mean Z values for each ROI and harmonic."
        )
        union_label.setWordWrap(True)
        group_mean_form.addRow("", union_label)

        group_mean_layout.addLayout(group_mean_form)

        self.group_mean_preview_btn = QPushButton("Preview harmonic sets")
        self.group_mean_preview_btn.setToolTip(
            "Preview the harmonics that will be used by the Rossion method."
        )
        self.group_mean_preview_btn.clicked.connect(self._on_preview_group_mean_z_clicked)
        group_mean_layout.addWidget(self.group_mean_preview_btn)

        self.group_mean_preview_table = QTableWidget(0, 6)
        self.group_mean_preview_table.setHorizontalHeaderLabels(
            ["ROI", "Harmonics (Hz)", "Count", "Fallback", "Stop reason", "Stop fail harmonics"]
        )
        self.group_mean_preview_table.verticalHeader().setVisible(False)
        self.group_mean_preview_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.group_mean_preview_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.group_mean_preview_table.setSizePolicy(
            QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        )
        self.group_mean_preview_table.setMinimumHeight(120)
        group_mean_layout.addWidget(self.group_mean_preview_table)

        dv_layout.addWidget(self.group_mean_controls)
        self._set_group_mean_controls_visible(
            self._dv_policy_name == ROSSION_POLICY_NAME
        )

        self.dv_variants_group = QGroupBox("Optional comparison exports (do not change results)")
        self.dv_variants_group.setSizePolicy(QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred))
        dv_variants_layout = QVBoxLayout(self.dv_variants_group)
        dv_variants_layout.setContentsMargins(8, 8, 8, 8)
        dv_variants_layout.setSpacing(4)
        dv_variants_note = QLabel(
            "These exports are for consistency checks. Statistical results use the Primary DV only."
        )
        dv_variants_note.setWordWrap(True)
        self.dv_variants_group.setToolTip(
            "Optional exports that compare alternative DV definitions. "
            "They do not change any statistical results."
        )
        dv_variants_layout.addWidget(dv_variants_note)

        dv_variant_labels = {
            FIXED_K_POLICY_NAME: "Export a comparison version using a fixed number of harmonics",
        }
        for policy_name in [FIXED_K_POLICY_NAME]:
            checkbox = QCheckBox(dv_variant_labels[policy_name])
            checkbox.setToolTip(
                "Uses K=5 harmonics when no significant harmonics are found; exports only."
            )
            checkbox.setChecked(False)
            checkbox.stateChanged.connect(self._on_dv_variant_toggled)
            dv_variants_layout.addWidget(checkbox)
            self._dv_variant_checkboxes[policy_name] = checkbox
        self._sync_selected_dv_variants()

        self.outlier_group = QGroupBox("Outlier Flagging")
        self.outlier_group.setSizePolicy(QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred))
        self.outlier_group.setToolTip(
            "Flag participants whose DV values are outside the allowed range."
        )
        outlier_layout = QVBoxLayout(self.outlier_group)
        outlier_layout.setContentsMargins(8, 8, 8, 8)
        outlier_layout.setSpacing(6)

        self.outlier_enable_checkbox = QCheckBox("Enable DV flagging (always on)")
        self.outlier_enable_checkbox.setChecked(True)
        self.outlier_enable_checkbox.setToolTip(
            "Hard DV limit checks are always run to flag potential outliers."
        )
        self.outlier_enable_checkbox.stateChanged.connect(self._on_outlier_exclusion_toggled)
        self.outlier_enable_checkbox.setEnabled(False)
        outlier_layout.addWidget(self.outlier_enable_checkbox)

        outlier_form = QFormLayout()
        outlier_form.setLabelAlignment(Qt.AlignLeft)
        outlier_form.setFormAlignment(Qt.AlignLeft)
        outlier_form.setHorizontalSpacing(10)
        outlier_form.setVerticalSpacing(6)

        self.outlier_abs_limit_spin = QDoubleSpinBox()
        self.outlier_abs_limit_spin.setRange(0.0, 1_000_000.0)
        self.outlier_abs_limit_spin.setDecimals(2)
        self.outlier_abs_limit_spin.setSingleStep(1.0)
        self.outlier_abs_limit_spin.setValue(self._outlier_abs_limit)
        self.outlier_abs_limit_spin.setToolTip(
            "Participants are flagged if any DV exceeds this absolute cutoff."
        )
        self.outlier_abs_limit_spin.valueChanged.connect(self._on_outlier_abs_limit_changed)
        self.outlier_abs_limit_spin.setEnabled(True)
        outlier_form.addRow("Hard DV limit (abs):", self.outlier_abs_limit_spin)

        outlier_layout.addLayout(outlier_form)

        outlier_note = QLabel(
            "Flag participants if abs(DV) exceeds the limit; non-finite DV requires exclusion."
        )
        outlier_note.setWordWrap(True)
        outlier_note.setToolTip(
            "Applies to the Primary DV only; manual exclusions control modeling."
        )
        outlier_layout.addWidget(outlier_note)

        self.manual_exclusion_group = QGroupBox("Manual Exclusions")
        self.manual_exclusion_group.setSizePolicy(
            QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        )
        manual_layout = QHBoxLayout(self.manual_exclusion_group)
        manual_layout.setContentsMargins(8, 8, 8, 8)
        manual_layout.setSpacing(8)

        self.manual_exclusion_summary_label = QLabel("Excluded: 0")
        manual_layout.addWidget(self.manual_exclusion_summary_label)

        self.manual_exclusion_list = ElidedPathLabel("None")
        self.manual_exclusion_list.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.manual_exclusion_list.setMinimumHeight(22)
        self.manual_exclusion_list.setToolTip("None")
        manual_layout.addWidget(self.manual_exclusion_list, 1)

        manual_layout.addStretch(1)
        self.manual_exclusion_edit_btn = QPushButton("Edit…")
        self.manual_exclusion_clear_btn = QPushButton("Clear")
        manual_layout.addWidget(self.manual_exclusion_edit_btn)
        manual_layout.addWidget(self.manual_exclusion_clear_btn)

        self.manual_exclusion_edit_btn.clicked.connect(self._open_manual_exclusion_dialog)
        self.manual_exclusion_clear_btn.clicked.connect(self._clear_manual_exclusions)

        analysis_box = QGroupBox("Analysis Controls")
        analysis_box.setSizePolicy(QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred))
        analysis_layout = QHBoxLayout(analysis_box)
        analysis_layout.setContentsMargins(8, 8, 8, 8)
        analysis_layout.setSpacing(8)

        # single group section
        single_group_box = QGroupBox("Single Group Analysis")
        single_group_box.setSizePolicy(QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed))
        single_layout = QVBoxLayout(single_group_box)

        single_action_row = QHBoxLayout()
        self.analyze_single_btn = QPushButton("Analyze Single Group")
        self.analyze_single_btn.setToolTip(
            "Run the full single-group analysis pipeline using the selected settings."
        )
        self.analyze_single_btn.clicked.connect(self.on_analyze_single_group_clicked)
        single_action_row.addWidget(self.analyze_single_btn)

        self.single_advanced_btn = QPushButton("Advanced…")
        self.single_advanced_btn.setToolTip(
            "Run or export individual single-group steps."
        )
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
        self.analyze_between_btn.setToolTip(
            "Run the full between-group analysis pipeline."
        )
        self.analyze_between_btn.clicked.connect(self.on_analyze_between_groups_clicked)
        between_action_row.addWidget(self.analyze_between_btn)

        self.between_advanced_btn = QPushButton("Advanced…")
        self.between_advanced_btn.setToolTip(
            "Run or export individual between-group steps."
        )
        self.between_advanced_btn.clicked.connect(self.on_between_advanced_clicked)
        between_action_row.addWidget(self.between_advanced_btn)
        between_layout.addLayout(between_action_row)

        self.lela_mode_btn = QPushButton("Lela Mode (Cross-Phase LMM)")
        self.lela_mode_btn.setToolTip(
            "Run the cross-phase mixed model for between-group analyses."
        )
        self.lela_mode_btn.clicked.connect(self.on_run_lela_mode)
        between_layout.addWidget(self.lela_mode_btn)

        self.between_status_lbl = QLabel("Idle")
        self.between_status_lbl.setWordWrap(True)
        between_layout.addWidget(self.between_status_lbl)

        analysis_layout.addWidget(single_group_box)
        analysis_layout.addWidget(between_box)

        middle_scroll_area = QScrollArea()
        middle_scroll_area.setWidgetResizable(True)
        middle_scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        middle_scroll_area.setSizePolicy(QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding))
        middle_contents = QWidget()
        middle_layout = QVBoxLayout(middle_contents)
        middle_layout.setContentsMargins(0, 0, 0, 0)
        middle_layout.setSpacing(8)
        middle_layout.addWidget(self.dv_group)
        middle_layout.addWidget(self.dv_variants_group)
        middle_layout.addWidget(self.outlier_group)
        middle_layout.addWidget(self.manual_exclusion_group)
        middle_layout.addStretch(1)
        middle_scroll_area.setWidget(middle_contents)

        right_top_widget = QWidget()
        right_layout = QVBoxLayout(right_top_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        data_actions_widget = QWidget()
        data_actions_layout = QVBoxLayout(data_actions_widget)
        data_actions_layout.setContentsMargins(0, 0, 0, 0)
        data_actions_layout.setSpacing(6)

        folder_row = QHBoxLayout()
        folder_row.setSpacing(6)
        self.le_folder = ElidedPathLabel()
        self.le_folder.setToolTip(
            "Selected folder that contains the FPVS result spreadsheets."
        )
        self.le_folder.setMinimumHeight(24)
        btn_browse = QPushButton("Browse…")
        btn_browse.setToolTip("Choose the folder that contains FPVS results.")
        btn_browse.clicked.connect(self.on_browse_folder)
        self.btn_copy_folder = QPushButton("Copy")
        self.btn_copy_folder.setToolTip("Copy the data folder path.")
        self.btn_copy_folder.setEnabled(False)
        self.btn_copy_folder.clicked.connect(self._copy_data_folder_path)
        folder_row.addWidget(QLabel("Data Folder:"))
        folder_row.addWidget(self.le_folder, 1)
        folder_row.addWidget(btn_browse)
        folder_row.addWidget(self.btn_copy_folder)
        self.btn_open_results = QPushButton("Open Results Folder")
        self.btn_open_results.clicked.connect(self._open_results_folder)
        self.btn_open_results.setToolTip(
            "Open the folder where stats outputs are saved."
        )
        fm = QFontMetrics(self.btn_open_results.font())
        self.btn_open_results.setMinimumWidth(fm.horizontalAdvance(self.btn_open_results.text()) + 24)
        folder_row.addWidget(self.btn_open_results)
        self.info_button = QPushButton("Analysis Info")
        self.info_button.clicked.connect(self.on_show_analysis_info)
        self.info_button.setToolTip(
            "Show a short description of each analysis step."
        )
        folder_row.addWidget(self.info_button)
        folder_row.addStretch(1)
        data_actions_layout.addLayout(folder_row)

        multigroup_box = QGroupBox("Multi-Group Scan Summary")
        multigroup_box.setSizePolicy(QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum))
        multigroup_layout = QVBoxLayout(multigroup_box)
        multigroup_layout.setContentsMargins(8, 8, 8, 8)
        multigroup_layout.setSpacing(4)

        multigroup_status_row = QHBoxLayout()
        multigroup_status_row.addWidget(QLabel("Status:"))
        self.multi_group_ready_value = QLabel("Not ready")
        self.multi_group_ready_value.setStyleSheet("color: #b02a37;")
        multigroup_status_row.addWidget(self.multi_group_ready_value)
        multigroup_status_row.addStretch(1)
        multigroup_layout.addLayout(multigroup_status_row)

        multigroup_counts = QFormLayout()
        multigroup_counts.setLabelAlignment(Qt.AlignLeft)
        multigroup_counts.setFormAlignment(Qt.AlignLeft)
        multigroup_counts.setHorizontalSpacing(10)
        multigroup_counts.setVerticalSpacing(3)
        self.multi_group_discovered_value = QLabel("0")
        self.multi_group_assigned_value = QLabel("0")
        self.multi_group_groups_value = QLabel("0")
        self.multi_group_unassigned_value = QLabel("0")
        multigroup_counts.addRow("Discovered subjects:", self.multi_group_discovered_value)
        multigroup_counts.addRow("Assigned subjects:", self.multi_group_assigned_value)
        multigroup_counts.addRow("Groups with subjects:", self.multi_group_groups_value)
        multigroup_counts.addRow("Unassigned subjects:", self.multi_group_unassigned_value)
        multigroup_layout.addLayout(multigroup_counts)

        shared_action_row = QHBoxLayout()
        self.compute_shared_harmonics_btn = QPushButton("Compute Shared Harmonics")
        self.compute_shared_harmonics_btn.setToolTip(
            "Compute shared harmonic sets pooled across groups and intersected across selected conditions."
        )
        self.compute_shared_harmonics_btn.setEnabled(False)
        self.compute_shared_harmonics_btn.clicked.connect(self._on_compute_shared_harmonics_clicked)
        shared_action_row.addWidget(self.compute_shared_harmonics_btn)

        self.compute_fixed_harmonic_dv_btn = QPushButton("Compute Fixed-harmonic DV")
        self.compute_fixed_harmonic_dv_btn.setToolTip(
            "Compute Summed BCA DV values using the cached shared-harmonics-by-ROI mapping."
        )
        self.compute_fixed_harmonic_dv_btn.setEnabled(False)
        self.compute_fixed_harmonic_dv_btn.clicked.connect(self._on_compute_fixed_harmonic_dv_clicked)
        shared_action_row.addWidget(self.compute_fixed_harmonic_dv_btn)
        shared_action_row.addStretch(1)
        multigroup_layout.addLayout(shared_action_row)

        fixed_status_row = QHBoxLayout()
        fixed_status_row.addWidget(QLabel("Fixed-harmonic DV:"))
        self.fixed_harmonic_dv_summary_value = QLabel("Waiting for shared harmonics.")
        self.fixed_harmonic_dv_summary_value.setWordWrap(True)
        fixed_status_row.addWidget(self.fixed_harmonic_dv_summary_value, 1)
        multigroup_layout.addLayout(fixed_status_row)

        issues_header = QHBoxLayout()
        issues_header.addWidget(QLabel("Issues:"))
        issues_header.addStretch(1)
        self.multi_group_issue_toggle_btn = QPushButton("Show details")
        self.multi_group_issue_toggle_btn.setEnabled(False)
        self.multi_group_issue_toggle_btn.clicked.connect(self._toggle_multigroup_issue_details)
        issues_header.addWidget(self.multi_group_issue_toggle_btn)
        multigroup_layout.addLayout(issues_header)

        self.multi_group_issue_text = QPlainTextEdit()
        self.multi_group_issue_text.setReadOnly(True)
        self.multi_group_issue_text.setPlaceholderText("Issues will appear here after scan.")
        self.multi_group_issue_text.setMinimumHeight(70)
        self.multi_group_issue_text.setMaximumHeight(120)
        self.multi_group_issue_text.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.multi_group_issue_text.setSizePolicy(QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred))
        multigroup_layout.addWidget(self.multi_group_issue_text)

        right_layout.addWidget(multigroup_box)
        right_layout.addWidget(analysis_box)

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
        right_layout.addLayout(status_row)

        export_row = QHBoxLayout()
        export_row.setSpacing(6)
        export_row.addWidget(QLabel("Last Export:"))
        self.export_path_label = ElidedPathLabel()
        self.export_path_label.setMinimumHeight(22)
        export_row.addWidget(self.export_path_label, 1)
        self.export_open_btn = QPushButton("Open")
        self.export_open_btn.setToolTip("Open the most recent export file or folder.")
        self.export_open_btn.setEnabled(False)
        self.export_open_btn.clicked.connect(self._open_export_path)
        self.export_copy_btn = QPushButton("Copy")
        self.export_copy_btn.setToolTip("Copy the most recent export path.")
        self.export_copy_btn.setEnabled(False)
        self.export_copy_btn.clicked.connect(self._copy_export_path)
        export_row.addWidget(self.export_open_btn)
        export_row.addWidget(self.export_copy_btn)
        right_layout.addLayout(export_row)

        self.reporting_summary_export_checkbox = QCheckBox("Reporting Summary (.txt)")
        self.reporting_summary_export_checkbox.setChecked(True)
        self.reporting_summary_export_checkbox.setToolTip(
            "When checked, write a plain-text Reporting Summary at end-of-run."
        )
        right_layout.addWidget(self.reporting_summary_export_checkbox)

        self.lbl_rois = QLabel("")
        self.lbl_rois.setWordWrap(True)
        self.lbl_rois.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.lbl_rois.setToolTip(
            "ROIs loaded from Settings. Update ROI definitions in Settings to change this list."
        )
        right_layout.addWidget(self.lbl_rois)
        right_layout.addStretch(1)

        # output pane
        self.summary_text = QTextEdit()
        self.summary_text.setReadOnly(True)
        self.summary_text.setAcceptRichText(True)
        self.summary_text.setPlaceholderText("Summary output")
        self.summary_text.setMinimumHeight(140)
        self.summary_text.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setPlaceholderText("Log output")
        self.log_text.setMinimumHeight(140)
        self.log_text.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.output_tabs = QTabWidget()
        self.output_tabs.addTab(self.summary_text, "Summary")
        self.output_tabs.addTab(self.log_text, "Log")

        reporting_tab = QWidget()
        reporting_layout = QVBoxLayout(reporting_tab)
        reporting_layout.setContentsMargins(0, 0, 0, 0)
        reporting_layout.setSpacing(6)
        self.reporting_summary_text = QPlainTextEdit()
        self.reporting_summary_text.setReadOnly(True)
        self.reporting_summary_text.setPlaceholderText("Reporting Summary output")
        mono = self.reporting_summary_text.font()
        mono.setFamilies(["Consolas", "Menlo", "Courier New", "monospace"])
        self.reporting_summary_text.setFont(mono)
        reporting_layout.addWidget(self.reporting_summary_text)
        reporting_btn_row = QHBoxLayout()
        reporting_btn_row.addStretch(1)
        self.reporting_summary_copy_btn = QPushButton("Copy to Clipboard")
        self.reporting_summary_copy_btn.clicked.connect(self._copy_reporting_summary_text)
        self.reporting_summary_save_btn = QPushButton("Save .txt…")
        self.reporting_summary_save_btn.clicked.connect(self._save_reporting_summary_text)
        reporting_btn_row.addWidget(self.reporting_summary_copy_btn)
        reporting_btn_row.addWidget(self.reporting_summary_save_btn)
        reporting_layout.addLayout(reporting_btn_row)
        self.output_tabs.addTab(reporting_tab, "Reporting Summary")

        self.copy_summary_btn = QPushButton("Copy summary")
        self.copy_summary_btn.clicked.connect(self._copy_summary_text)
        self.copy_log_btn = QPushButton("Copy log")
        self.copy_log_btn.clicked.connect(self._copy_log_text)
        output_header = QHBoxLayout()
        output_header.addStretch(1)
        output_header.addWidget(self.copy_summary_btn)
        output_header.addWidget(self.copy_log_btn)

        output_container = QWidget()
        output_layout = QVBoxLayout(output_container)
        output_layout.setContentsMargins(0, 0, 0, 0)
        output_layout.setSpacing(6)
        output_layout.addLayout(output_header)
        output_layout.addWidget(self.output_tabs)

        self.output_text = self.log_text

        column_one = QWidget()
        column_one_layout = QVBoxLayout(column_one)
        column_one_layout.setContentsMargins(0, 0, 0, 0)
        column_one_layout.setSpacing(0)
        column_one_layout.addWidget(self.conditions_group)

        column_two = QWidget()
        column_two_layout = QVBoxLayout(column_two)
        column_two_layout.setContentsMargins(0, 0, 0, 0)
        column_two_layout.setSpacing(0)
        column_two_layout.addWidget(middle_scroll_area)

        column_three = QWidget()
        column_three_layout = QVBoxLayout(column_three)
        column_three_layout.setContentsMargins(0, 0, 0, 0)
        column_three_layout.setSpacing(0)
        column_three_layout.addWidget(right_top_widget)

        top_splitter = QSplitter(Qt.Horizontal)
        top_splitter.setObjectName("stats_top_splitter")
        top_splitter.setChildrenCollapsible(False)
        top_splitter.addWidget(column_one)
        top_splitter.addWidget(column_two)
        top_splitter.addWidget(column_three)
        top_splitter.setStretchFactor(0, 1)
        top_splitter.setStretchFactor(1, 2)
        top_splitter.setStretchFactor(2, 2)
        top_splitter.setSizes([280, 560, 560])

        root_splitter = QSplitter(Qt.Vertical)
        root_splitter.setObjectName("stats_root_splitter")
        root_splitter.setChildrenCollapsible(False)
        root_splitter.addWidget(top_splitter)
        root_splitter.addWidget(output_container)
        root_splitter.setStretchFactor(0, 5)
        root_splitter.setStretchFactor(1, 2)
        root_splitter.setSizes([620, 200])

        main_layout.addWidget(data_actions_widget)
        main_layout.addWidget(root_splitter, 1)

        # initialize export buttons
        self._update_export_buttons()
        self._populate_conditions_panel([])

    # --------------------------- actions ---------------------------

    def on_analyze_single_group_clicked(self) -> None:
        """Handle the on analyze single group clicked step for the Stats PySide6 workflow."""
        self._controller.run_single_group_analysis()

    def on_analyze_between_groups_clicked(self) -> None:
        """Handle the on analyze between groups clicked step for the Stats PySide6 workflow."""
        self._controller.run_between_group_analysis()

    def _open_advanced_dialog(self, title: str, actions: list[tuple[str, Callable[[], None], bool]]) -> None:
        """Handle the open advanced dialog step for the Stats PySide6 workflow."""
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        layout = QVBoxLayout(dialog)
        for text, cb, enabled in actions:
            btn = QPushButton(text)
            btn.setEnabled(enabled)
            if text.lower().startswith("export"):
                btn.setToolTip("Export the results for this step to Excel.")
            btn.clicked.connect(cb)
            layout.addWidget(btn)
        layout.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    def on_single_advanced_clicked(self) -> None:
        """Handle the on single advanced clicked step for the Stats PySide6 workflow."""
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
        """Handle the on between advanced clicked step for the Stats PySide6 workflow."""
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
            (
                "Export QC Context (By Group)",
                self.on_export_qc_context_by_group,
                isinstance(self._fixed_harmonic_dv_payload.get("dv_table"), pd.DataFrame)
                and not self._fixed_harmonic_dv_payload.get("dv_table").empty,
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
        """Handle the on run rm anova step for the Stats PySide6 workflow."""
        self._clear_output_views()
        self.rm_anova_results_data = None
        self._update_export_buttons()
        self._controller.run_single_group_rm_anova_only()

    def on_run_mixed_model(self) -> None:
        """Handle the on run mixed model step for the Stats PySide6 workflow."""
        self._clear_output_views()
        self.mixed_model_results_data = None
        self._update_export_buttons()
        self._controller.run_single_group_mixed_model_only()

    def on_run_between_anova(self) -> None:
        """Handle the on run between anova step for the Stats PySide6 workflow."""
        self._clear_output_views()
        self.between_anova_results_data = None
        self._update_export_buttons()
        self._controller.run_between_group_anova_only()

    def on_run_between_mixed_model(self) -> None:
        """Handle the on run between mixed model step for the Stats PySide6 workflow."""
        self._clear_output_views()
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
        """Handle the on run group contrasts step for the Stats PySide6 workflow."""
        self._clear_output_views()
        self.group_contrasts_results_data = None
        self._update_export_buttons()
        self._controller.run_between_group_contrasts_only()

    def on_run_interaction_posthocs(self) -> None:
        """Handle the on run interaction posthocs step for the Stats PySide6 workflow."""
        self._clear_output_views()
        self.posthoc_results_data = None
        our = self._update_export_buttons  # keep line short
        our()
        self._controller.run_single_group_posthoc_only()

    # ---- exports ----

    def on_export_rm_anova(self) -> None:
        """Handle the on export rm anova step for the Stats PySide6 workflow."""
        if not isinstance(self.rm_anova_results_data, pd.DataFrame) or self.rm_anova_results_data.empty:
            QMessageBox.information(self, "No Results", "Run RM-ANOVA first.")
            return
        out_dir = self._ensure_results_dir()
        try:
            self.export_results("anova", self.rm_anova_results_data, out_dir)
            self._set_status(f"RM-ANOVA exported to: {out_dir}")
            self._set_last_export_path(out_dir)
        except Exception as e:
            import traceback
            logger.exception("RM-ANOVA export failed.")
            tb = traceback.format_exc()
            QMessageBox.critical(self, "Export Failed", f"{type(e).__name__}: {e}\n\n{tb}")

    def on_export_mixed_model(self) -> None:
        """Handle the on export mixed model step for the Stats PySide6 workflow."""
        if not isinstance(self.mixed_model_results_data, pd.DataFrame) or self.mixed_model_results_data.empty:
            QMessageBox.information(self, "No Results", "Run Mixed Model first.")
            return
        out_dir = self._ensure_results_dir()
        try:
            self.export_results("lmm", self.mixed_model_results_data, out_dir)
            self._set_status(f"Mixed Model results exported to: {out_dir}")
            self._set_last_export_path(out_dir)
        except Exception as e:
            import traceback
            logger.exception("Mixed Model export failed.")
            tb = traceback.format_exc()
            QMessageBox.critical(self, "Export Failed", f"{type(e).__name__}: {e}\n\n{tb}")

    def on_export_between_anova(self) -> None:
        """Handle the on export between anova step for the Stats PySide6 workflow."""
        if not isinstance(self.between_anova_results_data, pd.DataFrame) or self.between_anova_results_data.empty:
            QMessageBox.information(self, "No Results", "Run Between-Group ANOVA first.")
            return
        out_dir = self._ensure_results_dir()
        try:
            self.export_results("anova_between", self.between_anova_results_data, out_dir)
            self._set_status(f"Between-group ANOVA exported to: {out_dir}")
            self._set_last_export_path(out_dir)
        except Exception as e:
            import traceback
            logger.exception("Between-group ANOVA export failed.")
            tb = traceback.format_exc()
            QMessageBox.critical(self, "Export Failed", f"{type(e).__name__}: {e}\n\n{tb}")

    def on_export_between_mixed(self) -> None:
        """Handle the on export between mixed step for the Stats PySide6 workflow."""
        if not isinstance(self.between_mixed_model_results_data,
                          pd.DataFrame) or self.between_mixed_model_results_data.empty:
            QMessageBox.information(self, "No Results", "Run Between-Group Mixed Model first.")
            return
        out_dir = self._ensure_results_dir()
        try:
            self.export_results("lmm_between", self.between_mixed_model_results_data, out_dir)
            self._set_status(f"Between-group Mixed Model exported to: {out_dir}")
            self._set_last_export_path(out_dir)
        except Exception as e:
            import traceback
            logger.exception("Between-group Mixed Model export failed.")
            tb = traceback.format_exc()
            QMessageBox.critical(self, "Export Failed", f"{type(e).__name__}: {e}\n\n{tb}")

    def on_export_posthoc(self) -> None:
        """Handle the on export posthoc step for the Stats PySide6 workflow."""
        if not isinstance(self.posthoc_results_data, pd.DataFrame) or self.posthoc_results_data.empty:
            QMessageBox.information(self, "No Results", "Run Interaction Post-hocs first.")
            return
        out_dir = self._ensure_results_dir()
        try:
            self.export_results("posthoc", self.posthoc_results_data, out_dir)
            self._set_status(f"Post-hoc results exported to: {out_dir}")
            self._set_last_export_path(out_dir)
        except Exception as e:
            import traceback
            logger.exception("Post-hoc export failed.")
            tb = traceback.format_exc()
            QMessageBox.critical(self, "Export Failed", f"{type(e).__name__}: {e}\n\n{tb}")

    def on_export_group_contrasts(self) -> None:
        """Handle the on export group contrasts step for the Stats PySide6 workflow."""
        if not isinstance(self.group_contrasts_results_data, pd.DataFrame) or self.group_contrasts_results_data.empty:
            QMessageBox.information(self, "No Results", "Run Group Contrasts first.")
            return
        out_dir = self._ensure_results_dir()
        try:
            self.export_results("group_contrasts", self.group_contrasts_results_data, out_dir)
            self._set_status(f"Group contrasts exported to: {out_dir}")
            self._set_last_export_path(out_dir)
        except Exception as e:
            import traceback
            logger.exception("Group contrasts export failed.")
            tb = traceback.format_exc()
            QMessageBox.critical(self, "Export Failed", f"{type(e).__name__}: {e}\n\n{tb}")

    def on_export_qc_context_by_group(self) -> None:
        """Handle the on export qc context by group step for the Stats PySide6 workflow."""
        fixed_payload = self._fixed_harmonic_dv_payload if isinstance(self._fixed_harmonic_dv_payload, dict) else {}
        dv_table = fixed_payload.get("dv_table")
        if not isinstance(dv_table, pd.DataFrame) or dv_table.empty:
            QMessageBox.information(self, "No Results", "Compute Fixed-harmonic DV first.")
            return

        out_dir = self._ensure_results_dir()
        try:
            export_path = self._export_qc_context_by_group(out_dir)
            if export_path is None:
                QMessageBox.information(self, "No Results", "No fixed-harmonic DV rows available for QC export.")
                return
            self._set_status(f"QC/context workbook exported to: {export_path}")
            self._set_last_export_path(export_path)
        except Exception as e:
            import traceback

            logger.exception("QC/context export failed.")
            tb = traceback.format_exc()
            QMessageBox.critical(self, "Export Failed", f"{type(e).__name__}: {e}\n\n{tb}")

    # ---- folder & scan ----

    def on_browse_folder(self) -> None:
        """Handle the on browse folder step for the Stats PySide6 workflow."""
        start_dir = self.le_folder.text() or self.project_dir
        folder = QFileDialog.getExistingDirectory(self, "Select Data Folder", start_dir)
        if folder:
            self._set_data_folder_path(folder)
            self._scan_button_clicked()

    def _scan_button_clicked(self) -> None:
        """Handle the scan button clicked step for the Stats PySide6 workflow."""
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
                self._reconcile_manual_exclusions(self.subjects)
                self._set_status(
                    f"Scan complete: Found {len(scan_result.subjects)} subjects and {len(scan_result.conditions)} conditions."
                )
                self._start_multigroup_scan(Path(folder))
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
        self._start_multigroup_scan(target)
        if target.exists() and target.is_dir():
            self._set_data_folder_path(str(target))
            self._scan_button_clicked()
        else:
            # Leave UI as-is; user will browse. Status hint only.
            self._set_status(
                f"Select the project's '{EXCEL_SUBFOLDER_NAME}' folder to begin."
            )
