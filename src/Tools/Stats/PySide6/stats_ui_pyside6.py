# src/Tools/Stats/PySide6/stats_ui_pyside6.py

from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QLabel,
    QLineEdit,
    QPushButton,
    QComboBox,
    QTextEdit,
    QHBoxLayout,
    QVBoxLayout,
    QFrame,
    QFileDialog,
    QMessageBox,
    QApplication,
    QSizePolicy,
)
from PySide6.QtGui import QDesktopServices, QAction
from PySide6.QtCore import Qt, QTimer, QUrl, QThreadPool, Slot

import os
import json
import pandas as pd
import numpy as np
from types import SimpleNamespace
from pathlib import Path
import logging

# Legacy analysis and helpers
from Tools.Stats.PySide6.stats_file_scanner_pyside6 import scan_folder_simple, ScanError
from Tools.Stats.Legacy.stats_analysis import (
    prepare_all_subject_summed_bca_data,
    run_rm_anova as analysis_run_rm_anova,
    get_included_freqs,
    _match_freq_column,
    ALL_ROIS_OPTION,
    run_harmonic_check as run_harmonic_check_new,
    set_rois,
)
from Tools.Stats.Legacy.mixed_effects_model import run_mixed_effects_model
from Tools.Stats.Legacy.interpretation_helpers import generate_lme_summary
from Tools.Stats.Legacy.posthoc_tests import run_interaction_posthocs
from Tools.Stats.Legacy.stats_helpers import load_rois_from_settings, apply_rois_to_modules
from Tools.Stats.Legacy.stats_export import (
    export_rm_anova_results_to_excel,
    export_mixed_model_results_to_excel,
    export_posthoc_results_to_excel,
    export_significance_results_to_excel as export_harmonic_results_to_excel,
)

# Main app widgets/utilities
from Main_App import SettingsManager
from Main_App.PySide6_App.utils.op_guard import OpGuard
from Main_App.PySide6_App.widgets.busy_spinner import BusySpinner
from Tools.Stats.PySide6.stats_worker import StatsWorker

logger = logging.getLogger(__name__)
_unused_qaction = QAction  # keep reference to avoid Qt GC issues


# ---------------------------
# Small helpers / background
# ---------------------------

def _auto_detect_project_dir() -> str:
    """Walk up directories to find project.json and return its folder, or cwd if none found."""
    path = Path.cwd()
    while not (path / "project.json").is_file():
        if path.parent == path:
            return str(Path.cwd())
        path = path.parent
    return str(path)


def _rm_anova_calc(progress_cb, message_cb, *, subjects, conditions, subject_data, base_freq):
    message_cb("Preparing data for Summed BCA RM-ANOVA...")
    all_subject_bca_data = prepare_all_subject_summed_bca_data(
        subjects=subjects,
        conditions=conditions,
        subject_data=subject_data,
        base_freq=base_freq,
        log_func=message_cb,
    )
    if not all_subject_bca_data:
        raise RuntimeError("data_prep_failed")
    progress_cb(50)
    message_cb("Data preparation complete. Running RM-ANOVA...")
    _, anova_df_results = analysis_run_rm_anova(all_subject_bca_data, message_cb)
    progress_cb(100)
    return {"anova_df_results": anova_df_results}


