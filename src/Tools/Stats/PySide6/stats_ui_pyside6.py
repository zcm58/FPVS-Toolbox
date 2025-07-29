from PySide6.QtWidgets import (
    QMainWindow, QWidget, QLabel, QLineEdit, QPushButton,
    QComboBox, QTextEdit, QHBoxLayout, QVBoxLayout,
    QFrame, QFileDialog, QSizePolicy, QMessageBox, QApplication
)
from PySide6.QtGui import QAction
from PySide6.QtCore import Qt, QTimer
import os
import json
from types import SimpleNamespace
from pathlib import Path

# Corrected imports for the new file structure
from Tools.Stats.PySide6.stats_file_scanner_pyside6 import scan_folder_simple, ScanError
from Tools.Stats.Legacy.stats_runners import (
    run_mixed_model,
    run_posthoc_tests, run_interaction_posthocs,
    run_harmonic_check, _structure_harmonic_results
)
from Tools.Stats.Legacy.stats_analysis import (
    prepare_all_subject_summed_bca_data,
    run_rm_anova as analysis_run_rm_anova,  # Alias to avoid name clash
    ALL_ROIS_OPTION
)
from Tools.Stats.Legacy.stats_helpers import (
    load_rois_from_settings, apply_rois_to_modules, log_to_main_app
)
from Tools.Stats.Legacy.stats_export import export_significance_results_to_excel
# Import the central settings manager to fetch the base frequency
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
    run_mixed_model = run_mixed_model
    run_posthoc_tests = run_posthoc_tests
    run_interaction_posthocs = run_interaction_posthocs
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

        # --- Data Folder Selection ---
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

        # --- Summed BCA Section ---
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

        self.run_rm_anova_btn = QPushButton("Run RM-ANOVA")
        self.run_mixed_model_btn = QPushButton("Run Mixed Model")
        self.run_posthoc_btn = QPushButton("Run Interaction Post-hocs")
        run_col.addWidget(self.run_rm_anova_btn)
        run_col.addWidget(self.run_mixed_model_btn)
        run_col.addWidget(self.run_posthoc_btn)

        self.export_rm_anova_btn = QPushButton("Export RM-ANOVA")
        self.export_mixed_model_btn = QPushButton("Export Mixed Model")
        self.export_posthoc_btn = QPushButton("Export Post-hoc Results")
        export_col.addWidget(self.export_rm_anova_btn)
        export_col.addWidget(self.export_mixed_model_btn)
        export_col.addWidget(self.export_posthoc_btn)

        btn_layout.addLayout(run_col);
        btn_layout.addLayout(export_col)
        vs.addLayout(btn_layout);
        main_layout.addWidget(summed_frame)

        # --- Harmonic Check Section ---
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

        # --- Connect Signals to Slots ---
        self.run_rm_anova_btn.clicked.connect(self.on_run_rm_anova)
        self.run_mixed_model_btn.clicked.connect(self.run_mixed_model)
        self.run_posthoc_btn.clicked.connect(self.run_interaction_posthocs)
        self.run_harm_btn.clicked.connect(self.run_harmonic_check)
        self.export_rm_anova_btn.clicked.connect(lambda: self.on_export("rm_anova"))
        self.export_mixed_model_btn.clicked.connect(lambda: self.on_export("mixed_model"))
        self.export_posthoc_btn.clicked.connect(lambda: self.on_export("posthoc"))
        self.export_harm_btn.clicked.connect(lambda: self.on_export("harmonic"))

    def on_run_rm_anova(self):
        """
        Handles the 'Run RM-ANOVA' button click.
        Gathers data, fetches settings, calls legacy analysis, and displays results.
        """
        if not self.subject_data:
            QMessageBox.warning(self, "No Data", "Please scan a data folder first.")
            return

        # Fetch base frequency from the central settings manager
        try:
            settings = SettingsManager()
            # Corrected method call and keys based on legacy stats_helpers.py
            base_freq = float(settings.get("analysis", "base_freq", 6.0))
        except Exception as e:
            QMessageBox.critical(self, "Settings Error", f"Could not load base frequency from settings: {e}")
            return

        # Clear previous results and prepare a logging function for the analysis
        self.results_text.clear()

        def log_to_gui(message):
            self.results_text.append(message)
            QApplication.processEvents()  # Keep UI responsive

        log_to_gui("Preparing data for Summed BCA RM-ANOVA...")

        # 1. Prepare the data using the legacy function
        all_subject_bca_data = prepare_all_subject_summed_bca_data(
            subjects=self.subjects,
            conditions=self.conditions,
            subject_data=self.subject_data,
            base_freq=base_freq,
            log_func=log_to_gui
        )

        if not all_subject_bca_data:
            log_to_gui("\nData preparation failed. Check logs for details.")
            return

        log_to_gui("Data preparation complete. Running RM-ANOVA...")

        # 2. Run the analysis using the legacy function
        results_str, results_df = analysis_run_rm_anova(all_subject_bca_data, log_to_gui)

        # 3. Store the results and update the UI
        self.rm_anova_results_data = results_df
        log_to_gui("\n--- RM-ANOVA Results ---")
        log_to_gui(results_str)
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
        data_map = {
            "rm_anova": (self.rm_anova_results_data, "RM-ANOVA"),
            "mixed_model": (self.mixed_model_results_data, "Mixed Model"),
            "posthoc": (self.posthoc_results_data, "Post-hoc"),
            "harmonic": (self.harmonic_check_results_data, "Harmonic Check")
        }
        data_to_export, name = data_map.get(export_type)
        if data_to_export is None or (hasattr(data_to_export, 'empty') and data_to_export.empty) or not data_to_export:
            QMessageBox.warning(self, "No Data", f"No {name} results to export. Please run the analysis first.")
            return
        file_path, _ = QFileDialog.getSaveFileName(self, f"Save {name} Results", self.project_dir,
                                                   "Excel Files (*.xlsx);;All Files (*)")
        if not file_path: return
        try:
            export_significance_results_to_excel(file_path, data_to_export, export_type)
            QMessageBox.information(self, "Export Successful", f"{name} results have been saved to:\n{file_path}")
        except Exception as e:
            QMessageBox.critical(self, "Export Failed", f"An error occurred while exporting:\n{e}")
            self.log_to_main_app(f"Failed to export {name} results: {e}")
