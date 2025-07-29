from PySide6.QtWidgets import (
    QMainWindow, QWidget, QLabel, QLineEdit, QPushButton,
    QComboBox, QTextEdit, QHBoxLayout, QVBoxLayout,
    QFrame, QFileDialog, QSizePolicy, QMessageBox, QApplication
)
from PySide6.QtGui import QAction
from PySide6.QtCore import Qt, QTimer
import os
import pandas as pd
import numpy as np
from types import SimpleNamespace
from pathlib import Path

# Corrected imports for the new file structure
from Tools.Stats.PySide6.stats_file_scanner_pyside6 import scan_folder_simple, ScanError
from Tools.Stats.Legacy.stats_runners import (
    run_harmonic_check, _structure_harmonic_results
)
from Tools.Stats.Legacy.stats_analysis import (
    prepare_all_subject_summed_bca_data,
    run_rm_anova as analysis_run_rm_anova,
    ALL_ROIS_OPTION
)
from Tools.Stats.Legacy.mixed_effects_model import run_mixed_effects_model
from Tools.Stats.Legacy.interpretation_helpers import generate_lme_summary
from Tools.Stats.Legacy.posthoc_tests import run_interaction_posthocs

from Tools.Stats.Legacy.stats_helpers import (
    load_rois_from_settings, apply_rois_to_modules, log_to_main_app
)
# Import all the new, UI-agnostic export functions
from Tools.Stats.Legacy.stats_export import (
    export_rm_anova_results_to_excel,
    export_mixed_model_results_to_excel,
    export_posthoc_results_to_excel,
    export_significance_results_to_excel
)
from Main_App import SettingsManager


def _auto_detect_project_dir() -> str:
    """
    Walk up directories to find project.json and return its folder,
    or cwd if none found.
    """
    path = Path.cwd()
    while not (path / 'project.json').is_file():
        if path.parent == path:
            return str(Path.cwd())
        path = path.parent
    return str(path)


