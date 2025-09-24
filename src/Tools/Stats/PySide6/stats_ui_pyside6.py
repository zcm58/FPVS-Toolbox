# src/Tools/Stats/PySide6/stats_ui_pyside6.py

from __future__ import annotations


import json
import logging
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Iterable

import numpy as np
import pandas as pd
from PySide6.QtCore import Qt, QTimer, QThreadPool, Slot, QUrl
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
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
from Main_App.PySide6_App.utils.op_guard import OpGuard
from Main_App.PySide6_App.widgets.busy_spinner import BusySpinner
from Tools.Stats.Legacy.interpretation_helpers import generate_lme_summary
from Tools.Stats.Legacy.mixed_effects_model import run_mixed_effects_model
from Tools.Stats.Legacy.posthoc_tests import run_interaction_posthocs
from Tools.Stats.Legacy.stats_analysis import (
    ALL_ROIS_OPTION,
    _match_freq_column,
    get_included_freqs,
    prepare_all_subject_summed_bca_data,
    run_rm_anova as analysis_run_rm_anova,
    run_harmonic_check as run_harmonic_check_new,
    set_rois,
)
from Tools.Stats.Legacy.stats_export import (
    export_mixed_model_results_to_excel,
    export_posthoc_results_to_excel,
    export_rm_anova_results_to_excel,
    export_significance_results_to_excel as export_harmonic_results_to_excel,
)
from Tools.Stats.Legacy.stats_helpers import load_rois_from_settings, apply_rois_to_modules
from Tools.Stats.PySide6.stats_file_scanner_pyside6 import ScanError, scan_folder_simple
from Tools.Stats.PySide6.stats_worker import StatsWorker


logger = logging.getLogger(__name__)
_unused_qaction = QAction  # keep import alive for Qt resource checkers


# --------------------------- helpers ---------------------------

def _auto_detect_project_dir() -> str:
    """Walk upward to find a folder containing project.json."""
    path = Path.cwd()
    while not (path / "project.json").is_file():
        if path.parent == path:
            return str(Path.cwd())
        path = path.parent
    return str(path)


def _first_present(d: dict, keys: Iterable[str], default=None):
    for k in keys:
        if k in d:
            return d[k]
    return default


# --------------------------- worker functions ---------------------------

def _rm_anova_calc(progress_cb, message_cb, *, subjects, conditions, subject_data, base_freq, rois):
    set_rois(rois)
    message_cb("Preparing data for Summed BCA RM-ANOVA…")
    all_subject_bca_data = prepare_all_subject_summed_bca_data(
        subjects=subjects,
        conditions=conditions,
        subject_data=subject_data,
        base_freq=base_freq,
        log_func=message_cb,
    )
    if not all_subject_bca_data:
        raise RuntimeError("Data preparation failed (empty).")
    message_cb("Running RM-ANOVA…")
    _, anova_df_results = analysis_run_rm_anova(all_subject_bca_data, message_cb)
    return {"anova_df_results": anova_df_results}


def _lmm_calc(progress_cb, message_cb, *, subjects, conditions, subject_data, base_freq, alpha, rois):
    set_rois(rois)
    message_cb("Preparing data for Mixed Effects Model…")
    all_subject_bca_data = prepare_all_subject_summed_bca_data(
        subjects=subjects,
        conditions=conditions,
        subject_data=subject_data,
        base_freq=base_freq,
        log_func=message_cb,
    )
    if not all_subject_bca_data:
        raise RuntimeError("Data preparation failed (empty).")

    long_format_data = []
    for pid, cond_data in all_subject_bca_data.items():
        for cond_name, roi_data in cond_data.items():
            for roi_name, value in roi_data.items():
                if not pd.isna(value):
                    long_format_data.append(
                        {"subject": pid, "condition": cond_name, "roi": roi_name, "value": value}
                    )
    if not long_format_data:
        raise RuntimeError("No valid rows for mixed model after filtering NaNs.")

    df_long = pd.DataFrame(long_format_data)
    message_cb("Running Mixed Effects Model…")

    mixed_results_df = run_mixed_effects_model(
        data=df_long, dv_col="value", group_col="subject", fixed_effects=["condition * roi"]
    )

    output_text = "============================================================\n"
    output_text += "       Linear Mixed-Effects Model Results\n"
    output_text += "       Analysis conducted on: Summed BCA Data\n"
    output_text += "============================================================\n\n"
    output_text += (
        "This model accounts for repeated observations from each subject by including\n"
        "a random intercept. Fixed effects assess how conditions and ROIs influence\n"
        "Summed BCA values, including their interaction.\n\n"
    )
    if mixed_results_df is not None and not mixed_results_df.empty:
        output_text += "--------------------------------------------\n"
        output_text += "                 FIXED EFFECTS TABLE\n"
        output_text += "--------------------------------------------\n"
        output_text += mixed_results_df.to_string(index=False) + "\n"
        output_text += generate_lme_summary(mixed_results_df, alpha=alpha)
    else:
        output_text += "Mixed effects model returned no rows.\n"

    return {"mixed_results_df": mixed_results_df, "output_text": output_text}