def _lmm_calc(progress_cb, message_cb, *, subjects, conditions, subject_data, base_freq, alpha):
    message_cb("Preparing data for Mixed Effects Model...")
    all_subject_bca_data = prepare_all_subject_summed_bca_data(
        subjects=subjects,
        conditions=conditions,
        subject_data=subject_data,
        base_freq=base_freq,
        log_func=message_cb,
    )
    if not all_subject_bca_data:
        raise RuntimeError("data_prep_failed")

    long_format_data = []
    for pid, cond_data in all_subject_bca_data.items():
        for cond_name, roi_data in cond_data.items():
            for roi_name, value in roi_data.items():
                if not pd.isna(value):
                    long_format_data.append(
                        {"subject": pid, "condition": cond_name, "roi": roi_name, "value": value}
                    )
    if not long_format_data:
        raise RuntimeError("No valid data available for Mixed Model after filtering NaNs.")

    df_long = pd.DataFrame(long_format_data)
    progress_cb(50)
    message_cb("Data preparation complete. Running Mixed Effects Model...")

    output_text = "============================================================\n"
    output_text += "       Linear Mixed-Effects Model Results\n"
    output_text += "       Analysis conducted on: Summed BCA Data\n"
    output_text += "============================================================\n\n"
    output_text += (
        "This model accounts for repeated observations from each subject by including\n"
        "a random intercept. Fixed effects assess how conditions and ROIs influence\n"
        "Summed BCA values, including their interaction.\n\n"
    )

    mixed_results_df = run_mixed_effects_model(
        data=df_long,
        dv_col="value",
        group_col="subject",
        fixed_effects=["condition * roi"],
    )

    if mixed_results_df is not None and not mixed_results_df.empty:
        output_text += "--------------------------------------------\n"
        output_text += "                 FIXED EFFECTS TABLE\n"
        output_text += "--------------------------------------------\n"
        output_text += mixed_results_df.to_string(index=False) + "\n"
        output_text += generate_lme_summary(mixed_results_df, alpha=alpha)
    else:
        output_text += "Mixed effects model did not return any results or the result was empty.\n"

    progress_cb(100)
    message_cb("Mixed model analysis complete.")
    return {"mixed_results_df": mixed_results_df, "output_text": output_text}


def _posthoc_calc(progress_cb, message_cb, *, subjects, conditions, subject_data, base_freq, alpha):
    message_cb("Preparing data for Interaction Post-hoc tests...")
    all_subject_bca_data = prepare_all_subject_summed_bca_data(
        subjects=subjects,
        conditions=conditions,
        subject_data=subject_data,
        base_freq=base_freq,
        log_func=message_cb,
    )
    if not all_subject_bca_data:
        raise RuntimeError("data_prep_failed")

    long_format_data = []
    for pid, cond_data in all_subject_bca_data.items():
        for cond_name, roi_data in cond_data.items():
            for roi_name, value in roi_data.items():
                if not pd.isna(value):
                    long_format_data.append(
                        {"subject": pid, "condition": cond_name, "roi": roi_name, "value": value}
                    )
    if not long_format_data:
        raise RuntimeError("No valid data available for post-hoc tests after filtering NaNs.")

    df_long = pd.DataFrame(long_format_data)
    progress_cb(50)
    message_cb("Data preparation complete. Running post-hoc tests...")

    output_text, results_df = run_interaction_posthocs(
        data=df_long,
        dv_col="value",
        roi_col="roi",
        condition_col="condition",
        subject_col="subject",
        alpha=alpha,
    )

    progress_cb(100)
    message_cb("Post-hoc analysis complete.")
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
    log_func,
):
    # Ensure analysis layer is using the same ROI set as UI
    try:
        set_rois(rois)
    except Exception:
        pass

    tail = "greater" if selected_metric in ("Z Score", "SNR") else "two-sided"
    message_cb("Running harmonic check...")
    output_text, findings = run_harmonic_check_new(
        subject_data=subject_data,
        subjects=subjects,
        conditions=conditions,
        selected_metric=selected_metric,
        mean_value_threshold=mean_value_threshold,
        base_freq=base_freq,
        log_func=log_func,
        max_freq=None,
        correction_method="holm",
        tail=tail,
        min_subjects=3,
        do_wilcoxon_sensitivity=True,
    )
    progress_cb(100)
    message_cb("Harmonic check completed.")
    return {"output_text": output_text, "findings": findings}


# ---------------------------
# Main Window
# ---------------------------

