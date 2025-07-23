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
    QButtonGroup,
    QDockWidget,
    QToolButton,
    QSizePolicy,
    QProgressBar,
    QStyle,
    QFrame,
    QMenu,
)
from PySide6.QtWidgets import QInputDialog, QMessageBox
from PySide6.QtCore import Qt, QSize, QPropertyAnimation, QObject, Signal
from PySide6.QtCore import QSettings
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QAction
import logging
import pandas as pd
from pathlib import Path
import subprocess
import sys
from .menu_bar import build_menu_bar
from .settings_panel import SettingsDialog
from Main_App.Legacy_App.settings_manager import SettingsManager
from Main_App.PySide6_App.Backend import Project
from Main_App.Legacy_App.load_utils import load_eeg_file
from Main_App.Legacy_App.app_logic import preprocess_raw
from Main_App.Legacy_App.eeg_preprocessing import perform_preprocessing
from Main_App.PySide6_App.Backend.processing import process_data
from Main_App.Legacy_App.post_process import post_process
class Processor(QObject):
    """Minimal processing stub emitting progress updates."""

    progressChanged = Signal(int)

    def emit_progress(self, value: int) -> None:
        self.progressChanged.emit(value)

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
        self.processor = Processor()
        self.setWindowTitle("FPVS Toolbox")
        self.setMinimumSize(1024, 768)
        self.currentProject: Project | None = None
        self._init_ui()
        self._init_sidebar()

        settings = QSettings()
        settings.beginGroup("paths")
        saved_root = settings.value("projectsRoot", "", type=str)
        settings.endGroup()

        if saved_root and Path(saved_root).is_dir():
            self.projectsRoot = Path(saved_root)
        else:
            root = QFileDialog.getExistingDirectory(
                self, "Select Projects Root Folder", ""
            )
            if not root:
                QMessageBox.critical(
                    self,
                    "Projects Root Required",
                    "You must select a Projects Root folder to continue.",
                )
                sys.exit(1)
            self.projectsRoot = Path(root)
            settings.beginGroup("paths")
            settings.setValue("projectsRoot", str(self.projectsRoot))
            settings.endGroup()
            settings.sync()

        self._init_file_menu()
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
        self.lbl_debug = QLabel("DEBUG MODE ENABLED", self)
        self.lbl_debug.setStyleSheet("color: red;")
        self.lbl_debug.setVisible(self.settings.debug_enabled())
        toolbar.addWidget(self.lbl_debug)

        # Central container
        container = QWidget(self)
        main_layout = QVBoxLayout(container)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(12)

        header = QWidget(container)
        header.setStyleSheet("background-color: #2A2A2A; padding: 8px;")
        h_lay = QHBoxLayout(header)
        h_lay.setContentsMargins(0, 0, 0, 0)
        self.lbl_currentProject = QLabel("Current Project: None", header)
        self.lbl_currentProject.setStyleSheet("color: white; font-weight: bold;")
        h_lay.addWidget(self.lbl_currentProject)
        h_lay.addStretch(1)
        main_layout.addWidget(header)

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

        # Preprocessing parameters have moved to Settings. Show placeholder
        placeholder = QLabel("⚙️ Configure preprocessing in Settings", container)
        placeholder.setAlignment(Qt.AlignCenter)
        placeholder.setStyleSheet("color: #CCCCCC; font-style: italic;")
        main_layout.addWidget(placeholder)

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

        action_row = QHBoxLayout()
        action_row.setSpacing(0)
        self.btn_start = QPushButton("Start Processing", container)
        self.progress_bar = QProgressBar(container)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%p%")
        self.progress_bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.progress_bar.setStyleSheet(
            "QProgressBar::chunk {background-color: #0BBF00;}"
        )
        action_row.addWidget(self.btn_start)
        action_row.addSpacing(16)
        action_row.addWidget(self.progress_bar)
        main_layout.addLayout(action_row)
        self._progress_anim = QPropertyAnimation(self.progress_bar, b"value")
        self._progress_anim.setDuration(200)
        self._progress_anim.valueChanged.connect(self.progress_bar.setValue)
        self.processor.progressChanged.connect(self._animate_progress_to)

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

        def make_button(name: str, text: str, icon: QIcon | str | None, slot) -> QToolButton:
            btn = QToolButton()
            btn.setObjectName(name)
            btn.setText(text)
            btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setIconSize(QSize(24, 24))
            btn.setStyleSheet("padding: 12px 16px; text-align: left;")
            if icon:
                if isinstance(icon, QIcon):
                    btn.setIcon(icon)
                else:
                    btn.setIcon(white_icon(icon))
            if slot:
                btn.clicked.connect(slot)
            lay.addWidget(btn)
            return btn

        self.btn_home = make_button("btn_home", "Home", "go-home", lambda: None)
        self.btn_data = make_button(
            "btn_data",
            "Statistical Analysis",
            QApplication.instance().style().standardIcon(QStyle.SP_ComputerIcon),
            self.open_stats_analyzer,
        )
        self.btn_graphs = make_button(
            "btn_graphs",
            "SNR Plots",
            QIcon.fromTheme("view-bar-chart"),  # TODO: supply bar-chart icon if missing
            self.open_plot_generator,
        )
        self.btn_image = make_button("btn_image", "Image Resizer", "camera-photo", self.open_image_resizer)
        self.btn_epoch = make_button("btn_epoch", "Epoch Averaging", "view-refresh", self.open_advanced_analysis_window)
        divider = QFrame()
        divider.setFrameShape(QFrame.HLine)
        divider.setFixedHeight(1)
        divider.setStyleSheet("background:#444;")
        lay.addWidget(divider)

        lay.addStretch(1)

        self.btn_settings = make_button("btn_settings", "Settings", "settings", self.open_settings_window)
        self.btn_info = make_button("btn_info", "Information", None, self.show_relevant_publications)
        self.btn_help = make_button("btn_help", "Help", None, self.show_about_dialog)

        dock = QDockWidget("", self)
        dock.setWidget(sidebar)
        dock.setFeatures(QDockWidget.NoDockWidgetFeatures)
        self.addDockWidget(Qt.LeftDockWidgetArea, dock)

    # ------------------------------------------------------------------
    def _init_file_menu(self) -> None:
        """Configure the File menu with project actions."""
        menu_bar = self.menuBar()
        if not menu_bar:
            return

        file_menu = menu_bar.findChild(QMenu, "fileMenu")
        if file_menu is None:
            return

        file_menu.clear()

        action_new = QAction("New Project…", self)
        action_new.triggered.connect(self.new_project)
        file_menu.addAction(action_new)

        action_open = QAction("Open Existing Project…", self)
        action_open.triggered.connect(self.open_existing_project)
        file_menu.addAction(action_open)
        file_menu.addSeparator()

        action_settings = QAction("Settings", self)
        action_settings.triggered.connect(self.open_settings_window)
        file_menu.addAction(action_settings)

        action_check = QAction("Check for Updates", self)
        action_check.triggered.connect(self.check_for_updates)
        file_menu.addAction(action_check)

        action_save = QAction("Save Project Settings", self)
        action_save.triggered.connect(self.saveProjectSettings)
        self.exit_action = QAction("Exit", self)
        self.exit_action.triggered.connect(self.quit)

        file_menu.addAction(action_save)
        file_menu.addAction(self.exit_action)

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
        if not hasattr(self, "btn_open_eeg"):
            return
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
        from Main_App.Legacy_App import update_manager

        update_manager.check_for_updates_async(self, silent=False)

    def quit(self) -> None:
        self.close()

    # ------------------------------------------------------------------
    def new_project(self) -> None:
        # 1) Ask for project name
        name, ok = QInputDialog.getText(
            self, "Project Name", "Enter a name for this new project:"
        )
        if not ok or not name.strip():
            return

        # 2) Ask for input folder of .BDF files
        input_folder = QFileDialog.getExistingDirectory(
            self, "Select Input Folder (BDF files)", ""
        )
        if not input_folder:
            return

        # 3) Create project directory under Projects Root
        project_dir = self.projectsRoot / name.strip()
        project_dir.mkdir(parents=True, exist_ok=True)

        # 4) Load (and scaffold) manifest via Project.load()
        project = Project.load(project_dir)
        project.name = name.strip()
        project.input_folder = input_folder
        project.save()

        # 5) Store and apply
        self.currentProject = project
        self.loadProject(project)

    def open_existing_project(self) -> None:
        candidates = [
            d for d in self.projectsRoot.iterdir() if (d / "project.json").exists()
        ]
        if not candidates:
            QMessageBox.information(
                self, "No Projects", "No projects found under your Projects Root."
            )
            return

        labels = []
        label_to_path = {}
        for d in candidates:
            proj = Project.load(d)
            label = proj.name
            labels.append(label)
            label_to_path[label] = d

        choice, ok = QInputDialog.getItem(
            self, "Open Project", "Select a project:", labels, editable=False
        )
        if not ok or choice not in label_to_path:
            return

        project = Project.load(label_to_path[choice])
        self.currentProject = project
        self.loadProject(project)

    def openProjectPath(self, folder: str) -> None:
        project = Project.load(folder)
        self.currentProject = project
        self.loadProject(project)

        settings = QSettings()
        recent = settings.value("recentProjects", [], type=list)
        if folder in recent:
            recent.remove(folder)
        recent.insert(0, folder)
        settings.setValue("recentProjects", recent)
        settings.sync()

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

    def start_processing(self) -> None:
        """Run the full legacy pipeline, ensuring load_eeg_file() is called with individual .bdf file paths."""
        try:
            input_dir = Path(self.currentProject.input_folder)
            run_loreta = self.cb_loreta.isChecked()

            if self.rb_batch.isChecked():
                bdf_files = list(input_dir.glob("*.bdf"))
                if not bdf_files:
                    raise FileNotFoundError(f"No .bdf files in {input_dir}")
            else:
                file_path, _ = QFileDialog.getOpenFileName(
                    self,
                    "Select .BDF File",
                    str(input_dir),
                    "BDF Files (*.bdf)",
                )
                if not file_path:
                    self.log("No file selected, aborting.")
                    return
                bdf_files = [Path(file_path)]

            for fp in bdf_files:
                self.log(f"Loading EEG file: {fp.name}")
                raw = load_eeg_file(str(fp))

                self.log("Preprocessing raw data")
                processed = preprocess_raw(raw)
                processed = perform_preprocessing(processed)

                out_dir = str(
                    self.currentProject.project_root
                    / self.currentProject.subfolders["excel"]
                )
                self.log(f"Running main processing (run_loreta={run_loreta})")
                result = process_data(processed, out_dir, run_loreta)

                self.log("Post-processing results")
                post_process(result)

            self._animate_progress_to(100)
            self.log("Processing complete")

        except Exception as e:
            self.log(f"Processing failed: {e}", level=logging.ERROR)
            QMessageBox.critical(self, "Processing Error", str(e))

    def _animate_progress_to(self, value: int) -> None:
        """Animate the progress bar smoothly to the target value."""
        self._progress_anim.stop()
        self._progress_anim.setStartValue(self.progress_bar.value())
        self._progress_anim.setEndValue(value)
        self._progress_anim.start()

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

    # ------------------------------------------------------------------
    def loadProject(self, project: Project) -> None:  # pragma: no cover - GUI stub
        """Apply project settings to the UI."""
        self.currentProject = project
        # Update header
        self.lbl_currentProject.setText(f"Current Project: {project.name}")

        self.settings.set("paths", "data_folder", str(project.input_folder))
        self.settings.save()

        # Processing Options
        mode = project.options.get("mode", "batch").lower()
        self.rb_single.setChecked(mode == "single")
        self.rb_batch.setChecked(mode == "batch")
        self.cb_loreta.setChecked(bool(project.options.get("run_loreta", False)))

        # Event Map
        for row in list(self.event_rows):
            row.setParent(None)
        self.event_rows.clear()

        if project.event_map:
            for label, ident in project.event_map.items():
                self.add_event_row(str(label), str(ident))
        else:
            self.add_event_row()

        self.log(f"Loaded project: {project.name}")

    def saveProjectSettings(self) -> None:
        """Collect current UI settings and save them to ``project.json``."""
        if not self.currentProject:
            QMessageBox.warning(self, "No Project", "Please open or create a project first.")
            return

        self.currentProject.options["mode"] = "single" if self.rb_single.isChecked() else "batch"
        self.currentProject.options["run_loreta"] = self.cb_loreta.isChecked()

        mapping: dict[str, int] = {}
        for row in self.event_rows:
            edits = row.findChildren(QLineEdit)
            if len(edits) >= 2:
                label = edits[0].text()
                ident = edits[1].text()
                if label and ident.isdigit():
                    mapping[label] = int(ident)
        self.currentProject.event_map = mapping

        self.currentProject.save()
        QMessageBox.information(self, "Project Saved", "All settings written to project.json.")

def main() -> None:
    app = QApplication([])
    win = MainWindow()
    win.show()
    app.exec()
if __name__ == "__main__":
    main()
