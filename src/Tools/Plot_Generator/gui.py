"""GUI elements for the plot generator."""
from __future__ import annotations

import os
import json
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QThread, QPropertyAnimation, Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QComboBox,
    QTextEdit,
    QProgressBar,
    QSplitter,
    QToolButton,
    QWidget,
    QMenuBar,
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QDoubleSpinBox,
    QCheckBox,
    QStyle,
    QSizePolicy,
    QListWidget,
    QListWidgetItem,
)
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import QColorDialog


from Main_App import SettingsManager
from Main_App.PySide6_App.Backend.project import (
    EXCEL_SUBFOLDER_NAME,
    SNR_SUBFOLDER_NAME,
)
from Tools.Stats.Legacy.stats_helpers import load_rois_from_settings
from Tools.Stats.Legacy.stats_analysis import ALL_ROIS_OPTION
from Tools.Plot_Generator.manifest_utils import (
    extract_group_names,
    has_multi_groups,
    load_manifest_for_excel_root,
    normalize_participants_map,
)
from Tools.Plot_Generator.plot_settings import PlotSettingsManager
from .worker import _Worker

def _auto_detect_project_dir() -> str:
    """Return folder containing ``project.json`` or CWD if not found."""
    path = Path.cwd()
    while not (path / "project.json").is_file():
        if path.parent == path:
            return str(Path.cwd())
        path = path.parent
    return str(path)

ALL_CONDITIONS_OPTION = "All Conditions"


def _auto_detect_project_dir() -> Path:
    """Return the nearest ancestor folder containing ``project.json``."""
    path = Path.cwd()
    while not (path / "project.json").is_file():
        if path.parent == path:
            return Path.cwd()
        path = path.parent
    return path


def _load_manifest(root: Path) -> tuple[str | None, dict[str, str]]:
    manifest = root / "project.json"
    if not manifest.is_file():
        return None, {}
    try:
        cfg = json.loads(manifest.read_text(encoding="utf-8"))
    except Exception:
        return None, {}
    results_folder = cfg.get("results_folder")
    if not isinstance(results_folder, str):
        results_folder = None
    subfolders = cfg.get("subfolders", {})
    if not isinstance(subfolders, dict):
        subfolders = {}
    normalized: dict[str, str] = {}
    for key, value in subfolders.items():
        if isinstance(value, str):
            normalized[key] = value
    return results_folder, normalized


def _resolve_results_root(project_root: Path, results_folder: str | None) -> Path:
    if results_folder:
        folder = Path(results_folder)
        if not folder.is_absolute():
            folder = project_root / folder
    else:
        folder = project_root
    return folder.resolve()


def _resolve_project_subfolder(
    project_root: Path,
    results_folder: str | None,
    subfolders: dict[str, str],
    key: str,
    default_name: str,
) -> Path:
    name = subfolders.get(key, default_name)
    candidate = Path(name)
    if candidate.is_absolute():
        return candidate.resolve()
    return (_resolve_results_root(project_root, results_folder) / candidate).resolve()


def _project_paths(parent: QWidget | None, project_dir: str | None) -> tuple[str | None, str | None]:
    """Return Excel and SNR plot folders for the given or detected project."""
    if project_dir and os.path.isdir(project_dir):
        root = Path(project_dir)
    else:
        proj = getattr(parent, "currentProject", None)
        if proj and hasattr(proj, "project_root"):
            root = Path(proj.project_root)
        else:
            root = _auto_detect_project_dir()

    results_folder, subfolders = _load_manifest(root)
    if results_folder is not None or subfolders:
        try:
            excel_path = _resolve_project_subfolder(root, results_folder, subfolders, "excel", EXCEL_SUBFOLDER_NAME)
            snr_path = _resolve_project_subfolder(root, results_folder, subfolders, "snr", SNR_SUBFOLDER_NAME)
            return str(excel_path), str(snr_path)
        except Exception:
            pass
    fallback_root = root if isinstance(root, Path) else Path(root)
    return str((fallback_root / EXCEL_SUBFOLDER_NAME).resolve()), str((fallback_root / SNR_SUBFOLDER_NAME).resolve())

class _SettingsDialog(QDialog):
    """Dialog for configuring plot options."""

    def __init__(self, parent: QWidget, color_a: str, color_b: str) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        layout = QVBoxLayout(self)

        row_a = QHBoxLayout()
        row_a.addWidget(QLabel("Condition A Color:"))
        self.color_a = color_a
        pick_a = QPushButton("Custom…")
        pick_a.clicked.connect(lambda: self._choose_custom("a"))
        row_a.addWidget(pick_a)
        layout.addLayout(row_a)

        row_b = QHBoxLayout()
        row_b.addWidget(QLabel("Condition B Color:"))
        self.color_b = color_b
        pick_b = QPushButton("Custom…")
        pick_b.clicked.connect(lambda: self._choose_custom("b"))
        row_b.addWidget(pick_b)
        layout.addLayout(row_b)

        btns = QHBoxLayout()
        ok = QPushButton("OK")
        ok.clicked.connect(self.accept)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        btns.addWidget(ok)
        btns.addWidget(cancel)
        layout.addLayout(btns)

    def _choose_custom(self, which: str) -> None:
        init = self.color_a if which == "a" else self.color_b
        color = QColorDialog.getColor(QColor(init), self)
        if color.isValid():
            if which == "a":
                self.color_a = color.name()
            else:
                self.color_b = color.name()

    def selected_colors(self) -> tuple[str, str]:
        return self.color_a.lower(), self.color_b.lower()

