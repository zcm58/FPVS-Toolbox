"""PySide6 GUI skeleton for the FPVS Statistical Analysis Tool.

This module defines a minimal :class:`StatsWindow` class that lays out the
widgets required for running statistical analyses. No behaviour is wired up
yet; this file only establishes the user interface.
"""

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
    QSizePolicy,
)
from PySide6.QtGui import QAction
from PySide6.QtCore import Qt


class StatsWindow(QMainWindow):
    """Standalone window for the FPVS Statistical Analysis Tool."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("FPVS Statistical Analysis Tool")
        # Ensure the window floats independently from the main app
        self.setWindowFlags(self.windowFlags() | Qt.Window)

        self._init_ui()
        self._connect_signals()

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------
    def _init_ui(self) -> None:
        """Build and lay out all widgets for the window."""

        central = QWidget(self)
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        # --------------------------------------------------------------
        # Data folder selection
        # --------------------------------------------------------------
        folder_row = QHBoxLayout()
        folder_row.setSpacing(5)

        lbl_folder = QLabel("Data Folder:")
        self.le_folder = QLineEdit()
        self.le_folder.setReadOnly(True)
        self.le_folder.setFixedHeight(28)

        self.btn_browse = QPushButton("Browse…")

        folder_row.addWidget(lbl_folder)
        folder_row.addWidget(self.le_folder, 1)
        folder_row.addWidget(self.btn_browse)

        main_layout.addLayout(folder_row)

        # --------------------------------------------------------------
        # Scan button and status message
        # --------------------------------------------------------------
        self.btn_scan = QPushButton("Scan Folder Contents")
        main_layout.addWidget(self.btn_scan)

        self.lbl_status = QLabel()
        main_layout.addWidget(self.lbl_status)

        # --------------------------------------------------------------
        # Summed BCA analysis options
        # --------------------------------------------------------------
        summed_frame = QFrame()
        summed_frame.setFrameShape(QFrame.StyledPanel)

        summed_layout = QVBoxLayout(summed_frame)

        title = QLabel("Summed BCA Analysis:")
        title_font = title.font()
        title_font.setBold(True)
        title.setFont(title_font)
        summed_layout.addWidget(title, alignment=Qt.AlignLeft)

        summed_rows = QHBoxLayout()
        col_left = QVBoxLayout()
        col_right = QVBoxLayout()

        self.btn_run_rm_anova = QPushButton("Run RM-ANOVA (Summed BCA)")
        self.btn_run_mixed_model = QPushButton("Run Mixed Model")
        self.btn_run_posthocs = QPushButton("Run Interaction Post-hocs")

        col_left.addWidget(self.btn_run_rm_anova)
        col_left.addWidget(self.btn_run_mixed_model)
        col_left.addWidget(self.btn_run_posthocs)

        # right column intentionally left blank as a placeholder
        summed_rows.addLayout(col_left)
        summed_rows.addLayout(col_right)
        summed_layout.addLayout(summed_rows)

        main_layout.addWidget(summed_frame)

        # --------------------------------------------------------------
        # Harmonic significance check
        # --------------------------------------------------------------
        harmonic_frame = QFrame()
        harmonic_frame.setFrameShape(QFrame.StyledPanel)

        harmonic_layout = QVBoxLayout(harmonic_frame)

        harm_title = QLabel("Per-Harmonic Significance Check:")
        harm_font = harm_title.font()
        harm_font.setBold(True)
        harm_title.setFont(harm_font)
        harmonic_layout.addWidget(harm_title, alignment=Qt.AlignLeft)

        harm_row = QHBoxLayout()
        harm_row.setSpacing(5)

        harm_row.addWidget(QLabel("Metric:"))
        self.cb_metric = QComboBox()
        self.cb_metric.addItems(["SNR", "Z-Score"])
        harm_row.addWidget(self.cb_metric)

        harm_row.addWidget(QLabel("Mean Threshold:"))
        self.le_threshold = QLineEdit("1.96")
        harm_row.addWidget(self.le_threshold)

        self.btn_harmonic = QPushButton("Run Harmonic Check")
        harm_row.addWidget(self.btn_harmonic)

        harmonic_layout.addLayout(harm_row)
        main_layout.addWidget(harmonic_frame)

        # --------------------------------------------------------------
        # Results display
        # --------------------------------------------------------------
        self.results_text = QTextEdit()
        self.results_text.setReadOnly(True)
        self.results_text.setFontFamily("Courier New")
        self.results_text.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        main_layout.addWidget(self.results_text, 1)

    # ------------------------------------------------------------------
    # Signal connections
    # ------------------------------------------------------------------
    def _connect_signals(self) -> None:
        """Placeholder for signal wiring."""
        pass

