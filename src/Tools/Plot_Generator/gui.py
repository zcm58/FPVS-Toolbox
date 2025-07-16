"""GUI elements for the plot generator."""
from __future__ import annotations

import os
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
    QWidget,
    QMenuBar,
    QDialog,
    QGridLayout,
    QVBoxLayout,
    QHBoxLayout,
    QDoubleSpinBox,
    QCheckBox,
    QStyle,
    QSizePolicy,
)
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import QColorDialog


from Tools.Stats.stats_helpers import load_rois_from_settings
from Tools.Stats.stats_analysis import ALL_ROIS_OPTION
from Main_App.settings_manager import SettingsManager
from Tools.Plot_Generator.plot_settings import PlotSettingsManager
from .worker import _Worker

ALL_CONDITIONS_OPTION = "All Conditions"

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

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Generate SNR Plots")
        self.roi_map = load_rois_from_settings()

        mgr = SettingsManager()
        self.plot_mgr = PlotSettingsManager()
        default_in = self.plot_mgr.get("paths", "input_folder", "")
        default_out = self.plot_mgr.get("paths", "output_folder", "")
        self.stem_color = self.plot_mgr.get_stem_color()
        self.stem_color_b = self.plot_mgr.get_second_color()
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
        }
        self._orig_defaults = self._defaults.copy()
        self._conditions_queue: list[str] = []
        self._total_conditions = 0
        self._current_condition = 0

        self._all_conditions = False


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

    def _bold_label(self, text: str) -> QLabel:
        label = QLabel(text)
        font = label.font()
        font.setBold(True)
        label.setFont(font)
        return label

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

        top_widget = QWidget()
        grid = QGridLayout(top_widget)
        grid.setSpacing(8)
        grid.setContentsMargins(10, 10, 10, 10)

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
        params_form.addRow("Condition:", self.condition_combo)

        self.overlay_check = QCheckBox("Overlay Comparison")
        self.overlay_check.toggled.connect(self._overlay_toggled)
        params_form.addRow("", self.overlay_check)

        self.condition_b_combo = QComboBox()
        self.condition_b_combo.setToolTip("Select second condition")
        params_form.addRow("Condition B:", self.condition_b_combo)
        self.condition_b_combo.hide()



        self.roi_combo = QComboBox()
        self.roi_combo.addItems([ALL_ROIS_OPTION] + list(self.roi_map.keys()))
        self.roi_combo.setToolTip("Select the region of interest")
        params_form.addRow(QLabel("ROI:"), self.roi_combo)

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

        grid.addWidget(file_box, 0, 0)
        grid.addWidget(params_box, 0, 1)
        grid.addWidget(ranges_box, 1, 0)
        grid.addWidget(actions_box, 1, 1)
        grid.setColumnStretch(0, 2)
        grid.setColumnStretch(1, 1)

        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(top_widget)

        console_box = QGroupBox()
        self._style_box(console_box)
        console_layout = QVBoxLayout(console_box)
        console_layout.setContentsMargins(10, 10, 10, 10)
        console_layout.setSpacing(8)

        header = QHBoxLayout()
        header.setContentsMargins(10, 10, 10, 10)
        header.setSpacing(8)
        label = self._bold_label("Log Output")
        label.setStyleSheet("color: gray;")
        header.addWidget(label)
        header.addStretch()
        clear_btn = QPushButton()
        clear_btn.setIcon(self.style().standardIcon(QStyle.SP_TrashIcon))
        clear_btn.setFixedSize(22, 22)
        clear_btn.setToolTip("Clear Log")
        clear_btn.clicked.connect(lambda: self.log.clear())
        header.addWidget(clear_btn)
        console_layout.addLayout(header)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        font = self.log.font()
        font.setBold(False)
        self.log.setFont(font)
        console_layout.addWidget(self.log)

        splitter.addWidget(console_box)
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
        self.condition_b_combo.setVisible(checked)
        if checked:
            self.title_edit.setEnabled(True)
            self.title_edit.clear()
            self.title_edit.setPlaceholderText(
                "Enter base chart name (e.g. Color Response vs Category Response)"
            )
        else:
            # Revert to auto-generation behavior when comparison mode is off
            self._update_chart_title_state(self.condition_combo.currentText())

    def _select_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select Excel Folder")
        if folder:
            self.folder_edit.setText(folder)
            self._populate_conditions(folder)


    def _select_output(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if folder:
            self.out_edit.setText(folder)

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
        folder, out_dir, x_min, x_max, y_min, y_max = self._gen_params
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
            self._gen_params = (folder, out_dir, x_min, x_max, y_min, y_max)
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
        self.gen_btn.setEnabled(required)

    def _generation_finished(self) -> None:
        self._thread = None
        self._worker = None
        if self._conditions_queue:
            self._start_next_condition()
            return
        self._finish_all()
