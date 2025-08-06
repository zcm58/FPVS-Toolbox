from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QGroupBox,
    QListWidget,
    QPushButton,
    QHBoxLayout,
    QVBoxLayout,
    QPlainTextEdit,
    QSizePolicy,
    QRadioButton,
    QButtonGroup,
    QLabel,
    QMessageBox,
)
from PySide6.QtGui import QCloseEvent
import os

# --- Ported Mixin Imports ---
# (Assuming they are in the same directory or Python path)
from .advanced_analysis_file_ops import AdvancedAnalysisFileOpsMixin
from .advanced_analysis_group_ops import AdvancedAnalysisGroupOpsMixin
from .advanced_analysis_processing import AdvancedAnalysisProcessingMixin
from .advanced_analysis_post import AdvancedAnalysisPostMixin


class AdvancedAveragingWindow(
    QMainWindow,
    AdvancedAnalysisFileOpsMixin,
    AdvancedAnalysisGroupOpsMixin,
    AdvancedAnalysisProcessingMixin,
    AdvancedAnalysisPostMixin,
):
    def __init__(
        self,
        parent=None,
        input_dir: str | None = None,
        output_dir: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Advanced Averaging Analysis")

        # Store project paths
        self.project_input_folder = input_dir
        self.project_output_folder = output_dir

        # State
        self.source_eeg_files: list[str] = []
        self.defined_groups: list[dict] = []
        self.selected_group_index: int | None = None
        self.processing_thread = None
        self.worker = None

        self._build_ui()
        self._auto_load_source_files()

    def _build_ui(self):
        central = QWidget()
        main_h = QHBoxLayout()

        # — Left Panel —
        left_v = QVBoxLayout()
        src_gb = QGroupBox("Source EEG Files")
        src_l = QVBoxLayout(src_gb)
        self.source_files_listbox = QListWidget()
        btn_h1 = QHBoxLayout()
        self.btn_add = QPushButton("Add Files…")
        self.btn_remove = QPushButton("Remove Selected")
        btn_h1.addWidget(self.btn_add)
        btn_h1.addWidget(self.btn_remove)
        src_l.addWidget(self.source_files_listbox)
        src_l.addLayout(btn_h1)

        grp_gb = QGroupBox("Defined Averaging Groups")
        grp_l = QVBoxLayout(grp_gb)
        self.groups_listbox = QListWidget()
        self.grp_list = self.groups_listbox
        btn_h2 = QHBoxLayout()
        self.btn_new = QPushButton("Create New Group")
        self.btn_rename = QPushButton("Rename Group")
        self.btn_del = QPushButton("Delete Group")
        btn_h2.addWidget(self.btn_new)
        btn_h2.addWidget(self.btn_rename)
        btn_h2.addWidget(self.btn_del)
        grp_l.addWidget(self.groups_listbox)
        grp_l.addLayout(btn_h2)

        left_v.addWidget(src_gb)
        left_v.addWidget(grp_gb)

        # — Right Panel —
        right_v = QVBoxLayout()
        info_label = QLabel(
            "This tool should be used if you have multiple FPVS Conditions "
            "that are expected to elicit a similar neural response in the participant. "
            "This tool will generate a pooled average of each oddball epoch from all "
            "of the conditions that you choose to average together BEFORE calculating "
            "FFT, SNR, BCA, or Z-scores."
        )
        info_label.setWordWrap(True)
        info_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        right_v.addWidget(info_label)

        avg_label = QLabel("Averaging Method:")
        right_v.addWidget(avg_label)
        radio_h = QHBoxLayout()
        self.radio_pool = QRadioButton("Pool Trials")
        self.radio_avgofavg = QRadioButton("Average of Averages")
        self.radio_pool.setChecked(True)
        self.radio_pool.setToolTip(
            "Combine all epochs from selected files and average them together."
        )
        self.radio_avgofavg.setToolTip(
            "Average each file separately, then average the results together."
        )
        radio_h.addWidget(self.radio_pool)
        radio_h.addWidget(self.radio_avgofavg)
        right_v.addLayout(radio_h)

        method_group = QButtonGroup(self)
        method_group.addButton(self.radio_pool)
        method_group.addButton(self.radio_avgofavg)

        main_h.addLayout(left_v)
        main_h.addLayout(right_v)

        master_v = QVBoxLayout()
        master_v.addLayout(main_h)

        # — Log pane —
        self.log_edit = QPlainTextEdit()
        self.log_edit.setReadOnly(True)
        master_v.addWidget(self.log_edit)

        # — Bottom control buttons —
        btn_controls = QHBoxLayout()
        self.btn_start = QPushButton("Start Advanced Processing")
        self.btn_stop = QPushButton("Stop")
        btn_controls.addWidget(self.btn_start)
        btn_controls.addWidget(self.btn_stop)
        btn_controls.addStretch(1)
        self.btn_clear = QPushButton("Clear Log")
        self.btn_close = QPushButton("Close")
        btn_controls.addWidget(self.btn_clear)
        btn_controls.addWidget(self.btn_close)
        master_v.addLayout(btn_controls)

        central.setLayout(master_v)
        self.setCentralWidget(central)

        # Connect button signals to the inherited legacy mixin methods
        self.btn_add.clicked.connect(self.add_source_files)
        self.btn_remove.clicked.connect(self.remove_source_files)
        self.btn_new.clicked.connect(self.create_new_group)
        self.btn_rename.clicked.connect(self.rename_selected_group)
        self.btn_del.clicked.connect(self.delete_selected_group)
        self.btn_start.clicked.connect(self.start_advanced_processing)
        self.btn_stop.clicked.connect(self.stop_processing)
        self.btn_clear.clicked.connect(self.clear_log)
        self.btn_close.clicked.connect(self.close)

    def closeEvent(self, event: QCloseEvent):
        """Overrides the default close event to check for running processes."""
        if self.processing_thread and self.processing_thread.isRunning():
            reply = QMessageBox.question(
                self,
                "Confirm Close",
                "Processing is ongoing. Are you sure you want to stop and close?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                self.stop_processing()
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()

    # ---- UI-Specific Helper Methods -------------------------------------
    def log(self, message: str) -> None:
        """Append a message to the log widget."""
        self.log_edit.appendPlainText(message)
        self.log_edit.verticalScrollBar().setValue(
            self.log_edit.verticalScrollBar().maximum()
        )

    def clear_log(self) -> None:
        """Clear all text from the log widget."""
        self.log_edit.clear()

    def save_groups_to_file(self) -> None:
        """Stubbed out: configuration saving is disabled in this UI."""
        return

    def _auto_load_source_files(self) -> None:
        """Scan project_input_folder for .bdf files and populate the list."""
        folder = self.project_input_folder
        if not folder or not os.path.isdir(folder):
            self.log("Project data folder not found.")
            return

        bdfs = sorted(
            f for f in os.listdir(folder)
            if f.lower().endswith(".bdf")
        )
        full_paths = [os.path.join(folder, f) for f in bdfs]
        self.source_eeg_files = full_paths
        self._update_source_files_listbox()
        self.log(f"Loaded {len(full_paths)} .bdf files from project.")
