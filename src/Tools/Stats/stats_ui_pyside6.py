from PySide6.QtWidgets import (
    QMainWindow, QWidget, QLabel, QLineEdit, QPushButton,
    QComboBox, QTextEdit, QHBoxLayout, QVBoxLayout,
    QGroupBox, QFileDialog
)
from PySide6.QtGui import QAction
from PySide6.QtCore import Qt
import os


class StatsWindow(QMainWindow):
    """Skeleton PySide6 window for the FPVS Statistical Analysis Tool."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("FPVS Statistical Analysis Tool")
        self._init_ui()

    # ------------------------------------------------------------------
    # UI construction
    def _init_ui(self):
        central = QWidget(self)
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        # --- Data Folder Selection Row ---
        folder_row = QHBoxLayout()
        folder_row.setSpacing(5)
        lbl_folder = QLabel("Data Folder:")
        self.le_folder = QLineEdit()
        self.le_folder.setReadOnly(True)
        btn_browse = QPushButton("Browse…")
        btn_browse.clicked.connect(self.on_browse_folder)
        folder_row.addWidget(lbl_folder)
        folder_row.addWidget(self.le_folder, 1)
        folder_row.addWidget(btn_browse)
        main_layout.addLayout(folder_row)

        # Status label
        self.lbl_status = QLabel(
            "Scan complete: Found 7 subjects and 4 conditions.", self
        )
        self.lbl_status.setStyleSheet("background-color: lightgray;")
        main_layout.addWidget(self.lbl_status)

        # --- Summed BCA Analysis Section ---
        summed_group = QGroupBox()
        summed_layout = QVBoxLayout(summed_group)
        title_summed = QLabel("Summed BCA Analysis:")
        f = title_summed.font()
        f.setBold(True)
        title_summed.setFont(f)
        summed_layout.addWidget(title_summed, alignment=Qt.AlignLeft)

        buttons_row = QHBoxLayout()
        col1 = QVBoxLayout()
        col2 = QVBoxLayout()
        self.run_rm_anova_btn = QPushButton("Run RM-ANOVA (Summed BCA)")
        self.run_rm_anova_btn.clicked.connect(self.on_run_rm_anova)
        self.run_mixed_model_btn = QPushButton("Run Mixed Model")
        self.run_mixed_model_btn.clicked.connect(self.on_run_mixed_model)
        self.run_posthoc_btn = QPushButton("Run Interaction Post-hocs")
        self.run_posthoc_btn.clicked.connect(self.on_run_interaction_posthocs)

        self.export_rm_anova_btn = QPushButton("Export RM-ANOVA")
        self.export_rm_anova_btn.clicked.connect(self.on_export_rm_anova)
        self.export_mixed_model_btn = QPushButton("Export Mixed Model")
        self.export_mixed_model_btn.clicked.connect(self.on_export_mixed_model)
        self.export_posthoc_btn = QPushButton("Export Post-hoc Results")
        self.export_posthoc_btn.clicked.connect(self.on_export_posthoc_results)

        col1.addWidget(self.run_rm_anova_btn)
        col1.addWidget(self.run_mixed_model_btn)
        col1.addWidget(self.run_posthoc_btn)
        col2.addWidget(self.export_rm_anova_btn)
        col2.addWidget(self.export_mixed_model_btn)
        col2.addWidget(self.export_posthoc_btn)
        buttons_row.addLayout(col1)
        buttons_row.addLayout(col2)
        summed_layout.addLayout(buttons_row)

        main_layout.addWidget(summed_group)

        # --- Harmonic Significance Section ---
        harmonic_group = QGroupBox()
        harmonic_layout = QVBoxLayout(harmonic_group)
        title_harmonic = QLabel("Per-Harmonic Significance Check:")
        f2 = title_harmonic.font()
        f2.setBold(True)
        title_harmonic.setFont(f2)
        harmonic_layout.addWidget(title_harmonic, alignment=Qt.AlignLeft)

        controls_row = QHBoxLayout()
        controls_row.setSpacing(5)
        lbl_metric = QLabel("Metric:")
        self.cb_metric = QComboBox()
        self.cb_metric.addItems(["SNR"])
        lbl_thresh = QLabel("Mean Threshold:")
        self.le_threshold = QLineEdit("1.96")
        self.run_harmonic_btn = QPushButton("Run Harmonic Check")
        self.run_harmonic_btn.clicked.connect(self.on_run_harmonic_check)
        self.export_harmonic_btn = QPushButton("Export Harmonic Results")
        self.export_harmonic_btn.clicked.connect(self.on_export_harmonic_results)

        controls_row.addWidget(lbl_metric)
        controls_row.addWidget(self.cb_metric)
        controls_row.addWidget(lbl_thresh)
        controls_row.addWidget(self.le_threshold)
        controls_row.addWidget(self.run_harmonic_btn)
        controls_row.addWidget(self.export_harmonic_btn)
        harmonic_layout.addLayout(controls_row)

        main_layout.addWidget(harmonic_group)

        # --- Results Display ---
        self.results_text = QTextEdit()
        self.results_text.setReadOnly(True)
        main_layout.addWidget(self.results_text, 1)

    # ------------------------------------------------------------------
    # Slots / Actions
    def on_browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Data Folder", os.getcwd())
        if folder:
            self.le_folder.setText(folder)
            print(f"Selected folder: {folder}")

    def on_run_rm_anova(self):
        print("Run RM-ANOVA clicked")

    def on_export_rm_anova(self):
        print("Export RM-ANOVA clicked")

    def on_run_mixed_model(self):
        print("Run Mixed Model clicked")

    def on_export_mixed_model(self):
        print("Export Mixed Model clicked")

    def on_run_interaction_posthocs(self):
        print("Run Interaction Post-hocs clicked")

    def on_export_posthoc_results(self):
        print("Export Post-hoc Results clicked")

    def on_run_harmonic_check(self):
        print("Run Harmonic Check clicked")

    def on_export_harmonic_results(self):
        print("Export Harmonic Results clicked")

