from PySide6.QtWidgets import (
    QMainWindow, QWidget, QGroupBox, QListWidget, QPushButton,
    QHBoxLayout, QVBoxLayout, QPlainTextEdit, QSizePolicy,
)
from PySide6.QtGui import QAction  # noqa: F401
import os  # noqa: F401

# Import legacy mixins but do NOT alter those files:
from Tools.Average_Preprocessing.Legacy.advanced_analysis_file_ops import (
    AdvancedAnalysisFileOpsMixin,
)
from Tools.Average_Preprocessing.Legacy.advanced_analysis_group_ops import (
    AdvancedAnalysisGroupOpsMixin,
)
from Tools.Average_Preprocessing.Legacy.advanced_analysis_processing import (
    AdvancedAnalysisProcessingMixin,
)
from Tools.Average_Preprocessing.Legacy.advanced_analysis_post import (
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
        self._build_ui()

    def _build_ui(self):
        central = QWidget()
        main_h = QHBoxLayout(central)

        # — Left Panel —
        left_v = QVBoxLayout()
        # Source EEG Files group
        src_gb = QGroupBox("Source EEG Files")
        src_l = QVBoxLayout(src_gb)
        self.src_list = QListWidget()
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
        right_v.addWidget(map_gb)

        main_h.addLayout(left_v)
        main_h.addLayout(right_v)

        # — Bottom Log & Buttons —
        log_edit = QPlainTextEdit()
        log_edit.setReadOnly(True)
        btn_h3 = QHBoxLayout()
        self.btn_start = QPushButton("Start Advanced Processing")
        self.btn_stop = QPushButton("Stop")
        self.btn_clear = QPushButton("Clear Log")
        self.btn_close = QPushButton("Close")
        btn_h3.addWidget(self.btn_start)
        btn_h3.addWidget(self.btn_stop)
        btn_h3.addStretch(1)
        btn_h3.addWidget(self.btn_clear)
        btn_h3.addWidget(self.btn_close)

        # assemble everything
        master_v = QVBoxLayout()
        master_v.addLayout(main_h)
        master_v.addWidget(log_edit)
        master_v.addLayout(btn_h3)

        central.setLayout(master_v)
        self.setCentralWidget(central)

        # — Hook up signals to imported legacy functions (slots left for you) —
        # self.btn_add.clicked.connect(add_files)
        # self.btn_remove.clicked.connect(remove_selected)
        # self.btn_new.clicked.connect(create_group)
        # self.btn_rename.clicked.connect(rename_group)
        # self.btn_del.clicked.connect(delete_group)
        # self.btn_start.clicked.connect(start_processing)
        # self.btn_stop.clicked.connect(stop_processing)
        # self.btn_clear.clicked.connect(clear_log)
