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
    QScrollArea,
    QLabel,
)
from PySide6.QtGui import QAction  # noqa: F401
import os  # noqa: F401

from Tools.Average_Preprocessing.New_PySide6.advanced_analysis_file_ops import (
    AdvancedAnalysisFileOpsMixin,
)
from Tools.Average_Preprocessing.New_PySide6.advanced_analysis_group_ops import (
    AdvancedAnalysisGroupOpsMixin,
)
from Tools.Average_Preprocessing.New_PySide6.advanced_analysis_processing import (
    AdvancedAnalysisProcessingMixin,
)
from Tools.Average_Preprocessing.New_PySide6.advanced_analysis_post import (
    AdvancedAnalysisPostMixin,
)


class AdvancedAveragingWindow(
    QMainWindow,
    AdvancedAnalysisFileOpsMixin,
    AdvancedAnalysisGroupOpsMixin,
    AdvancedAnalysisProcessingMixin,
    AdvancedAnalysisPostMixin,
):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Advanced Averaging Analysis")
        # Attributes expected by legacy routines
        self.source_eeg_files: list[str] = []
        self.defined_groups: list[dict] = []
        self._build_ui()
        self.selected_group_index: int | None = None
        self._update_start_processing_button_state()

    def _build_ui(self):
        central = QWidget()
        main_h = QHBoxLayout()

        # — Left Panel —
        left_v = QVBoxLayout()
        # Source EEG Files group
        src_gb = QGroupBox("Source EEG Files")
        src_l = QVBoxLayout(src_gb)
        self.src_list = QListWidget()
        self.source_files_listbox = self.src_list
        btn_h1 = QHBoxLayout()
        self.btn_add = QPushButton("Add Files…")
        self.btn_remove = QPushButton("Remove Selected")
        btn_h1.addWidget(self.btn_add)
        btn_h1.addWidget(self.btn_remove)
        src_l.addWidget(self.src_list)
        src_l.addLayout(btn_h1)
        # Defined Averaging Groups group
        grp_gb = QGroupBox("Defined Averaging Groups")
        grp_l = QVBoxLayout(grp_gb)
        self.grp_list = QListWidget()
        self.groups_listbox = self.grp_list
        btn_h2 = QHBoxLayout()
        self.btn_new = QPushButton("Create New Group")
        self.btn_rename = QPushButton("Rename Group")
        self.btn_del = QPushButton("Delete Group")
        btn_h2.addWidget(self.btn_new)
        btn_h2.addWidget(self.btn_rename)
        btn_h2.addWidget(self.btn_del)
        grp_l.addWidget(self.grp_list)
        grp_l.addLayout(btn_h2)

        left_v.addWidget(src_gb)
        left_v.addWidget(grp_gb)

        # — Right Panel —
        right_v = QVBoxLayout()
        cfg_gb = QGroupBox("Group Configuration")
        map_gb = QGroupBox("Condition Mapping for Selected Group")
        cfg_gb.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        map_gb.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        right_v.addWidget(cfg_gb)

        # — Condition Mapping Panel —
        mapping_layout = QVBoxLayout(map_gb)

        # 1) Scrollable mapping area
        self.mapping_area = QScrollArea()
        self.mapping_area.setWidgetResizable(True)
        empty_container = QWidget()
        empty_container.setLayout(QVBoxLayout())
        self.mapping_area.setWidget(empty_container)
        mapping_layout.addWidget(self.mapping_area)

        # 2) Averaging Method radio buttons
        avg_label = QLabel("Averaging Method:")
        mapping_layout.addWidget(avg_label)
        radio_h = QHBoxLayout()
        self.radio_pool = QRadioButton("Pool Trials")
        self.radio_avgofavg = QRadioButton("Average of Averages")
        self.radio_pool.setChecked(True)
        radio_h.addWidget(self.radio_pool)
        radio_h.addWidget(self.radio_avgofavg)
        mapping_layout.addLayout(radio_h)

        # Make the two radios exclusive (optional)
        method_group = QButtonGroup(self)
        method_group.addButton(self.radio_pool)
        method_group.addButton(self.radio_avgofavg)

        # 3) Save Group Configuration button
        self.btn_save_cfg = QPushButton("Save Group Configuration")
        mapping_layout.addWidget(self.btn_save_cfg)

        right_v.addWidget(map_gb)

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
        self.btn_stop  = QPushButton("Stop")
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

        # Connect button signals to handlers
        self.btn_add.clicked.connect(self.add_source_files)
        self.btn_remove.clicked.connect(self.remove_source_files)
        self.btn_new.clicked.connect(self.create_new_group)
        self.btn_rename.clicked.connect(self.rename_selected_group)
        self.btn_del.clicked.connect(self.delete_selected_group)
        self.grp_list.currentRowChanged.connect(self.on_group_select)
        self.btn_start.clicked.connect(self.start_advanced_processing)
        self.btn_stop.clicked.connect(self.stop_processing)
        self.btn_clear.clicked.connect(self.clear_log)
        self.btn_close.clicked.connect(self.close)

    # ---- Button handlers -------------------------------------------------
    def log(self, message: str) -> None:
        """Append a message to the log widget."""
        self.log_edit.appendPlainText(message)
        self.log_edit.verticalScrollBar().setValue(
            self.log_edit.verticalScrollBar().maximum()
        )

    def clear_log(self) -> None:
        """Clear all text from the log widget."""
        self.log_edit.clear()
