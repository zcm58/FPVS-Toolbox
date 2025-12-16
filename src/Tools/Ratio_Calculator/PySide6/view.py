from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

import pandas as pd
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QProgressBar,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from Tools.Ratio_Calculator.PySide6.model import RatioCalcInputs, RatioCalcResult


class RatioCalculatorWindow(QMainWindow):
    compute_requested = Signal(RatioCalcInputs)
    excel_root_changed = Signal(Path)

    def __init__(self, parent: QWidget | None = None, project_root: Path | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Ratio Calculator")
        self._project_root = project_root or Path(os.environ.get("FPVS_PROJECT_ROOT", Path.cwd()))
        self._busy = False
        self._last_df: pd.DataFrame | None = None

        central = QWidget(self)
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        layout.addWidget(self._build_input_group())
        layout.addWidget(self._build_params_group())
        layout.addWidget(self._build_advanced_group())
        layout.addWidget(self._build_output_group())

        self.progress = QProgressBar(self)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        layout.addWidget(self._build_log_group())

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.compute_btn = QPushButton("Compute", self)
        self.compute_btn.clicked.connect(self._on_compute)
        btn_row.addWidget(self.compute_btn)
        layout.addLayout(btn_row)

        self.statusBar().showMessage("Ready")

    def _build_input_group(self) -> QGroupBox:
        group = QGroupBox("Excel Root", self)
        form = QFormLayout(group)
        form.setLabelAlignment(Qt.AlignLeft)

        self.excel_path_edit = QLineEdit(str(self._project_root))
        self.excel_path_edit.setReadOnly(True)
        self.excel_browse_btn = QPushButton("Browse…", group)
        self.excel_browse_btn.clicked.connect(self._select_excel_root)

        row = QHBoxLayout()
        row.addWidget(self.excel_path_edit)
        row.addWidget(self.excel_browse_btn)
        form.addRow(QLabel("Excel folder:"), row)
        return group

    def _build_params_group(self) -> QGroupBox:
        group = QGroupBox("Parameters", self)
        form = QFormLayout(group)
        form.setLabelAlignment(Qt.AlignLeft)

        self.cond_a_combo = QComboBox(group)
        self.cond_b_combo = QComboBox(group)
        form.addRow(QLabel("Condition A (numerator):"), self.cond_a_combo)
        form.addRow(QLabel("Condition B (denominator):"), self.cond_b_combo)

        self.roi_combo = QComboBox(group)
        form.addRow(QLabel("ROI:"), self.roi_combo)

        return group

    def _build_advanced_group(self) -> QGroupBox:
        group = QGroupBox("Advanced", self)
        form = QFormLayout(group)
        form.setLabelAlignment(Qt.AlignLeft)

        self.threshold_spin = QDoubleSpinBox(group)
        self.threshold_spin.setDecimals(2)
        self.threshold_spin.setRange(0.0, 10.0)
        self.threshold_spin.setSingleStep(0.01)
        self.threshold_spin.setValue(1.64)
        self.threshold_spin.setEnabled(False)
        form.addRow(QLabel("Z-score threshold:"), self.threshold_spin)
        return group

    def _build_output_group(self) -> QGroupBox:
        group = QGroupBox("Output", self)
        form = QFormLayout(group)
        form.setLabelAlignment(Qt.AlignLeft)

        self.output_edit = QLineEdit(str(self._default_output_path()))
        self.output_edit.setReadOnly(True)
        self.output_browse_btn = QPushButton("Browse…", group)
        self.output_browse_btn.clicked.connect(self._select_output_file)

        row = QHBoxLayout()
        row.addWidget(self.output_edit)
        row.addWidget(self.output_browse_btn)
        form.addRow(QLabel("Output Excel:"), row)
        return group

    def _build_log_group(self) -> QGroupBox:
        group = QGroupBox("Logs", self)
        group.setCheckable(True)
        group.setChecked(True)
        layout = QVBoxLayout(group)
        self.log_view = QTextEdit(group)
        self.log_view.setReadOnly(True)
        layout.addWidget(self.log_view)

        def _toggle(checked: bool) -> None:
            self.log_view.setVisible(checked)

        group.toggled.connect(_toggle)
        return group

    def _default_output_path(self) -> Path:
        return self._project_root / "ratio_results.xlsx"

    # View API for controller -------------------------------------------------
    def set_conditions(self, conditions: Iterable[str]) -> None:
        self.cond_a_combo.blockSignals(True)
        self.cond_b_combo.blockSignals(True)
        self.cond_a_combo.clear()
        self.cond_b_combo.clear()
        for cond in conditions:
            self.cond_a_combo.addItem(cond)
            self.cond_b_combo.addItem(cond)
        self.cond_a_combo.blockSignals(False)
        self.cond_b_combo.blockSignals(False)

    def set_rois(self, rois: Iterable[str]) -> None:
        self.roi_combo.blockSignals(True)
        self.roi_combo.clear()
        for roi in rois:
            self.roi_combo.addItem(roi)
        self.roi_combo.blockSignals(False)

    def append_log(self, message: str) -> None:
        self.log_view.append(message)
        self.statusBar().showMessage(message, 5000)

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        for widget in (
            self.excel_path_edit,
            self.excel_browse_btn,
            self.cond_a_combo,
            self.cond_b_combo,
            self.roi_combo,
            self.output_edit,
            self.output_browse_btn,
            self.compute_btn,
        ):
            widget.setEnabled(not busy)
        self.progress.setVisible(busy or self.progress.value() > 0)

    def set_progress(self, value: int) -> None:
        self.progress.setValue(value)

    def status_message(self, message: str) -> None:
        self.statusBar().showMessage(message, 5000)
        self.append_log(message)

    def handle_result(self, result: RatioCalcResult) -> None:
        self._last_df = result.dataframe
        self.append_log(f"Saved results to {result.output_path}")
        self.statusBar().showMessage("Completed", 3000)

    # UI events --------------------------------------------------------------
    def _select_excel_root(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self,
            "Select Excel root",
            str(self._project_root),
            options=QFileDialog.ShowDirsOnly,
        )
        if not directory:
            return
        self.excel_path_edit.setText(directory)
        self.output_edit.setText(str(Path(directory) / "ratio_results.xlsx"))
        self.excel_root_changed.emit(Path(directory))

    def _select_output_file(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save output Excel",
            str(self._default_output_path()),
            "Excel Files (*.xlsx)",
        )
        if not path:
            return
        self.output_edit.setText(path)

    def _on_compute(self) -> None:
        if self._busy:
            self.append_log("A computation is already running.")
            return
        excel_root = Path(self.excel_path_edit.text())
        if not excel_root.exists():
            self.append_log("Please select a valid Excel root folder.")
            return
        cond_a = self.cond_a_combo.currentText()
        cond_b = self.cond_b_combo.currentText()
        if not cond_a or not cond_b or cond_a == cond_b:
            self.append_log("Please select two different conditions.")
            return
        roi_name = self.roi_combo.currentText() or None
        threshold = float(self.threshold_spin.value())
        output_path = Path(self.output_edit.text())
        inputs = RatioCalcInputs(
            excel_root=excel_root,
            cond_a=cond_a,
            cond_b=cond_b,
            roi_name=roi_name,
            z_threshold=threshold,
            output_path=output_path,
        )
        self.compute_requested.emit(inputs)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._busy:
            event.ignore()
            self.append_log("Cannot close while computation is running.")
            return
        super().closeEvent(event)