def _posthoc_calc(progress_cb, message_cb, *, subjects, conditions, subject_data, base_freq, alpha, rois):
    set_rois(rois)
    message_cb("Preparing data for Interaction Post-hoc tests…")
    all_subject_bca_data = prepare_all_subject_summed_bca_data(
        subjects=subjects,
        conditions=conditions,
        subject_data=subject_data,
        base_freq=base_freq,
        log_func=message_cb,
    )
    if not all_subject_bca_data:
        raise RuntimeError("Data preparation failed (empty).")

    long_format_data = []
    for pid, cond_data in all_subject_bca_data.items():
        for cond_name, roi_data in cond_data.items():
            for roi_name, value in roi_data.items():
                if not pd.isna(value):
                    long_format_data.append(
                        {"subject": pid, "condition": cond_name, "roi": roi_name, "value": value}
                    )
    if not long_format_data:
        raise RuntimeError("No valid rows for post-hoc tests after filtering NaNs.")

    df_long = pd.DataFrame(long_format_data)
    message_cb("Running post-hoc tests…")
    output_text, results_df = run_interaction_posthocs(
        data=df_long,
        dv_col="value",
        roi_col="roi",
        condition_col="condition",
        subject_col="subject",
        alpha=alpha,
    )
    return {"results_df": results_df, "output_text": output_text}



def _harmonic_calc(
    progress_cb,
    message_cb,
    *,
    subject_data,
    subjects,
    conditions,
    selected_metric,
    mean_value_threshold,
    base_freq,
    alpha,
    rois,
):
    set_rois(rois)
    tail = "greater" if selected_metric in ("Z Score", "SNR") else "two-sided"
    message_cb("Running harmonic check…")
    output_text, findings = run_harmonic_check_new(
        subject_data=subject_data,
        subjects=subjects,
        conditions=conditions,
        selected_metric=selected_metric,
        mean_value_threshold=mean_value_threshold,
        base_freq=base_freq,
        log_func=message_cb,
        max_freq=None,
        correction_method="holm",
        tail=tail,
        min_subjects=3,
        do_wilcoxon_sensitivity=True,
    )
    return {"output_text": output_text, "findings": findings}


# --------------------------- main window ---------------------------