class StatsWindow(QMainWindow):
    """PySide6 window wrapping the legacy FPVS Statistical Analysis Tool."""

    # Alias other legacy methods directly
    run_harmonic_check = run_harmonic_check
    _structure_harmonic_results = _structure_harmonic_results
    log_to_main_app = log_to_main_app

    def __init__(self, parent=None, project_dir: str = None):
        if project_dir and os.path.isdir(project_dir):
            self.project_dir = project_dir
        else:
            proj = getattr(parent, 'currentProject', None)
            self.project_dir = str(proj.project_root) if proj and hasattr(proj,
                                                                          'project_root') else _auto_detect_project_dir()

        super().__init__(parent)
        self.setWindowFlags(self.windowFlags() | Qt.Window)
        self.setWindowTitle("FPVS Statistical Analysis Tool")

        # --- Legacy state variables ---
        self.subject_data = {}
        self.subjects = []
        self.conditions = []
        self.rm_anova_results_data = None
        self.mixed_model_results_data = None
        self.posthoc_results_data = None
        self.harmonic_check_results_data = []

        # --- UI variable proxies ---
        self.stats_data_folder_var = SimpleNamespace(get=lambda: self.le_folder.text(),
                                                     set=lambda v: self.le_folder.setText(v))
        self.detected_info_var = SimpleNamespace(set=lambda txt: self.lbl_status.setText(txt))
        self.roi_var = SimpleNamespace(get=lambda: ALL_ROIS_OPTION, set=lambda v: None)
        self.alpha_var = SimpleNamespace(get=lambda: "0.05", set=lambda v: None)
        self.harmonic_metric_var = SimpleNamespace(get=lambda: self.cb_metric.currentText(), set=lambda v: None)
        self.harmonic_threshold_var = SimpleNamespace(get=lambda: self.le_threshold.text(), set=lambda v: None)
        self.posthoc_factor_var = SimpleNamespace(get=lambda: "condition by roi", set=lambda v: None)

        self._init_ui()
        self.results_textbox = self.results_text
        QTimer.singleShot(100, self._load_default_data_folder)

    def _init_ui(self):
        central = QWidget(self)
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        folder_row = QHBoxLayout();
        folder_row.setSpacing(5)
        self.le_folder = QLineEdit();
        self.le_folder.setReadOnly(True)
        btn_browse = QPushButton("Browse…");
        btn_browse.clicked.connect(self.on_browse_folder)
        folder_row.addWidget(QLabel("Data Folder:"))
        folder_row.addWidget(self.le_folder, 1)
        folder_row.addWidget(btn_browse)
        main_layout.addLayout(folder_row)

        self.btn_scan = QPushButton("Scan Folder Contents")
        self.btn_scan.clicked.connect(self._scan_button_clicked)
        main_layout.addWidget(self.btn_scan)

        self.lbl_status = QLabel("Select a folder containing FPVS results.")
        main_layout.addWidget(self.lbl_status)

        summed_frame = QFrame();
        summed_frame.setFrameShape(QFrame.StyledPanel)
        vs = QVBoxLayout(summed_frame)
        title = QLabel("Summed BCA Analysis:");
        font = title.font();
        font.setBold(True);
        title.setFont(font)
        vs.addWidget(title, alignment=Qt.AlignLeft)

        btn_layout = QHBoxLayout()
        run_col, export_col = QVBoxLayout(), QVBoxLayout()
        self.run_rm_anova_btn = QPushButton("Run RM-ANOVA");
        run_col.addWidget(self.run_rm_anova_btn)
        self.run_mixed_model_btn = QPushButton("Run Mixed Model");
        run_col.addWidget(self.run_mixed_model_btn)
        self.run_posthoc_btn = QPushButton("Run Interaction Post-hocs");
        run_col.addWidget(self.run_posthoc_btn)
        self.export_rm_anova_btn = QPushButton("Export RM-ANOVA");
        export_col.addWidget(self.export_rm_anova_btn)
        self.export_mixed_model_btn = QPushButton("Export Mixed Model");
        export_col.addWidget(self.export_mixed_model_btn)
        self.export_posthoc_btn = QPushButton("Export Post-hoc Results");
        export_col.addWidget(self.export_posthoc_btn)
        btn_layout.addLayout(run_col);
        btn_layout.addLayout(export_col)
        vs.addLayout(btn_layout);
        main_layout.addWidget(summed_frame)

        harm_frame = QFrame();
        harm_frame.setFrameShape(QFrame.StyledPanel)
        vh = QVBoxLayout(harm_frame)
        t2 = QLabel("Per-Harmonic Significance Check:");
        hf = t2.font();
        hf.setBold(True);
        t2.setFont(hf)
        vh.addWidget(t2, alignment=Qt.AlignLeft)
        harm_layout = QHBoxLayout()
        harm_layout.addWidget(QLabel("Metric:"));
        self.cb_metric = QComboBox();
        self.cb_metric.addItems(["SNR", "Z-Score"]);
        harm_layout.addWidget(self.cb_metric)
        harm_layout.addWidget(QLabel("Mean Threshold:"));
        self.le_threshold = QLineEdit("1.96");
        harm_layout.addWidget(self.le_threshold)
        self.run_harm_btn = QPushButton("Run Harmonic Check");
        harm_layout.addWidget(self.run_harm_btn)
        self.export_harm_btn = QPushButton("Export Harmonic Results");
        harm_layout.addWidget(self.export_harm_btn)
        vh.addLayout(harm_layout);
        main_layout.addWidget(harm_frame)

        self.results_text = QTextEdit();
        self.results_text.setReadOnly(True)
        main_layout.addWidget(self.results_text, 1)

        self.run_rm_anova_btn.clicked.connect(self.on_run_rm_anova)
        self.run_mixed_model_btn.clicked.connect(self.on_run_mixed_model)
        self.run_posthoc_btn.clicked.connect(self.on_run_interaction_posthocs)
        self.run_harm_btn.clicked.connect(self.on_run_harmonic_check)
        self.export_rm_anova_btn.clicked.connect(lambda: self.on_export("rm_anova"))
        self.export_mixed_model_btn.clicked.connect(lambda: self.on_export("mixed_model"))
        self.export_posthoc_btn.clicked.connect(lambda: self.on_export("posthoc"))
        self.export_harm_btn.clicked.connect(lambda: self.on_export("harmonic"))

    def on_run_rm_anova(self):
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

        self.results_text.clear()
        self.rm_anova_results_data = None
        self.export_rm_anova_btn.setEnabled(False)

        def log_to_gui(message):
            self.results_text.append(message)
            QApplication.processEvents()

        log_to_gui("Preparing data for Summed BCA RM-ANOVA...")

        all_subject_bca_data = prepare_all_subject_summed_bca_data(
            subjects=self.subjects, conditions=self.conditions,
            subject_data=self.subject_data, base_freq=base_freq, log_func=log_to_gui
        )

        if not all_subject_bca_data:
            log_to_gui("\nData preparation failed. Check logs for details.")
            return

        log_to_gui("Data preparation complete. Running RM-ANOVA...")

        _, anova_df_results = analysis_run_rm_anova(all_subject_bca_data, log_to_gui)

        output_text = "============================================================\n"
        output_text += "       Repeated Measures ANOVA (RM-ANOVA) Results\n"
        output_text += "       Analysis conducted on: Summed BCA Data\n"
        output_text += "============================================================\n\n"
        output_text += (
            "This test examines the overall effects of your experimental conditions (e.g., different stimuli),\n"
            "the different brain regions (ROIs) you analyzed, and, crucially, whether the\n"
            "effect of the conditions changes depending on the brain region (interaction effect).\n\n")

        if anova_df_results is not None and not anova_df_results.empty:
            pes_vals = []
            for _, row in anova_df_results.iterrows():
                f_val = row.get('F Value', np.nan)
                df1 = row.get('Num DF', np.nan)
                df2 = row.get('Den DF', np.nan)
                if not pd.isna(f_val) and not pd.isna(df1) and not pd.isna(df2) and (f_val * df1 + df2) != 0:
                    pes_vals.append((f_val * df1) / ((f_val * df1) + df2))
                else:
                    pes_vals.append(np.nan)
            anova_df_results['partial eta squared'] = pes_vals

            output_text += "--------------------------------------------\n"
            output_text += "           STATISTICAL TABLE (RM-ANOVA)\n"
            output_text += "--------------------------------------------\n"
            output_text += anova_df_results.to_string(index=False) + "\n\n"
            self.rm_anova_results_data = anova_df_results
            self.export_rm_anova_btn.setEnabled(True)

            output_text += "--------------------------------------------\n"
            output_text += "       SIMPLIFIED EXPLANATION OF RESULTS\n"
            output_text += "--------------------------------------------\n"
            output_text += f"(A result is 'statistically significant' if its p-value ('Pr > F') is less than {alpha:.2f})\n\n"

            for _, row in anova_df_results.iterrows():
                effect_name_raw = str(row.get('Effect', 'Unknown Effect'))
                p_value_raw = row.get('Pr > F', np.nan)
                eta_sq = row.get('partial eta squared', np.nan)

                effect_display_name = effect_name_raw.replace(':', ' by ').replace('_', ' ').title()
                output_text += f"Effect: {effect_display_name}\n"

                if pd.isna(p_value_raw):
                    output_text += "  - Significance: Could not be determined (p-value missing).\n\n"
                    continue

                is_significant = p_value_raw < alpha
                p_value_display = "< .0001" if p_value_raw < 0.0001 else f"{p_value_raw:.4f}"
                eta_sq_display = f"{eta_sq:.3f}" if not pd.isna(eta_sq) else "N/A"

                output_text += f"  - Statistical Finding: {'SIGNIFICANT' if is_significant else 'NOT SIGNIFICANT'} (p-value = {p_value_display})\n"
                output_text += f"  - Partial Eta Squared: {eta_sq_display}\n"

                explanation = ""
                if 'condition' in effect_name_raw.lower() and 'roi' in effect_name_raw.lower():
                    explanation = "  - Interpretation: This is often the most important finding! It means the way brain activity\n" \
                                  "                    changed across conditions **depended on which brain region** you were observing.\n" if is_significant else \
                        "  - Interpretation: The effect of your conditions on brain activity was generally consistent\n" \
                        "                    across the different brain regions analyzed.\n"
                elif 'condition' == effect_name_raw.lower():
                    explanation = "  - Interpretation: Overall, averaging across all ROIs, your conditions led to statistically\n" \
                                  "                    different average levels of brain activity.\n" if is_significant else \
                        "  - Interpretation: When averaging across all ROIs, your conditions did not produce\n" \
                        "                    statistically different overall levels of brain activity.\n"
                elif 'roi' == effect_name_raw.lower():
                    explanation = "  - Interpretation: Different brain regions showed reliably different average levels of activity,\n" \
                                  "                    regardless of the specific experimental condition.\n" if is_significant else \
                        "  - Interpretation: There wasn't a significant overall difference in activity between the\n" \
                        "                    different brain regions analyzed.\n"

                output_text += explanation + "\n"

            output_text += "--------------------------------------------\n"
            output_text += "NOTE: This explanation simplifies the main statistical patterns. For detailed reporting\n"
            output_text += "and follow-up analyses (e.g., post-hoc tests), please refer to the table above.\n"
            output_text += "--------------------------------------------\n"
        else:
            output_text += "RM-ANOVA did not return any results or the result was empty.\n"

        self.results_text.setText(output_text)
        log_to_gui("\nAnalysis complete.")

    def on_run_mixed_model(self):
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

        self.results_text.clear()
        self.mixed_model_results_data = None
        self.export_mixed_model_btn.setEnabled(False)

        def log_to_gui(message):
            self.results_text.append(message)
            QApplication.processEvents()

        log_to_gui("Preparing data for Mixed Effects Model...")

        all_subject_bca_data = prepare_all_subject_summed_bca_data(
            subjects=self.subjects, conditions=self.conditions,
            subject_data=self.subject_data, base_freq=base_freq, log_func=log_to_gui
        )

        if not all_subject_bca_data:
            log_to_gui("\nData preparation failed. Check logs for details.")
            return

        long_format_data = []
        for pid, cond_data in all_subject_bca_data.items():
            for cond_name, roi_data in cond_data.items():
                for roi_name, value in roi_data.items():
                    if not pd.isna(value):
                        long_format_data.append(
                            {'subject': pid, 'condition': cond_name, 'roi': roi_name, 'value': value})

        if not long_format_data:
            QMessageBox.critical(self, "Data Error", "No valid data available for Mixed Model after filtering NaNs.")
            return

        df_long = pd.DataFrame(long_format_data)
        log_to_gui("Data preparation complete. Running Mixed Effects Model...")

        output_text = "============================================================\n"
        output_text += "       Linear Mixed-Effects Model Results\n"
        output_text += "       Analysis conducted on: Summed BCA Data\n"
        output_text += "============================================================\n\n"
        output_text += (
            "This model accounts for repeated observations from each subject by including\n"
            "a random intercept. Fixed effects assess how conditions and ROIs influence\n"
            "Summed BCA values, including their interaction.\n\n"
        )

        try:
            mixed_results_df = run_mixed_effects_model(
                data=df_long,
                dv_col='value',
                group_col='subject',
                fixed_effects=['condition * roi']
            )

            if mixed_results_df is not None and not mixed_results_df.empty:
                output_text += "--------------------------------------------\n"
                output_text += "                 FIXED EFFECTS TABLE\n"
                output_text += "--------------------------------------------\n"
                output_text += mixed_results_df.to_string(index=False) + "\n"
                output_text += generate_lme_summary(mixed_results_df, alpha=alpha)
                self.mixed_model_results_data = mixed_results_df
                self.export_mixed_model_btn.setEnabled(True)
            else:
                output_text += "Mixed effects model did not return any results or the result was empty.\n"

        except Exception as e:
            output_text += f"Mixed effects model failed unexpectedly: {e}\n"
            QMessageBox.critical(self, "Analysis Failed", f"An error occurred during the mixed model analysis:\n{e}")

        self.results_text.setText(output_text)
        log_to_gui("\nAnalysis complete.")

    def on_run_interaction_posthocs(self):
        if not self.subject_data:
            QMessageBox.warning(self, "No Data", "Please scan a data folder first.")
            return

        if self.rm_anova_results_data is None:
            QMessageBox.warning(self, "Run ANOVA First",
                                "Please run a successful RM-ANOVA before running post-hoc tests for the interaction.")
            return

        try:
            settings = SettingsManager()
            base_freq = float(settings.get("analysis", "base_freq", 6.0))
            alpha = float(settings.get("analysis", "alpha", 0.05))
        except Exception as e:
            QMessageBox.critical(self, "Settings Error", f"Could not load analysis settings: {e}")
            return

        self.results_text.clear()
        self.posthoc_results_data = None
        self.export_posthoc_btn.setEnabled(False)

        def log_to_gui(message):
            self.results_text.append(message)
            QApplication.processEvents()

        log_to_gui("Preparing data for Interaction Post-hoc tests...")

        all_subject_bca_data = prepare_all_subject_summed_bca_data(
            subjects=self.subjects, conditions=self.conditions,
            subject_data=self.subject_data, base_freq=base_freq, log_func=log_to_gui
        )

        if not all_subject_bca_data:
            log_to_gui("\nData preparation failed. Check logs for details.")
            return

        long_format_data = []
        for pid, cond_data in all_subject_bca_data.items():
            for cond_name, roi_data in cond_data.items():
                for roi_name, value in roi_data.items():
                    if not pd.isna(value):
                        long_format_data.append(
                            {'subject': pid, 'condition': cond_name, 'roi': roi_name, 'value': value})

        if not long_format_data:
            QMessageBox.critical(self, "Data Error", "No valid data available for post-hoc tests after filtering NaNs.")
            return

        df_long = pd.DataFrame(long_format_data)
        log_to_gui("Data preparation complete. Running post-hoc tests...")

        try:
            output_text, results_df = run_interaction_posthocs(
                data=df_long,
                dv_col='value',
                roi_col='roi',
                condition_col='condition',
                subject_col='subject',
                alpha=alpha
            )

            self.results_text.setText(output_text)
            if results_df is not None and not results_df.empty:
                self.posthoc_results_data = results_df
                self.export_posthoc_btn.setEnabled(True)

        except Exception as e:
            QMessageBox.critical(self, "Analysis Failed", f"An error occurred during the post-hoc analysis:\n{e}")
            self.results_text.setText(f"Post-hoc analysis failed unexpectedly: {e}")

        log_to_gui("\nAnalysis complete.")

    def on_run_harmonic_check(self):
        """
        Handles the 'Run Harmonic Check' button click.
        """
        if not self.subject_data:
            QMessageBox.warning(self, "No Data", "Please scan a data folder first.")
            return

        try:
            settings = SettingsManager()
            base_freq = float(settings.get("analysis", "base_freq", 6.0))
            alpha = float(settings.get("analysis", "alpha", 0.05))
            metric = self.harmonic_metric_var.get()
            threshold = float(self.harmonic_threshold_var.get())
        except ValueError:
            QMessageBox.warning(self, "Invalid Input", "Please ensure Mean Threshold is a valid number.")
            return
        except Exception as e:
            QMessageBox.critical(self, "Settings Error", f"Could not load analysis settings: {e}")
            return

        self.results_text.clear()
        self.harmonic_check_results_data = []
        self.export_harm_btn.setEnabled(False)

        def log_to_gui(message):
            self.results_text.append(message)
            QApplication.processEvents()

        log_to_gui("Running Per-Harmonic Significance Check...")

        try:
            output_text, findings_list = run_harmonic_check(
                self,  # Pass self to give access to legacy helper methods
            )
            self.results_text.setText(output_text)
            if findings_list:
                self.harmonic_check_results_data = findings_list
                self.export_harm_btn.setEnabled(True)
        except Exception as e:
            QMessageBox.critical(self, "Analysis Failed", f"An error occurred during the harmonic check:\n{e}")
            self.results_text.setText(f"Harmonic check failed unexpectedly: {e}")

        log_to_gui("\nAnalysis complete.")

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
            self.lbl_status.setText(f"Scan complete: Found {len(subjects)} subjects and {len(conditions)} conditions.")
        except ScanError as e:
            self.lbl_status.setText(f"Scan failed: {e}")
            QMessageBox.critical(self, "Scan Error", str(e))

    def _load_default_data_folder(self):
        default = None
        if self.parent() and hasattr(self.parent(), 'currentProject'):
            proj = self.parent().currentProject
            if proj:
                root = getattr(proj, 'project_root', '')
                sub = proj.subfolders.get('excel', '')
                cand = Path(root) / sub
                if cand.is_dir(): default = str(cand)
        if not default:
            cand = Path(_auto_detect_project_dir()) / '1 - Excel Data Files'
            if cand.is_dir(): default = str(cand)
        if default:
            self.le_folder.setText(default)
            self._scan_button_clicked()

    def on_export(self, export_type: str):
        """Handles exporting different result types to Excel."""

        export_map = {
            "rm_anova": {
                "data": self.rm_anova_results_data,
                "func": export_rm_anova_results_to_excel,
                "name": "RM-ANOVA",
                "file": "Stats_RM_ANOVA_SummedBCA.xlsx",
                "kwargs": {}
            },
            "mixed_model": {
                "data": self.mixed_model_results_data,
                "func": export_mixed_model_results_to_excel,
                "name": "Mixed Model",
                "file": "Stats_MixedModel.xlsx",
                "kwargs": {}
            },
            "posthoc": {
                "data": self.posthoc_results_data,
                "func": export_posthoc_results_to_excel,
                "name": "Post-hoc",
                "file": "Stats_Posthoc_Interaction.xlsx",
                "kwargs": {'factor': 'condition by roi'}
            },
            "harmonic": {
                "data": self._structure_harmonic_results(),  # Call the structuring function
                "func": export_significance_results_to_excel,
                "name": "Harmonic Check",
                "file": f"Stats_HarmonicCheck_{self.harmonic_metric_var.get()}.xlsx",
                "kwargs": {'metric': self.harmonic_metric_var.get()}
            }
        }

        config = export_map.get(export_type)
        if not config:
            QMessageBox.critical(self, "Export Error", f"Unknown export type: {export_type}")
            return

        data_to_export = config["data"]

        # Correctly check if the data is empty (works for DataFrames and other types)
        is_empty = False
        if data_to_export is None:
            is_empty = True
        elif isinstance(data_to_export, pd.DataFrame):
            is_empty = data_to_export.empty
        elif isinstance(data_to_export, (list, dict)):
            is_empty = not data_to_export

        if is_empty:
            QMessageBox.warning(self, "No Data",
                                f"No {config['name']} results to export. Please run the analysis first.")
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self, f"Save {config['name']} Results", self.project_dir, "Excel Files (*.xlsx)"
        )
        if not file_path:
            return

        try:
            # Pass the data and path to the UI-agnostic export function
            config["func"](data_to_export, file_path, self.log_to_main_app, **config["kwargs"])
            QMessageBox.information(self, "Export Successful",
                                    f"{config['name']} results have been saved to:\n{file_path}")
        except Exception as e:
            QMessageBox.critical(self, "Export Failed",
                                 f"An error occurred while exporting {config['name']} results:\n{e}")
