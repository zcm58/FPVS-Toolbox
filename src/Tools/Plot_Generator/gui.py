"""GUI elements for the plot generator."""
from __future__ import annotations

import logging
import os
import json
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QPropertyAnimation, QSignalBlocker, QThread, Qt, QTimer
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
    QGridLayout,
    QWidget,
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
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QColorDialog


from Main_App import SettingsManager
from Main_App.PySide6_App.Backend.project import (
    EXCEL_SUBFOLDER_NAME,
    SNR_SUBFOLDER_NAME,
    Project,
)
from Main_App.PySide6_App.Backend.project_metadata import read_project_metadata
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

ALL_CONDITIONS_OPTION = "All Conditions"
_LEGEND_LABELS_KEY_PATH = ("tools", "snr_plot", "legend_labels")
_LEGEND_DEFAULT_A_PEAKS = "A-Peaks"
_LEGEND_DEFAULT_B_PEAKS = "B-Peaks"

logger = logging.getLogger(__name__)


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


def _project_paths(
    parent: QWidget | None, project_dir: str | Path | None
) -> tuple[str | None, str | None]:
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
        self._ui_initializing = True
        self._populating_conditions = False
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
        self._project_root: Path | None = None
        self._project: Project | None = None


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
        if proj and hasattr(proj, "project_root"):
            self._project = proj
            self._project_root = Path(proj.project_root)

        if project_dir_path is not None:
            self._project_root = project_dir_path
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

        self._log_last_expanded_height: int | None = None
        self._initial_collapsed_height: int | None = None


        self._build_ui()
        self._update_selector_columns(self.overlay_check.isChecked())
        self._load_legend_settings()
        self._update_legend_group_visibility()
        # Prepare animation for smooth progress updates
        self._progress_anim = QPropertyAnimation(self.progress_bar, b"value")
        self._progress_anim.setDuration(200)
        if default_in:
            self.folder_edit.setText(default_in)
            self._populate_conditions(default_in)
        if default_out:
            self.out_edit.setText(default_out)

        QTimer.singleShot(0, self._record_initial_collapsed_height)

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
        self._ui_initializing = False

    def _bold_label(self, text: str) -> QLabel:
        label = QLabel(text)
        font = label.font()
        font.setBold(True)
        label.setFont(font)
        return label

    def _legend_default_values(self) -> dict[str, str]:
        return {
            "condition_a_label": self.condition_combo.currentText().strip(),
            "condition_b_label": self.condition_b_combo.currentText().strip(),
            "a_peaks_label": _LEGEND_DEFAULT_A_PEAKS,
            "b_peaks_label": _LEGEND_DEFAULT_B_PEAKS,
        }

    def _legend_settings_payload(self) -> dict[str, object]:
        return {
            "custom_labels_enabled": self.legend_custom_check.isChecked(),
            "condition_a_label": self.legend_condition_a_edit.text(),
            "condition_b_label": self.legend_condition_b_edit.text(),
            "a_peaks_label": self.legend_a_peaks_edit.text(),
            "b_peaks_label": self.legend_b_peaks_edit.text(),
        }

    def _update_legend_group_visibility(self) -> None:
        show = self.overlay_check.isChecked()
        self.legend_group.setVisible(show)
        if show and self.legend_custom_check.isChecked():
            self._prefill_legend_defaults_if_empty()

    def _prefill_legend_defaults_if_empty(self) -> None:
        defaults = self._legend_default_values()
        if not self.legend_condition_a_edit.text().strip():
            self.legend_condition_a_edit.setText(defaults["condition_a_label"])
        if not self.legend_condition_b_edit.text().strip():
            self.legend_condition_b_edit.setText(defaults["condition_b_label"])
        if not self.legend_a_peaks_edit.text().strip():
            self.legend_a_peaks_edit.setText(defaults["a_peaks_label"])
        if not self.legend_b_peaks_edit.text().strip():
            self.legend_b_peaks_edit.setText(defaults["b_peaks_label"])

    def _toggle_custom_legend_labels(self, checked: bool) -> None:
        self.legend_condition_a_edit.setEnabled(checked)
        self.legend_condition_b_edit.setEnabled(checked)
        self.legend_a_peaks_edit.setEnabled(checked)
        self.legend_b_peaks_edit.setEnabled(checked)
        if checked:
            self._prefill_legend_defaults_if_empty()
        if not self._ui_initializing:
            self._persist_legend_settings()

    def _reset_legend_defaults(self) -> None:
        defaults = self._legend_default_values()
        self.legend_custom_check.setChecked(False)
        self.legend_condition_a_edit.setText(defaults["condition_a_label"])
        self.legend_condition_b_edit.setText(defaults["condition_b_label"])
        self.legend_a_peaks_edit.setText(defaults["a_peaks_label"])
        self.legend_b_peaks_edit.setText(defaults["b_peaks_label"])
        self.legend_condition_a_edit.setEnabled(False)
        self.legend_condition_b_edit.setEnabled(False)
        self.legend_a_peaks_edit.setEnabled(False)
        self.legend_b_peaks_edit.setEnabled(False)
        if not self._ui_initializing:
            self._persist_legend_settings()

    def _load_legend_settings(self) -> None:
        if self._project is None and self._project_root:
            try:
                metadata = read_project_metadata(self._project_root)
            except Exception as exc:
                logger.warning(
                    "Failed to read project metadata for legend settings.",
                    exc_info=exc,
                    extra={
                        "operation": "snr_plot_project_metadata",
                        "project_root": str(self._project_root),
                    },
                )
            else:
                if metadata.parse_error:
                    self._append_log(
                        "Project settings could not be read (invalid JSON). Using defaults."
                    )
                    logger.warning(
                        "Invalid project.json detected; using defaults.",
                        extra={
                            "operation": "snr_plot_project_metadata",
                            "project_root": str(self._project_root),
                        },
                    )
            try:
                self._project = Project.load(self._project_root)
            except Exception as exc:
                self._append_log(
                    "Unable to load project settings. Legend label settings will not persist."
                )
                logger.warning(
                    "Failed to load project for legend settings.",
                    exc_info=exc,
                    extra={
                        "operation": "snr_plot_project_load",
                        "project_root": str(self._project_root),
                    },
                )
                self._project = None

        defaults = self._legend_default_values()
        labels: dict[str, object] = {}
        if self._project is not None:
            tools_section = self._project.manifest.get("tools", {})
            if isinstance(tools_section, dict):
                snr_section = tools_section.get("snr_plot", {})
                if isinstance(snr_section, dict):
                    labels = snr_section.get("legend_labels", {})
        if not isinstance(labels, dict):
            labels = {}
        self.legend_custom_check.setChecked(bool(labels.get("custom_labels_enabled", False)))
        self.legend_condition_a_edit.setText(
            str(labels.get("condition_a_label", defaults["condition_a_label"]))
        )
        self.legend_condition_b_edit.setText(
            str(labels.get("condition_b_label", defaults["condition_b_label"]))
        )
        self.legend_a_peaks_edit.setText(
            str(labels.get("a_peaks_label", defaults["a_peaks_label"]))
        )
        self.legend_b_peaks_edit.setText(
            str(labels.get("b_peaks_label", defaults["b_peaks_label"]))
        )
        self._toggle_custom_legend_labels(self.legend_custom_check.isChecked())

    def _persist_legend_settings(self) -> None:
        if self._ui_initializing:
            return
        if self._project is None:
            logger.info(
                "Legend label settings changed without active project; skipping persistence.",
                extra={
                    "operation": "snr_plot_legend_persist",
                    "project_root": str(self._project_root) if self._project_root else None,
                },
            )
            return
        data = self._legend_settings_payload()
        manifest = self._project.manifest
        cursor = manifest
        for key in _LEGEND_LABELS_KEY_PATH:
            if key not in cursor or not isinstance(cursor.get(key), dict):
                cursor[key] = {}
            cursor = cursor[key]
        cursor.clear()
        cursor.update(data)
        try:
            self._project.save()
        except Exception as exc:
            self._append_log(
                "Failed to save legend label settings to project.json."
            )
            logger.warning(
                "Failed to persist legend label settings.",
                exc_info=exc,
                extra={
                    "operation": "snr_plot_legend_persist",
                    "project_root": str(self._project.project_root),
                },
            )

    def _toggle_scalp_controls(self, checked: bool) -> None:
        if not hasattr(self, "scalp_min_spin"):
            return
        self.include_scalp_maps = checked
        self.scalp_min_spin.setEnabled(checked)
        self.scalp_max_spin.setEnabled(checked)
        self.scalp_title_a_edit.setEnabled(checked)
        self._update_scalp_title_b_visibility()
        self._update_scalp_title_warnings()

    def _update_selector_columns(self, overlay_on: bool) -> None:
        if not hasattr(self, "_selectors_grid"):
            return
        stretches = (1, 1, 1) if overlay_on else (1, 0, 1)
        for idx, stretch in enumerate(stretches):
            self._selectors_grid.setColumnStretch(idx, stretch)
        self.condB_container.setVisible(overlay_on)

    def _ensure_condition_a_valid_for_overlay(self) -> None:
        if (
            self.condition_combo.currentText() == ALL_CONDITIONS_OPTION
            and self.condition_combo.count() > 1
        ):
            self.condition_combo.setCurrentIndex(1)

    def _set_all_conditions_enabled(self, enabled: bool) -> None:
        model = self.condition_combo.model()
        if model and hasattr(model, "item") and model.rowCount() > 0:
            item = model.item(0)
            if item is not None:
                item.setEnabled(enabled)
        self._check_required()

    def _update_scalp_title_b_visibility(self) -> None:
        show_b = self.include_scalp_maps and self.overlay_check.isChecked()
        self.scalp_title_b_label.setVisible(show_b)
        self.scalp_title_b_edit.setVisible(show_b)
        self.scalp_title_b_edit.setEnabled(show_b)
        self._update_scalp_title_warnings()

    def _set_invalid_state(self, edit: QLineEdit, invalid: bool) -> None:
        edit.setProperty("invalid", invalid)
        edit.style().unpolish(edit)
        edit.style().polish(edit)

    def _update_scalp_title_warnings(self) -> None:
        include_scalp = self.scalp_check.isChecked()
        need_b = include_scalp and self.overlay_check.isChecked()
        invalid_a = include_scalp and not self.scalp_title_a_edit.text().strip()
        invalid_b = (
            need_b
            and self.scalp_title_b_edit.isVisible()
            and not self.scalp_title_b_edit.text().strip()
        )
        self._set_invalid_state(self.scalp_title_a_edit, invalid_a)
        self._set_invalid_state(self.scalp_title_b_edit, invalid_b)

    def _scalp_titles_valid(self) -> bool:
        if not self.scalp_check.isChecked():
            return True
        has_a = bool(self.scalp_title_a_edit.text().strip())
        if not self.overlay_check.isChecked():
            return has_a
        return has_a and bool(self.scalp_title_b_edit.text().strip())

    def _toggle_log_panel(self, expanded: bool) -> None:
        self.log_toggle_btn.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.log_body.setVisible(expanded)

        splitter = getattr(self, "_main_splitter", None)
        if splitter is None:
            return

        sizes = splitter.sizes()
        if len(sizes) != 2:
            return

        collapsed_h = 52  # header strip height

        if not expanded:
            if self._initial_collapsed_height is None:
                self._initial_collapsed_height = self.height()
            self._log_splitter_sizes = sizes
            self._log_prev_window_height = self.height()
            self._log_last_expanded_height = self.height()

            top_h, _ = sizes[0], sizes[1]
            splitter.setSizes([top_h, collapsed_h])

            min_h = self.minimumSizeHint().height()
            target_h = max(min_h, self._initial_collapsed_height or self.height())
            if target_h != self.height():
                self.resize(self.width(), target_h)
        else:
            if self._log_splitter_sizes and len(self._log_splitter_sizes) == 2:
                splitter.setSizes(self._log_splitter_sizes)

            target = self._log_last_expanded_height or self._log_prev_window_height
            if target is not None and self.height() < target:
                self.resize(self.width(), target)

    def _record_initial_collapsed_height(self) -> None:
        if not self.log_toggle_btn.isChecked():
            if self._initial_collapsed_height is None:
                self._initial_collapsed_height = self.height()
            else:
                self._initial_collapsed_height = min(
                    self._initial_collapsed_height, self.height()
                )

    def _style_box(self, box: QGroupBox) -> None:
        font = box.font()
        font.setPointSize(10)
        font.setBold(False)
        box.setFont(font)
        box.setStyleSheet("QGroupBox::title {font-weight: bold;}")

    def _build_ui(self) -> None:
        self.setMinimumWidth(500)
        self.resize(500, 750)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(8, 8, 8, 8)
        root_layout.setSpacing(6)
        self.setStyleSheet(
            self.styleSheet()
            + "\nQLineEdit[invalid=\"true\"] {border: 1px solid red;}"
        )

        file_box = QGroupBox("File I/O")
        self._style_box(file_box)
        file_box.setSizePolicy(QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum))
        file_layout = QVBoxLayout(file_box)
        file_layout.setContentsMargins(6, 6, 6, 6)
        file_layout.setSpacing(6)
        file_form = QFormLayout()
        file_form.setContentsMargins(0, 0, 0, 0)
        file_form.setSpacing(6)
        file_form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        file_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

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
        in_row_widget = QWidget()
        in_row = QHBoxLayout(in_row_widget)
        in_row.setContentsMargins(0, 0, 0, 0)
        in_row.setSpacing(6)
        in_row.addWidget(self.folder_edit)
        in_row.addWidget(browse)
        self.folder_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        file_form.addRow(QLabel("Excel Files Folder:"), in_row_widget)

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
        out_row_widget = QWidget()
        out_row = QHBoxLayout(out_row_widget)
        out_row.setContentsMargins(0, 0, 0, 0)
        out_row.setSpacing(6)
        out_row.addWidget(self.out_edit)
        out_row.addWidget(browse_out)
        out_row.addWidget(open_out)
        self.out_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        file_form.addRow(QLabel("Save Plots To:"), out_row_widget)

        file_layout.addLayout(file_form)

        params_box = QGroupBox("Plot Parameters")
        self._style_box(params_box)
        params_box.setSizePolicy(QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum))
        params_form = QFormLayout(params_box)
        params_form.setContentsMargins(6, 6, 6, 6)
        params_form.setSpacing(6)
        params_form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        params_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

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

        self.roi_combo = QComboBox()
        self.roi_combo.addItems([ALL_ROIS_OPTION] + list(self.roi_map.keys()))
        self.roi_combo.setToolTip("Select the region of interest")

        self.condition_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.condition_b_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.roi_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        cond_a_container = QWidget()
        cond_a_layout = QVBoxLayout(cond_a_container)
        cond_a_layout.setContentsMargins(0, 0, 0, 0)
        cond_a_layout.setSpacing(4)
        cond_a_layout.addWidget(QLabel("Condition A"))
        cond_a_row = QHBoxLayout()
        cond_a_row.setContentsMargins(0, 0, 0, 0)
        cond_a_row.setSpacing(6)
        cond_a_row.addWidget(self.condition_combo)
        cond_a_row.addWidget(self.color_a_btn)
        cond_a_layout.addLayout(cond_a_row)

        self.condB_container = QWidget()
        cond_b_layout = QVBoxLayout(self.condB_container)
        cond_b_layout.setContentsMargins(0, 0, 0, 0)
        cond_b_layout.setSpacing(4)
        cond_b_layout.addWidget(QLabel("Condition B"))
        cond_b_row = QHBoxLayout()
        cond_b_row.setContentsMargins(0, 0, 0, 0)
        cond_b_row.setSpacing(6)
        cond_b_row.addWidget(self.condition_b_combo)
        cond_b_row.addWidget(self.color_b_btn)
        cond_b_layout.addLayout(cond_b_row)
        roi_container = QWidget()
        roi_layout = QVBoxLayout(roi_container)
        roi_layout.setContentsMargins(0, 0, 0, 0)
        roi_layout.setSpacing(4)
        roi_layout.addWidget(QLabel("ROI"))
        roi_row = QHBoxLayout()
        roi_row.setContentsMargins(0, 0, 0, 0)
        roi_row.setSpacing(6)
        roi_row.addWidget(self.roi_combo)
        roi_layout.addLayout(roi_row)

        selectors_grid = QGridLayout()
        selectors_grid.setContentsMargins(0, 0, 0, 0)
        selectors_grid.setHorizontalSpacing(10)
        selectors_grid.setVerticalSpacing(2)
        selectors_grid.addWidget(cond_a_container, 0, 0)
        selectors_grid.addWidget(self.condB_container, 0, 1)
        selectors_grid.addWidget(roi_container, 0, 2)

        selectors_container = QWidget()
        selectors_container_layout = QHBoxLayout(selectors_container)
        selectors_container_layout.setContentsMargins(0, 0, 0, 0)
        selectors_container_layout.setSpacing(0)
        selectors_container_layout.addStretch(1)
        selectors_container_layout.addLayout(selectors_grid)
        selectors_container_layout.addStretch(1)

        self._selectors_grid = selectors_grid
        params_form.addRow(selectors_container)

        self.overlay_check = QCheckBox("Overlay Comparison")
        self.overlay_check.toggled.connect(self._overlay_toggled)

        overlay_row = QWidget()
        overlay_layout = QHBoxLayout(overlay_row)
        overlay_layout.setContentsMargins(0, 0, 0, 0)
        overlay_layout.setSpacing(8)
        overlay_layout.addStretch(1)
        overlay_layout.addWidget(self.overlay_check)

        self.scalp_check = QCheckBox("Include scalp maps")
        self.scalp_check.setChecked(self.include_scalp_maps)
        self.scalp_check.toggled.connect(self._toggle_scalp_controls)
        overlay_layout.addWidget(self.scalp_check)
        overlay_layout.addStretch(1)

        params_form.addRow("", overlay_row)

        self.legend_group = QGroupBox("Legend labels (optional)")
        self._style_box(self.legend_group)
        legend_layout = QVBoxLayout(self.legend_group)
        legend_layout.setContentsMargins(6, 6, 6, 6)
        legend_layout.setSpacing(6)
        self.legend_custom_check = QCheckBox("Custom legend labels")
        self.legend_custom_check.toggled.connect(self._toggle_custom_legend_labels)
        legend_layout.addWidget(self.legend_custom_check)

        legend_form = QFormLayout()
        legend_form.setContentsMargins(0, 0, 0, 0)
        legend_form.setSpacing(6)
        legend_form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        legend_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.legend_condition_a_edit = QLineEdit()
        self.legend_condition_a_edit.setPlaceholderText("Condition A label")
        self.legend_condition_a_edit.setEnabled(False)
        self.legend_condition_a_edit.textChanged.connect(self._persist_legend_settings)
        legend_form.addRow(QLabel("Condition A label:"), self.legend_condition_a_edit)

        self.legend_condition_b_edit = QLineEdit()
        self.legend_condition_b_edit.setPlaceholderText("Condition B label")
        self.legend_condition_b_edit.setEnabled(False)
        self.legend_condition_b_edit.textChanged.connect(self._persist_legend_settings)
        legend_form.addRow(QLabel("Condition B label:"), self.legend_condition_b_edit)

        self.legend_a_peaks_edit = QLineEdit()
        self.legend_a_peaks_edit.setPlaceholderText(_LEGEND_DEFAULT_A_PEAKS)
        self.legend_a_peaks_edit.setEnabled(False)
        self.legend_a_peaks_edit.textChanged.connect(self._persist_legend_settings)
        legend_form.addRow(QLabel("A-Peaks label:"), self.legend_a_peaks_edit)

        self.legend_b_peaks_edit = QLineEdit()
        self.legend_b_peaks_edit.setPlaceholderText(_LEGEND_DEFAULT_B_PEAKS)
        self.legend_b_peaks_edit.setEnabled(False)
        self.legend_b_peaks_edit.textChanged.connect(self._persist_legend_settings)
        legend_form.addRow(QLabel("B-Peaks label:"), self.legend_b_peaks_edit)

        legend_layout.addLayout(legend_form)
        self.legend_reset_btn = QPushButton("Reset to defaults")
        self.legend_reset_btn.clicked.connect(self._reset_legend_defaults)
        legend_layout.addWidget(self.legend_reset_btn, alignment=Qt.AlignRight)
        params_form.addRow(self.legend_group)

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

        self.scalp_title_a_edit = QLineEdit(self.scalp_title_a_template)
        self.scalp_title_a_edit.setPlaceholderText("{condition} {roi} scalp map")
        self.scalp_title_a_edit.setToolTip(
            "Title template for scalp maps. Use {condition} and {roi} placeholders."
        )
        self.scalp_title_a_edit.setProperty("invalid", False)
        params_form.addRow(QLabel("Scalp title (A):"), self.scalp_title_a_edit)

        self.scalp_title_b_edit = QLineEdit(self.scalp_title_b_template)
        self.scalp_title_b_edit.setPlaceholderText("{condition} {roi} scalp map")
        self.scalp_title_b_edit.setToolTip(
            "Title template for Condition B scalp maps. Use {condition} and {roi}."
        )
        self.scalp_title_b_edit.setProperty("invalid", False)
        self.scalp_title_b_label = QLabel("Scalp title (B):")
        params_form.addRow(self.scalp_title_b_label, self.scalp_title_b_edit)

        self.title_edit = QLineEdit(self._defaults["title_snr"])
        self.title_edit.setPlaceholderText("e.g. Fruit vs Veg")
        self.title_edit.setToolTip("Title shown on the plot")

        self.xlabel_edit = QLineEdit(self._defaults["xlabel"])
        self.xlabel_edit.setPlaceholderText("e.g. Frequency (Hz)")
        self.xlabel_edit.setToolTip("Label for the X axis")

        self.ylabel_edit = QLineEdit(self._defaults["ylabel_snr"])
        self.ylabel_edit.setPlaceholderText("Metric units")
        self.ylabel_edit.setToolTip("Label for the Y axis")

        ranges_box = QGroupBox("Axis Ranges")
        self._style_box(ranges_box)
        ranges_box.setSizePolicy(
            QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        )
        ranges_form = QFormLayout(ranges_box)
        ranges_form.setContentsMargins(8, 8, 8, 8)
        ranges_form.setSpacing(6)

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
        x_row.setContentsMargins(0, 0, 0, 0)
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
        y_row.setContentsMargins(0, 0, 0, 0)
        y_row.setSpacing(8)
        y_row.addWidget(self.ymin_spin)
        y_row.addWidget(QLabel("to"))
        y_row.addWidget(self.ymax_spin)
        ranges_form.addRow(QLabel("Y Range:"), y_row)

        scalp_row = QHBoxLayout()
        scalp_row.setContentsMargins(0, 0, 0, 0)
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
        ranges_form.addRow(QLabel("Scalp range (uV):"), scalp_row)

        advanced_box = QGroupBox("Advanced")
        self._style_box(advanced_box)
        advanced_box.setSizePolicy(
            QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        )
        advanced_layout = QVBoxLayout(advanced_box)
        advanced_layout.setContentsMargins(6, 6, 6, 6)
        advanced_layout.setSpacing(6)

        advanced_form = QFormLayout()
        advanced_form.setContentsMargins(0, 0, 0, 0)
        advanced_form.setSpacing(6)
        advanced_form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        advanced_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        advanced_form.addRow(QLabel("Chart title:"), self.title_edit)
        advanced_form.addRow(QLabel("X-axis label:"), self.xlabel_edit)
        advanced_form.addRow(QLabel("Y-axis label:"), self.ylabel_edit)
        advanced_layout.addLayout(advanced_form)
        advanced_layout.addWidget(ranges_box)

        self.progress_bar = QProgressBar()
        self.progress_bar.setStyleSheet(
            "QProgressBar::chunk {background-color: #16C60C;}"
        )

        progress_box = QGroupBox("Progress")
        self._style_box(progress_box)
        progress_box.setSizePolicy(
            QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        )
        progress_layout = QVBoxLayout(progress_box)
        progress_layout.setContentsMargins(10, 10, 10, 10)
        progress_layout.setSpacing(6)
        progress_layout.addWidget(self.progress_bar)

        top_content = QWidget()
        top_content.setSizePolicy(
            QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        )
        top_layout = QVBoxLayout(top_content)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(10)
        top_layout.addWidget(file_box)
        top_layout.addWidget(params_box)
        top_layout.addWidget(advanced_box)
        top_layout.addWidget(progress_box)

        splitter = QSplitter(Qt.Vertical)
        self._main_splitter = splitter
        self._log_splitter_sizes: list[int] | None = None
        self._log_prev_window_height: int | None = None
        splitter.addWidget(top_content)

        console_box = QGroupBox()
        self._style_box(console_box)
        console_layout = QVBoxLayout(console_box)
        console_layout.setContentsMargins(10, 10, 10, 10)
        console_layout.setSpacing(8)

        header = QHBoxLayout()
        header.setContentsMargins(2, 2, 2, 2)
        header.setSpacing(6)
        self.log_toggle_btn = QToolButton()
        self.log_toggle_btn.setText("Log Output")
        self.log_toggle_btn.setCheckable(True)
        self.log_toggle_btn.setChecked(False)
        self.log_toggle_btn.setArrowType(Qt.RightArrow)
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

        self.log_body.setVisible(False)

        splitter.addWidget(console_box)
        splitter.setChildrenCollapsible(False)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        top_h = top_content.sizeHint().height()
        log_h = max(180, int(top_h * 0.45))
        splitter.setSizes([top_h, log_h])
        root_layout.addWidget(splitter)

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
        self.gen_btn.setDefault(True)
        self.gen_btn.setAutoDefault(True)
        self.gen_btn.setMinimumWidth(110)

        actions_widget = QWidget()
        actions_layout = QHBoxLayout(actions_widget)
        actions_layout.setContentsMargins(8, 8, 8, 8)
        actions_layout.setSpacing(12)
        actions_layout.addWidget(self.save_defaults_btn)
        actions_layout.addWidget(self.load_defaults_btn)
        actions_layout.addSpacing(12)
        actions_layout.addWidget(self.gen_btn)
        actions_layout.addWidget(self.cancel_btn)

        root_layout.addWidget(actions_widget, alignment=Qt.AlignHCenter)

        self.folder_edit.textChanged.connect(self._check_required)
        self.out_edit.textChanged.connect(self._check_required)
        self.condition_combo.currentTextChanged.connect(self._on_condition_a_changed)
        self.condition_b_combo.currentTextChanged.connect(self._on_condition_b_changed)
        self.overlay_check.toggled.connect(self._check_required)
        self.scalp_title_a_edit.textChanged.connect(self._check_required)
        self.scalp_title_b_edit.textChanged.connect(self._check_required)
        self._toggle_scalp_controls(self.include_scalp_maps)
        self._check_required()

        self._toggle_log_panel(False)

    def _overlay_toggled(self, checked: bool) -> None:
        if checked:
            self._ensure_condition_a_valid_for_overlay()
            self._set_all_conditions_enabled(False)
            self._update_selector_columns(True)
            if self.group_box.isVisible():
                self.group_overlay_check.setChecked(False)
                self.group_overlay_check.setEnabled(False)
                self.group_list.setEnabled(False)
            self.title_edit.setEnabled(True)
            self.title_edit.clear()
            self.title_edit.setPlaceholderText(
                "Enter base chart name (e.g. Color Response vs Category Response)"
            )
        else:
            self._set_all_conditions_enabled(True)
            self._update_selector_columns(False)
            # Revert to auto-generation behavior when comparison mode is off
            self._update_chart_title_state(self.condition_combo.currentText())
            self.scalp_title_b_edit.clear()
            if self.group_box.isVisible():
                self.group_overlay_check.setEnabled(True)
                self.group_list.setEnabled(self.group_overlay_check.isChecked())
        self._update_scalp_title_b_visibility()
        self._update_scalp_title_warnings()
        self._update_legend_group_visibility()

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

    def _on_condition_a_changed(self, condition: str) -> None:
        self._update_chart_title_state(condition)
        if not (self._ui_initializing or self._populating_conditions):
            self.scalp_title_a_edit.clear()
        if self.legend_custom_check.isChecked() and self.overlay_check.isChecked():
            self._prefill_legend_defaults_if_empty()
        self._update_scalp_title_warnings()
        self._check_required()

    def _on_condition_b_changed(self, condition: str) -> None:
        _ = condition  # unused value required by signal signature
        if not (self._ui_initializing or self._populating_conditions):
            self.scalp_title_b_edit.clear()
        if self.legend_custom_check.isChecked() and self.overlay_check.isChecked():
            self._prefill_legend_defaults_if_empty()
        self._update_scalp_title_warnings()
        self._check_required()

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
        self._populating_conditions = True
        try:
            self._refresh_group_controls(folder)
            subfolders: list[str] = []
            try:
                subfolders = [
                    f.name
                    for f in Path(folder).iterdir()
                    if f.is_dir() and ".fif" not in f.name.lower()
                ]
            except Exception:
                subfolders = []

            with QSignalBlocker(self.condition_combo), QSignalBlocker(
                self.condition_b_combo
            ):
                self.condition_combo.clear()
                self.condition_b_combo.clear()
                if subfolders:
                    self.condition_combo.addItem(ALL_CONDITIONS_OPTION)
                    self.condition_combo.addItems(subfolders)
                    self.condition_b_combo.addItems(subfolders)
            if self.overlay_check.isChecked():
                self._ensure_condition_a_valid_for_overlay()
                self._set_all_conditions_enabled(False)
            else:
                self._set_all_conditions_enabled(True)
            # Default to "All Conditions" which auto-generates chart names
            self._update_chart_title_state(
                ALL_CONDITIONS_OPTION
                if subfolders
                else self.condition_combo.currentText()
            )
            self._update_scalp_title_warnings()
            self._check_required()
        finally:
            self._populating_conditions = False

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
                images = list(Path(out_dir).rglob("*.svg"))
            else:
                images = list(Path(out_dir).glob("*.svg"))
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
        log_context = {
            "operation": "snr_plot_generate",
            "project_root": str(self._project_root) if self._project_root else None,
            "compare_two_conditions": self.overlay_check.isChecked(),
            "custom_labels_enabled": self.legend_custom_check.isChecked(),
        }
        logger.info("SNR plot generation started.", extra=log_context)
        try:
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

            if include_scalp:
                if not self.scalp_title_a_edit.text().strip():
                    QMessageBox.warning(
                        self,
                        "Scalp Title",
                        "Please enter a scalp title for Condition A.",
                    )
                    return
                if (
                    self.overlay_check.isChecked()
                    and not self.scalp_title_b_edit.text().strip()
                ):
                    QMessageBox.warning(
                        self,
                        "Scalp Title",
                        "Please enter a scalp title for Condition B.",
                    )
                    return

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
                legend_payload = self._legend_settings_payload()
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
                    legend_custom_enabled=bool(legend_payload["custom_labels_enabled"]),
                    legend_condition_a=str(legend_payload["condition_a_label"]),
                    legend_condition_b=str(legend_payload["condition_b_label"]),
                    legend_a_peaks=str(legend_payload["a_peaks_label"]),
                    legend_b_peaks=str(legend_payload["b_peaks_label"]),
                    project_root=(
                        str(self._project_root) if self._project_root else None
                    ),
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
        except Exception as exc:
            self._append_log("SNR plot generation failed. See logs for details.")
            logger.error(
                "SNR plot generation failed.",
                exc_info=exc,
                extra=log_context,
            )
            self.gen_btn.setEnabled(True)
            self.cancel_btn.setEnabled(False)
            return

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
        if not self._scalp_titles_valid():
            required = False
        self._update_scalp_title_warnings()
        self.gen_btn.setEnabled(required)

    def _generation_finished(self) -> None:
        self._thread = None
        self._worker = None
        if self._conditions_queue:
            self._start_next_condition()
            return
        self._finish_all()
