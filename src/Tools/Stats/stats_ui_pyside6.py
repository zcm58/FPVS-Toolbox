from PySide6.QtWidgets import (
    QMainWindow, QWidget, QLabel, QLineEdit, QPushButton,
    QComboBox, QTextEdit, QHBoxLayout, QVBoxLayout,
    QFrame, QFileDialog, QSizePolicy
)
from PySide6.QtGui import QAction
from PySide6.QtCore import Qt
import os
import json
import tkinter.messagebox as messagebox
from types import SimpleNamespace

# Legacy imports for scanning and analysis
from Tools.Stats.stats_file_scanner import (
    browse_folder, scan_folder,
    update_condition_menus, update_condition_B_options
)
from Tools.Stats.stats_runners import (
    run_rm_anova, run_mixed_model,
    run_posthoc_tests, run_interaction_posthocs,
    run_harmonic_check, _structure_harmonic_results
)
from Tools.Stats.stats_helpers import (
    load_rois_from_settings, apply_rois_to_modules, log_to_main_app
)
from Tools.Stats.stats_analysis import ALL_ROIS_OPTION


def _auto_detect_project_dir() -> str:
    """
    Walk up directories to find project.json and return its folder,
    or cwd if none found.
    """
    path = os.getcwd()
    while True:
        if os.path.isfile(os.path.join(path, 'project.json')):
            return path
        parent = os.path.dirname(path)
        if parent == path:
            break
        path = parent
    return os.getcwd()


