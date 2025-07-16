"""GUI elements for the plot generator."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QThread, QPropertyAnimation
from PySide6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QComboBox,
    QPlainTextEdit,
    QProgressBar,
    QWidget,
    QMenuBar,
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
)
from PySide6.QtGui import QAction, QDoubleValidator, QColor
from PySide6.QtWidgets import QColorDialog


from Tools.Stats.stats_helpers import load_rois_from_settings
from Tools.Stats.stats_analysis import ALL_ROIS_OPTION
from Main_App.settings_manager import SettingsManager
from Tools.Plot_Generator.plot_settings import PlotSettingsManager
from .worker import _Worker

ALL_CONDITIONS_OPTION = "All Conditions"

class _SettingsDialog(QDialog):
    """Dialog for configuring plot options."""

    def __init__(self, parent: QWidget, color: str) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        row.addWidget(QLabel("Stem Plot Line Color:"))
        self.combo = QComboBox()
        self.combo.addItems(["Red", "Blue", "Green", "Purple"])
        self.combo.setCurrentText(color.capitalize())
        row.addWidget(self.combo)
        self.custom_color: str | None = None
        pick = QPushButton("Custom…")
        pick.clicked.connect(self._choose_custom)
        row.addWidget(pick)
        layout.addLayout(row)
        btns = QHBoxLayout()
        ok = QPushButton("OK")
        ok.clicked.connect(self.accept)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        btns.addWidget(ok)
        btns.addWidget(cancel)
        layout.addLayout(btns)

    def _choose_custom(self) -> None:
        color = QColorDialog.getColor(QColor(self.combo.currentText()), self)
        if color.isValid():
            self.custom_color = color.name()

    def selected_color(self) -> str:
        if self.custom_color:
            return self.custom_color
        return self.combo.currentText().lower()

class PlotGeneratorWindow(QWidget):
    """Main window for generating plots."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Generate Plots")
        self.roi_map = load_rois_from_settings()

        mgr = SettingsManager()
        self.plot_mgr = PlotSettingsManager()
        default_in = self.plot_mgr.get("paths", "input_folder", "")
        default_out = self.plot_mgr.get("paths", "output_folder", "")
        self.stem_color = self.plot_mgr.get_stem_color()
        main_default = mgr.get("paths", "output_folder", "")
        if not default_in:
            default_in = main_default
        if not default_out:
            default_out = main_default
        self._defaults = {
            "title_snr": "SNR Plot",
            "title_bca": "BCA Plot",
            "xlabel": "Frequency (Hz)",
            "ylabel_snr": "SNR",
            "ylabel_bca": "Baseline-corrected amplitude (µV)",
            "x_min": "0.0",
            "x_max": "10.0",
            "y_min_snr": "0.0",
            "y_max_snr": "3.0",
            "y_min_bca": "0.0",
            "y_max_bca": "0.3",
            "input_folder": default_in,
            "output_folder": default_out,
        }
        self._orig_defaults = self._defaults.copy()
        self._conditions_queue: list[str] = []
        self._total_conditions = 0
        self._current_condition = 0

        self._build_ui()
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
        self._gen_params: tuple[str, str, float, float, float, float] | None = None

    def _build_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        menu = QMenuBar()
        menu.setNativeMenuBar(False)
        menu.setStyleSheet(
            "QMenuBar {background-color: #e0e0e0;}"
            "QMenuBar::item {padding: 2px 8px; background: transparent;}"
            "QMenuBar::item:selected {background: #d5d5d5;}"
        )
        action = QAction("Settings", self)
        action.triggered.connect(self._open_settings)
        menu.addAction(action)
        root_layout.addWidget(menu)

        layout = QGridLayout()
        root_layout.addLayout(layout)
        row = 0
        layout.addWidget(QLabel("Excel Files Folder:"), row, 0)
        self.folder_edit = QLineEdit()
        self.folder_edit.setReadOnly(True)

        self.folder_edit.setText(self._defaults.get("input_folder", ""))

        layout.addWidget(self.folder_edit, row, 1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._select_folder)
        layout.addWidget(browse, row, 2)
        row += 1


        layout.addWidget(QLabel("Save Plots To:"), row, 0)
        self.out_edit = QLineEdit()
        self.out_edit.setReadOnly(True)
        self.out_edit.setText(self._defaults.get("output_folder", ""))

        layout.addWidget(self.out_edit, row, 1)
        browse_out = QPushButton("Browse…")
        browse_out.clicked.connect(self._select_output)
        layout.addWidget(browse_out, row, 2)
        open_out = QPushButton("Open…")
        open_out.clicked.connect(self._open_output_folder)
        layout.addWidget(open_out, row, 3)
        row += 1


        layout.addWidget(QLabel("Condition:"), row, 0)
        self.condition_combo = QComboBox()
        self.condition_combo.currentTextChanged.connect(self._condition_changed)
        layout.addWidget(self.condition_combo, row, 1, 1, 2)
        row += 1

        layout.addWidget(QLabel("Metric:"), row, 0)
        self.metric_combo = QComboBox()
        self.metric_combo.addItems(["SNR", "BCA"])
        self.metric_combo.currentTextChanged.connect(self._metric_changed)
        layout.addWidget(self.metric_combo, row, 1, 1, 2)
        row += 1

        layout.addWidget(QLabel("ROI:"), row, 0)
        self.roi_combo = QComboBox()
        self.roi_combo.addItems([ALL_ROIS_OPTION] + list(self.roi_map.keys()))
        layout.addWidget(self.roi_combo, row, 1, 1, 2)
        row += 1


        layout.addWidget(QLabel("Chart title:"), row, 0)
        self.title_edit = QLineEdit(self._defaults["title_snr"])
        layout.addWidget(self.title_edit, row, 1, 1, 2)
        row += 1

        layout.addWidget(QLabel("X-axis label:"), row, 0)
        self.xlabel_edit = QLineEdit(self._defaults["xlabel"])
        layout.addWidget(self.xlabel_edit, row, 1, 1, 2)
        row += 1

        layout.addWidget(QLabel("Y-axis label:"), row, 0)
        self.ylabel_edit = QLineEdit(self._defaults["ylabel_snr"])
        layout.addWidget(self.ylabel_edit, row, 1, 1, 2)
        row += 1


        layout.addWidget(QLabel("X min:"), row, 0)
        self.xmin_edit = QLineEdit(self._defaults["x_min"])
        self.xmin_edit.setValidator(QDoubleValidator())
        layout.addWidget(self.xmin_edit, row, 1)
        layout.addWidget(QLabel("X max:"), row, 2)
        self.xmax_edit = QLineEdit(self._defaults["x_max"])
        self.xmax_edit.setValidator(QDoubleValidator())
        layout.addWidget(self.xmax_edit, row, 3)
        row += 1

        layout.addWidget(QLabel("Y min:"), row, 0)
        self.ymin_edit = QLineEdit(self._defaults["y_min_snr"])
        self.ymin_edit.setValidator(QDoubleValidator())
        layout.addWidget(self.ymin_edit, row, 1)
        layout.addWidget(QLabel("Y max:"), row, 2)
        self.ymax_edit = QLineEdit(self._defaults["y_max_snr"])
        self.ymax_edit.setValidator(QDoubleValidator())
        layout.addWidget(self.ymax_edit, row, 3)
        row += 1

        self.apply_btn = QPushButton("Apply Settings")
        self.apply_btn.clicked.connect(self._apply_settings)
        layout.addWidget(self.apply_btn, row, 0)
        self.save_defaults_btn = QPushButton("Save Defaults")
        self.save_defaults_btn.clicked.connect(self._save_defaults)
        layout.addWidget(self.save_defaults_btn, row, 1)
        self.load_defaults_btn = QPushButton("Load Defaults")
        self.load_defaults_btn.clicked.connect(self._load_defaults)
        layout.addWidget(self.load_defaults_btn, row, 2)
        self.gen_btn = QPushButton("Generate")
        self.gen_btn.clicked.connect(self._generate)
        layout.addWidget(self.gen_btn, row, 3)
        row += 1
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel_generation)
        layout.addWidget(self.cancel_btn, row, 0)
        row += 1

        self.progress_bar = QProgressBar()
        # Windows 11 green accent color for the progress bar
        self.progress_bar.setStyleSheet(
            "QProgressBar::chunk {background-color: #16C60C;}"
        )
        layout.addWidget(self.progress_bar, row, 0, 1, 4)
        row += 1

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        layout.addWidget(self.log, row, 0, 1, 4)

    def _metric_changed(self, metric: str) -> None:
        if metric == "SNR":
            self.ylabel_edit.setText(self._defaults["ylabel_snr"])
            self.ymin_edit.setText(self._defaults["y_min_snr"])
            self.ymax_edit.setText(self._defaults["y_max_snr"])
        else:
            self.ylabel_edit.setText(self._defaults["ylabel_bca"])
            self.ymin_edit.setText(self._defaults["y_min_bca"])
            self.ymax_edit.setText(self._defaults["y_max_bca"])

    def _select_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select Excel Folder")
        if folder:
            self.folder_edit.setText(folder)
            self._populate_conditions(folder)


    def _select_output(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if folder:
            self.out_edit.setText(folder)

    def _condition_changed(self, condition: str) -> None:
        if condition:
            self.title_edit.setText(condition)

    def _populate_conditions(self, folder: str) -> None:
        self.condition_combo.clear()
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
            self._condition_changed(subfolders[0])

    def _apply_settings(self) -> None:
        metric = self.metric_combo.currentText()
        if metric == "SNR":
            self._defaults["title_snr"] = self.title_edit.text()
            self._defaults["ylabel_snr"] = self.ylabel_edit.text()
            self._defaults["y_min_snr"] = self.ymin_edit.text()
            self._defaults["y_max_snr"] = self.ymax_edit.text()
        else:
            self._defaults["title_bca"] = self.title_edit.text()
            self._defaults["ylabel_bca"] = self.ylabel_edit.text()
            self._defaults["y_min_bca"] = self.ymin_edit.text()
            self._defaults["y_max_bca"] = self.ymax_edit.text()

        self._defaults["xlabel"] = self.xlabel_edit.text()
        self._defaults["x_min"] = self.xmin_edit.text()
        self._defaults["x_max"] = self.xmax_edit.text()

        self._defaults["input_folder"] = self.folder_edit.text()
        self._defaults["output_folder"] = self.out_edit.text()

        QMessageBox.information(self, "Settings", "New settings have been applied.")

    def _save_defaults(self) -> None:
        self.plot_mgr.set("paths", "input_folder", self.folder_edit.text())
        self.plot_mgr.set("paths", "output_folder", self.out_edit.text())
        self.plot_mgr.save()
        QMessageBox.information(self, "Defaults", "Default folders saved.")

    def _load_defaults(self) -> None:
        self._defaults = self._orig_defaults.copy()
        metric = self.metric_combo.currentText()
        self.folder_edit.setText(self._defaults["input_folder"])
        self.out_edit.setText(self._defaults["output_folder"])
        self._populate_conditions(self._defaults["input_folder"])
        self.xlabel_edit.setText(self._defaults["xlabel"])
        self.xmin_edit.setText(self._defaults["x_min"])
        self.xmax_edit.setText(self._defaults["x_max"])
        if metric == "SNR":
            self.title_edit.setText(self._defaults["title_snr"])
            self.ylabel_edit.setText(self._defaults["ylabel_snr"])
            self.ymin_edit.setText(self._defaults["y_min_snr"])
            self.ymax_edit.setText(self._defaults["y_max_snr"])
        else:
            self.title_edit.setText(self._defaults["title_bca"])
            self.ylabel_edit.setText(self._defaults["ylabel_bca"])
            self.ymin_edit.setText(self._defaults["y_min_bca"])
            self.ymax_edit.setText(self._defaults["y_max_bca"])
        QMessageBox.information(self, "Defaults", "Settings reset to defaults.")

    def _append_log(self, text: str) -> None:
        self.log.appendPlainText(text)
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
        folder, out_dir, x_min, x_max, y_min, y_max = self._gen_params
        condition = self._conditions_queue.pop(0)
        self._current_condition = self._total_conditions - len(self._conditions_queue)
        self._thread = QThread()
        self._worker = _Worker(
            folder,
            condition,
            self.metric_combo.currentText(),
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
            x_min = float(self.xmin_edit.text())
            x_max = float(self.xmax_edit.text())
            y_min = float(self.ymin_edit.text())
            y_max = float(self.ymax_edit.text())
        except ValueError:
            QMessageBox.critical(self, "Error", "Invalid axis limits.")
            return

        self.gen_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.log.clear()
        self._animate_progress_to(0)
        if self.condition_combo.currentText() == ALL_CONDITIONS_OPTION:
            self._conditions_queue = [
                self.condition_combo.itemText(i)
                for i in range(1, self.condition_combo.count())
            ]
        else:
            self._conditions_queue = [self.condition_combo.currentText()]
        self._total_conditions = len(self._conditions_queue)
        self._current_condition = 0
        self._gen_params = (folder, out_dir, x_min, x_max, y_min, y_max)
        self._start_next_condition()

    def _open_settings(self) -> None:
        dlg = _SettingsDialog(self, self.stem_color)
        if dlg.exec():
            self.stem_color = dlg.selected_color()
            self.plot_mgr.set_stem_color(self.stem_color)
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

    def _generation_finished(self) -> None:
        self._thread = None
        self._worker = None
        if self._conditions_queue:
            self._start_next_condition()
            return
        self._finish_all()