class StatsWindow(QMainWindow):
    """PySide6 window wrapping the legacy FPVS Statistical Analysis Tool."""

    def __init__(self, parent=None, project_dir: str = None):
        # Project root
        if project_dir and os.path.isdir(project_dir):
            self.project_dir = project_dir
        else:
            proj = getattr(parent, "currentProject", None)
            self.project_dir = (
                str(proj.project_root) if proj and hasattr(proj, "project_root") else _auto_detect_project_dir()
            )

        # Title from project.json (if available)
        config_path = os.path.join(self.project_dir, "project.json")
        try:
            with open(config_path, "r") as f:
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

        # --- Legacy/state variables ---
        self.subject_data = {}
        self.subjects = []
        self.conditions = []
        self.rm_anova_results_data = None
        self.mixed_model_results_data = None
        self.posthoc_results_data = None
        self.harmonic_check_results_data = []
        self.rois = {}

        # --- UI proxies (kept for compatibility with legacy code) ---
        self.stats_data_folder_var = SimpleNamespace(get=lambda: self.le_folder.text(),
                                                     set=lambda v: self.le_folder.setText(v))
        self.detected_info_var = SimpleNamespace(set=lambda txt: self.lbl_status.setText(txt))
        self.roi_var = SimpleNamespace(get=lambda: ALL_ROIS_OPTION, set=lambda v: None)
        self.alpha_var = SimpleNamespace(get=lambda: "0.05", set=lambda v: None)
        self.harmonic_metric_var = SimpleNamespace(get=lambda: self.cb_metric.currentText(), set=lambda v: None)
        self.harmonic_threshold_var = SimpleNamespace(get=lambda: self.le_threshold.text(), set=lambda v: None)
        self.posthoc_factor_var = SimpleNamespace(get=lambda: "condition by roi", set=lambda v: None)

        # Build UI
        self._init_ui()
        self.results_textbox = self.results_text

        # Kick a first scan target (if a default excel dir is discoverable)
        QTimer.singleShot(100, self._load_default_data_folder)

        # test hook / progress collector
        self._progress_updates: list[int] = []

    # ------- small logging helpers -------

    def log_to_main_app(self, message):
        """A simple logger for the standalone stats window."""
        logger.info("stats_window: %s", message)

    def refresh_rois(self):
        """Reload ROI definitions from settings and update the wrapped status line."""
        self.rois = load_rois_from_settings()
        apply_rois_to_modules(self.rois)
        self.log_to_main_app("Refreshed ROI definitions from settings.")

        # Wrapped, non-expanding status text + full list in tooltip
        if self.rois:
            roi_names = ", ".join(self.rois.keys())
            prefix = f"Using {len(self.rois)} ROIs from Settings:"
            self.lbl_status.setText(f"{prefix}\n{roi_names}")
            self.lbl_status.setToolTip(f"{prefix} {roi_names}")
        else:
            self.lbl_status.setText("No ROIs loaded from Settings.")
            self.lbl_status.setToolTip("")

    def resizeEvent(self, e):  # keep label wrapping on live resizes
        super().resizeEvent(e)
        tip = self.lbl_status.toolTip()
        if tip.startswith("Using ") and ": " in tip:
            prefix, rest = tip.split(": ", 1)
            self.lbl_status.setText(f"{prefix}:\n{rest}")

    def _focus_self(self) -> None:
        self._focus_calls += 1
        self.raise_()
        self.activateWindow()

    # ------- run-state helpers -------

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

    # ------- worker signal handlers -------

    @Slot(int)
    def _on_worker_progress(self, val: int) -> None:
        self._progress_updates.append(val)  # kept for tests

    @Slot(str)
    def _on_worker_message(self, msg: str) -> None:
        # transient status messages also wrap
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setText(msg)

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
            "the different brain regions (ROIs) you analyzed, and, crucially, whether the\n"
            "effect of the conditions changes depending on the brain region (interaction effect).\n\n"
        )

        anova_df_results = self.rm_anova_results_data
        if anova_df_results is not None and not anova_df_results.empty:
            pes_vals = []
            for _, row in anova_df_results.iterrows():
                f_val = row.get("F Value", np.nan)
                df1 = row.get("Num DF", np.nan)
                df2 = row.get("Den DF", np.nan)
                if not pd.isna(f_val) and not pd.isna(df1) and not pd.isna(df2) and (f_val * df1 + df2) != 0:
                    pes_vals.append((f_val * df1) / ((f_val * df1) + df2))
                else:
                    pes_vals.append(np.nan)

            # Quick readable interpretation per effect
            for _, row in anova_df_results.iterrows():
                effect_name_raw = str(row.get("Effect", ""))
                p_val = row.get("p Value", np.nan)
                is_significant = (not pd.isna(p_val)) and (p_val <= alpha)
                if "condition:roi" in effect_name_raw.lower():
                    explanation = (
                        "  - Interpretation: The effect of condition depends on ROI (interaction present).\n"
                        if is_significant else
                        "  - Interpretation: No reliable condition-by-ROI interaction.\n"
                    )
                elif "condition" == effect_name_raw.lower():
                    explanation = (
                        "  - Interpretation: Conditions differ overall (averaged across ROIs).\n"
                        if is_significant else
                        "  - Interpretation: No overall difference between conditions.\n"
                    )
                elif "roi" == effect_name_raw.lower():
                    explanation = (
                        "  - Interpretation: ROIs differ overall (averaged across conditions).\n"
                        if is_significant else
                        "  - Interpretation: No overall difference between ROIs.\n"
                    )
                else:
                    explanation = ""
                output_text += explanation
            output_text += "--------------------------------------------\n"
            output_text += "NOTE: For detailed reporting and post-hoc tests, refer to the tables above.\n"
            output_text += "--------------------------------------------\n"
        else:
            output_text += "RM-ANOVA did not return any results or the result was empty.\n"

        self.results_text.append(output_text)
        self._end_run()

    @Slot(dict)
    def _on_mixed_model_finished(self, payload: dict) -> None:
        self.mixed_model_results_data = payload.get("mixed_results_df")
        output_text = payload.get("output_text", "")
        self.results_text.setText(output_text)
        if self.mixed_model_results_data is not None and not self.mixed_model_results_data.empty:
            self.export_mixed_model_btn.setEnabled(True)
        self.results_text.append("\nAnalysis complete.")
        self._end_run()

    @Slot(dict)
    def _on_posthoc_finished(self, payload: dict) -> None:
        self.posthoc_results_data = payload.get("results_df")
        output_text = payload.get("output_text", "")
        self.results_text.setText(output_text)
        if self.posthoc_results_data is not None and not self.posthoc_results_data.empty:
            self.export_posthoc_btn.setEnabled(True)
        self.results_text.append("\nAnalysis complete.")
        self._end_run()

    @Slot(dict)
    def _on_harmonic_finished(self, payload: dict) -> None:
        output_text = payload.get("output_text") or ""
        findings = payload.get("findings") or []
        if output_text.strip():
            self.results_text.setText(output_text)
        else:
            self.results_text.setText("(Harmonic check returned empty text. See logs for details.)")
        self.harmonic_check_results_data = findings
        if self.harmonic_check_results_data:
            self.export_harm_btn.setEnabled(True)
        self.results_text.append("\n[debug] Harmonic check completed.")
        self.log_to_main_app("== Harmonic Check END ==")
        self._end_run()

    # ------- UI building -------

    def _init_ui(self):
        central = QWidget(self)
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        # Folder chooser row
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

        # Scan button
        self.btn_scan = QPushButton("Scan Folder Contents")
        self.btn_scan.clicked.connect(self._scan_button_clicked)
        main_layout.addWidget(self.btn_scan)

        # Status line (wrapped, non-expanding)
        self.lbl_status = QLabel("Select a folder containing FPVS results.")
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.lbl_status.setMinimumWidth(0)
        self.lbl_status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        main_layout.addWidget(self.lbl_status)

        # Spinner row (fixed-size spinner + stretch; no progress bar)
        prog_row = QHBoxLayout()
        self.spinner = BusySpinner()
        self.spinner.setFixedSize(18, 18)
        self.spinner.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.spinner.hide()
        prog_row.addWidget(self.spinner)
        prog_row.addStretch(1)
        main_layout.addLayout(prog_row)

        # Summed BCA group
        summed_frame = QFrame()
        summed_frame.setFrameShape(QFrame.StyledPanel)
        vs = QVBoxLayout(summed_frame)
        title = QLabel("Summed BCA Analysis:")
        f = title.font()
        f.setBold(True)
        title.setFont(f)
        vs.addWidget(title, alignment=Qt.AlignLeft)

        btn_layout = QHBoxLayout()
        run_col, export_col = QVBoxLayout(), QVBoxLayout()

        self.run_rm_anova_btn = QPushButton("Run RM-ANOVA")
        run_col.addWidget(self.run_rm_anova_btn)
        self.run_mixed_model_btn = QPushButton("Run Mixed Model")
        run_col.addWidget(self.run_mixed_model_btn)
        self.run_posthoc_btn = QPushButton("Run Interaction Post-hocs")
        run_col.addWidget(self.run_posthoc_btn)

        self.export_rm_anova_btn = QPushButton("Export RM-ANOVA")
        export_col.addWidget(self.export_rm_anova_btn)
        self.export_mixed_model_btn = QPushButton("Export Mixed Model")
        export_col.addWidget(self.export_mixed_model_btn)
        self.export_posthoc_btn = QPushButton("Export Post-hoc Results")
        export_col.addWidget(self.export_posthoc_btn)

        btn_layout.addLayout(run_col, 1)
        btn_layout.addSpacing(16)
        btn_layout.addLayout(export_col, 1)
        vs.addLayout(btn_layout)

        # Metric / threshold / harmonic
        metric_row = QHBoxLayout()
        metric_row.addWidget(QLabel("Metric:"))
        self.cb_metric = QComboBox()
        self.cb_metric.addItems(["Z Score", "SNR", "Amplitude"])
        metric_row.addWidget(self.cb_metric)

        metric_row.addWidget(QLabel("Mean Threshold:"))
        self.le_threshold = QLineEdit("0.0")
        self.le_threshold.setFixedWidth(80)
        metric_row.addWidget(self.le_threshold)

        self.run_harm_btn = QPushButton("Run Harmonic Check")
        metric_row.addWidget(self.run_harm_btn)

        self.export_harm_btn = QPushButton("Export Harmonic Results")
        metric_row.addWidget(self.export_harm_btn)

        metric_row.addStretch(1)
        vs.addLayout(metric_row)

        main_layout.addWidget(summed_frame)

        # Results text
        self.results_text = QTextEdit()
        self.results_text.setReadOnly(True)
        main_layout.addWidget(self.results_text, 1)

        # Button wiring
        self.run_rm_anova_btn.clicked.connect(self.on_run_rm_anova)
        self.run_mixed_model_btn.clicked.connect(self.on_run_mixed_model)
        self.run_posthoc_btn.clicked.connect(self.on_run_interaction_posthocs)
        self.run_harm_btn.clicked.connect(self.on_run_harmonic_check)

        self.export_rm_anova_btn.clicked.connect(self.on_export_rm_anova)
        self.export_mixed_model_btn.clicked.connect(self.on_export_mixed_model)
        self.export_posthoc_btn.clicked.connect(self.on_export_posthoc)
        self.export_harm_btn.clicked.connect(self.on_export_harmonic)

        # Exports start disabled
        self.export_rm_anova_btn.setEnabled(False)
        self.export_mixed_model_btn.setEnabled(False)
        self.export_posthoc_btn.setEnabled(False)
        self.export_harm_btn.setEnabled(False)

    # ------- actions -------

    def _check_for_open_excel_files(self, folder_path: str) -> bool:
        """Warn if .xlsx files in the selected folder appear to be open (Windows lock heuristic)."""
        try:
            open_files = []
            for name in os.listdir(folder_path or ""):
                if name.lower().endswith(".xlsx"):
                    full = os.path.join(folder_path, name)
                    try:
                        # try renaming as a crude "locked?" heuristic
                        test_name = full + ".lockcheck"
                        os.rename(full, test_name)
                        os.rename(test_name, full)
                    except PermissionError:
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
        except Exception:
            # If anything goes wrong, don't block—just continue
            pass
        return False

    def on_run_rm_anova(self):
        if self._check_for_open_excel_files(self.le_folder.text()):
            return
        if not self.subject_data:
            QMessageBox.warning(self, "No Data", "Please scan a data folder first.")
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
        )
        worker.signals.progress.connect(self._on_worker_progress)
        worker.signals.message.connect(self._on_worker_message)
        worker.signals.error.connect(self._on_worker_error)
        worker.signals.finished.connect(self._on_posthoc_finished)
        self.pool.start(worker)

    def on_run_harmonic_check(self):
        if self._check_for_open_excel_files(self.le_folder.text()):
            return

        # Ensure we have data
        if not (self.subject_data and self.subjects and self.conditions):
            QMessageBox.warning(self, "Data Error", "No subject data found. Please click 'Scan Folder Contents' first.")
            return

        # Reload ROI defs (and update the wrapped status line)
        self.refresh_rois()

        # Read settings and inputs
        try:
            settings = SettingsManager()
            base_freq = float(settings.get("analysis", "base_freq", 6.0))
            alpha = float(settings.get("analysis", "alpha", 0.05))
            selected_metric = self.harmonic_metric_var.get()
            mean_value_threshold = float(self.harmonic_threshold_var.get())
        except ValueError:
            QMessageBox.warning(self, "Input Error", "Invalid Mean Threshold. Please enter a numeric value.")
            return
        except Exception as e:
            QMessageBox.critical(self, "Settings Error", f"Could not load analysis settings: {e}")
            return

        if not self._begin_run():
            return
        self.results_text.clear()
        self.harmonic_check_results_data.clear()
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
            log_func=self.log_to_main_app,
        )
        worker.signals.progress.connect(self._on_worker_progress)
        worker.signals.message.connect(self._on_worker_message)
        worker.signals.error.connect(self._on_worker_error)
        worker.signals.finished.connect(self._on_harmonic_finished)
        self.pool.start(worker)

    # ------- exports -------

    def _ensure_results_dir(self) -> str:
        results_dir = os.path.join(self.project_dir, "3 - Statistical Analysis Results")
        os.makedirs(results_dir, exist_ok=True)
        return results_dir

    def on_export_rm_anova(self):
        if self.rm_anova_results_data is None or self.rm_anova_results_data.empty:
            QMessageBox.information(self, "No Results", "No RM-ANOVA results to export.")
            return
        out_dir = self._ensure_results_dir()
        out_path = os.path.join(out_dir, "RM-ANOVA Results.xlsx")
        try:
            export_rm_anova_results_to_excel(self.rm_anova_results_data, out_path)
            QDesktopServices.openUrl(QUrl.fromLocalFile(out_dir))
        except Exception as e:
            QMessageBox.critical(self, "Export Failed", str(e))

    def on_export_mixed_model(self):
        if self.mixed_model_results_data is None or self.mixed_model_results_data.empty:
            QMessageBox.information(self, "No Results", "No Mixed Model results to export.")
            return
        out_dir = self._ensure_results_dir()
        out_path = os.path.join(out_dir, "Mixed Model Results.xlsx")
        try:
            export_mixed_model_results_to_excel(self.mixed_model_results_data, out_path)
            QDesktopServices.openUrl(QUrl.fromLocalFile(out_dir))
        except Exception as e:
            QMessageBox.critical(self, "Export Failed", str(e))

    def on_export_posthoc(self):
        if self.posthoc_results_data is None or self.posthoc_results_data.empty:
            QMessageBox.information(self, "No Results", "No Post-hoc results to export.")
            return
        out_dir = self._ensure_results_dir()
        out_path = os.path.join(out_dir, "Interaction Post-hocs.xlsx")
        try:
            export_posthoc_results_to_excel(self.posthoc_results_data, out_path)
            QDesktopServices.openUrl(QUrl.fromLocalFile(out_dir))
        except Exception as e:
            QMessageBox.critical(self, "Export Failed", str(e))

    def on_export_harmonic(self):
        if not self.harmonic_check_results_data:
            QMessageBox.information(self, "No Results", "No Harmonic Check results to export.")
            return
        out_dir = self._ensure_results_dir()
        out_path = os.path.join(out_dir, "Harmonic Check.xlsx")
        try:
            export_harmonic_results_to_excel(self.harmonic_check_results_data, out_path)
            QDesktopServices.openUrl(QUrl.fromLocalFile(out_dir))
        except Exception as e:
            QMessageBox.critical(self, "Export Failed", str(e))

    # ------- scanning / project defaults -------

    def on_browse_folder(self):
        start_dir = self.le_folder.text() or self.project_dir
        folder = QFileDialog.getExistingDirectory(self, "Select Data Folder", start_dir)
        if folder:
            self.le_folder.setText(folder)
            self._scan_button_clicked()

    def _scan_button_clicked(self):
        folder = self.le_folder.text()
        if not folder:
            QMessageBox.warning(self, "No Folder", "Please select a data folder first.")
            return
        try:
            subjects, conditions, data = scan_folder_simple(folder)
            self.subjects = subjects
            self.conditions = conditions
            self.subject_data = data
            self.lbl_status.setText(
                f"Scan complete: Found {len(subjects)} subjects and {len(conditions)} conditions."
            )
            # Update ROI status (wrapped) after a successful scan
            self.refresh_rois()
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