class PlotGeneratorWindow(QWidget):
    """Main window for generating plots."""

    def __init__(
        self,
        parent: QWidget | None = None,
        project_dir: str | None = None,
        plot_mgr: PlotSettingsManager | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Generate SNR Plots")
        self.roi_map = load_rois_from_settings()

        mgr = SettingsManager()
        self.plot_mgr = plot_mgr or PlotSettingsManager()
        default_in = self.plot_mgr.get("paths", "input_folder", "")
        default_out = self.plot_mgr.get("paths", "output_folder", "")
        self.stem_color = self.plot_mgr.get_stem_color()
        self.stem_color_b = self.plot_mgr.get_second_color()
        self.scalp_min, self.scalp_max = self.plot_mgr.get_scalp_bounds()
        self.include_scalp_maps = self.plot_mgr.include_scalp_maps()
        self.scalp_title_a_template = self.plot_mgr.get_scalp_title_a_template()
        self.scalp_title_b_template = self.plot_mgr.get_scalp_title_b_template()


        project_dir_path: Path | None = None
        proj = getattr(parent, "currentProject", None)
        if proj and hasattr(proj, "project_root"):
            project_dir_path = Path(proj.project_root)
        else:
            env_dir = os.environ.get("FPVS_PROJECT_ROOT")
            if env_dir and Path(env_dir).is_dir():
                project_dir_path = Path(env_dir)
            else:
                cand = _auto_detect_project_dir()
                if (cand / "project.json").is_file():
                    project_dir_path = cand

        if project_dir_path is not None:
            try:
                results_folder, subfolders = _load_manifest(project_dir_path)
                default_in = str(
                    _resolve_project_subfolder(
                        project_dir_path,
                        results_folder,
                        subfolders,
                        "excel",
                        EXCEL_SUBFOLDER_NAME,
                    )
                )
                default_out = str(
                    _resolve_project_subfolder(
                        project_dir_path,
                        results_folder,
                        subfolders,
                        "snr",
                        SNR_SUBFOLDER_NAME,
                    )
                )
            except Exception:
                pass
        else:
            main_default = mgr.get("paths", "output_folder", "")
            if not default_in:
                default_in = main_default
            if not default_out:
                default_out = main_default

        self._defaults = {
            "title_snr": "SNR Plot",
            "xlabel": "Frequency (Hz)",
            "ylabel_snr": "SNR",
            "x_min": "0.0",
            "x_max": "10.0",
            "y_min_snr": "0.0",
            "y_max_snr": "3.0",
            "input_folder": default_in,
            "output_folder": default_out,
            "include_scalp_maps": self.include_scalp_maps,
            "scalp_min": self.scalp_min,
            "scalp_max": self.scalp_max,
            "scalp_title_a_template": self.scalp_title_a_template,
            "scalp_title_b_template": self.scalp_title_b_template,
        }
        self._orig_defaults = self._defaults.copy()
        self._conditions_queue: list[str] = []
        self._total_conditions = 0
        self._current_condition = 0

        self._all_conditions = False

        self._subject_groups_map: dict[str, str] = {}
        self._available_groups: list[str] = []
        self._has_multi_groups = False


        self._build_ui()
        self._overlay_width_anim = QPropertyAnimation(self.overlay_container, b"maximumWidth")
        self._overlay_width_anim.setDuration(200)
        self._overlay_opacity_anim = QPropertyAnimation(self.overlay_container, b"windowOpacity")
        self._overlay_opacity_anim.setDuration(200)
        self.overlay_container.setMaximumWidth(0)
        self.overlay_container.setWindowOpacity(0.0)
        # Prepare animation for smooth progress updates
        self._progress_anim = QPropertyAnimation(self.progress_bar, b"value")
        self._progress_anim.setDuration(200)
        if default_in:
            self.folder_edit.setText(default_in)
            self._populate_conditions(default_in)
        if default_out:
            self.out_edit.setText(default_out)

        self._thread: QThread | None = None
        self._worker: _Worker | None = None
        self._gen_params: (
            tuple[
                str,
                str,
                float,
                float,
                float,
                float,
                dict,
                bool,
                float,
                float,
                str,
                str,
            ]
            | None
        ) = None

    def _bold_label(self, text: str) -> QLabel:
        label = QLabel(text)
        font = label.font()
        font.setBold(True)
        label.setFont(font)
        return label

    def _toggle_scalp_controls(self, checked: bool) -> None:
        self.include_scalp_maps = checked
        self.scalp_min_spin.setEnabled(checked)
        self.scalp_max_spin.setEnabled(checked)
        self.scalp_title_a_edit.setEnabled(checked)
        self._update_scalp_title_b_visibility()

    def _update_scalp_title_b_visibility(self) -> None:
        show_b = self.include_scalp_maps and self.overlay_check.isChecked()
        self.scalp_title_b_label.setVisible(show_b)
        self.scalp_title_b_edit.setVisible(show_b)
        self.scalp_title_b_edit.setEnabled(show_b)

    def _toggle_log_panel(self, expanded: bool) -> None:
        # Arrow state
        if hasattr(self, "log_toggle_btn"):
            self.log_toggle_btn.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)

        # Show/hide body
        if hasattr(self, "log_body"):
            self.log_body.setVisible(expanded)

        # Give space back to the controls by resizing the vertical splitter
        splitter = getattr(self, "_main_splitter", None)
        if splitter is None:
            return

        sizes = splitter.sizes()
        total = sum(sizes) if sizes else 0

        if not expanded:
            # store current expanded sizes once
            self._log_splitter_sizes = sizes

            # keep a small strip for the header-only group
            collapsed_h = 52  # header strip height
            if total > collapsed_h:
                splitter.setSizes([total - collapsed_h, collapsed_h])
        else:
            # restore previous sizes if available
            if self._log_splitter_sizes and len(self._log_splitter_sizes) == 2:
                splitter.setSizes(self._log_splitter_sizes)
            else:
                # sensible fallback
                if total:
                    splitter.setSizes([int(total * 0.75), int(total * 0.25)])

    def _style_box(self, box: QGroupBox) -> None:
        font = box.font()
        font.setPointSize(10)
        font.setBold(False)
        box.setFont(font)
        box.setStyleSheet("QGroupBox::title {font-weight: bold;}")

    def _build_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(10, 10, 10, 10)
        root_layout.setSpacing(8)

        menu = QMenuBar()
        menu.setNativeMenuBar(False)
        menu.setStyleSheet(
            "QMenuBar {background-color: #e0e0e0;}"
            "QMenuBar::item {padding: 2px 8px; background: transparent;}"
            "QMenuBar::item:selected {background: #d5d5d5;}"
        )
        action = QAction("Settings", self)
        action.setToolTip("Open plot generator settings")
        action.triggered.connect(self._open_settings)
        menu.addAction(action)
        root_layout.addWidget(menu)

        controls_splitter = QSplitter(Qt.Horizontal)
        controls_splitter.setContentsMargins(0, 0, 0, 0)

        file_box = QGroupBox("File I/O")
        self._style_box(file_box)
        file_layout = QVBoxLayout(file_box)
        file_layout.setContentsMargins(8, 8, 8, 8)
        file_layout.setSpacing(6)

        self.folder_edit = QLineEdit()
        self.folder_edit.setReadOnly(True)
        self.folder_edit.setPlaceholderText("Select the folder containing your Excel sheets")
        self.folder_edit.setText(self._defaults.get("input_folder", ""))
        self.folder_edit.setToolTip("Select the folder containing your Excel sheets.")
        browse = QPushButton("Browse…")
        browse.setToolTip(
            "Select the FOLDER that contains your results excel files"
        )
        browse.setIcon(self.style().standardIcon(QStyle.SP_DirOpenIcon))
        browse.clicked.connect(self._select_folder)
        in_row = QHBoxLayout()
        in_row.addWidget(QLabel("Excel Files Folder:"))
        in_row.addWidget(browse)
        file_layout.addLayout(in_row)
        self.folder_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        file_layout.addWidget(self.folder_edit)

        self.out_edit = QLineEdit()
        self.out_edit.setReadOnly(True)
        self.out_edit.setPlaceholderText("Folder where plots will be saved")
        self.out_edit.setText(self._defaults.get("output_folder", ""))
        self.out_edit.setToolTip("Folder where plots will be saved")
        browse_out = QPushButton("Browse…")
        browse_out.setToolTip("Browse for output folder")
        browse_out.setIcon(self.style().standardIcon(QStyle.SP_DirOpenIcon))
        browse_out.clicked.connect(self._select_output)
        open_out = QPushButton("Open…")
        open_out.setToolTip("Open save directory")
        open_out.setIcon(self.style().standardIcon(QStyle.SP_DirOpenIcon))
        open_out.clicked.connect(self._open_output_folder)
        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("Save Plots To:"))
        out_row.addWidget(browse_out)
        out_row.addWidget(open_out)
        file_layout.addLayout(out_row)
        self.out_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        file_layout.addWidget(self.out_edit)

        params_box = QGroupBox("Plot Parameters")
        self._style_box(params_box)
        params_form = QFormLayout(params_box)
        params_form.setContentsMargins(10, 10, 10, 10)
        params_form.setSpacing(8)

        self.condition_combo = QComboBox()
        self.condition_combo.setToolTip("Select the condition to plot")
        self.condition_combo.currentTextChanged.connect(self._update_chart_title_state)

        self.color_a_btn = QPushButton()
        self.color_a_btn.setFixedSize(20, 20)
        self.color_a_btn.setStyleSheet(f"background-color: {self.stem_color};")
        self.color_a_btn.setToolTip("Color for Condition A")
        self.color_a_btn.clicked.connect(lambda: self._choose_color("a"))

        self.condition_b_combo = QComboBox()
        self.condition_b_combo.setToolTip("Select second condition")

        self.color_b_btn = QPushButton()
        self.color_b_btn.setFixedSize(20, 20)
        self.color_b_btn.setStyleSheet(f"background-color: {self.stem_color_b};")
        self.color_b_btn.setToolTip("Color for Condition B")
        self.color_b_btn.clicked.connect(lambda: self._choose_color("b"))

        cond_row = QHBoxLayout()
        cond_row.setSpacing(6)
        cond_row.addWidget(QLabel("Condition A"))
        cond_row.addWidget(self.condition_combo)
        cond_row.addWidget(self.color_a_btn)
        self.overlay_container = QWidget()
        oc_layout = QHBoxLayout(self.overlay_container)
        oc_layout.setContentsMargins(0, 0, 0, 0)
        oc_layout.setSpacing(6)
        self.vs_label = QLabel("vs")
        oc_layout.addWidget(self.vs_label)
        oc_layout.addWidget(QLabel("Condition B"))
        oc_layout.addWidget(self.condition_b_combo)
        oc_layout.addWidget(self.color_b_btn)
        cond_row.addWidget(self.overlay_container)
        params_form.addRow(cond_row)

        self.overlay_check = QCheckBox("Overlay Comparison")
        self.overlay_check.toggled.connect(self._overlay_toggled)
        params_form.addRow("", self.overlay_check)

        self.group_box = QGroupBox("Group Options")
        self._style_box(self.group_box)
        group_layout = QVBoxLayout(self.group_box)
        group_layout.setContentsMargins(6, 6, 6, 6)
        group_layout.setSpacing(6)
        self.group_overlay_check = QCheckBox("Overlay groups on plots")
        self.group_overlay_check.toggled.connect(self._on_group_overlay_toggled)
        group_layout.addWidget(self.group_overlay_check)
        self.group_list = QListWidget()
        self.group_list.setSelectionMode(QListWidget.NoSelection)
        self.group_list.setMinimumHeight(80)
        group_layout.addWidget(self.group_list)
        self.group_box.setVisible(False)
        params_form.addRow(self.group_box)



        self.roi_combo = QComboBox()
        self.roi_combo.addItems([ALL_ROIS_OPTION] + list(self.roi_map.keys()))
        self.roi_combo.setToolTip("Select the region of interest")
        params_form.addRow(QLabel("ROI:"), self.roi_combo)

        self.scalp_check = QCheckBox("Include scalp maps")
        self.scalp_check.setChecked(self.include_scalp_maps)
        self.scalp_check.toggled.connect(self._toggle_scalp_controls)
        params_form.addRow("", self.scalp_check)

        scalp_row = QHBoxLayout()
        scalp_row.setContentsMargins(10, 0, 10, 0)
        scalp_row.setSpacing(6)
        self.scalp_min_spin = QDoubleSpinBox()
        self.scalp_min_spin.setRange(-9999.0, 9999.0)
        self.scalp_min_spin.setDecimals(2)
        self.scalp_min_spin.setSingleStep(0.1)
        self.scalp_min_spin.setValue(float(self.scalp_min))
        self.scalp_min_spin.setSuffix(" uV")
        self.scalp_max_spin = QDoubleSpinBox()
        self.scalp_max_spin.setRange(-9999.0, 9999.0)
        self.scalp_max_spin.setDecimals(2)
        self.scalp_max_spin.setSingleStep(0.1)
        self.scalp_max_spin.setValue(float(self.scalp_max))
        self.scalp_max_spin.setSuffix(" uV")
        scalp_row.addWidget(self.scalp_min_spin)
        scalp_row.addWidget(QLabel("to"))
        scalp_row.addWidget(self.scalp_max_spin)
        params_form.addRow(QLabel("Scalp range (uV):"), scalp_row)

        self.scalp_title_a_edit = QLineEdit(self.scalp_title_a_template)
        self.scalp_title_a_edit.setPlaceholderText("{condition} {roi} scalp map")
        self.scalp_title_a_edit.setToolTip(
            "Title template for scalp maps. Use {condition} and {roi} placeholders."
        )
        params_form.addRow(QLabel("Scalp title (A):"), self.scalp_title_a_edit)

        self.scalp_title_b_edit = QLineEdit(self.scalp_title_b_template)
        self.scalp_title_b_edit.setPlaceholderText("{condition} {roi} scalp map")
        self.scalp_title_b_edit.setToolTip(
            "Title template for Condition B scalp maps. Use {condition} and {roi}."
        )
        self.scalp_title_b_label = QLabel("Scalp title (B):")
        params_form.addRow(self.scalp_title_b_label, self.scalp_title_b_edit)

        self._toggle_scalp_controls(self.include_scalp_maps)

        self.title_edit = QLineEdit(self._defaults["title_snr"])
        self.title_edit.setPlaceholderText("e.g. Fruit vs Veg")
        self.title_edit.setToolTip("Title shown on the plot")
        params_form.addRow(QLabel("Chart title:"), self.title_edit)

        self.xlabel_edit = QLineEdit(self._defaults["xlabel"])
        self.xlabel_edit.setPlaceholderText("e.g. Frequency (Hz)")
        self.xlabel_edit.setToolTip("Label for the X axis")
        params_form.addRow(QLabel("X-axis label:"), self.xlabel_edit)

        self.ylabel_edit = QLineEdit(self._defaults["ylabel_snr"])
        self.ylabel_edit.setPlaceholderText("Metric units")
        self.ylabel_edit.setToolTip("Label for the Y axis")
        params_form.addRow(QLabel("Y-axis label:"), self.ylabel_edit)

        ranges_box = QGroupBox("Axis Ranges")
        self._style_box(ranges_box)
        ranges_form = QFormLayout(ranges_box)
        ranges_form.setContentsMargins(10, 10, 10, 10)
        ranges_form.setSpacing(8)

        self.xmin_spin = QDoubleSpinBox()
        self.xmin_spin.setRange(-9999.0, 9999.0)
        self.xmin_spin.setDecimals(2)
        self.xmin_spin.setSingleStep(0.1)
        self.xmin_spin.setSuffix(" Hz")
        self.xmin_spin.setValue(float(self._defaults["x_min"]))
        self.xmin_spin.setToolTip("Minimum X frequency")
        self.xmax_spin = QDoubleSpinBox()
        self.xmax_spin.setRange(-9999.0, 9999.0)
        self.xmax_spin.setDecimals(2)
        self.xmax_spin.setSingleStep(0.1)
        self.xmax_spin.setSuffix(" Hz")
        self.xmax_spin.setValue(float(self._defaults["x_max"]))
        self.xmax_spin.setToolTip("Maximum X frequency")
        x_row = QHBoxLayout()
        x_row.setContentsMargins(10, 10, 10, 10)
        x_row.setSpacing(8)
        x_row.addWidget(self.xmin_spin)
        x_row.addWidget(QLabel("to"))
        x_row.addWidget(self.xmax_spin)
        ranges_form.addRow(QLabel("X Range:"), x_row)

        self.ymin_spin = QDoubleSpinBox()
        self.ymin_spin.setRange(-9999.0, 9999.0)
        self.ymin_spin.setDecimals(2)
        self.ymin_spin.setSingleStep(0.1)
        self.ymin_spin.setValue(float(self._defaults["y_min_snr"]))
        self.ymin_spin.setToolTip("Minimum Y value")
        self.ymax_spin = QDoubleSpinBox()
        self.ymax_spin.setRange(-9999.0, 9999.0)
        self.ymax_spin.setDecimals(2)
        self.ymax_spin.setSingleStep(0.1)
        self.ymax_spin.setValue(float(self._defaults["y_max_snr"]))
        self.ymax_spin.setToolTip("Maximum Y value")
        y_row = QHBoxLayout()
        y_row.setContentsMargins(10, 10, 10, 10)
        y_row.setSpacing(8)
        y_row.addWidget(self.ymin_spin)
        y_row.addWidget(QLabel("to"))
        y_row.addWidget(self.ymax_spin)
        ranges_form.addRow(QLabel("Y Range:"), y_row)

        actions_box = QGroupBox("Actions")
        self._style_box(actions_box)
        actions_layout = QVBoxLayout(actions_box)
        actions_layout.setContentsMargins(10, 10, 10, 10)
        actions_layout.setSpacing(8)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(10, 10, 10, 10)
        btn_row.setSpacing(8)
        self.save_defaults_btn = QPushButton("Save Defaults")
        self.save_defaults_btn.setToolTip("Save current folders as defaults")
        self.save_defaults_btn.clicked.connect(self._save_defaults)
        self.load_defaults_btn = QPushButton("Reset to Default settings")
        self.load_defaults_btn.setToolTip("Reset all values to defaults")
        self.load_defaults_btn.clicked.connect(self._load_defaults)
        self.gen_btn = QPushButton("Generate")
        self.gen_btn.setToolTip("Start plot generation")
        self.gen_btn.clicked.connect(self._generate)
        self.gen_btn.setEnabled(False)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setToolTip("Cancel generation")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel_generation)
        for w in (self.save_defaults_btn, self.load_defaults_btn):
            btn_row.addWidget(w)
        btn_row.addStretch()
        for w in (self.gen_btn, self.cancel_btn):
            btn_row.addWidget(w)
        actions_layout.addLayout(btn_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setStyleSheet(
            "QProgressBar::chunk {background-color: #16C60C;}"
        )
        actions_layout.addWidget(self.progress_bar)

        left_container = QWidget()
        left_layout = QVBoxLayout(left_container)
        left_layout.setContentsMargins(10, 10, 10, 10)
        left_layout.setSpacing(8)
        left_layout.addWidget(file_box)
        left_layout.addWidget(ranges_box)

        right_container = QWidget()
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(10, 10, 10, 10)
        right_layout.setSpacing(8)
        right_layout.addWidget(params_box)
        right_layout.addWidget(actions_box)

        controls_splitter.addWidget(left_container)
        controls_splitter.addWidget(right_container)
        controls_splitter.setSizes([600, 300])

        splitter = QSplitter(Qt.Vertical)
        self._main_splitter = splitter
        self._log_splitter_sizes: list[int] | None = None
        splitter.addWidget(controls_splitter)

        console_box = QGroupBox()
        self._style_box(console_box)
        console_layout = QVBoxLayout(console_box)
        console_layout.setContentsMargins(10, 10, 10, 10)
        console_layout.setSpacing(8)

        header = QHBoxLayout()
        header.setContentsMargins(10, 10, 10, 10)
        header.setSpacing(8)
        self.log_toggle_btn = QToolButton()
        self.log_toggle_btn.setText("Log Output")
        self.log_toggle_btn.setCheckable(True)
        self.log_toggle_btn.setChecked(True)
        self.log_toggle_btn.setArrowType(Qt.DownArrow)
        self.log_toggle_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.log_toggle_btn.toggled.connect(self._toggle_log_panel)
        header.addWidget(self.log_toggle_btn)
        header.addStretch()
        clear_btn = QPushButton()
        clear_btn.setIcon(self.style().standardIcon(QStyle.SP_TrashIcon))
        clear_btn.setFixedSize(22, 22)
        clear_btn.setToolTip("Clear Log")
        clear_btn.clicked.connect(lambda: self.log.clear())
        header.addWidget(clear_btn)
        console_layout.addLayout(header)

        self.log_body = QWidget()
        log_body_layout = QVBoxLayout(self.log_body)
        log_body_layout.setContentsMargins(0, 0, 0, 0)
        log_body_layout.setSpacing(0)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        font = self.log.font()
        font.setBold(False)
        self.log.setFont(font)
        log_body_layout.addWidget(self.log)

        console_layout.addWidget(self.log_body)

        splitter.addWidget(console_box)
        splitter.setSizes([500, 200])
        root_layout.addWidget(splitter)

        root_layout.setSpacing(10)
        root_layout.setContentsMargins(10, 10, 10, 10)

        self.folder_edit.textChanged.connect(self._check_required)
        self.out_edit.textChanged.connect(self._check_required)
        self.condition_combo.currentTextChanged.connect(self._check_required)
        self.condition_b_combo.currentTextChanged.connect(self._check_required)
        self.overlay_check.toggled.connect(self._check_required)
        self._check_required()

    def _overlay_toggled(self, checked: bool) -> None:
        for anim in (self._overlay_width_anim, self._overlay_opacity_anim):
            anim.stop()
        if checked:
            end_width = self.overlay_container.sizeHint().width()
            self.overlay_container.setVisible(True)
            self._overlay_width_anim.setStartValue(self.overlay_container.maximumWidth())
            self._overlay_width_anim.setEndValue(end_width)
            self._overlay_opacity_anim.setStartValue(self.overlay_container.windowOpacity())
            self._overlay_opacity_anim.setEndValue(1.0)
            if self.group_box.isVisible():
                self.group_overlay_check.setChecked(False)
                self.group_overlay_check.setEnabled(False)
                self.group_list.setEnabled(False)
        else:
            self._overlay_width_anim.setStartValue(self.overlay_container.maximumWidth())
            self._overlay_width_anim.setEndValue(0)
            self._overlay_opacity_anim.setStartValue(self.overlay_container.windowOpacity())
            self._overlay_opacity_anim.setEndValue(0.0)
            if self.group_box.isVisible():
                self.group_overlay_check.setEnabled(True)
                self.group_list.setEnabled(self.group_overlay_check.isChecked())
        self._overlay_width_anim.start()
        self._overlay_opacity_anim.start()
        if checked:
            self.title_edit.setEnabled(True)
            self.title_edit.clear()
            self.title_edit.setPlaceholderText(
                "Enter base chart name (e.g. Color Response vs Category Response)"
            )
        else:
            # Revert to auto-generation behavior when comparison mode is off
            self._update_chart_title_state(self.condition_combo.currentText())
        self._update_scalp_title_b_visibility()

    def _on_group_overlay_toggled(self, checked: bool) -> None:
        self.group_list.setEnabled(checked)
        self._check_required()

    def _select_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select Excel Folder")
        if folder:
            self.folder_edit.setText(folder)
            self._populate_conditions(folder)


    def _select_output(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if folder:
            self.out_edit.setText(folder)

    def _persist_scalp_settings(self, save: bool = True) -> None:
        self.plot_mgr.set_include_scalp_maps(self.scalp_check.isChecked())
        self.plot_mgr.set_scalp_bounds(
            self.scalp_min_spin.value(), self.scalp_max_spin.value()
        )
        self.plot_mgr.set_scalp_title_a_template(self.scalp_title_a_edit.text())
        self.plot_mgr.set_scalp_title_b_template(self.scalp_title_b_edit.text())
        if save:
            self.plot_mgr.save()

    def _choose_color(self, which: str) -> None:
        init = self.stem_color if which == "a" else self.stem_color_b
        color = QColorDialog.getColor(QColor(init), self)
        if color.isValid():
            if which == "a":
                self.stem_color = color.name()
                self.color_a_btn.setStyleSheet(f"background-color: {self.stem_color};")
                self.plot_mgr.set_stem_color(self.stem_color)
            else:
                self.stem_color_b = color.name()
                self.color_b_btn.setStyleSheet(f"background-color: {self.stem_color_b};")
                self.plot_mgr.set_second_color(self.stem_color_b)
            self.plot_mgr.save()

    def _update_chart_title_state(self, condition: str) -> None:
        """Enable/disable the title field based on the selected condition."""
        if self.overlay_check.isChecked():
            self.title_edit.setEnabled(True)
            self.title_edit.setPlaceholderText(
                "Enter base chart name (e.g. Color Response vs Category Response)"
            )
            return
        if condition == ALL_CONDITIONS_OPTION:
            self.title_edit.setEnabled(False)
            self.title_edit.setPlaceholderText("")
            self.title_edit.setText(
                "Chart Names Automatically Generated Based on Condition"
            )
        else:
            self.title_edit.setEnabled(True)
            self.title_edit.setPlaceholderText("e.g. Fruit vs Veg")
            if condition:
                self.title_edit.setText(condition)

    def _populate_conditions(self, folder: str) -> None:
        self._refresh_group_controls(folder)
        self.condition_combo.clear()
        self.condition_b_combo.clear()
        try:
            subfolders = [
                f.name
                for f in Path(folder).iterdir()
                if f.is_dir() and ".fif" not in f.name.lower()
            ]
        except Exception:
            subfolders = []
        if subfolders:
            self.condition_combo.addItem(ALL_CONDITIONS_OPTION)
            self.condition_combo.addItems(subfolders)
            self.condition_b_combo.addItems(subfolders)
            # Default to "All Conditions" which auto-generates chart names
            self._update_chart_title_state(ALL_CONDITIONS_OPTION)

    def _save_defaults(self) -> None:
        self.plot_mgr.set("paths", "input_folder", self.folder_edit.text())
        self.plot_mgr.set("paths", "output_folder", self.out_edit.text())
        self._persist_scalp_settings(save=False)
        self.plot_mgr.save()
        QMessageBox.information(self, "Defaults", "Default folders saved.")

    def _load_defaults(self) -> None:
        self._defaults = self._orig_defaults.copy()
        self.folder_edit.setText(self._defaults["input_folder"])
        self.out_edit.setText(self._defaults["output_folder"])
        self._populate_conditions(self._defaults["input_folder"])
        self.xlabel_edit.setText(self._defaults["xlabel"])
        self.xmin_spin.setValue(float(self._defaults["x_min"]))
        self.xmax_spin.setValue(float(self._defaults["x_max"]))
        self.ylabel_edit.setText(self._defaults["ylabel_snr"])
        self.ymin_spin.setValue(float(self._defaults["y_min_snr"]))
        self.ymax_spin.setValue(float(self._defaults["y_max_snr"]))
        self.scalp_check.setChecked(bool(self._defaults.get("include_scalp_maps", False)))
        self.scalp_min_spin.setValue(float(self._defaults.get("scalp_min", -1.0)))
        self.scalp_max_spin.setValue(float(self._defaults.get("scalp_max", 1.0)))
        self.scalp_title_a_edit.setText(self._defaults.get("scalp_title_a_template", ""))
        self.scalp_title_b_edit.setText(self._defaults.get("scalp_title_b_template", ""))
        # Update the chart title field based on the current condition
        self._update_chart_title_state(self.condition_combo.currentText())
        QMessageBox.information(self, "Defaults", "Settings reset to defaults.")

    def _refresh_group_controls(self, folder: str) -> None:
        if not hasattr(self, "group_box"):
            return
        manifest = None
        if folder:
            try:
                manifest = load_manifest_for_excel_root(Path(folder))
            except Exception:  # pragma: no cover - log via UI only
                manifest = None
        self._subject_groups_map = normalize_participants_map(manifest)
        groups = extract_group_names(manifest)
        self._available_groups = groups
        self._has_multi_groups = has_multi_groups(manifest)
        self.group_box.setVisible(self._has_multi_groups)
        self.group_overlay_check.setChecked(False)
        self.group_overlay_check.setEnabled(
            self._has_multi_groups and not self.overlay_check.isChecked()
        )
        self.group_list.clear()
        if self._has_multi_groups:
            for name in groups:
                item = QListWidgetItem(name)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked)
                self.group_list.addItem(item)
            self.group_list.setEnabled(False)
        else:
            self.group_list.setEnabled(False)

    def _selected_groups(self) -> list[str]:
        selected: list[str] = []
        for idx in range(self.group_list.count()):
            item = self.group_list.item(idx)
            if item.checkState() == Qt.Checked:
                selected.append(item.text())
        return selected

    def _group_overlay_enabled(self) -> bool:
        return self.group_box.isVisible() and self.group_overlay_check.isChecked()

    def _group_worker_kwargs(
        self, overlay_enabled: bool, selected_groups: list[str]
    ) -> dict:
        if not overlay_enabled:
            return {
                "subject_groups": None,
                "selected_groups": None,
                "enable_group_overlay": False,
                "multi_group_mode": self._has_multi_groups,
            }
        return {
            "subject_groups": dict(self._subject_groups_map),
            "selected_groups": list(selected_groups),
            "enable_group_overlay": True,
            "multi_group_mode": self._has_multi_groups,
        }

    def _append_log(self, text: str) -> None:
        self.log.append(text)
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())

    def _animate_progress_to(self, value: int) -> None:
        """Animate the progress bar smoothly to the target value."""
        self._progress_anim.stop()
        self._progress_anim.setStartValue(self.progress_bar.value())
        self._progress_anim.setEndValue(value)
        self._progress_anim.start()

    def _on_progress(self, msg: str, processed: int, total: int) -> None:
        if msg:
            self._append_log(msg)
        # Avoid resetting the progress bar when only log messages are emitted
        if total == 0:
            return

        if self._total_conditions:
            frac = (self._current_condition - 1) / self._total_conditions
            if total:
                frac += processed / total / self._total_conditions
            value = int(frac * 100)
        else:
            value = int(100 * processed / total) if total else 0
        self._animate_progress_to(value)

    def _cancel_generation(self) -> None:
        if self._worker:
            self._worker.stop()
        if self._thread:
            self._thread.quit()
        self._conditions_queue.clear()
        self._total_conditions = 0
        self._current_condition = 0
        self.cancel_btn.setEnabled(False)
        self.gen_btn.setEnabled(True)
        self._append_log("Generation cancelled.")

    def _start_next_condition(self) -> None:
        if not self._conditions_queue:
            self._finish_all()
            return
        (
            folder,
            out_dir,
            x_min,
            x_max,
            y_min,
            y_max,
            group_kwargs,
            include_scalp,
            scalp_min,
            scalp_max,
            scalp_title_a,
            scalp_title_b,
        ) = self._gen_params
        condition = self._conditions_queue.pop(0)
        self._current_condition += 1

        cond_out = Path(out_dir)
        if self._all_conditions:
            cond_out = cond_out / f"{condition} Plots"
            title = condition
        else:
            title = self.title_edit.text()

        self._thread = QThread()
        self._worker = _Worker(
            folder,
            condition,
            self.roi_map,
            self.roi_combo.currentText(),
            title,
            self.xlabel_edit.text(),
            self.ylabel_edit.text(),
            x_min,
            x_max,
            y_min,
            y_max,
            str(cond_out),
            self.stem_color,
            include_scalp_maps=include_scalp,
            scalp_vmin=scalp_min,
            scalp_vmax=scalp_max,
            scalp_title_a_template=scalp_title_a,
            scalp_title_b_template=scalp_title_b,
            **group_kwargs,
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._generation_finished)
        self._thread.start()

    def _finish_all(self) -> None:
        self.gen_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self._animate_progress_to(100)
        self._total_conditions = 0
        self._current_condition = 0
        out_dir = self.out_edit.text()
        images = []
        try:
            if self._all_conditions:
                images = list(Path(out_dir).rglob("*.png"))
            else:
                images = list(Path(out_dir).glob("*.png"))
        except Exception:
            pass
        if images:
            resp = QMessageBox.question(
                self,
                "Finished",
                "Plots have been successfully generated. View plots?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if resp == QMessageBox.Yes:
                self._open_output_folder()
        else:
            QMessageBox.warning(
                self,
                "Finished",
                "No plots were generated. Please check the log for errors.",
            )

    def _generate(self) -> None:
        folder = self.folder_edit.text()
        if not folder:
            QMessageBox.critical(self, "Error", "Select a folder first.")
            return

        out_dir = self.out_edit.text()
        if not out_dir:
            QMessageBox.critical(self, "Error", "Select an output folder first.")
            return

        if not self.condition_combo.currentText():
            QMessageBox.critical(self, "Error", "No condition selected.")
            return
        try:
            x_min = self.xmin_spin.value()
            x_max = self.xmax_spin.value()
            y_min = self.ymin_spin.value()
            y_max = self.ymax_spin.value()
        except ValueError:
            QMessageBox.critical(self, "Error", "Invalid axis limits.")
            return

        include_scalp = self.scalp_check.isChecked()
        scalp_min = self.scalp_min_spin.value()
        scalp_max = self.scalp_max_spin.value()

        overlay_groups = self._group_overlay_enabled()
        selected_groups = self._selected_groups() if overlay_groups else []
        if overlay_groups and not selected_groups:
            QMessageBox.warning(
                self,
                "Group Overlay",
                "Select at least one group before plotting.",
            )
            self.gen_btn.setEnabled(True)
            self.cancel_btn.setEnabled(False)
            return
        group_kwargs = self._group_worker_kwargs(overlay_groups, selected_groups)
        self._persist_scalp_settings(save=True)

        self.gen_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.log.clear()
        self._animate_progress_to(0)
        if self.overlay_check.isChecked():
            cond_a = self.condition_combo.currentText()
            cond_b = self.condition_b_combo.currentText()
            if cond_a == cond_b:
                QMessageBox.critical(self, "Error", "Select two different conditions.")
                self.gen_btn.setEnabled(True)
                self.cancel_btn.setEnabled(False)
                return
            self._thread = QThread()
            self._worker = _Worker(
                folder,
                cond_a,
                self.roi_map,
                self.roi_combo.currentText(),
                self.title_edit.text(),
                self.xlabel_edit.text(),
                self.ylabel_edit.text(),
                x_min,
                x_max,
                y_min,
                y_max,
                out_dir,
                self.stem_color,
                condition_b=cond_b,
                stem_color_b=self.stem_color_b,
                overlay=True,
                include_scalp_maps=include_scalp,
                scalp_vmin=scalp_min,
                scalp_vmax=scalp_max,
                scalp_title_a_template=self.scalp_title_a_edit.text(),
                scalp_title_b_template=self.scalp_title_b_edit.text(),
                **group_kwargs,
            )
            self._worker.moveToThread(self._thread)
            self._thread.started.connect(self._worker.run)
            self._worker.progress.connect(self._on_progress)
            self._worker.finished.connect(self._thread.quit)
            self._worker.finished.connect(self._worker.deleteLater)
            self._thread.finished.connect(self._thread.deleteLater)
            self._thread.finished.connect(self._finish_all)
            self._thread.start()
        else:
            self._all_conditions = (
                self.condition_combo.currentText() == ALL_CONDITIONS_OPTION
            )
            if self._all_conditions:
                self._conditions_queue = [
                    self.condition_combo.itemText(i)
                    for i in range(1, self.condition_combo.count())
                ]
            else:
                self._conditions_queue = [self.condition_combo.currentText()]
            self._total_conditions = len(self._conditions_queue)
            self._current_condition = 0
            self._gen_params = (
                folder,
                out_dir,
                x_min,
                x_max,
                y_min,
                y_max,
                group_kwargs.copy(),
                include_scalp,
                scalp_min,
                scalp_max,
                self.scalp_title_a_edit.text(),
                self.scalp_title_b_edit.text(),
            )
            self._start_next_condition()

    def _open_settings(self) -> None:
        dlg = _SettingsDialog(self, self.stem_color, self.stem_color_b)
        if dlg.exec():
            self.stem_color, self.stem_color_b = dlg.selected_colors()
            self.plot_mgr.set_stem_color(self.stem_color)
            self.plot_mgr.set_second_color(self.stem_color_b)
            self.plot_mgr.save()

    def _open_output_folder(self) -> None:
        folder = self.out_edit.text()
        if not folder:
            return
        if sys.platform.startswith("win"):
            os.startfile(folder)
        elif sys.platform == "darwin":
            subprocess.call(["open", folder])
        else:
            subprocess.call(["xdg-open", folder])

    def _check_required(self) -> None:
        required = bool(
            self.folder_edit.text()
            and self.out_edit.text()
            and self.condition_combo.currentText()
        )
        if self.overlay_check.isChecked():
            required = required and bool(self.condition_b_combo.currentText())
        if self._group_overlay_enabled() and not self._selected_groups():
            required = False
        self.gen_btn.setEnabled(required)

    def _generation_finished(self) -> None:
        self._thread = None
        self._worker = None
        if self._conditions_queue:
            self._start_next_condition()
            return
        self._finish_all()
