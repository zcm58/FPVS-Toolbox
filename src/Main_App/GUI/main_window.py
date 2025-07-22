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
    QFileDialog,
    QMessageBox,
    QButtonGroup,
    QDockWidget,
    QToolButton,
    QSizePolicy,
)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor
import logging
import pandas as pd
from pathlib import Path
import subprocess
import sys

from Main_App.GUI.menu_bar import build_menu_bar
from Main_App.GUI.settings_panel import SettingsDialog
from Main_App.settings_manager import SettingsManager

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Main application window implemented with PySide6."""

    def __init__(self) -> None:
        super().__init__()
        self.settings = SettingsManager()
        self.output_folder: str = ""
        self.data_paths: list[str] = []
        self.event_rows: list[QWidget] = []
        self._settings_dialog = None
        self.setWindowTitle("FPVS Toolbox")
        self.setMinimumSize(1024, 768)
        self._init_ui()
        self._init_sidebar()
        self.log("Welcome to the FPVS Toolbox!")
        self.log(
            f"Appearance Mode: {self.settings.get('appearance', 'mode', 'System')}"
        )

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
        self.lbl_debug.setVisible(self.settings.debug_enabled())
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
        self.cb_loreta = QCheckBox("Run LORETA during processing?", grp_proc)
        gl.addWidget(self.cb_loreta, 1, 0, 1, 3)
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        self.mode_group.addButton(self.rb_single)
        self.mode_group.addButton(self.rb_batch)
        self.rb_single.toggled.connect(
            lambda checked: checked and self._on_mode_changed("single")
        )
        self.rb_batch.toggled.connect(
            lambda checked: checked and self._on_mode_changed("batch")
        )
        main_layout.addWidget(grp_proc)

        # Load saved processing options
        mode = self.settings.get("processing", "mode", "batch").lower()
        if mode == "batch":
            self.rb_batch.setChecked(True)
        else:
            self.rb_single.setChecked(True)

        loreta_enabled = (
            self.settings.get("processing", "run_loreta", "False").lower() == "true"
        )
        self.cb_loreta.setChecked(loreta_enabled)

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
        # Populate defaults using stored settings with fallbacks from the legacy app
        pre_keys = [
            ("preprocessing", "low_pass", "0.1"),
            ("preprocessing", "high_pass", "50"),
            ("preprocessing", "downsample", "256"),
            ("preprocessing", "epoch_start", "-1"),
            ("preprocessing", "reject_thresh", "5"),
            ("preprocessing", "epoch_end", "125"),
            ("preprocessing", "ref_chan1", "EXG1"),
            ("preprocessing", "ref_chan2", "EXG2"),
            ("preprocessing", "max_idx_keep", "64"),
            ("preprocessing", "max_bad_chans", "10"),
        ]
        for edit, (sec, opt, fallback) in zip(self.pre_edits, pre_keys):
            edit.setText(self.settings.get(sec, opt, fallback))
        self.cb_save_fif = QCheckBox("Save Preprocessed .fif", grp_pre)
        self.cb_save_fif.setChecked(
            self.settings.get("paths", "save_fif", "False").lower() == "true"
        )
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

        # Populate saved event map rows
        saved_pairs = self.settings.get_event_pairs()
        if saved_pairs:
            for label, ident in saved_pairs:
                self.add_event_row(label, ident)
        else:
            self.add_event_row()

        # Log group
        grp_log = QGroupBox("Log", container)
        lay_log = QVBoxLayout(grp_log)
        self.text_log = QTextEdit(grp_log)
        self.text_log.setReadOnly(True)
        lay_log.addWidget(self.text_log)
        main_layout.addWidget(grp_log)

        # Finalize
        self.homeWidget = container
        self.setCentralWidget(container)
        self.setStatusBar(QStatusBar(self))

        # Connect toolbar buttons to methods
        self.btn_open_eeg.clicked.connect(self.select_eeg_file)
        self.btn_open_output.clicked.connect(self.select_output_folder)
        self.btn_start.clicked.connect(self.start_processing)
        self.btn_add_row.clicked.connect(lambda: self.add_event_row())
        self.btn_detect.clicked.connect(self.detect_trigger_ids)

        # Sync the select button label with the current mode
        self._update_select_button_text()

    # ------------------------------------------------------------------
    def _init_sidebar(self) -> None:
        """Create the dark sidebar with tool buttons."""
        sidebar = QWidget(self)
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(200)
        lay = QVBoxLayout(sidebar)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        def white_icon(name: str) -> QIcon:
            icon = QIcon.fromTheme(name)
            if icon.isNull():
                return icon
            pm = icon.pixmap(24, 24)
            tinted = QPixmap(pm.size())
            tinted.fill(Qt.transparent)
            painter = QPainter(tinted)
            painter.drawPixmap(0, 0, pm)
            painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
            painter.fillRect(tinted.rect(), QColor("white"))
            painter.end()
            return QIcon(tinted)

        def make_button(name: str, text: str, icon: str | None, slot) -> QToolButton:
            btn = QToolButton()
            btn.setObjectName(name)
            btn.setText(text)
            btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setIconSize(QSize(24, 24))
            btn.setStyleSheet("padding: 12px 16px; text-align: left;")
            if icon:
                btn.setIcon(white_icon(icon))
            if slot:
                btn.clicked.connect(slot)
            lay.addWidget(btn)
            return btn

        self.btn_home = make_button("btn_home", "Home", "go-home", lambda: None)
        self.btn_data = make_button("btn_data", "Data Analysis", "view-statistics", self.open_stats_analyzer)
        self.btn_graphs = make_button("btn_graphs", "Graphs", "view-media-visualization", self.open_plot_generator)
        self.btn_image = make_button("btn_image", "Image Resizer", "camera-photo", self.open_image_resizer)
        self.btn_epoch = make_button("btn_epoch", "Epoch Averaging", "view-refresh", self.open_advanced_analysis_window)

        lay.addStretch(1)

        self.btn_settings = make_button("btn_settings", "Settings", "settings", self.open_settings_window)
        self.btn_info = make_button("btn_info", "Information", None, self.show_relevant_publications)
        self.btn_help = make_button("btn_help", "Help", None, self.show_about_dialog)

        dock = QDockWidget("", self)
        dock.setWidget(sidebar)
        dock.setFeatures(QDockWidget.NoDockWidgetFeatures)
        self.addDockWidget(Qt.LeftDockWidgetArea, dock)

    # ------------------------------------------------------------------
    def log(self, message: str, level: int = logging.INFO) -> None:
        ts = pd.Timestamp.now().strftime("%H:%M:%S.%f")[:-3]
        formatted = f"{ts} [GUI]: {message}"
        if hasattr(self, "text_log") and self.text_log:
            self.text_log.append(formatted)
        logger.log(level, message)

    def debug(self, message: str) -> None:
        if logger.isEnabledFor(logging.DEBUG):
            self.log(f"[DEBUG] {message}", level=logging.DEBUG)

    # ------------------------------------------------------------------
    def _on_mode_changed(self, mode: str) -> None:
        self.settings.set("processing", "mode", mode)
        self.settings.save()
        self._update_select_button_text()

    def _update_select_button_text(self) -> None:
        """Update the label of the EEG selection button based on the mode."""
        if self.rb_batch.isChecked():
            self.btn_open_eeg.setText("Select Input Folder…")
        else:
            self.btn_open_eeg.setText("Select .BDF File…")

    # ------------------------------------------------------------------
    def open_settings_window(self) -> None:
        if self._settings_dialog and self._settings_dialog.isVisible():
            self._settings_dialog.raise_()
            self._settings_dialog.activateWindow()
            return
        dlg = SettingsDialog(self.settings, self)
        self._settings_dialog = dlg
        dlg.exec()
        self.lbl_debug.setVisible(self.settings.debug_enabled())
        self._settings_dialog = None

    def check_for_updates(self) -> None:
        from Main_App import update_manager

        update_manager.check_for_updates_async(self, silent=False)

    def quit(self) -> None:
        self.close()

    def open_stats_analyzer(self) -> None:
        QMessageBox.information(
            self,
            "Stats Toolbox",
            "The statistics tool is not yet available in the Qt interface.",
        )

    def open_image_resizer(self) -> None:
        cmd = [sys.executable]
        if not getattr(sys, "frozen", False):
            cmd.append(str(Path(__file__).resolve().parents[2] / "main.py"))
        cmd.append("--run-image-resizer")
        subprocess.Popen(cmd, close_fds=True)

    def open_plot_generator(self) -> None:
        cmd = [sys.executable]
        if not getattr(sys, "frozen", False):
            cmd.append(str(Path(__file__).resolve().parents[2] / "main.py"))
        cmd.append("--run-plot-generator")
        subprocess.Popen(cmd, close_fds=True)

    def open_advanced_analysis_window(self) -> None:
        QMessageBox.information(
            self,
            "Advanced Analysis",
            "The advanced preprocessing tool is not yet available in the Qt interface.",
        )

    def show_relevant_publications(self) -> None:
        QMessageBox.information(
            self,
            "Relevant Publications",
            "This dialog is not yet implemented in the Qt interface.",
        )

    def show_about_dialog(self) -> None:
        from PySide6.QtWidgets import QMessageBox
        from config import FPVS_TOOLBOX_VERSION

        QMessageBox.information(
            self,
            "About FPVS ToolBox",
            f"Version: {FPVS_TOOLBOX_VERSION} was developed by Zack Murphy at Mississippi State University.",
        )

    # ------------------------------------------------------------------
    def select_eeg_file(self) -> None:  # pragma: no cover - GUI stub
        """Prompt the user to select a single .BDF file or an input folder."""
        if self.rb_batch.isChecked():
            folder = QFileDialog.getExistingDirectory(
                self,
                "Select Input Folder",
                self.settings.get("paths", "data_folder", ""),
            )
            if folder:
                bdf_files = sorted(Path(folder).glob("*.bdf"))
                if bdf_files:
                    self.data_paths = [str(p) for p in bdf_files]
                    self.log(
                        f"Selected folder: {folder}, Found {len(bdf_files)} '.bdf' file(s)."
                    )
                else:
                    self.log(f"No '.bdf' files found in {folder}.")
                    QMessageBox.warning(
                        self, "No Files Found", f"No '.bdf' files found in:\n{folder}"
                    )
            else:
                self.log("No folder selected.")
        else:
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                "Select EEG File",
                self.settings.get("paths", "data_folder", ""),
                "BDF Files (*.bdf);;All Files (*)",
            )
            if file_path:
                self.data_paths = [file_path]
                self.log(f"Selected file: {Path(file_path).name}")
            else:
                self.log("No file selected.")

    def select_output_folder(self) -> None:  # pragma: no cover - GUI stub
        folder = QFileDialog.getExistingDirectory(
            self, "Select Output Folder", self.output_folder or ""
        )
        if folder:
            self.output_folder = folder
            self.log(f"Output folder set: {folder}")

    def start_processing(self) -> None:  # pragma: no cover - GUI stub
        self.log("start_processing() stub")

    def detect_trigger_ids(self) -> None:  # pragma: no cover - GUI stub
        try:
            from Tools.Event_Map import event_map_utils

            pairs = event_map_utils.detect_trigger_ids(self.data_paths)
        except Exception as err:
            QMessageBox.warning(self, "Detection Failed", str(err))
            return

        added = 0
        for lbl, ident in pairs:
            self.add_event_row(str(lbl), str(ident))
            added += 1
        self.log(f"Detected and added {added} trigger ID(s)")

    def add_event_row(self, label: str = "", id: str = "") -> None:
        row = QWidget(self.event_container)
        hl = QHBoxLayout(row)
        le_label = QLineEdit(label, row)
        le_id = QLineEdit(id, row)
        btn_rm = QPushButton("✕", row)
        def _remove() -> None:
            row.setParent(None)
            self.log("Event map row removed.")
        btn_rm.clicked.connect(_remove)
        hl.addWidget(le_label)
        hl.addWidget(le_id)
        hl.addWidget(btn_rm)
        self.event_layout.addWidget(row)
        self.event_rows.append(row)
        self.log("Added event map row")


def main() -> None:
    app = QApplication([])
    win = MainWindow()
    win.show()
    app.exec()


if __name__ == "__main__":
    main()