class StatsWindow(QMainWindow):
    """PySide6 window wrapping the legacy FPVS Statistical Analysis Tool."""

    def __init__(self, parent=None, project_dir: str | None = None):
        if project_dir and os.path.isdir(project_dir):
            self.project_dir = project_dir
        else:
            proj = getattr(parent, "currentProject", None)
            self.project_dir = (
                str(proj.project_root) if proj and hasattr(proj, "project_root") else _auto_detect_project_dir()
            )

        config_path = os.path.join(self.project_dir, "project.json")
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            self.project_title = cfg.get("name", cfg.get("title", os.path.basename(self.project_dir)))
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

        # --- state ---
        self.subject_data: dict = {}
        self.subjects: list[str] = []
        self.conditions: list[str] = []
        self.rm_anova_results_data: pd.DataFrame | None = None
        self.mixed_model_results_data: pd.DataFrame | None = None
        self.posthoc_results_data: pd.DataFrame | None = None
        self.harmonic_check_results_data: list[dict] = []
        self.rois: dict[str, list[str]] = {}
        self._harmonic_metric: str = ""

        # --- legacy UI proxies ---
        self.stats_data_folder_var = SimpleNamespace(get=lambda: self.le_folder.text() if hasattr(self, "le_folder") else "",
                                                     set=lambda v: self.le_folder.setText(v) if hasattr(self, "le_folder") else None)
        self.detected_info_var = SimpleNamespace(set=self._set_detected_info)
        self.roi_var = SimpleNamespace(get=lambda: ALL_ROIS_OPTION, set=lambda v: None)
        self.alpha_var = SimpleNamespace(get=lambda: "0.05", set=lambda v: None)

        # UI
        self._init_ui()
        self.results_textbox = self.results_text

        self.refresh_rois()
        QTimer.singleShot(100, self._load_default_data_folder)

        self._progress_updates: list[int] = []

    # --------- ROI + focus helpers ---------

    def _safe_export_call(self, func, data_obj, out_dir: str, base_name: str) -> None:
        """
        Call legacy export function with best-effort signature:
          1) func(data_obj, save_path=<file>, log_func=<callable>)
          2) func(data_obj, out_dir, log_func=<callable>)  # fallback
        """
        os.makedirs(out_dir, exist_ok=True)
        fname = base_name if base_name.lower().endswith(".xlsx") else f"{base_name}.xlsx"
        save_path = os.path.join(out_dir, fname)
        try:
            func(
                data_obj,
                save_path=save_path,
                log_func=self._set_detected_info,
            )
            return
        except TypeError:
            func(data_obj, out_dir, log_func=self._set_detected_info)

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

    def export_results(self, kind: str, data, out_dir: str) -> None:
        """Unified export adapter. Keeps UI thin, uses legacy exporters."""
        mapping = {
            "anova": (export_rm_anova_results_to_excel, "RM-ANOVA Results.xlsx"),
            "lmm": (export_mixed_model_results_to_excel, "Mixed Model Results.xlsx"),
            "posthoc": (export_posthoc_results_to_excel, "Posthoc Results.xlsx"),
            "harmonic": (export_harmonic_results_to_excel, "Harmonic Results.xlsx"),
        }
        func, fname = mapping[kind]
        if kind == "harmonic":
            grouped = self._group_harmonic(data)

            # Adapter to supply required kwargs while reusing _safe_export_call
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

    def refresh_rois(self):
        fresh = load_rois_from_settings() or {}
        try:
            set_rois({})
        except Exception:
            pass
        apply_rois_to_modules(fresh)
        set_rois(fresh)
        self.rois = fresh
        self._update_roi_label()

    def _update_roi_label(self):
        names = list(self.rois.keys())
        txt = "Using {} ROI{} from Settings: {}".format(
            len(names), "" if len(names) == 1 else "s", ", ".join(names)
        ) if names else "No ROIs defined in Settings."
        self.lbl_rois.setText(txt)

    def _set_detected_info(self, txt: str) -> None:
        lower_txt = txt.lower() if isinstance(txt, str) else str(txt).lower()
        if (" roi" in lower_txt) or lower_txt.startswith("using ") or lower_txt.startswith("rois"):
            if hasattr(self, "lbl_rois"):
                self.lbl_rois.setText(txt)
        else:
            if hasattr(self, "lbl_status"):
                self.lbl_status.setText(txt)

    def _focus_self(self) -> None:
        self._focus_calls += 1
        self.raise_()
        self.activateWindow()

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

    def _set_running(self, running: bool) -> None:
        buttons = [
            self.run_rm_anova_btn,
            self.run_mixed_model_btn,
            self.run_posthoc_btn,
            self.run_harm_btn,
            self.export_rm_anova_btn,
            self.export_mixed_model_btn,
            self.export_posthoc_btn,
            self.export_harm_btn,
            self.btn_scan,
        ]
        for b in buttons:
            b.setEnabled(not running)
        if running:
            self.spinner.show()
            self.spinner.start()
        else:
            self.spinner.stop()
            self.spinner.hide()

    # --------- worker signal handlers ---------

    @Slot(int)
    def _on_worker_progress(self, val: int) -> None:
        self._progress_updates.append(val)

    @Slot(str)
    def _on_worker_message(self, msg: str) -> None:
        self._set_detected_info(msg)

    @Slot(str)
    def _on_worker_error(self, msg: str) -> None:
        self.results_text.append(f"Error: {msg}")
        self._end_run()

    @Slot(dict)
    def _on_rm_anova_finished(self, payload: dict) -> None:
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
            p_cols = ["Pr > F", "p-value", "p_value", "p", "P", "pvalue"]
            eff_cols = ["Effect", "Source", "Factor", "Term"]

            lines = []
            for _, row in anova_df_results.iterrows():
                effect_name = str(_first_present(row, eff_cols, "")).strip()
                effect_lower = effect_name.lower()

                p_val = _first_present(row, p_cols, np.nan)
                try:
                    p_val = float(p_val)
                except Exception:
                    p_val = np.nan

                if any(k in effect_lower for k in ["condition:roi", "condition*roi", "condition x roi", "roi:condition", "roi*condition"]):
                    tag = "condition-by-ROI interaction"
                elif "condition" == effect_lower or effect_lower.startswith("conditions"):
                    tag = "difference between conditions"
                elif effect_lower == "roi" or "region" in effect_lower:
                    tag = "difference between ROIs"
                else:
                    continue

                if np.isfinite(p_val) and p_val < alpha:
                    lines.append(f"  - Significant {tag} (p = {p_val:.4g}).")
                elif np.isfinite(p_val):
                    lines.append(f"  - No significant {tag} (p = {p_val:.4g}).")
                else:
                    lines.append(f"  - {tag.capitalize()}: p-value unavailable.")

            if lines:
                output_text += "\n".join(lines) + "\n"
            else:
                output_text += "No interpretable effects were found in the ANOVA table.\n"

            output_text += "--------------------------------------------\n"
            output_text += "NOTE: For detailed reporting and post-hoc tests, refer to the tables above.\n"
            output_text += "--------------------------------------------\n"
        else:
            output_text += "RM-ANOVA returned no results.\n"

        self.results_text.setText(output_text)
        self._end_run()

    @Slot(dict)
    def _on_mixed_model_finished(self, payload: dict) -> None:
        self.mixed_model_results_data = payload.get("mixed_results_df")
        output_text = payload.get("output_text", "")
        self.results_text.setText(output_text)
        if self.mixed_model_results_data is not None and not self.mixed_model_results_data.empty:
            self.export_mixed_model_btn.setEnabled(True)
        self._end_run()

    @Slot(dict)
    def _on_posthoc_finished(self, payload: dict) -> None:
        self.posthoc_results_data = payload.get("results_df")
        output_text = payload.get("output_text", "")
        self.results_text.setText(output_text)
        if self.posthoc_results_data is not None and not self.posthoc_results_data.empty:
            self.export_posthoc_btn.setEnabled(True)
        self._end_run()

    @Slot(dict)
    def _on_harmonic_finished(self, payload: dict) -> None:
        output_text = payload.get("output_text") or ""
        findings = payload.get("findings") or []
        self.results_text.setText(output_text.strip() or "(Harmonic check returned empty text. See logs for details.)")
        self.harmonic_check_results_data = findings
        if self.harmonic_check_results_data:
            self.export_harm_btn.setEnabled(True)
        self._end_run()

    # --------------------------- UI building ---------------------------

    def _init_ui(self):
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

        # scan button
        self.btn_scan = QPushButton("Scan Folder Contents")
        self.btn_scan.clicked.connect(self._scan_button_clicked)
        main_layout.addWidget(self.btn_scan)

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

        # summed BCA section
        summed_frame = QFrame()
        summed_frame.setFrameShape(QFrame.StyledPanel)
        vs = QVBoxLayout(summed_frame)
        title = QLabel("Summed BCA Analysis:")
        f = title.font()
        f.setBold(True)
        title.setFont(f)
        vs.addWidget(title, alignment=Qt.AlignLeft)

        btn_row = QHBoxLayout()
        run_col, export_col = QVBoxLayout(), QVBoxLayout()

        self.run_rm_anova_btn = QPushButton("Run RM-ANOVA")
        self.run_rm_anova_btn.clicked.connect(self.on_run_rm_anova)
        run_col.addWidget(self.run_rm_anova_btn)

        self.run_mixed_model_btn = QPushButton("Run Mixed Model")
        self.run_mixed_model_btn.clicked.connect(self.on_run_mixed_model)
        run_col.addWidget(self.run_mixed_model_btn)

        self.run_posthoc_btn = QPushButton("Run Interaction Post-hocs")
        self.run_posthoc_btn.clicked.connect(self.on_run_interaction_posthocs)
        run_col.addWidget(self.run_posthoc_btn)

        self.export_rm_anova_btn = QPushButton("Export RM-ANOVA")
        self.export_rm_anova_btn.clicked.connect(self.on_export_rm_anova)
        export_col.addWidget(self.export_rm_anova_btn)

        self.export_mixed_model_btn = QPushButton("Export Mixed Model")
        self.export_mixed_model_btn.clicked.connect(self.on_export_mixed_model)
        export_col.addWidget(self.export_mixed_model_btn)

        self.export_posthoc_btn = QPushButton("Export Post-hoc Results")
        self.export_posthoc_btn.clicked.connect(self.on_export_posthoc)
        export_col.addWidget(self.export_posthoc_btn)

        btn_row.addLayout(run_col, 1)
        btn_row.addSpacing(12)
        btn_row.addLayout(export_col, 1)
        vs.addLayout(btn_row)

        # harmonic controls
        harm_row = QHBoxLayout()
        harm_row.addWidget(QLabel("Metric:"))
        self.cb_metric = QComboBox()
        self.cb_metric.addItems(["Z Score", "SNR", "Amplitude"])
        harm_row.addWidget(self.cb_metric)

        harm_row.addWidget(QLabel("Mean Threshold:"))
        self.le_threshold = QLineEdit("0.0")
        self.le_threshold.setFixedWidth(80)
        harm_row.addWidget(self.le_threshold)

        self.run_harm_btn = QPushButton("Run Harmonic Check")
        self.run_harm_btn.clicked.connect(self.on_run_harmonic_check)
        harm_row.addWidget(self.run_harm_btn)

        self.export_harm_btn = QPushButton("Export Harmonic Results")
        self.export_harm_btn.clicked.connect(self.on_export_harmonic)
        harm_row.addWidget(self.export_harm_btn)
        harm_row.addStretch(1)
        vs.addLayout(harm_row)

        main_layout.addWidget(summed_frame)

        # results pane
        self.results_text = QTextEdit()
        self.results_text.setReadOnly(True)
        main_layout.addWidget(self.results_text, 1)

    # --------------------------- actions ---------------------------

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

    def on_run_rm_anova(self):
        if self._check_for_open_excel_files(self.le_folder.text()):
            return
        if not self.subject_data:
            QMessageBox.warning(self, "No Data", "Please scan a data folder first.")
            return
        self.refresh_rois()
        if not self.rois:
            QMessageBox.warning(self, "No ROIs", "Define at least one ROI in Settings before running stats.")
            return
        try:
            settings = SettingsManager()
            base_freq = float(settings.get("analysis", "base_freq", 6.0))
            alpha = float(settings.get("analysis", "alpha", 0.05))
        except Exception as e:
            QMessageBox.critical(self, "Settings Error", f"Could not load analysis settings: {e}")
            return
        if not self._begin_run():
            return
        self._current_alpha = alpha
        self.results_text.clear()
        self.rm_anova_results_data = None
        self.export_rm_anova_btn.setEnabled(False)

        worker = StatsWorker(
            _rm_anova_calc,
            subjects=self.subjects,
            conditions=self.conditions,
            subject_data=self.subject_data,
            base_freq=base_freq,
            rois=self.rois,
        )
        worker.signals.progress.connect(self._on_worker_progress)
        worker.signals.message.connect(self._on_worker_message)
        worker.signals.error.connect(self._on_worker_error)
        worker.signals.finished.connect(self._on_rm_anova_finished)
        self.pool.start(worker)

    def on_run_mixed_model(self):
        if self._check_for_open_excel_files(self.le_folder.text()):
            return
        if not self.subject_data:
            QMessageBox.warning(self, "No Data", "Please scan a data folder first.")
            return
        self.refresh_rois()
        if not self.rois:
            QMessageBox.warning(self, "No ROIs", "Define at least one ROI in Settings before running stats.")
            return
        try:
            settings = SettingsManager()
            base_freq = float(settings.get("analysis", "base_freq", 6.0))
            alpha = float(settings.get("analysis", "alpha", 0.05))
        except Exception as e:
            QMessageBox.critical(self, "Settings Error", f"Could not load analysis settings: {e}")
            return
        if not self._begin_run():
            return

        self.results_text.clear()
        self.mixed_model_results_data = None
        self.export_mixed_model_btn.setEnabled(False)

        worker = StatsWorker(
            _lmm_calc,
            subjects=self.subjects,
            conditions=self.conditions,
            subject_data=self.subject_data,
            base_freq=base_freq,
            alpha=alpha,
            rois=self.rois,
        )
        worker.signals.progress.connect(self._on_worker_progress)
        worker.signals.message.connect(self._on_worker_message)
        worker.signals.error.connect(self._on_worker_error)
        worker.signals.finished.connect(self._on_mixed_model_finished)
        self.pool.start(worker)

    def on_run_interaction_posthocs(self):
        if self._check_for_open_excel_files(self.le_folder.text()):
            return
        if not self.subject_data:
            QMessageBox.warning(self, "No Data", "Please scan a data folder first.")
            return
        if self.rm_anova_results_data is None:
            QMessageBox.warning(
                self,
                "Run ANOVA First",
                "Please run a successful RM-ANOVA before running post-hoc tests for the interaction.",
            )
            return

        self.refresh_rois()
        if not self.rois:
            QMessageBox.warning(self, "No ROIs", "Define at least one ROI in Settings before running stats.")
            return
        try:
            settings = SettingsManager()
            base_freq = float(settings.get("analysis", "base_freq", 6.0))
            alpha = float(settings.get("analysis", "alpha", 0.05))
        except Exception as e:
            QMessageBox.critical(self, "Settings Error", f"Could not load analysis settings: {e}")
            return
        if not self._begin_run():
            return

        self.results_text.clear()
        self.posthoc_results_data = None
        self.export_posthoc_btn.setEnabled(False)

        worker = StatsWorker(
            _posthoc_calc,
            subjects=self.subjects,
            conditions=self.conditions,
            subject_data=self.subject_data,
            base_freq=base_freq,
            alpha=alpha,
            rois=self.rois,
        )
        worker.signals.progress.connect(self._on_worker_progress)
        worker.signals.message.connect(self._on_worker_message)
        worker.signals.error.connect(self._on_worker_error)
        worker.signals.finished.connect(self._on_posthoc_finished)
        self.pool.start(worker)

    def on_run_harmonic_check(self):
        if self._check_for_open_excel_files(self.le_folder.text()):
            return
        if not (self.subject_data and self.subjects and self.conditions):
            QMessageBox.warning(self, "Data Error", "No subject data found. Please click 'Scan Folder Contents' first.")
            return

        self.refresh_rois()
        if not self.rois:
            QMessageBox.warning(self, "No ROIs", "Define at least one ROI in Settings before running stats.")
            return
        try:
            settings = SettingsManager()
            base_freq = float(settings.get("analysis", "base_freq", 6.0))
            alpha = float(settings.get("analysis", "alpha", 0.05))
            selected_metric = self.cb_metric.currentText()
            mean_value_threshold = float(self.le_threshold.text())
        except ValueError:
            QMessageBox.warning(self, "Input Error", "Invalid Mean Threshold. Please enter a numeric value.")
            return
        except Exception as e:
            QMessageBox.critical(self, "Settings Error", f"Could not load analysis settings: {e}")
            return
        if not self._begin_run():
            return

        self._harmonic_metric = selected_metric  # for legacy exporter

        self.results_text.clear()
        self.harmonic_check_results_data = []
        self.export_harm_btn.setEnabled(False)

        worker = StatsWorker(
            _harmonic_calc,
            subject_data=self.subject_data,
            subjects=self.subjects,
            conditions=self.conditions,
            selected_metric=selected_metric,
            mean_value_threshold=mean_value_threshold,
            base_freq=base_freq,
            alpha=alpha,
            rois=self.rois,
        )
        worker.signals.progress.connect(self._on_worker_progress)
        worker.signals.message.connect(self._on_worker_message)
        worker.signals.error.connect(self._on_worker_error)
        worker.signals.finished.connect(self._on_harmonic_finished)
        self.pool.start(worker)

    # ---- exports ----

    def _ensure_results_dir(self) -> str:
        results_dir = os.path.join(self.project_dir, "3 - Statistical Analysis Results")
        os.makedirs(results_dir, exist_ok=True)
        return results_dir

    def on_export_rm_anova(self):
        if not isinstance(self.rm_anova_results_data, pd.DataFrame) or self.rm_anova_results_data.empty:
            QMessageBox.information(self, "No Results", "Run RM-ANOVA first.")
            return
        out_dir = self._ensure_results_dir()
        try:
            self.export_results("anova", self.rm_anova_results_data, out_dir)
            self.lbl_status.setText(f"RM-ANOVA exported to: {out_dir}")
        except Exception as e:
            QMessageBox.critical(self, "Export Failed", str(e))

    def on_export_mixed_model(self):
        if not isinstance(self.mixed_model_results_data, pd.DataFrame) or self.mixed_model_results_data.empty:
            QMessageBox.information(self, "No Results", "Run Mixed Model first.")
            return
        out_dir = self._ensure_results_dir()
        try:
            self.export_results("lmm", self.mixed_model_results_data, out_dir)
            self.lbl_status.setText(f"Mixed Model results exported to: {out_dir}")
        except Exception as e:
            QMessageBox.critical(self, "Export Failed", str(e))

    def on_export_posthoc(self):
        if not isinstance(self.posthoc_results_data, pd.DataFrame) or self.posthoc_results_data.empty:
            QMessageBox.information(self, "No Results", "Run Interaction Post-hocs first.")
            return
        out_dir = self._ensure_results_dir()
        try:
            self.export_results("posthoc", self.posthoc_results_data, out_dir)
            self.lbl_status.setText(f"Post-hoc results exported to: {out_dir}")
        except Exception as e:
            QMessageBox.critical(self, "Export Failed", str(e))

    def on_export_harmonic(self):
        if not self.harmonic_check_results_data:
            QMessageBox.information(self, "No Results", "Run Harmonic Check first.")
            return
        out_dir = self._ensure_results_dir()
        try:
            self.export_results("harmonic", self.harmonic_check_results_data, out_dir)
            self.lbl_status.setText(f"Harmonic check results exported to: {out_dir}")
        except Exception as e:
            QMessageBox.critical(self, "Export Failed", str(e))

    # ---- folder & scan ----

    def on_browse_folder(self):
        start_dir = self.le_folder.text() or self.project_dir
        folder = QFileDialog.getExistingDirectory(self, "Select Data Folder", start_dir)
        if folder:
            self.le_folder.setText(folder)
            self._scan_button_clicked()

    def _scan_button_clicked(self):
        self.refresh_rois()
        folder = self.le_folder.text()
        if not folder:
            QMessageBox.warning(self, "No Folder", "Please select a data folder first.")
            return
        try:
            subjects, conditions, data = scan_folder_simple(folder)
            self.subjects = subjects
            self.conditions = conditions
            self.subject_data = data
            self.lbl_status.setText(f"Scan complete: Found {len(subjects)} subjects and {len(conditions)} conditions.")
        except ScanError as e:
            self.lbl_status.setText(f"Scan failed: {e}")
            QMessageBox.critical(self, "Scan Error", str(e))

    def _load_default_data_folder(self):
        default = None
        if self.parent() and hasattr(self.parent(), "currentProject"):
            proj = self.parent().currentProject
            if proj:
                root = getattr(proj, "project_root", "")
                sub = proj.subfolders.get("excel", "")
                cand = Path(root) / sub
                if cand.is_dir():
                    default = str(cand)
        if not default:
            cand = Path(_auto_detect_project_dir()) / "1 - Excel Data Files"
            if cand.is_dir():
                default = str(cand)
        if default:
            self.le_folder.setText(default)
            self._scan_button_clicked()
