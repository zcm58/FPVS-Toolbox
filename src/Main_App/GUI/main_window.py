from __future__ import annotations

from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QToolBar,
    QPushButton,
    QLabel,
    QGroupBox,
    QGridLayout,
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
    QRadioButton,
    QCheckBox,
    QLineEdit,
    QScrollArea,
    QTextEdit,
    QStatusBar,
)
from PySide6.QtCore import Qt

from Main_App.GUI.menu_bar import build_menu_bar


class MainWindow(QMainWindow):
    """Main application window implemented with PySide6."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("FPVS Toolbox")
        self.setMinimumSize(1024, 768)
        self._init_ui()

    # ------------------------------------------------------------------
    def _init_ui(self) -> None:
        # Menu bar
        menu = build_menu_bar(self)
        self.setMenuBar(menu)

        # Top toolbar
        toolbar = QToolBar(self)
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.addToolBar(Qt.TopToolBarArea, toolbar)
        self.btn_open_eeg = QPushButton("Select EEG File…", self)
        self.btn_open_output = QPushButton("Select Output Folder…", self)
        self.btn_start = QPushButton("Start Processing", self)
        self.lbl_debug = QLabel("DEBUG MODE ENABLED", self)
        self.lbl_debug.setStyleSheet("color: red;")
        for w in (
            self.btn_open_eeg,
            self.btn_open_output,
            self.btn_start,
            self.lbl_debug,
        ):
            toolbar.addWidget(w)

        # Central container
        container = QWidget(self)
        main_layout = QVBoxLayout(container)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(12)

        # Processing Options group
        grp_proc = QGroupBox("Processing Options", container)
        gl = QGridLayout(grp_proc)
        gl.addWidget(QLabel("Mode:"), 0, 0)
        self.rb_single = QRadioButton("Single File", grp_proc)
        self.rb_batch = QRadioButton("Batch Folder", grp_proc)
        gl.addWidget(self.rb_single, 0, 1)
        gl.addWidget(self.rb_batch, 0, 2)
        gl.addWidget(QLabel("File Type:"), 1, 0)
        self.rb_bdf = QRadioButton(".BDF", grp_proc)
        self.rb_set = QRadioButton(".set", grp_proc)
        gl.addWidget(self.rb_bdf, 1, 1)
        gl.addWidget(self.rb_set, 1, 2)
        self.cb_loreta = QCheckBox("Run LORETA during processing?", grp_proc)
        gl.addWidget(self.cb_loreta, 2, 0, 1, 3)
        main_layout.addWidget(grp_proc)

        # Preprocessing Parameters group
        grp_pre = QGroupBox("Preprocessing Parameters", container)
        grid = QGridLayout(grp_pre)
        params = [
            "Low Pass (Hz):",
            "High Pass (Hz):",
            "Downsample (Hz):",
            "Epoch Start (s):",
            "Rejection Z-Thresh:",
            "Epoch End (s):",
            "Ref Chan 1:",
            "Ref Chan 2:",
            "Max Chan Idx Keep:",
            "Max Bad Chans (Flag):",
        ]
        self.pre_edits: list[QLineEdit] = []
        for i, label_text in enumerate(params):
            row, col = divmod(i, 2)
            lbl = QLabel(label_text, grp_pre)
            edit = QLineEdit(grp_pre)
            self.pre_edits.append(edit)
            grid.addWidget(lbl, row, col * 2)
            grid.addWidget(edit, row, col * 2 + 1)
        self.cb_save_fif = QCheckBox("Save Preprocessed .fif", grp_pre)
        grid.addWidget(self.cb_save_fif, 5, 0, 1, 4)
        main_layout.addWidget(grp_pre)

        # Event Map group
        grp_event = QGroupBox(
            "Event Map (Condition Label → Numerical ID)", container
        )
        vlay = QVBoxLayout(grp_event)
        scroll = QScrollArea(grp_event)
        scroll.setWidgetResizable(True)
        self.event_container = QWidget()
        self.event_layout = QVBoxLayout(self.event_container)
        scroll.setWidget(self.event_container)
        vlay.addWidget(scroll)
        btns = QHBoxLayout()
        self.btn_detect = QPushButton("Detect Trigger IDs", grp_event)
        self.btn_add_row = QPushButton("+ Add Condition", grp_event)
        btns.addWidget(self.btn_detect)
        btns.addWidget(self.btn_add_row)
        vlay.addLayout(btns)
        main_layout.addWidget(grp_event)

        # Log group
        grp_log = QGroupBox("Log", container)
        lay_log = QVBoxLayout(grp_log)
        self.text_log = QTextEdit(grp_log)
        self.text_log.setReadOnly(True)
        lay_log.addWidget(self.text_log)
        main_layout.addWidget(grp_log)

        # Finalize
        self.setCentralWidget(container)
        self.setStatusBar(QStatusBar(self))

        # Connect toolbar buttons to methods
        self.btn_open_eeg.clicked.connect(self.select_eeg_file)
        self.btn_open_output.clicked.connect(self.select_output_folder)
        self.btn_start.clicked.connect(self.start_processing)
        self.btn_add_row.clicked.connect(lambda: self.add_event_row())

    # ------------------------------------------------------------------
    def select_eeg_file(self) -> None:  # pragma: no cover - GUI stub
        print("select_eeg_file() stub")

    def select_output_folder(self) -> None:  # pragma: no cover - GUI stub
        print("select_output_folder() stub")

    def start_processing(self) -> None:  # pragma: no cover - GUI stub
        print("start_processing() stub")

    def add_event_row(self, label: str = "", id: str = "") -> None:
        row = QWidget(self.event_container)
        hl = QHBoxLayout(row)
        le_label = QLineEdit(label, row)
        le_id = QLineEdit(id, row)
        btn_rm = QPushButton("✕", row)
        btn_rm.clicked.connect(lambda _, r=row: r.setParent(None))
        hl.addWidget(le_label)
        hl.addWidget(le_id)
        hl.addWidget(btn_rm)
        self.event_layout.addWidget(row)


def main() -> None:
    app = QApplication([])
    win = MainWindow()
    win.show()
    app.exec()


if __name__ == "__main__":
    main()
