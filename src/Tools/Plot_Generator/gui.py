"""GUI elements for the plot generator."""
from __future__ import annotations

import logging
import os
from pathlib import Path

from PySide6.QtCore import QPropertyAnimation, QThread
from PySide6.QtWidgets import (
    QFileDialog,
    QLabel,
    QMessageBox,
    QWidget,
)
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QColorDialog


from Main_App import SettingsManager
from Main_App.gui.components import apply_font_role
from Main_App.projects.project import Project
from Tools.Stats.data.shared_rois import load_rois_from_settings
from Tools.Plot_Generator.plot_settings import PlotSettingsManager
from Tools.Plot_Generator.gui_settings import (
    PlotGeneratorSettingsMixin,
    _project_plot_input_folder,
)
from Tools.Plot_Generator.generation_workflow import PlotGeneratorWorkflowMixin
from Tools.Plot_Generator.ui_sections import PlotGeneratorUiSectionsMixin
from Tools.Plot_Generator.settings_dialog import _SettingsDialog
from Tools.Plot_Generator.selection_state import (
    ALL_CONDITIONS_OPTION,  # noqa: F401 - re-exported by plot_generator.py
    PlotGeneratorSelectionMixin,
)
from Tools.Plot_Generator.project_paths import (
    EXCEL_SUBFOLDER_NAME,
    SNR_SUBFOLDER_NAME,
    _auto_detect_project_dir,
    _load_manifest,
    _resolve_project_subfolder,
)

logger = logging.getLogger(__name__)


class PlotGeneratorWindow(
    PlotGeneratorWorkflowMixin,
    PlotGeneratorUiSectionsMixin,
    PlotGeneratorSelectionMixin,
    PlotGeneratorSettingsMixin,
    QWidget,
):
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
        self._project_root: Path | None = None
        self._project: Project | None = None
        self._canonical_project_excel_root: Path | None = None


        project_dir_path: Path | None = None
        proj = getattr(parent, "currentProject", None)
        if project_dir and Path(project_dir).is_dir():
            project_dir_path = Path(project_dir)
        elif proj and hasattr(proj, "project_root"):
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
            self._project_root = Path(proj.project_root)
            if hasattr(proj, "manifest"):
                self._project = proj

        if project_dir_path is not None:
            self._project_root = project_dir_path
            if self._project is None:
                try:
                    self._project = Project.load(project_dir_path)
                except Exception as exc:
                    logger.warning(
                        "Failed to load project for SNR plot settings.",
                        exc_info=exc,
                        extra={
                            "operation": "snr_plot_project_load",
                            "project_root": str(project_dir_path),
                        },
                    )
            try:
                results_folder, subfolders = _load_manifest(project_dir_path)
                excel_root = _resolve_project_subfolder(
                    project_dir_path,
                    results_folder,
                    subfolders,
                    "excel",
                    EXCEL_SUBFOLDER_NAME,
                )
                self._canonical_project_excel_root = excel_root
                default_in = str(excel_root)
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
            project_settings = self._read_project_plot_settings()
            if project_settings:
                default_in = _project_plot_input_folder(
                    default_in,
                    project_settings,
                    self._project,
                )
                default_out = str(project_settings.get("output_folder") or default_out)
                self.stem_color = str(project_settings.get("stem_color") or self.stem_color)
                self.stem_color_b = str(project_settings.get("stem_color_b") or self.stem_color_b)
        else:
            main_default = mgr.get("paths", "output_folder", "")
            if not default_in:
                default_in = main_default
            if not default_out:
                default_out = main_default

        try:
            plot_x_max_default = str(
                float(mgr.get("analysis", "bca_upper_limit", "10.0"))
            )
        except Exception:
            plot_x_max_default = "10.0"

        self._defaults = {
            "title_snr": "SNR Plot",
            "xlabel": "Frequency (Hz)",
            "ylabel_snr": "SNR",
            "x_min": "0.0",
            "x_max": plot_x_max_default,
            "y_min_snr": "0.5",
            "y_max_snr": "3.0",
            "input_folder": default_in,
            "output_folder": default_out,
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

        self._thread: QThread | None = None
        self._worker: object | None = None
        self._generated_paths: list[str] = []
        self._failed_items: list[dict[str, str]] = []
        self._gen_params: (
            tuple[
                str,
                str,
                float,
                float,
                float,
                float,
                dict,
                dict[str, object],
            ]
            | None
        ) = None
        self._ui_initializing = False

    def _bold_label(self, text: str) -> QLabel:
        label = QLabel(text)
        apply_font_role(label, "caption")
        return label

    def _update_legend_group_visibility(self) -> None:
        self.legend_group.setVisible(True)
        group_overlay = self._group_overlay_enabled()
        show_b = self.overlay_check.isChecked() or group_overlay
        if group_overlay:
            self.legend_condition_a_label.setText("First group label:")
            self.legend_condition_b_label.setText("Second group label:")
        else:
            self.legend_condition_a_label.setText("Condition A label:")
            self.legend_condition_b_label.setText("Condition B label:")
        self.legend_condition_b_label.setVisible(show_b)
        self.legend_condition_b_edit.setVisible(show_b)
        self.legend_b_peaks_label.setVisible(show_b)
        self.legend_b_peaks_edit.setVisible(show_b)
        custom = self.legend_custom_check.isChecked()
        self.legend_condition_a_edit.setEnabled(custom)
        self.legend_a_peaks_edit.setEnabled(custom)
        self.legend_condition_b_edit.setEnabled(custom and show_b)
        self.legend_b_peaks_edit.setEnabled(custom and show_b)
        if custom:
            self._prefill_legend_defaults_if_empty()

    def _update_selector_columns(self, overlay_on: bool) -> None:
        if not hasattr(self, "_selectors_grid"):
            return
        _ = overlay_on
        self._selectors_grid.setColumnStretch(0, 1)
        self._selectors_grid.setColumnStretch(1, 1)
        self.condB_container.setVisible(overlay_on)

    def _select_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select Excel Folder")
        if folder:
            self.folder_edit.setText(folder)
            self._populate_conditions(folder)


    def _select_output(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if folder:
            self.out_edit.setText(folder)

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
            if hasattr(self, "_update_group_color_widgets"):
                self._update_group_color_widgets()
            if not self._persist_project_plot_settings(include_paths=False):
                self.plot_mgr.save()

    def _save_defaults(self) -> None:
        if self._persist_project_plot_settings(include_paths=True):
            QMessageBox.information(self, "Defaults", "Project plot defaults saved.")
            return
        self.plot_mgr.set("paths", "input_folder", self.folder_edit.text())
        self.plot_mgr.set("paths", "output_folder", self.out_edit.text())
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
        # Update the chart title field based on the current condition
        self._update_chart_title_state(self.condition_combo.currentText())
        QMessageBox.information(self, "Defaults", "Settings reset to defaults.")

    def _open_settings(self) -> None:
        dlg = _SettingsDialog(self, self.stem_color, self.stem_color_b)
        if dlg.exec():
            self.stem_color, self.stem_color_b = dlg.selected_colors()
            self.plot_mgr.set_stem_color(self.stem_color)
            self.plot_mgr.set_second_color(self.stem_color_b)
            if not self._persist_project_plot_settings(include_paths=False):
                self.plot_mgr.save()

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