class StatsWindow(QMainWindow):
    """PySide6 window wrapping the legacy FPVS Statistical Analysis Tool."""

    # Alias legacy methods directly
    browse_folder = browse_folder
    scan_folder = scan_folder
    update_condition_menus = update_condition_menus
    update_condition_B_options = update_condition_B_options
    run_rm_anova = run_rm_anova
    run_mixed_model = run_mixed_model
    run_posthoc_tests = run_posthoc_tests
    run_interaction_posthocs = run_interaction_posthocs
    run_harmonic_check = run_harmonic_check
    _structure_harmonic_results = _structure_harmonic_results
    log_to_main_app = log_to_main_app

    def __init__(self, parent=None, project_dir: str = None):
        # Determine project_dir
        if project_dir and os.path.isdir(project_dir):
            self.project_dir = project_dir
        else:
            proj = getattr(parent, 'currentProject', None)
            if proj and hasattr(proj, 'project_root'):
                self.project_dir = str(proj.project_root)
            else:
                self.project_dir = _auto_detect_project_dir()
        if not os.path.isdir(self.project_dir):
            self.project_dir = _auto_detect_project_dir()

        super().__init__(parent)
        # Independent top-level window
        self.setWindowFlags(self.windowFlags() | Qt.Window)
        self.setWindowTitle("FPVS Statistical Analysis Tool")

        # --- Legacy state variables ---
        self.subject_data = {}
        self.all_subject_data = {}
        self.subjects = []
        self.conditions = []
        self.rm_anova_results_data = None
        self.mixed_model_results_data = None
        self.posthoc_results_data = None
        self.harmonic_check_results_data = []

        # --- UI variable proxies for legacy code expecting tk.StringVar-like API ---
        self.stats_data_folder_var = SimpleNamespace(
            get=lambda: self.le_folder.text(),
            set=lambda v: self.le_folder.setText(v)
        )
        self.detected_info_var = SimpleNamespace(
            set=lambda txt: self.lbl_status.setText(txt)
        )
        self.roi_var = SimpleNamespace(
            get=lambda: ALL_ROIS_OPTION,
            set=lambda v: None
        )
        self.alpha_var = SimpleNamespace(
            get=lambda: "0.05",
            set=lambda v: None
        )
        self.harmonic_metric_var = SimpleNamespace(
            get=lambda: self.cb_metric.currentText(),
            set=lambda v: None
        )
        self.harmonic_threshold_var = SimpleNamespace(
            get=lambda: self.le_threshold.text(),
            set=lambda v: None
        )
        self.posthoc_factor_var = SimpleNamespace(
            get=lambda: "condition by roi",
            set=lambda v: None
        )

        self._init_ui()
        # Bind the QTextEdit to legacy name
        self.results_textbox = self.results_text
        # Auto-load default data folder
        self._load_default_data_folder()

    def _init_ui(self):
        central = QWidget(self)
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        # --- Data Folder Selection ---
        folder_row = QHBoxLayout(); folder_row.setSpacing(5)
        lbl = QLabel("Data Folder:")
        self.le_folder = QLineEdit(); self.le_folder.setReadOnly(True); self.le_folder.setFixedHeight(28)
        btn = QPushButton("Browse…"); btn.setFixedHeight(28)
        btn.clicked.connect(lambda: self.browse_folder())
        folder_row.addWidget(lbl)
        folder_row.addWidget(self.le_folder, 1)
        folder_row.addWidget(btn)
        main_layout.addLayout(folder_row)

        # --- Status ---
        self.lbl_status = QLabel("Select folder containing FPVS results.", self)
        main_layout.addWidget(self.lbl_status)

        # --- Summed BCA Section ---
        summed = QFrame(); summed.setFrameShape(QFrame.StyledPanel); summed.setLineWidth(1)
        vs = QVBoxLayout(summed)
        title = QLabel("Summed BCA Analysis:"); f = title.font(); f.setBold(True); title.setFont(f)
        vs.addWidget(title, alignment=Qt.AlignLeft)
        hr = QHBoxLayout(); vc1, vc2 = QVBoxLayout(), QVBoxLayout()
        self.run_rm_anova_btn = QPushButton("Run RM-ANOVA (Summed BCA)")
        self.run_rm_anova_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.run_rm_anova_btn.clicked.connect(lambda: self.run_rm_anova())
        vc1.addWidget(self.run_rm_anova_btn)
        self.run_mixed_model_btn = QPushButton("Run Mixed Model")
        self.run_mixed_model_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.run_mixed_model_btn.clicked.connect(lambda: self.run_mixed_model())
        vc1.addWidget(self.run_mixed_model_btn)
        self.run_posthoc_btn = QPushButton("Run Interaction Post-hocs")
        self.run_posthoc_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.run_posthoc_btn.clicked.connect(lambda: self.run_interaction_posthocs())
        vc1.addWidget(self.run_posthoc_btn)
        self.export_rm_anova_btn = QPushButton("Export RM-ANOVA")
        self.export_rm_anova_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        vc2.addWidget(self.export_rm_anova_btn)
        self.export_mixed_model_btn = QPushButton("Export Mixed Model")
        self.export_mixed_model_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        vc2.addWidget(self.export_mixed_model_btn)
        self.export_posthoc_btn = QPushButton("Export Post-hoc Results")
        self.export_posthoc_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        vc2.addWidget(self.export_posthoc_btn)
        hr.addLayout(vc1); hr.addLayout(vc2); vs.addLayout(hr)
        main_layout.addWidget(summed)

        # --- Harmonic Check Section ---
        harm = QFrame(); harm.setFrameShape(QFrame.StyledPanel); harm.setLineWidth(1)
        vh = QVBoxLayout(harm)
        t2 = QLabel("Per-Harmonic Significance Check:"); hf = t2.font(); hf.setBold(True); t2.setFont(hf)
        vh.addWidget(t2, alignment=Qt.AlignLeft)
        rc = QHBoxLayout(); rc.setSpacing(5)
        rc.addWidget(QLabel("Metric:"))
        self.cb_metric = QComboBox(); self.cb_metric.addItems(["SNR", "Z-Score"]); rc.addWidget(self.cb_metric)
        rc.addWidget(QLabel("Mean Threshold:")); self.le_threshold = QLineEdit("1.96"); rc.addWidget(self.le_threshold)
        runh = QPushButton("Run Harmonic Check"); runh.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        runh.clicked.connect(lambda: self.run_harmonic_check()); rc.addWidget(runh)
        exph = QPushButton("Export Harmonic Results"); exph.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        rc.addWidget(exph)
        vh.addLayout(rc); main_layout.addWidget(harm)

        # --- Results Display ---
        self.results_text = QTextEdit(); self.results_text.setReadOnly(True)
        main_layout.addWidget(self.results_text, 1)

    def _load_default_data_folder(self):
        # Populate using legacy scan_folder or auto-detect
        default = None
        parent = self.parent()
        if parent and hasattr(parent, 'currentProject') and parent.currentProject:
            proj = parent.currentProject
            root = str(getattr(proj, 'project_root', ''))
            sub = proj.subfolders.get('excel', '')
            cand = os.path.join(root, sub)
            if os.path.isdir(cand): default = cand
        if not default or not os.path.isdir(default):
            pd_dir = _auto_detect_project_dir(); cand = os.path.join(pd_dir, '1 - Excel Data Files')
            if os.path.isdir(cand): default = cand
        if default and os.path.isdir(default):
            self.le_folder.setText(default)
            self.stats_data_folder_var.set(default)
            try:
                self.scan_folder()
            except Exception as e:
                self.lbl_status.setText(f"Initial scan failed: {e}")

    # No custom slots needed; using aliased legacy methods
